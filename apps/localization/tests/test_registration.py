import asyncio
import json
import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from helios_localization import __main__ as cli
from helios_localization import registration, transport


def result():
    return {
        "machine_id": str(uuid.uuid4()),
        "device_id": str(uuid.uuid4()),
        "credential": f"{uuid.uuid4()}.private-secret",
        "frame_version": "dummy-enu-v1",
        "websocket_path": "/ws/v1/pi/",
    }


def test_setup_registers_and_saves_private_config_without_shared_password(tmp_path, monkeypatch):
    destination = tmp_path / "helios" / "localization.json"
    issued = result()
    monkeypatch.setattr("builtins.input", lambda prompt: "Student laptop")
    monkeypatch.setattr(registration.getpass, "getpass", lambda prompt: "shared-password")
    calls = []

    def enroll(backend, name, password):
        calls.append((backend, name, password))
        return issued

    monkeypatch.setattr(registration, "enroll", enroll)
    registration.configure(destination)
    saved = json.loads(destination.read_text())
    assert calls == [(registration.DEFAULT_BACKEND, "Student laptop", "shared-password")]
    assert saved["url"] == "wss://api.projecthelios.dev/ws/v1/pi/"
    assert saved["device_id"] == issued["device_id"]
    assert "shared-password" not in destination.read_text()
    assert "private-secret" not in destination.read_text()
    credential = Path(saved["credential_file"])
    assert credential.read_text().strip() == issued["credential"]
    for path in (destination, credential):
        assert path.stat().st_mode & 0o777 == 0o600
    # Repeated setup must not create another registration, including legacy configs.
    registration.configure(destination)
    assert len(calls) == 1


def test_failed_save_preserves_existing_configuration(tmp_path, monkeypatch):
    destination = tmp_path / "localization.json"
    destination.write_text('{"original": true}')
    original = destination.read_bytes()

    def fail(*args):
        raise PermissionError

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(ValueError, match="Existing settings were preserved"):
        registration.save_registration(destination, registration.DEFAULT_BACKEND, result())
    assert destination.read_bytes() == original
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:secret@example.com",
        "https://example.com/path",
        "https://example.com?password=test",
        "file:///tmp/backend",
    ],
)
def test_rejects_unsafe_backend_origins(url):
    with pytest.raises(ValueError):
        registration.backend_origin(url)


def test_local_backend_supported():
    assert registration.backend_origin("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"


def test_conflict_before_setup_terminates_without_retry(tmp_path, monkeypatch):
    credential = tmp_path / "credential"
    credential.write_text("private-secret")

    class Socket:
        async def recv(self):
            return json.dumps(
                {
                    "version": 1,
                    "type": "error",
                    "code": "machine_already_connected",
                    "message": "Cannot start: “Lab Pi” is already connected.",
                }
            )

    class Connect:
        async def __aenter__(self):
            return Socket()

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(transport, "connect", lambda *args, **kwargs: Connect())
    sleep = AsyncMock()
    monkeypatch.setattr(transport.asyncio, "sleep", sleep)
    with pytest.raises(transport.TerminalConnectionError, match="Lab Pi") as exc:
        asyncio.run(transport.run("ws://127.0.0.1", credential, str(uuid.uuid4()), "dummy-enu-v1"))
    assert exc.value.exit_status == 3
    sleep.assert_not_awaited()


def test_temporary_network_failure_still_retries(tmp_path, monkeypatch):
    credential = tmp_path / "credential"
    credential.write_text("private-secret")
    connect = AsyncMock(side_effect=[OSError, transport.TerminalConnectionError("conflict", 3)])
    sleep = AsyncMock()
    monkeypatch.setattr(transport, "connection", connect)
    monkeypatch.setattr(transport.asyncio, "sleep", sleep)
    with pytest.raises(transport.TerminalConnectionError):
        asyncio.run(transport.run("ws://127.0.0.1", credential, str(uuid.uuid4()), "dummy-enu-v1"))
    assert connect.await_count == 2
    sleep.assert_awaited_once()


def test_old_config_runs_and_terminal_error_has_nonzero_exit(tmp_path, monkeypatch, capsys):
    credential = tmp_path / "old.credential"
    credential.write_text("old-token")
    config = tmp_path / "localization.json"
    device_id = str(uuid.uuid4())
    config.write_text(
        json.dumps(
            {
                "url": "wss://api.projecthelios.dev/ws/v1/pi/",
                "device_id": device_id,
                "credential_file": str(credential),
            }
        )
    )
    monkeypatch.setenv("HELIOS_CONFIG_FILE", str(config))
    for name in ("HELIOS_DEVICE_ID", "HELIOS_CREDENTIAL_FILE", "HELIOS_BACKEND_WS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("sys.argv", ["helios-localization", "simulate"])
    run = AsyncMock(side_effect=transport.TerminalConnectionError("Lab Pi is connected", 3))
    monkeypatch.setattr(cli, "run", run)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 3
    assert "Lab Pi" in capsys.readouterr().err
    assert run.await_args.args[2] == device_id
    assert credential.read_text() == "old-token"


def test_revoked_credential_inside_task_group_is_terminal():
    from websockets.exceptions import ConnectionClosedError
    from websockets.frames import Close

    error = transport.terminal_error(
        ExceptionGroup("connection", [ConnectionClosedError(Close(4401, "revoked"), None, None)])
    )
    assert error is not None and error.exit_status == 4
    assert (
        transport.terminal_error(ConnectionClosedError(Close(4410, "expired"), None, None)) is None
    )


def test_force_setup_can_repair_malformed_saved_config(tmp_path, monkeypatch):
    config = tmp_path / "localization.json"
    config.write_text("not-json")
    monkeypatch.setenv("HELIOS_CONFIG_FILE", str(config))
    monkeypatch.setattr("sys.argv", ["helios-localization", "configure", "--force"])
    from unittest.mock import Mock

    setup = Mock()
    monkeypatch.setattr(cli, "configure", setup)
    cli.main()
    setup.assert_called_once_with(config, registration.DEFAULT_BACKEND, True)
