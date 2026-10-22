"""The dashboard demo exercises measured fixes, bounded prediction, and recovery."""

from pathlib import Path

import numpy as np

from helios_localization.config import load_settings
from helios_localization.demo import dropout, synthetic_epoch
from helios_localization.measurements import AircraftSample
from helios_localization.replay import Pipeline


def test_demo_cycle():
    settings = load_settings(Path(__file__).parents[1] / "configs/survey.example.toml")
    pipeline = Pipeline(settings, "demo-test")
    rng = np.random.default_rng(2026)
    measured = []
    kinds = set()
    sequence = 0
    for index in range(650):
        at = index * 0.02
        pipeline.aircraft(AircraftSample("controller", at, at, 1, 0.15, 0, 0, 0))
        if index % 3 == 0 and not dropout(at):
            result = pipeline.range(synthetic_epoch(settings, sequence, at, at, rng), at)
            sequence += 1
            measured.append(result)
        else:
            result = pipeline.estimator.predict(at)
        kinds.add(result.kind)
        if result.kind == "predicted":
            assert result.prediction_age <= 0.1
        if 8.2 < at < 8.6:
            assert result.kind == "invalid"
    assert kinds == {"measured", "predicted", "invalid"}
    assert all(result.kind == "measured" for result in measured)
    assert measured[-1].position is not None


def test_waypoint_drives_sensor_ground_truth():
    from datetime import UTC, datetime, timedelta

    from helios_localization.demo import SensorDemoCoordinator
    from helios_localization.models import Position, Target

    settings = load_settings(Path(__file__).parents[1] / "configs/survey.example.toml")
    coordinator = SensorDemoCoordinator(settings)
    target = Target(
        "simulation-command", Position(1.5, 1.5, 1.5), datetime.now(UTC) + timedelta(seconds=30)
    )
    coordinator.start(target, 0)
    rng = np.random.default_rng(2026)
    for i in range(1, 151):
        at = i * 0.05
        coordinator.tick(at)
        position = coordinator.provider.position
        coordinator.pipeline.aircraft(
            AircraftSample("controller", at, at, position.z, 0.15, 0, 0, 0)
        )
        coordinator.latest[0] = coordinator.pipeline.range(
            synthetic_epoch(settings, i, at, at, rng, [position.x, position.y, position.z]), at
        )
    telemetry = coordinator.telemetry()
    assert telemetry["state"] == "idle"
    assert telemetry["completed_command_id"] == target.command_id
    assert telemetry["position"] == target.position.as_dict()
    estimate = telemetry["simulated_localization"]["observation"]
    assert estimate["kind"] == "measured"
    assert abs(estimate["position"]["x"] - 1.5) < 0.1
    assert abs(estimate["position"]["y"] - 1.5) < 0.1
    coordinator.reset()
    assert "simulated_localization" not in coordinator.telemetry()
