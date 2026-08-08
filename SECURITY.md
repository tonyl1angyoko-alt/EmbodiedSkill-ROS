# Security and Robot-Safety Policy

## Reporting

For credential exposure or a vulnerability, use the repository's private GitHub Security Advisory feature. Do not post secrets, robot network information, or exploit details in a public issue.

## Real-robot warning

Before any hardware use, independently verify joint and Cartesian limits, velocity and acceleration, payload/tool configuration, transport-safe arm poses, lift/arm compatibility, emergency-stop behavior, AGV localization and obstacle handling, human supervision, and a physically cleared test area.

Dangerous fault injection belongs in `MockRobotBackend` or an isolated simulation. Do not reproduce command-loss, state-drift, timeout, or actuator-conflict scenarios on hardware without an approved test procedure.

Version 0.3.0 is **not suitable for unsupervised real-robot deployment**. The
process-separated fake-robot path and exact-schema JAKA/Kargo adapter stub are
`ROS2-RUNTIME-VERIFIED`, while the external interfaces/toolbox are
`ROS2-BUILD-VERIFIED`. Vendor-backed JAKA node runtime, hardware execution, physics
simulation, whole-robot stopping, collision safety, sensor trust, and real-time
guarantees remain `UNVERIFIED`.
