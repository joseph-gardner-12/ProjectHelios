# Helios localization

The localization application now includes a backend-connected dummy runtime.
It runs on a laptop or Raspberry Pi without ranging or flight hardware.
Real ranging, replay, and flight-controller integration remain unimplemented.

`transport.py` owns the outbound WebSocket, authentication, heartbeats, and
reconnection. `coordinator.py` owns command validation and lifecycle.
`simulation.py` owns dummy coordinates. Typed positions and targets cross these
boundaries; transport does not depend on a real sensor or solver.

## Run the dummy client

For the complete laptop demo, start all processes in Solo or run `pnpm dev`
from the repository root. The dummy client is included and configured automatically.

For a standalone Pi with a device already provisioned on the backend, configure
once (the credential stays in its restricted file):

```sh
pnpm pi:setup
```

Then start it with:

```sh
pnpm pi
```

The setup prompts for the WSS URL, device UUID, and credential-file path. It saves
settings to `~/.config/helios/localization.json` with mode 0600. Override the config
location with `HELIOS_CONFIG_FILE`; CLI options and `HELIOS_*` environment variables
override saved settings. Without pnpm, use `helios-localization configure` and
`helios-localization simulate` from the installed Python environment.

Equivalent CLI flags are `--device-id`, `--credential-file`, `--url`, and
`--frame-version`. The default frame is `dummy-enu-v1`. Use WSS outside loopback;
production uses `wss://api.projecthelios.dev/ws/v1/pi/`.

The client starts at the dummy origin, reports positions at 5 Hz, acknowledges
valid targets, and moves at 0.5 m/s. Disconnection clears the target. A reconnect
retains only the in-process position and starts idle; a process restart starts
at the origin. Old targets never resume automatically.

`run` and `replay` fail explicitly rather than falling back to simulation.
No target is forwarded to aircraft hardware. Future real localization must
report measurements independently of requested targets.

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
