# Backend and Raspberry Pi WebSocket implementation plan

Status: historical proposal, 2026-10-02. The implementation evolved from this
plan. See [control setup](../control-setup.md) and the
[protocol contract](../../contracts/control-v1/README.md) for current behavior;
the original scope and timing recommendations below are retained for context.

Deliver a complete simulated data path: an authenticated user selects a target,
Django sends it to the dock Pi, the Pi acknowledges it and generates dummy
positions, and the browser displays those positions live. Use the existing
Channels, Daphne, Redis and Caddy architecture described in the
[research](../research/backend-pi-websocket.md). Preserve the local supervision
boundary in [ADR-0001](../adr/0001-uwb-sik-ardupilot-navigation.md).

## Release scope and defaults

- One provisioned dock device and one authorized operator initially; enforce
  device permissions throughout so additional users cannot bypass isolation.
- Pi initiates an outbound WebSocket. Browser submits targets through HTTP and
  receives position and command events through its own WebSocket.
- Keep UI inputs/display in feet. Convert once at the API boundary using
  `metres = feet × 0.3048`; all protocol coordinates use dock ENU metres.
- Start with the existing 0–10 ft demo cube, represented as 0–3.048 m per axis
  in server/device configuration. Use `demo-dock-enu-v1` to distinguish this
  synthetic frame from a future surveyed frame.
- Publish dummy position at 5 Hz; mark position stale after 2 seconds without a
  fresh sample. Start with a 3-second acknowledgment deadline, 10-second target
  acceptance expiry and 20-second ping/pong intervals. These are configurable
  demo defaults, not qualified flight parameters.
- Send only on explicit user action. Permit one unresolved request per device;
  after acknowledgment, a new target may replace the simulator's active target.
- Include authentication, acknowledgments, duplicate handling and reconnects in
  the first release. Hardware acquisition, MAVLink, flight commands, historical
  telemetry storage and automatic offline command delivery remain later work.

## Phase 1 Define the protocol and state transitions

Create `docs/protocols/device-websocket-v1.md` and shared JSON fixtures under
`tests/fixtures/device-protocol/`. Use the research's message examples as the
starting point; make the following contracts authoritative in the protocol doc.

| Direction | Messages and purpose |
| --- | --- |
| Pi → backend | `hello`: boot identity, protocol/frame version and simulation mode |
| Backend → Pi | `welcome`: server-assigned session ID and protocol configuration |
| Backend → Pi | `target.set`: command ID, session ID, expiry, frame and metre coordinates |
| Pi → backend | `target.ack`: accepted or rejected, with a stable reason code |
| Pi → backend | `position`: session/boot ID, sequence, sample timestamp, position, active command ID and simulated flag |
| Backend ↔ Pi | `state.request` / `state.report`: query command disposition without resending a target |
| Backend → browser | Initial snapshot, position, command status and device presence |

Define strict validation for finite numeric coordinates, UUIDs, versions, frame
identity, sequence ordering, maximum payload size (initially 16 KiB), message
direction and required fields. Reject booleans as numeric coordinates. Use server
receive timestamps for connection freshness and preserve Pi sample timestamps
separately. Telemetry freshness must also require advancing sequence numbers.

Define command states: `pending`, `dispatching`, `accepted`, `rejected`,
`expired`, `unknown` and `abandoned`. Mark `dispatching` durably before attempting
a socket send. A timeout or crash after that point becomes `unknown`; only a
never-dispatched expired command can be classified as `expired`. Accepted means
the simulator accepted the target, not that the target has been reached.

Unknown commands block another submission until reconciliation or explicit
operator abandonment. Abandonment only unblocks the demo; it does not cancel a
target already accepted by the Pi. Record the operator and time. Terminal states
must not regress when delayed messages arrive.

Completion: protocol fixtures cover a successful exchange, rejection, duplicate,
late acknowledgment, stale session and reconnect reconciliation. Both Python
implementations and TypeScript types have a single documented contract to follow.

## Phase 2 Add device records and authenticated HTTP APIs

