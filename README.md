**English** | [简体中文](README_zh-CN.md)

# EmbodiedSkill-ROS

**Contract-Driven Reliable Skill Execution for ROS2 Robots**

EmbodiedSkill-ROS addresses a practical robotics gap: a ROS action or SDK call can
return success while the intended physical state transition never occurs. It is a
planner-independent execution layer that grounds high-level plans in robot state,
checks backend semantics, executes through ROS2, observes the resulting state, and
selects bounded retry, repair, replanning, or stop behavior from explicit contracts.

```text
Planner / LLM  →  EmbodiedSkill-ROS  →  ROS2 / Robot Backend
                    GROUND
                      ↓
                   EXECUTE
                      ↓
                   OBSERVE
                      ↓
                   VERIFY
                      ↓
             RETRY / REPAIR / REPLAN / STOP
```

## Project at a glance

| | |
|---|---|
| Domain | ROS2, embodied robotics, reliable execution |
| Language | Python |
| Validated platform | Ubuntu 22.04.5, ROS2 Humble, Fast DDS |
| Architecture | Contract-driven execution layer between planner and backend |
| Evaluation | Fault injection, independent oracle, ablation, frozen holdout |
| Runtime | Process-separated core fake robot plus legacy-schema JAKA/Kargo integration stub |
| Deployment | External JAKA/Kargo packages build-verified; vendor-node runtime and hardware unverified |

## Key evidence

| Result | What it means |
|---:|---|
| **15 / 15** | required process-separated ROS2 runtime scenarios produced the expected decision |
| **9 / 9** | JAKA/Kargo adapter scenarios passed through a separate ROS2 process using the external schemas |
| **128** | tests passed in the extended ROS2 Humble environment (107 v0.2 + 20 integration contract + 1 integration runtime) |
| **5 skills / 8 ROS endpoints** | JAKA/Kargo integration coverage |
| **25 / 25** | feasible cases completed in the frozen adversarial V2 design suite |
| **60 / 65 (92.31%)** | correct decisions across all adversarial V2 trials |
| **12 files / 1,385 LOC** | frozen reasoning core protected by a hash manifest |
| **0 core modifications** | two new preparation skills generalized through declarative effects after core freeze |

These are deterministic artifact results, not deployment statistics. Seven of the
15 ROS2 scenarios complete their task; eight correctly stop and are not counted as
task successes.

| Validation boundary | Status |
|---|---|
| Pure-Python core and Mock experiments | `UNIT-VERIFIED` / `MOCK-VERIFIED` |
| Fixed, procedural, adversarial, ablation, and frozen holdout evaluation | `BENCHMARK-VERIFIED` |
| Process-separated fake-robot runtime on Ubuntu 22.04.5 / ROS2 Humble | `ROS2-RUNTIME-VERIFIED` |
| JAKA/Kargo source semantics | `STATICALLY-INSPECTED` |
| External interfaces and unmodified `jaka_toolbox` | `ROS2-BUILD-VERIFIED` |
| JAKA/Kargo adapter with exact-schema stub | `UNIT-VERIFIED` / `ROS2-RUNTIME-VERIFIED` |
| External JAKA/Kargo nodes with vendor SDK | `UNVERIFIED` |
| JAKA robot hardware | `UNVERIFIED` |
| Gazebo / MoveIt2 physics simulation | `UNVERIFIED` |

The v0.2 core result remains 107/107. The larger 128/128 count requires the two
external interface packages to be built and sourced; without them, the integration
runtime test skips explicitly. Demo video is pending a real recording. No simulator
run or hardware video is claimed.

## 30-second architecture

```mermaid
flowchart TD
    P["High-Level Planner / LLM"] --> TP["TaskPlan"]
    TP --> SC["Declarative SkillContract"]
    SC --> ES["Epistemic Robot State<br/>KNOWN / UNKNOWN / STALE"]
    ES --> GC["Grounding + Capability Check"]
    GC --> RR["Generic Repair / Replan"]
    RR --> RB["ROS2 Backend"]
    RB --> PO["Physical Observation"]
    PO --> OV["Outcome Verification"]
    OV --> D["Retry / Repair / Replan / Stop"]
    D -->|bounded continuation| GC
```

Planning and execution reliability are deliberately separated. A deterministic
planner, an LLM adapter, or another planning system can produce `TaskPlan`; the
execution layer remains responsible for state grounding and evidence-based outcome
verification.

