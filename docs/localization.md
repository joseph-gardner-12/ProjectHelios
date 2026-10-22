# Localization setup and development

The localization application includes the existing backend-connected dummy demo
and a separate measurement-only UWB service. See the
[implementation research](research/uwb-localization-implementation.md) and
[accepted architecture](adr/0001-uwb-sik-ardupilot-navigation.md).

## Install and verify

```sh
pnpm setup:localization
pnpm test:localization
pnpm lint:localization
```

Python 3.14 is retained. NumPy, SciPy, pySerial, pymavlink and websockets are locked
in the application's uv project. macOS installation is tested by the software
checks; ARM64 Raspberry Pi installation still requires qualification.

## Run offline replay

This committed recording is synthetic, includes constant-velocity motion and a
measurement gap, and requires no device, cloud credential, or aircraft connection:

```sh
pnpm localization:replay --survey apps/localization/configs/survey.example.toml apps/localization/tests/fixtures/synthetic-motion.jsonl
```

Replay emits JSON estimates on stdout. The manifest includes the entire survey
configuration, firmware metadata and original timebase. Replay rejects mismatched
configuration, oversized entries and backwards time. It uses recorded timing;
wall-clock replay speed does not alter solver results. Replay never opens serial
ports or publishes aircraft observations.

## Survey and acquisition

Copy `apps/localization/configs/survey.example.toml` to a site-specific file. Its
example coordinates are synthetic; replace them with measured antenna positions.
Use `protocol = "mauwb-at-v1.1.6"` for the documented raw AT format. IDs use `A0`,
`A1`, etc., matching each report's ancid field. Calibrated range is reported metres
minus the configured anchor bias. Do not apply the same calibration twice.

Configure both `uwb_port` and `mavlink_port`, baud rates, firmware identities,
altitude datum, antenna offset, surveyed frame version and uncertainty limits.
`altitude_offset` maps aircraft LOCAL_POSITION_NED to surveyed aircraft height:
`survey_z = -local_ned_z + altitude_offset`. `dock_in_ned` is the surveyed origin's
position in the aircraft EKF frame. Both frames must have aligned east/north axes;
rotate the survey into ENU before commissioning. Body antenna offset uses FRD.

For acquisition before qualifying the protocol (mavlink_port may be empty in
capture-only mode):

```sh
pnpm localization:run --survey /absolute/path/survey.toml --record /absolute/path/capture.jsonl --capture-only
```

For measurement processing and recording:

```sh
pnpm localization:run --survey /absolute/path/survey.toml --record /absolute/path/measurements.jsonl
```

The service never sends collector provisioning commands. Files are created
exclusively and stop at `recording_max_bytes`; choose a new path for each session.
Records include raw UWB bytes, relevant MAVLink telemetry, normalized aircraft
samples, predictions, corrections, and transmitted external observations.

The AT adapter is provisional until real captures verify firmware behavior. Bad
records, startup text, missing anchors, stale altitude and invalid geometry cannot
produce a fresh measured position. Four valid ranges are mandatory. The synthetic
JSON adapter requires an explicit format label and always publishes as synthetic.

## Prediction and correction

The solver fits slant ranges with nonlinear weighted least squares and uses a
constant-velocity state prior. Huber loss applies to range residuals; the prior is
quadratic. Shared altitude error contributes correlated range noise. Position,
velocity, uncertainty, residual, speed and geometry gates determine validity.

Predictions retain the last measurement time, grow covariance and stop after
100 ms or earlier on stale altitude or excess uncertainty. Controller reset,
frame mismatch and long gaps invalidate prior motion. Reinitialization obtains a
new range-only position with zero assumed velocity and broad velocity covariance.
Prediction is available to the dashboard and logs only.

The default uncertainty, speed, skew and residual limits are bench defaults.
Qualify them with ground truth, turns, acceleration, persistent bias and occlusion;
robust loss cannot remove coherent NLOS errors. In particular, a smooth track must
not be interpreted as proof of accuracy.

## Read-only dashboard

Provision a distinct backend Device with `frame_version` matching the survey
(e.g. `lab-enu-v1`), grant DevicePermission to viewers, and provision its normal
credential using `provision_device --device-id ... --credential-file ...`.
Enrollment retains the existing backend-wide single-computer connection slot.
Configure the localization enrollment JSON or existing HELIOS_* overrides with
that device ID, credential and WSS URL. Do not change the dummy device's frame
while its demo is in use.

