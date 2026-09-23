# Dock hardware and deployment verification

Verified against primary sources on 2026-09-23. These are planning constraints, not a completed hardware compatibility test.

## Raspberry Pi dock controller

- Pi 4's recommended supply is 5 V / 3 A (official 15 W adapter). Pi 5's recommendation is 5 V / 5 A (official 27 W USB-C adapter). A Pi 5 on a 3 A supply restricts USB peripherals to 600 mA; a suitable 5 A supply permits 1.6 A. Budget the actual peripherals, cable losses, fan, and storage together. [Raspberry Pi getting started](https://www.raspberrypi.com/documentation/computers/getting-started.html), [hardware documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html).
- Official guidance recommends active cooling for best performance; Pi 5 supports the Active Cooler or official fan case. A powered USB hub is an available remedy for peripheral power shortfalls. [Raspberry Pi hardware documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html).
- Planning recommendation: Pi 4 is a reasonable candidate for serial/network bridging and modest numerical processing; choose Pi 5 for added compute headroom. Neither claim substitutes for a measured workload. Include a suitable supply, cooling, enclosure, storage, Ethernet, and USB/serial adapters in the dock bill of materials. Keep motors/charging loads on appropriately designed power circuits; do not treat the Pi supply rating as a dock-wide power budget.

## Kakute H7 Mini and PX4

- Current PX4 documentation requires H7 Mini hardware v1.3 or later and lists PX4 main / v1.14 or newer support. The build target is `holybro_kakuteh7mini_default`. Boards shipped with Betaflight require the PX4 bootloader flashing procedure first. [PX4 board documentation](https://docs.px4.io/main/en/flight_controller/kakuteh7mini).
- That same current page still says its 128 MB flash logging is unsupported under PX4. Do not count it as working onboard flight-log storage. It also documents no internal magnetometer, and a 5 V / 2 A BEC. [PX4 board documentation](https://docs.px4.io/main/en/flight_controller/kakuteh7mini).
- Procurement gate: confirm exact revision, firmware image, available ports, supported sensors and required estimator modules on one physical board. Prove a usable flight-log strategy before fleet purchase; otherwise select a supported controller with verified onboard logging. The docs' support statement does not establish every sensor, driver, or peripheral combination.

## MaUWB anchor topology and rates

- Makerfabs' v1.1.6 test states that all anchors report the same system data: one anchor can be the wired ingestion point. It reports up to 100 Hz aggregate anchor output at 6.8 M mode / 10 ms slots; this is not 100 Hz per tag. Per-tag update period is configured tag capacity multiplied by slot duration, even when some configured tags are absent. Their five-tag / 10 ms example is 20 Hz per tag. At 850 K mode, minimum slot duration is 15 ms. [Makerfabs update-frequency test](https://www.makerfabs.com/blog/post/mauwb-update-frequency-test).
- Firmware v1.1.6 changes `AT+Range` output by removing RSSI. A parser must match the deployed firmware. [Makerfabs update-frequency test](https://www.makerfabs.com/blog/post/mauwb-update-frequency-test).
- The vendor repository provides ESP32-S3 examples, AT configuration and STM32 firmware-flashing instructions. Firmware upgrades require ST-Link access and separate USB-C power in its documented setup. [Makerfabs source repository](https://github.com/Makerfabs/MaUWB_ESP32S3-with-STM32-AT-Command).
- Planning implication: provision one anchor-to-Pi serial path initially, plus power at all anchors. Validate reporting on the exact purchased SKU/firmware; do not generalize to every Makerfabs UWB product. These are range observations, not proof of a complete 3D pose estimator. Measure real latency, missed updates, geometry sensitivity and interference with the intended tag count before flight integration.

## MAVSDK Python on ARM64

- The current Python guide documents native `mavsdk` bindings with Linux aarch64 wheels, explicitly including 64-bit Raspberry Pi OS. There are no native wheels for 32-bit ARM Linux. The guide distinguishes the new API from `mavsdk` 3.x and earlier, which used gRPC. [MAVSDK Python quickstart](https://mavsdk.mavlink.io/main/en/python/quickstart.html).
- Legacy MAVSDK-Python documents a separate `mavsdk_server`, which may need manual startup on Raspberry Pi, with matched server/package versions. This remains relevant to existing legacy code, but is not an unconditional requirement of the current native package. [Legacy wrapper README](https://github.com/mavlink/MAVSDK-Python/blob/main/README.md), [migration guide](https://mavsdk.mavlink.io/main/en/python/migration.html).
- Deployment gate: choose the API generation deliberately, pin package versions, use a 64-bit OS, and verify installation, discovery, telemetry, reconnects and commands on the actual Pi. Old examples and new package APIs must not be mixed. No ARM64 installation or hardware execution was performed in this research.
