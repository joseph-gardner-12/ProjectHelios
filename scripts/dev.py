"""One-command local control stack. All data and credentials stay in .helios/dev."""

import argparse
import fcntl
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".helios/dev"


def postgres_bin(name):
    executable = shutil.which(name)
    if executable:
        return executable
    pg_config = shutil.which("pg_config")
    if pg_config:
        result = subprocess.run(
            [pg_config, "--bindir"], capture_output=True, text=True, check=True
        )
        candidate = Path(result.stdout.strip()) / name
        if candidate.is_file():
            return str(candidate)
    for base in (
        "/opt/homebrew/opt/postgresql@16/bin",
        "/usr/local/opt/postgresql@16/bin",
    ):
        candidate = Path(base) / name
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError(
        "PostgreSQL is required. On macOS: brew install postgresql@16 redis"
    )


def wait_for(check, processes, label, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        failed = next(
            (name for name, process in processes if process.poll() is not None), None
        )
        if failed:
            raise RuntimeError(f"{failed} exited. See .helios/dev/logs/{failed}.log")
        try:
            if check():
                return
        except (OSError, URLError):
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {label}; see .helios/dev/logs")


def listening(port):
    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
        return True


def ready(url):
    with urlopen(url, timeout=1) as response:
        return response.status == 200


def prepare_device():
    # Django is imported only after this launcher has forced its isolated local environment.
    sys.path.insert(0, str(ROOT / "apps/backend"))
    import django

    django.setup()
    from control.models import Device
    from control.services import authenticate_pi, issue_credential
    from django.contrib.auth.hashers import make_password
    from django.core.management import call_command
    from django.db import connections

    call_command("migrate", verbosity=0)
    profile = STATE / "device.json"
    credential_path = STATE / "pi.credential"
    saved = json.loads(profile.read_text()) if profile.exists() else {}
    device = (
        Device.objects.filter(pk=saved.get("id")).first() if saved.get("id") else None
    )
    if not device:
        device = Device.objects.create(name="Local dummy Pi")
        profile.write_text(json.dumps({"id": str(device.id)}) + "\n")
        profile.chmod(0o600)
    credential = (
        authenticate_pi(credential_path.read_text().strip())
        if credential_path.exists()
        else None
    )
    if not device.enabled:
        device.enabled = True
        device.save(update_fields=["enabled"])
    if not credential or credential.device_id != device.id:
        credential_path.write_text(issue_credential(device) + "\n")
        credential_path.chmod(0o600)
    os.environ.update(
        {
            "CONTROL_DEMO_DEVICE_ID": str(device.id),
            "CONTROL_PASSWORD_HASH": make_password("SeniorDesign"),
            "HELIOS_DEVICE_ID": str(device.id),
            "HELIOS_CREDENTIAL_FILE": str(credential_path),
            "HELIOS_BACKEND_WS": "ws://127.0.0.1:8000/ws/v1/pi/",
            "HELIOS_FRAME_VERSION": "dummy-enu-v1",
        }
    )
    connections.close_all()
    return device.id


def local_environment():
    # Never inherit a production database, session configuration, or API destination.
    os.environ.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings.local",
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "15432",
            "POSTGRES_DB": "helios_dev",
            "POSTGRES_USER": "helios_dev",
            "POSTGRES_PASSWORD": "local-development-only",
            "REDIS_URL": "redis://127.0.0.1:16379/0",
            "CONTROL_REDIS_PREFIX": "helios:dev:control:v1",
            "HELIOS_DEV_BACKEND": "http://127.0.0.1:8000",
            "VITE_API_ORIGIN": "",
            "PYTHONUNBUFFERED": "1",
            "pnpm_config_verify_deps_before_run": "false",
        }
    )


