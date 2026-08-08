# JAKA/Kargo Legacy Workspace Integration Analysis

Audit date: 2026-08-08

Scope: the separately delivered `kargo_ws_delivery_20260521` workspace, inspected
with permission as an external development dependency. No legacy source, robot
description, network configuration, vendor binary, build tree, or nested Git
history is redistributed by EmbodiedSkill-ROS.

## System call chain

The real high-level path is not a single ROS node:

```text
user text
  -> chat_real_sdk.py
  -> RobotAgent.chat (Qwen-compatible function calling)
  -> RobotAgent._dispatch
  -> RealSdk{Arm,Lift,Waist,Head,Agv}Skill
  -> rclpy Service client or AGV topic publisher
  -> kargo_ext_and_arm_node / jagv_navigation_node / AGV controller
  -> JAKA dual-arm SDK or JAGV controller
  -> robot
```

`robot_agent.py` registers lift, waist, head, bilateral/single-arm, AGV velocity,
AGV distance/rotation, pose-query, hold, and optional MoveIt tools. The dispatcher
calls concrete Python skill objects directly. It reports their return text to the
LLM; it has no general contract grounding, independent outcome verifier, or
capability-scope check.

For arm/lift/waist/head, `real_sdk_skills.py` uses `call_async` followed by
`spin_until_future_complete` without an explicit timeout. For AGV elementary motion,
`agv_skill.py` publishes `Twist` at 10 Hz, waits for steering encoder readiness, then
estimates duration from requested distance/speed. The source explicitly calls this
open-loop and has no displacement odometry in that path.

An alternate `JagvNavigation` node exposes map navigation services. It subscribes
JAGV odometry and motion state, forwards requests to the JAGV `AutoMove` service,
and observes the motion-state transition from idle to moving and back. The v0.3
adapter uses this measured navigation path for `move_agv`, not the open-loop
function-calling path.

## Low-level ROS2 and SDK boundary

`KargoExtAndArm` creates the following relevant interfaces:

| Role | Interface | Type | SDK path |
|---|---|---|---|
| arm feedback | `/query_pose_arm` | `jaka_toolbox_interfaces/srv/PoseQuery` | `edg_get_stat` |
| external-axis feedback | `/query_status_ext` | `jaka_toolbox_interfaces/srv/AxisStatusQuery` | `get_ext_status` |
| arm joint move | `/joint_move_arm` | `jaka_toolbox_interfaces/srv/JointMove` | `robot_run_multi_movj` |
| arm linear move | `/linear_move_arm` | `jaka_toolbox_interfaces/srv/LinearMove` | `robot_run_multi_movl` |
| lift/waist/head move | `/joint_move_ext` | `jaka_toolbox_interfaces/srv/JointMove` | `multi_mov_with_ext` |
| periodic joints | `/upperlimb_joint_states` | `sensor_msgs/msg/JointState` | external-axis status + arm EDG state |

The node initializes the vendor SDK, controller login/power/enable, and EDG state
feed inside the C++ process. Its build links directly to a delivered x86-64 shared
library. A Service response with `success=1` means the SDK call returned success; it
is not an independent comparison between target and later measured state.

`JagvNavigation` adds:

| Role | Interface | Type |
|---|---|---|
| map-X goal used by this adapter | `/navigate_single_pose` | `jaka_toolbox_interfaces/srv/SinglePoseNavigate` |
| measured base pose | configured JAGV odometry topic | `nav_msgs/msg/Odometry` |
| motion/fault/AGV E-stop bits | configured JAGV motion topic | `jagv_interfaces/msg/MotionState` |
| AGV pause/resume/stop | `/motion_state_control` | `jaka_toolbox_interfaces/srv/TriggerInt` |

No ROS actions are defined in the audited workspace. Arm and external-axis motion
remain synchronous Services. The navigation Service has an internal timeout and an
independent AGV stop Service, but no Action cancellation protocol.

## Observable state and gaps

Measured signals available in source are:

- left/right 7-joint state and TCP pose from `PoseQuery`;
- lift, waist, head-yaw, and head-pitch feedback plus commanded position, powered,
  enabled, limit, and in-position flags from `AxisStatusQuery`;
