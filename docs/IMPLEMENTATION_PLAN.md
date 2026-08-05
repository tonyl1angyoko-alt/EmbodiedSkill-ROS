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

## Hardware follow-up order

1. Implement a measured arm transport-pose classifier using joint/TCP feedback and calibrated tolerances.
2. Supply AGV odometry, motion state, fault, and emergency-stop fields through `state_provider`/`agv_position_provider`.
3. Replace blocking legacy service calls with bounded ROS2 future waits and cancellation.
4. Validate outcome settle times and tolerance bands on hardware.
5. Re-run the same scenario schema with a hardware backend and compare Mock-to-real failure distributions.

## Research follow-up

The most valuable next experiment is not a larger language model. It is an ablation over observation quality: progressively replace UNKNOWN state with measured feedback and quantify how grounding accuracy, repair success, and unnecessary stops change.