def run_service(name):
    """Each Solo pane owns one foreground process; dependencies may start in any order."""
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True)
    local_environment()
    lock = (STATE / f"{name}.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(f"The {name} service is already running in this checkout.")
    # Keep the service lock through exec so restarting a pane cannot duplicate it.
    os.set_inheritable(lock.fileno(), True)
    if name == "postgres":
        pgdata = STATE / "postgres"
        if not (pgdata / "PG_VERSION").exists():
            subprocess.run(
                [
                    postgres_bin("initdb"),
                    "-D",
                    str(pgdata),
                    "-A",
                    "trust",
                    "-U",
                    "helios_dev",
                ],
                check=True,
            )
        command = [
            postgres_bin("postgres"),
            "-D",
            str(pgdata),
            "-h",
            "127.0.0.1",
            "-p",
            "15432",
            "-k",
            "",
            "-c",
            "shared_buffers=32MB",
            "-c",
            "max_connections=30",
        ]
    elif name == "redis":
        executable = shutil.which("redis-server")
        if not executable:
            sys.exit("Install Redis first: brew install redis")
        command = [
            executable,
            "--bind",
            "127.0.0.1",
            "--port",
            "16379",
            "--save",
            "",
            "--appendonly",
            "no",
        ]
    elif name == "frontend":
        os.chdir(ROOT / "apps/frontend")
        command = ["pnpm", "exec", "vite", "--host", "127.0.0.1"]
    elif name == "backend":
        print("Waiting for PostgreSQL and Redis…", flush=True)
        wait_for(
            lambda: listening(15432) and listening(16379),
            [],
            "PostgreSQL and Redis",
            120,
        )
        import psycopg

        with psycopg.connect(
            host="127.0.0.1",
            port=15432,
            user="helios_dev",
            dbname="postgres",
            autocommit=True,
        ) as database:
            if not database.execute(
                "SELECT 1 FROM pg_database WHERE datname = 'helios_dev'"
            ).fetchone():
                database.execute("CREATE DATABASE helios_dev")
        prepare_device()
        runtime = {
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "CONTROL_DEMO_DEVICE_ID",
                "CONTROL_PASSWORD_HASH",
                "HELIOS_DEVICE_ID",
                "HELIOS_CREDENTIAL_FILE",
                "HELIOS_BACKEND_WS",
                "HELIOS_FRAME_VERSION",
            }
        }
        temporary = STATE / "runtime.tmp"
        temporary.write_text(json.dumps(runtime))
        temporary.replace(STATE / "runtime.json")
        os.chdir(ROOT / "apps/backend")
        command = [sys.executable, "manage.py", "runserver", "127.0.0.1:8000"]
        print(
            "Open http://127.0.0.1:5173/control · Clemson email / SeniorDesign",
            flush=True,
        )
    else:
        print("Waiting for backend setup…", flush=True)
        wait_for(
            lambda: (
                (STATE / "runtime.json").exists()
                and ready("http://127.0.0.1:8000/api/ready/")
            ),
            [],
            "backend setup",
            120,
        )
        os.environ.update(json.loads((STATE / "runtime.json").read_text()))
        if name == "control":
            os.chdir(ROOT / "apps/backend")
            command = [sys.executable, "manage.py", "control_worker"]
        else:
            os.chdir(ROOT)
            command = [
                "uv",
                "run",
                "--locked",
                "--project",
                "apps/localization",
                "helios-localization",
                "simulate",
            ]
    os.execvpe(command[0], command, os.environ)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify startup and live telemetry, then stop",
    )
    parser.add_argument(
        "--service",
        choices=("postgres", "redis", "backend", "control", "frontend", "localization"),
    )
    args = parser.parse_args()
    if args.service:
        run_service(args.service)
        return
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True)
    STATE.chmod(0o700)
    lock = (STATE / "launcher.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("Helios development is already running in this checkout.")

    processes = []
    logs = STATE / "logs"
    logs.mkdir(exist_ok=True)

    def start(name, command, cwd=ROOT):
        with (logs / f"{name}.log").open("w") as output:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=os.environ.copy(),
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        processes.append((name, process))
        return process

    def interrupt(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        redis = shutil.which("redis-server")
        if not redis:
            raise RuntimeError(
                "Redis is required. On macOS: brew install postgresql@16 redis"
            )
        postgres, initdb = postgres_bin("postgres"), postgres_bin("initdb")
        for port in (15432, 16379, 8000, 5173):
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", port))
                except OSError as exc:
                    raise RuntimeError(
                        f"Port {port} is occupied. Stop its service and rerun pnpm dev."
                    ) from exc
        local_environment()
        print("Preparing Helios development…", flush=True)
        subprocess.run(
            ["uv", "sync", "--locked", "--project", "apps/localization"],
            cwd=ROOT,
            check=True,
        )
        if not (ROOT / "apps/frontend/node_modules/.bin/vite").exists():
            subprocess.run(
                ["pnpm", "install", "--frozen-lockfile"], cwd=ROOT, check=True
            )
        pgdata = STATE / "postgres"
        if not (pgdata / "PG_VERSION").exists():
            with (logs / "initdb.log").open("w") as output:
                subprocess.run(
                    [initdb, "-D", str(pgdata), "-A", "trust", "-U", "helios_dev"],
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    check=True,
                )
        start(
            "postgres",
            [
                postgres,
                "-D",
                str(pgdata),
                "-h",
                "127.0.0.1",
                "-p",
                "15432",
                "-k",
                "",
                "-c",
                "shared_buffers=32MB",
                "-c",
                "max_connections=30",
            ],
        )
        start(
            "redis",
            [
                redis,
                "--bind",
                "127.0.0.1",
                "--port",
                "16379",
                "--save",
                "",
                "--appendonly",
                "no",
            ],
        )
        wait_for(lambda: listening(15432), processes, "PostgreSQL")
        wait_for(lambda: listening(16379), processes, "Redis")
        import psycopg
        from psycopg import sql

        with psycopg.connect(
            host="127.0.0.1",
            port=15432,
            user="helios_dev",
            dbname="postgres",
            autocommit=True,
        ) as database:
            if not database.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", ("helios_dev",)
            ).fetchone():
                database.execute(
                    sql.SQL("CREATE DATABASE {} ").format(sql.Identifier("helios_dev"))
                )
        device_id = prepare_device()
        start(
            "backend",
            [sys.executable, "manage.py", "runserver", "127.0.0.1:8000"],
            ROOT / "apps/backend",
        )
        start(
            "control",
            [sys.executable, "manage.py", "control_worker"],
            ROOT / "apps/backend",
        )
        wait_for(
            lambda: ready("http://127.0.0.1:8000/api/ready/"), processes, "backend"
        )
        start(
            "frontend",
            [str(ROOT / "apps/frontend/node_modules/.bin/vite"), "--host", "127.0.0.1"],
            ROOT / "apps/frontend",
        )
        start(
            "localization",
            [str(ROOT / "apps/localization/.venv/bin/helios-localization"), "simulate"],
        )
        wait_for(lambda: ready("http://127.0.0.1:5173/control"), processes, "frontend")
        from control import presence

        def telemetry():
            state = presence.read(device_id)
            return (
                state
                and state.get("sequence", -1) >= 2
                and state.get("source_timestamp")
            )

        wait_for(telemetry, processes, "dummy telemetry")
        print(
            "\nHelios is ready: http://127.0.0.1:5173/control\n"
            "Sign in: any @clemson.edu email · Password: SeniorDesign\n"
            "All six services are running. Logs: .helios/dev/logs/\n"
            "Ctrl+C stops everything; local data is kept.\n",
            flush=True,
        )
        if args.check:
            return
        while True:
            for name, process in processes:
                if process.poll() is not None:
                    raise RuntimeError(
                        f"{name} exited. See .helios/dev/logs/{name}.log"
                    )
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping Helios…", flush=True)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Helios could not start: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Reverse startup order: clients and app processes stop before their dependencies.
        for _, process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
        lock.close()


if __name__ == "__main__":
    main()
