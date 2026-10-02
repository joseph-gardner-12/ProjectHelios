"""Protocol v1 validation; mirrored by localization and shared contract fixtures."""

import math
import uuid
from datetime import datetime

VERSION = 1
FRAME = "dummy-enu-v1"
ACTIVE = ("pending_ack", "accepted")


def coordinates(value):
    if not isinstance(value, dict) or set(value) != {"x", "y", "z"}:
        raise ValueError("Expected x, y, z coordinates")
    if any(
        type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 3.048
        for v in value.values()
    ):
        raise ValueError("Coordinates must be finite and between 0 and 3.048 metres")
    return value


def identifier(value):
    return str(uuid.UUID(str(value)))


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return parsed


def validate_message(data, device, connection):
    if (
        not isinstance(data, dict)
        or type(data.get("version")) is not int
        or data.get("version") != VERSION
    ):
        raise ValueError("Unsupported protocol")
    if data.get("device_id") != str(device.id) or data.get("connection_id") != str(connection):
        raise ValueError("Wrong connection")
    if data.get("frame_version") != device.frame_version:
        raise ValueError("Wrong coordinate frame")
    timestamp(data["timestamp"])
    fields = {
        "ready": set(),
        "heartbeat": set(),
        "ack": {"command_id", "accepted", "reason"},
        "arrival": {"command_id"},
        "position": {
            "sequence",
            "position",
            "source",
            "state",
            "command_id",
            "completed_command_id",
        },
    }
    base = {"version", "type", "device_id", "connection_id", "frame_version", "timestamp"}
    if set(data) - (base | fields.get(data.get("type"), set())):
        raise ValueError("Unexpected message fields")
    if "reason" in data and not isinstance(data["reason"], str):
        raise ValueError("Reason must be a string")
    if data.get("type") not in {"ready", "position", "ack", "arrival", "heartbeat"}:
        raise ValueError("Unsupported message")
    if data["type"] in {"ack", "arrival"}:
        identifier(data["command_id"])
    if data["type"] == "ack" and type(data.get("accepted")) is not bool:
        raise ValueError("Acknowledgment needs accepted boolean")
    if data["type"] == "position":
        coordinates(data["position"])
        if type(data.get("sequence")) is not int or data["sequence"] < 0:
            raise ValueError("Invalid sequence")
        if data.get("source") != "dummy" or data.get("state") not in {"idle", "moving"}:
            raise ValueError("Only explicit dummy positions supported")
        for key in ("command_id", "completed_command_id"):
            if data.get(key) is not None:
                identifier(data[key])
    return data
