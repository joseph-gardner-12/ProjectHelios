from dataclasses import replace
from unittest.mock import Mock

from helios_localization.mavlink import EXPECTED_PARAMETERS, AircraftClock, AircraftLink
from helios_localization.measurements import AircraftSample, Estimate
from helios_localization.models import Position


def link_and_estimate():
    link = AircraftLink.__new__(AircraftLink)
    link.settings = Mock(
        external_nav=True,
        max_age=0.1,
        max_skew=0.05,
        dock_in_ned=(10, 20, 30),
        controller_firmware="4.6.3",
    )
    link.link = Mock()
    link.armed = False
    link.origin = True
    link.firmware_version = "4.6.3"
    link.last_heartbeat = 1.0
    link.parameters = dict(EXPECTED_PARAMETERS)
    link.last_sent = None
    link.last_estimator_session = None
    link.reset_counter = 0
    estimate = Estimate(
        "measured",
        "capture:fc:1",
        "survey",
        1.0,
        1.0,
        Position(1, 2, 3),
        ((0.01, 0, 0), (0, 0.02, 0), (0, 0, 0.03)),
        timing_sigma=0.001,
    )
    sample = AircraftSample("fc", 1.0, 1.0, 3.0, 0.1, 0.1, 0.2, 0.3)
    return link, estimate, sample


def test_only_fresh_measured_results_sent_once_and_transformed():
    link, estimate, sample = link_and_estimate()
    assert link.send_estimate(estimate, sample, 1.01)
    arguments = link.link.mav.vision_position_estimate_send.call_args.args
    assert arguments[:4] == (1_000_000, 12, 21, 27)
    assert arguments[4:7] == (0.1, 0.2, 0.3)
    assert arguments[7][0] == 0.02 and arguments[7][6] == 0.01 and arguments[7][11] == 0.03
    assert not link.send_estimate(estimate, sample, 1.02)
    assert link.link.mav.vision_position_estimate_send.call_count == 1


def test_output_guards():
    for change in ("armed", "parameters", "origin", "disabled", "stale", "predicted", "invalid"):
        link, estimate, sample = link_and_estimate()
        now = 1.01
        if change == "armed":
            link.armed = True
        if change == "parameters":
            link.parameters["EK3_SRC1_POSZ"] = 6
        if change == "origin":
            link.origin = False
        if change == "disabled":
            link.settings.external_nav = False
        if change == "stale":
            now = 1.2
        if change in ("predicted", "invalid"):
            estimate = replace(estimate, kind=change)
        assert not link.send_estimate(estimate, sample, now), change
        link.link.mav.vision_position_estimate_send.assert_not_called()


def test_boot_clock_rollback_creates_new_session():
    clock = AircraftClock()
    assert clock.map(10000, 20.0) == 20.0
    session = clock.session
    assert clock.map(10050, 20.1) == 20.05
    assert clock.map(0, 21.0) == 21.0
    assert session != clock.session


def test_real_mavlink2_serial_encoding_and_telemetry_with_pseudoterminal():
    import os
    import time

    from pymavlink.dialects.v20 import ardupilotmega as dialect

    from helios_localization.config import load_settings

    if not hasattr(os, "openpty"):
        import pytest

        pytest.skip("POSIX pseudoterminal test; Windows serial path is exercised with mocks")
    master, slave = os.openpty()
    link = None
    try:
        cfg = replace(
            load_settings("apps/localization/configs/survey.example.toml"),
            mavlink_port=os.ttyname(slave),
        )
        link = AircraftLink(cfg)
        assert link.link.mavlink20()
        sender = dialect.MAVLink(None, srcSystem=1, srcComponent=1)
        messages = [
            dialect.MAVLink_heartbeat_message(2, 3, 0, 0, 3, 3),
            dialect.MAVLink_attitude_message(5000, 0.1, 0.2, 0.3, 0, 0, 0),
            dialect.MAVLink_local_position_ned_message(5000, 1, 2, -1.5, 0, 0, 0),
        ]
        os.write(master, b"".join(message.pack(sender) for message in messages))
        samples = []
        events = []
        for _ in range(20):
            samples.extend(link.poll(10.0))
            events.extend(link.events)
            if samples:
                break
            time.sleep(0.005)
        assert len(samples) == 1
        assert samples[0].z == 1.5
        assert samples[0].acquired_at == 10.0
        assert samples[0].session == link.clock.session
        assert link.armed is False
        assert all("packet" in event for event in events)
    finally:
        if link:
            link.close()
        os.close(master)
        os.close(slave)
