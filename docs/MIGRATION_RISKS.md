# Migration Risks

| Risk | Evidence | New-project treatment | Remaining work |
|---|---|---|---|
| A named arm preset is assumed transport-safe | Legacy presets are motion targets, not safety classifications (`arm_skill.py:611-728`) | `JakaRobotBackend` returns `UNKNOWN` unless a transport pose is explicitly configured; state safety remains UNKNOWN without a validated provider | Calibrate joint/TCP envelopes and implement measured-pose classification |
| Service success is treated as physical success | Dispatcher formats Boolean return as completion (`robot_agent.py:706-770`) | Separate `CommandReceipt` from `VerificationResult` | Add hardware tolerances and settle windows per skill |
| AGV distance is open-loop | `agv_skill.py:411-459` | JAKA adapter reports position UNKNOWN unless an odometry callback/provider is supplied | Wire verified odometry/motion-state adapter |
| Cross-component collisions/resources are absent | No global registry/state/guard around `_dispatch()` | Registry resources, grounder, deterministic repair, runtime guard | Replace rule-level body envelopes with robot-specific collision data |
| Multi-tool calls are not a stable plan | Chat loop executes returned calls directly (`robot_agent.py:904-942`) | Typed `TaskPlan` and `PlanStep`, validation before execution | Connect a production LLM planner with constrained JSON/schema output |
| Failure recovery is delegated to free-form LLM behavior | Exceptions become tool-result strings (`robot_agent.py:897-900`) | Bounded retry, re-ground, replan, safe stop | Add parameter correction and alternative-skill policies |
| Legacy calls may block without a bounded service timeout | `_SyncServiceMixin._call` spins until completion (`real_sdk_skills.py:62-74`) | Mock timeouts are testable; elapsed timeout is detected after return | Use ROS2 future timeouts/cancellation in a deployment adapter |
| Interface provider may be external | `/dual_arm_planning` client exists, provider absent from included toolbox sources | Marked UNKNOWN and not used by minimum JAKA adapter | Document and version the external MoveIt provider |
| Sensitive deployment configuration | Legacy YAML holds network configuration | Never copied into docs/config/source | Use local environment/launch parameters and secret scanning |
| Simulation semantics can inflate results | Mock effects are deterministic | Fault injection plus independent final-state scoring | Validate fault distribution and constraints on hardware |

## Migration boundary

The new project does not replace the C++ SDK node or ROS2 interface packages. It wraps verified legacy skill objects behind `RobotBackend`. All planning, state projection, outcome verification, trace, and recovery logic is newly implemented and SDK-neutral.
