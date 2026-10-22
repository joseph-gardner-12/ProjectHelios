"""Sensor/estimator boundaries. All durations use one session's monotonic seconds."""

from dataclasses import asdict, dataclass
from typing import Literal

from .models import Position


@dataclass(frozen=True)
class RangeEpoch:
    session: str
    sequence: int
    frame: str
    acquired_at: float
    received_at: float
    timing_sigma: float
    ranges: dict[str, float]
    timing_source: str = "device"


@dataclass(frozen=True)
class AircraftSample:
    session: str
    acquired_at: float
    received_at: float
    z: float  # aircraft reference height in survey ENU
    z_sigma: float
    roll: float  # body FRD -> local NED Euler angles, radians
    pitch: float
    yaw: float
    timing_sigma: float = 0.0


@dataclass(frozen=True)
class Estimate:
    kind: Literal["measured", "predicted", "invalid"]
    session: str
    frame: str
    estimated_at: float
    measurement_at: float | None
    position: Position | None = None
    covariance: tuple[tuple[float, ...], ...] | None = None  # ENU position, 3x3
    state_covariance: tuple[tuple[float, ...], ...] | None = None  # x,y,vx,vy
    reason: str | None = None
    residual_rms: float | None = None
    timing_sigma: float = 0.0

    @property
    def prediction_age(self):
        return None if self.measurement_at is None else self.estimated_at - self.measurement_at

    def as_dict(self):
        return asdict(self)
