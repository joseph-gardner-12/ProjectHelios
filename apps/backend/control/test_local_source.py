import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from .models import Device, DevicePermission


class LocalSourceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("local@clemson.edu")
        self.client.force_login(self.user)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "source.json"
        self.path.write_text('{"mode":"real"}')
        self.devices = {
            mode: str(Device.objects.create(name=mode).id) for mode in ("real", "simulated")
        }
        for device_id in self.devices.values():
            DevicePermission.objects.create(user=self.user, device_id=device_id)
        settings = override_settings(
            CONTROL_LOCAL_UWB_FILE=str(self.path),
            CONTROL_LOCAL_UWB_DEVICES=json.dumps(self.devices),
        )
        settings.enable()
        self.addCleanup(settings.disable)

    def test_switch_is_authenticated_loopback_only_and_validated(self):
        url = "/api/v1/local/uwb-source/"
        self.assertEqual(self.client.get(url).json()["mode"], "real")
        response = self.client.post(url, {"mode": "simulated"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(self.path.read_text()), {"mode": "simulated"})
        self.assertEqual(
            self.client.post(
                url, {"mode": "arbitrary"}, content_type="application/json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                url, {"mode": "real"}, REMOTE_ADDR="192.168.1.2", content_type="application/json"
            ).status_code,
            403,
        )
        DevicePermission.objects.filter(user=self.user).delete()
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 401)

    def test_disabled_outside_local_launcher(self):
        with override_settings(CONTROL_LOCAL_UWB_FILE=""):
            self.assertEqual(
                self.client.get("/api/v1/local/uwb-source/").json(), {"enabled": False}
            )

    def test_active_command_prevents_switch(self):
        with patch("control.views.Command.objects.filter") as query:
            query.return_value.exists.return_value = True
            response = self.client.post(
                "/api/v1/local/uwb-source/", {"mode": "simulated"}, content_type="application/json"
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(self.path.read_text())["mode"], "real")