Select the surveyed device from the dashboard Device selector when multiple
devices are permitted.

Add `--cloud` to `localization:run` to publish read-only observations. Local
capture/estimation continues through cloud outages and rejected credentials.
Surveyed sessions cannot acquire control turns or accept targets. Dummy mode
retains its existing protocol and control demonstration.

The dashboard shows signed ENU metres, axis uncertainty, last measurement time,
prediction age, source, validity and rejection reason. Publishing at 5 Hz does not
refresh the source measurement time. With a 100-ms validity budget, a dashboard
sample may expire before the next update; it is deliberately shown as stale.

## Optional external-navigation bench output

`external_nav = false` is the default. Set true only in a qualified bench survey
with protocol_verified, UWB firmware identity, and controller_firmware set to the
actual `major.minor.patch` from AUTOPILOT_VERSION. Synthetic input cannot enable
this output. A hardware configuration flag alone is not qualification evidence.

The adapter requires a disarmed aircraft, recent heartbeat, EKF origin and the
ADR's source parameters. Sensor offsets VISO_POS_X/Y/Z must be zero because the
Pi already compensates the antenna offset. Output is MAVLink 2
VISION_POSITION_ESTIMATE with transformed covariance and attitude. Predicted,
invalid, repeated or stale estimates are never transmitted. This runtime has no
arming, takeoff, mode-selection or waypoint commands. It requests telemetry and
parameter values without configuring the estimator or origin.

Validate on pinned SITL firmware, then with propellers removed: frame axes, origin,
reset handling, altitude datum, correct X/Y fusion, barometric Z, compass yaw and
no external velocity fusion. Archive full parameter files and estimator logs.

Hardware gates remain: complete four-range epochs, error distributions across the
surveyed room and heights, barometric drift, heading performance, Pi installation,
SiK latency and worst gaps. Neither 20 corrections/second nor p95 latency below
100 ms has been established by software tests. Autonomous flight needs separate
failure-response and flight-envelope qualification.

### Hardware-free live dashboard demo

Run `pnpm dev:uwb` from the repository root (stop `pnpm dev` first if running).
This starts the local PostgreSQL, Redis, backend, worker, frontend, and synthetic
UWB sensor runtime. Open http://127.0.0.1:5173/control and sign in with any
`@clemson.edu` address and local demo password `SeniorDesign`.

The demo sends noisy four-anchor slant ranges through the live parser and nonlinear
estimator as you use the original X/Y/Z waypoint controls to move the simulated drone.
The original tracking view and command lifecycle remain at the top; synthetic
UWB localization diagnostics appear underneath. The two displays distinguish
simulated ground truth from estimated sensor position. Every
12 seconds it omits ranges for 80 ms at second 4 and 600 ms at second 8. Predictions
retain their measurement time and expire after 100 ms; fresh ranges reinitialize
the estimator after the long outage. Source labels remain **Synthetic**. The
5 Hz dashboard can show stale intervals between updates because the freshness
limit is only 100 ms. This is a demonstration, not hardware qualification.

Ctrl+C in the launcher stops all six services. Logs are in `.helios/dev/logs/`.
The existing `pnpm dev` dummy command demo is unchanged. The UWB waypoint demo has its own
local dummy device and credential, and never opens aircraft or UWB serial ports.


### Connect the real collector to the dashboard

James's `record-ranges` and the estimator now share `parse_range_report`.
`run` uses a bounded serial reader and passes each complete AT record through
that parser, mapping `ancid` to surveyed IDs such as `A4`. It does not interpret
mask bits or combine separate reports. At least four surveyed anchors in one
report are required for a corrected fix; James's single-A4 samples cannot
localize a tag on their own.

Copy `apps/localization/configs/survey.example.toml` to a private survey file.
Replace **all example anchor coordinates** with measured coordinates in metres,
use the actual anchor IDs (`A0`, `A2`, etc.), and set:

```toml
protocol = "mauwb-at-v1.1.6"
uwb_port = "COM4" # Windows example; use the actual /dev/cu.* or /dev/tty* port on Mac/Pi
uwb_baud = 115200 # James's collector setting; verify your device
tag_id = 1 # James's observed tag; verify your tag
external_nav = false
```

