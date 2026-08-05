# ROS2 Interface Inventory

No ROS2 actions were found in the inspected Agent execution path. Interfaces are services, publishers, and subscribers.

## Interfaces used directly by the chat Agent path

| Name | Kind / type | Direction | Evidence | Outcome caveat |
|---|---|---|---|---|
| `/query_status_ext` | service `AxisStatusQuery` | client → SDK node | `real_sdk_skills.py:85-100` | supplies feedback including `pos_fdb`; wrapper returns mainly position |
| `/joint_move_ext` | service `JointMove` | client → SDK node | `real_sdk_skills.py:86-123`, `479-511` | response reports SDK call success; caller should re-query |
| `/query_pose_arm` | service `PoseQuery` | client → SDK node | `real_sdk_skills.py:237-256` | returns measured joints/TCP |
| `/joint_move_arm` | service `JointMove` | client → SDK node | `real_sdk_skills.py:238`, `258-281` | no generic target-tolerance check |
| `/linear_move_arm` | service `LinearMove` | client → SDK node | `real_sdk_skills.py:239`, `283-380` | no generic target-tolerance check |
| `/dual_arm_planning` | service `DualArmPlanningTarget` | client → external MoveIt provider | `real_sdk_skills.py:382-429` | interface is defined, but provider is not created in included toolbox C++ sources: **UNKNOWN external dependency** |
| `/<robot>/agv/cmd_vel` | topic `geometry_msgs/Twist` | publisher → AGV | `agv_skill.py:116-129`, `293-360` | timed open-loop body motion |
| `/<robot>/agv/joint_states` | topic `sensor_msgs/JointState` | AGV → subscriber | `agv_skill.py:130-159` | verifies steering orientation/stability, not base displacement |
| `/<robot>/agv/motion_state_control` | service `jagv_interfaces/MotionStateControl` | optional client → AGV | `agv_skill.py:161-169`, `273-291` | resume failure is logged and ignored |

Names beginning with `/<robot>` are templates derived by code. No new concrete robot name is asserted by EmbodiedSkill-ROS.

## Services/topics exposed by included toolbox nodes

`KargoExtAndArm` creates `query_pose_arm`, `linear_move_arm`, `joint_move_arm`, `query_pose_ext`, `query_status_ext`, `joint_move_ext`, `multi_move`, TIO, force-control, frame-setting, and trajectory-follow services (`KargoExtAndArm.cpp:33-129`). It also publishes `upperlimb_joint_states` (`KargoExtAndArm.cpp:23-29`).

`JagvNavigation` subscribes to configured motion-state and odometry topics, plus `goal_pose`; publishes `planned_path`, `start_pose`, and `end_pose`; and exposes path/single-pose navigation, motion-state query/control, relocalization, and wheel-odometry reset services (`JagvNavigation.cpp:22-145`).

The interface build list is authoritative in `jaka_toolbox_interfaces/CMakeLists.txt:50-81` and `jagv_interfaces/CMakeLists.txt:15-31`.

## Interfaces available but not exposed as LLM tools

The toolbox also defines force control, gripper/TIO read/write, RGB-D and point-cloud query, navigation, trajectory-following, relocalization, and frame-setting services. They are intentionally not claimed as new-project skills because the minimum project only wires capabilities evidenced in the legacy Agent and because their preconditions/effects are not yet modeled.

## Configuration handling

Legacy YAML contains deployment-specific network and namespace values. These are not copied into the new project. Integrators must provide their own local ROS2 launch configuration. `JakaRobotBackend` accepts existing initialized skill objects rather than embedding addresses or credentials.
