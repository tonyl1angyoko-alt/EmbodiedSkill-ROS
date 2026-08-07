# Validation Evidence Ledger

Evidence labels are deliberately non-transitive: a unit test does not imply a ROS2,
simulation, or hardware result.

| Capability | Status | Evidence | Limit |
|---|---|---|---|
| Declarative `SkillContract`, predicates, effects, argument validation | `UNIT-VERIFIED` | `tests/test_models_and_registry.py`, `tests/test_research_core.py` | Pure Python semantics only |
| `KNOWN` / `UNKNOWN` / `STALE` / `CONTRADICTORY` epistemic state | `UNIT-VERIFIED` / `BENCHMARK-VERIFIED` | explicit refresh, permanent blindness, noncritical unknown, contradiction tests | Sensor timestamps are synthetic in Mock |
| Effect-driven generic preparation repair | `MOCK-VERIFIED` | built-in arm repair; generic `B -> A -> Goal`; frozen-core `deploy_stabilizer`/`secure_payload` experiment | Not a complete task-and-motion planner |
| Backend capability preflight | `UNIT-VERIFIED` | unsupported custom skill is stopped before dispatch | JAKA capabilities depend on supplied adapters/providers |
| Hidden physical world and independent oracle | `BENCHMARK-VERIFIED` | structural dependency tests, oracle-spoof tests, V2 | Fresh spoof still fools runtime verifier; deterministic model |
| Goal-directed replanning | `UNIT-VERIFIED` / `MOCK-VERIFIED` | three persistent alternate-skill counterfactuals plus V2 dead end | Effect achiever, not optimal or motion-feasible search |
| Recovery-policy enforcement | `UNIT-VERIFIED` | skill policy forbids retry despite executor retry budget | Cancellation of a blocking ROS call remains deployment work |
| A/B/C/D fixed benchmark | `BENCHMARK-VERIFIED` | `benchmarks/benchmark_results.json` | 30 predefined deterministic scenarios |
| Seeded procedural fault benchmark | `BENCHMARK-VERIFIED` | `benchmarks/procedural_results.json`, seed `20260808`, 200 trials | Synthetic transient faults |
| Frozen-core V2 adversarial suite | `BENCHMARK-VERIFIED` | 65 design trials, A-F and removal ablations | One fresh-spoof family fails FULL |
| Post-freeze holdout | `BENCHMARK-VERIFIED` | 78 trials, core hashes revalidated | Balanced deterministic family replication, not deployment statistics |
| Optional ROS2 Mock bridge source, launch, package metadata | `STATICALLY-INSPECTED` | source inspection and ROS-free import test on macOS | Not built or launched on this host |
| ROS2 Humble runtime | `UNVERIFIED` | ROS2 tests skipped with an explicit reason | Requires Ubuntu 22.04 validation |
| Gazebo/MoveIt simulation | `UNVERIFIED` | no simulation executed | No simulation result claimed |
| JAKA hardware | `UNVERIFIED` | adapter contract tests only | No command was sent to hardware |

## Current macOS evidence

The hostile-audit standard-library suite contains 102 tests: 100
platform-independent tests pass and 2 ROS2 runtime tests are skipped when ROS2 is absent.
The exact current result must be regenerated rather than copied into a paper:

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
python3 benchmarks/run_benchmark.py
python3 benchmarks/run_procedural_benchmark.py --seed 20260808 --trials 200
PYTHONPATH=. python3 benchmarks/run_benchmark_v2.py
```
