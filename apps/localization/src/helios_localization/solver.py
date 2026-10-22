"""Robust nonlinear range correction with a constant-velocity Gaussian prior.

The range covariance includes the correlated error from the shared height input.
Huber applies to whitened range residuals only; the motion prior stays quadratic.
"""

import math

import numpy as np
from scipy.optimize import least_squares

from .frames import body_to_enu
from .measurements import Estimate
from .models import Position


def matrix_tuple(value):
    return tuple(tuple(float(v) for v in row) for row in value)


class Estimator:
    def __init__(self, settings):
        self.settings = settings
        self.reset()

    def reset(self):
        self.state = self.covariance = None
        self.at = self.measurement_at = self.aircraft = None
        self.session = ""
        self.controller_session = None
        self.sequence = -1
        self.timing_sigma = 0.0
        self.height_cross = np.zeros(4)
        self.generation = 0

    def invalid(self, at, reason):
        return Estimate(
            "invalid",
            self.session or "uninitialized",
            self.settings.frame,
            at,
            self.measurement_at,
            reason=reason,
        )

    def propagate(self, at):
        dt = at - self.at
        if dt < 0:
            raise ValueError("Time moved backwards")
        transition = np.eye(4)
        transition[0, 2] = transition[1, 3] = dt
        drive = np.array([[dt**2 / 2, 0], [0, dt**2 / 2], [dt, 0], [0, dt]])
        process = drive @ drive.T * self.settings.acceleration_sigma**2
        return transition @ self.state, transition @ self.covariance @ transition.T + process

    def output(self, kind, at, state, covariance, aircraft, rms=None):
        if math.sqrt(np.linalg.eigvalsh(covariance[:2, :2]).max()) > self.settings.max_sigma:
            self.state = None
            return self.invalid(at, "horizontal_uncertainty")
        position_covariance = np.zeros((3, 3))
        position_covariance[:2, :2] = covariance[:2, :2]
        position_covariance[2, 2] = aircraft.z_sigma**2
        cross = self.height_cross[:2].copy()
        if kind == "predicted":
            cross += (at - self.at) * self.height_cross[2:]
        position_covariance[:2, 2] = cross
        position_covariance[2, :2] = cross
        return Estimate(
            kind,
            f"{self.session}:{self.controller_session}:{self.generation}",
            self.settings.frame,
            at,
            self.measurement_at,
            Position(float(state[0]), float(state[1]), aircraft.z),
            matrix_tuple(position_covariance),
            matrix_tuple(covariance),
            residual_rms=rms,
            timing_sigma=self.timing_sigma,
        )

    def predict(self, at):
        if self.state is None:
            return self.invalid(at, "not_initialized")
        if at < self.at:
            return self.invalid(at, "time_reversal")
        if at - self.measurement_at > self.settings.prediction_limit + 1e-9:
            self.state = None
            return self.invalid(at, "prediction_expired")
        if at - self.aircraft.acquired_at + self.aircraft.timing_sigma > self.settings.max_age:
            self.state = None
            return self.invalid(at, "altitude_stale")
        state, covariance = self.propagate(at)
        return self.output("predicted", at, state, covariance, self.aircraft)

    def correct(self, epoch, aircraft):
        cfg = self.settings
        now = epoch.received_at
        if epoch.frame != cfg.frame:
            self.reset()
            return self.invalid(now, "frame_mismatch")
        if epoch.session != self.session or (
            aircraft is not None and aircraft.session != self.controller_session
        ):
            self.reset()
            self.session = epoch.session
            self.controller_session = aircraft.session if aircraft else None
        if epoch.sequence <= self.sequence:
            return self.invalid(now, "duplicate_epoch")
        self.sequence = epoch.sequence
        if self.at is not None and epoch.acquired_at <= self.at:
            return self.invalid(now, "out_of_order_epoch")
        if aircraft is None:
            self.state = None
            return self.invalid(now, "altitude_unavailable")
        values = [
            epoch.acquired_at,
            now,
            epoch.timing_sigma,
            aircraft.acquired_at,
            aircraft.received_at,
            aircraft.timing_sigma,
            aircraft.z,
            aircraft.z_sigma,
            aircraft.roll,
            aircraft.pitch,
            aircraft.yaw,
        ]
        if (
            not all(math.isfinite(v) for v in values)
            or min(epoch.timing_sigma, aircraft.timing_sigma, aircraft.z_sigma) < 0
            or aircraft.z_sigma == 0
        ):
            self.state = None
            return self.invalid(now, "invalid_sensor_sample")
        if (
            epoch.acquired_at > now
            or aircraft.acquired_at > now
            or now - epoch.acquired_at + epoch.timing_sigma > cfg.max_age
            or now - aircraft.acquired_at + aircraft.timing_sigma > cfg.max_age
            or abs(epoch.acquired_at - aircraft.acquired_at)
            + epoch.timing_sigma
            + aircraft.timing_sigma
            > cfg.max_skew
        ):
            self.state = None
            return self.invalid(now, "sensor_timing")
        if self.at is not None and epoch.acquired_at - self.measurement_at > cfg.prediction_limit:
            self.state = None
        selected = [
            a
            for a in cfg.anchors
            if a.id in epoch.ranges
            and type(epoch.ranges[a.id]) in (int, float)
            and math.isfinite(epoch.ranges[a.id])
            and epoch.ranges[a.id] > 0
        ]
        if len(selected) < 4:
            return self.invalid(now, "four_ranges_required")
        anchors = np.array([a.xyz for a in selected])
        ranges = np.array([epoch.ranges[a.id] - a.bias for a in selected])
        offset = body_to_enu(aircraft.roll, aircraft.pitch, aircraft.yaw) @ cfg.tag_offset_frd
        z_tag = aircraft.z + offset[2]
        if np.any(ranges <= 0) or np.any(
            ranges + cfg.gate_sigma * np.array([a.sigma for a in selected])
            < np.abs(z_tag - anchors[:, 2])
        ):
            return self.invalid(now, "impossible_range")
        prior = self.propagate(epoch.acquired_at) if self.state is not None else None
        seed = prior[0] if prior else np.r_[anchors[:, :2].mean(axis=0) - offset[:2], 0.0, 0.0]

        def geometry(state):
            delta = np.c_[state[:2] + offset[:2] - anchors[:, :2], z_tag - anchors[:, 2]]
            distance = np.maximum(np.linalg.norm(delta, axis=1), 1e-9)
            return distance, delta[:, :2] / distance[:, None], delta[:, 2] / distance

        _, _, dz = geometry(seed)
        # Height is one shared random variable, not independent noise per anchor.
        noise = np.diag([a.sigma**2 for a in selected]) + np.outer(dz, dz) * aircraft.z_sigma**2
        noise += np.eye(len(selected)) * (cfg.max_speed * epoch.timing_sigma) ** 2
        whitening = np.linalg.solve(np.linalg.cholesky(noise), np.eye(len(selected)))

        def retain(mask):
            nonlocal selected, anchors, ranges, noise, whitening
            selected = [a for a, keep in zip(selected, mask, strict=True) if keep]
            anchors, ranges = anchors[mask], ranges[mask]
            noise = noise[np.ix_(mask, mask)]
            whitening = np.linalg.solve(np.linalg.cholesky(noise), np.eye(len(selected)))

        prior_white = None
        if prior:
            prior_white = np.linalg.solve(np.linalg.cholesky(prior[1]), np.eye(4))
            distances, jac, _ = geometry(seed)
            innovation_sigma = np.sqrt(np.diag(noise) + np.diag(jac @ prior[1][:2, :2] @ jac.T))
            keep = np.abs(distances - ranges) <= cfg.gate_sigma * innovation_sigma
            if not np.all(keep):
                if np.count_nonzero(keep) < 4:
                    return self.invalid(now, "innovation_gate")
                retain(keep)

        def residual(state):
            measured = whitening @ (geometry(state)[0] - ranges)
            return np.r_[measured, prior_white @ (state - prior[0])] if prior else measured

        def loss(squared):
            # scipy custom loss allows robust ranges and a strictly quadratic prior.
            result = np.vstack((squared.copy(), np.ones_like(squared), np.zeros_like(squared)))
            indexes = np.flatnonzero(squared[: len(selected)] > cfg.huber_scale**2)
            root = np.sqrt(squared[indexes])
            result[0, indexes] = 2 * cfg.huber_scale * root - cfg.huber_scale**2
            result[1, indexes] = cfg.huber_scale / root
            result[2, indexes] = -cfg.huber_scale / (2 * root**3)
            return result

        try:
            for _ in range(len(selected) - 3):
                fit = least_squares(residual, seed, loss=loss, max_nfev=150)
                if not fit.success or not np.all(np.isfinite(fit.x)):
                    return self.invalid(now, "solver_failed")
                distance, jac, dz = geometry(fit.x)
                error = distance - ranges
                keep = np.abs(error) <= cfg.gate_sigma * np.sqrt(np.diag(noise))
                if np.all(keep):
                    break
                if np.count_nonzero(keep) < 4:
                    return self.invalid(now, "range_residual_gate")
                retain(keep)
                seed = fit.x
            singular = np.linalg.svd(whitening @ jac, compute_uv=False)
            if singular[-1] <= 1e-6 or singular[0] / singular[-1] > cfg.max_condition:
                return self.invalid(now, "poor_geometry")
            if np.linalg.norm(fit.x[2:]) > cfg.max_speed:
                return self.invalid(now, "speed_gate")
            if prior and np.linalg.norm(fit.x[:2] - self.state[:2]) > (
                cfg.max_speed * (epoch.acquired_at - self.at)
                + cfg.gate_sigma * math.sqrt(np.linalg.eigvalsh(prior[1][:2, :2]).max())
            ):
                return self.invalid(now, "position_jump")
            if prior:
                covariance = np.linalg.inv(fit.jac.T @ fit.jac)
            else:
                covariance = np.zeros((4, 4))
                covariance[:2, :2] = np.linalg.inv(fit.jac[:, :2].T @ fit.jac[:, :2])
                covariance[2:, 2:] = np.eye(2) * cfg.initial_velocity_sigma**2
            # Never shrink uncertainty when residuals exceed the assumed noise model.
            covariance *= max(1.0, float(np.mean((whitening @ error) ** 2)))
        except ValueError, np.linalg.LinAlgError:
            return self.invalid(now, "solver_failed")
        if prior is None:
            self.generation += 1
        sensitivity = np.zeros((len(selected), 4))
        sensitivity[:, :2] = jac
        # Use the unrobust linearized gain for shared-height cross covariance.
        # Huber variance inflation must not multiply the implied correlation.
        information = sensitivity.T @ np.linalg.solve(noise, sensitivity)
        if prior:
            linear_covariance = np.linalg.inv(information + np.linalg.inv(prior[1]))
        else:
            linear_covariance = np.zeros((4, 4))
            linear_covariance[:2, :2] = np.linalg.inv(information[:2, :2])
        self.height_cross = (
            -linear_covariance @ sensitivity.T @ np.linalg.solve(noise, dz) * aircraft.z_sigma**2
        )
        # Reusing barometric samples across epochs must not drive shared-height
        # uncertainty to zero. Retain a per-epoch systematic height-error floor.
        height_response = -np.linalg.solve(jac.T @ jac, jac.T @ dz)
        covariance[:2, :2] += np.outer(height_response, height_response) * aircraft.z_sigma**2
        self.state, self.covariance = fit.x, covariance
        self.at = self.measurement_at = epoch.acquired_at
        self.aircraft = aircraft
        self.timing_sigma = epoch.timing_sigma + aircraft.timing_sigma
        return self.output(
            "measured",
            epoch.acquired_at,
            fit.x,
            covariance,
            aircraft,
            float(np.sqrt(np.mean(error**2))),
        )
