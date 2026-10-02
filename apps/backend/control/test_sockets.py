import asyncio
import os
import uuid
from unittest import skipUnless

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import User
from django.test import Client, TransactionTestCase

from config.asgi import application

from . import services
from .models import Device, DeviceCredential, DevicePermission


@skipUnless(os.getenv("HELIOS_INTEGRATION_TESTS") == "1", "Requires Redis")
class SocketTests(TransactionTestCase):
    def setUp(self):
        self.device = Device.objects.create(name="Socket test")
        self.token = services.issue_credential(self.device)
        self.user = User.objects.create_user(username="socket@clemson.edu")
        DevicePermission.objects.create(device=self.device, user=self.user)
        self.browser = Client()
        self.browser.force_login(self.user, backend="control.auth.DemoBackend")
        self.session_key = self.browser.session.session_key
        services.join(self.device.id, self.user, self.session_key)

    def pi(self):
        return WebsocketCommunicator(
            application, "/ws/v1/pi/", headers=[(b"authorization", f"Bearer {self.token}".encode())]
        )

    def viewer(self, origin=b"http://localhost:5173"):
        return WebsocketCommunicator(
            application,
            f"/ws/v1/devices/{self.device.id}/",
            headers=[(b"cookie", f"sessionid={self.session_key}".encode()), (b"origin", origin)],
        )

    async def test_browser_origin_and_device_authorization(self):
        viewer = self.viewer(b"https://evil.example")
        self.assertFalse((await viewer.connect())[0])
        await viewer.disconnect()
        await database_sync_to_async(DevicePermission.objects.all().delete)()
        viewer = self.viewer()
        self.assertFalse((await viewer.connect())[0])
        await viewer.disconnect()

    async def test_target_ack_and_replacement(self):
        pi = self.pi()
        self.assertTrue((await pi.connect())[0])
        setup = await pi.receive_json_from()
        message = {k: v for k, v in setup.items() if k != "telemetry_hz"}
        await pi.send_json_to({**message, "type": "ready"})
        await pi.send_json_to(
            {
                **message,
                "type": "position",
                "sequence": 0,
                "position": {"x": 0, "y": 0, "z": 0},
                "source": "dummy",
                "state": "idle",
            }
        )
        viewer = self.viewer()
        self.assertTrue((await viewer.connect())[0])
        state = await viewer.receive_json_from()
        while not state["can_send"]:
            state = await viewer.receive_json_from(timeout=3)
        payload = {
            "request_id": str(uuid.uuid4()),
            "lease_id": state["queue"]["lease_id"],
            "frame_version": "dummy-enu-v1",
            "target": {"x": 1, "y": 1, "z": 1},
        }
        command, _ = await database_sync_to_async(services.submit)(
            self.device.id, self.user, self.session_key, payload
        )
        dispatched = await pi.receive_json_from()
        while dispatched["type"] != "target":
            dispatched = await pi.receive_json_from()
        self.assertEqual(dispatched["command_id"], command["id"])
        await pi.send_json_to(
            {**message, "type": "ack", "command_id": command["id"], "accepted": True}
        )
        while (state.get("command") or {}).get("status") != "accepted":
            state = await viewer.receive_json_from()
        replacement = self.pi()
        self.assertTrue((await replacement.connect())[0])
        new_setup = await replacement.receive_json_from()
        self.assertNotEqual(new_setup["connection_id"], setup["connection_id"])
        close = await pi.receive_output()
        self.assertEqual(close["type"], "websocket.close")
        self.assertEqual(close["code"], 4409)
        await replacement.disconnect()
        await pi.disconnect()
        await viewer.disconnect()

    async def test_revocation_closes_live_socket(self):
        pi = self.pi()
        await pi.connect()
        setup = await pi.receive_json_from()
        from django.utils import timezone

        await database_sync_to_async(DeviceCredential.objects.filter(device=self.device).update)(
            revoked_at=timezone.now()
        )
        result = await pi.receive_output(timeout=3)
        self.assertEqual(result["type"], "websocket.close")
        await pi.disconnect()
        self.assertTrue(setup["connection_id"])

    async def test_logout_closes_browser(self):
        viewer = self.viewer()
        self.assertTrue((await viewer.connect())[0])
        await viewer.receive_json_from()
        await database_sync_to_async(self.browser.logout)()
        async with asyncio.timeout(3):
            while True:
                result = await viewer.receive_output(timeout=3)
                if result["type"] == "websocket.close":
                    break
        self.assertEqual(result["code"], 4401)
        await viewer.disconnect()
