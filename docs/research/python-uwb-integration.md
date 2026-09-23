# Python UWB integration with Django

Research date: September 23, 2026. Hardware assumption: Makerfabs MaUWB anchor/tag family, with PX4 controlling the drone. This recommendation does not assume arbitrary UWB boards share a Python API.

## Finding

Python is a practical host language for the UWB bridge and Django backend. There is no need for a special Django UWB package: use a device-specific parser over a supported serial or network transport, a separate 3D estimator, and a dedicated flight service. This is an architectural recommendation, not a tested implementation.

Makerfabs supplies an actual [Python positioning example](https://github.com/Makerfabs/MaUWB_ESP32S3-with-STM32-AT-Command/blob/main/example/Indoor%20positioning/position.py). It imports pySerial as `serial`, reads newline-delimited JSON at 115200 baud, and draws with pygame. Its position model and solver are **2D (x, y)**; it is useful protocol/demo reference, not a ready-made 3D flight localization SDK. It also auto-selects the first serial port and mixes display and acquisition in one loop, which should not be copied as the flight-service design.

The JSON comes from the paired [ESP32 get_range sketch](https://github.com/Makerfabs/MaUWB_ESP32S3-with-STM32-AT-Command/blob/main/example/Indoor%20positioning/get_range/get_range.ino), which parses raw `AT+RANGE` output. Do not assume a stock MaUWB Direct or a different firmware version emits the same JSON. That older sketch expects RSSI fields; Makerfabs says firmware v1.1.6 removes RSSI from range reports. Confirm and pin the hardware firmware/protocol before writing the adapter. [Firmware update explanation](https://www.makerfabs.com/blog/post/mauwb-update-frequency-test)

## Recommended transport topology

```text
Airborne UWB tag ↔ fixed UWB anchors
                         │
                one fixed anchor via USB
                         │
                  Python hardware service
                   ├─ 3D estimate → MAVLink link → PX4
                   └─ UI telemetry → Django/Channels → browser

Browser destination → Django validation → hardware service → PX4
```

Makerfabs' firmware v1.1.6 test states that every anchor outputs the same system data, allowing collection from any anchor. Consequently, a fixed USB-connected anchor can collect ranges for a flying tag without an airborne USB tether or an extra Wi-Fi hop for the UWB data. Verify that behavior on the exact firmware/configuration. The separate wireless MAVLink connection to PX4 is still required. [Manufacturer test](https://www.makerfabs.com/blog/post/mauwb-update-frequency-test)

If data is instead collected from the tag's UART, the flying tag needs an onboard host or wireless forwarding to reach the laptop. The MaUWB ESP32S3 board has a programmable controller, but the existence of Wi-Fi hardware alone does not implement a forwarding service. Its official setup uses Arduino sketches and AT commands. [Makerfabs wiki](https://wiki.makerfabs.com/MaUWB_ESP32S3%20UWB%20module.html)

## Library choices

| Layer | Choice | Responsibility |
|---|---|---|
| USB/UART | [pySerial](https://pyserial.readthedocs.io/en/latest/pyserial_api.html) | Open configured device port, read bounded records with timeouts, write AT configuration commands. It is transport, not a UWB solver. |
| 3D localization | [SciPy least_squares](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html), NumPy | Fit a position to calibrated ranges and surveyed anchor coordinates; least_squares supports bounds and robust loss functions. |
| PX4 messages | [pymavlink](https://mavlink.io/en/mavgen_python/) | Generate and send the exact MAVLink external-position messages selected for the PX4 integration. |
| Flight commands | [MAVSDK-Python](https://mavsdk.mavlink.io/main/en/python/) | Higher-level vehicle telemetry and offboard command interface, subject to selected API and PX4 version. |
| Browser updates | [Django Channels](https://channels.readthedocs.io/en/latest/topics/channel_layers.html) | WebSocket updates; use a cross-process channel layer such as its supported Redis backend when the hardware service and web workers are separate. In-memory layers do not communicate across processes. |

Recommendation: model residuals as predicted anchor distance minus calibrated measured distance, in meters. Start with at least four valid non-coplanar anchor ranges, reject stale/malformed records, and log solver residuals and age alongside position. Do not manufacture fresh timestamps by repeatedly forwarding an old estimate. Robust fitting reduces outlier impact but does not solve persistent UWB bias, poor anchor geometry, or heading estimation.

Run serial acquisition and the PX4 connection in a **single dedicated supervised process**, optionally launched through a custom Django management command. Keep it independent of HTTP request lifetimes, page connections, and Django development auto-reload. Django manages room/anchor configuration, destination validation, and logs; the dedicated process validates live flight state and owns the control loop. PX4 retains onboard stabilization and failsafe handling.

First implementation milestone: record raw fixed-anchor serial data, replay it through the parser and 3D solver, and compare estimates against measured positions before enabling any flight commands.
