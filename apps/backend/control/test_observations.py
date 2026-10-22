import copy
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from . import services
from .models import Command, Device, DevicePermission
from .observations import validate_observation


def observation(now=None, **changes):
    now = now or timezone.now()
    return {
        "kind": "measured",
        "session": "test:fc:1",
        "estimated_time": now.isoformat(),
        "measurement_time": now.isoformat(),
        "prediction_age_s": 0,
        "position": {"x": -1.0, "y": 2.0, "z": 0.5},
        "covariance": [[0.01, 0, 0], [0, 0.01, 0], [0, 0, 0.02]],
        "timing_sigma_s": 0.001,
        "reason": None,
        **changes,
    }


class ObservationTests(TestCase):
    def setUp(self):
        self.state = None
        self.read = patch("control.presence.read", side_effect=lambda _: copy.deepcopy(self.state))
        self.write = patch("control.presence.write", side_effect=self.save_state)
        self.read.start()
        self.write.start()
        self.addCleanup(self.read.stop)
        self.addCleanup(self.write.stop)
        self.addCleanup(patch.stopall)
        patch("control.services.notify").start()
        self.device = Device.objects.create(name="Measured", frame_version="survey-enu-v1")
        self.user = User.objects.create_user(username="test@clemson.edu")
        DevicePermission.objects.create(device=self.device, user=self.user)
        token = services.issue_credential(self.device)
        credential = services.authenticate_pi(token)
        self.setup = services.connect_pi(credential.id, "test.pi")
        self.device.refresh_from_db()
        self.send("ready", capability="measurement")

    def save_state(self, _, state):
        self.state = copy.deepcopy(state)

    def send(self, kind, **values):
        services.receive_pi(
            self.device.id,
            self.setup["connection_id"],
            {
                **{k: v for k, v in self.setup.items() if k != "telemetry_hz"},
                "type": kind,
                **values,
            },
        )

    def test_observations_are_signed_and_read_only(self):
        self.send("observation", sequence=0, source="uwb", observation=observation())
        result = services.snapshot(self.device.id, self.user, "test")
        self.assertEqual(result["position"]["x"], -1.0)
        self.assertEqual(result["health"], "fresh")
        self.assertEqual(result["capability"], "measurement")
        self.assertFalse(result["can_send"])
        with self.assertRaises(services.ControlError):
            services.join(self.device.id, self.user, "test")
        with self.assertRaises(services.ControlError):
            services.submit(
                self.device.id,
                self.user,
                "test",
                {
                    "target": {"x": 1, "y": 1, "z": 1},
                    "request_id": str(uuid.uuid4()),
                    "lease_id": str(uuid.uuid4()),
                    "frame_version": self.device.frame_version,
                },
            )
        self.assertEqual(Command.objects.count(), 0)

    def test_repeated_results_do_not_refresh_measurement_time(self):
        old = observation(timezone.now() - timedelta(seconds=1))
        self.send("observation", sequence=0, source="uwb", observation=old)
        first_time = self.state["position_at"]
        self.send("observation", sequence=1, source="uwb", observation=old)
        result = services.snapshot(self.device.id, self.user, "test")
        self.assertEqual(result["position_at"], first_time)
        self.assertEqual(result["health"], "stale")

    def test_invalid_result_keeps_reference_position_but_clears_validity(self):
        self.send("observation", sequence=0, source="synthetic", observation=observation())
        self.send(
            "observation",
            sequence=1,
            source="synthetic",
            observation=observation(
                kind="invalid", position=None, covariance=None, reason="altitude_stale"
            ),
        )
        result = services.snapshot(self.device.id, self.user, "test")
        self.assertIsNotNone(result["position"])
        self.assertEqual(result["health"], "stale")
        self.assertEqual(result["source"], "synthetic")

    def test_dummy_and_capability_switches_rejected(self):
        with self.assertRaises(ValueError):
            self.send(
                "position",
                sequence=0,
                source="dummy",
                state="idle",
                position={"x": 0, "y": 0, "z": 0},
            )
        with self.assertRaises(ValueError):
            self.send("ready", capability="dummy")

    def test_duplicate_observation_does_not_replace_current_result(self):
        self.send("observation", sequence=1, source="uwb", observation=observation())
        self.send(
            "observation",
            sequence=0,
            source="uwb",
            observation=observation(position={"x": 99, "y": 99, "z": 99}),
        )
        self.assertEqual(self.state["position"]["x"], -1.0)

    def test_validation_rejects_malformed_or_unbounded_estimates(self):
        now = timezone.now()
        for changes in (
            {"prediction_age_s": 0.2},
            {
                "kind": "predicted",
                "prediction_age_s": 0.2,
                "estimated_time": (now + timedelta(seconds=0.2)).isoformat(),
            },
            {"position": {"x": float("nan"), "y": 0, "z": 1}},
            {"covariance": [[1, 2, 0], [2, 1, 0], [0, 0, 1]]},
            {"covariance": [[1, 0, 0], [1, 1, 0], [0, 0, 1]]},
            {"measurement_time": None},
            {"reason": "unexpected"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_observation(observation(now, **changes))
        predicted = observation(
            now,
            kind="predicted",
            prediction_age_s=0.05,
            estimated_time=(now + timedelta(seconds=0.05)).isoformat(),
        )
        self.assertEqual(validate_observation(predicted), predicted)


class SimulatedDiagnosticsContractTests(TestCase):
    def test_dummy_sensor_diagnostics_are_validated_separately(self):
        from .protocol import validate_message

        device = Device(id=uuid.uuid4(), frame_version="dummy-enu-v1")
        connection = uuid.uuid4()
        message = {
            "version": 1,
            "type": "position",
            "device_id": str(device.id),
            "connection_id": str(connection),
            "frame_version": device.frame_version,
            "timestamp": timezone.now().isoformat(),
            "sequence": 1,
            "source": "dummy",
            "position": {"x": 1, "y": 1, "z": 1},
            "state": "idle",
            "simulated_localization": {"frame": "bench-enu-v1", "observation": observation()},
        }
        self.assertEqual(validate_message(message, device, connection), message)
        message["simulated_localization"]["observation"]["kind"] = "unlabelled"
        with self.assertRaises(ValueError):
            validate_message(message, device, connection)
