# Remaining Failure Modes

Audit date: 2026-08-08. These limitations are intentionally not hidden and were
not repaired after the holdout was inspected.

| Scenario | Root cause | Type | Conservative? | Likely future fix |
|---|---|---|---|---|
| Fresh sensor spoof reports target reached while hidden actuator never moved | Runtime verifier and final goal check trust one fresh observation source; freshness is not correctness | Architectural | No; this is a false positive and unsafe execution in V2 | Redundant independent sensors, cross-modal consistency, actuator-current/encoder checks, sensor trust and fault isolation |
| Permanent UNKNOWN safety fact stops a physically feasible task | No safe evidence exists and no refresh action can establish it | Architectural policy | Yes | Add a validated observation provider or a domain-specific alternate plan that avoids the unknown dependency |
| Contradictory safety sources force stop | Core represents contradiction but cannot diagnose which source is faulty | Architectural | Yes | Sensor provenance, confidence/calibration, and explicit diagnostic actions |
| Capability mismatch rejects the only backend | Abstract contract forbids an unavoidable bilateral effect | Deployment-specific semantic incompatibility | Yes | Register a compatible backend or explicitly widen the contract only after hazard analysis |
| Impossible predicate and replan dead end stop without an explanatory unsat core | Bounded search returns summary counters, not a minimal proof of infeasibility | Implementation limitation | Yes | Return causal unsat cores and failed-achiever graphs |
| Generic backward repair can miss a valid path past depth/expansion/insertion bounds | Deliberate finite limits: depth 6, 64 expansions, 16 inserted steps | Architectural tradeoff | Yes | Adaptive budgets, heuristic search, or an external symbolic planner while preserving time bounds |
| Repair projection may not model harmful sequential side effects beyond declared effects | Correctness depends on complete and truthful contracts/backend semantics | Architectural assumption | Not necessarily | Contract validation, learned residual models, invariant checking after each repair action |
| Goal replanner optimizes for any declared achiever, not cost/risk/optimality | It is a bounded effect achiever, not a task-and-motion or optimal planner | Architectural scope | Usually | Costed search, resource/time models, motion-feasibility queries |
| Mock custom transition handlers receive hidden state | Required to implement simulated physics, but a malicious benchmark handler could encode shortcuts | Benchmark implementation risk | N/A | Keep handlers out of runtime modules, audit source boundaries, and add external simulator/oracle process isolation |
| Deterministic family replication gives no uncertainty interval | V2 is a coverage audit, not a sample from a deployment distribution | Evaluation limitation | N/A | Preregister distributions and run larger randomized/simulation/hardware studies with confidence intervals |
| ROS2/JAKA execution remains unverified | Current host is macOS arm64 without ROS2/colcon/JAKA hardware | Platform limitation | N/A | Execute the checked Ubuntu 22.04/Humble validation plan on robot or simulator |

## Strongest current interpretation

The Mock evidence supports bounded declarative grounding, multi-step repair,
epistemic gating, semantic capability rejection, verified local recovery, and
structurally distinct replanning on the tested symbolic contracts. It does not
support claims of sensor-fault tolerance, complete planning, general robot
robustness, ROS2 runtime correctness, or hardware safety.
