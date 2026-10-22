"""Strict measurement telemetry validation; never accepts movement authority."""

import math

from .protocol import timestamp

FIELDS = {
    "kind",
    "session",
    "estimated_time",
    "measurement_time",
    "prediction_age_s",
    "position",
    "covariance",
    "timing_sigma_s",
    "reason",
}


def number(value, minimum=None):
    return (
        type(value) in (int, float)
        and math.isfinite(value)
        and (minimum is None or value >= minimum)
    )


def validate_observation(value):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("Invalid observation fields")
    kind = value["kind"]
    if kind not in {"measured", "predicted", "invalid"}:
        raise ValueError("Invalid estimate kind")
    if not isinstance(value["session"], str) or not 1 <= len(value["session"]) <= 100:
        raise ValueError("Invalid estimator session")
    estimated = timestamp(value["estimated_time"])
    measured = (
        timestamp(value["measurement_time"]) if value["measurement_time"] is not None else None
    )
    if not number(value["timing_sigma_s"], 0):
        raise ValueError("Invalid timing uncertainty")
    age = value["prediction_age_s"]
    if measured:
        if not number(age, 0) or abs((estimated - measured).total_seconds() - age) > 0.00001:
            raise ValueError("Inconsistent prediction age")
    elif age is not None:
        raise ValueError("Age without measurement")
    if kind == "invalid":
        if value["position"] is not None or value["covariance"] is not None:
            raise ValueError("Invalid estimate cannot provide coordinates")
        if not isinstance(value["reason"], str) or not 1 <= len(value["reason"]) <= 120:
            raise ValueError("Invalid rejection reason")
        return value
    if not measured or age > 0.100001 or (kind == "measured" and age != 0):
        raise ValueError("Unbounded or inconsistent prediction")
    p = value["position"]
    if (
        not isinstance(p, dict)
        or set(p) != {"x", "y", "z"}
        or not all(number(v) for v in p.values())
    ):
        raise ValueError("Invalid signed coordinates")
    cov = value["covariance"]
    if (
        not isinstance(cov, (list, tuple))
        or len(cov) != 3
        or any(
            not isinstance(row, (list, tuple)) or len(row) != 3 or not all(number(v) for v in row)
            for row in cov
        )
    ):
        raise ValueError("Invalid covariance")
    if any(cov[i][i] <= 0 for i in range(3)) or any(
        abs(cov[i][j] - cov[j][i]) > 1e-8 for i in range(3) for j in range(3)
    ):
        raise ValueError("Covariance must be symmetric with positive variances")
    # All principal minors must be nonnegative for a symmetric PSD 3x3 matrix.
    if any(cov[i][i] * cov[j][j] < cov[i][j] ** 2 - 1e-10 for i in range(3) for j in range(i)):
        raise ValueError("Covariance is not positive semidefinite")
    determinant = (
        cov[0][0] * (cov[1][1] * cov[2][2] - cov[1][2] ** 2)
        - cov[0][1] * (cov[0][1] * cov[2][2] - cov[1][2] * cov[0][2])
        + cov[0][2] * (cov[0][1] * cov[1][2] - cov[1][1] * cov[0][2])
    )
    if determinant < -1e-10 or value["reason"] is not None:
        raise ValueError("Invalid measurement covariance/reason")
    return value
