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