For aircraft tracking, configure `mavlink_port`, its baud rate, the dock altitude
datum, and antenna offset as described above. For a tag held at a known bench
height instead, leave `mavlink_port = ""`, keep `tag_offset_frd = [0, 0, 0]`, and
set `fixed_height` to that surveyed height in metres. Set `altitude_sigma` to
the height uncertainty. This explicitly constrains Z; it does **not** measure
vertical movement. Fixed-height mode refuses aircraft transmission and offsets
that would need measured attitude. Recordings identify its altitude samples as
`fixed-height-bench` and preserve the constraint in their configuration.

With PostgreSQL/Redis installed, start the complete local hardware dashboard:

```sh
pnpm dev --survey /absolute/path/real-survey.toml
```

Stop an existing demo stack first. This command provisions a measurement-only
local device with the survey's frame, starts `run --cloud`, and saves raw records,
altitude inputs, and estimates to `.helios/dev/uwb-*.jsonl`. Close the Makerfabs
configuration tool and `record-ranges` so only one process owns the collector.
Sign in at http://127.0.0.1:5173/control with the local demo credentials and
select **Real UWB collector** if more than one device appears. The original graph
shows corrected positions (feet); the panel beneath shows metres, uncertainty,
and measured/predicted/invalid status. Waypoint entry remains visible, but real
measurement sessions do not send aircraft commands. The dummy demo remains
available separately through `pnpm dev:uwb`.

For an existing backend enrollment matching the survey frame, use:

```sh
pnpm localization:run --survey /absolute/path/real-survey.toml --record /absolute/path/new-capture.jsonl --cloud
```

Do not use a dummy-frame credential for real measurements. No synthetic fallback
is used when the collector, required altitude, or four-anchor epoch is missing.

### Native Windows setup and source toggle

No Docker or WSL is required. Install Node.js 24+, pnpm 11, uv, native PostgreSQL
16+ and a native Redis-compatible server. Memurai is supported on Windows; the
launcher discovers `memurai.exe` on PATH or in `C:\Program Files\Memurai` and
starts a separate local instance on port 16379. PostgreSQL is discovered on PATH
or under `C:\Program Files\PostgreSQL\<version>\bin`. Run from a normal
PowerShell terminal, not an administrator terminal. Keep the checkout in your
user directory so its local credentials inherit your account's filesystem ACLs.

From the repository root:

```powershell
pnpm install --frozen-lockfile
uv sync --locked --project apps/backend
uv sync --locked --project apps/localization
pnpm dev --survey apps/localization/configs/table-bench.toml
```

The launcher creates its own PostgreSQL data directory under `.helios/dev` and
uses ports 15432 (PostgreSQL), 16379 (Redis/Memurai), 8000 (backend), and 5173
(frontend). Existing system database services on 5432/6379 are not stopped or
modified. Python runs natively on Windows and opens COM5 directly at 115200 baud;
close other serial readers first. Ctrl+C stops the launcher's own processes and
retains recordings and database contents. Separate `solo:*` panes remain POSIX-only.

Sign in again after upgrading an existing local session to access both devices.
The **UWB source** buttons switch the running reader between:

- **Simulated UWB:** synthetic ranges and nonlinear correction, with the original
  waypoint controls. Use **Rejoin queue** to obtain a turn before sending a target.
- **Real UWB · COM5:** the table survey, real serial ranges, and fixed Z = 0.7466 m.
  Aircraft commands remain disabled. An absent/busy collector stays offline;
  simulation is never substituted automatically.

Switching takes about six seconds while the prior connection lease expires.
Switches are blocked during an active simulated command. The dashboard stays
available after a serial startup failure; click Real UWB again after reconnecting
the collector to retry, or choose simulation. This local, authenticated control
is only enabled by `--survey`; production deployment does not expose runtime
switching. The configured survey determines the real device port.

References: [Memurai native Windows installation](https://docs.memurai.com/en/installation),
[Memurai standalone command-line configuration](https://docs.memurai.com/en/config-file),
and [Python process-group support on Windows](https://docs.python.org/3/library/subprocess.html).
Windows CI checks launcher paths, locks, process cleanup, backend behavior, and
localization tests; an attached COM5 collector still requires a hardware test.
