"""Versioned survey configuration, independent of enrollment credentials."""

import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Anchor:
    id: str
    xyz: tuple[float, float, float]
    bias: float = 0.0
    sigma: float = 0.1


@dataclass(frozen=True)
class Settings:
    frame: str
    anchors: tuple[Anchor, ...]
    tag_id: int = 0
    tag_offset_frd: tuple[float, float, float] = (0.0, 0.0, 0.0)
    dock_in_ned: tuple[float, float, float] = (0.0, 0.0, 0.0)
    altitude_offset: float = 0.0
    altitude_sigma: float = 0.15
    fixed_height: float | None = None  # explicit stationary-height bench constraint
    max_age: float = 0.1
    max_skew: float = 0.05
    prediction_limit: float = 0.1
    max_sigma: float = 0.5
    acceleration_sigma: float = 2.0
    initial_velocity_sigma: float = 2.0
    gate_sigma: float = 5.0
    huber_scale: float = 1.5
    max_condition: float = 100.0
    max_speed: float = 3.0
    uwb_port: str = ""
    uwb_baud: int = 250000
    mavlink_port: str = ""
    mavlink_baud: int = 57600
    protocol: str = "synthetic-json-v1"
    protocol_verified: bool = False
    firmware: str = "unverified"
    controller_firmware: str = "unverified"
    acquisition_delay: float = 0.0
    timing_sigma: float = 0.02
    external_nav: bool = False
    recording_max_bytes: int = 100_000_000
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if type(self.external_nav) is not bool or type(self.protocol_verified) is not bool:
            raise ValueError("Enable/qualification flags must be TOML booleans")
        for name in ("tag_id", "uwb_baud", "mavlink_baud", "recording_max_bytes"):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer")
        if self.tag_id < 0:
            raise ValueError("tag_id must be nonnegative")
        if not self.frame or self.frame == "dummy-enu-v1" or len(self.frame) > 80:
            raise ValueError("A named surveyed frame is required")
        if len(self.anchors) < 4 or len({a.id for a in self.anchors}) != len(self.anchors):
            raise ValueError("At least four uniquely named anchors required")
        for anchor in self.anchors:
            if len(anchor.xyz) != 3 or not all(math.isfinite(v) for v in anchor.xyz):
                raise ValueError("Invalid anchor coordinates")
            if (
                not math.isfinite(anchor.bias)
                or not math.isfinite(anchor.sigma)
                or anchor.sigma <= 0
            ):
                raise ValueError("Invalid anchor calibration")
        for vector in (self.tag_offset_frd, self.dock_in_ned):
            if len(vector) != 3 or not all(math.isfinite(v) for v in vector):
                raise ValueError("Invalid frame/offset vector")
        for name in (
            "altitude_sigma",
            "max_age",
            "max_skew",
            "prediction_limit",
            "max_sigma",
            "acceleration_sigma",
            "initial_velocity_sigma",
            "gate_sigma",
            "huber_scale",
            "max_condition",
            "max_speed",
            "timing_sigma",
        ):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"Invalid {name}")
        if self.fixed_height is not None:
            if type(self.fixed_height) not in (int, float) or not math.isfinite(self.fixed_height):
                raise ValueError("fixed_height must be a finite surveyed height in metres")
            if self.external_nav or self.mavlink_port or any(self.tag_offset_frd):
                raise ValueError(
                    "Fixed-height bench mode requires no MAVLink, output, or tag offset"
                )
        if self.prediction_limit > 0.1:
            raise ValueError("Bench prediction limit cannot exceed 100 ms")
        if not math.isfinite(self.altitude_offset) or self.acquisition_delay < 0:
            raise ValueError("Invalid datum or acquisition delay")
        if not math.isfinite(self.acquisition_delay):
            raise ValueError("Invalid acquisition delay")
        if self.uwb_baud <= 0 or self.mavlink_baud <= 0 or self.recording_max_bytes <= 0:
            raise ValueError("Invalid serial/recording limits")
        if self.protocol not in {"synthetic-json-v1", "mauwb-at-v1.1.6"}:
            raise ValueError("Unsupported range protocol")


def load_settings(path: str | Path) -> Settings:
    with Path(path).open("rb") as stream:
        data = tomllib.load(stream)
    if data.pop("version", None) != 1:
        raise ValueError("Unsupported survey configuration version")
    data["anchors"] = tuple(
        Anchor(id=a["id"], xyz=tuple(a["xyz"]), bias=a.get("bias", 0), sigma=a.get("sigma", 0.1))
        for a in data["anchors"]
    )
    for key in ("tag_offset_frd", "dock_in_ned"):
        if key in data:
            data[key] = tuple(data[key])
    return Settings(**data)
