# Literature Positioning and Novelty Boundaries

This document is a claim audit, not a claim that the repository introduces a new
planning algorithm.

## Closest ideas

- [SayCan](https://arxiv.org/abs/2204.01691) grounds language-model choices in a
  repertoire of pretrained robot skills and their affordances. EmbodiedSkill-ROS
  therefore does **not** claim that constraining an LLM by executable skills is new.
- [Inner Monologue](https://arxiv.org/abs/2207.05608) studies closed-loop language
  feedback including success detection and environment observations. This repository
  does **not** claim that observation-conditioned LLM replanning is new.
- [LLM+P](https://arxiv.org/abs/2304.11477) delegates formal plan construction to a
  classical planner. This repository's small goal-directed replanner is not presented
  as a replacement for PDDL search or an optimal planner.
- [PDDLStream](https://arxiv.org/abs/1802.08705) integrates declarative planning with
  black-box sampling for continuous robot constraints. EmbodiedSkill-ROS currently
  has no kinematic, collision, or motion sampler and makes no task-and-motion-planning
  claim.
- [Behavior Trees in Robotics and AI](https://arxiv.org/abs/1709.00084) and the
  implementation analysis in [Colledanchise and Natale](https://arxiv.org/abs/2106.15227)
  establish modular reactive execution as mature prior art. Bounded retry and fallback
  ordering are not novel by themselves.
- ROS2's [PlanSys2 executor](https://docs.ros.org/en/ros2_packages/humble/api/plansys2_executor/__README.html)
  already checks action requirements during execution and applies action effects.
  This repository should be compared experimentally with PlanSys2 rather than implying
  that precondition-aware ROS execution is absent from the ecosystem.

## Defensible contribution of this repository

The defensible contribution is a compact, ROS-independent experimental artifact that
combines the following under one falsifiable interface:

1. freshness-aware epistemic state (`KNOWN`, `UNKNOWN`, `STALE`);
2. declarative skill preconditions/effects that support generic preparation synthesis;
3. backend capability preflight before command dispatch;
4. separation of command acceptance, observed outcome, and hidden physical truth;
5. an independent benchmark oracle that never consumes `ExecutionReport.success`;
6. fixed and procedurally generated fault experiments; and
7. a zero-core-code skill-extension experiment.

The repository currently supports an **artifact contribution** and a research
hypothesis: these mechanisms reduce invalid calls and false success under partial state
and transient faults. It does not yet support a claim of algorithmic novelty,
state-of-the-art performance, real-time guarantees, collision safety, or hardware
generalization.

## Experiments still required for a paper-level novelty claim

- externally administered holdout tasks and paraphrases beyond the checked-in
  post-freeze deterministic family variants;
- multiple seeds and confidence intervals, not one deterministic run;
- matched comparisons with PlanSys2/BT-based recovery and a classical planner;
- sensor-delay, sensor-bias, and missing-observation ablations;
- simulation and supervised hardware trials with identical oracle definitions;
- failure taxonomy and calibration of verification tolerances; and
- preregistered success criteria that prevent post-hoc benchmark editing.
