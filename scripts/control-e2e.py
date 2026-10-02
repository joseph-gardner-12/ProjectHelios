"""Run the browser/Pi loop against a disposable PostgreSQL database and Redis.

POSTGRES_DB must end in _e2e. This script never uses the local SQLite database.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if not os.environ.get("POSTGRES_DB", "").endswith("_e2e") or not os.environ.get(
    "REDIS_URL"
):
    sys.exit("Set POSTGRES_* for a disposable database ending in _e2e, and REDIS_URL")
sys.path.insert(0, str(ROOT / "apps/backend"))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.local"
os.environ["CONTROL_REDIS_PREFIX"] = f"helios:e2e:{uuid.uuid4()}"

import django

django.setup()
from control.models import Device
from control.services import issue_credential
from django.contrib.auth.hashers import make_password
from django.core.management import call_command

call_command("migrate", verbosity=0)
device = Device.objects.create(name="Browser acceptance dummy")
processes = []
with tempfile.TemporaryDirectory(prefix="helios-e2e-") as temporary:
    credential = Path(temporary) / "pi.credential"
    credential.write_text(issue_credential(device))
    credential.chmod(0o600)
    env = {
        **os.environ,
        "CONTROL_DEMO_DEVICE_ID": str(device.id),
        "CONTROL_PASSWORD_HASH": make_password("e2e-demo-password"),
        "HELIOS_DEVICE_ID": str(device.id),
        "HELIOS_CREDENTIAL_FILE": str(credential),
        "HELIOS_BACKEND_WS": "ws://127.0.0.1:18000/ws/v1/pi/",
        "HELIOS_DEV_BACKEND": "http://127.0.0.1:18000",
        "HELIOS_E2E_PASSWORD": "e2e-demo-password",
        "HELIOS_E2E_RUN": str(uuid.uuid4()),
        "pnpm_config_verify_deps_before_run": "false",
    }
    logs = []
    try:
        commands = [
            (
                [
                    str(ROOT / "apps/backend/.venv/bin/daphne"),
                    "-b",
                    "127.0.0.1",
                    "-p",
                    "18000",
                    "config.asgi:application",
                ],
                ROOT / "apps/backend",
            ),
            ([sys.executable, "manage.py", "control_worker"], ROOT / "apps/backend"),
            (
                [
                    str(ROOT / "apps/frontend/node_modules/.bin/vite"),
                    "--host",
                    "127.0.0.1",
                ],
                ROOT / "apps/frontend",
            ),
        ]
        for index, (command, cwd) in enumerate(commands):
            logfile = Path(temporary) / f"service-{index}.log"
            logs.append(logfile)
            with logfile.open("w") as output:
                processes.append(
                    subprocess.Popen(
                        command,
                        cwd=cwd,
                        env=env,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                )
        for url in (
            "http://127.0.0.1:18000/api/ready/",
            "http://127.0.0.1:5173/control",
        ):
            for attempt in range(100):
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError("A test service exited")
                try:
                    with urlopen(url, timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError(f"Service did not become ready: {url}")
        env["HELIOS_E2E_BACKEND_PID"] = str(processes[0].pid)
        result = subprocess.run(
            [str(ROOT / "apps/frontend/node_modules/.bin/playwright"), "test"],
            cwd=ROOT / "apps/frontend",
            env=env,
            check=False,
        )
        evidence = ROOT / "output/control-e2e.json"
        evidence.parent.mkdir(exist_ok=True)
        evidence.write_text(
            json.dumps(
                {
                    "device_id": str(device.id),
                    "exit_code": result.returncode,
                    "completed_at": time.time(),
                },
                indent=2,
            )
        )
        if result.returncode:
            raise RuntimeError("Browser acceptance failed")
    except Exception:
        for logfile in logs:
            print(f"--- {logfile.name} ---\n{logfile.read_text()[-12000:]}")
        raise
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
