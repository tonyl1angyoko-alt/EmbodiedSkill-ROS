# JAKA/Kargo integration layer

This directory is owned by EmbodiedSkill-ROS. It targets a separately delivered
laboratory JAKA/Kargo ROS2 workspace used with permission. The original workspace,
vendor SDK, robot description, and private deployment configuration are not
redistributed.

## Boundary

```text
SkillExecutor
  -> JakaKargoBackend
  -> JakaKargoStateProvider + JakaKargoCapabilityMapper
  -> JakaKargoRos2Transport
  -> external jaka_toolbox_interfaces / jagv_interfaces
  -> external jaka_toolbox + JAGV nodes
  -> vendor SDK / robot
```

Imports remain optional. Pure-core users do not need ROS2 or the laboratory
interfaces. `JakaKargoRos2Transport` imports them only when instantiated.

## External workspace build

Install the ROS Humble dependencies declared by the external packages, including
`moveit_msgs`, then build from the external workspace rather than copying it here:

```bash
source /opt/ros/humble/setup.bash
cd /path/to/kargo_ws_delivery_20260521
colcon build --packages-select jagv_interfaces jaka_toolbox_interfaces jaka_toolbox
source install/setup.bash
```

The vendor package build does not prove hardware connectivity. Do not launch
`kargo_ext_and_arm_node` unless controller access, network configuration, workspace
safety, and operator supervision have been established.

## Read-only probe

After sourcing the external workspace and EmbodiedSkill-ROS:

```bash
ros2 launch embodied_skill_ros jaka_kargo_integration.launch.py
```

The launch file runs only `jaka_kargo_probe`. It discovers endpoints and reads
available state with motion disabled. It does not start the vendor driver or send a
motion command.

The committed example configuration is deliberately non-deployable: motion is off,
global E-stop scope is not asserted, and transport joint targets are absent. An
application must provide reviewed calibration and safety evidence in a private
deployment configuration before the capability mapper advertises motion.

## Legacy-compatible runtime harness

With the two external interface packages sourced:

```bash
ROS_LOCALHOST_ONLY=1 ros2 run embodied_skill_ros validate_jaka_kargo \
  --output jaka_kargo_validation_outputs/integration_scenarios.json
```

This command starts a separate schema-compatible stub process and never loads the
vendor SDK. It validates adapter behavior, including the accepted/no-motion negative
control, but it is not physics simulation or hardware evidence.
