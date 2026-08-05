# Contributing

Thank you for helping improve EmbodiedSkill-ROS. Reproducibility and honest capability labels are part of correctness.

## Before opening a change

1. Do not commit robot addresses, credentials, internal configuration, recorded personal data, or proprietary reference source.
2. Keep the core backend-neutral. ROS2/JAKA-specific imports belong behind optional adapters.
3. Label evidence as `VERIFIED`, `MOCK-VERIFIED`, `STATICALLY-INSPECTED`, `UNVERIFIED`, or `PLANNED`.
4. Never describe a Mock result as hardware validation.

## Development checks

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
python3 examples/normal_task.py
python3 examples/state_grounded_task.py
python3 examples/plan_repair_demo.py
python3 examples/recovery_demo.py
python3 benchmarks/run_benchmark.py --output benchmark_outputs/local_results.json
```

If ROS2 Humble is available, report the exact build/test command and environment. A failed or skipped check must not be rewritten as a pass.

## Pull requests

- Explain body-state assumptions and expected physical effects.
- Add tests for new skills, constraints, repair rules, or recovery behavior.
- Include a fault-injection scenario for new failure handling.
- Confirm generated output contains no local paths or secrets.
