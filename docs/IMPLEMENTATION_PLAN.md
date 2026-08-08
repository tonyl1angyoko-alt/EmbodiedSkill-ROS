# Implementation Plan and Status

| Phase | Deliverable | Status |
|---|---|---|
| 1 | Preserve and inspect original project | Complete; reference tree unchanged |
| 2 | Evidence-based call chain, skill, interface, and risk docs | Complete |
| 3 | Typed state, plans, results, and skill abstraction | Complete |
| 4 | Registry and four-component skill set | Complete |
| 5 | Mock backend and deterministic fault injection | Complete |
| 6 | State grounding, resource/body constraints, plan repair | Complete |
| 7 | Closed-loop executor and outcome verification | Complete |
| 8 | Bounded retry, re-ground, replan, safe stop | Complete |
| 9 | Optional JAKA adapter over legacy skills | Implemented with explicit UNKNOWN fields; hardware validation pending |
| 10 | Required demos and automated tests | Complete in Mock |
| 11 | 30-scenario A/B/C/D benchmark | Complete and reproducible |
| 12 | Hardware integration and calibration | TODO; requires ROS2/JAKA runtime and robot access |
| 13 | Declarative contracts and freshness-aware epistemic state | Complete; unit verified |
| 14 | Effect-driven generic repair and goal-directed replanning | Complete; Mock verified |
| 15 | Hidden physical world and independent benchmark oracle | Complete; integrity tested |
| 16 | Backend capabilities and recovery-policy enforcement | Complete; unit verified |
| 17 | Seeded procedural fault benchmark and adversarial/property tests | Complete; benchmark verified |
| 18 | Process-separated ROS2 fake robot and Ubuntu/Humble runtime validation | Complete; ROS2 runtime verified for R1–R15 |
| 19 | Portfolio v0.2.0 claim consolidation and release metadata | Complete after final validation/tagging |
| 20 | JAKA/Kargo adapter, state/capability mapping, exact-schema runtime evidence, and v0.3.0 release | Complete; hardware remains unverified |

## Hardware follow-up order

1. Implement a measured arm transport-pose classifier using joint/TCP feedback and calibrated tolerances.
2. Supply AGV odometry, motion state, fault, and emergency-stop fields through `state_provider`/`agv_position_provider`.
3. Replace blocking legacy service calls with bounded ROS2 future waits and cancellation.
4. Validate outcome settle times and tolerance bands on hardware.
5. Re-run the same scenario schema with a hardware backend and compare Mock-to-real failure distributions.

## Research follow-up

The most valuable next experiment is not a larger language model. It is an ablation over observation quality: progressively replace UNKNOWN state with measured feedback and quantify how grounding accuracy, repair success, and unnecessary stops change.

See `docs/VALIDATION_EVIDENCE.md` for evidence categories and
`docs/LITERATURE_AND_NOVELTY.md` for claim boundaries.
