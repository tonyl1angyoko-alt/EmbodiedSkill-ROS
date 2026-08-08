# ROS2 Humble Runtime Validation Report

Historical scope: this report is the v0.2 frozen-core fake-runtime validation record.
For current JAKA/Kargo integration evidence, see
`JAKA_KARGO_INTEGRATION_ANALYSIS.md`, `JAKA_KARGO_INTERFACE_MATRIX.md`, and
`../jaka_kargo_validation_outputs/README.md`. The historical environment statements
below are retained rather than rewritten as though the external stack had already
been built during v0.2.

Validation date: 2026-08-08

Base milestone: `7fdf9255a454f375dbc1c1328895c6e71812bdb7`

Validation branch: `codex/ros2-humble-validation`

## Skeptical outcome

The frozen abstraction survives process-separated ROS2 Humble integration for the
15 required deterministic fake-robot scenarios. This result is stronger than an
import or build check: commands cross a ROS action, physical state changes in a
separate process, and verification consumes a later topic observation. Generic
repair, retry, and structural replanning continue to be selected by the frozen
core.

The run also demonstrates two unsafe limitations. A fresh observation is not an
atomic lease on the world, so a safety fact can change after the runtime guard and
before motion. A fresh but false single-source observation still fools the
verifier. The runtime evidence therefore does not establish collision safety,
sensor trustworthiness, real-time safety, simulation validity, or hardware safety.

## Environment

| Item | Observed value |
|---|---|
| Host | Ubuntu 22.04.5 LTS (Jammy) |
| Kernel | Linux 6.8.0-136-generic, x86_64/amd64 |
| Python | 3.10.12, `/usr/bin/python3`, no virtualenv/Conda |
| ROS | ROS2 Humble, `rclpy` 3.3.21 |
| RMW | Fast DDS, `rmw_fastrtps_cpp` 6.2.10 |
| colcon | core 0.21.0, common extensions 0.3.0 |
| pytest | Ubuntu package 6.2.5 |
| MoveIt2 | not installed/discoverable |
| Gazebo / ros-gz | not installed/discoverable |
| JAKA runtime | source and x86-64 vendor `.so` found in a sibling delivery; runtime packages/services not built, installed, or active |

`ros2 doctor --report` completed with host-level network access. It reported Humble
and Fast DDS correctly, no active topics at audit time, and several installed ROS
packages one patch behind the currently advertised repository versions. No ROS or
simulator packages were installed for this validation.

## Runtime boundary

The fake robot is a separate OS process. It owns hidden physical state and exposes:

| Semantic role | ROS interface |
|---|---|
| asynchronous observations | `/embodied_skill/state`, `std_msgs/msg/String` |
| long-running/cancellable command lifecycle | `/embodied_skill/execute_skill`, ROS action |
| scenario reset and active refresh | standard parameter services (`rcl_interfaces`) |
| capabilities and safe stop | `std_srvs/srv/Trigger` services |
| independent test oracle | test-only service; never called by the executor/verifier |

The validation action uses `action_tutorials_interfaces/action/Fibonacci` only as
a correlation/lifecycle envelope, with the typed JSON command installed through a
standard parameter transaction. This avoids adding a custom interface package to
the frozen artifact, but it is not proposed as a production robot action schema.

The backend waits for an observation sequence newer than the pre-command sample.
It does not update epistemic state from an action result. Thus action success and
physical verification remain separate.

## Required scenarios

| ID | Runtime result | Task completed | Correct safe handling | Key evidence |
|---|---|---:|---:|---|
| R1 nominal | pass | yes | n/a | action succeeded, new topic sample verified target |
| R2 command rejection | pass | no | yes | action goal rejected; hidden state unchanged |
| R3 accepted/no motion | pass | no | yes | goal accepted and action succeeded; verifier rejected unchanged observation |
| R4 delayed observation | pass | yes | n/a | backend waited for a later sequence before verification |
| R5 STALE | pass | no | yes | STALE detected, refresh attempted, motion blocked when refresh failed |
| R6 UNKNOWN | pass | no | yes | UNKNOWN was not interpreted as safe; no command sent |
| R7 refresh succeeds | pass | yes | n/a | OBSERVE preceded action; refreshed fact became KNOWN |
| R8 refresh fails | pass | no | yes | evidence remained unavailable; no guessed execution |
| R9 transient actuator | pass | yes | n/a | first accepted action had no effect; `LOCAL_RETRY` (classification: RETRY) succeeded; no REPLAN |
| R10 generic repair | pass | yes | n/a | frozen effect search inserted `retract_arm -> move_agv` |
| R11 structural replan | pass | yes | n/a | `primary_route` failed persistently; suffix became `alternate_route` |
| R12 capability mismatch | pass | no | yes | bilateral arm side effect rejected before action transmission |
| R13 timeout | pass | yes | n/a | action timeout caused ROS cancellation and bounded RETRY; second attempt succeeded |
| R14 cancellation | pass | no | yes | external action cancel accepted; no partial transition; safe stop invoked |
| R15 safe stop | pass | no | yes | emergency-stop preflight returned STOP; prohibited AGV action was never sent |

All 15 are correct decisions. Seven complete their intended task (R1, R4, R7,
R9, R10, R11, and R13); eight correctly stop (R2, R3, R5, R6, R8, R12, R14,
and R15). The STOP-expected cases are recorded as correct safe handling, not task success.
The machine-readable evidence is the authoritative source for per-case scoring.

## Accepted transport is not physical success

