import asyncio
import contextlib
import logging

from channels.auth import get_user
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.sessions.models import Session
from django.utils import timezone

from . import services

log = logging.getLogger(__name__)
call = database_sync_to_async


class PiConsumer(AsyncJsonWebsocketConsumer):
    connection_id = None
    task = None

    async def connect(self):
        headers = dict(self.scope["headers"])
        authorization = headers.get(b"authorization", b"").decode()
        if not authorization.startswith("Bearer "):
            await self.close(code=4401)
            return
        credential = await call(services.authenticate_pi)(authorization[7:])
        if not credential:
            await self.close(code=4401)
            return
        self.credential_id = credential.id
        self.device_id = credential.device_id
        try:
            setup = await call(services.connect_pi)(credential.id, self.channel_name)
            self.connection_id = setup["connection_id"]
            await self.accept()
            await self.send_json(setup)
            self.task = asyncio.create_task(self.heartbeat())
        except Exception:
            log.exception("Pi setup failed")
            await self.close(code=1011)

    async def heartbeat(self):
        try:
            while True:
                await asyncio.sleep(1)
                message = await call(services.check_connection)(
                    self.device_id, self.connection_id, self.credential_id
                )
                if not message:
                    await self.close(code=4401)
                    return
                await self.send_json(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.close(code=1011)

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        if bytes_data or not text_data or len(text_data) > 8192:
            await self.close(code=4400)
            return
        try:
            await super().receive(text_data=text_data, **kwargs)
        except ValueError, TypeError, KeyError:
            await self.close(code=4400)

    async def receive_json(self, content, **kwargs):
        try:
            await call(services.receive_pi)(self.device_id, self.connection_id, content)
        except ValueError, TypeError, KeyError, services.ControlError:
            await self.close(code=4400)
        except Exception:
            log.exception("Pi receive failed device=%s", self.device_id)
            await self.close(code=1011)

    async def command_dispatch(self, event):
        try:
            valid = await call(services.check_connection)(
                self.device_id, self.connection_id, self.credential_id
            )
            if not valid:
                await self.close(code=4401)
                return
            message = await call(services.dispatch_message)(
                self.device_id, self.connection_id, event["command_id"]
            )
            if message:
                await self.send_json(message)
        except Exception:
            await self.close(code=1011)

    async def replaced(self, event):
        await self.close(code=4409)

    async def disconnect(self, code):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        if self.connection_id:
            await call(services.disconnect)(self.device_id, self.connection_id)


class BrowserConsumer(AsyncJsonWebsocketConsumer):
    task = None
    joined = False

    async def authorized(self):
        # Reload the stored session: the handshake's session cache survives logout.
        key = self.scope["session"].session_key
        exists = await call(
            Session.objects.filter(session_key=key, expire_date__gt=timezone.now()).exists
        )()
        return exists and (await get_user(self.scope)).is_authenticated

    async def connect(self):
        self.device_id = self.scope["url_route"]["kwargs"]["device_id"]
        self.session_key = self.scope["session"].session_key
        if not self.scope["user"].is_authenticated:
            await self.close(code=4401)
            return
        try:
            await call(services.browser_seen)(self.device_id, self.scope["user"], self.session_key)
            await self.channel_layer.group_add(services.group(self.device_id), self.channel_name)
            self.joined = True
            await self.accept()
            await self.refresh({})
            self.task = asyncio.create_task(self.heartbeat())
        except services.ControlError:
            await self.close(code=4403)
        except Exception:
            await self.close(code=1011)

    async def heartbeat(self):
        try:
            while True:
                await asyncio.sleep(1)
                if not await self.authorized():
                    await self.close(code=4401)
                    return
                await call(services.browser_seen)(
                    self.device_id, self.scope["user"], self.session_key
                )
                await self.refresh({})
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.close(code=1011)

    async def refresh(self, event):
        try:
            if not await self.authorized():
                await self.close(code=4401)
                return
            data = await call(services.snapshot)(
                self.device_id, self.scope["user"], self.session_key
            )
            await self.send_json(data)
        except Exception:
            await self.close(code=1011)

    async def receive_json(self, content, **kwargs):
        # Browser commands are CSRF-protected HTTP mutations, never socket messages.
        await self.close(code=4400)

    async def disconnect(self, code):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        if self.joined:
            with contextlib.suppress(Exception):
                await self.channel_layer.group_discard(
                    services.group(self.device_id), self.channel_name
                )
