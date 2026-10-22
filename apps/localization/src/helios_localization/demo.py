"""Hardware-free sensor simulation through the live parser and estimator."""

import asyncio
import json
import logging
import math
import time
import uuid

import numpy as np

from .coordinator import CommandCoordinator
from .measurements import AircraftSample
from .replay import Pipeline
from .runtime import observation
from .transport import run


def synthetic_epoch(settings, sequence, at, elapsed, rng, position=None):
    """A slow ellipse with calibrated, noisy slant ranges (metres)."""
    if position is None:
        position = [1.5 + 0.7 * math.cos(elapsed * 0.3), 1.5 + 0.6 * math.sin(elapsed * 0.3), 1.0]
    position = np.asarray(position)
    ranges = {
        anchor.id: float(
            np.linalg.norm(position - np.asarray(anchor.xyz))
            + anchor.bias
            + rng.normal(0, anchor.sigma * 0.25)
        )
        for anchor in settings.anchors
    }
    return json.dumps(
        {
            "format": "helios-synthetic-ranges-v1",
            "tag_id": settings.tag_id,
            "sequence": sequence,
            "acquired_at": at,
            "ranges": ranges,
        }
    ).encode()


def dropout(elapsed):
    phase = elapsed % 12
    return 4 <= phase < 4.08 or 8 <= phase < 8.6


async def run_demo(settings, cloud):
    if settings.protocol != "synthetic-json-v1" or settings.external_nav:
        raise ValueError("Demo requires synthetic protocol and external_nav=false")
    if any(settings.tag_offset_frd):
        raise ValueError("Demo geometry requires a zero antenna offset")
    coordinator = SensorDemoCoordinator(settings)
    pipeline = coordinator.pipeline
    latest = coordinator.latest
    start = time.monotonic()
    publisher = asyncio.create_task(
        run(**cloud, frame_version="dummy-enu-v1", coordinator=coordinator)
    )
    rng = np.random.default_rng(2026)
    sequence = 0
    next_range = start
    previous_kind = None
    try:
        while True:
            now = time.monotonic()
            elapsed = now - start
            coordinator.tick(now)
            position = coordinator.provider.position
            pipeline.aircraft(
                AircraftSample(
                    "synthetic-controller", now, now, position.z, settings.altitude_sigma, 0, 0, 0
                )
            )
            if now >= next_range and not dropout(elapsed):
                next_range = now + 0.05
                latest[0] = pipeline.range(
                    synthetic_epoch(
                        settings, sequence, now, elapsed, rng, [position.x, position.y, position.z]
                    ),
                    now,
                )
                sequence += 1
            else:
                latest[0] = pipeline.estimator.predict(now)
            if latest[0].kind != previous_kind:
                logging.info("Synthetic UWB: %s (%s)", latest[0].kind, latest[0].reason or "valid")
                previous_kind = latest[0].kind
            await asyncio.sleep(0.02)
    finally:
        publisher.cancel()
        await asyncio.gather(publisher, return_exceptions=True)


class SensorDemoCoordinator(CommandCoordinator):
    """Existing dummy command lifecycle plus independent synthetic sensor diagnostics."""

    def __init__(self, settings):
        self.settings = settings
        self.pipeline = Pipeline(settings, str(uuid.uuid4()))
        self.latest = [None]
        self.wall_origin = time.time() - time.monotonic()
        super().__init__()

    def reset(self):
        super().reset()
        self.pipeline.estimator.reset()
        self.latest[0] = None

    def telemetry(self):
        data = super().telemetry()
        if self.latest[0]:
            data["simulated_localization"] = {
                "frame": self.settings.frame,
                "observation": observation(self.latest[0], self.wall_origin),
            }
        return data