## Middleware success ≠ physical success

The clearest negative control is ROS2 runtime scenario R3:

```text
ROS Action Goal
      ↓
   ACCEPTED
      ↓
Action Result: SUCCEEDED
      ↓
Fake Robot Hidden State: NO TARGET TRANSITION
      ↓
Fresh ROS Topic Observation
      ↓
OutcomeVerifier: FAILURE
      ↓
     STOP
```

EmbodiedSkill-ROS does not treat ROS Action `SUCCEEDED` as evidence that the
contracted physical effect occurred. The action result and post-command observation
remain separate trace records. See the
[runtime report](docs/ROS2_RUNTIME_VALIDATION_REPORT.md) and
[machine-readable trace](ros2_validation_outputs/runtime_scenarios.json).

## Starting point & my contributions

### Existing laboratory / reference system

The starting point provided:

- JAKA / ROS2 robot skill wrappers and SDK/service interfaces;
- elementary arm, AGV, lift, and head skills; and
- a function-calling dispatcher/reference agent.

That separately delivered reference workspace is not redistributed in this
repository. EmbodiedSkill-ROS does not claim that the JAKA robot system or its
elementary hardware skills were built from scratch here.

### Core redesign — my work

Based on those existing skill/backend interfaces, I designed and implemented a
separate reliable embodied skill execution layer:

- declarative `SkillContract` schemas, predicates, resources, effects, timeouts,
  and recovery policies;
- epistemic `KNOWN`, `UNKNOWN`, `STALE`, and contradictory robot state;
- generic effect-driven preparation repair and structural goal-directed replanning;
- backend capability and unavoidable-side-effect preflight;
- separation of command receipt, observation, verification, and hidden truth;
- an independent hidden-state benchmark oracle and deterministic fault injection;
- fixed, procedural, adversarial V2, A–F ablation, and frozen holdout evaluation;
- a process-separated ROS2 Humble runtime using topics, services, and actions; and
- a JAKA capability/semantic-scope audit with explicit failure boundaries.

### JAKA/Kargo system integration — my work

For v0.3, I added the boundary that reconnects the unchanged reasoning core to the
laboratory stack:

- a `JakaKargoBackend` that normalizes heterogeneous service semantics;
- a measured-state provider that maps feedback to `KNOWN`, `UNKNOWN`, and `STALE`;
- a capability mapper for endpoint availability, component scope, unavoidable side
  effects, timeout, cancellation, observation, and stop scope;
- lazy ROS2 transport imports, a motion-disabled read-only deployment probe, and an
  external-dependency build boundary;
- 20 integration contract tests and nine process-separated ROS2 scenarios using
  the real generated legacy interface types; and
- an IP/provenance audit that keeps the vendor SDK, robot assets, private network
  configuration, and original workspace outside this repository.

The laboratory stack still owns low-level actuation. EmbodiedSkill-ROS owns the
execution semantics and the integration boundary.

## Core design

### Declarative contracts and epistemic state

Each skill declares what it requires and what it is expected to change. The executor
does not silently interpret unavailable safety state as safe: evidence can be known,
unknown, stale, or contradictory, and contracts can require bounded active refresh.

### Bounded generic repair, not a general planner

Repair uses declarative effect search rather than branching on concrete skill names.
The frozen-core extension experiment begins with only `transport_payload` planned:

```text
deploy_stabilizer
→ secure_payload
→ transport_payload
```

The two preparation skills were added after the reasoning core was frozen. The same
bounded search inserted them with **zero changes to the 12 frozen core files**. This
is evidence for contract-driven extensibility, not a claim of general task-and-motion
planning or optimal search.

### Structural replanning

Replanning must change the failed suffix. ROS2 scenario R11 makes `primary_route`
permanently ineffective; the replanner selects `alternate_route`, while a retry-only
counterfactual sends the primary action three times and still fails.

### Backend capability contracts

The JAKA audit exposes a concrete semantic mismatch:

```text
Abstract contract: retract LEFT arm only
Legacy JAKA preset: potentially moves BOTH arms
```

Because abstract scope is narrower than the unavoidable backend effect, capability
preflight rejects the command before transmission. The source semantics are
`STATICALLY-INSPECTED`, and this rejection is `UNIT-VERIFIED` plus
`ROS2-RUNTIME-VERIFIED` against a schema-compatible stub. It is not vendor-node or
hardware evidence.