Create `apps/backend/devices/` with models, migrations, admin registration,
credential management commands, validators, command services and views. Register
the app and URLs in the existing Django configuration.

Store a device UUID, authorized operator relationship, enabled flag, frame and
demo limits. Store revocable credential identifiers and secret hashes; expose a
new secret only during provisioning/rotation. Persist each target with its
request ID, device, operator, payload, session, status, timestamps and rejection
reason. Enforce uniqueness for `(device, client_request_id)` and serialize command
creation per device in a database transaction. Test concurrent submissions on
PostgreSQL; SQLite alone cannot establish production locking behavior.

| Proposed route | Behavior |
| --- | --- |
| `GET /api/auth/csrf/` | Supply a CSRF token for credentialed requests |
| `POST /api/auth/login/` | Authenticate using Django sessions |
| `POST /api/auth/logout/` | End the session |
| `GET /api/auth/session/` | Return current user and authorized devices |
| `GET /api/devices/{id}/state/` | Return connection freshness, latest sample and command state |
| `POST /api/devices/{id}/targets/` | Validate and persist a target; return command ID/status |
| `GET /api/devices/{id}/commands/{command_id}/` | Recover status after HTTP/socket interruption |
| `POST /api/devices/{id}/commands/{command_id}/abandon/` | Explicitly resolve an unknown demo request, without implying cancellation |

Return the existing command for identical request-ID retries; return conflict if
the same ID is reused with another payload. Reject offline/stale devices and
conflicting unresolved requests. Recheck the current session at dispatch because
presence can change after HTTP validation. Add bounded login and target-request
rate limits with explicit error responses. Use existing users/admin provisioning;
self-service registration is outside this release.

Completion: API tests prove authentication, CSRF, device isolation, unit bounds,
idempotency, concurrency and valid state transitions. Migrations work on fresh
SQLite and PostgreSQL databases without changing existing domain data.

## Phase 3 Implement backend WebSocket transport

Add `devices/consumers.py`, routing, device authentication middleware and presence
helpers. Replace the reject-all WebSocket branch in `config/asgi.py` with:

- `/ws/device/`: authenticate the bearer credential before accepting; require
  timely `hello`, bind identity to the credential and return a new session ID.
- `/ws/devices/{id}/events/`: use Django sessions, explicit frontend origin
  validation and device authorization before joining any group.

Use a Redis lease for the authoritative device session, refreshed by valid
messages. Atomically replace the lease on a new connection; every dispatch and
telemetry update must check ownership. An old connection's disconnect handler
must only remove its own lease. Record sessions in command records to prevent
delivery to a different connection following a race.

Persist commands before notifying the device consumer through Channels. The
consumer reloads and validates the command before marking it `dispatching` and
sending. Bound acknowledgment waits. Reconcile expired pending/dispatching
records on connection, state reads and new submissions so recovery does not rely
on an in-process timer surviving a restart. Never automatically resend movement
after reconnect; request the Pi's command state instead.

Cache only the newest telemetry sample per device with a freshness timestamp and
TTL. Join browser groups before reading the initial snapshot, then deduplicate by
session/sequence or command revision. Renew long-lived group membership. Recheck
authorization periodically and on relevant messages so logout or device-token
revocation closes existing sessions within a documented bounded interval.

On Redis failure, reject new commands and report unavailable/stale state; do not
silently switch to process-local routing. Keep queues bounded and drop obsolete
telemetry before acknowledgments. Clean up consumer tasks on disconnect.

Completion: Channels communicator tests prove both directions, unauthorized
upgrades, snapshot ordering, credential revocation, lost ACKs, session replacement
and cleanup. A real Redis integration test proves cross-process routing.

## Phase 4 Implement the Pi dummy client

Add a locked `websockets` dependency to `apps/localization`. Implement dedicated
`transport.py` and `dummy.py` modules plus a CLI `demo` subcommand in
`__main__.py`. Reserve the scaffold's existing `simulate`, `replay` and `run`
commands for their documented localization responsibilities.

