import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from helios_localization.coordinator import CommandCoordinator
from helios_localization.protocol import coordinates, validate

FIXTURES = Path(__file__).resolve().parents[3] / "contracts/control-v1/coordinates.fixtures.json"


@pytest.mark.parametrize("case", json.loads(FIXTURES.read_text()), ids=lambda case: case["name"])
def test_coordinate_contract(case):
    if case["valid"]:
        assert coordinates(case["position"]).as_dict() == case["position"]
    else:
        with pytest.raises(ValueError):
            coordinates(case["position"])


def target(x=0.5):
    return {
        "command_id": str(uuid.uuid4()),
        "target": {"x": x, "y": 0, "z": 0},
        "expires_at": (datetime.now(UTC) + timedelta(seconds=3)).isoformat(),
    }


def test_ack_before_motion_and_arrival_dwell():
    coordinator = CommandCoordinator()
    ack, candidate = coordinator.prepare(target(), datetime.now(UTC))
    assert ack["accepted"] and coordinator.active is None
    coordinator.start(candidate, 0)
    coordinator.tick(0.5)
    assert coordinator.provider.position.x == 0.25
    coordinator.tick(1)
    assert coordinator.provider.position.x == 0.5 and coordinator.active
    coordinator.tick(1.5)
    assert coordinator.completed_id == candidate.command_id and coordinator.active is None


def test_duplicate_does_not_restart_and_busy_rejects():
    coordinator = CommandCoordinator()
    data = target()
    ack, candidate = coordinator.prepare(data, datetime.now(UTC))
    coordinator.start(candidate, 0)
    coordinator.tick(0.5)
    duplicate, candidate = coordinator.prepare(data, datetime.now(UTC))
    assert duplicate == ack and candidate is None
    rejected, _ = coordinator.prepare(target(), datetime.now(UTC))
    assert not rejected["accepted"]
    assert coordinator.provider.position.x == 0.25


def test_disconnect_clears_target_but_keeps_position():
    coordinator = CommandCoordinator()
    _, candidate = coordinator.prepare(target(), datetime.now(UTC))
    coordinator.start(candidate, 0)
    coordinator.tick(0.5)
    coordinator.reset()
    coordinator.tick(100)
    assert coordinator.telemetry()["state"] == "idle"
    assert coordinator.provider.position.x == 0.25
    assert coordinator.completed_id is None


def test_timeout_and_expired_command():
    coordinator = CommandCoordinator()
    data = target()
    data["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    assert not coordinator.prepare(data, datetime.now(UTC))[0]["accepted"]
    _, candidate = coordinator.prepare(target(), datetime.now(UTC))
    coordinator.start(candidate, 0)
    with pytest.raises(TimeoutError):
        coordinator.tick(30)


def test_wrong_frame_or_connection():
    device, connection = str(uuid.uuid4()), str(uuid.uuid4())
    message = {
        "version": 1,
        "type": "heartbeat",
        "device_id": device,
        "connection_id": connection,
        "frame_version": "dummy-enu-v1",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    validate(message, device, "dummy-enu-v1", connection)
    with pytest.raises(ValueError):
        validate(message, device, "real-survey-v1", connection)
    with pytest.raises(ValueError):
        validate(message, device, "dummy-enu-v1", str(uuid.uuid4()))


def test_shared_backend_message_fixtures():
    cases = json.loads((FIXTURES.parent / "messages.fixtures.json").read_text())
    for case in cases:
        if case["direction"] != "backend":
            continue
        if case["valid"]:
            validate(
                case["message"],
                "11111111-1111-4111-8111-111111111111",
                "dummy-enu-v1",
                "22222222-2222-4222-8222-222222222222",
            )
        else:
            with pytest.raises((ValueError, KeyError, TypeError)):
                validate(
                    case["message"],
                    "11111111-1111-4111-8111-111111111111",
                    "dummy-enu-v1",
                    "22222222-2222-4222-8222-222222222222",
                )
