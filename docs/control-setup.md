# Set up dummy browser and Pi control

This guide runs the authenticated control queue and dummy localization client.
The shared password is a demonstration access gate; a Clemson email is checked
for format only. No physical flight commands are implemented.

## Local setup with Solo

Install Node.js 24+, pnpm 11.2.2, uv, PostgreSQL 16, and Redis. On macOS,
`brew install postgresql@16 redis` installs the two services; don't start global
services for this workflow. Install JavaScript dependencies once with
`pnpm install --frozen-lockfile`.

Add this repository folder to [Solo](https://soloterm.com/docs/projects/solo-yml)
and load/trust its `solo.yml`, just like Staccato Music. Start all processes.
There are separate panes for PostgreSQL, Redis, Backend, Control worker,
Frontend, and Dummy localization. Django and Vite reload on source changes.
The other panes can be restarted individually. Automatic process restart is
disabled so stopping the dummy client stays stopped for interruption checks.

The backend pane waits for its dependencies, applies migrations, provisions a
local device and private credential, and configures the demo login automatically.
The worker and dummy client wait for backend setup. No environment exports or
manual device setup are needed. Open `http://127.0.0.1:5173/control` and sign in
with a Clemson-format email and `SeniorDesign`.

For a single-terminal alternative, run:

```sh
pnpm dev
```

This starts the same six services and stops them with Ctrl+C. Don't run it at
the same time as the Solo processes. Logs are in `.helios/dev/logs/`.

Local data and credentials stay in ignored `.helios/dev/`; PostgreSQL uses
port 15432, Redis 16379, Django 8000, and Vite 5173. These launchers force local
settings rather than inheriting production database or API destinations.
PostgreSQL data persists across stops; Redis presence does not. A newly started
dummy process begins at the origin and never resumes an old target.

For a separately running computer, run `pnpm pi:setup` once. Enter a computer
name and the shared registration password; the production backend URL and
connection settings are handled automatically. Then start it with `pnpm pi`.
The password is set in Django admin under **Computer registration settings**.
This configuration is separate from the automatically provisioned local demo.
Only one computer can connect to the backend at a time; a second exits with a
readable error without disconnecting the active computer.

## Manual check

Open `http://127.0.0.1:5173/control`.
Sign in with two different Clemson-format emails in separate browser profiles.
Only the current controller should have an enabled **Send target** button.

Send a nearby target. Confirm acknowledgment, moving positions in both browsers,
and arrival before a second send is enabled. Reset should change only selection
to `(5, 5, 5)` feet. Release the turn and confirm the next browser gains control.

Stop the simulator during movement. Both browsers should mark the retained
position stale and disable sending. Restart it: the position returns to the
dummy origin, the old command stays interrupted, and movement does not resume.
Test browser refresh and sign-out separately from Pi disconnection.

## Automated checks

Run `pnpm check` and `pnpm build`. The default backend suite skips tests requiring
external services; the localization and frontend contract tests run normally.
To run backend integration tests, provide disposable PostgreSQL/Redis settings,
set `HELIOS_INTEGRATION_TESTS=1`, and run `pnpm test:backend`.

For the two-browser acceptance test, create a separate PostgreSQL database whose
name ends in `_e2e`, export its `POSTGRES_*` variables and `REDIS_URL`, and run:

```sh
pnpm --filter @project-helios/frontend exec playwright install chromium
uv run --locked --project apps/backend python scripts/control-e2e.py
```

Ports 18000 and 5173 must be free. The harness starts and stops its own Django,
lifecycle worker, Vite, and localization processes. It uses a unique Redis
namespace, writes temporary credentials, and stores screenshots and command
IDs under ignored `output/`. It adds test users/devices only to the specified
throwaway database; discard that database when finished.

## Production preparation and manual acceptance

No repository edit deploys this feature. Install the new backend service asset
through the existing bootstrap workflow, then deploy backend migrations and code
before enabling the frontend. `helios-control.service` is enabled as a dependency
of `helios.service`; backend stop/restart also stops/restarts the worker.
For rollback to code predating control, disable the worker first; migrations are
additive and need not be reversed.

For an existing server, deploy the backend code and migrations successfully
before starting the new worker. From the repository root on your Mac, with
`HELIOS_IP` set to the server address, install and start only the new service:

```sh
scp -i ~/.ssh/helios_ed25519 deploy/helios-control.service root@"$HELIOS_IP":/etc/systemd/system/helios-control.service && ssh -i ~/.ssh/helios_ed25519 root@"$HELIOS_IP" 'systemctl daemon-reload && systemctl enable --now helios-control.service && systemctl status helios-control.service --no-pager'
```

If logs show `Unknown command: 'control_worker'`, the active backend release
does not register the new command. Copying a service file does not deploy Python
code. Stop the restart loop with `systemctl disable --now helios-control.service`
on the server, deploy the updated backend, then run
`systemctl enable --now helios-control.service`. Inspect startup with
`journalctl -u helios-control.service -n 50 --no-pager`.

After deploying these migrations and restarting the backend/worker, open
`https://api.projecthelios.dev/admin/control/registrationsettings/1/change/` and
set the shared registration password. Keep registration enabled, then save.
Students can now use `pnpm pi:setup` without server access. The browser demo
password and the computer registration password are separate settings.

The existing device and credentials are preserved: migration 0003 adds a named
legacy computer for each credential without changing its UUID, secret hash,
revocation status, or device association. Existing config files and environment
variables keep working. Rename the legacy computer under **Machines** in admin
if desired; do not create a replacement Device or rerun setup on that computer.
New computers use the configured `CONTROL_DEMO_DEVICE_ID`, or the sole enabled
Device when that setting is absent. Ambiguous or missing devices block enrollment.
Changing the registration password does not revoke existing computer credentials.

Update the old computer's checkout/client to get terminal conflict handling.
An old client still authenticates but its old reconnect loop will keep retrying
when blocked; the backend will never let it take over an occupied slot. The normal
backend deployment restarts Daphne and drops existing sockets, which reconnect
using the preserved credential. Do not run old and new backend versions together
for this policy change: old application code still implements replacement.

Migration 0002 creates new tables only; 0003 backfills computer metadata. Neither
rewrites nor replaces existing Device or DeviceCredential records. Normal GitHub
backend deployment applies migrations and restarts services. No SSH is needed to
set the registration password or register subsequent computers. The Pi systemd
unit must be updated separately if used; its conflict/authentication exit codes
are excluded from automatic restart. See the localization README for service setup.

The frontend defaults to `https://api.projecthelios.dev` in production. Optional
`VITE_API_ORIGIN` overrides both HTTP and WebSocket origins. Keep the allowed
CORS, CSRF, and WebSocket origins set to the actual frontend domain, including
`https://www.projecthelios.dev` and the apex domain. Preview deployment domains
are not authorized automatically.

Verify deployed WSS from the real frontend with two users and the real Pi.
Record command IDs and timestamps; test interruption, idle reconnection, turn
handoff, and revoking the credential in Django admin. Revocation should close the
existing connection within the heartbeat interval and block future connections.

The 5 Hz browser telemetry and dummy arrival tolerance are not physical-flight
qualification criteria. Real Pi, systemd, and production-domain acceptance must
be recorded separately from the local automated test results.
