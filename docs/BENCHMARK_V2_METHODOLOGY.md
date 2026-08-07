# Benchmark V2 Methodology and Hostile Audit

Validation date: 2026-08-08. Evidence is deterministic Python/Mock evidence on
macOS, not ROS2, simulation, or hardware evidence.

## What the old 200-trial `100%` means

The exact reproduction command was:

```bash
PYTHONPATH=. python3 benchmarks/run_procedural_benchmark.py --seed 20260808 --trials 200
```

The generated mix was 48 no-fault, 46 one-shot physical-failure, 60 one-shot
command-failure, and 46 one-shot timeout trials. Every task was theoretically
possible. Every injected fault occupied a one-element queue, while FULL had one
local retry; therefore the second command always saw an exhausted queue. There
were no permanent failures, impossible goals, sensor faults, capability
mismatches, resource contradictions, or blocked-path dead ends.

Consequently the old FULL `100%` was **100% hidden-world task completion on a
transient-only synthetic benchmark**. It did not mean 100% correct behavior over
recoverable and unrecoverable cases, and it provided no evidence about safe
failure handling. The generator was independent of the fixed JSON fixture, but
it was not a scientific holdout and is no longer described as one.

### Couplings found in the old generator

| Coupling | Evidence | Consequence |
|---|---|---|
| Only three built-in effects | `set_head`, `set_lift`, `move_agv` templates | No unseen skill composition |
| Faults always expire | One queued `FaultEvent` per faulty trial | Permanent failures are absent |
| Retry budget matches fault duration | Queue length 1, `max_retries=1` | FULL is guaranteed a fault-free second attempt |
| Initial state is fully known and safe | One fixed `initial_state()` | No UNKNOWN, STALE, or contradictory evidence |
| Every target is directly achievable | Arguments are drawn inside skill domains | No impossible predicate or search dead end |
| Replanner sees the same direct effect vocabulary | Default registry and projected goal | No alternate-path reasoning is required |
| Oracle target mirrors the selected skill's declared target field | Generator stores `target_field` | Useful for scoring, but narrow and not independent task specification |

## Frozen-core protocol

The generic core was frozen before the two new-skill experiment and before the
holdout definitions were inspected. `benchmarks/core_freeze_manifest.json`
records SHA-256 and line counts for 12 files (1,385 physical lines). Every V2 run
first recomputes them and refuses to run on drift. No frozen-core file was changed
after observing holdout failures.

Design variants are `0..4` (65 trials). Holdout variants are disjoint `100..105`
(78 trials). Both contain the same independently specified fault families, while
numeric targets and arm choices differ. Scenario construction declares faults,
observations, capabilities, physical transitions, and oracle goals before calling
the executor; it never branches on executor output.

## V2 fault-family audit

The table reports FULL on the 65-trial design suite (5 trials per family).

| Family | Fault type | N | Possible? | Correct behavior | Retry | Repair | Observe | Replan | Stop only | FULL |
|---|---|---:|---|---|---|---|---|---|---|---|
| nominal | none | 5 | yes | COMPLETE | no | no | no | no | no | 5/5 complete |
| transient_physical | one-shot no physical effect | 5 | yes | COMPLETE | yes | no | no | no | no | 5/5 complete |
| permanent_actuator | permanent no physical effect | 5 | no on this backend | SAFE_STOP | no | no | no | no | yes | 5/5 correct stop |
| permanent_sensor_blindness | safety field stays UNKNOWN | 5 | physically yes, epistemically unsafe | SAFE_STOP | no | no | required but unavailable | no | yes | 5/5 correct stop |
| stale_refresh | safety field STALE, refresh works | 5 | yes | COMPLETE | no | no | yes | no | no | 5/5 complete |
| capability_mismatch | backend moves both arms for one-arm contract | 5 | no on this backend | SAFE_STOP | no | no | no | no | yes | 5/5 rejected pre-dispatch |
| contradictory_observation | `True` and `False` safety evidence | 5 | physically yes, epistemically unsafe | SAFE_STOP | no | no | required but unresolved | no | yes | 5/5 correct stop |
| multi_step_repair | two missing prerequisite layers | 5 | yes | COMPLETE | no | yes | no | no | no | 5/5 `deploy -> secure -> transport` |
| genuine_replan | primary path permanently blocked | 5 | yes | COMPLETE | no | no | no | yes | no | 5/5 alternate path |
| impossible_predicate | no skill establishes `payload_locked` | 5 | no | UNSAT/SAFE_STOP | no | no | no | no | yes | 5/5 correct stop |
| irreparable_conflict | parallel effects require A and B simultaneously | 5 | no | UNSAT/SAFE_STOP | no | no | no | no | yes | 5/5 correct stop |
| fresh_sensor_spoof | fresh target-valued observation, actuator never moves | 5 | no on this backend | SAFE_STOP | no | no | no | no | yes | **0/5; false positive** |
| replan_dead_end | failed skill is only achiever | 5 | no | replan failure + SAFE_STOP | no | no | no | attempted | yes | 5/5 correct stop |

