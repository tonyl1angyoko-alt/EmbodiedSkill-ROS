# Final Report

## 1. What the original system is

The original project is a Qwen function-calling chat agent connected to JAKA mobile-manipulator skills. A monolithic dispatcher calls lift, waist, head, arm, MoveIt, and AGV wrappers. Arm/external axes primarily use ROS2 services backed by the JAKA SDK; elementary AGV motion publishes timed `cmd_vel`. The model can chain multiple calls, but the system has no explicit structured plan, unified body state, cross-component resource model, or generic physical-outcome verifier.

## 2. What the new project adds

Evidence labels: `UNIT-VERIFIED`, `MOCK-VERIFIED`, and `BENCHMARK-VERIFIED` as
itemized in `docs/VALIDATION_EVIDENCE.md`.

EmbodiedSkill-ROS adds:

- typed epistemic `RobotState` with KNOWN/UNKNOWN/STALE evidence;
- declarative skill contracts with schemas, resources, preconditions, invertible effects, timeout, and enforced recovery policy;
- state projection, backend capability checks, generic effect-driven repair, and goal-directed replanning;
- closed-loop `execute → observe → verify → update` execution;
- bounded retry, re-grounding, one bounded replan, and safe stop;
- full per-attempt execution traces;
- a hidden Mock physical world, configurable observations, and deterministic fault injection;
- an independent physical oracle, four demos, 102 automated tests, a fixed 30-scenario
  A/B/C/D benchmark, 200 seeded transient-fault trials, and frozen-core V2 adversarial,
  ablation, and post-freeze holdout evaluations.

## 3. What was genuinely reimplemented

All research-core logic under `embodied_skill_ros/` is independent of ROS2 and the
original SDK. The only `rclpy` import is lazy and confined to the optional ROS2 Mock
bridge entry point.

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

The current standard-library suite was run on macOS from the repository root with:

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

Final result: **102 tests discovered: 100 passed and 2 ROS2 tests skipped with the stated
Humble-unavailable reason**. Coverage adds stale evidence, capability rejection,
contradictory evidence, non-finite/adversarial parameters, structural oracle isolation,
real sensor-spoof false positives, multi-level generic new-skill repair, three persistent
replanning counterfactuals, recovery-policy enforcement, 128 randomized arm-state trials,
benchmark integrity, and optional ROS import isolation.

`colcon` was not installed in the execution environment, so a ROS2 build was not claimed. Python compilation/import, four demos, the test suite, and benchmark were executed in the Mock environment.

`ruff`, `mypy`, `pytest`, and `pyright` were not installed on the Mac and were not added
to the host. Bytecode compilation passed with its cache redirected to `/tmp`.

## 7. Benchmark design and result

The checked-in benchmark contains exactly 30 required scenarios and reports all nine requested metrics. Task success is independently scored from final physical state.

Evidence label: `BENCHMARK-VERIFIED`. The fixed 30-scenario results are 60.00%
direct/structured, 83.33% grounded, and 93.33% grounded plus recovery. The previously
reported 96.67% counted an equivalent-plan retry as a replan; structural replan
validation correctly turns that scenario into a stop. The independent
oracle reads hidden physical truth rather than observed state. The separate 200-trial
procedural experiment reports 24.00% direct success with a 23.00% false-positive rate,
versus 100.00% for grounded recovery, but every fault is a one-shot transient matched
by one allowed retry. It is not evidence for unrecoverable cases.

The 65-trial frozen-core V2 design suite reports 38.46% overall task completion,
100% feasible-task completion, 87.50% correct safe stops, 92.31% overall correct
decisions, and 7.69% unsafe executions. The 78-trial post-freeze holdout has the same
balanced-family rates. The remaining failure is deliberate evidence, not hidden noise:
a fresh target-valued sensor spoof fools both runtime verification and the final goal
check while the independent hidden-world oracle remains false. Exact definitions,
family results, A-F ablations, and coupling analysis are in
`docs/BENCHMARK_V2_METHODOLOGY.md`.

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
