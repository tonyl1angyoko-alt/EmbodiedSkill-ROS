# Changelog

## [Unreleased]

- replace callback-only semantics with declarative skill predicates and effects;
- add freshness-aware epistemic state and backend capability contracts;
- make plan repair effect-driven and replanning goal-directed;
- separate Mock observations from hidden physical truth and add an independent oracle;
- add a seeded 200-trial procedural fault benchmark and integrity/property tests;
- add frozen-core V2 adversarial and 78-trial post-freeze holdout suites, A-F/removal
  ablations, explicit metric definitions, and a remaining-failures ledger;
- add bounded multi-level generic repair, explicit contradictory evidence, active
  observation, semantic capability checks, permanent faults, and genuine alternate-skill replanning;
- add an optional ROS2 Mock bridge, launch file, evidence ledger, novelty audit, and
  Ubuntu 22.04 + ROS2 Humble validation plan;
- expand the suite to 102 tests (100 passing on macOS, 2 ROS2 tests skipped).

## [0.1.0] - 2026-08-06

Initial research prototype:

- unified embodied skill abstraction;
- four-component Mock support;
- state-grounded plan repair;
- closed-loop execution and bounded recovery;
- 30-scenario Mock benchmark;
- automated test suite;
- statically inspected JAKA adapter boundary.
