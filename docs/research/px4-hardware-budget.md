# PX4 indoor hardware budget feasibility

Research date: September 23, 2026. Scope: one drone, 10 × 10 × 10 ft (3.048 m per side), website-selected destinations, return to a dock, automatic landing and manual charging. The existing laptop is excluded from the $800 hardware budget. Prices below are USD listings observed during research, not delivered quotes or purchases.

## Finding

An $800 ceiling is a stretch for a carefully sourced prototype with automatic return and landing, but manual charging. Manual charging is the latest confirmed scope; automatic charging is excluded. A four-anchor prototype has a planning range of about $770–$1,100 before automatic charging hardware; six anchors add about $86 using the lower-cost modules below. These are engineering allowances with unresolved compatibility and shipping costs, not a validated shopping cart. Borrowed hardware or increased funding would materially reduce risk.

Use a small guarded airframe, an explicitly supported PX4 controller, multi-anchor UWB firmware, an existing laptop for localization/control, and a local wireless MAVLink connection. Do not buy a generic Betaflight board assuming PX4 support follows from its processor.

## Verified candidate listings

| Candidate | Listed price | Availability observed | Relevance and limitations |
|---|---:|---|---|
| [Holybro Kakute H7 Mini v1.5](https://holybro.com/products/kakute-h7-mini) | $58.99 | Variant data marked available | 20 × 20 mm mounting, 5.5 g, I2C for external magnetometer; ESC is separate. The cheaper $48.99 v1.3 was unavailable. |
| [Makerfabs MaUWB Direct](https://www.makerfabs.com/mauwb-direct.html) | $42.80 each | In stock | USB configuration/output and included battery; suitable candidate for fixed anchors. Listed weight is 50 g, so assess carefully before using as airborne tag. |
| [Makerfabs MaUWB ESP32S3](https://www.makerfabs.com/mauwb-esp32s3-uwb-module.html) | $54.80 each | In stock | Candidate airborne tag/development board with programmable ESP32 and multi-anchor ranging firmware. Verify payload dimensions, mass, power, antenna mounting, and firmware compatibility. |
| [Makerfabs ESP32 UWB DW3000](https://www.makerfabs.com/esp32-uwb-dw3000.html) | $43.80 each | In stock | Manufacturer explicitly states demo libraries do not implement time multiplexing for multi-anchor/tag use. Lower board cost transfers work into firmware; not the recommended baseline. |
| [RadioMaster Pocket Crush ELRS](https://radiomasterrc.com/products/pocket-crush-radio-controller) | $64.99 | Example FCC variant marked available | Price is transmitter only; receiver and radio batteries need separate allowance. |

PX4 documents the [Kakute H7 Mini](https://docs.px4.io/main/en/flight_controller/kakuteh7mini) as manufacturer-supported and says v1.3 and later can run PX4. Its documentation also warns that onboard flash logging is not supported there. Confirm the exact purchased revision's IMU/barometer and selected PX4 release, and plan telemetry logging to the laptop. The Holybro product listing and PX4 page describe different sensor revisions; do not treat a family-level compatibility statement as a completed bench test.

The UWB candidate totals are arithmetic from the listings:

- Four MaUWB Direct anchors + one ESP32S3 tag: **$226.00**.
- Six MaUWB Direct anchors + one ESP32S3 tag: **$311.60**.
- Five identical ESP32S3 boards: **$274.00**; seven: **$383.60**.

These UWB products report ranging data; the project still needs anchor surveying, calibration, a 3D position solver, outlier rejection, timestamp handling, and a PX4 bridge. An attractive module price does not establish hover or docking accuracy.

## Land-only planning baseline, not a purchase list

| Item | Allowance |
|---|---:|
| Four-anchor/one-tag mixed MaUWB set above | $226 |
| Kakute H7 Mini v1.5 flight controller | $59 |
| Compatible guarded frame, four motors, ESC, props | $110–$190, estimate |
| External PX4-supported heading sensor and mounting | $15–$35, estimate |
| Flight batteries and appropriate balance charger/power supply | $55–$100, estimate |
| RC transmitter, compatible receiver, radio batteries | $85–$105, estimate |
| Wireless MAVLink bridge and wiring | $15–$40, estimate |
| Downward distance sensor | $25–$50, estimate |
| Anchor power/cables/mounts and simple landing pad | $30–$60, estimate |
| Shipping, taxes, consumables, spares, contingency | $50–$130, estimate |
| **Total** | **$770–$1,095** |

All rows labelled estimate require exact part selection and electrical/mechanical compatibility checks. A compatible guarded frame/propulsion combination has not been verified within its allowance. The heading sensor requires validation in the actual indoor magnetic environment. The range sensor requires supported PX4 driver, field-of-view, usable range, and minimum-height checks. Shared laboratory tools, existing network, and test enclosure are assumed available; a new enclosure, tools, labor, onboard Linux computer, and automatic charging dock are excluded. Website/backend can run locally on the existing laptop, so paid hosting is unnecessary for the prototype.

## Integration gates before a full purchase

Makerfabs reports firmware v1.1.6 supporting up to 100 Hz, depending on configured tag capacity and timeslot. Their example explains that allocating five tag slots at 10 ms produces 20 Hz per tag even if fewer tags are present. Validate a **complete, fresh multi-anchor range set**, transport latency, jitter and dropouts; a nominal packet rate is not a demonstrated position update rate. [Manufacturer update-frequency test](https://www.makerfabs.com/blog/post/mauwb-update-frequency-test)

Recommendation: start with four non-coplanar anchors as a cost-constrained bench prototype and reserve mounting/power provision for six. Survey actual antenna positions and test the whole volume, especially near floor/dock and walls. Do not promise charging-contact alignment from nominal UWB ranging accuracy. A single tag does not provide full drone attitude or heading.

## Dock scope and future automatic charging

The budget table funds a broad landing pad and manually operated charger, matching the latest request. If automatic charging is added in a future phase, it additionally requires an alignment/capture design, onboard and dock contacts compatible with the selected battery topology, charge controller and power supply, reliable landed/contact detection, motor/charging interlocks, and validation of charge termination. A normal manually connected balance charger in the baseline does not constitute an automatic dock.

Recommendation for the current scope: use UWB to return above a broad pad and descend only after measured position/control error fits within its usable area. Size the pad from flight-test results, vehicle footprint, and margins. If future charging contacts are introduced, additional relative alignment sensing or mechanical capture would need evaluation; those additions remain unpriced.

PX4's [precision-landing documentation](https://docs.px4.io/v1.17/en/advanced_features/precland) specifies a valid global position requirement. The [external-position guide](https://docs.px4.io/main/en/ros/external_position_estimation) explains establishing a global origin for local-position use. For this small room, explicitly design and simulate a room-coordinate return/approach/descent sequence instead of assuming outdoor return-to-launch defaults are suitable. Built-in precision landing does not implement charging control.
