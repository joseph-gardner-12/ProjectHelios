import json
from pathlib import Path

import pytest
import serial

from helios_localization.ranging import (
    active_ranges_cm,
    parse_range_report,
    record_range_reports,
)

SAMPLES = [
    "AT+RANGE=tid:1,mask:10,seq:35,range:(0,0,0,0,102,0,0,0),ancid:(-1,-1,-1,-1,4,-1,-1,-1)",
    "AT+RANGE=tid:1,mask:10,seq:36,range:(0,0,0,0,106,0,0,0),ancid:(-1,-1,-1,-1,4,-1,-1,-1)",
    "AT+RANGE=tid:1,mask:10,seq:37,range:(0,0,0,0,109,0,0,0),ancid:(-1,-1,-1,-1,4,-1,-1,-1)",
]


def test_parses_captured_a4_samples():
    measurements = [parse_range_report(sample)[0] for sample in SAMPLES]
    assert [
        (item.tag_id, item.sequence, item.anchor_id, item.distance_m) for item in measurements
    ] == [
        (1, 35, 4, 1.02),
        (1, 36, 4, 1.06),
        (1, 37, 4, 1.09),
    ]
    assert all(item.mask == "10" for item in measurements)


def test_maps_active_ranges_to_anchor_ids_in_centimetres():
    measurements = parse_range_report(
        "AT+RANGE=tid:1,mask:0F,seq:35,range:(102,106,109,98,0,0,0,0),"
        "ancid:(1,2,3,4,-1,-1,-1,-1)"
    )
    assert active_ranges_cm(measurements) == {1: 102, 2: 106, 3: 109, 4: 98}
    assert active_ranges_cm(parse_range_report(SAMPLES[0])) == {4: 102}


@pytest.mark.parametrize(
    "line,reason",
    [
        ("garbage", "Not a complete AT\\+RANGE report"),
        ("AT+RANGE=tid:1,mask:10,seq:35,range:(102),ancid:(4,5)",
         "Range and anchor-ID tuple lengths differ"),
        ("AT+RANGE=tid:1,mask:10,seq:35,range:(0),ancid:(4)",
         "Active anchor has a nonpositive range"),
        ("AT+RANGE=tid:1,mask:10,seq:35,range:(0),ancid:(-1)",
         "Range report has no active anchor measurements"),
    ],
)
def test_rejects_invalid_range_reports(line, reason):
    with pytest.raises(ValueError, match=reason):
        parse_range_report(line)


class FakeSerial:
    def __init__(self, lines):
        self.lines = iter(lines)
        self.closed = False

    def readline(self):
        return next(self.lines)

    def close(self):
        self.closed = True


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_records_rejections_and_suppresses_duplicates(tmp_path, capsys):
    output = tmp_path / "ranges.jsonl"
    fake = FakeSerial([(SAMPLES[0] + "\r\n").encode(), (SAMPLES[0] + "\r\n").encode(),
                       b"AT+RANGE=tid:1", b"not-a-range\r\n"])
    record_range_reports(
        "COM4", output, max_lines=4, echo=True, serial_factory=lambda **_: fake
    )
    records = read_jsonl(output)
    assert records[0]["type"] == "collector_metadata"
    assert records[1]["distance_m"] == 1.02
    assert [record["reason"] for record in records[2:]] == [
        "duplicate measurement", "partial serial line", "Not a complete AT+RANGE report"
    ]
    assert fake.closed
    assert capsys.readouterr().out == '{"4": 102}\n'


def test_reconnects_after_serial_error(tmp_path):
    output = tmp_path / "ranges.jsonl"
    fake = FakeSerial([(SAMPLES[0] + "\n").encode()])
    attempts = 0
    delays = []

    def factory(**_):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise serial.SerialException("port busy")
        return fake

    record_range_reports("COM4", output, max_lines=1, serial_factory=factory, sleep=delays.append)
    assert attempts == 2
    assert delays == [1.0]
    assert read_jsonl(output)[1]["sequence"] == 35