R3 is the central negative control. ROS accepted the action goal and returned
terminal `SUCCEEDED`. The fake robot deliberately applied no transition and then
published a fresh state sample. `OutcomeVerifier` compared that observation with
the contract effect, rejected the outcome, and the executor selected STOP. The
independent hidden-state service confirmed that the target remained false.

## Generic repair and replanning

R10 begins with `left_arm_safe=False` and a plan containing only `move_agv`.
The unchanged `PlanRepairer` searches registered effects and inserts
`retract_arm(left)`; both commands then cross the ROS action boundary and the final
topic observation verifies AGV displacement.

R11 makes `primary_route` permanently ineffective. After observed failure, the
unchanged `GoalDirectedReplanner` blocks that skill and produces the structurally
different suffix `alternate_route`. A separately executed retry-only
counterfactual sends the primary action three times and never reaches `arrived`.

## Asynchronous-state findings

R4 shows the adapter can prevent immediate reasoning over the pre-command sample
by requiring an observation with a newer sequence. This handles bounded reporting
delay but is not a safety transaction.

The TOCTOU limitation scenario starts from a fresh `left_arm_safe=True` sample.
After the runtime guard, the fake world changes it to false before the AGV
transition. The action and goal verification still succeed because the declared
effect concerns AGV position. Freshness alone is therefore insufficient to ensure
that a precondition remains true during command execution. No new lease/interlock
subsystem was added post hoc; this remains a paper limitation.

The fresh-sensor-spoof scenario also reproduces over ROS. A fresh target-valued
observation makes the executor report success while the independent physical
oracle remains at the old value.

## Cancellation limitation

The ROS backend supports action cancellation and R14 verifies coherent state after
cancellation. The frozen `SkillExecutor` has no caller-facing asynchronous cancel
API; the validation invokes cancellation on the backend while the executor runs in
a worker thread. Consequently adapter-level cancellation is
`ROS2-RUNTIME-VERIFIED`, while end-to-end application cancellation remains only
partially integrated.

## Terminal STOP limitation

STOP denotes the executor's terminal policy decision; it is not a safety-rated
physical-state certificate. Recovery-exhaustion paths invoke the backend stop
operation, as shown in R3, R11's retry-only counterfactual, and R14. Some earlier
grounding/preflight exits in the frozen executor return STOP without transmitting
`backend.stop()`. R15 is one such path: emergency stop is already observed active,
the prohibited AGV action is blocked, and no additional stop service call is claimed.
An older experimental branch contains a possible funneling fix, but it was not
cherry-picked because it modifies the frozen `SkillExecutor` and has not been
revalidated against the frozen benchmark methodology and ROS2 evidence.

## Build and test evidence

- `colcon build --symlink-install --packages-select embodied_skill_ros`: passed.
- installed package discovery and three executables: passed.
- live launch graph and clean Ctrl-C shutdown: passed.
- `colcon test`: 107 passed.
- `colcon test-result --all --verbose`: 107 tests, zero errors/failures/skips.
- ROS-enabled `unittest discover`: 107 passed.
- all 15 process-separated scenarios and two limitation probes: reproduced.
- bytecode compilation, freeze-manifest verification, optional-import sanity,
  sensitive-pattern scan, and `git diff --check`: passed.

The original package was initially misidentified by colcon as generic `(python)`
because `package.xml` contained an invalid `@localhost` maintainer email. The build
command returned success but the package was absent from `AMENT_PREFIX_PATH`.
Correcting the package metadata made colcon identify `(ros.ament_python)`. Adding
`tests_require=["pytest"]` was also necessary: otherwise `colcon test` reported a
misleading success with zero discovered tests.

Flake8 4.0.1 was already installed and was run. It is not a clean project gate:
the repository has existing 79-column/W503 style findings plus six non-style
findings, including a deferred-annotation `PlanStep` warning in the frozen
grounder. The new Linux runtime files have no remaining unused-import or
undefined-name findings after three unused imports were removed. The frozen core was not changed
to make this optional lint run green. `setup.py check` passed with warnings for
pre-existing absent URL/author metadata.

## Research-core modifications

None of the 12 files in `benchmarks/core_freeze_manifest.json` changed. The
manifest remains 12 files / 1,385 lines with all hashes matching. Runtime work is
confined to `embodied_skill_ros/ros2`, package metadata, tests, documentation, and
the non-frozen JAKA adapter honesty fix.

## Publication assessment

Materially stronger claims:

- the core/backend boundary works across real ROS processes rather than direct
  Python calls;
- command acceptance remains distinct from measured outcome under ROS actions;
- UNKNOWN/STALE refresh gating, declarative repair, bounded retry, structural
  replan, capability preflight, timeout, and adapter cancellation have executable
  Humble evidence;
- asynchronous delayed observations can be handled with a post-command sequence
  barrier.

Claims an ICRA/IROS reviewer could still reject:

- general robot robustness or safety: no physics, collision model, redundant
  sensing, real-time analysis, or hardware trials;
- novelty over PlanSys2/behavior trees/classical planning: no matched baseline;
- statistical generalization: scenarios are deterministic and authored with the
  harness;
- sensor-fault tolerance: the fresh-spoof false positive remains;
- atomic safety preconditions: the TOCTOU scenario is unsafe;
- production ROS API maturity: the validation action envelope is test-only;
- JAKA deployment safety at this milestone: adapter mappings were static only.
  v0.3 later build-verified the external packages and runtime-verified the new
  adapter against an exact-schema stub, but whole-robot stop, calibrated deployment,
  vendor-node runtime, and supervised execution remain unverified.
