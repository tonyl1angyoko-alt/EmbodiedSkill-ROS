# Roadmap

Completed evidence and planned work are separated explicitly.

## v0.2.0 — ROS2 Runtime Portfolio Release — complete

- frozen declarative reasoning core and corrected benchmark methodology;
- epistemic state, generic repair, structural replanning, and capability preflight;
- hidden-state oracle, adversarial V2, ablations, and frozen holdout;
- Ubuntu 22.04.5 / ROS2 Humble build and 107-test validation environment;
- process-separated fake robot with topic/service/action communication;
- R1–R15 runtime scenarios plus fresh-spoof and TOCTOU probes; and
- static JAKA capability/side-effect audit.

## v0.3.0 — JAKA/Kargo Integration Layer — complete

- legacy call chain, ROS schema, SDK, state, side-effect, and IP audit;
- five-skill backend adapter, epistemic state provider, and capability mapper;
- exact external interface and unmodified toolbox build validation;
- 20 integration contract tests plus nine process-separated exact-schema runtime
  scenarios;
- motion-disabled read-only deployment probe; and
- zero modifications to the 12-file frozen reasoning core.

This is an integration-layer release, not a hardware release. Vendor-node runtime,
private deployment review, and supervised hardware validation remain separate gates.

## v0.3.1 — Engineering Hygiene — complete

- portable CI and a Python 3.9–3.11 unit-test matrix;
- correctness-oriented Ruff and scoped non-ROS2 Pyright baselines;
- automated release metadata, registry mirror, and freeze-manifest checks;
- a committed-evidence versus local-rerun artifact policy; and
- executor/STOP-path audit documentation with zero frozen-core modifications.

This is a software-engineering and reproducibility release, not a new robot
capability milestone. It does not replace the v0.3.0 ROS2/JAKA evidence. ROS2
runtime and hardware validation remain separate gates.

## Near-term portfolio work — planned

- record a real terminal/runtime demo without presenting it as hardware footage;
- add a concise release page linked to the machine-readable evidence; and
- improve documentation navigation as external users reproduce the artifact.

## Externally administered evaluation — planned

- unseen task paraphrases and hidden initial states;
- adversarial resource conflicts administered outside the repository fixtures;
- repeated trials and confidence intervals; and
- matched PlanSys2 or behavior-tree recovery baselines.

The current 78-trial frozen holdout is deterministic family replication, not a
sample from a deployment distribution.

## Simulation integration — unverified / planned

- Gazebo, MoveIt2, or another physics backend;
- reproducible simulator launch and measured before/after state; and
- clear separation from the deterministic fake robot.

## JAKA hardware validation — unverified / planned

- private, reviewed calibration and endpoint configuration;
- read-only state acquisition from a supervised vendor-backed node;
- calibrated transport-safe joint/TCP envelope;
- measured AGV odometry and fault state;
- whole-robot stop semantics;
- supervised low-risk execution; and
- sanitized traces and a real recorded demo.

## Optional research track

Version/evidence-guarded command admission may be studied for ROS2 check→dispatch
races. It is optional future research, not a prerequisite for the v0.2.0 or v0.3.0
integration-layer claims.
