# Hazard-driven safety benchmark

This deterministic Mock benchmark evaluates the H-001 through H-008 safety
properties against four benchmark-only assurance profiles. Scenario oracles are
declared in `scenarios.json`; they do not call production constraint or outcome
logic to manufacture ground truth. Profiles A–C are isolated ablation runners.
Profile D exercises the normal `SkillExecutor` without adding an unsafe runtime
switch. `safety_results.json` intentionally contains no latency measurements.

The benchmark is comparative evidence about this Mock model. It is not a
hardware-safety result, statistical significance claim, or certification.
