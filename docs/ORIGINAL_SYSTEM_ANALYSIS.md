# Original System Analysis

## Scope and evidence policy

The analysis was performed against a separately delivered reference workspace that is intentionally not redistributed with this repository. It covers the chat agent, its simulation and real-SDK skills, ROS2 interface packages, launch/configuration files, and the C++ service nodes. File-and-line citations identify evidence in that reference delivery; they are not runtime dependencies. Deployment network values in the legacy YAML are intentionally not reproduced.

## What the system is

The original system is a Qwen/OpenAI-compatible conversational agent whose static function schema is declared in `chat_agent/skills/robot_agent.py:56-611`. `RobotAgent.chat()` sends conversation history and the tool schema to the model, then executes every returned tool call in a loop (`robot_agent.py:904-942`). `_dispatch()` is a large conditional router from tool name to a Python skill object (`robot_agent.py:656-900`).

The real-machine path constructs lift, waist, arm, head, and AGV objects in `real_sdk_skills.py:637-644`. Arm and external-axis calls use services exposed by `KargoExtAndArm`; AGV elementary motion publishes velocity commands through `agv_skill.py`.

## Answers to the required questions

1. **Supported skills.** The LLM sees 27 functions: lift (2), waist (2), hold/query (2), dual-arm convenience motion (4), head (4), single-arm Cartesian motion (2), MoveIt dual-arm planning/presets (2), AGV motion (8), and one MoveIt single-arm planning function. See the complete inventory in `SKILL_INVENTORY.md` and the declarations at `robot_agent.py:56-611`.

2. **Inputs.** Inputs and ranges are embedded in the JSON-like tool declarations, not in a shared executable skill model. Examples are lift height 0–780 mm (`robot_agent.py:60-75`), head yaw ±90° (`robot_agent.py:258-273`), and AGV velocity limits (`robot_agent.py:461-471`).

3. **ROS2 transport.** Arm/lift/waist/head use ROS2 services on the real-SDK path (`real_sdk_skills.py:76-239`, `467-527`). AGV elementary motion publishes `geometry_msgs/Twist` and subscribes to steering `JointState` (`agv_skill.py:101-168`). MoveIt planning is service-based when the external provider is present (`real_sdk_skills.py:382-429`). No ROS2 actions are used in the inspected Agent path.

4. **Real results.** External-axis and arm wrappers return the ROS2/SDK response and sometimes perform a subsequent state query for user-facing text. However, there is no generic expected-effect/tolerance verifier. AGV distance and angle motion are explicitly open-loop (`agv_skill.py:411-459`).

5. **Command success vs physical success.** Yes, in several paths. `RobotAgent._dispatch()` formats a successful function return as task success (`robot_agent.py:706-770`). The C++ arm service marks success when the blocking SDK call returns `ERR_SUCC` (`KargoExtAndArm.cpp:567-581`) but does not compare final feedback with a requested tolerance. The AGV publishes for a computed duration, sends stop, and returns (`agv_skill.py:293-360`); steering feedback is checked, but base displacement is not.

6. **Multi-step tasks.** The model may emit several tool calls in one or more rounds, and the `while` loop executes them sequentially (`robot_agent.py:904-942`). There is no explicit `TaskPlan`, stable step ID, expected effect, dependency graph, or plan revision.

7. **Unified robot state.** No. State is queried ad hoc through each skill in the `robot_pose` branch (`robot_agent.py:682-704`). Conversation history is maintained, but that is not a typed, timestamped robot state.

8. **Preconditions.** Only local implementation checks exist (service availability, SDK login, numeric clamping, steering readiness). There is no cross-skill precondition model used before LLM tool execution.

9. **Body resource conflicts.** The inspected Agent layer has no arm/AGV/lift resource ownership or cross-component constraint checker. The SDK offers a coordinated `MultiMove` service (`KargoExtAndArm.cpp:588-639`), but the Agent does not use it as a global scheduler.

10. **Failure behavior.** Exceptions are converted to a text tool result (`robot_agent.py:897-900`) and returned to the LLM. Deterministic retry budgets, recovery actions, re-grounding, and safe-stop escalation are absent.

11. **Reusable code.** `RealSdkSession`, the service clients in `RealSdkLiftBackend`, `RealSdkArmSkill`, `RealSdkHeadBackend`, and `RealSdkAgvSkill` are useful adapter inputs (`real_sdk_skills.py:31-644`). Interface definitions and the `KargoExtAndArm`/`JagvNavigation` nodes remain the true-machine backend.

12. **Logic to reimplement.** Skill metadata, structured plans, typed state, grounding, deterministic repair, runtime guard, physical outcome verification, bounded recovery, trace data, and benchmark evaluation belong in the new project rather than in the monolithic dispatcher.

## Important nuance

The legacy code is not “unsafe by definition.” It contains meaningful local checks: service responses, SDK error codes, external-axis feedback queries, steering encoder readiness, and MoveIt planning. The missing layer is a uniform, cross-component interpretation of those observations before and after each task step.
