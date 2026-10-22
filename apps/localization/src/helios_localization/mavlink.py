"""Measurement-only MAVLink interface; no arm, mode, or waypoint methods."""

import base64
import math
import os
import uuid
from collections import deque

from .frames import covariance_to_ned, enu_to_ned
from .measurements import AircraftSample

EXPECTED_PARAMETERS = {
    "VISO_TYPE": 3,
    "EK3_ENABLE": 1,
    "EK3_SRC1_POSXY": 6,
    "EK3_SRC1_VELXY": 0,
    "EK3_SRC1_POSZ": 1,
    "EK3_SRC1_VELZ": 0,
    "EK3_SRC1_YAW": 1,
    "VISO_POS_X": 0,
    "VISO_POS_Y": 0,
    "VISO_POS_Z": 0,
}


class AircraftClock:
    """Estimate boot-clock offset from the lowest observed receive delay.

    This is an estimate, not a clock synchronization guarantee. Configured timing
    uncertainty must include measured downlink latency. Reset on boot-time rollback.
    """

    def __init__(self):
        self.session = str(uuid.uuid4())
        self.offsets = deque(maxlen=100)
        self.last_boot = None

    def map(self, boot_ms, received):
        boot = boot_ms / 1000
        if self.last_boot is not None and boot < self.last_boot - 1:
            self.session = str(uuid.uuid4())
            self.offsets.clear()
        self.last_boot = max(boot, self.last_boot or boot) if self.offsets else boot
        self.offsets.append(received - boot)
        return boot + min(self.offsets)


class AircraftLink:
    def __init__(self, settings):
        os.environ["MAVLINK20"] = "1"
        from pymavlink import mavutil

        self.settings = settings
        self.link = mavutil.mavlink_connection(
            settings.mavlink_port,
            baud=settings.mavlink_baud,
            source_system=246,
            source_component=191,
            dialect="ardupilotmega",
        )
        if not self.link.mavlink20():
            self.link.close()
            raise ValueError("MAVLink 2 is required")
        self.clock = AircraftClock()
        self.attitude = None
        self.parameters = {}
        self.last_heartbeat = None
        self.armed = True
        self.origin = False
        self.firmware_version = None
        self.events = []
        self.reset_counter = 0
        self.last_sent = None
        self.last_estimator_session = None
        self.requested = False

    def poll(self, now):
        samples = []
        self.events = []
        # Bound work so a telemetry flood cannot starve range acquisition.
        for _ in range(100):
            message = self.link.recv_match(blocking=False)
            if message is None:
                break
            kind = message.get_type()
            if kind in {
                "HEARTBEAT",
                "ATTITUDE",
                "LOCAL_POSITION_NED",
                "PARAM_VALUE",
                "GPS_GLOBAL_ORIGIN",
                "AUTOPILOT_VERSION",
            }:
                self.events.append(
                    {
                        "type": "mavlink",
                        "at": now,
                        "packet": base64.b64encode(message.get_msgbuf()).decode(),
                    }
                )
            if kind == "HEARTBEAT":
                # Ignore GCS heartbeats and telemetry from another vehicle.
                if message.autopilot == 8:
                    continue
                if self.link.target_system not in (0, message.get_srcSystem()):
                    continue
                self.link.target_system = message.get_srcSystem()
                self.link.target_component = message.get_srcComponent()
                self.last_heartbeat = now
                self.armed = bool(message.base_mode & 128)
                if not self.requested:
                    for message_id in (30, 32):  # ATTITUDE, LOCAL_POSITION_NED, 20 Hz
                        self.link.mav.command_long_send(
                            self.link.target_system,
                            self.link.target_component,
                            511,
                            0,
                            message_id,
                            50000,
                            0,
                            0,
                            0,
                            0,
                            0,
                        )
                    self.link.mav.command_long_send(
                        self.link.target_system,
                        self.link.target_component,
                        512,
                        0,
                        49,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,  # request GPS_GLOBAL_ORIGIN
                    )
                    if self.settings.external_nav:
                        self.link.mav.command_long_send(
                            self.link.target_system,
                            self.link.target_component,
                            512,
                            0,
                            148,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                        )
                        for name in EXPECTED_PARAMETERS:
                            self.link.mav.param_request_read_send(
                                self.link.target_system,
                                self.link.target_component,
                                name.encode(),
                                -1,
                            )
                    self.requested = True
            elif message.get_srcSystem() != self.link.target_system:
                continue
            elif kind == "AUTOPILOT_VERSION":
                version = message.flight_sw_version
                self.firmware_version = (
                    f"{version >> 24}.{(version >> 16) & 255}.{(version >> 8) & 255}"
                )
            elif kind == "PARAM_VALUE":
                self.parameters[message.param_id] = message.param_value
            elif kind == "GPS_GLOBAL_ORIGIN":
                self.origin = True
            elif kind in {"ATTITUDE", "LOCAL_POSITION_NED"}:
                old_session = self.clock.session
                at = self.clock.map(message.time_boot_ms, now)
                if old_session != self.clock.session:
                    self.attitude = None
                    self.parameters.clear()
                    self.origin = False
                    self.firmware_version = None
                    self.requested = False
                    self.last_sent = None
                    self.reset_counter = (self.reset_counter + 1) % 256
                if kind == "ATTITUDE":
                    if all(math.isfinite(v) for v in (message.roll, message.pitch, message.yaw)):
                        self.attitude = (at, message.roll, message.pitch, message.yaw)
                    else:
                        self.attitude = None
                elif (
                    self.attitude
                    and math.isfinite(message.z)
                    and abs(at - self.attitude[0]) <= self.settings.max_skew
                ):
                    samples.append(
                        AircraftSample(
                            self.clock.session,
                            at,
                            now,
                            -message.z + self.settings.altitude_offset,
                            self.settings.altitude_sigma,
                            *self.attitude[1:],
                            self.settings.timing_sigma,
                        )
                    )
        return samples

    def send_estimate(self, estimate, aircraft, now):
        if not self.settings.external_nav or estimate.kind != "measured":
            return False
        if (
            self.armed
            or self.firmware_version != self.settings.controller_firmware
            or not self.origin
            or self.last_heartbeat is None
            or now - self.last_heartbeat > 1
            or now - estimate.measurement_at + estimate.timing_sigma > self.settings.max_age
            or self.last_sent == (estimate.session, estimate.measurement_at)
            or any(self.parameters.get(k) != v for k, v in EXPECTED_PARAMETERS.items())
        ):
            return False
        if estimate.position is None or estimate.covariance is None or aircraft is None:
            return False
        if abs(aircraft.acquired_at - estimate.measurement_at) > self.settings.max_skew:
            return False
        if self.last_estimator_session != estimate.session:
            self.reset_counter = (self.reset_counter + 1) % 256
            self.last_estimator_session = estimate.session
        position = enu_to_ned(estimate.position, self.settings.dock_in_ned)
        covariance = covariance_to_ned(estimate.covariance)
        pose = [[0.0] * 6 for _ in range(6)]
        for i in range(3):
            for j in range(3):
                pose[i][j] = float(covariance[i, j])
        for i in range(3, 6):
            pose[i][i] = math.radians(5) ** 2
        packed = [pose[i][j] for i in range(6) for j in range(i, 6)]
        self.link.mav.vision_position_estimate_send(
            int(estimate.measurement_at * 1e6),
            *position,
            aircraft.roll,
            aircraft.pitch,
            aircraft.yaw,
            packed,
            self.reset_counter,
        )
        self.last_sent = (estimate.session, estimate.measurement_at)
        return True

    def close(self):
        self.link.close()
