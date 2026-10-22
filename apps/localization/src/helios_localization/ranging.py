"""Bounded acquisition and explicitly synthetic parsing pending verified captures."""

import json
import math
import re

from .measurements import RangeEpoch

MAX_RECORD = 8192


class LineReader:
    """Preserve partial reads; discard an oversized record through its newline."""

    def __init__(self):
        self.buffer = bytearray()
        self.discard = False

    def feed(self, chunk):
        records = []
        for byte in chunk:
            if byte == 10:
                if not self.discard and self.buffer:
                    records.append(bytes(self.buffer).rstrip(b"\r"))
                self.buffer.clear()
                self.discard = False
            elif not self.discard:
                self.buffer.append(byte)
                if len(self.buffer) > MAX_RECORD:
                    self.buffer.clear()
                    self.discard = True
        return records


def parse_record(raw, settings, session, received_at):
    if len(raw) > MAX_RECORD:
        raise ValueError("Record exceeds size limit")
    if settings.protocol == "mauwb-at-v1.1.6":
        return parse_mauwb(raw, settings, session, received_at)
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("format") != "helios-synthetic-ranges-v1":
        raise ValueError("Expected explicitly labelled synthetic ranges")
    if data.get("tag_id") != settings.tag_id:
        raise ValueError("Wrong tag")
    if type(data.get("sequence")) is not int or data["sequence"] < 0:
        raise ValueError("Invalid source sequence")
    ranges = data.get("ranges")
    if (
        not isinstance(ranges, dict)
        or not ranges
        or len(ranges) > 64
        or any(
            not isinstance(key, str)
            or type(value) not in (int, float)
            or not math.isfinite(value)
            or value <= 0
            for key, value in ranges.items()
        )
    ):
        raise ValueError("Invalid ranges in metres")
    acquired_at = data.get("acquired_at", received_at - settings.acquisition_delay)
    if type(acquired_at) not in (int, float) or not math.isfinite(acquired_at):
        raise ValueError("Invalid acquisition timestamp")
    return RangeEpoch(
        session,
        data["sequence"],
        settings.frame,
        acquired_at,
        received_at,
        settings.timing_sigma,
        ranges,
        "synthetic" if "acquired_at" in data else "receive_estimate",
    )


AT_RANGE = re.compile(
    rb"AT\+RANGE=tid:(\d+),mask:([0-9a-fA-F]{1,2}),seq:(\d+),"
    rb"range:\(([-0-9,]+)\),ancid:\(([-0-9,]+)\)"
)


def parse_mauwb(raw, settings, session, received_at):
    """Manual §3.15, strict v1.1.6 shape; hardware qualification still pending."""
    match = AT_RANGE.fullmatch(raw)
    if not match:
        raise ValueError("Not a v1.1.6 range report")
    tag, mask, sequence, distances, ids = match.groups()
    if int(tag) != settings.tag_id:
        raise ValueError("Wrong tag")
    distances = [int(v) for v in distances.split(b",")]
    ids = [int(v) for v in ids.split(b",")]
    if len(distances) != 8 or len(ids) != 8:
        raise ValueError("Expected eight range/anchor slots")
    valid = int(mask, 16)
    ranges = {}
    for slot, (distance, anchor) in enumerate(zip(distances, ids, strict=True)):
        if not valid & (1 << slot):
            continue
        key = f"A{anchor}"
        if anchor < 0 or distance <= 0 or key in ranges:
            raise ValueError("Invalid active anchor slot")
        ranges[key] = distance / 100.0
    return RangeEpoch(
        session,
        int(sequence),
        settings.frame,
        received_at - settings.acquisition_delay,
        received_at,
        settings.timing_sigma,
        ranges,
        "receive_estimate",
    )
