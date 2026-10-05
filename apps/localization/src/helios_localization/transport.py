"""Outbound WebSocket transport; reconnect always starts with an idle coordinator."""

import asyncio
import json
import logging
import random
import time
from datetime import UTC, datetime

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from .coordinator import CommandCoordinator
from .protocol import validate

log = logging.getLogger(__name__)


class TerminalConnectionError(Exception):
    def __init__(self, message, exit_status=4):
        super().__init__(message)
        self.exit_status = exit_status


def terminal_error(exc):
    if isinstance(exc, TerminalConnectionError):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            if error := terminal_error(child):
                return error
    if (isinstance(exc, InvalidStatus) and exc.response.status_code in {401, 403}) or (
        isinstance(exc, ConnectionClosed) and exc.rcvd and exc.rcvd.code == 4401
    ):
        return TerminalConnectionError(
            "Computer credential rejected or disabled. Ask the administrator, "
            "then run pnpm pi:setup --force if a new registration is needed."
        )
    return None


async def connection(url, credential, device_id, frame_version, coordinator, *, on_connected=None):
    coordinator.reset()
    async with connect(
        url,
        additional_headers={"Authorization": f"Bearer {credential}"},
        max_size=8192,
        open_timeout=10,
        ping_interval=2,
        ping_timeout=5,
    ) as socket:
        first = json.loads(await asyncio.wait_for(socket.recv(), 5))
        if (
            isinstance(first, dict)
            and first.get("version") == 1
            and first.get("type") == "error"
            and first.get("code") == "machine_already_connected"
        ):
            message = first.get("message")
            if not isinstance(message, str) or not message or len(message) > 512:
                message = "Cannot start: another computer is already connected."
            raise TerminalConnectionError(message, exit_status=3)
        if isinstance(first, dict) and first.get("code") == "backend_unavailable":
            raise ConnectionError("Backend temporarily unavailable")
        setup = validate(first, device_id, frame_version)
        if setup["type"] != "setup":
            raise ValueError("Expected setup")
        connection_id = setup["connection_id"]
        if on_connected:
            on_connected()

        async def send(data):
            await socket.send(
                json.dumps(
                    {
                        "version": 1,
                        "device_id": device_id,
                        "connection_id": connection_id,
                        "frame_version": frame_version,
                        "timestamp": datetime.now(UTC).isoformat(),
                        **data,
                    },
                    allow_nan=False,
                )
            )

        await send({"type": "ready"})
        log.info("Connected device=%s connection=%s source=dummy", device_id, connection_id)
        heartbeat_at = time.monotonic()

        async def receive():
            nonlocal heartbeat_at
            async for raw in socket:
                data = validate(json.loads(raw), device_id, frame_version, connection_id)
                if data["type"] == "heartbeat":
                    heartbeat_at = time.monotonic()
                elif data["type"] == "target":
                    log.info(
                        "Received target command=%r target=%r",
                        data.get("command_id"),
                        data.get("target"),
                    )
                    acknowledgment, candidate = coordinator.prepare(data, datetime.now(UTC))
                    await send(acknowledgment)
                    log.info(
                        "Sent acknowledgment command=%r accepted=%s reason=%r",
                        acknowledgment["command_id"],
                        acknowledgment["accepted"],
                        acknowledgment.get("reason"),
                    )
                    coordinator.start(candidate, time.monotonic())
                else:
                    raise ValueError("Unexpected setup")
            raise ConnectionError("Backend disconnected")

        async def publish():
            sequence = 0
            last_completed = None
            while True:
                now = time.monotonic()
                if now - heartbeat_at >= 5:
                    raise TimeoutError("Backend heartbeat expired")
                coordinator.tick(now)
                telemetry = coordinator.telemetry()
                await send({**telemetry, "sequence": sequence})
                position = telemetry["position"]
                log.info(
                    "Sent position sequence=%d x=%.3f y=%.3f z=%.3f m state=%s command=%r",
                    sequence,
                    position["x"],
                    position["y"],
                    position["z"],
                    telemetry["state"],
                    telemetry["command_id"],
                )
                if coordinator.completed_id and coordinator.completed_id != last_completed:
                    await send({"type": "arrival", "command_id": coordinator.completed_id})
                    log.info("Sent arrival command=%r", coordinator.completed_id)
                    last_completed = coordinator.completed_id
                sequence += 1
                await asyncio.sleep(0.2)

        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(receive())
                tasks.create_task(publish())
        finally:
            coordinator.reset()


async def run(url, credential_file, device_id, frame_version):
    coordinator = CommandCoordinator()
    delay = 1
    while True:
        started = time.monotonic()
        established = False

        def connected():
            nonlocal established
            established = True

        try:
            credential = credential_file.read_text().strip()
            await connection(
                url, credential, device_id, frame_version, coordinator, on_connected=connected
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            coordinator.reset()
            if error := terminal_error(exc):
                raise error from None
            # Exception text from networking libraries may contain headers; log only the type.
            log.warning("Connection interrupted (%s); target cleared", type(exc).__name__)
        if time.monotonic() - started > 10:
            delay = 1
        # A stopped backend may not run disconnect cleanup. Its admission lease
        # lasts five seconds after the last frame; let it expire before retrying
        # so our own stale lease isn't reported as a terminal machine conflict.
        await asyncio.sleep((5 if established else 0) + random.uniform(delay / 2, delay))
        delay = min(30, delay * 2)
