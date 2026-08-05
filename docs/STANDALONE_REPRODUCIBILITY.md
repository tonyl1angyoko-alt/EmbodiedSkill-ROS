# Standalone Reproducibility

Validation date: 2026-08-06

Evidence label: `MOCK-VERIFIED`

## Isolation method

The complete repository directory was copied to a newly created `/tmp` directory. Commands were executed from the copied repository, which contained no parent workspace, reference project, ROS2 installation, JAKA SDK, credentials, or network configuration.

No source was copied from the reference project to make the standalone run pass.

## Commands executed

```bash
python3 -m compileall -q embodied_skill_ros examples benchmarks tests
python3 examples/normal_task.py
python3 examples/state_grounded_task.py
python3 examples/plan_repair_demo.py
python3 examples/recovery_demo.py
PYTHONPATH=. python3 -m unittest discover -s tests -v
python3 benchmarks/run_benchmark.py --output benchmark_outputs/standalone_results.json
python3 benchmarks/evaluate.py benchmark_outputs/standalone_results.json
```

`PYTHONPYCACHEPREFIX` was directed to the temporary directory during execution so validation would not create cache files in the repository.

## Actual results

- Python compilation: passed.
- Normal task demo: passed.
- State-grounded plan-change demo: passed.
- Resource-conflict repair demo: passed.
- Accepted-command/failed-outcome recovery demo: passed.
- Automated tests: **48 passed**, 0 failed.
- Scenario count: **30** with categories 5 single, 10 multi, 5 state, 5 conflict, and 5 fault.

| Profile | Task success | Invalid skill-call rate |
|---|---:|---:|
| A Direct Function Calling | 60.00% | 14.55% |
| B Structured Sequential | 60.00% | 12.96% |
| C State-Grounded | 83.33% | 0.00% |
| D State-Grounded + Recovery | 96.67% | 0.00% |

These are deterministic Mock results over predefined scenarios, not ROS2 simulation or hardware results. Sub-millisecond local Python latency values are environment-specific and are not treated as robot-performance measurements.

## Unavailable checks

- `python3 -m pytest`: unavailable because the system Python has no `pytest` module. The pytest-compatible tests were run with `unittest`.
- `colcon build --symlink-install`: unavailable because `colcon` is not installed.
- ROS2 Humble services, nodes, actions, and launch files: `UNVERIFIED`.
- JAKA hardware: `UNVERIFIED`.
