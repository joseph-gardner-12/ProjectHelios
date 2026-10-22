"""Read and record automatic MaUWB range reports from a USB collector."""

import json
import logging
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import serial

DEFAULT_PORT = "COM4"
DEFAULT_BAUDRATE = 115200
COLLECTOR_METADATA = {
    "firmware": "V01_01_006",
    "hardware": "V01_03_000",
    "anchor_id": 4,
    "pan_id": "1111",
    "air_rate": "850kbps",
    "distance_filter": "enabled",
    "tag_capacity": 10,
    "slot_time_ms": 15,
    "mode": "standard",
}
RANGE_REPORT = re.compile(
    r"^AT\+RANGE=tid:(?P<tag_id>\d+),mask:(?P<mask>[0-9A-Fa-f]+),"
    r"seq:(?P<sequence>\d+),range:\((?P<ranges>[^)]*)\),ancid:\((?P<anchor_ids>[^)]*)\)$"
)


@dataclass(frozen=True)
class RangeMeasurement:
    tag_id: int
    sequence: int
    mask: str
    anchor_id: int
    distance_m: float

    def as_dict(self) -> dict[str, int | float | str]:
        return {
            "tag_id": self.tag_id,
            "sequence": self.sequence,
            "mask": self.mask,
            "anchor_id": self.anchor_id,
            "distance_m": self.distance_m,
        }


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_range_report(line: str) -> list[RangeMeasurement]:
    """Convert one complete v1.1.6 report into its active anchor ranges."""
    match = RANGE_REPORT.fullmatch(line.strip())
    if not match:
        raise ValueError("Not a complete AT+RANGE report")
    try:
        ranges_cm = [int(value) for value in match["ranges"].split(",")]
        anchor_ids = [int(value) for value in match["anchor_ids"].split(",")]
    except ValueError as exc:
        raise ValueError("Range report contains a non-integer tuple value") from exc
    if len(ranges_cm) != len(anchor_ids):
        raise ValueError("Range and anchor-ID tuple lengths differ")
    if not ranges_cm:
        raise ValueError("Range report has no anchor slots")

    measurements = []
    for distance_cm, anchor_id in zip(ranges_cm, anchor_ids, strict=True):
        if anchor_id < 0:
            continue
        if distance_cm <= 0:
            raise ValueError("Active anchor has a nonpositive range")
        measurements.append(
            RangeMeasurement(
                int(match["tag_id"]),
                int(match["sequence"]),
                match["mask"],
                anchor_id,
                distance_cm / 100,
            )
        )
    if not measurements:
        raise ValueError("Range report has no active anchor measurements")
    return measurements


class RecentMeasurements:
    """Bound duplicate suppression so source-sequence wrap can recover."""

    def __init__(self, capacity: int = 2048):
        self._keys: deque[tuple[int, int, int, float]] = deque(maxlen=capacity)
        self._known: set[tuple[int, int, int, float]] = set()

    def contains_or_add(self, measurement: RangeMeasurement) -> bool:
        key = (
            measurement.tag_id,
            measurement.sequence,
            measurement.anchor_id,
            measurement.distance_m,
        )
        if key in self._known:
            return True
        if len(self._keys) == self._keys.maxlen:
            self._known.remove(self._keys[0])
        self._keys.append(key)
        self._known.add(key)
        return False


def _write_jsonl(output, value: dict, *, echo: bool) -> None:
    line = json.dumps(value, sort_keys=True)
    output.write(line + "\n")
    output.flush()
    if echo:
        print(line, flush=True)


def record_range_reports(
    port: str,
    output_path: Path,
    *,
    baudrate: int = DEFAULT_BAUDRATE,
    max_lines: int | None = None,
    echo: bool = False,
    serial_factory: Callable[..., object] = serial.Serial,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Append parsed measurements and rejected UWB records to a JSONL file."""
    if max_lines is not None and max_lines < 1:
        raise ValueError("max_lines must be positive")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    recent = RecentMeasurements()
    completed_lines = 0
    retry_delay = 1.0
    with output_path.open("a", encoding="utf-8") as output:
        _write_jsonl(
            output,
            {
                "type": "collector_metadata",
                "recorded_at": utc_now().isoformat(),
                "port": port,
                "baudrate": baudrate,
                "collector": COLLECTOR_METADATA,
            },
            echo=echo,
        )
        while max_lines is None or completed_lines < max_lines:
            connection = None
            try:
                connection = serial_factory(
                    port=port,
                    baudrate=baudrate,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.25,
                )
                logging.info("Recording MaUWB range reports from %s at %s baud", port, baudrate)
                retry_delay = 1.0
                while max_lines is None or completed_lines < max_lines:
                    raw_bytes = connection.readline()
                    if not raw_bytes:
                        continue
                    received_at = utc_now().isoformat()
                    completed_lines += 1
                    if not raw_bytes.endswith(b"\n"):
                        _write_jsonl(
                            output,
                            {
                                "type": "rejected_range_report",
                                "received_at": received_at,
                                "reason": "partial serial line",
                                "raw": raw_bytes.decode("utf-8", errors="replace"),
                            },
                            echo=echo,
                        )
                        continue
                    try:
                        raw_line = raw_bytes.decode("utf-8").strip()
                    except UnicodeDecodeError:
                        _write_jsonl(
                            output,
                            {
                                "type": "rejected_range_report",
                                "received_at": received_at,
                                "reason": "invalid UTF-8",
                                "raw": raw_bytes.decode("utf-8", errors="replace"),
                            },
                            echo=echo,
                        )
                        continue
                    try:
                        measurements = parse_range_report(raw_line)
                    except ValueError as exc:
                        _write_jsonl(
                            output,
                            {
                                "type": "rejected_range_report",
                                "received_at": received_at,
                                "reason": str(exc),
                                "raw": raw_line,
                            },
                            echo=echo,
                        )
                        continue
                    for measurement in measurements:
                        if recent.contains_or_add(measurement):
                            _write_jsonl(
                                output,
                                {
                                    "type": "rejected_range_report",
                                    "received_at": received_at,
                                    "reason": "duplicate measurement",
                                    "raw": raw_line,
                                    **measurement.as_dict(),
                                },
                                echo=echo,
                            )
                            continue
                        _write_jsonl(
                            output,
                            {
                                "type": "range_measurement",
                                "received_at": received_at,
                                "raw": raw_line,
                                **measurement.as_dict(),
                            },
                            echo=echo,
                        )
            except (serial.SerialException, OSError) as exc:
                logging.warning(
                    "Cannot read %s: %s; retrying in %.0f seconds", port, exc, retry_delay
                )
                sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 10.0)
            finally:
                if connection is not None:
                    connection.close()
