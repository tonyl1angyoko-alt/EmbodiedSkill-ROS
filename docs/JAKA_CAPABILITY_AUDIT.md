# JAKA Capability-Contract Audit

Audit date: 2026-08-08

Status: `STATICALLY-INSPECTED`; JAKA ROS runtime and hardware remain `UNVERIFIED`.

## Available evidence

A sibling delivery workspace contains the reference Python skill adapters, JAKA
ROS service definitions, C++ SDK bridge sources, and an x86-64
`libjakaAPI_2_3_1_DUAL.so`. `file` and `ldd` show that the library matches this host
architecture and its ordinary system-library dependencies resolve. However, only
`jaka_kargo_description` is built/installed in that workspace. `jaka_toolbox`,
`jaka_toolbox_interfaces`, `jagv_interfaces`, and `moveit_msgs` are not discoverable
from its install prefix, and no JAKA services or hardware session were started.

Finding source and a loadable ELF file is not runtime or hardware validation.

## Mapping table

| Abstract contract | JAKA mapping | Known semantics and limits | Observation signal | Status |
|---|---|---|---|---|
| `retract_arm(arm)` | `arm.go_preset(transport_pose_name)` | Reference `go_preset` sends 14 joint positions with `motion_unit_id=-1`; both arms move. A named preset is not calibrated proof of transport safety. | `_query_arm(0/1)` can show readiness/poses, but safe-envelope classification requires a supplied validated state provider. | `STATICALLY-INSPECTED`; single-arm contract correctly rejected by capability preflight unless bilateral effects are explicitly allowed |
| `extend_arm(arm)` | no adapter mapping | Unsupported rather than approximated with a bilateral Cartesian move. | none | `UNVERIFIED`; rejected preflight |
| `move_agv(distance_m, speed_mps)` | sign becomes forward/backward; `agv.drive_distance(direction, abs(distance), speed)` | Reference publishes Twist at 10 Hz for `distance/speed` after steering-wheel readiness. It is open-loop and capped at 0.5 m/s. Steering encoders are not displacement odometry. | Only an explicitly supplied `agv_position_provider` makes `agv_position_m` observable; otherwise effect preflight rejects. | `STATICALLY-INSPECTED`; ROS/JAKA runtime and physical displacement `UNVERIFIED` |
| `set_lift(height_mm)` | `lift.lift_to(height_mm)` | Absolute external axis 0; 0–780 mm; synchronous ROS service; reference clamps targets and derives velocity from distance/duration. No cancellation path is exposed. | `lift.backend.get_j1_mm()` / `/query_status_ext` feedback when available. | `STATICALLY-INSPECTED`; runtime/hardware `UNVERIFIED` |
| `set_head(yaw_deg?, pitch_deg?)` | sequential `yaw_to`, then `pitch_to` | yaw −90°..90°; pitch −45°..20° with sign inversion for the physical pitch joint. If both are requested, one axis can move before the second fails; post-state observation is essential. | backend yaw/pitch status queries. | `STATICALLY-INSPECTED`; runtime/hardware `UNVERIFIED` |
| `safe_stop` | `agv.stop()` only | Sends zero Twist to the AGV. It does not stop/disable arms, lift, or head and does not confirm a whole-robot stopped state. | no comprehensive stopped-state provider. | whole-robot semantics `UNVERIFIED`; adapter no longer advertises `supports_safe_stop` or command acceptance |

## Semantic-scope finding

The clearest mismatch is:

```text
abstract: retract left arm only
JAKA preset call: move both left and right arm joint vectors
```

`JakaRobotBackend.capabilities()` already encodes both arm-safety fields as
unavoidable effects for `retract_arm`. The core capability check rejects the
single-arm abstract contract before dispatch. R12 reproduces this class of
rejection through the ROS fake backend; it does not validate the JAKA service.

## Safe-stop correction

Before this audit, an AGV object caused `supports_safe_stop=True`, even though the
only operation was an AGV zero-velocity call. The Linux branch changes this
adapter-only claim to false, removes `safe_stop` from advertised supported skills,
and returns a non-accepted receipt after sending the partial AGV stop. This is an
honesty correction, not a new physical safety mechanism.

## Required deployment work

- build and source the exact vendor interface/bridge packages;
- verify controller/EDG login, power, enable, and emergency-stop behavior under
  operator supervision;
- calibrate a transport-safe joint/TCP envelope instead of trusting a preset name;
- supply measured AGV odometry rather than open-loop time integration;
- define and verify a whole-robot safe-stop sequence;
- use cancellable action wrappers or bounded service clients for long motions;
- record robot serial/configuration hashes, sanitized command receipts, measured
  before/after state, and independent outcome checks.

Until that work is complete, no JAKA item in this repository is
`ROS2-RUNTIME-VERIFIED`, `SIMULATION-VERIFIED`, or `HARDWARE-VERIFIED`.