Configure the backend URL, device credential, frame, limits and update frequency
through explicit arguments/environment/configuration. Keep secrets out of CLI
arguments and logs. Add a root `localization:demo` command.

Run one receive task, a deterministic dummy-position loop and one bounded writer
with acknowledgment priority. Move toward the accepted target at a configured
constant speed (initially 0.5 m/s), using monotonic elapsed time. Continue sending
fresh stationary samples when the target is reached. Echo the active command ID.

Cache accepted/rejected command outcomes for the current process boot. A repeated
ID returns its prior outcome without restarting movement; a new connection gets
a new session while preserving boot-level reconciliation data. A process restart
gets a new boot ID and starts at the demo origin with no active command.

On connection loss, pause dummy movement locally. Reconnect with jittered
exponential backoff capped at 30 seconds, send current state and remain paused
until a new explicit target. Reconciliation reports whether the old target was
accepted; it does not resume motion. Stop rapid retries on credential rejection
and expose a clear operational error.

Completion: a laptop process receives a real backend target, acknowledges it and
streams deterministic positions. Tests verify speed, bounds, duplicate handling,
expiry, reconnect task cleanup and reboot behavior without hardware dependencies.

## Phase 5 Connect the control page

Add frontend API/session helpers, protocol types and a `useDeviceTelemetry` hook.
Provide login and authorized-device selection; auto-select the single device
when appropriate. Add development `/ws` proxy support in `vite.config.ts` and
explicit production API/WebSocket base URL configuration.

Replace `ControlPage.tsx`'s local position generator with telemetry state. Keep
selected target separate from accepted target and current position. Label the
page as simulated, show sample age and connection state, and disable submission
while offline/stale, unauthorized or awaiting a command outcome.

Rename the action to “Send target.” Remove the simulated flight/pause behavior;
make reset “Reset target” and change only the unsent selection. Reduced-motion
preferences can affect visual transitions but must never fabricate position.
Preserve a client request ID across an uncertain HTTP retry. On browser reconnect,
resubscribe and recover state without resubmitting the target.

Completion: selecting `(5, 5, 5)` feet sends `(1.524, 1.524, 1.524)` metres to the
Pi and displays returned metre samples correctly in feet. Disconnecting the Pi
stops position changes and shows stale state within the configured threshold.
Tests cover conversion, request retry identity and reconnect state recovery.

## Phase 6 Verify the complete path and prepare deployment

Run existing backend/frontend checks and the new localization suite. Include the
demo tests in the repository check workflow. Add an integration harness that
starts Daphne, Redis and the actual dummy client in separate processes; use a
browser smoke test for login, target submission and displayed updates.

Test backend restart, Pi restart, Caddy reload, Redis interruption, lost ACK,
duplicate target, rapid double submission, old/new device-session races and a
slow browser subscriber. Verify that errors become explicit states, queues stay
bounded and old commands never replay. Reconcile all dispatched-but-unconfirmed
commands conservatively after crashes.

Add a Pi systemd service example and deployment instructions covering a protected
credential file, restart behavior, URL/frame configuration and credential rotation.
Update the localization guide, backend runbook and environment examples. Verify
the actual Pi's Python 3.14 installation and locked dependencies before recording
hardware validation as complete.

Use the existing DigitalOcean endpoint and Caddy configuration for a TLS smoke
test after local checks. Verify production browser cookie/CSRF/origin behavior
from the real frontend domain. Treat arbitrary Vercel previews as a separate
configuration task. Record deployment commit, Pi runtime and observed latency;
the repository's current deployment status is not proof of a working live server.

Completion: the real Pi receives a user-selected target and returns dummy
coordinates through the deployed backend to the browser. A restart recovers
connectivity without replaying or resuming the old target. If Pi/cloud access is
unavailable, report local completion and list those external checks as pending.

## Suggested implementation order

Deliver six reviewable changes in the phase order above. The first useful backend
demonstration occurs after phase 4; the user-facing local milestone occurs after
phase 5; deployment and physical Pi verification complete phase 6. Authentication,
protocol validation and delivery uncertainty belong in the initial slice rather
than being deferred until after frontend integration.
