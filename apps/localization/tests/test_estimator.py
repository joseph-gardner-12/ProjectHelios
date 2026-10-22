import json
import math
from dataclasses import asdict, replace
from unittest.mock import patch

import numpy as np
import pytest

from helios_localization.config import Anchor, Settings, load_settings
from helios_localization.frames import body_to_enu, enu_to_ned
from helios_localization.measurements import AircraftSample, RangeEpoch
from helios_localization.models import Position
from helios_localization.ranging import LineReader, parse_record
from helios_localization.replay import Recorder, replay
from helios_localization.solver import Estimator


@pytest.fixture
def settings():
    return Settings(
        "test-enu-v1",
        tuple(
            Anchor(f"A{i}", xyz, sigma=0.05)
            for i, xyz in enumerate(
                [(0.0, 0.0, 2.0), (3.0, 0.0, 2.0), (3.0, 3.0, 2.0), (0.0, 3.0, 2.0)]
            )
        ),
        timing_sigma=0.001,
    )


def sample(t, z=1.0, session="fc"):
    return AircraftSample(session, t, t, z, 0.05, 0.0, 0.0, 0.0, 0.001)


def epoch(cfg, t=0.0, sequence=0, position=(1.0, 1.0, 1.0), noise=None):
    ranges = {a.id: math.dist(position, a.xyz) + a.bias for a in cfg.anchors}
    if noise:
        ranges = {key: value + noise.get(key, 0.0) for key, value in ranges.items()}
    return RangeEpoch("test", sequence, cfg.frame, t, t, 0.001, ranges)


def test_position_bias_and_signed_coordinates(settings):
    cfg = replace(settings, anchors=tuple(replace(a, bias=0.12) for a in settings.anchors))
    estimate = Estimator(cfg).correct(epoch(cfg, position=(-0.5, 1.0, 1.0)), sample(0.0))
    assert estimate.kind == "measured", estimate.reason
    assert estimate.position.x == pytest.approx(-0.5, abs=1e-5)
    assert estimate.position.y == pytest.approx(1.0, abs=1e-5)
    assert np.linalg.eigvalsh(estimate.covariance).min() > 0


def test_prediction_timeout_and_reinitialization(settings):
    estimator = Estimator(settings)
    for i in range(10):
        t = i * 0.05
        result = estimator.correct(epoch(settings, t, i, (1 + t, 1.0, 1.0)), sample(t))
        assert result.kind == "measured", result.reason
    predicted = estimator.predict(0.5)
    assert predicted.kind == "predicted"
    assert predicted.measurement_at == pytest.approx(0.45)
    assert predicted.position.x > result.position.x
    assert predicted.state_covariance[0][0] > result.state_covariance[0][0]
    assert estimator.predict(0.551).kind == "invalid"
    again = estimator.correct(epoch(settings, 0.6, 12, (1.6, 1.0, 1.0)), sample(0.6))
    assert again.kind == "measured"
    assert estimator.state[2] == 0  # velocity is not carried across prolonged gaps


def test_invalid_inputs_and_controller_reset(settings):
    estimator = Estimator(settings)
    first = epoch(settings)
    assert estimator.correct(first, sample(0)).kind == "measured"
    assert estimator.correct(first, sample(0)).reason == "duplicate_epoch"
    assert estimator.correct(epoch(settings, 0.05, 1), sample(-1)).reason == "sensor_timing"
    assert estimator.predict(0.05).kind == "invalid"
    result = estimator.correct(epoch(settings, 0.06, 2), sample(0.06, session="reboot"))
    assert result.kind == "measured"
    assert estimator.state[2] == 0
    wrong = replace(epoch(settings, 0.07, 3), frame="other")
    assert estimator.correct(wrong, sample(0.07)).reason == "frame_mismatch"
    assert estimator.correct(epoch(settings, 0.08, 4), None).reason == "altitude_unavailable"


