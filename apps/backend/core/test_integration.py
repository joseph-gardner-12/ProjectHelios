import asyncio
import os
import uuid
from unittest import skipUnless

from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from channels_redis.core import RedisChannelLayer
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase

from config.asgi import application
from config.settings.environment import redis_channels


@skipUnless(os.environ.get("HELIOS_INTEGRATION_TESTS") == "1", "Requires Redis")
class IdleRedisTests(SimpleTestCase):
    async def test_idle_channel_survives_blocking_read_timeout(self):
        config = redis_channels(settings.REDIS_URL)["default"]["CONFIG"]
        layer = RedisChannelLayer(**{**config, "prefix": f"idle-test-{uuid.uuid4().hex}"})
        channel = await layer.new_channel()

        async def delayed_send():
            # Cross an entire empty blocking read before delivering a message.
            await asyncio.sleep(layer.brpop_timeout + 1)
            await layer.send(channel, {"type": "test.idle"})

        sender = asyncio.create_task(delayed_send())
        try:
            message = await asyncio.wait_for(layer.receive(channel), timeout=12)
            self.assertEqual(message, {"type": "test.idle"})
        finally:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
            await layer.close_pools()


class ASGITests(SimpleTestCase):
    async def test_pi_websocket_requires_authentication(self):
        socket = WebsocketCommunicator(application, "/ws/v1/pi/")
        connected, code = await socket.connect()
        self.assertFalse(connected)
        self.assertEqual(code, 4401)
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
