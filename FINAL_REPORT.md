# EmbodiedSkill-ROS Portfolio Release Report

Current portfolio release: `v0.3.0` — JAKA/Kargo Integration Layer

Frozen portfolio milestone: `v0.2.0` — ROS2 Runtime Portfolio Release

Current evidence date: 2026-08-08

## 1. Project position

EmbodiedSkill-ROS is a contract-driven execution layer between a high-level planner
and ROS2/robot backends. Its central engineering claim is deliberately narrow:
middleware command success is not sufficient evidence of physical task success.

The execution loop grounds plans in timestamped robot state, checks capability
semantics, executes commands, observes later state, verifies declared effects, and
selects bounded retry, repair, structural replanning, or stop behavior.

## 2. Starting point and contribution boundary

The separately delivered laboratory/reference system already contained JAKA/ROS2
skill wrappers, SDK/service interfaces, elementary arm/AGV/lift/head operations, and
a function-calling dispatcher. That workspace is not redistributed here.

This repository independently implements the planner-neutral reliability layer:

- declarative `SkillContract` parameters, predicates, effects, resources, timeouts,
  and recovery policies;
- epistemic `KNOWN`, `UNKNOWN`, `STALE`, and contradictory state;
- generic bounded effect-driven repair and goal-directed structural replanning;
- backend capability and unavoidable-side-effect preflight;
- separation of command receipt, post-command observation, verifier result, and
  hidden physical truth;
- deterministic fault injection and an independent benchmark oracle;
- fixed, procedural, adversarial V2, ablation, and frozen holdout evaluation; and
- a process-separated ROS2 Humble fake-robot runtime; and
- a JAKA/Kargo adapter, measured-state provider, capability mapper, ROS transport,
  contract suite, and exact-schema process-separated integration harness.

This is not a claim that the whole JAKA robot stack was built from scratch.

## 3. Current validation evidence

### Core and benchmark regression

- frozen reasoning core: 12 files / 1,385 LOC, all manifest hashes match;
- fixed 30-scenario Mock benchmark: 60.00% direct, 83.33% grounded, 93.33%
  grounded with recovery;
- 200 seeded transient-fault trials: 24.00% direct and 100.00% grounded with
  recovery, explicitly limited to one-shot faults matched by one retry;
- adversarial V2: 60/65 correct decisions, 25/25 feasible completion, 35/40
  correct safe handling, and 5/65 unsafe false positives; and
- frozen holdout: 72/78 correct decisions, 30/30 feasible completion, 42/48
  correct safe handling, and 6/78 unsafe false positives.

The older fixed-benchmark result that counted an equivalent plan as replanning is a
historical methodology error. The corrected current fixed result is 93.33%.

### Ubuntu 22.04 / ROS2 Humble baseline

- environment: Ubuntu 22.04.5, Python 3.10.12, ROS2 Humble, Fast DDS;
- `colcon build`: one `ros.ament_python` package passed;
- `colcon test`: 107 tests passed;
- `colcon test-result`: 107 tests, zero errors/failures/skips;
- runtime harness: R1–R15 all produced their expected decisions; and
- limitation probes: fresh sensor spoof and ROS2 TOCTOU both remain reproduced.

### JAKA/Kargo integration release

- five skill mappings: single-arm retract, map-X AGV motion, lift, head, and waist;
- eight ROS endpoints exercised: six Services and two asynchronous topics;
- 20 pure-Python integration contract tests passed;
- nine process-separated exact-schema integration scenarios passed;
- full extended environment: 128 tests, zero failures/errors/skips;
- exact external `jagv_interfaces`, `jaka_toolbox_interfaces`, and unmodified
  `jaka_toolbox` built on Humble; and
- all 12 frozen core hashes still match; frozen-core modification count is zero.

The runtime harness loads the generated types from the external packages and starts
a separate legacy-compatible stub. It does not launch the vendor-backed JAKA node,
initialize the SDK/controller, or command hardware.

The fake robot is a separate OS process. Commands cross a ROS action; physical state
is hidden in that process; observations return asynchronously by topic; and short
refresh/capability/stop operations use services.

## 4. Strongest runtime evidence