## ROS2 runtime validation

The validated runtime path is:

```text
EmbodiedSkill Core
        ↓
ROS2 Action
        ↓
Independent Fake Robot Process
        ↓
Hidden Physical State
        ↓
ROS2 Topic Observation
        ↓
Outcome Verifier
```

The fake robot is a separate OS process, not a direct Python backend call and not a
physics simulator. Long-running and cancellable commands use a ROS action; state is
published asynchronously; short reset, refresh, capability, and stop operations use
services. The validation action uses a standard action as a test-only lifecycle
envelope rather than claiming a production robot command schema.

R1–R15 cover nominal execution, command rejection, accepted/no-motion, delayed
observation, stale and unknown safety evidence, successful and failed refresh,
transient recovery, generic repair, structural replanning, capability mismatch,
timeout, cancellation, and terminal stop behavior.

## JAKA/Kargo integration

```text
EmbodiedSkill-ROS Core
        ↓
JakaKargoBackend
        ↓
State Provider + Capability Mapper
        ↓
JakaKargoRos2Transport
        ↓
External JAKA/Kargo ROS2 Interfaces
        ↓
Existing jaka_toolbox / JAGV Nodes
        ↓
Vendor SDK / Robot
```

The integration maps five skills—single-arm retract, AGV map-X motion, lift, head,
and waist—onto six Services and two asynchronous AGV topics. It observes arm joints,
four external axes, odometry, and AGV motion/fault state. Missing or uncalibrated
signals remain `UNKNOWN`; `PoseQuery` success does not default to arm readiness, and
a successful Service response never fabricates an effect.

For AGV motion, the adapter waits for post-command odometry and motion-state
revisions rather than immediately reusing its pre-command topic cache.

J2 repeats the central negative control through the actual external message/service
schemas: `/joint_move_ext` returns success, the separate stub does not move the lift,
the later `/query_status_ext` observation remains unchanged, and verification stops.
The harness also verifies stale/unknown handling, bilateral semantic rejection,
service timeout honesty, arm feedback, odometry, and head/waist translation.

The original interface packages and unmodified `jaka_toolbox` compile on Humble.
The vendor-backed node was deliberately not launched because construction initiates
controller/SDK setup. No hardware command was sent.

## Evaluation summary

### Frozen adversarial V2 and holdout

| Evaluation | Correct decisions | Feasible completion | Correct safe handling | Unsafe / false positive |
|---|---:|---:|---:|---:|
| Designed V2 (65) | 60/65 (92.31%) | 25/25 | 35/40 | 5/65 |
| Frozen holdout (78) | 72/78 | 30/30 | 42/48 | 6/78 |

The five design-suite false positives are the intentionally preserved
`fresh_sensor_spoof` family. Metric definitions, family results, coupling controls,
and A–F/removal ablations are in the
[V2 methodology](docs/BENCHMARK_V2_METHODOLOGY.md).

### Corrected fixed benchmark

The smaller 30-scenario deterministic Mock benchmark remains useful as an engineering
regression, not as the headline evidence:

| Configuration | Task success | Invalid skill calls |
|---|---:|---:|
| Direct function calling | 60.00% | 14.55% |
| State-grounded | 83.33% | 0.00% |
| State-grounded + recovery | 93.33% | 0.00% |

Historical methodology corrections are documented outside this portfolio summary.

## Known failure boundaries

- **Fresh evidence is not truthful evidence.** A fresh false sensor observation can
  fool outcome verification; the independent oracle records the false positive.
- **Freshness is not an atomic safety guarantee.** The ROS2 TOCTOU probe observes a
  safe state, then changes the world before dispatch; unsafe motion still occurs.
- **STOP is a policy decision, not a universal physical-stop proof.** Recovery
  exhaustion paths call the backend stop operation, but some early grounding/preflight
  STOP exits in the frozen executor do not transmit that operation. R15 blocks the
  prohibited command while emergency stop is already observed active.
- The synchronous executor has no caller-facing cancellation API, although the ROS2
  backend can cancel actions and R14 verifies coherent adapter state afterward.
- No collision safety, real-time guarantee, safety-rated interlock, sensor-fault
  tolerance, simulation validity, or hardware safety is claimed.

The complete failure ledger is in
[docs/REMAINING_FAILURE_MODES.md](docs/REMAINING_FAILURE_MODES.md).

## JAKA status

