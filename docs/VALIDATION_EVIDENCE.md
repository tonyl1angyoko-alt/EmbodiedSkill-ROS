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
| ROS2 Humble package build/discovery/launch | `ROS2-RUNTIME-VERIFIED` | Ubuntu 22.04.5/Humble; colcon build; installed package discovery; live graph; clean shutdown | Fake robot only; validation action schema is test-only |
| Process-separated nominal command → observation → verification | `ROS2-RUNTIME-VERIFIED` | R1 and R4 in `ros2_validation_outputs/runtime_scenarios.json` | Deterministic fake physical state, not simulation physics |
| ROS action acceptance vs physical outcome | `ROS2-RUNTIME-VERIFIED` | R3 accepted/succeeded with no transition; fresh post-action sample caused verifier STOP | Still conditioned on observation truth |
| UNKNOWN/STALE active refresh and conservative block | `ROS2-RUNTIME-VERIFIED` | R5–R8 | Single deterministic observation source |
| Generic effect-driven repair through ROS | `ROS2-RUNTIME-VERIFIED` | R10 inserts `retract_arm -> move_agv` and executes both across ROS | Same bounded symbolic search as Mock |
| Structural replanning through ROS | `ROS2-RUNTIME-VERIFIED` | R11 switches persistent `primary_route` failure to `alternate_route`; retry-only counterfactual fails | Synthetic route effects; no motion planner |
| ROS capability preflight | `ROS2-RUNTIME-VERIFIED` | R12 bilateral arm semantics rejected before action transmission | JAKA endpoint itself was not run |
| ROS action timeout and adapter cancellation | `ROS2-RUNTIME-VERIFIED` | R13 timeout/cancel/retry and R14 external cancel/coherent state | Frozen executor has no caller-facing cancel API |
| Asynchronous TOCTOU safety | `KNOWN-UNSAFE-LIMITATION` | L1 changes a fresh safety fact between guard and transition; prohibited motion succeeds | Freshness is not an atomic lease/interlock |
| Fresh ROS sensor spoof | `KNOWN-UNSAFE-LIMITATION` | L2 reproduces executor success with false hidden state | Intentional frozen trust-model boundary |
| Gazebo/MoveIt simulation | `UNVERIFIED` | no simulation executed | No simulation result claimed |
| JAKA adapter mapping | `STATICALLY-INSPECTED` | `docs/JAKA_CAPABILITY_AUDIT.md`; bilateral preflight and partial-safe-stop honesty tests | Vendor bridge packages/services not active |
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

## Ubuntu 22.04 / Humble evidence

The Linux branch contains 107 tests: the original 102, four process-separated ROS
scenario tests, and one JAKA safe-stop honesty regression. The exact final count
must be regenerated after every test change.

```bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select embodied_skill_ros
source install/setup.bash
ROS_LOG_DIR=/tmp/embodied_skill_ros_logs ROS_LOCALHOST_ONLY=1 \
  colcon test --packages-select embodied_skill_ros
colcon test-result --all --verbose
ROS_LOG_DIR=/tmp/embodied_skill_ros_logs ROS_LOCALHOST_ONLY=1 \
  ros2 run embodied_skill_ros validate_runtime \
  --output ros2_validation_outputs/runtime_scenarios.json
```

See `docs/ROS2_RUNTIME_VALIDATION_REPORT.md` for scenario-level interpretation.