FULL therefore does **not** achieve 100% task completion or 100% correct behavior.
It completes every task whose expected behavior is COMPLETE, conservatively stops
7 of 8 stop-expected families, and fails on fresh sensor spoofing.

## Metric definitions

All top-level rates use trial instances, not skill attempts.

| Metric | Exact numerator | Exact denominator | Interpretation / edge cases |
|---|---|---|---|
| `task_completion_rate` | trials where executor reports success **and** independent oracle goal is true | all trials | Safe stop never counts. Impossible tasks remain in the denominator. |
| `feasible_task_completion_rate` | same completed trials restricted to `expected_behavior=COMPLETE` | all COMPLETE-expected trials | Measures completion where the benchmark says completion is the correct outcome. |
| `correct_safe_stop_rate` | SAFE_STOP-expected trials with report failure, decision STOP, and no forbidden dispatch/false positive | all SAFE_STOP-expected trials | An impossible task is scored here, never as task completion. |
| `overall_correct_decision_rate` | completed COMPLETE trials plus correctly stopped SAFE_STOP trials | all trials | Separates decision quality from raw completion. |
| `unsafe_execution_rate` | trials with a scenario-declared forbidden command or executor success while oracle is false | all trials | Uses scenario safety rules and hidden physical truth. |
| `false_positive_rate` | executor-success trials whose independent oracle is false | all trials | A verifier report cannot label itself correct. |
| `repair_attempt_rate` | trials with REPAIR trace/metadata **or** explicit failed repair-search message | all trials | Failed searches are included. FULL: 20/65. |
| `replan_attempt_rate` | trials where recovery selected REPLAN, whether replanner succeeded or returned `None` | all trials | Failed replans are included. FULL: 15/65. |

V2 design-suite FULL results:

- task completion: 25/65 = 38.4615%;
- feasible task completion: 25/25 = 100%;
- correct safe stop: 35/40 = 87.5%;
- overall correct decision: 60/65 = 92.3077%;
- unsafe execution: 5/65 = 7.6923%;
- false positive: 5/65 = 7.6923%.

## Oracle independence

The boundaries are deliberately different:

1. Runtime verifier: `embodied_skill_ros.execution.outcome_verifier.OutcomeVerifier.verify`
   dispatches to `skills.base_skill.RobotSkill.verify_outcome`. It evaluates only
   the before/after **observed** `RobotState` supplied by `StateManager`.
2. Hidden transition: `backends.mock_backend.MockRobotBackend.command`, registered
   transition handlers, and `set_state` mutate private `_world`.
3. Benchmark oracle: `evaluation.oracle.BenchmarkOracle.evaluate` calls the
   benchmark-only `backend.oracle_state()` and compares raw hidden fields directly.

`SkillExecutor` and `OutcomeVerifier` neither import nor reference
`BenchmarkOracle`/`oracle_state`. `BenchmarkOracle` does not call
`verify_outcome`, `OutcomeVerifier`, or `StatePredicate`. Integrity tests inspect
these source boundaries, make `oracle_state()` raise during normal execution, and
replace runtime verification with an exception while independently running the
oracle.

Shared code is limited to the `RobotState` data container, its raw field accessor,
and ordinary equality/numeric tolerance. The oracle does not reuse epistemic
status evaluation or contract predicates, so sharing the container does not leak
ground truth into runtime execution.

## False-positive evidence

For `set_head(yaw_deg=25)`, the backend accepts a command while a permanent
physical failure leaves hidden yaw at 0:

| Configuration | Observation | Executor | Oracle |
|---|---|---|---|
| Direct/unverified | misleading target value marked STALE | success | false |
| FULL | misleading target value marked STALE | verifier rejects `STALE`, then stops | false |
| FULL verifier-failure case | spoofed target value marked fresh | **success** | **false** |

The final row is an observed architectural limitation: a single fresh but corrupt
sensor source can fool both per-skill and final-goal verification. The benchmark
keeps this failure instead of improving the headline.

## Replanning is not retry

Automated tests cover three persistent counterfactuals:

| Case | Original plan | Persistent failure | Observed relevant state | Replanned suffix | Structural change | Retry-only counterfactual |
|---|---|---|---|---|---|---|
| Navigation | `primary_drive` | permanent outage | `arrived=False` | `backup_drive` | skill changed | fails after retries; `arrived=False` |
| Payload | `primary_lock` | permanent outage | `payload_locked=False` | `backup_clamp` | skill changed | fails after retries; unlocked |
| Process power | `main_power -> run_process` | primary power permanent outage | `power_available=False`, `process_done=False` | `backup_power -> run_process` | intermediate achiever changed | retry-only never powers process |