`JakaKargoBackend` uses an optional ROS2 transport and never imports vendor packages
from the core path. Motion capabilities are withheld unless motion is explicitly
enabled, endpoints are discovered, whole-robot emergency-stop observability is
asserted, and required arm targets are calibrated. The audited AGV stop remains
`AGV_ONLY`, Service timeout does not claim physical cancellation, and bilateral
preset effects cannot silently satisfy a single-arm contract.

See the [integration analysis](docs/JAKA_KARGO_INTEGRATION_ANALYSIS.md) and
[interface matrix](docs/JAKA_KARGO_INTERFACE_MATRIX.md). External node runtime,
SDK/controller connection, calibration, whole-robot stopping, supervised hardware,
and physics simulation remain `UNVERIFIED`.

## Quick reproduction

The pure-Python core requires Python 3.9+ and has no mandatory third-party runtime
dependency:

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

Without ROS2, ROS-marked tests skip explicitly. On Ubuntu 22.04 with ROS2 Humble:

```bash
source /opt/ros/humble/setup.bash

colcon build --symlink-install --packages-select embodied_skill_ros
source install/setup.bash

ROS_LOG_DIR=/tmp/embodied_skill_ros_logs ROS_LOCALHOST_ONLY=1 \
  colcon test --packages-select embodied_skill_ros

colcon test-result --all --verbose
```

Expected v0.2 baseline: **107 tests, zero errors, zero failures, zero skips**.

Run the process-separated scenario harness:

```bash
ROS_LOG_DIR=/tmp/embodied_skill_ros_logs ROS_LOCALHOST_ONLY=1 \
  ros2 run embodied_skill_ros validate_runtime \
  --output ros2_validation_outputs/runtime_scenarios.json
```

Expected summary: **15/15 required scenarios pass** and both unsafe limitation
probes—fresh sensor spoof and TOCTOU—remain reproduced.

For JAKA/Kargo integration, keep the separately delivered workspace outside this
repository. Build and source `jagv_interfaces` and `jaka_toolbox_interfaces`, then:

```bash
source /opt/ros/humble/setup.bash
source /path/to/kargo_ws_delivery_20260521/install/setup.bash
source install/setup.bash

ROS_LOG_DIR=/tmp/embodied_skill_jaka_logs ROS_LOCALHOST_ONLY=1 \
  ros2 run embodied_skill_ros validate_jaka_kargo \
  --output jaka_kargo_validation_outputs/integration_scenarios.json
```

Expected integration result: **9/9 scenarios pass**. With the external types
available, the complete environment reports **128/128 tests**. This harness starts
a separate legacy-compatible stub; it does not load the vendor SDK or move hardware.

## Documentation map

- [Validation evidence ledger](docs/VALIDATION_EVIDENCE.md)
- [ROS2 runtime report](docs/ROS2_RUNTIME_VALIDATION_REPORT.md)
- [Machine-readable ROS2 traces](ros2_validation_outputs/README.md)
- [Adversarial V2 methodology](docs/BENCHMARK_V2_METHODOLOGY.md)
- [Frozen-core reproducibility](docs/STANDALONE_REPRODUCIBILITY.md)
- [JAKA capability audit](docs/JAKA_CAPABILITY_AUDIT.md)
- [JAKA/Kargo integration analysis](docs/JAKA_KARGO_INTEGRATION_ANALYSIS.md)
- [JAKA/Kargo interface matrix](docs/JAKA_KARGO_INTERFACE_MATRIX.md)
- [JAKA/Kargo runtime evidence](jaka_kargo_validation_outputs/README.md)
- [Architecture details](docs/NEW_ARCHITECTURE.md)
- [Literature and novelty boundaries](docs/LITERATURE_AND_NOVELTY.md)
- [Remaining failure modes](docs/REMAINING_FAILURE_MODES.md)
- [Current project report](FINAL_REPORT.md)

## Roadmap

Portfolio v0.2.0 remains the frozen ROS2-core milestone. v0.3.0 releases the
JAKA/Kargo integration layer without changing any frozen reasoning file. A reviewed
deployment configuration, vendor-backed node runtime, and supervised low-risk
hardware validation remain future deployment gates; v0.3.0 is not a hardware
release.
An optional research track may study
version/evidence-guarded command admission for ROS2 check→dispatch races; it is not
required for the current project claims.

See [ROADMAP.md](ROADMAP.md) for the status-separated roadmap.
