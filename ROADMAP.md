# Roadmap

All items below are `PLANNED`, not completed capabilities.

## v0.2.0 — Research-core rigor and ROS2 validation preparation

- declarative contracts, epistemic freshness, generic repair, genuine goal replanning;
- hidden-world oracle, procedural benchmark, integrity/property/adversarial tests;
- optional ROS2 Mock bridge and exact Ubuntu validation plan.

Core items are complete on macOS; ROS2 runtime validation remains planned.

## v0.2.1 — ROS2 Humble runtime validation

- Ubuntu 22.04 build;
- `colcon build --symlink-install`;
- ROS2 node/service/action smoke tests;
- launch-file validation.

## v0.3.0 — Externally administered benchmark

- unseen task paraphrases;
- hidden initial states;
- adversarial resource conflicts;
- benchmark leakage audit;
- confidence intervals and repeated trials.

A 78-trial deterministic post-freeze Mock holdout now exists. It does not replace
this planned external evaluation or provide deployment-distribution confidence intervals.

## v0.4.0 — Simulation integration

- Gazebo, MoveIt2, or another suitable simulation backend;
- RViz visualization;
- reproducible simulation demo.

## v0.5.0 — JAKA hardware validation

- verified adapter mapping;
- low-risk real-robot tasks;
- human-supervised execution;
- real execution traces and videos.
