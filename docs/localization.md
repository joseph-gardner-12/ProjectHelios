# Localization setup and development

The localization application lives in `apps/localization`. It is a standalone
Python package intended to run on the dock Raspberry Pi, independently of Django.
The accepted [ADR-0001](adr/0001-uwb-sik-ardupilot-navigation.md) defines the hardware,
coordinate contract, aircraft integration, and qualification requirements.

## Current status

This is a structure-only scaffold. All Python modules are empty. Package metadata,
development tooling, a dependency lockfile, and root pnpm commands are provided.
There is no solver, simulator, serial parser, MAVLink integration, flight control,
or test implementation yet.

The console entry point reserves `helios_localization.__main__:main`. Until that
function and its subcommands are implemented, simulation, replay, and run commands
exit with an import error. This is expected and does not indicate working
localization. Pytest exits with code 5 while no tests exist. Lint can pass on empty
modules; that establishes no runtime behavior.

## Responsibilities and data flow

The intended processing path is:

```text
MaUWB collector ── ranges ──────────────┐
                                      ↓
ArduPilot ── altitude/attitude ──→ validate and time-align
                                      ↓
                                 solve X/Y
                                      ↓
                         estimate uncertainty and health
                                      ↓
                       transform coordinates → ArduPilot
                                      ↓
                             telemetry → Django
```

The Pi owns hardware acquisition and the positioning loop. Django owns users,
remote requests, and history; the frontend displays status and accepts destinations.
Internet availability must not sustain the positioning loop. Future flight
supervision should be a separate responsibility from the mathematical solver,
with a single owner of the MAVLink connection.

Use four valid anchor ranges and time-aligned measured aircraft altitude to solve
horizontal position. UWB measures slant distance, so altitude and its uncertainty
affect X/Y. Do not substitute a requested waypoint height for measured altitude.
The aircraft estimator retains barometric Z and compass yaw under the accepted
baseline. Reject stale or incomplete inputs instead of refreshing timestamps on
old estimates.

The application frame is east/north/up in metres relative to the dock survey.
The aircraft adapter converts to north/east/down and applies the dock-to-EKF-origin
offset. Survey versions, altitude datum, antenna offset, and measurement timing
must remain explicit. See the ADR for the full contract.

## Directory layout

```text
apps/localization/
  .python-version
  pyproject.toml
  uv.lock
  README.md
  src/helios_localization/
    __init__.py
    __main__.py
    config.py
    models.py
    ranging.py
    solver.py
    frames.py
    mavlink.py
    runtime.py
    replay.py
    simulation.py
  configs/
    simulation.toml
  tests/
    fixtures/
      .gitkeep
```

| Module or directory | Intended responsibility |
| --- | --- |
| `__main__.py` | CLI entry point and `simulate`, `replay`, and `run` subcommands |
| `config.py` | Validate survey, calibration, port, frame, and timing configuration |
| `models.py` | Measurement, estimate, uncertainty, and health records |
| `ranging.py` | Serial acquisition and decoding of the verified collector protocol |
| `solver.py` | Pure X/Y estimation from ranges and measured height; no hardware I/O |
| `frames.py` | Coordinate transforms and reference offsets |
| `mavlink.py` | Aircraft telemetry reception and external-position publication |
| `runtime.py` | Coordinate acquisition, processing, output, and health |
| `replay.py` | Feed recorded measurements through the processing pipeline |
| `simulation.py` | Generate synthetic measurements from known trajectories |
| `configs/` | Versioned configuration; the simulation file is currently comments only |
| `tests/fixtures/` | Future deterministic measurement recordings and expected results |

## Setup and commands

Install the repository's Node/pnpm prerequisites and uv as described in the root
[README](../README.md). Run these commands from the repository root:

```sh
pnpm setup:localization
pnpm lint:localization
```

Setup creates `apps/localization/.venv`, installs the package in editable mode,
and installs pytest and Ruff using the committed lockfile. Python is pinned to
3.14 to match the existing backend. Verify Python and dependency compatibility
on the target Pi before hardware integration; this scaffold does not qualify it.

| Root command | Purpose | Available now? |
| --- | --- | --- |
| `pnpm setup:localization` | Install the isolated Python environment and development tools | Yes |
| `pnpm localization:simulate` | Invoke the future synthetic measurement runner | Command wired; implementation pending |
| `pnpm localization:replay` | Invoke the future recorded measurement runner | Command wired; implementation pending |
| `pnpm localization:run` | Invoke the future live hardware service | Command wired; implementation pending |
| `pnpm test:localization` | Run the localization pytest suite | Runner available; no tests yet, exit code 5 |
| `pnpm lint:localization` | Check localization files with Ruff | Yes |

The subcommand names are reserved; their arguments and configuration schema are
not yet defined. The simulation configuration is not automatically loaded by any
implemented code. Do not expect the run command to connect to hardware yet.

Existing `pnpm setup`, `pnpm dev`, and `pnpm check` retain their frontend/backend
scope. Localization is opt-in while it is a scaffold, so ordinary web development
does not require hardware or fail because the localization test suite is empty.

## Dependencies and packaging

This app has its own `pyproject.toml`, `uv.lock`, and virtual environment. Root pnpm
scripts orchestrate uv; Python dependencies belong in the localization project,
not in `package.json`. Hatchling packages the `src/helios_localization` directory.

Runtime dependencies are deliberately empty until implementation begins. The ADR
selects pySerial for acquisition, NumPy/SciPy for fitting, and pymavlink for aircraft
communication. Add them when implementing their corresponding modules:

```sh
uv add --project apps/localization pyserial numpy scipy pymavlink
```

Commit changes to both `pyproject.toml` and `uv.lock`. After manually editing
dependency metadata, refresh the lock with `uv lock --project apps/localization`.
Root commands use `--locked` to catch metadata/lockfile mismatches.

## Implementation sequence

1. Define measurement records, configuration schema, frame transforms, and CLI
   arguments. Keep measurement time distinct from receive time.
2. Implement a pure solver and synthetic inputs with known ground truth. Test
   multiple heights, range errors, missing anchors, stale altitude, and frame signs.
3. Define a recording format and replay the same inputs through the same pipeline.
   Preserve raw records and timing so faults can be reproduced.
4. Capture real MaUWB output and implement its verified protocol adapter. Record
   firmware versions and baud rates rather than assuming a stock JSON format.
5. Connect to ArduCopter SITL, then bench hardware. Follow the ADR's position-only
   `VISION_POSITION_ESTIMATE` integration and validate estimator source selection,
   uncertainty, latency, resets, and loss handling.
6. Add Pi service supervision with systemd and outbound telemetry to Django.
   Keep display traffic from blocking the localization path. Add flight supervision
   and command handling only with the ADR's readiness and failure behavior.

The first milestone is repeatable synthetic/replayed positioning with meaningful
tests. Hardware execution and flight qualification are later milestones; neither
the scaffold nor a successful installation demonstrates flight readiness.
