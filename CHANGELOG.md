# Changelog

## [Unreleased]

No changes yet.

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
