"""Local measurement service. Cloud publishing consumes a single latest-result slot."""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime

import serial

from .mavlink import AircraftLink
from .protocol import validate
from .ranging import LineReader
from .replay import Pipeline, Recorder
from .transport import TerminalConnectionError, terminal_error

log = logging.getLogger(__name__)


def observation(estimate, wall_origin):
    def utc(at):
        return datetime.fromtimestamp(wall_origin + at, UTC).isoformat() if at is not None else None

    return {
        "kind": estimate.kind,
        "session": estimate.session,
        "estimated_time": utc(estimate.estimated_at),
        "measurement_time": utc(estimate.measurement_at),
        "prediction_age_s": estimate.prediction_age,
        "position": estimate.position.as_dict() if estimate.position else None,
        "covariance": estimate.covariance,
        "timing_sigma_s": estimate.timing_sigma,
        "reason": estimate.reason,
    }


async def publish_cloud(latest, settings, wall_origin, url, credential_file, device_id):
    from websockets.asyncio.client import connect

    delay = 1
    while True:
        try:
            async with connect(
                url,
                additional_headers={
                    "Authorization": f"Bearer {credential_file.read_text().strip()}"
                },
                max_size=8192,
                open_timeout=10,
                ping_interval=2,
                ping_timeout=5,
            ) as socket:
                setup = json.loads(await asyncio.wait_for(socket.recv(), 5))
                if setup.get("code") == "machine_already_connected":
                    raise TerminalConnectionError(
                        setup.get("message", "Computer already connected"), 3
                    )
                setup = validate(setup, device_id, settings.frame)
                if setup["type"] != "setup":
                    raise ValueError("Expected setup")
                connection = setup["connection_id"]
                heartbeat_at = time.monotonic()

                async def send(data):
                    await socket.send(
                        json.dumps(
                            {
                                "version": 1,
                                "device_id": device_id,
                                "connection_id": connection,
                                "frame_version": settings.frame,
                                "timestamp": datetime.now(UTC).isoformat(),
                                **data,
                            },
                            allow_nan=False,
                        )
                    )

                await send({"type": "ready", "capability": "measurement"})

                async def receive():
                    nonlocal heartbeat_at
                    async for raw in socket:
                        data = validate(json.loads(raw), device_id, settings.frame, connection)
                        if data["type"] == "heartbeat":
                            heartbeat_at = time.monotonic()
                        elif data["type"] == "target":
                            await send(
                                {
                                    "type": "ack",
                                    "command_id": data["command_id"],
                                    "accepted": False,
                                    "reason": "Measurement-only session",
                                }
                            )
                        else:
                            raise ValueError("Unexpected backend message")
                    raise ConnectionError("Backend disconnected")

                async def publish():
                    sequence = 0
                    while True:
                        if time.monotonic() - heartbeat_at > 5:
                            raise TimeoutError("Backend heartbeat expired")
                        estimate = latest[0]
                        if estimate:
                            await send(
                                {
                                    "type": "observation",
                                    "sequence": sequence,
                                    "source": "synthetic"
                                    if settings.protocol == "synthetic-json-v1"
                                    else "uwb",
                                    "observation": observation(estimate, wall_origin),
                                }
                            )
                            sequence += 1
                        else:
                            await send({"type": "heartbeat"})
                        await asyncio.sleep(0.2)

                async with asyncio.TaskGroup() as tasks:
                    tasks.create_task(receive())
                    tasks.create_task(publish())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if error := terminal_error(exc):
                # A denied cloud session must not stop local capture/estimation.
                log.error("Cloud publishing stopped: %s", error)
                return
            log.warning("Cloud unavailable (%s); local acquisition continues", type(exc).__name__)
        await asyncio.sleep(delay)
        delay = min(30, delay * 2)


async def run_measurements(settings, recording, *, capture_only=False, cloud=None):
    if not settings.uwb_port or (not capture_only and not settings.mavlink_port):
        raise ValueError("Configure uwb_port and, for estimation, mavlink_port")
    if settings.external_nav and (
        capture_only
        or not settings.protocol_verified
        or settings.firmware == "unverified"
        or settings.controller_firmware == "unverified"
        or settings.protocol == "synthetic-json-v1"
    ):
        raise ValueError(
            "External-nav bench output requires pinned, qualified hardware configuration"
        )
    if not settings.protocol_verified:
        log.warning("Protocol/timing configuration is unqualified; capture and bench use only")
    session = str(uuid.uuid4())
    start = time.monotonic()
    wall_origin = time.time() - start
    recorder = Recorder(recording, settings, session, wall_origin)
    pipeline = Pipeline(settings, session)
    latest = [None]
    cloud_task = None
    port = link = None
    try:
        # Nonblocking serial; runtime never sends provisioning commands to the collector.
        port = serial.Serial(settings.uwb_port, settings.uwb_baud, timeout=0, exclusive=True)
        link = AircraftLink(settings) if settings.mavlink_port else None
        reader = LineReader()
        if cloud:
            cloud_task = asyncio.create_task(publish_cloud(latest, settings, wall_origin, **cloud))
        tick_at = 0
        while True:
            now = time.monotonic()
            for sample in link.poll(now) if link else ():
                recorder.write({"type": "aircraft", "at": now, "sample": asdict(sample)})
                pipeline.aircraft(sample)
            for event in link.events if link else ():
                recorder.write(event)
            if (
                link
                and pipeline.controller_session
                and pipeline.controller_session != link.clock.session
            ):
                pipeline.samples.clear()
                pipeline.estimator.reset()
                latest[0] = pipeline.estimator.invalid(now, "controller_reset")
            for raw in reader.feed(port.read(4096)):
                recorder.raw(raw, now)
                if not capture_only:
                    result = pipeline.range(raw, now)
                    latest[0] = result
                    recorder.write({"type": "estimate", "at": now, "result": result.as_dict()})
                    if result.kind == "measured":
                        sent = link.send_estimate(result, pipeline.estimator.aircraft, now)
                        if sent:
                            recorder.write(
                                {"type": "external_nav", "at": now, "result": result.as_dict()}
                            )
            if not capture_only and now - tick_at >= 0.02:
                tick_at = now
                # Preserve the freshly corrected result until the next acquisition cycle.
                if latest[0] is None or latest[0].estimated_at < now - 0.005:
                    recorder.write({"type": "tick", "at": now})
                    latest[0] = pipeline.estimator.predict(now)
            await asyncio.sleep(0.005)
    finally:
        if cloud_task:
            cloud_task.cancel()
            await asyncio.gather(cloud_task, return_exceptions=True)
        if port:
            port.close()
        if link:
            link.close()
        recorder.close()
