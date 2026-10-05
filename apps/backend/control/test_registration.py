import importlib
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.hashers import check_password, make_password
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from . import services
from .admin import RegistrationForm
from .models import ConnectionSlot, Device, DeviceCredential, Machine, RegistrationSettings


class RegistrationTests(TestCase):
    def setUp(self):
        self.device = Device.objects.create(name="Existing Helios")
        self.settings = RegistrationSettings.objects.update_or_create(
            pk=1, defaults={"enabled": True, "password_hash": make_password("student-project")}
        )[0]
        self.override = override_settings(CONTROL_DEMO_DEVICE_ID=str(self.device.id))
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.redis = patch("control.presence.client").start()
        self.addCleanup(patch.stopall)
        self.redis.return_value.eval.return_value = 1
        self.client = Client(enforce_csrf_checks=True)

    def register(self, name="Laptop", password="student-project"):
        return self.client.post(
            "/api/v1/machines/register/",
            {"name": name, "password": password},
            content_type="application/json",
        )

    def test_registers_distinct_computers_for_existing_device_without_csrf(self):
        first = self.register()
        second = self.register()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first["Cache-Control"], "no-store")
        self.assertEqual(first.json()["device_id"], str(self.device.id))
        self.assertNotEqual(first.json()["credential"], second.json()["credential"])
        self.assertEqual(Device.objects.count(), 1)
        self.assertEqual(Machine.objects.count(), 2)
        self.assertIsNotNone(services.authenticate_pi(first.json()["credential"]))
        self.assertFalse(Machine.objects.filter(legacy=True).exists())

    def test_password_rotation_preserves_existing_credentials(self):
        token = self.register().json()["credential"]
        self.settings.password_hash = make_password("new-password")
        self.settings.save()
        self.assertEqual(self.register().status_code, 401)
        self.assertEqual(self.register(password="new-password").status_code, 201)
        self.assertIsNotNone(services.authenticate_pi(token))

    def test_bad_password_disabled_registration_and_invalid_names(self):
        self.assertEqual(self.register(password="wrong").status_code, 401)
        for name in ("", "x" * 101, "line\nbreak", 42):
            self.assertEqual(self.register(name=name).status_code, 400)
        self.settings.enabled = False
        self.settings.save()
        self.assertEqual(self.register().status_code, 403)
        self.assertFalse(Machine.objects.exists())

    def test_rate_limit_and_redis_failure(self):
        self.redis.return_value.eval.return_value = 21
        self.assertEqual(self.register().status_code, 429)
        self.redis.return_value.eval.side_effect = ConnectionError
        self.assertEqual(self.register().status_code, 503)
        self.assertFalse(Machine.objects.exists())

    def test_disabled_machine_cannot_authenticate(self):
        token = self.register().json()["credential"]
        Machine.objects.update(enabled=False)
        self.assertIsNone(services.authenticate_pi(token))

    def test_admin_hashes_password_and_blank_preserves_it(self):
        form = RegistrationForm(
            data={"enabled": True, "registration_password": "replacement"}, instance=self.settings
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertNotEqual(saved.password_hash, "replacement")
        self.assertTrue(check_password("replacement", saved.password_hash))
        hashed = saved.password_hash
        form = RegistrationForm(data={"enabled": True}, instance=saved)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().password_hash, hashed)


class AdmissionTests(TestCase):
    def setUp(self):
        self.device = Device.objects.create(name="Existing target")
        self.token = services.issue_credential(self.device, "Lab Pi")
        self.credential = services.authenticate_pi(self.token)
        self.states = {}
        for target, action in (
            ("control.presence.read", lambda key: self.states.get(key)),
            ("control.presence.write", lambda key, data: self.states.update({key: data.copy()})),
            ("control.services.notify", lambda key: None),
        ):
            mock = patch(target, side_effect=action)
            mock.start()
            self.addCleanup(mock.stop)
        self.setup = services.connect_pi(self.credential.id, "first")

    def test_rejects_second_process_without_changing_first(self):
        with self.assertRaisesMessage(services.MachineAlreadyConnected, "Lab Pi"):
            services.connect_pi(self.credential.id, "second")
        self.device.refresh_from_db()
        self.assertEqual(str(self.device.connection_id), self.setup["connection_id"])
        self.assertEqual(self.device.channel_name, "first")

    def test_exclusion_is_backend_wide(self):
        other = Device.objects.create(name="Other target")
        credential = services.authenticate_pi(services.issue_credential(other, "Other laptop"))
        with self.assertRaises(services.MachineAlreadyConnected):
            services.connect_pi(credential.id, "other")
        other.refresh_from_db()
        self.assertIsNone(other.connection_id)

    def test_disconnect_releases_and_old_disconnect_cannot_release_new(self):
        services.disconnect(self.device.id, self.setup["connection_id"])
        new = services.connect_pi(self.credential.id, "second")
        services.disconnect(self.device.id, self.setup["connection_id"])
        self.device.refresh_from_db()
        self.assertEqual(str(self.device.connection_id), new["connection_id"])
        with self.assertRaises(services.MachineAlreadyConnected):
            services.connect_pi(self.credential.id, "third")

    def test_expired_owner_is_fenced(self):
        ConnectionSlot.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        new = services.connect_pi(self.credential.id, "second")
        self.assertNotEqual(new["connection_id"], self.setup["connection_id"])
        with self.assertRaises(services.ControlError):
            services.receive_pi(self.device.id, self.setup["connection_id"], {})

    def test_missing_presence_does_not_steal_live_slot(self):
        self.states.clear()
        with self.assertRaises(services.MachineAlreadyConnected):
            services.connect_pi(self.credential.id, "second")

    def test_disabling_computer_invalidates_live_connection(self):
        Machine.objects.update(enabled=False)
        self.assertIsNone(
            services.check_connection(
                self.device.id, self.setup["connection_id"], self.credential.id
            )
        )
        self.device.refresh_from_db()
        self.assertIsNone(self.device.connection_id)


class LegacyMigrationTests(TransactionTestCase):
    def test_old_device_and_secrets_survive_migration(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("control", "0001_initial")])
        try:
            old = executor.loader.project_state([("control", "0001_initial")]).apps
            device = old.get_model("control", "Device").objects.create(name="Original Pi")
            key = uuid.uuid4()
            secret_hash = make_password("existing-secret")
            old.get_model("control", "DeviceCredential").objects.create(
                id=key, device=device, secret_hash=secret_hash
            )
            revoked = old.get_model("control", "DeviceCredential").objects.create(
                device=device, secret_hash=make_password("revoked"), revoked_at=timezone.now()
            )
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate([("control", "0003_preserve_legacy_computers")])
        self.assertEqual(Device.objects.get(pk=device.pk).name, "Original Pi")
        self.assertEqual(DeviceCredential.objects.get(pk=key).secret_hash, secret_hash)
        machine = Machine.objects.get(credential_id=key)
        self.assertTrue(machine.legacy)
        self.assertIn("Original Pi", machine.name)
        self.assertEqual(services.authenticate_pi(f"{key}.existing-secret").id, key)
        self.assertIsNone(services.authenticate_pi(f"{revoked.id}.revoked"))
        # Re-running the backfill is harmless and never creates a replacement device.
        migration = importlib.import_module("control.migrations.0003_preserve_legacy_computers")
        from django.apps import apps

        with connection.schema_editor() as editor:
            migration.preserve_computers(apps, editor)
        self.assertEqual(Device.objects.count(), 1)
        self.assertEqual(Machine.objects.count(), 2)
