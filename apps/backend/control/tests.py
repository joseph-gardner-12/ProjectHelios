import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.db import close_old_connections, connection
from django.test import Client, SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone

from . import presence, services
from .models import Command, ControlLease, Device, DeviceCredential, DevicePermission, QueueEntry
from .protocol import coordinates


class ContractTests(SimpleTestCase):
    def test_coordinates(self):
        path = (
            Path(__file__).resolve().parents[3] / "contracts/control-v1/coordinates.fixtures.json"
        )
        for case in json.loads(path.read_text()):
            with self.subTest(case=case["name"]):
                if case["valid"]:
                    self.assertEqual(coordinates(case["position"]), case["position"])
                else:
                    with self.assertRaises(ValueError):
                        coordinates(case["position"])
        for value in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                coordinates({"x": value, "y": 0, "z": 0})


@skipUnless(os.getenv("HELIOS_INTEGRATION_TESTS") == "1", "Requires disposable PostgreSQL/Redis")
class ControlIntegrationTests(TransactionTestCase):
    def setUp(self):
        self.device = Device.objects.create(name="Test dummy")
        self.override = override_settings(
            CONTROL_DEMO_DEVICE_ID=str(self.device.id),
            CONTROL_REDIS_PREFIX=f"test:control:{uuid.uuid4()}",
            CONTROL_PASSWORD_HASH=make_password("test-password"),
        )
        self.override.enable()
        self.user = User.objects.create_user(username="one@clemson.edu")
        self.other = User.objects.create_user(username="two@clemson.edu")
        for user in (self.user, self.other):
            DevicePermission.objects.create(device=self.device, user=user)
        token = services.issue_credential(self.device)
        self.credential = services.authenticate_pi(token)
        self.setup = services.connect_pi(self.credential.id, "test.pi")
        self.connection_id = self.setup["connection_id"]
        self.sequence = 0
        self.message("ready")
        self.position()
        services.join(self.device.id, self.user, "one")
        services.browser_seen(self.device.id, self.user, "one")
        self.state = services.snapshot(self.device.id, self.user, "one")

    def tearDown(self):
        redis = presence.client()
        from django.conf import settings

        keys = list(redis.scan_iter(f"{settings.CONTROL_REDIS_PREFIX}:*"))
        if keys:
            redis.delete(*keys)
        self.override.disable()

    def message(self, kind, **kwargs):
        services.receive_pi(
            self.device.id,
            self.connection_id,
            {
                **{k: v for k, v in self.setup.items() if k != "telemetry_hz"},
                "type": kind,
                **kwargs,
            },
        )

    def position(self, x=0, state="idle", completed=None):
        self.sequence += 1
        self.message(
            "position",
            position={"x": x, "y": 0, "z": 0},
            source="dummy",
            sequence=self.sequence,
            state=state,
            completed_command_id=completed,
        )

    def payload(self):
        return {
            "request_id": str(uuid.uuid4()),
            "lease_id": self.state["queue"]["lease_id"],
            "frame_version": "dummy-enu-v1",
            "target": {"x": 0.5, "y": 0, "z": 0},
        }

    def submit(self, data=None):
        return services.submit(self.device.id, self.user, "one", data or self.payload())

    def test_idempotency_and_busy(self):
        data = self.payload()
        first, created = self.submit(data)
        self.assertTrue(created)
        self.assertEqual(first["status"], "pending_ack")
        self.assertEqual(self.submit(data), (first, False))
        with self.assertRaises(services.ControlError):
            self.submit()
        with self.assertRaises(services.ControlError):
            self.submit({**data, "target": {"x": 1, "y": 0, "z": 0}})
        self.assertEqual(Command.objects.count(), 1)

    def test_permission_and_controller_enforced(self):
        with self.assertRaises(services.ControlError):
            services.submit(self.device.id, self.other, "two", self.payload())
        DevicePermission.objects.filter(user=self.user).delete()
        with self.assertRaises(services.ControlError):
            self.submit()

    def test_ack_arrival_and_queue_handoff(self):
        services.join(self.device.id, self.other, "two")
        services.browser_seen(self.device.id, self.other, "two")
        command, _ = self.submit()
        self.message("ack", command_id=command["id"], accepted=True)
        Command.objects.filter(pk=command["id"]).update(
            accepted_at=timezone.now() - timedelta(seconds=1)
        )
        ControlLease.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertFalse(services.snapshot(self.device.id, self.other, "two")["can_send"])
        self.position(0.5, completed=command["id"])
        self.message("arrival", command_id=command["id"])
        self.assertEqual(Command.objects.get().status, "arrived")
        self.assertTrue(services.snapshot(self.device.id, self.other, "two")["can_send"])

    def test_lost_ack_invalidates_and_never_replays(self):
        command, _ = self.submit()
        Command.objects.filter(pk=command["id"]).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        services.tick()
        self.assertEqual(Command.objects.get().status, "unconfirmed")
        new = services.connect_pi(self.credential.id, "test.new")
        self.assertNotEqual(new["connection_id"], self.connection_id)
        self.assertIsNone(
            services.dispatch_message(self.device.id, new["connection_id"], command["id"])
        )
        with self.assertRaises(services.ControlError):
            self.position()

    def test_stale_and_out_of_order_positions(self):
        state = presence.read(self.device.id)
        state["position_at"] -= 3
        presence.write(self.device.id, state)
        self.assertEqual(services.snapshot(self.device.id, self.user, "one")["health"], "stale")
        with self.assertRaises(services.ControlError):
            self.submit()
        self.message(
            "position", position={"x": 2, "y": 0, "z": 0}, source="dummy", sequence=0, state="idle"
        )
        self.assertEqual(presence.read(self.device.id)["position"]["x"], 0)

    def test_restart_missing_presence_and_redis_outage(self):
        self.submit()
        presence.clear(self.device.id)
        services.tick()
        self.assertEqual(Command.objects.get().status, "unconfirmed")
        with patch("control.presence.read", side_effect=ConnectionError):
            services.tick()
        self.device.refresh_from_db()
        self.assertIsNone(self.device.connection_id)

    def test_real_redis_connection_failure_fails_closed_and_recovers_idle(self):
        import socket

        # Reserve an unused port, then close it to exercise a real refused Redis connection.
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        command, _ = self.submit()
        self.message("ack", command_id=command["id"], accepted=True)
        client = Client()
        client.force_login(self.user, backend="control.auth.DemoBackend")
        with override_settings(REDIS_URL=f"redis://127.0.0.1:{port}/0"):
            self.assertEqual(client.get(f"/api/v1/devices/{self.device.id}/").status_code, 503)
            with self.assertLogs("control.services", level="ERROR"):
                services.tick()
        self.assertEqual(Command.objects.get().status, "interrupted")
        self.device.refresh_from_db()
        self.assertIsNone(self.device.connection_id)
        new_setup = services.connect_pi(self.credential.id, "test.recovered")
        self.assertNotEqual(new_setup["connection_id"], self.connection_id)
        self.assertIsNone(
            services.dispatch_message(self.device.id, new_setup["connection_id"], command["id"])
        )
        self.assertFalse(services.snapshot(self.device.id, self.user, "one")["can_send"])

    def test_revoked_credential_invalidates_current_connection(self):
        DeviceCredential.objects.filter(pk=self.credential.id).update(revoked_at=timezone.now())
        self.assertIsNone(
            services.check_connection(self.device.id, self.connection_id, self.credential.id)
        )
        self.device.refresh_from_db()
        self.assertIsNone(self.device.connection_id)

    def test_disconnect_grace_and_no_automatic_requeue(self):
        QueueEntry.objects.filter(user=self.user).update(
            last_seen=timezone.now() - timedelta(seconds=16)
        )
        services.tick()
        self.assertFalse(QueueEntry.objects.filter(user=self.user).exists())
        self.assertFalse(services.snapshot(self.device.id, self.user, "one")["queue"]["joined"])

    def test_concurrent_submissions_only_one_command(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL row locks required")
        payloads = [self.payload(), self.payload()]

        def submit(data):
            close_old_connections()
            try:
                self.submit(data)
                return "accepted"
            except services.ControlError:
                return "blocked"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(submit, payloads))
        self.assertCountEqual(outcomes, ["accepted", "blocked"])
        self.assertEqual(Command.objects.count(), 1)

    def test_concurrent_computers_admit_exactly_one(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL row locks required")
        from threading import Barrier

        services.disconnect(self.device.id, self.connection_id)
        other_device = Device.objects.create(name="Different logical device")
        other = services.authenticate_pi(services.issue_credential(other_device))
        barrier = Barrier(2)

        def connect(credential_id):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                services.connect_pi(credential_id, f"race.{credential_id}")
                return "accepted"
            except services.MachineAlreadyConnected:
                return "blocked"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(connect, [self.credential.id, other.id]))
        self.assertCountEqual(outcomes, ["accepted", "blocked"])
        self.assertEqual(Device.objects.exclude(connection_id=None).count(), 1)

    def test_login_csrf_and_exact_domain(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(
            client.post("/api/v1/login/", {}, content_type="application/json").status_code, 403
        )
        csrf = client.get("/api/v1/session/").json()["csrf_token"]
        for email in ("a@example.com", "a@evilclemson.edu", "a@clemson.edu.evil"):
            response = client.post(
                "/api/v1/login/",
                {"email": email, "password": "test-password"},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
            )
            self.assertEqual(response.status_code, 401)
        response = client.post(
            "/api/v1/login/",
            {"email": "New@Clemson.edu", "password": "test-password"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(username="new@clemson.edu")
        self.assertFalse(user.is_staff or user.has_usable_password())
        self.assertTrue(QueueEntry.objects.filter(user=user).exists())


class MessageContractTests(SimpleTestCase):
    def test_shared_schemas_and_backend_messages(self):
        from types import SimpleNamespace

        from jsonschema import Draft202012Validator, FormatChecker

        from .protocol import validate_message

        root = Path(__file__).resolve().parents[3] / "contracts/control-v1"
        validators = {
            name: Draft202012Validator(
                json.loads((root / f"{name}.schema.json").read_text()),
                format_checker=FormatChecker(),
            )
            for name in ("pi", "browser")
        }
        device = SimpleNamespace(
            id="11111111-1111-4111-8111-111111111111", frame_version="dummy-enu-v1"
        )
        connection_id = "22222222-2222-4222-8222-222222222222"
        for case in json.loads((root / "messages.fixtures.json").read_text()):
            with self.subTest(name=case["name"]):
                schema = validators["browser" if case["direction"] == "browser" else "pi"]
                self.assertEqual(not list(schema.iter_errors(case["message"])), case["valid"])
                if case["direction"] == "pi":
                    if case["valid"]:
                        validate_message(case["message"], device, connection_id)
                    else:
                        with self.assertRaises((ValueError, KeyError, TypeError)):
                            validate_message(case["message"], device, connection_id)