def test_four_ranges_outliers_and_convergence(settings):
    estimator = Estimator(settings)
    missing = replace(epoch(settings), ranges={"A0": 1.0, "A1": 1.0, "A2": 1.0})
    assert estimator.correct(missing, sample(0)).reason == "four_ranges_required"
    assert estimator.correct(epoch(settings, 0.01, 1), sample(0.01)).kind == "measured"
    outlier = epoch(settings, 0.05, 2, noise={"A0": 2.0})
    assert estimator.correct(outlier, sample(0.05)).reason == "innovation_gate"
    with patch("helios_localization.solver.least_squares", side_effect=ValueError):
        assert Estimator(settings).correct(epoch(settings), sample(0)).reason == "solver_failed"


def test_geometry_and_impossible_range(settings):
    cfg = replace(settings, anchors=tuple(Anchor(f"A{i}", (float(i), 0.0, 1.0)) for i in range(4)))
    result = Estimator(cfg).correct(epoch(cfg, position=(1.5, 0.0, 1.0)), sample(0))
    assert result.kind == "invalid" and result.reason == "poor_geometry"
    bad = replace(epoch(settings), ranges={f"A{i}": 0.01 for i in range(4)})
    assert Estimator(settings).correct(bad, sample(0)).reason == "impossible_range"


def test_tag_offset_and_frame(settings):
    cfg = replace(settings, tag_offset_frd=(0.2, 0.1, -0.05))
    offset = body_to_enu(0, 0, 0) @ cfg.tag_offset_frd
    reference = np.array([1.0, 1.0, 1.0])
    estimate = Estimator(cfg).correct(epoch(cfg, position=reference + offset), sample(0))
    assert estimate.kind == "measured"
    assert estimate.position.x == pytest.approx(1.0, abs=1e-5)
    assert estimate.position.y == pytest.approx(1.0, abs=1e-5)
    assert enu_to_ned(Position(1, 2, 3), (10, 20, 30)).tolist() == [12, 21, 27]


def test_noise_uncertainty_and_motion_lag(settings):
    random = np.random.default_rng(42)
    estimator = Estimator(settings)
    corrected_errors, range_errors, sigmas = [], [], []
    for i in range(100):
        t = i * 0.04 + (i % 3) * 0.001
        truth = (1.0 + 0.2 * math.sin(t), 1.0 + 0.15 * math.cos(t), 1.0)
        noisy = epoch(
            settings, t, i, truth, {a.id: float(random.normal(0, 0.05)) for a in settings.anchors}
        )
        result = estimator.correct(noisy, sample(t))
        baseline = Estimator(settings).correct(noisy, sample(t))
        assert result.kind == baseline.kind == "measured"
        corrected_errors.append(math.dist((result.position.x, result.position.y), truth[:2]))
        range_errors.append(math.dist((baseline.position.x, baseline.position.y), truth[:2]))
        sigmas.append(math.sqrt(np.linalg.eigvalsh(np.asarray(result.covariance)[:2, :2]).max()))
    assert np.mean(corrected_errors) < np.mean(range_errors)
    assert np.mean(np.array(corrected_errors) <= 3 * np.array(sigmas)) > 0.9


def test_height_noise_increases_horizontal_uncertainty(settings):
    low = Estimator(settings).correct(epoch(settings, position=(0.3, 0.3, 1)), sample(0))
    high = Estimator(settings).correct(
        epoch(settings, position=(0.3, 0.3, 1)), replace(sample(0), z_sigma=0.3)
    )
    assert np.trace(np.asarray(high.covariance)[:2, :2]) > np.trace(
        np.asarray(low.covariance)[:2, :2]
    )


def test_record_boundaries_and_parser(settings):
    reader = LineReader()
    assert reader.feed(b"hello") == []
    assert reader.feed(b"\r\nworld\n") == [b"hello", b"world"]
    assert reader.feed(b"x" * 9000 + b"\nok\n") == [b"ok"]
    cfg = replace(settings, protocol="mauwb-at-v1.1.6")
    raw = (
        b"AT+RANGE=tid:0,mask:0f,seq:205,range:(200,210,220,230,0,0,0,0),"
        b"ancid:(3,2,1,0,-1,-1,-1,-1)"
    )
    parsed = parse_record(raw, cfg, "s", 10)
    assert parsed.ranges == {"A3": 2.0, "A2": 2.1, "A1": 2.2, "A0": 2.3}
    assert parsed.timing_source == "receive_estimate"
    for bad in (raw.replace(b"tid:0", b"tid:1"), b"Hello! ESP32", raw + b",rssi:(1)"):
        with pytest.raises(ValueError):
            parse_record(bad, cfg, "s", 10)