R3 is the central negative control. ROS accepts a goal and returns action status
`SUCCEEDED`, but the fake robot applies no target transition. A fresh post-command
topic sample reaches `OutcomeVerifier`, which rejects the effect and causes STOP.
Transport success and physical verification therefore remain distinct.

R10 shows generic contract-driven repair through ROS2: the effect search inserts
`retract_arm` before `move_agv` without branching on those names. R11 shows genuine
replanning: a permanently ineffective `primary_route` is replaced by
`alternate_route`, while a retry-only counterfactual remains unsuccessful.

R12 rejects a backend with unavoidable bilateral arm effects before command
transmission. R13 verifies timeout-driven ROS cancellation and bounded retry. R14
verifies backend-level external cancellation without a partial state transition.

## 5. Honest boundaries

- A fresh but false observation can fool both runtime verification and the final
  goal check. Fresh evidence is not necessarily truthful evidence.
- Freshness does not make check→dispatch atomic. The TOCTOU probe changes a safety
  fact after validation and still permits unsafe motion.
- STOP is a terminal policy result, not proof that every physical component stopped.
  Some early grounding/preflight STOP paths in the frozen executor do not transmit a
  backend stop request; R15 instead observes emergency stop already active and blocks
  the prohibited command.
- The ROS backend can cancel an action, but the frozen synchronous executor has no
  caller-facing cancellation API.
- The validation action is a test-only lifecycle envelope, not a production robot
  command schema.
- No collision safety, real-time guarantee, safety-rated interlock, sensor-fault
  tolerance, physics-simulation validity, or hardware safety is claimed.

## 6. JAKA/Kargo integration and simulation status

The external workspace and call graph are `STATICALLY-INSPECTED`; its interface
packages and unmodified toolbox are `ROS2-BUILD-VERIFIED`; the integration mappings
are `UNIT-VERIFIED`; and the separate exact-schema stub path is
`ROS2-RUNTIME-VERIFIED`. The vendor-backed node, SDK session, controller connection,
calibration, and hardware are `UNVERIFIED`.

The adapter does not use the legacy bilateral preset to satisfy a single-arm
contract. It exposes no motion capability without configured calibration and
whole-robot emergency-stop observability. Head effects remain sequential, Service
timeout cannot prove cancellation, and the only audited stop is AGV-only. Gazebo
and MoveIt2 simulation remain `UNVERIFIED`.

## 7. Three-minute interview explanation

“The starting robot system already exposed useful JAKA and ROS2 skills, but the
agent layer behaved like ordinary function calling: a tool returned success and that
could be treated as task success. I focused on the reliability gap between a
high-level plan and the physical state transition.

I built a separate execution layer where skills declare preconditions, body
resources, effects, timeout, and recovery policy. Plans are grounded against
timestamped epistemic state, backend side effects are checked before transmission,
and every command is followed by state observation and effect verification. Generic
effect search can insert preparation actions; persistent failure can trigger a
structurally different plan suffix.

On Ubuntu 22.04 with ROS2 Humble, I first validated the loop against a fake robot in
a separate process using topics, services, and actions. All 15 required scenarios
produced the expected decision. I then audited the existing JAKA/Kargo workspace and
implemented a separate skill/state/capability adapter. Nine process-separated
scenarios use its real generated ROS schemas, including a Service-success/no-motion
negative control. The external packages also build unmodified. I did not launch the
vendor node or claim hardware validation. Fresh sensor spoof, check→dispatch TOCTOU,
noncancellable Service timeout, and AGV-only stop remain explicit limitations.”

## 8. Evidence index

- `docs/VALIDATION_EVIDENCE.md`
- `docs/ROS2_RUNTIME_VALIDATION_REPORT.md`
- `ros2_validation_outputs/runtime_scenarios.json`
- `docs/BENCHMARK_V2_METHODOLOGY.md`
- `docs/JAKA_CAPABILITY_AUDIT.md`
- `docs/JAKA_KARGO_INTEGRATION_ANALYSIS.md`
- `docs/JAKA_KARGO_INTERFACE_MATRIX.md`
- `jaka_kargo_validation_outputs/integration_scenarios.json`
- `docs/REMAINING_FAILURE_MODES.md`
