"""Estimate a fixed bench square from a stationary tag inside its four corners."""

import base64
import json
import math
import tomllib
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from .config import Settings, load_settings
from .ranging import parse_range_report


@dataclass(frozen=True)
class SquareCalibration:
    side_m: float
    tag_xy_m: tuple[float, float]
    fit_rms_m: float
    samples: int
    spread_m: float
    corners: tuple[str, ...]  # origin, +X, +Y, diagonal


def fit_square(ranges, corners=("A0", "A2", "A3", "A4")) -> SquareCalibration:
    """Fit side, X and Y jointly; caller guarantees a square and an interior tag.

    A single tag outside the square can imply an alternative, smaller square.
    Ranges alone cannot establish which physical geometry is correct, or detect
    a common range bias/unknown height. Do not use this as a flight survey.
    """
    values = np.asarray(ranges, dtype=float)
    if (
        values.ndim != 2
        or values.shape[1] != 4
        or values.shape[0] < 30
        or not np.all(np.isfinite(values))
        or np.any(values <= 0)
    ):
        raise ValueError("Need at least 30 complete, positive four-anchor reports")
    if len(corners) != 4 or len(set(corners)) != 4:
        raise ValueError("Supply four unique corners: origin, +X, +Y, diagonal")
    spread = float(np.max(np.ptp(np.percentile(values, [5, 95], axis=0), axis=0)))
    if spread > 0.10:
        raise ValueError(f"Ranges vary by {spread:.3f} m; hold the tag and anchors still")
    distances = np.median(values, axis=0)
    unit_corners = np.array([(0, 0), (1, 0), (0, 1), (1, 1)])

    def residual(parameters):
        side, u, v = parameters
        return side * np.linalg.norm(unit_corners - (u, v), axis=1) - distances

    seed_side = float(np.median(distances) * math.sqrt(2))
    fits = [
        least_squares(
            residual,
            [seed_side, u, v],
            bounds=([0.05, 0, 0], [100, 1, 1]),
            max_nfev=300,
        )
        for u, v in [(0.5, 0.5), (0.2, 0.2), (0.8, 0.2), (0.2, 0.8), (0.8, 0.8)]
    ]
    fit = min(fits, key=lambda candidate: np.sum(candidate.fun**2))
    rms = float(np.sqrt(np.mean(fit.fun**2)))
    if not fit.success or not np.all(np.isfinite(fit.x)):
        raise ValueError("Square calibration did not converge")
    if rms > 0.05 or np.max(np.abs(fit.fun)) > 0.10:
        raise ValueError(
            f"Ranges do not fit an interior tag in a square (RMS {rms:.3f} m); "
            "check corner IDs, square shape, antenna heights and obstructions"
        )
    side, u, v = map(float, fit.x)
    if not 0.1 <= side <= 50 or not (0.05 < u < 0.95 and 0.05 < v < 0.95):
        raise ValueError("Keep the tag inside the square, away from its edges")
    if np.linalg.cond(fit.jac) > 100:
        raise ValueError("Square size is poorly constrained; move the tag nearer the center")
    return SquareCalibration(side, (side * u, side * v), rms, len(values), spread, tuple(corners))


