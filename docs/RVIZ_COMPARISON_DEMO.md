# RViz A/B Comparison Demo

This is the presentation-oriented companion to the single-robot RViz reproduction
in `RVIZ_DEMO.md`. It keeps the same ROS2 fake-robot semantics but shows two
process-isolated robots side by side so the execution-policy difference is visible
without reading terminal traces.

## What is compared

Both lanes receive the same task, initial state, and scripted fake-robot behavior.
Only the execution policy differs:

- **Baseline — direct middleware execution:** send the requested ROS command and
  treat an accepted `SUCCEEDED` action result as success.
- **EmbodiedSkill-ROS:** ground the task against observed state, execute through the
  existing `SkillExecutor`, observe the post-command state, verify contract effects,
  and select bounded repair or stop behavior.

The baseline is intentionally narrow: it visualizes the failure mode targeted by
this project. It is not presented as a benchmark against every ROS application,
behavior tree, or planning framework.

## Comparison 1 — generic repair

```bash
ROS_LOG_DIR=/tmp/embodied_skill_rviz_comparison_repair \
ROS_LOCALHOST_ONLY=1 \
ros2 launch embodied_skill_ros rviz_comparison.launch.py comparison_case:=repair
```

Expected sequence:

1. Both robots begin with the same extended left arm and the same `move_agv(1.0 m)` task.
2. **Baseline** executes `move_agv` immediately and reaches the goal with the arm
   still extended.
3. **EmbodiedSkill-ROS** detects `left_arm_safe == False`, selects `REPAIR`, and the
   existing `PlanRepairer` inserts `retract_arm(left)`.
4. The right-hand robot retracts its arm, verifies the new state, then resumes the
   original `move_agv` step.
5. The RViz text panels show the two policies and their live phases above the lanes.

## Comparison 2 — middleware success is not physical success

```bash
ROS_LOG_DIR=/tmp/embodied_skill_rviz_comparison_false_success \
ROS_LOCALHOST_ONLY=1 \
ros2 launch embodied_skill_ros rviz_comparison.launch.py comparison_case:=false_success
```

Expected sequence:

1. Both fake robots accept `move_agv` and return ROS action `SUCCEEDED`.
2. The scripted physical transition is suppressed, so both RViz robots remain at `x=0`.
3. **Baseline** stops reasoning at middleware success and displays `SUCCESS (middleware-only)`.
4. **EmbodiedSkill-ROS** consumes the later observation, detects `x=0` instead of
   the contracted `x=1`, rejects the physical outcome, and reaches `STOP`.

## Recording layout

The supplied RViz configuration opens a wide A/B view with:

- two identical robot geometries in separate lanes;
- lane titles identifying the execution policies;
- live `TEXT_VIEW_FACING` status panels;
- lane lines and goal markers at `x=1.0`;
- a shared task/fault banner above the comparison.

For a portfolio recording, capture RViz and the concise terminal summary together.
The single-robot `repair` and `false_success` demos remain available as reproduction
evidence; the A/B launch is the recommended presentation view.

## Validation boundary

This remains **RViz state visualization**, not physics simulation. The smooth motion
is presentation-only interpolation of authoritative ROS observations. There is no
Gazebo dynamics, collision model, controller simulation, sensor simulation, or
hardware claim. No laboratory JAKA/Kargo assets are used.
