# UWB localization implementation research

Research checked October 21, 2026. [ADR-0001](../adr/0001-uwb-sik-ardupilot-navigation.md)
remains the accepted hardware and frame baseline. This note records software
choices and qualification limits, not demonstrated flight performance.

## Interfaces confirmed in primary sources

[ArduPilot's external-navigation interface](https://ardupilot.org/dev/docs/mavlink-nongps-position-estimation.html)
permits external horizontal position with barometric vertical position and
compass yaw, and documents incoming observations at 4 Hz or higher. The initial
adapter uses VISION_POSITION_ESTIMATE without sending external velocity.

The [MAVLink definition](https://mavlink.io/en/messages/common.html#VISION_POSITION_ESTIMATE)
provides a timestamp, pose covariance, and reset counter. Pose attitude is copied
from time-aligned aircraft telemetry. It does not become an independent heading
measurement. Source selections must be verified in estimator logs; sending a
packet alone does not prove fusion.

[Makerfabs' v1.1.6 test](https://www.makerfabs.com/blog/post/mauwb-update-frequency-test)
states that anchors expose identical network data. Configured tag capacity and
slot duration determine per-tag rate, even if fewer tags are active. The test also
states that v1.1.6 removed RSSI from range output. A single collector is therefore
supported in principle, but four fresh ranges must be verified experimentally.

The [manual bundled with v1.1.6, sections 3.15 and following](https://github.com/Makerfabs/MaUWB_ESP32S3-with-STM32-AT-Command/blob/main/example/Firmware%20V1.1.6%20Manual%26%20Demo/Makerfabs%20UWB%20AT%20Module%20AT%20Command%20Manual%28v1.1.2%29.pdf)
defines decimal tag/sequence fields, hexadecimal validity mask, eight ranges in
centimetres, and eight anchor IDs. The adapter maps slot identities using ancid;
it does not assume slot number equals surveyed anchor ID. Malformed active slots
and duplicate anchor identities are rejected. Sequence rollback starts a new
estimator session because rollover width and restart semantics remain unverified.

The [vendor forwarding sketch](https://github.com/Makerfabs/MaUWB_ESP32S3-with-STM32-AT-Command/blob/main/example/Firmware%20V1.1.6%20Manual%26%20Demo/esp32s3_at_a0/esp32s3_at_a0.ino)
uses 250000 baud for USB and 115200 baud for the UWB UART. It forwards serial lines
and restores settings during startup. The host sends no provisioning commands.
A production forwarding sketch must preserve calibrated configuration.

## Estimation decisions

[SciPy least_squares](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html)
supports nonlinear residuals and a callable loss. The implementation applies
Huber loss only to whitened range residuals; the predicted-state prior remains
quadratic. State is horizontal position and velocity. Range prediction includes
measured tag height and the rotated body-FRD antenna offset.

This is a local constant-velocity model, not a claim that UWB measures velocity.
Velocity starts at zero with broad covariance. Prediction propagates motion and
uncertainty for at most 100 ms. Only a successful correction with four usable
ranges counts as a measurement. Prediction never feeds the aircraft adapter.

Height uncertainty is shared by every range residual, so the measurement noise
matrix includes correlated terms. The output includes horizontal/vertical cross
covariance and a shared-height uncertainty floor. Covariance remains a local
linearized approximation: changing attitude, NLOS bias and temporally correlated
range errors require empirical coverage tests. A smooth track does not establish
correct uncertainty or correct position.

## Qualification still required

No real captures, surveyed hardware results, SiK timing results, Pi ARM64 install
results, or SITL flight-controller logs were available for this change. The AT
parser is documentation-derived and provisional. Capture normal/startup/reset,
missing-anchor, duplicate, and malformed data before marking protocol_verified.

Receive-time-based UWB acquisition and the minimum-delay aircraft clock mapping
are estimates. Measure delay, jitter, acquisition skew, barometric repeatability,
and antenna survey errors before tuning timing_sigma, max_age, max_skew, noise,
and gates. These limits must include measurement uncertainty, not just host loop
speed. The 20 Hz correction and p95 under-100-ms latency targets are unverified.

Bench external output additionally requires explicit enablement, pinned controller
version matching AUTOPILOT_VERSION, the expected EKF parameters, an EKF origin,
and a disarmed aircraft. This milestone does not arm, take off, navigate, or land.
