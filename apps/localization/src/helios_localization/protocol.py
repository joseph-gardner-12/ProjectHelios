import math
import uuid
from datetime import datetime

from .models import Position, Target


def coordinates(value):
    if not isinstance(value, dict) or set(value) != {"x", "y", "z"}:
        raise ValueError("Expected x, y, z coordinates")
    if any(
        type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 3.048
        for v in value.values()
    ):
        raise ValueError("Coordinates outside dummy bounds")
    return Position(**value)


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp must be a string")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp needs timezone")
    return result


def validate(data, device_id, frame_version, connection_id=None):
    if (
        not isinstance(data, dict)
        or type(data.get("version")) is not int
        or data.get("version") != 1
    ):
        raise ValueError("Unsupported protocol")
    if data.get("device_id") != device_id or data.get("frame_version") != frame_version:
        raise ValueError("Device or frame mismatch")
    uuid.UUID(data["connection_id"])
    if connection_id and data["connection_id"] != connection_id:
        raise ValueError("Connection mismatch")
    timestamp(data["timestamp"])
    if data.get("type") not in {"setup", "target", "heartbeat"}:
        raise ValueError("Unknown backend message")
    return data


def target(data):
    uuid.UUID(data["command_id"])
    return Target(data["command_id"], coordinates(data["target"]), timestamp(data["expires_at"]))
