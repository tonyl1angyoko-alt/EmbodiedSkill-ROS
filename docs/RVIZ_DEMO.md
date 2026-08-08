# RViz state visualization demo

This self-contained demo turns the already validated EmbodiedSkill ROS2 state and
execution decisions into a recordable RViz view of a small mobile manipulator. The
robot description uses only URDF box and cylinder primitives and redistributes no
laboratory or vendor asset.

## What this is

- RViz state visualization of the real `SkillExecutor` → `Ros2RobotBackend` →
  process-separated fake robot → asynchronous observation → `OutcomeVerifier` path.
- A presentation adapter from `/embodied_skill/state` to `/joint_states` and
  `map -> base_link` TF.
- Smooth, display-only interpolation at 25 Hz. Authoritative state remains the ROS
  observation; interpolation never feeds back into grounding or verification.

## What this is not

- Not Gazebo and not physics simulation.
- Not MoveIt, dynamics, collision, or safety validation.
- Not JAKA deployment or hardware evidence.
- Not a replacement execution system: repair and verification decisions still come
  from the existing EmbodiedSkill core.

## Prerequisites

Ubuntu 22.04 with ROS2 Humble and these ordinary ROS visualization packages:

```bash
sudo apt install ros-humble-rviz2 ros-humble-robot-state-publisher \
  ros-humble-xacro ros-humble-tf2-ros
```

They were already present on the validated development machine.

Build once:

```bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select embodied_skill_ros
source install/setup.bash
```

## Demo 1 — Generic Repair

```bash
ROS_LOG_DIR=/tmp/embodied_skill_rviz_repair_logs ROS_LOCALHOST_ONLY=1 \
  ros2 launch embodied_skill_ros rviz_demo.launch.py demo_case:=repair
```

The original plan contains only `move_agv(distance_m=1.0)`. With
`left_arm_safe=False`, the existing effect-driven `PlanRepairer` produces
`retract_arm(left) -> move_agv`. RViz first folds the arm, then moves the base one
metre. The terminal prints the inserted-step provenance, observations, verifier
results, and final `SUCCESS`.

## Demo 2 — Middleware success is not physical success

```bash
ROS_LOG_DIR=/tmp/embodied_skill_rviz_false_success_logs ROS_LOCALHOST_ONLY=1 \
  ros2 launch embodied_skill_ros rviz_demo.launch.py demo_case:=false_success
```

The fake robot accepts the `move_agv` action and returns `SUCCEEDED`, but its scripted
no-motion behavior does not apply the physical transition. The fresh state observation
remains at `agv_position_m=0.0`; `OutcomeVerifier` rejects the effect and the executor
chooses `STOP`. RViz correctly remains still.

Use `Ctrl-C` after the final banner. For headless graph validation, append
`use_rviz:=false` to either launch command.

## Recording notes

- RViz fixed frame: `map`.
- The saved view already contains Grid and RobotModel displays.
- Allow about 10–12 seconds per clip: three seconds startup, a 1.5-second initial
  pose hold, two to four seconds execution, and a short final-state hold.
- Terminal output is intentionally concise; fake robot and bridge logs go to the
  selected `ROS_LOG_DIR`.

The extended arm is mapped to `(shoulder, elbow) = (0.2, 0.2)` radians and the
transport-safe arm to `(-1.1, 1.8)`. A one-metre base transition is visually
interpolated over approximately two seconds. These values affect presentation only.