The executor adds the failed skill to `blocked_skills`; `GoalDirectedReplanner`
rejects an equivalent signature. V2 additionally tests `primary_route ->
alternate_route` and a dead end where blocking `primary_route` leaves no achiever.

## Generic repair and zero-core-code experiment

The repair search enumerates registered effects that unify with a missing fact,
recursively solves declared preconditions, and selects a shortest bounded path.
It does not select by skill name. Search limits are 6 prerequisite levels, 64
expanded subgoals, and 16 inserted steps. Tests cover `B -> A -> Goal`, cycles,
no solution, the depth bound, multiple candidate paths, and incompatible parallel
effects.

After core freeze, two new preparation skills were added only in benchmark
contracts and Mock transition handlers:

```text
deploy_stabilizer (requires anchor_ready)
  -> secure_payload (requires stabilizer_deployed)
  -> transport_payload (requires payload_secured)
```

FULL synthesizes that exact sequence from a plan containing only
`transport_payload`. New preparation skills: 2. Frozen core LOC changed: **0**.
Manifest hashes remain identical, and a regression test rejects either new name
inside any frozen generic module.

### Concrete-name audit

| Location | Occurrence | Classification |
|---|---|---|
| `skills/registry.py` imports and `build_default_registry()` | five built-in skill classes | ACCEPTABLE composition root; generic `SkillRegistry` search itself uses contracts |
| `skills/*_skills.py` | contract names and definitions | ACCEPTABLE domain declarations |
| `backends/mock_backend.py` | deterministic built-in transitions | DOMAIN-SPECIFIC ADAPTER |
| `backends/jaka_backend.py` | legacy API dispatch/capabilities | DOMAIN-SPECIFIC ADAPTER |
| `planner/structured_planner.py` | command-oriented baseline parser | DOMAIN-SPECIFIC BASELINE, not repair reasoning |
| Frozen grounder/repair/recovery/executor/predicate modules | no concrete skill strings | no violation found |

## UNKNOWN, STALE, capability, and recovery outcomes

- UNKNOWN safety-critical and non-refreshable: gate fails; no motion command.
- STALE safety-critical and refreshable: OBSERVE, fresh evidence, then completion.
- UNKNOWN noncritical: unrelated skill can proceed.
- Permanently UNKNOWN critical: bounded acquisition cannot establish evidence; stop.
- Refresh succeeds: task continues. Refresh fails: target motion is never dispatched.
- Contradictory safety evidence: remains unusable; no convenient value is selected.
- One-arm abstract contract on bilateral backend: rejected before command unless
  bilateral side effects are explicitly allowed.
- Backend parameter-domain mismatch: rejected before command.
- `("safe_stop",)`: even a transient fault is not retried.
- `("retry", "safe_stop")`: exactly the bounded local retry is permitted.
- `("repair", "replan", "safe_stop")`: declarative preparation precedes the task.
- `("observe", "repair", "safe_stop")`: observation is attempted before repair.

## Ablation results on the same 65 trials

| Profile | Task completion | Feasible completion | Correct safe stop | Overall correct | Unsafe execution |
|---|---:|---:|---:|---:|---:|
| A Open loop | 46.15% | 60.00% | 0.00% | 23.08% | 76.92% |
| B Verification only | 46.15% | 60.00% | 25.00% | 38.46% | 46.15% |
| C Grounding + verification | 7.69% | 20.00% | 87.50% | 61.54% | 7.69% |
| D Contract grounding + generic repair | 15.38% | 40.00% | 87.50% | 69.23% | 7.69% |
| E + epistemic active observation | 23.08% | 60.00% | 87.50% | 76.92% | 7.69% |
| F FULL | 38.46% | 100.00% | 87.50% | 92.31% | 7.69% |
| F minus capability preflight | 38.46% | 100.00% | 75.00% | 84.62% | 15.38% |
| F minus explicit UNKNOWN | 46.15% | 100.00% | 75.00% | 84.62% | 15.38% |
| F minus generic repair | 30.77% | 80.00% | 87.50% | 84.62% | 7.69% |
| F minus verification | 23.08% | 60.00% | 62.50% | 61.54% | 38.46% |
| F minus active observation | 30.77% | 80.00% | 87.50% | 84.62% | 7.69% |

The scenarios are unchanged across profiles. “Minus UNKNOWN” is a documented
legacy optimistic-imputation ablation for the blind field; it is intentionally
unsafe and is not used by FULL.

## Holdout

The 78 post-freeze trials use variants 100–105 and were not used to change core
logic. The full system produced the same family-level outcome: 30/78 overall task
completion, 30/30 feasible completion, 42/48 correct safe stops, 72/78 correct
decisions, and 6/78 unsafe/false-positive executions. The equality with the design
suite reflects balanced deterministic family replication, not statistical
generalization. Exact rows are in `benchmarks/holdout_results.json`.
