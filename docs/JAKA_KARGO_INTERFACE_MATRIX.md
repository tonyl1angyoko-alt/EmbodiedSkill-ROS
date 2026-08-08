# JAKA/Kargo Interface and Capability Matrix

Status date: 2026-08-08

The matrix distinguishes the real external interface from the evidence used to
validate this repository's adapter. `ROS2-RUNTIME-VERIFIED` below means the
process-separated legacy-compatible stub, not the JAKA node or robot.

| Embodied skill | Legacy interface | ROS primitive | Measured observation | Cancellation / timeout | Scope / side effects | Evidence |
|---|---|---|---|---|---|---|
| `retract_arm(arm)` | `/joint_move_arm`, id 0/1, seven calibrated joints | Service | `/query_pose_arm` joint vector; safety derived only from calibrated target+tolerance; readiness requires a reviewed deployment assertion | no reliable cancellation; client-wait timeout only | single-arm service mapping; legacy bilateral preset mode is rejected | mapping `UNIT-VERIFIED`; schema stub `ROS2-RUNTIME-VERIFIED`; JAKA runtime/hardware `UNVERIFIED` |
| `move_agv(distance_m,speed_mps)` | `/navigate_single_pose` with current odom x + signed distance | Service plus topics | JAGV `Odometry` x and `MotionState`; both revisions must advance after dispatch | navigation timeout is backend-bounded; AGV component stop exists | map-frame X displacement, not the legacy open-loop timed skill | mapping `UNIT-VERIFIED`; J7/J9 schema-stub runtime; JAGV runtime/hardware `UNVERIFIED` |
| `set_lift(height_mm)` | `/joint_move_ext`, external id 0 | Service | `/query_status_ext` id 0 feedback, power/enable/limit/in-position | no reliable cancellation; client-wait timeout only | 0–780 mm deployment domain | mapping `UNIT-VERIFIED`; schema stub `ROS2-RUNTIME-VERIFIED`; JAKA runtime/hardware `UNVERIFIED` |
| `set_head(yaw?,pitch?)` | `/joint_move_ext`, ids 2 then 3 | sequential Services | `/query_status_ext` ids 2/3; pitch sign inverted into user convention | no reliable cancellation; client-wait timeout only | partial yaw effect is possible if pitch fails | mapping `UNIT-VERIFIED`; schema stub `ROS2-RUNTIME-VERIFIED`; JAKA runtime/hardware `UNVERIFIED` |
| `set_waist(angle_deg)` | `/joint_move_ext`, external id 1 | Service | `/query_status_ext` id 1 into dynamic `waist_angle_deg` | no reliable cancellation; client-wait timeout only | integration-only contract, 0–84° | mapping `UNIT-VERIFIED`; schema stub `ROS2-RUNTIME-VERIFIED`; JAKA runtime/hardware `UNVERIFIED` |
| backend `stop()` | `/motion_state_control`, id 3 | Service | AGV motion state only | AGV component stop | `AGV_ONLY`; receipt never claims whole-robot safe stop | mapping/stub `UNIT-VERIFIED` / `ROS2-RUNTIME-VERIFIED`; whole-robot stop `UNVERIFIED` |

## State mapping

| Source | RobotState field(s) | UNKNOWN rule | Freshness |
|---|---|---|---|
| `AxisStatusQuery(0)` | `lift_height_mm`, `lift_ready` | query failure leaves both unavailable | response receipt timestamp |
| `AxisStatusQuery(1)` | `facts.waist_angle_deg`, `facts.waist_ready` | query failure leaves facts absent | response receipt timestamp |
| `AxisStatusQuery(2/3)` | `head_yaw_deg`, `head_pitch_deg`, `head_ready` | either missing axis prevents known aggregate readiness | per-query receipt timestamp |
| `PoseQuery(0/1)` | joint/TCP facts, optional arm-safe classification; readiness only under reviewed deployment assertion | readiness is UNKNOWN by default; safety is UNKNOWN without calibrated target | per-query receipt timestamp |
| JAGV odometry | `agv_position_m`, y/orientation facts | no message means UNKNOWN | message header timestamp |
| JAGV motion state | `agv_moving`, `agv_ready`, AGV E-stop/fault facts | no message means UNKNOWN | local receipt timestamp; message has no header |
| asserted whole-robot safety source | `emergency_stop`, `fault` | AGV-only scope is not promoted by default | same motion-state receipt timestamp |

## Capability admission rules

Motion is advertised only when all of the following are true:

1. deployment configuration explicitly enables motion;
2. a whole-robot emergency-stop observation is explicitly asserted and available;
3. command and post-command observation endpoints for that skill are discovered;
4. arm transport targets, when needed, are calibrated; and
5. unavoidable backend effects fit the abstract contract.

The example configuration keeps motion disabled and contains no joint targets,
private IPs, or map name. It is safe to commit but is not a deployable calibration.

## Evidence summary

- Five skill mappings across five named components are implemented: arm, AGV,
  lift, head, and waist.
- Eight external endpoints are discovered by the runtime harness: six Services and
  two asynchronous AGV topics.
- The state provider also maps two arm queries and four external-axis query ids.
- Twenty pure-Python integration contract tests pass.
- Nine process-separated ROS2 legacy-compatible scenarios pass, including separate
  accepted/no-motion checks for lift feedback and AGV odometry.
- The unmodified external interface packages and `jaka_toolbox` compile on Humble.
- Frozen-core delta is zero.
- JAKA node runtime, SDK session, calibration, and hardware motion remain unverified.