def calibrate_recording(
    path: Path,
    settings: Settings,
    corners=("A0", "A2", "A3", "A4"),
) -> SquareCalibration:
    """Use only the last ten recorded seconds, never merge partial epochs."""
    if settings.protocol != "mauwb-at-v1.1.6" or settings.fixed_height is None:
        raise ValueError("Square calibration requires real MaUWB fixed-height bench mode")
    anchors = {anchor.id: anchor for anchor in settings.anchors}
    if len(corners) != 4 or len(set(corners)) != 4 or set(corners) != set(anchors):
        raise ValueError("Corners must name exactly the four configured anchors")
    if any(abs(anchor.xyz[2] - settings.fixed_height) > 1e-6 for anchor in anchors.values()):
        raise ValueError("Tag and all anchor antennas must share the fixed bench height")
    recent = deque()
    first = True
    last_at = -math.inf
    seen = set()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if len(line) > 65536:
                raise ValueError("Oversized calibration recording entry")
            if not line.endswith("\n"):
                break  # a live recorder may still be writing its last entry
            event = json.loads(line)
            if first:
                first = False
                manifest = event.get("settings", {})
                if (
                    event.get("type") != "manifest"
                    or event.get("version") != 1
                    or manifest.get("protocol") != settings.protocol
                    or manifest.get("tag_id") != settings.tag_id
                    or manifest.get("anchors")
                    != [
                        {"id": a.id, "xyz": list(a.xyz), "bias": a.bias, "sigma": a.sigma}
                        for a in settings.anchors
                    ]
                ):
                    raise ValueError("Recording does not match the source survey")
                continue
            at = event.get("at")
            if type(at) not in (float, int) or not math.isfinite(at) or at < last_at:
                raise ValueError("Recording has invalid or backwards timestamps")
            last_at = at
            while recent and recent[0][0] < at - 10:
                recent.popleft()
            if event.get("type") != "uwb":
                continue
            try:
                report = parse_range_report(base64.b64decode(event["raw"], validate=True).decode())
            except ValueError, UnicodeError:
                continue
            if report[0].tag_id != settings.tag_id:
                continue
            key = (report[0].sequence, event["raw"])
            if key in seen:
                continue
            # Bound duplicate history; sequences can wrap during long recordings.
            if len(seen) >= 4096:
                seen.clear()
            seen.add(key)
            distances = {f"A{r.anchor_id}": r.distance_m for r in report}
            if not set(corners).issubset(distances):
                continue
            recent.append((at, [distances[c] - anchors[c].bias for c in corners]))
    if len(recent) < 30 or recent[-1][0] - recent[0][0] < 4:
        raise ValueError("Need at least 30 complete reports spanning four seconds in the last 10s")
    if last_at - recent[-1][0] > 1:
        raise ValueError("Four-anchor reports stopped; wait for a current complete capture")
    return fit_square([ranges for _, ranges in recent], corners)


def _toml_value(value):
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{ "
            + ", ".join(f"{json.dumps(key)} = {_toml_value(item)}" for key, item in value.items())
            + " }"
        )
    raise ValueError(f"Unsupported survey value: {type(value).__name__}")


def write_square_survey(source: Path, output: Path, result: SquareCalibration) -> None:
    """Write a new frame and survey; preserve input settings and never overwrite."""
    settings = load_settings(source)
    data = tomllib.loads(source.read_text())
    data["frame"] = f"square-bench-{uuid.uuid4().hex[:12]}"
    data["external_nav"] = False
    data["protocol_verified"] = False
    coordinates = [(0, 0), (result.side_m, 0), (0, result.side_m), (result.side_m, result.side_m)]
    xy = dict(zip(result.corners, coordinates, strict=True))
    for anchor in data["anchors"]:
        anchor["xyz"] = [*xy[anchor["id"]], settings.fixed_height]
    data.setdefault("metadata", {})["square_calibration"] = {
        "method": "stationary-interior-tag-same-height",
        "side_m": result.side_m,
        "fit_rms_m": result.fit_rms_m,
        "samples": result.samples,
        "spread_m": result.spread_m,
        "qualification": "bench estimate; square shape and tag placement assumed",
    }
    text = "# Estimated bench square; validate against physical ground truth before use.\n"
    text += "\n".join(
        f"{json.dumps(key)} = {_toml_value(value)}"
        for key, value in data.items()
        if key != "anchors"
    )
    for anchor in data["anchors"]:
        text += "\n\n[[anchors]]\n" + "\n".join(
            f"{json.dumps(key)} = {_toml_value(value)}" for key, value in anchor.items()
        )
    # Verify serialization before touching the output.
    tomllib.loads(text)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(text + "\n")
