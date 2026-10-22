"""Native process and dependency support for the local development launcher."""

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"


def acquire_lock(path):
    stream = path.open("a+b")
    try:
        if WINDOWS:
            import msvcrt

            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise RuntimeError(
            "Helios development is already running in this checkout"
        ) from None
    return stream


def spawn_options():
    if WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def stop_process(process):
    if process.poll() is not None:
        return
    try:
        if WINDOWS:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        if WINDOWS:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def localization_command(root):
    python = (
        root
        / "apps/localization/.venv"
        / ("Scripts/python.exe" if WINDOWS else "bin/python")
    )
    return [str(python), "-m", "helios_localization"]


def frontend_command(root):
    # Invoke JS directly: .bin/vite is a POSIX shell script and .cmd needs a shell.
    return [
        shutil.which("node") or "node",
        str(root / "apps/frontend/node_modules/vite/bin/vite.js"),
        "--host",
        "127.0.0.1",
    ]


def redis_binary():
    for name in ("redis-server", "memurai"):
        if executable := shutil.which(name):
            return executable
    candidate = (
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Memurai/memurai.exe"
    )
    if WINDOWS and candidate.is_file():
        return str(candidate)
    raise RuntimeError("Install native Redis or Memurai (Windows), and put it on PATH")


def windows_postgres(name):
    root = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "PostgreSQL"
    for directory in sorted(root.glob("*/bin"), reverse=True):
        candidate = directory / (name + ".exe")
        if candidate.is_file():
            return str(candidate)
    return None
