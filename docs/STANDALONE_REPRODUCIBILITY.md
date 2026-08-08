# Standalone Reproducibility

> **Historical frozen-macOS record.** This document preserves the exact pre-ROS2
> isolation audit and its 102-test/ROS-unavailable environment. It is not the current
> project status. For current evidence, see `docs/VALIDATION_EVIDENCE.md` and
> `docs/ROS2_RUNTIME_VALIDATION_REPORT.md`.

Validation date: 2026-08-08

Evidence labels: `UNIT-VERIFIED`, `MOCK-VERIFIED`, `BENCHMARK-VERIFIED`

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
python3 benchmarks/run_procedural_benchmark.py --seed 20260808 --trials 200
PYTHONPATH=. python3 benchmarks/run_benchmark_v2.py
```

`PYTHONPYCACHEPREFIX` was directed to the temporary directory during execution so validation would not create cache files in the repository.

## Actual results

- Python compilation: passed.
- Normal task demo: passed.
- State-grounded plan-change demo: passed.
- Resource-conflict repair demo: passed.
- Accepted-command/failed-outcome recovery demo: passed.
- Automated tests: regenerate with the command above; the hostile-audit run found
  **102 discovered; 100 passed, 2 ROS2 runtime tests skipped**, 0 failed.
- Scenario count: **30** with categories 5 single, 10 multi, 5 state, 5 conflict, and 5 fault.

| Profile | Task success | Invalid skill-call rate |
|---|---:|---:|
| A Direct Function Calling | 60.00% | 14.55% |
| B Structured Sequential | 60.00% | 12.96% |
| C State-Grounded | 83.33% | 0.00% |
| D State-Grounded + Recovery | 93.33% | 0.00% |

These are deterministic Mock results over predefined scenarios, not ROS2 simulation
or hardware results. The older 96.67% figure counted an equivalent-plan retry as
replanning; after enforcing structural difference the corrected rate is 93.33%.
Sub-millisecond local Python latency values are environment-specific and are not
treated as robot-performance measurements.

The independently generated 200-trial run reports 24.00% direct success with a
23.00% false-positive rate, and 100.00% success with 0 false positives for grounded
execution plus bounded recovery. This old suite contains only no-fault or one-shot
transient faults; its 100% is task completion on that narrow set, not correct safe
handling of unrecoverable cases.

The frozen-core V2 design suite has 65 trials and FULL reports 38.46% overall task
completion, 100% feasible-task completion, 87.50% correct safe stop, 92.31%
overall correct decision, and 7.69% unsafe execution. The independent post-freeze
holdout has 78 trials with 38.46%, 100%, 87.50%, 92.31%, and 7.69%, respectively.

## Exact Python test environment

- `python` executable: absent from `PATH`; therefore `python --version` is unavailable.
- `python3` command: `/usr/bin/python3`.
- `sys.executable`: `/Library/Developer/CommandLineTools/usr/bin/python3`.
- version: Python 3.9.6, Clang 21.0.0; `python3 --version` prints `Python 3.9.6`.
- architecture/host: Apple Silicon `arm64`, macOS 26.5.2 (build 25F84).
- environment manager: none. `VIRTUAL_ENV` and `CONDA_PREFIX` were empty;
  `uv`, `poetry`, and `conda` were absent; `sys.prefix == sys.base_prefix`.
- test runner: standard-library `unittest`, loaded from
  `/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/unittest/__init__.py`.
- exact test command: `PYTHONPATH=. python3 -m unittest discover -s tests -v`.
- pytest executable/module source: none. `pytest` is absent from `PATH`, and
  `python3 -m pytest --version` returns `No module named pytest`.
- pip is user-site pip 26.0.1 under the host's Python 3.9 user-site directory;
  it was not used to install anything for this audit.
- project/runtime dependencies: the audited core and tests use the Python standard
  library. Optional ROS/JAKA dependencies were neither installed nor invoked.

## Unavailable checks

- `python3 -m pytest`: unavailable because the system Python has no `pytest` module. The pytest-compatible tests were run with `unittest`.
- `colcon build --symlink-install`: unavailable because `colcon` is not installed.
- Optional ROS2 Mock bridge source and launch: `STATICALLY-INSPECTED`; Humble runtime `UNVERIFIED`.
- JAKA hardware: `UNVERIFIED`.