- all 18 upper-limb joints on `upperlimb_joint_states`;
- AGV pose from odometry; and
- AGV motion state, drive error codes, and an AGV E-stop bit from `MotionState`.

Signals not established by the delivered boundary are:

- a calibrated boolean transport-safe envelope for either arm;
- an arm powered/enabled/readiness field in `PoseQuery`;
- whole-robot emergency-stop coverage across AGV, arms, lift, head, and waist;
- a whole-robot stopped-state confirmation;
- an application-cancellable arm/lift/head/waist operation; and
- redundant or independently trustworthy sensing.

The integration therefore leaves arm readiness UNKNOWN unless a reviewed deployment
explicitly asserts that successful `PoseQuery` is sufficient for readiness, and
computes `left/right_arm_safe` only when an operator has
supplied seven-joint calibrated targets and a tolerance. The JAGV E-stop bit remains
`agv_emergency_stop`; it becomes the global `emergency_stop` field only under an
explicit deployment assertion that its scope is whole-robot. Without that assertion,
motion capabilities are withheld.

The AGV transport also records odometry and motion-state sequence numbers before
submitting navigation. Its next observation waits for both topic revisions to
advance. A runtime negative control exposed why this is necessary: directly reusing
the cached odometry message while constructing a request can contaminate local state,
and reading the cache immediately after a Service response can return a pre-command
sample. The adapter now copies request fields and enforces a post-command revision
barrier; J7 verifies nominal motion and J9 verifies Service success with unchanged
odometry.

## Side effects, stop, timeout, and cancellation

- The legacy `go_preset` Python helper always submits 14 joints with arm id `-1`.
  It is bilateral even when an abstract caller asks about one arm. The integration
  capability mapper declares both arm-safety effects and the core rejects the
  narrower contract before transmission.
- The underlying `/joint_move_arm` schema also supports ids `0` and `1`. v0.3 can
  use this single-arm service only with per-arm calibrated joint targets; it does
  not reuse an uncalibrated preset name as proof of safety.
- `set_head(yaw,pitch)` requires two sequential external-axis Services. Yaw can move
  before pitch fails, so later observation is mandatory.
- External-axis `JointMove` declares a STOP mode, but all `KargoExtAndArm` services
  share a mutually exclusive callback group. The audit therefore does not claim
  reliable concurrent cancellation of a blocking motion callback.
- The available stop path is AGV motion-state control code `3` or zero `Twist` in
  the elementary AGV skill. Neither is a whole-robot safe stop.
- A client timeout on a ROS Service cannot prove the server callback or physical
  motion stopped. v0.3 returns `timed_out=True` with this caveat instead of claiming
  cancellation.

## Dependency and build audit

The workspace contains four ROS packages: `jagv_interfaces`,
`jaka_toolbox_interfaces`, `jaka_toolbox`, and `jaka_kargo_description`.
`jagv_interfaces` built independently on Humble. `jaka_toolbox_interfaces` initially
failed because its CMake file requires `moveit_msgs`; a non-system temporary overlay
of the standard ROS message packages allowed the exact external interface package to
build. With both interface packages sourced, the unmodified `jaka_toolbox` package,
including its vendor-SDK link, also built successfully in `/tmp`.

This establishes `ROS2-BUILD-VERIFIED`, not runtime or hardware behavior. The C++
node was not launched because construction initiates SDK/controller setup and no
supervised hardware authorization was given.

## Provenance and publication boundary

The laboratory/reference stack owns the elementary skills, ROS wrappers, interface
definitions, robot description, dispatcher, low-level nodes, and vendor SDK. The
v0.3 repository owns only the adapter/state/capability boundary, integration-only
waist contract, optional ROS client, safe read-only probe, exact-schema stub harness,
tests, evidence, and documentation.

The external scan found private-network configuration, workstation-specific paths,
nested Git repositories, robot meshes, and a 26 MB vendor shared library. No live
credential was found, but none of those materials is copied. `jagv_interfaces` also
declares an unresolved license placeholder, which is an additional reason to keep it
external even though its generated types were used for local validation.
