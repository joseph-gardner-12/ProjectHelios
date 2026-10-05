# Control protocol version 1

This protocol carries dummy targets and telemetry between the browser, Django,
and the localization application's `simulate` runtime. It does not control an
actual aircraft. The JSON schemas in this directory describe Pi messages,
browser snapshots, and HTTP target requests. The shared coordinate fixtures run
against all three implementations.

## Units and identity

Coordinates are dock-relative east/north/up metres: X east, Y north, Z up.
`dummy-enu-v1` identifies a synthetic frame, never a surveyed frame. Each axis is
between 0 and 3.048 metres. The browser converts feet once at the API boundary
using 0.3048 metres per foot and does not round wire coordinates.

Every admitted-session WebSocket message has `version: 1`, `type`, `device_id`, `connection_id`,
`frame_version`, and an ISO 8601 timestamp with timezone. UUIDs identify devices,
connections, commands, requests, and control leases. Browser snapshots may have
a null connection ID when the device is offline. Message size is limited to 8 KiB
on the Pi socket. Credentials are bearer headers, never URL parameters.

## Exchange

1. Pi authenticates at `/ws/v1/pi/` with `Authorization: Bearer <id>.<secret>`.
2. Backend atomically claims one backend-wide computer slot, then sends `setup`
   with a new connection ID and `telemetry_hz: 5`. If the slot is occupied, the
   authenticated socket receives `{"version":1,"type":"error",
   "code":"machine_already_connected","message":"..."}` and closes with 4409.
   This error precedes admission and has no device/connection envelope. It must
   terminate the CLI with exit status 3; it never replaces the incumbent.
   A transient setup failure instead uses `backend_unavailable` and close 1011,
   which may be retried. Invalid credentials are denied during the handshake.
3. Pi sends `ready`, then an idle `position`. Only advancing sequence numbers
   refresh position freshness. Idle telemetry continues at 5 Hz.
4. A session-authenticated browser watches `/ws/v1/devices/{device_id}/`.
   It receives complete `snapshot` messages containing position, health,
   command status, and its own queue state. It sends mutations only over HTTP.
5. The current controller posts to `/api/v1/devices/{device_id}/targets/` with
   `request_id`, `lease_id`, `frame_version`, and `target`. HTTP 202 means persisted,
   not accepted. An identical retry returns the same command with HTTP 200.
6. Backend delivers `target` with command ID, target coordinates, and expiry to
   that exact Pi connection. The Pi validates and sends `ack` with `accepted`
   and an optional rejection `reason` before beginning movement.
7. Pi sends `position` with `sequence`, `position`, `source: "dummy"`, `state`
   (`idle` or `moving`), and nullable active/completed command IDs. After reaching
   the target it sends `arrival`; subsequent idle positions repeat the completed
   command ID so a dropped arrival can be recovered.
8. Backend sends heartbeats every second. The Pi clears its target if the backend
   heartbeat is absent for five seconds, and reconnects idle.

Snapshots combine health, queue, and command events to avoid browser resubscribe
races. `revision` orders durable changes; `sequence` orders positions within a
connection. A fresh snapshot on reconnect supersedes earlier transient state.
The frontend retains the last position as stale until another position arrives.

## State and failure semantics

Commands transition `pending_ack` → `accepted` → `arrived`. Rejection is
`rejected`; a missing acknowledgment becomes `unconfirmed`; loss after acceptance
becomes `interrupted`. Terminal commands cannot be reaccepted or replayed.

Acknowledgment expiry is three seconds. Position freshness is two seconds;
connection presence expires after five seconds. Dummy speed is 0.5 m/s; arrival
requires 0.01 m tolerance for 0.5 seconds. Execution times out after 30 seconds.
These are demonstration defaults, not physical flight qualification limits.

Redis stores transient positions and presence. PostgreSQL stores requests, queue decisions, and the computer admission lease. Missing Redis state blocks control. Command delivery is an
at-most-once dispatch attempt after commit, with duplicate command handling on
the Pi; it is not an exactly-once delivery guarantee. A crash after persistence
can leave an unconfirmed command. Recovery invalidates that connection and never
redelivers the target. Users must explicitly submit a new request.

## Browser authentication and queue

`GET /api/v1/session/` returns session details and a masked CSRF token.
`POST /api/v1/login/` accepts an exact-domain Clemson email and the configured
shared demo password. It rotates the session and returns the fresh CSRF token.
The shared gate does not verify email ownership. POST requests send that token
in `X-CSRFToken`; all requests include cookies.

`GET /api/v1/devices/` lists permitted devices. Device status and queue status are
at `/api/v1/devices/{id}/` and `/queue/`. `/queue/join/` and `/queue/leave/` accept
POST. `/commands/{command_id}/` returns status; `/commands/?request_id={uuid}`
looks up the submitting session's request. Logout is `POST /api/v1/logout/`.

Control turns last five minutes. A command in progress finishes before handoff.
Browser disconnection gets 15 seconds' grace. Waiting users see telemetry but
cannot send. Released places do not automatically rejoin. An email cannot hold
multiple places or transfer its active place to a different session. Server
transactions and database constraints enforce these rules, including concurrent
requests from multiple processes.

## Computer enrollment and compatibility

`POST /api/v1/machines/register/` accepts JSON `name` and `password`, using the
shared registration password configured in Django admin. It does not use browser
session authentication or CSRF cookies. Success returns HTTP 201 with
`machine_id`, `name`, `credential`, `device_id`, `frame_version`, and
`websocket_path`. The CLI builds WSS on the same trusted backend origin and saves
the credential privately. Registration does not acquire the connection slot.

The original device UUID and bearer credentials remain valid. A separate Machine
record gives each old credential a legacy name without altering its secret.
Disabling a Machine prevents authentication and closes its connection within the
normal heartbeat check (one second). Connection close 4401 means rejected or
revoked credentials (terminal CLI status 4); close 4410 means an expired or
invalidated connection that may reconnect idle. The global slot expires after
five seconds without valid client traffic. Delayed old disconnects or messages
cannot release or modify a newer connection. The browser ControlLease remains
independent of this slot.
