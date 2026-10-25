import argparse
import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .ranging import DEFAULT_BAUDRATE, DEFAULT_PORT, record_range_reports
from .registration import DEFAULT_BACKEND, configure
from .transport import TerminalConnectionError, run


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


def main():
    parser = argparse.ArgumentParser(description="Helios localization runtime")
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("configure", help="Register this computer with the backend")
    setup.add_argument("--backend", default=DEFAULT_BACKEND, help="Backend HTTP origin")
    setup.add_argument("--force", action="store_true", help="Replace the saved registration")
    simulate = commands.add_parser(
        "simulate", help="Backend-connected dummy positions; no hardware"
    )
    simulate.add_argument("--url")
    simulate.add_argument("--credential-file", type=Path)
    simulate.add_argument("--device-id")
    simulate.add_argument("--frame-version")
    record_ranges = commands.add_parser(
        "record-ranges", help="Record automatic MaUWB range reports from a USB collector"
    )
    record_ranges.add_argument("--port", default=DEFAULT_PORT, help="Collector serial port")
    record_ranges.add_argument(
        "--baud", type=int, default=DEFAULT_BAUDRATE, help="Collector serial baud rate"
    )
    record_ranges.add_argument(
        "--output", type=Path, default=Path("a4-range-reports.jsonl"), help="JSON Lines output"
    )
    record_ranges.add_argument(
        "--echo",
        action="store_true",
        help="Print active ranges as JSON anchor-ID-to-centimetre mappings",
    )
    demo = commands.add_parser("simulate-uwb", help="Synthetic ranges through the real solver")
    demo.add_argument("--survey", type=Path, required=True)
    live = commands.add_parser("run", help="Measurement-only hardware runtime")
    live.add_argument("--survey", type=Path, required=True)
    live.add_argument("--record", type=Path, required=True)
    live.add_argument("--capture-only", action="store_true")
    live.add_argument("--cloud", action="store_true", help="Publish read-only observations")
    recorded = commands.add_parser("replay", help="Offline deterministic measurement replay")
    recorded.add_argument("--survey", type=Path, required=True)
    recorded.add_argument("recording", type=Path)
    calibration = commands.add_parser(
        "calibrate-square", help="Estimate bench square size from a stationary interior tag"
    )
    calibration.add_argument("--survey", type=Path, required=True)
    calibration.add_argument("--recording", type=Path, required=True)
    calibration.add_argument(
        "--output", type=Path, required=True, help="New survey; never overwritten"
    )
    calibration.add_argument(
        "--corners",
        nargs=4,
        default=["A0", "A2", "A3", "A4"],
        metavar=("ORIGIN", "X", "Y", "DIAGONAL"),
    )
    calibration.add_argument(
        "--interior-tag",
        action="store_true",
        required=True,
        help="Confirm a stationary tag inside a physical square, at the anchors' antenna height",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "calibrate-square":
        from dataclasses import asdict

        from .calibration import calibrate_recording, write_square_survey
        from .config import load_settings

        try:
            result = calibrate_recording(args.recording, load_settings(args.survey), args.corners)
            write_square_survey(args.survey, args.output, result)
            print(json.dumps({**asdict(result), "survey": str(args.output)}, allow_nan=False))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            parser.error(str(exc))
        return
    if args.command == "configure":
        try:
            configure(config_path(), args.backend, args.force)
        except (OSError, ValueError, EOFError) as exc:
            parser.error(str(exc))
        return
    if args.command == "record-ranges":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        try:
            record_range_reports(args.port, args.output, baudrate=args.baud, echo=args.echo)
        except KeyboardInterrupt:
            pass
        return
    if args.command == "replay":
        from .config import load_settings
        from .replay import replay

        try:
            for result in replay(args.recording, load_settings(args.survey)):
                print(json.dumps(result.as_dict(), allow_nan=False))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            parser.error(str(exc))
        return
    if args.command == "run" and not args.cloud:
        from .config import load_settings
        from .runtime import run_measurements

        try:
            asyncio.run(
                run_measurements(
                    load_settings(args.survey), args.record, capture_only=args.capture_only
                )
            )
        except KeyboardInterrupt:
            pass
        except (OSError, ValueError, TypeError) as exc:
            parser.error(str(exc))
        return
    try:
        saved = json.loads(config_path().read_text()) if config_path().exists() else {}
        if not isinstance(saved, dict):
            raise ValueError("Expected a settings object")
        args.url = getattr(args, "url", None) or os.getenv(
            "HELIOS_BACKEND_WS", saved.get("url", "ws://127.0.0.1:8000/ws/v1/pi/")
        )
        credential = getattr(args, "credential_file", None) or os.getenv(
            "HELIOS_CREDENTIAL_FILE", saved.get("credential_file")
        )
        args.credential_file = Path(credential).expanduser() if credential else None
        args.device_id = getattr(args, "device_id", None) or os.getenv(
            "HELIOS_DEVICE_ID", saved.get("device_id")
        )
        args.frame_version = getattr(args, "frame_version", None) or os.getenv(
            "HELIOS_FRAME_VERSION", saved.get("frame_version", "dummy-enu-v1")
        )
    except (OSError, ValueError, TypeError) as exc:
        parser.error(f"Cannot read localization configuration: {exc}. Run pnpm pi:setup --force.")
    if not args.credential_file or not args.credential_file.is_file() or not args.device_id:
        parser.error(
            "Run pnpm pi:setup to register this computer (credential file or device ID missing)"
        )
    try:
        validate(args.url, args.device_id, args.credential_file)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        if args.command == "simulate-uwb":
            from .config import load_settings
            from .demo import run_demo

            asyncio.run(
                run_demo(
                    load_settings(args.survey),
                    {
                        "url": args.url,
                        "credential_file": args.credential_file,
                        "device_id": args.device_id,
                    },
                )
            )
        elif args.command == "run":
            from .config import load_settings
            from .runtime import run_measurements

            asyncio.run(
                run_measurements(
                    load_settings(args.survey),
                    args.record,
                    capture_only=args.capture_only,
                    cloud={
                        "url": args.url,
                        "credential_file": args.credential_file,
                        "device_id": args.device_id,
                    },
                )
            )
        else:
            asyncio.run(run(args.url, args.credential_file, args.device_id, args.frame_version))
    except TerminalConnectionError as exc:
        parser.exit(exc.exit_status, f"{exc}\n")
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
