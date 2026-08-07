# Embodied Constraints

## Implemented constraints

| Constraint | Detection | Repair / response |
|---|---|---|
| Emergency stop active | `emergency_stop is True` | non-repairable `STOP` |
| Robot fault present | non-empty `fault` | non-repairable `STOP` |
| Body resource busy | overlap of `active_resources` and skill resources | re-ground; stop if state does not clear |
| Skill predicate false, UNKNOWN, or STALE | declarative `StatePredicate` | synthesize a registered effect that establishes the fact, otherwise stop |
| Parallel shared resource | same resource in one parallel group | serialize group |
| Incompatible parallel body resources | contract `incompatible_resources` | serialize and add effect-derived preparation as needed |
| Backend lacks skill/effect observation | capability contract | non-repairable stop before dispatch |
| Parameter outside schema | static validation | stop before backend call; not silently clamped |
| Command timeout/failure | receipt or elapsed skill timeout | bounded retry, then replan, then stop |
| State differs from expected effect | outcome verifier | bounded retry/re-ground/replan |

## UNKNOWN policy

For safety-critical preconditions, UNKNOWN and STALE are treated as “not currently
grounded,” not as false evidence of danger and not as permission to move. A repair can
turn missing evidence into known safe only when its outcome is observable and verified.
On the default JAKA adapter, arm transport safety remains UNKNOWN unless the deployment
supplies a validated state provider; therefore the adapter will not claim successful
grounded transport from command acceptance alone.

## Mock body model

The Mock backend models a low-level controller that may accept AGV/lift commands while inhibiting motion if an arm is not transport-safe. This is deliberate: it creates a reproducible “accepted but not achieved” case. Benchmark success is scored independently from final physical state, so disabling verification cannot inflate the measured task outcome.

## Deliberately not claimed

- No collision geometry, swept-volume model, torque/force envelope, payload model, or human-proximity sensor is invented.
- “Transport-safe arm pose” is semantic in Mock only. Hardware classification requires robot-specific calibration.
- Lift/arm compatibility is a conservative rule, not a proven kinematic theorem.
- No global emergency-stop topic/service is asserted because the inspected Agent path did not provide one.

## Extension point

Robot-specific deployments should extend `ConstraintChecker`, populate `RobotState` from verified topics/services, and add tolerances/settle windows to each skill verifier. The execution policy should remain repair-first and bounded.
