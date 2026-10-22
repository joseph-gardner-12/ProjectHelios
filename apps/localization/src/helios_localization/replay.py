"""Bounded append-only recordings; replay has no aircraft/network dependencies."""

import base64
import json
import math
from dataclasses import asdict
from pathlib import Path

from .measurements import AircraftSample
from .ranging import MAX_RECORD, parse_record
from .solver import Estimator


class Recorder:
    def __init__(self, path, settings, session, wall_origin):
        self.stream = Path(path).open("x", encoding="utf-8")
        self.limit = settings.recording_max_bytes
        self.size = 0
        try:
            self.write(
                {
                    "type": "manifest",
                    "version": 1,
                    "session": session,
                    "wall_origin": wall_origin,
                    "settings": asdict(settings),
                    "qualification": "hardware qualification pending",
                }
            )
        except BaseException:
            self.stream.close()
            raise

    def write(self, record):
        line = json.dumps(record, allow_nan=False, separators=(",", ":")) + "\n"
        size = len(line.encode())
        if self.size + size > self.limit:
            raise OSError("Recording size limit reached")
        self.stream.write(line)
        self.stream.flush()
        self.size += size

    def raw(self, raw, at):
        self.write({"type": "uwb", "at": at, "raw": base64.b64encode(raw).decode()})

    def close(self):
        self.stream.close()


class Pipeline:
    def __init__(self, settings, session):
        self.settings = settings
        self.session = session
        self.estimator = Estimator(settings)
        self.samples = []
        self.controller_session = None
        self.last_source_sequence = None
        self.range_generation = 0

    def aircraft(self, sample):
        if self.controller_session != sample.session:
            self.samples.clear()
            self.estimator.reset()
            self.controller_session = sample.session
        self.samples.append(sample)
        self.samples = self.samples[-256:]

    def range(self, raw, at):
        try:
            epoch = parse_record(raw, self.settings, self.session, at)
        except ValueError, KeyError, TypeError, UnicodeError:
            return self.estimator.invalid(at, "range_parse_error")
        if self.settings.protocol == "mauwb-at-v1.1.6":
            if self.last_source_sequence is not None and epoch.sequence < self.last_source_sequence:
                # Counter width/reset semantics are unverified. Start a new session
                # rather than invent a rollover modulus or carry velocity across it.
                self.range_generation += 1
                self.estimator.reset()
            self.last_source_sequence = epoch.sequence
            from dataclasses import replace

            epoch = replace(epoch, session=f"{self.session}:{self.range_generation}")
        # Nearest already-received sample; no extrapolated altitude masquerading as a sample.
        eligible = [s for s in self.samples if s.received_at <= at]
        sample = min(eligible, key=lambda s: abs(s.acquired_at - epoch.acquired_at), default=None)
        return self.estimator.correct(epoch, sample)


def replay(path, settings):
    with Path(path).open(encoding="utf-8") as stream:
        first = stream.readline(65537)
        manifest = json.loads(first)
        if manifest.get("type") != "manifest" or manifest.get("version") != 1:
            raise ValueError("Unsupported recording")
        # Changes in tuning require a new recording/explicit conversion, not silent replay drift.
        if manifest["settings"] != json.loads(json.dumps(asdict(settings))):
            raise ValueError("Recording configuration does not match supplied survey")
        pipeline = Pipeline(settings, manifest["session"])
        previous = -1.0
        while line := stream.readline(65537):
            if len(line) > 65536:
                raise ValueError("Oversized recording entry")
            event = json.loads(line)
            kind = event["type"]
            if kind not in {"aircraft", "uwb", "tick"}:
                continue
            at = event["at"]
            if type(at) not in (float, int) or not math.isfinite(at) or at < previous:
                raise ValueError("Recording time moved backwards")
            previous = at
            if kind == "aircraft":
                pipeline.aircraft(AircraftSample(**event["sample"]))
            elif kind == "uwb":
                raw = base64.b64decode(event["raw"], validate=True)
                if len(raw) > MAX_RECORD:
                    raise ValueError("Oversized UWB record")
                yield pipeline.range(raw, at)
            else:
                yield pipeline.estimator.predict(at)
