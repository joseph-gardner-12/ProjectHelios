import base64
import json
import math
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pytest

from helios_localization.calibration import (
    calibrate_recording,
    fit_square,
    write_square_survey,
)
from helios_localization.config import load_settings
from helios_localization.measurements import AircraftSample, RangeEpoch
from helios_localization.solver import Estimator

SURVEY = Path("apps/localization/configs/table-bench.toml")


def distances(side, x, y):
    return [math.hypot(x - ax, y - ay) for ax, ay in [(0, 0), (side, 0), (0, side), (side, side)]]


@pytest.mark.parametrize("side,x,y", [(0.6, 0.3, 0.3), (1.2, 0.42, 0.76), (3, 1.7, 0.9)])
def test_recovers_size_with_off_center_tag_and_centimetre_noise(side, x, y):
    rng = np.random.default_rng(42)
    ranges = np.array(distances(side, x, y)) + rng.normal(0, 0.005, (60, 4))
    result = fit_square(ranges)
    assert result.side_m == pytest.approx(side, abs=0.01)
    assert result.tag_xy_m == pytest.approx((x, y), abs=0.01)


def test_rejects_motion_and_inconsistent_geometry():
    moving = [distances(2, 0.5 + i * 0.02, 1) for i in range(50)]
    with pytest.raises(ValueError, match="hold the tag"):
        fit_square(moving)
    with pytest.raises(ValueError, match="do not fit"):
        fit_square([[3.67, 1.61, 1.50, 3.29]] * 40)


def test_interior_assumption_is_explicit_not_inferred_from_ranges():
    # Exterior points may admit a different, smaller square with an interior point.
    # A small residual alone cannot prove physical placement or square dimensions.
    result = fit_square([distances(2, 3, 3)] * 40)
    assert result.side_m != pytest.approx(2)
    assert result.fit_rms_m < 1e-6


@pytest.mark.parametrize(
    "ranges",
    [
        [],
        [[1, 1, 1, 1]] * 29,
        [[1, 1, 1]] * 40,
        [[1, 0, 1, 1]] * 40,
        [[1, float("nan"), 1, 1]] * 40,
    ],
)
def test_requires_complete_positive_sample_window(ranges):
    with pytest.raises(ValueError, match="30 complete"):
        fit_square(ranges)


def write_recording(path, cfg, *, partial=False, duplicate=False, old=False):
    rows = [{"type": "manifest", "version": 1, "settings": asdict(cfg)}]
    cm = [round(r * 100) for r in distances(1.2, 0.43, 0.74)]
    for i in range(60):
        ids = "0,2,3,-1" if partial else "0,2,3,4"
        raw = (
            f"AT+RANGE=tid:1,mask:1D,seq:{0 if duplicate else i},"
            f"range:({','.join(map(str, cm))}),ancid:({ids})\n"
        )
        rows.append({"type": "uwb", "at": i * 0.15, "raw": base64.b64encode(raw.encode()).decode()})
    if old:
        rows.append({"type": "tick", "at": 25})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_recording_to_new_survey_then_real_estimator(tmp_path):
    cfg = load_settings(SURVEY)
    recording = tmp_path / "ranges.jsonl"
    write_recording(recording, cfg)
    result = calibrate_recording(recording, cfg)
    assert result.side_m == pytest.approx(1.2, abs=0.01)
    output = tmp_path / "square.toml"
    write_square_survey(SURVEY, output, result)
    square = load_settings(output)
    assert square.frame != cfg.frame
    assert not square.external_nav and not square.protocol_verified
    assert square.uwb_port == cfg.uwb_port
    assert square.metadata["square_calibration"]["samples"] == 60
    assert square.anchors[0].xyz[:2] == (0, 0)
    with pytest.raises(FileExistsError):
        write_square_survey(SURVEY, output, result)
    # Calibrate once, then track a different position without changing the survey.
    expected = (0.71, 0.39, square.fixed_height)
    epoch = RangeEpoch(
        "bench",
        1,
        square.frame,
        1,
        1,
        0.02,
        {a.id: math.dist(expected, a.xyz) for a in square.anchors},
    )
    sample = AircraftSample("bench", 1, 1, square.fixed_height, 0.15, 0, 0, 0)
    estimate = Estimator(square).correct(epoch, sample)
    assert estimate.kind == "measured", estimate.reason
    assert (estimate.position.x, estimate.position.y) == pytest.approx(expected[:2], abs=0.01)


@pytest.mark.parametrize("kwargs", [{"partial": True}, {"duplicate": True}, {"old": True}])
def test_no_merging_partial_epochs_or_reusing_stale_duplicates(tmp_path, kwargs):
    cfg = load_settings(SURVEY)
    recording = tmp_path / "ranges.jsonl"
    write_recording(recording, cfg, **kwargs)
    with pytest.raises(ValueError, match="30 complete"):
        calibrate_recording(recording, cfg)


def test_rejects_wrong_survey_and_ignores_live_incomplete_tail(tmp_path):
    cfg = load_settings(SURVEY)
    recording = tmp_path / "ranges.jsonl"
    write_recording(recording, cfg)
    with recording.open("a") as stream:
        stream.write('{"type":')
    assert calibrate_recording(recording, cfg).samples == 60
    with pytest.raises(ValueError, match="does not match"):
        calibrate_recording(recording, replace(cfg, tag_id=2))
