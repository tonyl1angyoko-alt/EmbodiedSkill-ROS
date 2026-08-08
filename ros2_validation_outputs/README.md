# ROS2 Runtime Evidence

`runtime_scenarios.json` is generated on the Ubuntu 22.04 / ROS2 Humble host by:

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
ROS_LOG_DIR=/tmp/embodied_skill_ros_logs ROS_LOCALHOST_ONLY=1 \
  ros2 run embodied_skill_ros validate_runtime \
  --output ros2_validation_outputs/runtime_scenarios.json
```

The artifact contains all R1–R15 plans, contracts, capability preflight results,
initial/final observations, timestamps, grounding issues, ROS action/service/topic
events, verifier and recovery decisions, structural replan output, and a test-only
hidden-state oracle snapshot. It also preserves the unsafe TOCTOU and fresh sensor
spoof probes.

The hidden-state service is queried only by the scenario scorer after execution.
The ROS backend, state manager, executor, and outcome verifier do not consume it.
Timestamps, process IDs, and temporary log paths are host-run metadata and are not
expected to be byte-for-byte deterministic.
