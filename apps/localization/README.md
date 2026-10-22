# Helios localization

The localization application now includes a backend-connected dummy runtime.
It runs on a laptop or Raspberry Pi without ranging or flight hardware.
A separate measurement-only runtime now supports documented MaUWB AT reports,
nonlinear correction, bounded prediction, recording/replay, and optional disarmed
external-navigation bench output. Hardware qualification remains pending. See
[measurement setup](../../docs/localization.md) for survey configuration and commands.

## Record UWB range reports

The MaUWB A4 collector shown in the commissioning record has automatic reporting
enabled on `COM4` at 115200 baud. Close the Makerfabs Configuration Tool first,
then record its read-only USB stream:

```sh
uv run --locked --project apps/localization helios-localization record-ranges
```

This writes append-only JSON Lines to `a4-range-reports.jsonl`. Override the
port, baud rate, or output path with `--port`, `--baud`, and `--output`. The
recorder never sends AT commands. Add `--echo` to print active ranges as a JSON
mapping from anchor ID to centimetres. For example, a report with ranges to
anchors 0, 2, 3, and 4 prints `{"0": 208, "2": 271, "3": 322, "4": 143}`. The
JSON Lines file retains the raw report and the matching anchor IDs. Stop it with
Ctrl+C.

`transport.py` owns the outbound WebSocket, authentication, heartbeats, and
reconnection. `coordinator.py` owns command validation and lifecycle.
`simulation.py` owns dummy coordinates. Typed positions and targets cross these
boundaries; transport does not depend on a real sensor or solver.

## Run the dummy client

For the complete laptop demo, start all processes in Solo or run `pnpm dev`
from the repository root. The dummy client is included and configured automatically.

For a standalone computer, register once using a computer name and the shared
registration password set in Django admin. No SSH, device UUID, or credential
transfer is needed:

```sh
pnpm pi:setup
```

Then start it with:

```sh
pnpm pi
```

The terminal shows each sent position (5 times per second, with X/Y/Z in meters),
received targets, sent acknowledgments and arrivals, and connection events.
To also save the output, run `pnpm pi 2>&1 | tee /tmp/helios-pi.log`.
With `pnpm dev`, follow the same output using
`tail -f .helios/dev/logs/localization.log`; in Solo, open **Dummy localization**.

Setup defaults to `https://api.projecthelios.dev`, asks for the computer name and
registration password, and saves a unique credential plus
`~/.config/helios/localization.json` with mode 0600. It never saves the shared
password. The backend attaches new computers to the existing control device.
For a local backend, use `pnpm pi:setup --backend http://127.0.0.1:8000`.

Existing configurations and credentials continue working without setup. The
migration lists their computers in Django admin as legacy registrations; an
administrator can rename them. Running setup again preserves an existing config.
Use `pnpm pi:setup --force` only to intentionally create a replacement registration;
the previous registration remains available for the administrator to disable.

Only one computer may connect to this backend at a time. A second `pnpm pi`
prints the active computer's name and exits with status 3 without retrying or
interrupting the active computer. Stop the active program before starting another.
After a crash, allow five seconds for the connection lease to expire. Rejected
credentials exit with status 4; temporary network failures retry automatically.

Override the config location with `HELIOS_CONFIG_FILE`; CLI options and `HELIOS_*`
environment variables override saved settings. Clear stale environment overrides
if a client uses an unexpected connection. CLI flags remain `--device-id`,
`--credential-file`, `--url`, and `--frame-version`; the default frame is
`dummy-enu-v1`. Use WSS outside loopback. Without pnpm, the Python commands are
`helios-localization configure` and `helios-localization simulate`.

The client starts at the dummy origin, reports positions at 5 Hz, acknowledges
valid targets, and moves at 0.5 m/s. Disconnection clears the target. A reconnect
retains only the in-process position and starts idle; a process restart starts
at the origin. Old targets never resume automatically.

`run` uses measured ranges and aircraft altitude; `replay` processes recorded
sensor input offline. Neither falls back to dummy motion or executes targets.
External-position bench output is disabled by default and never sends predictions.

## Tests and Pi service

`pnpm test:localization` tests the shared coordinate contract, acknowledgment
ordering, movement, arrival dwell, expiry, duplicates, and interruption.

Use the versioned `deploy/helios-localization.service` and
`deploy/localization.env.example` for Pi deployment. Install Python 3.14 and locked
dependencies under `/opt/helios/apps/localization`, create the unprivileged
`helios-pi` account, and put its credential at `/etc/helios/pi.credential` with
mode 0600 owned by `helios-pi`. Keep the environment file root-owned, readable by
that service's group. Review the service paths before enabling it.

See the [control setup guide](../../docs/control-setup.md) and
[protocol](../../contracts/control-v1/README.md).

For new service installations, run setup as the service account with
`HELIOS_CONFIG_FILE` pointing to a writable location such as
`/var/lib/helios-pi/localization.json`, and configure that path in the service's
environment. Remove the old `HELIOS_DEVICE_ID`, `HELIOS_CREDENTIAL_FILE`, and
`HELIOS_BACKEND_WS` overrides when using saved configuration. Existing service
installations can retain those overrides and their original credential. Install
the updated unit with `RestartPreventExitStatus=3 4` so conflict and credential
errors remain stopped rather than being automatically restarted. The unit invokes
the Python entry point directly and preserves these statuses.

## Real tag tracking

Use `pnpm dev --survey /absolute/path/real-survey.toml` to connect the collector
to the nonlinear solver and local dashboard. Both `record-ranges` and `run` now
use the same anchor-ID parser. Supply a real four-anchor survey and either
flight-controller altitude or an explicit fixed-height bench constraint. See
[real collector setup](../../docs/localization.md#connect-the-real-collector-to-the-dashboard).
