"""Interactive computer enrollment; no backend shell access required."""

import getpass
import json
import os
import socket
import tempfile
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

DEFAULT_BACKEND = "https://api.projecthelios.dev"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the registration password to a redirected origin.
        return None


def backend_origin(value):
    url = urlsplit(value)
    if (
        url.scheme not in {"https", "http"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
        or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"})
    ):
        raise ValueError("Use an HTTPS backend origin (HTTP is allowed only on loopback).")
    return f"{url.scheme}://{url.netloc}"


def enroll(backend, name, password):
    request = Request(
        f"{backend}/api/v1/machines/register/",
        data=json.dumps({"name": name, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with build_opener(NoRedirect).open(request, timeout=15) as response:
            result = json.loads(response.read(8192))
    except HTTPError as exc:
        messages = {
            400: "Invalid computer name. Use 1–100 characters.",
            401: "Incorrect registration password.",
            403: "Registration is disabled or not configured. Ask the administrator.",
            404: "This backend does not support computer registration yet.",
            429: "Too many registration attempts. Try again in five minutes.",
        }
        raise ValueError(
            messages.get(exc.code, "Backend could not complete registration.")
        ) from None
    except URLError, TimeoutError, OSError:
        raise ValueError(
            "Cannot reach the backend. Check the address and connection, then retry."
        ) from None
    try:
        uuid.UUID(result["machine_id"])
        uuid.UUID(result["device_id"])
        key, secret = result["credential"].split(".", 1)
        uuid.UUID(key)
        if not secret or result["websocket_path"] != "/ws/v1/pi/":
            raise ValueError
        if not isinstance(result["frame_version"], str) or not result["frame_version"]:
            raise ValueError
    except KeyError, TypeError, AttributeError, ValueError:
        raise ValueError("Backend returned invalid registration settings.") from None
    return result


def save_registration(destination, backend, result):
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Use a new credential file so a failed config replacement cannot break the old setup.
    credential = (
        destination.parent / f"machine-{result['machine_id']}-{uuid.uuid4().hex}.credential"
    )
    temporary = None
    try:
        fd = os.open(credential, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(result["credential"] + "\n")
        origin = urlsplit(backend)
        config = {
            "url": f"{'wss' if origin.scheme == 'https' else 'ws'}://{origin.netloc}/ws/v1/pi/",
            "device_id": result["device_id"],
            "machine_id": result["machine_id"],
            "credential_file": str(credential.resolve()),
            "frame_version": result["frame_version"],
        }
        fd, temporary = tempfile.mkstemp(prefix=".registration-", dir=destination.parent)
        with os.fdopen(fd, "w") as output:
            json.dump(config, output)
            output.write("\n")
        os.replace(temporary, destination)
    except OSError:
        credential.unlink(missing_ok=True)
        raise ValueError(
            "Could not save registration. Existing settings were preserved. "
            "Fix local file permissions and retry; "
            "the administrator can disable the unused registration."
        ) from None
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def configure(destination, backend=DEFAULT_BACKEND, force=False):
    if destination.exists() and not force:
        print(f"Already configured in {destination}. Run pnpm pi to connect.")
        print("To replace this registration, run pnpm pi:setup --force.")
        return
    backend = backend_origin(backend)
    default_name = socket.gethostname()[:100]
    name = input(f"Computer name [{default_name}]: ").strip() or default_name
    if len(name) > 100 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError("Use a computer name of 1–100 characters without control characters.")
    password = getpass.getpass("Registration password: ")
    result = enroll(backend, name, password)
    save_registration(destination, backend, result)
    print("Registered successfully. Run pnpm pi to connect.")
