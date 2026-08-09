# Evidence Artifact Policy

This repository separates canonical release evidence from ordinary local reruns.
Generated does not automatically mean disposable: the committed JSON files are part
of the reproducible v0.2/v0.3 evidence record and remain tracked.

## Canonical committed evidence

The following paths are reviewable release artifacts:

- `benchmarks/benchmark_results.json`
- `benchmarks/procedural_results.json`
- `benchmarks/adversarial_v2_results.json`
- `benchmarks/ablation_results.json`
- `benchmarks/holdout_results.json`
- `ros2_validation_outputs/runtime_scenarios.json`
- `jaka_kargo_validation_outputs/integration_scenarios.json`

They must not be deleted or broadly ignored. Replacing one is a release-evidence
operation: use the required platform, pass an explicit canonical output path, inspect
the complete diff, and record the environment and evidence boundary. A macOS rerun
cannot replace or upgrade ROS2 Humble or JAKA/Kargo exact-schema evidence.

## Local rerun output

Benchmark and runtime CLIs default to `local_validation_outputs/`, which is ignored by
Git. This prevents a normal developer rerun from silently dirtying frozen evidence.
Examples:

```bash
python3 benchmarks/run_benchmark.py
python3 benchmarks/run_procedural_benchmark.py --seed 20260808 --trials 200
PYTHONPATH=. python3 benchmarks/run_benchmark_v2.py
```

ROS2 and JAKA/Kargo runtime commands use the same local directory when `--output` is
omitted. They still require their documented external environments; the output-path
default does not make those environments portable.

## Explicit release regeneration

Only a deliberate release validation should target the committed paths:

```bash
python3 benchmarks/run_benchmark.py \
  --output benchmarks/benchmark_results.json
python3 benchmarks/run_procedural_benchmark.py \
  --seed 20260808 --trials 200 \
  --output benchmarks/procedural_results.json
PYTHONPATH=. python3 benchmarks/run_benchmark_v2.py \
  --output-dir benchmarks
```

On the already documented Ubuntu 22.04 / ROS2 Humble environments, the release
harnesses likewise require explicit `--output ros2_validation_outputs/...` or
`--output jaka_kargo_validation_outputs/...`. Portable CI never regenerates those
canonical runtime artifacts and makes no vendor, laboratory-workspace, or hardware
claim.
