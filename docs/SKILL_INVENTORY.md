# Original Skill Inventory

All names below are exposed to the LLM in `chat_agent/skills/robot_agent.py:56-611` and dispatched in `robot_agent.py:656-895`.

| Component | Tool | Main inputs | Backend/result semantics |
|---|---|---|---|
| Lift | `lift_to` | `height_mm` 0–780, optional duration | `/joint_move_ext`; dispatch queries current height |
| Lift | `lift_by` | signed `delta_mm`, duration | Same; relative target derived by skill |
| Waist | `rotate_waist_to` | `angle_deg` 0–84, duration | `/joint_move_ext`; dispatch queries current angle |
| Waist | `rotate_waist_by` | signed `delta_deg`, duration | Same |
| General | `hold` | seconds | Local sleep/hold; elapsed time is the effect |
| General | `robot_pose` | none | Queries lift, waist, optional head, arm pose report |
| Arms | `arms_go_preset` | `home/ready/grasp`, duration | `/joint_move_arm`; both arms |
| Arms | `arms_lift` | signed `delta_z_mm`, duration | `/linear_move_arm`; both arms |
| Arms | `arms_extend` | signed `delta_x_mm`, duration | `/linear_move_arm`; both arms |
| Arms | `arms_spread` | signed `delta_mm`, duration | `/linear_move_arm`; symmetric Y motion |
| Head | `head_yaw_to/by` | absolute or delta degree, duration | external axis ID 2 via services |
| Head | `head_pitch_to/by` | absolute or delta degree, duration | external axis ID 3 via services |
| Arm | `arm_movl_single` | arm, Cartesian/RPY deltas, velocity | `/linear_move_arm`; single arm |
| Arm | `arm_movl_abs` | arm, XYZ mm, RPY degree, velocity | `/linear_move_arm`; single arm |
| MoveIt | `dual_arm_plan` | use flags, 7-value poses, execute, scaling, timeout | `/dual_arm_planning`; provider not implemented in the included toolbox node |
| MoveIt | `dual_arm_go_preset` | named pose, execute, scaling | Wrapper around `dual_arm_plan` |
| AGV | `agv_move` | vx/vy/wz, duration | publishes `Twist`; open-loop duration |
| AGV | `agv_move_forward/backward` | speed, duration | publishes `Twist`; open-loop duration |
| AGV | `agv_turn_left/right` | angular speed, duration | publishes `Twist`; open-loop duration |
| AGV | `agv_stop` | none | publishes zero `Twist` three times |
| AGV | `agv_drive_distance` | direction, distance, speed | converts distance/speed to duration; open-loop |
| AGV | `agv_rotate_angle` | angle, angular speed | converts angle/speed to duration; open-loop |
| MoveIt | `moveit_plan_single_arm_pose` | arm, XYZ, unit, quaternion, frame, planning and RViz options | simulation/MoveIt helper; saves and visualizes trajectory |

## Parameter model limitations

- The LLM schema is separate from the Python implementations, so range behavior can differ. Some skill classes clamp values rather than reject them; for example AGV clamping is in `agv_skill.py:387-409`.
- No tool declaration contains required body resources, cross-component preconditions, expected effects, verification tolerance, or recovery policy.
- `duration` is accepted by several high-level tools but real SDK motion methods primarily use velocity/acceleration parameters; this semantic mismatch should not be hidden by the new adapter.

## Physical verification classification

| Class | Original evidence | Assessment |
|---|---|---|
| External axes | `AxisStatusQuery` includes `is_inpos`, `pos_cmd`, and `pos_fdb` (`AxisStatusQuery.srv:4-11`) | Feedback exists, but the Agent does not uniformly verify target tolerance after every command |
| Arms | `PoseQuery` returns Cartesian and joint positions (`PoseQuery.srv:5-10`) | Feedback exists; named “transport safe” semantics are not defined |
| AGV elementary motion | steering `JointState` plus timed `cmd_vel` (`agv_skill.py:101-360`) | Steering is checked; displacement/rotation outcome is not |
| AGV navigation | odometry and motion-state subscriptions in `JagvNavigation.cpp:22-40` | Potential future adapter source; not used by current Agent tools |
| MoveIt | planned trajectory and service result | Planning result is observable; final physical pose verification remains separate |
