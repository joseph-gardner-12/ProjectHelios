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
