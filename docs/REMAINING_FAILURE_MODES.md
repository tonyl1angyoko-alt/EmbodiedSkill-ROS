# Remaining Failure Modes

Audit date: 2026-08-08. These limitations are intentionally not hidden and were
not repaired after the holdout was inspected.

| Scenario | Root cause | Type | Conservative? | Likely future fix |
|---|---|---|---|---|
| Fresh sensor spoof reports target reached while hidden actuator never moved | Runtime verifier and final goal check trust one fresh observation source; freshness is not correctness | Architectural | No; this is a false positive and unsafe execution in V2 | Redundant independent sensors, cross-modal consistency, actuator-current/encoder checks, sensor trust and fault isolation |
| Fresh safety observation changes after guard and before ROS action transition | Freshness bounds age but supplies no atomic lease/interlock across asynchronous middleware | Architectural | No; ROS L1 executes AGV motion after arm safety becomes false | Controller-side invariant/interlock or optional version/evidence-guarded command admission |
| Permanent UNKNOWN safety fact stops a physically feasible task | No safe evidence exists and no refresh action can establish it | Architectural policy | Yes | Add a validated observation provider or a domain-specific alternate plan that avoids the unknown dependency |
| Contradictory safety sources force stop | Core represents contradiction but cannot diagnose which source is faulty | Architectural | Yes | Sensor provenance, confidence/calibration, and explicit diagnostic actions |
| Capability mismatch rejects the only backend | Abstract contract forbids an unavoidable bilateral effect | Deployment-specific semantic incompatibility | Yes | Register a compatible backend or explicitly widen the contract only after hazard analysis |
| Impossible predicate and replan dead end stop without an explanatory unsat core | Bounded search returns summary counters, not a minimal proof of infeasibility | Implementation limitation | Yes | Return causal unsat cores and failed-achiever graphs |
| Generic backward repair can miss a valid path past depth/expansion/insertion bounds | Deliberate finite limits: depth 6, 64 expansions, 16 inserted steps | Architectural tradeoff | Yes | Adaptive budgets, heuristic search, or an external symbolic planner while preserving time bounds |
| Repair projection may not model harmful sequential side effects beyond declared effects | Correctness depends on complete and truthful contracts/backend semantics | Architectural assumption | Not necessarily | Contract validation, learned residual models, invariant checking after each repair action |
| Goal replanner optimizes for any declared achiever, not cost/risk/optimality | It is a bounded effect achiever, not a task-and-motion or optimal planner | Architectural scope | Usually | Costed search, resource/time models, motion-feasibility queries |
| Mock custom transition handlers receive hidden state | Required to implement simulated physics, but a malicious benchmark handler could encode shortcuts | Benchmark implementation risk | N/A | Keep handlers out of runtime modules, audit source boundaries, and add external simulator/oracle process isolation |
| Deterministic family replication gives no uncertainty interval | V2 is a coverage audit, not a sample from a deployment distribution | Evaluation limitation | N/A | Preregister distributions and run larger randomized/simulation/hardware studies with confidence intervals |
| Caller-facing cancellation is absent from `SkillExecutor` | ROS backend can cancel an action, but the frozen synchronous executor exposes no application cancellation API | Integration limitation | Usually; adapter cancellation preserves state in R14 | Add an explicit cancellation token/API without moving recovery logic into ROS modules |
| Early grounding/preflight STOP may not call the backend stop operation | Several frozen executor exits return the terminal STOP decision before the traced execution/recovery path is established | Core/interface limitation | It blocks the prohibited command, but does not prove stop actuation | Unify STOP reporting and stop-attempt evidence in a future post-freeze core revision with dedicated tests |
| Validation action uses a correlation envelope | Standard Fibonacci action supplies lifecycle/cancel semantics but is not a production typed robot command | Test-harness limitation | N/A | Define deployment-specific typed actions in a separate interface package |
| JAKA vendor-node and hardware execution remain unverified | External interfaces/toolbox build and exact-schema stub pass, but the SDK-initializing node was not launched and no hardware is connected | Platform/deployment limitation | N/A | Reviewed private configuration, read-only supervised observation, calibration, then bounded hardware trials |
| Legacy Service client timeout cannot cancel physical motion | Service futures can time out locally while the mutually-exclusive server callback or SDK motion continues | Integration limitation | Not necessarily | Cancellable Action wrapper or controller-side cancel/stop with measured acknowledgement |
| Audited stop is AGV-only | `/motion_state_control` code 3 does not stop or confirm arms/lift/head/waist | Deployment semantic gap | Conservative because whole-robot stop is not advertised | Define and verify a whole-robot stop sequence/interlock under supervision |
| Whole-robot safety state is not established | JAGV `MotionState` exposes AGV E-stop/fault bits only | Observation-scope limitation | Yes; motion capabilities are withheld by default | Integrate a scope-qualified whole-robot safety signal without promoting AGV-only evidence |

## Strongest current interpretation

The Mock evidence plus process-separated Humble evidence supports bounded
declarative grounding, multi-step repair, epistemic gating, semantic capability
rejection, verified local recovery, and structurally distinct replanning on the
tested symbolic contracts. It does not support claims of sensor-fault tolerance,
atomic safety preconditions, complete planning, general robot robustness,
simulation validity, or hardware safety.