def test_deterministic_replay_and_limits(settings, tmp_path):
    path = tmp_path / "capture.jsonl"
    recorder = Recorder(path, settings, "test", 1700000000.0)
    for i in range(3):
        t = i * 0.05
        recorder.write({"type": "aircraft", "at": t, "sample": asdict(sample(t))})
        data = {
            "format": "helios-synthetic-ranges-v1",
            "tag_id": 0,
            "sequence": i,
            "acquired_at": t,
            "ranges": epoch(settings, t, i).ranges,
        }
        recorder.raw(json.dumps(data).encode(), t)
    recorder.write({"type": "tick", "at": 0.11})
    recorder.close()
    first = [r.as_dict() for r in replay(path, settings)]
    assert first == [r.as_dict() for r in replay(path, settings)]
    assert [r["kind"] for r in first] == ["measured", "measured", "measured", "predicted"]
    with pytest.raises(ValueError):
        list(replay(path, replace(settings, max_speed=4)))
    with pytest.raises(OSError):
        Recorder(tmp_path / "small.jsonl", replace(settings, recording_max_bytes=10), "s", 0.0)


def test_configuration_validation(settings, tmp_path):
    with pytest.raises(ValueError):
        replace(settings, prediction_limit=0.101)
    with pytest.raises(ValueError):
        replace(settings, anchors=settings.anchors[:3])
    with pytest.raises(ValueError):
        replace(settings, max_age=float("nan"))
    assert load_settings("apps/localization/configs/survey.example.toml").external_nav is False


def test_additional_anchors_allow_outlier_rejection(settings):
    cfg = replace(
        settings,
        anchors=settings.anchors
        + (
            Anchor("A4", (1.5, 0.0, 2.0), sigma=0.05),
            Anchor("A5", (1.5, 3.0, 2.0), sigma=0.05),
        ),
    )
    estimator = Estimator(cfg)
    assert estimator.correct(epoch(cfg), sample(0)).kind == "measured"
    result = estimator.correct(epoch(cfg, 0.05, 1, noise={"A0": 2.0}), sample(0.05))
    assert result.kind == "measured", result.reason
    assert result.position.x == pytest.approx(1.0, abs=0.02)
    assert result.position.y == pytest.approx(1.0, abs=0.02)


def test_shared_height_bias_coverage_and_persistent_range_bias(settings):
    random = np.random.default_rng(81)
    covered = []
    for trial in range(30):
        estimator = Estimator(settings)
        height_bias = float(random.normal(0, 0.15))
        for i in range(12):
            t = i * 0.04
            truth = (0.4, 0.6, 1.0)
            noisy = epoch(
                settings,
                t,
                i,
                truth,
                {a.id: float(random.normal(0, 0.03)) for a in settings.anchors},
            )
            result = estimator.correct(noisy, replace(sample(t, z=1 + height_bias), z_sigma=0.15))
        assert result.kind == "measured"
        error = math.dist((result.position.x, result.position.y), truth[:2])
        sigma = math.sqrt(np.linalg.eigvalsh(np.asarray(result.covariance)[:2, :2]).max())
        covered.append(error <= 3 * sigma)
        assert np.linalg.eigvalsh(result.covariance).min() >= -1e-9
    assert np.mean(covered) >= 0.9
    # A persistent gross bias must fail a quality gate rather than appear precise.
    result = Estimator(settings).correct(
        epoch(settings, noise={a.id: 1.0 for a in settings.anchors}), sample(0)
    )
    assert result.kind == "invalid"
