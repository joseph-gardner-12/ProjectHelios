import asyncio
import json
import math
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from helios_localization.config import load_settings
from helios_localization.measurements import AircraftSample
from helios_localization.replay import replay
from helios_localization.runtime import observation, run_measurements
from helios_localization.solver import Estimator


def test_live_pipeline_survives_cloud_failure_and_cleans_up(tmp_path):
    cfg = replace(
        load_settings("apps/localization/configs/survey.example.toml"),
        uwb_port="fake",
        mavlink_port="fake",
    )
    port = Mock()
    link = Mock(events=[])
    link.clock.session = "fc"
    at, sequence = [0.0], [0]

    def poll(now):
        at[0] = now
        return [AircraftSample("fc", now, now, 1.0, 0.1, 0, 0, 0, 0.001)]

    def read(_):
        data = {
            "format": "helios-synthetic-ranges-v1",
            "tag_id": 0,
            "sequence": sequence[0],
            "acquired_at": at[0],
            "ranges": {a.id: math.dist((1.0, 1.0, 1.0), a.xyz) for a in cfg.anchors},
        }
        sequence[0] += 1
        return json.dumps(data).encode() + b"\n"

    async def cloud(*args, **kwargs):
        return  # rejected cloud credential does not stop measurement service

    real_sleep = asyncio.sleep

    async def sleep(_):
        await real_sleep(0)
        if sequence[0] >= 3:
            raise asyncio.CancelledError

    link.poll.side_effect = poll
    port.read.side_effect = read
    path = tmp_path / "live.jsonl"
    with (
        patch("helios_localization.runtime.serial.Serial", return_value=port),
        patch("helios_localization.runtime.AircraftLink", return_value=link),
        patch("helios_localization.runtime.publish_cloud", side_effect=cloud),
        patch("helios_localization.runtime.asyncio.sleep", side_effect=sleep),
        patch(
            "helios_localization.runtime.time",
            SimpleNamespace(monotonic=Mock(side_effect=[0.0, 0.05, 0.1, 0.15]), time=time.time),
        ),
    ):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(run_measurements(cfg, path, cloud={"url": "unused"}))
    port.close.assert_called_once()
    link.close.assert_called_once()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert sum(row["type"] == "uwb" for row in rows) == 3
    results = list(replay(path, cfg))
    assert len([r for r in results if r.kind == "measured"]) == 3
    assert all(r.kind == "measured" for r in results)


def test_external_output_requires_qualified_real_input(tmp_path):
    cfg = replace(
        load_settings("apps/localization/configs/survey.example.toml"),
        external_nav=True,
        uwb_port="unused",
        mavlink_port="unused",
    )
    with pytest.raises(ValueError, match="qualified"):
        asyncio.run(run_measurements(cfg, tmp_path / "capture.jsonl"))
    assert not (tmp_path / "capture.jsonl").exists()


def test_invalid_observation_before_first_sample_has_explicit_identity():
    cfg = load_settings("apps/localization/configs/survey.example.toml")
    result = observation(Estimator(cfg).predict(1.0), 1700000000.0)
    assert result["kind"] == "invalid" and result["session"]
    assert result["measurement_time"] is None
    assert result["prediction_age_s"] is None


def test_collector_capture_does_not_require_aircraft_link(tmp_path):
    cfg = replace(load_settings("apps/localization/configs/survey.example.toml"), uwb_port="fake")
    port = Mock()
    port.read.return_value = b"Hello! ESP32 startup\n"

    async def stop(_):
        raise asyncio.CancelledError

    path = tmp_path / "raw.jsonl"
    with (
        patch("helios_localization.runtime.serial.Serial", return_value=port),
        patch("helios_localization.runtime.AircraftLink") as link,
        patch("helios_localization.runtime.asyncio.sleep", side_effect=stop),
    ):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(run_measurements(cfg, path, capture_only=True))
    link.assert_not_called()
    port.close.assert_called_once()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row["type"] for row in rows] == ["manifest", "uwb"]


def test_real_collector_bytes_reach_solver_recording_and_publisher(tmp_path):
    """Generated AT bytes exercise the hardware path, not the synthetic parser."""
    cfg = replace(
        load_settings("apps/localization/configs/survey.example.toml"),
        protocol="mauwb-at-v1.1.6",
        uwb_port="fake",
        fixed_height=1.0,
    )
    port = Mock()
    count = [0]
    captured = []
    ranges = [round(math.dist((1.0, 1.0, 1.0), a.xyz) * 100) for a in cfg.anchors]

    def read(_):
        count[0] += 1
        return (
            f"AT+RANGE=tid:0,mask:00,seq:{count[0]},"
            f"range:({','.join(map(str, ranges))},0,0,0,0),"
            "ancid:(0,1,2,3,-1,-1,-1,-1)\r\n"
        ).encode()

    async def publish(latest, *_args, **_kwargs):
        # The real publisher reads this exact latest-result slot.
        captured.append(latest)

    real_sleep = asyncio.sleep

    async def stop(_):
        await real_sleep(0)
        if count[0] == 3:
            raise asyncio.CancelledError

    path = tmp_path / "real-wire-format.jsonl"
    port.read.side_effect = read
    with (
        patch("helios_localization.runtime.serial.Serial", return_value=port),
        patch("helios_localization.runtime.AircraftLink") as link,
        patch("helios_localization.runtime.publish_cloud", side_effect=publish),
        patch("helios_localization.runtime.asyncio.sleep", side_effect=stop),
        patch(
            "helios_localization.runtime.time",
            SimpleNamespace(monotonic=Mock(side_effect=[0.0, 0.05, 0.1, 0.15]), time=time.time),
        ),
    ):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(run_measurements(cfg, path, cloud={"url": "unused"}))
    link.assert_not_called()
    port.close.assert_called_once()
    results = list(replay(path, cfg))
    assert len(results) == 3
    assert all(r.kind == "measured" and abs(r.position.x - 1) < 0.03 for r in results)
    assert captured[0][0].kind == "measured"
    assert results[-1].position == captured[0][0].position


@pytest.mark.parametrize(
    "changes",
    [
        {"fixed_height": float("nan")},
        {"fixed_height": True},
        {"fixed_height": 1, "external_nav": True},
        {"fixed_height": 1, "mavlink_port": "COM5"},
        {"fixed_height": 1, "tag_offset_frd": (0, 0, 0.1)},
    ],
)
def test_bench_height_cannot_masquerade_as_aircraft_altitude(changes):
    with pytest.raises(ValueError):
        replace(load_settings("apps/localization/configs/survey.example.toml"), **changes)
