import asyncio
import os
from unittest import skipUnless

from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase

from config.asgi import application


class ASGITests(SimpleTestCase):
    async def test_websocket_upgrade_is_rejected_until_auth_is_implemented(self):
        socket = WebsocketCommunicator(application, "/ws/device/")
        connected, code = await socket.connect()
        self.assertFalse(connected)
        self.assertEqual(code, 1008)
        await socket.disconnect()


@skipUnless(os.environ.get("HELIOS_INTEGRATION_TESTS") == "1", "Requires PostgreSQL and Redis")
class DependencyIntegrationTests(TransactionTestCase):
    def test_postgres_persistence_and_readiness(self):
        self.assertEqual(connection.vendor, "postgresql")
        user = get_user_model().objects.create_user(username="integration-user")
        connection.close()
        self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())
        self.assertEqual(self.client.get("/api/ready/").status_code, 200)

    async def test_redis_channel_group_roundtrip(self):
        layer = get_channel_layer()
        self.assertEqual(type(layer).__name__, "RedisChannelLayer")
        channel = await layer.new_channel()
        group = "helios-integration"
        try:
            await layer.group_add(group, channel)
            await layer.group_send(group, {"type": "test.message", "value": "connected"})
            message = await asyncio.wait_for(layer.receive(channel), timeout=3)
            self.assertEqual(message, {"type": "test.message", "value": "connected"})
        finally:
            await layer.group_discard(group, channel)
            await layer.close_pools()
