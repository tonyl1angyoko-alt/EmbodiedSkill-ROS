# Changelog

## [Unreleased]

No changes yet.

## [0.3.1] - 2026-08-09

Engineering Hygiene:

- add portable GitHub Actions for Python 3.9–3.11, Ruff, a scoped Pyright baseline,
  release-metadata consistency, YAML registry consistency, and freeze verification;
- add a dynamic unittest inventory instead of introducing another hard-coded count;
- separate ignored local rerun output from committed canonical release evidence;
- document the frozen executor state machine, every STOP path, and the two JAKA
  backend roles without changing execution or robot command semantics; and
- preserve all 12 frozen reasoning files and the v0.2.0/v0.3.0 tags unchanged.

No robot execution semantics changed. No ROS2/JAKA runtime claim was upgraded;
those evidence boundaries remain inherited from v0.3.0.

## [0.3.0] - 2026-08-08

JAKA/Kargo Integration Layer:

- audit the separately delivered laboratory JAKA/Kargo workspace, its real ROS2
  interfaces, SDK boundary, observation signals, side effects, stop scope,
  cancellation, timeout, dependencies, provenance, and publication risks;
- add an optional `JakaKargoBackend`, measured-state provider, capability mapper,
  and lazy exact-schema ROS2 transport without changing the frozen core;
- map five skills across arm, AGV, lift, head, and waist while preserving UNKNOWN
  state and rejecting semantic-scope mismatch before transmission;
- add a motion-disabled read-only probe and external-dependency deployment boundary;
- add 20 integration contract tests and nine process-separated ROS2 scenarios,
  including Service-success/no-physical-transition and timeout negative controls;
- build-verify the exact external interface packages and unmodified `jaka_toolbox`
  without redistributing vendor/laboratory material;
- retain a zero-file delta across the 12-file / 1,385-LOC frozen reasoning core; and
- document that vendor-node runtime, calibration, whole-robot stop, hardware, and
  physics simulation remain unverified.

## [0.2.0] - 2026-08-08

ROS2 Runtime Portfolio Release:

- add declarative skill contracts, freshness-aware epistemic state, generic
  effect-driven repair, structural replanning, and backend capability preflight;
- separate command acceptance, observation, outcome verification, and independent
  hidden-state scoring;
- correct the fixed benchmark methodology and retain 93.33% as the current
  30-scenario deterministic Mock result;
- add seeded procedural evaluation, adversarial V2, A–F/removal ablations, a
  frozen-core holdout, exact metric definitions, and an explicit failure ledger;
- freeze 12 reasoning files / 1,385 LOC with a hash manifest and verify a
  zero-core-modification new-skill extension;
- add Ubuntu 22.04.5 / ROS2 Humble validation with 107 passing tests;
- add a process-separated fake robot and R1–R15 topic/service/action scenarios;
- retain fresh-sensor-spoof and TOCTOU failures as explicit unsafe boundaries;
- audit JAKA backend semantics without claiming runtime or hardware validation; and
- redesign the project documentation for evidence-first portfolio presentation.

## [0.1.0] - 2026-08-06

Initial Mock-validated research prototype:

- unified embodied skill abstraction;
- four-component Mock support;
- state-grounded plan repair;
- closed-loop execution and bounded recovery;
- 30-scenario Mock benchmark;
- automated test suite; and
- statically inspected JAKA adapter boundary.
