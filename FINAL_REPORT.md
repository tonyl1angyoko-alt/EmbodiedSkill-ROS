# Final Report

## 1. What the original system is

The original project is a Qwen function-calling chat agent connected to JAKA mobile-manipulator skills. A monolithic dispatcher calls lift, waist, head, arm, MoveIt, and AGV wrappers. Arm/external axes primarily use ROS2 services backed by the JAKA SDK; elementary AGV motion publishes timed `cmd_vel`. The model can chain multiple calls, but the system has no explicit structured plan, unified body state, cross-component resource model, or generic physical-outcome verifier.

## 2. What the new project adds

Evidence label: `MOCK-VERIFIED` for the capabilities and results in this section.

EmbodiedSkill-ROS adds:

- typed `RobotState`, `TaskPlan`, `PlanStep`, command, verification, and result models;
- a registry-limited skill representation with schemas, resources, preconditions, expected effects, timeout, and recovery policy;
- state projection, body/resource constraints, and deterministic plan repair;
- closed-loop `execute → observe → verify → update` execution;
- bounded retry, re-grounding, continuation-only bounded replan, and one recorded backend-stop attempt for every STOP decision;
- full per-attempt execution traces;
- deterministic Mock fault injection;
- four demos, 48 automated tests, and a 30-scenario A/B/C/D benchmark.

## 3. What was genuinely reimplemented

All core logic under `embodied_skill_ros/` is independent of the original SDK: models, registry, skills, state manager, planner adapters, grounder, constraint checker, repairer, guard, verifier, recovery manager, executor, tracing, metrics, Mock backend, scenarios, and evaluation.

## 4. What reuses original adapters

Evidence label: `STATICALLY-INSPECTED`; ROS2 build and hardware execution are `UNVERIFIED`.

`JakaRobotBackend` is shaped to call original real-SDK skill objects for arm preset motion, AGV distance motion/stop, lift positioning, and head yaw/pitch. It does not copy addresses, credentials, ROS2 initialization, interface packages, or original source. The separately delivered reference system—not this repository—contains the actual hardware transport layer.

## 5. Supported demos

1. Normal arm → AGV → lift multi-step execution.
2. Same movement instruction producing a one-step or repaired two-step plan depending on arm state.
3. Parallel body-resource conflict serialization plus transport-pose insertion.
4. Command accepted but physical lift feedback unchanged, followed by verified retry.
5. Additional benchmark-only timeout, command failure, persistent actuator outage, and state-drift cases.

## 6. Tests actually run

The final standard-library suite was run from the standalone repository root with:

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

Current result: **100 tests passed**. The suite additionally covers fail-closed UNKNOWN emergency-stop state, non-finite values, non-idempotent continuation checkpoints, backend capability filtering, verified-global-stop injection, preserved observation timestamps, tri-state physical outcomes, empty-plan rejection, and the shared Structured/LLM planner protocol. ROS2 Humble and JAKA hardware remain unverified.

`colcon` was not installed in the execution environment, so a ROS2 build was not claimed. Python compilation/import, four demos, the test suite, and benchmark were executed in the Mock environment.

`python3 -m pytest` was also attempted, but the system Python reported `No module named pytest`. The same pytest-compatible tests were therefore executed with `unittest` without installing or downloading dependencies.

## 7. Benchmark design and result

The checked-in benchmark contains exactly 30 required scenarios and reports all nine requested metrics. Task success is independently scored from final physical state.

Evidence label: `MOCK-VERIFIED` on 30 predefined deterministic scenarios. Direct and structured-only configurations reached 60.00% task success and 0.00% state-change success. State grounding raised task success to 83.33% and state-change success to 100.00%. Adding runtime recovery raised overall success to 96.67%, with 0 invalid calls in the full configuration and 100% verification accuracy in this deterministic Mock dataset. These figures are not ROS2 or hardware results.

## 8. Hardware functions still incomplete

- Arm transport-safety classification from measured joints/TCP: **TODO**.
- AGV odometry/motion/fault/emergency-stop integration in the chat adapter: **TODO/UNKNOWN until a verified provider is supplied**.
- Hardware-specific tolerances and settle times: **TODO**.
- Bounded cancellation of a still-blocking legacy ROS2 service call: **TODO**.
- Provider for `/dual_arm_planning`: **UNKNOWN external dependency in the delivered source**.

No hardware test or unobserved sensor capability is claimed.

## 9. Best next research question

The next study should measure the value of observation quality: as arm safety, AGV odometry, actuator readiness, and faults move from UNKNOWN to measured state, how do task success, repair precision, unnecessary stopping, and recovery latency change? This directly tests state grounding rather than merely comparing language models.

## 10. Three-minute interview explanation

“The original robot already had useful ROS2 and SDK skills, but its Agent layer behaved like ordinary function calling: the model chose tools, the dispatcher called them, and a successful call often became a successful task. That breaks down on a mobile manipulator because the base, arms, and lift share one body.

I built EmbodiedSkill-ROS as a separate SDK-neutral layer. Every skill declares parameters, body resources, preconditions, expected physical effects, timeout, and recovery. Before execution, a grounder projects the plan through the current robot state. If the base is asked to move while an arm is extended or unknown, the system inserts a verified retract action and repairs the order. During execution it observes before and after every command, so ‘ROS2 accepted the command’ is different from ‘the lift actually reached 300 mm.’ Failures use bounded retry, re-grounding, replanning, and only then safe stop.

Because I did not have hardware, I made the core independently runnable with deterministic fault injection and kept the JAKA code behind an adapter. In a 30-scenario benchmark, state grounding improved success from 60% to 83%, and recovery raised it to 96.7%, while eliminating invalid calls in the full configuration. The main limitation—and the next research step—is calibrating real arm safety envelopes and wiring verified AGV odometry and fault state.”
