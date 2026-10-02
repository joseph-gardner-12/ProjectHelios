import argparse
import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .transport import run


def config_path():
    return Path(os.getenv("HELIOS_CONFIG_FILE", "~/.config/helios/localization.json")).expanduser()


def validate(url_text, device_id, credential_file):
    uuid.UUID(device_id)
    url = urlsplit(url_text)
    if (
        url.scheme not in {"ws", "wss"}
        or not url.hostname
        or url.username
        or url.password
        or (url.scheme == "ws" and url.hostname not in {"localhost", "127.0.0.1", "::1"})
    ):
        raise ValueError("Use WSS outside loopback development")
    if not credential_file.is_file():
        raise ValueError("Credential file does not exist")


def configure():
    url = input("Backend WSS URL [wss://api.projecthelios.dev/ws/v1/pi/]: ").strip()
    url = url or "wss://api.projecthelios.dev/ws/v1/pi/"
    device_id = input("Provisioned device UUID: ").strip()
    credential_file = Path(input("Credential file path: ").strip()).expanduser().resolve()
    validate(url, device_id, credential_file)
    destination = config_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Store the credential path, never the bearer credential itself.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(
            {"url": url, "device_id": device_id, "credential_file": str(credential_file)}, output
        )
        output.write("\n")
    print(f"Saved {destination}. Start with pnpm pi (or helios-localization simulate).")


def main():
    parser = argparse.ArgumentParser(description="Helios localization runtime")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("configure", help="Save the Pi connection settings once")
    try:
        saved = json.loads(config_path().read_text()) if config_path().exists() else {}
    except (OSError, ValueError) as exc:
        parser.error(f"Cannot read localization configuration: {exc}")
    simulate = commands.add_parser(
        "simulate", help="Backend-connected dummy positions; no hardware"
    )
    simulate.add_argument(
        "--url",
        default=os.getenv("HELIOS_BACKEND_WS", saved.get("url", "ws://127.0.0.1:8000/ws/v1/pi/")),
    )
    simulate.add_argument(
        "--credential-file",
        type=Path,
        default=os.getenv("HELIOS_CREDENTIAL_FILE", saved.get("credential_file")),
    )
    simulate.add_argument(
        "--device-id", default=os.getenv("HELIOS_DEVICE_ID", saved.get("device_id"))
    )
    simulate.add_argument(
        "--frame-version", default=os.getenv("HELIOS_FRAME_VERSION", "dummy-enu-v1")
    )
    commands.add_parser("run", help="Hardware runtime (not implemented)")
    commands.add_parser("replay", help="Recorded ranging replay (not implemented)")
    args = parser.parse_args()
    if args.command == "configure":
        try:
            configure()
        except (OSError, ValueError, EOFError) as exc:
            parser.error(str(exc))
        return
    if args.command != "simulate":
        parser.error("Hardware and replay modes are not implemented; no dummy fallback")
    if not args.credential_file or not args.credential_file.is_file() or not args.device_id:
        parser.error("A credential file and device ID are required")
    try:
        validate(args.url, args.device_id, args.credential_file)
    except ValueError as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(run(args.url, args.credential_file, args.device_id, args.frame_version))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
