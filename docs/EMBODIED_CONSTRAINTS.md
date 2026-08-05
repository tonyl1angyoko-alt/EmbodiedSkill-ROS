# Embodied Constraints

## Implemented constraints

| Constraint | Detection | Repair / response |
|---|---|---|
| Emergency stop active | `emergency_stop is True` | non-repairable `STOP` |
| Robot fault present | non-empty `fault` | non-repairable `STOP` |
| Body resource busy | overlap of `active_resources` and skill resources | re-ground; stop if state does not clear |
| AGV with unsafe or UNKNOWN arm | either `*_arm_safe is not True` | insert `retract_arm` before `move_agv` |
| Lift with unsafe or UNKNOWN arm | same | insert `retract_arm` before `set_lift` |
| Parallel shared resource | same resource in one parallel group | serialize group |
| AGV parallel with arm extension/lift | skill-name body conflict | serialize and add preparation action as needed |
| Parameter outside schema | static validation | stop before backend call; not silently clamped |
| Command timeout/failure | receipt or elapsed skill timeout | bounded retry, then replan, then stop |
| State differs from expected effect | outcome verifier | bounded retry/re-ground/replan |

## UNKNOWN policy

For safety-critical preconditions, UNKNOWN is treated as “not yet grounded,” not as false evidence of danger and not as permission to move. A repair can turn semantic UNKNOWN into known safe only when the repair skill itself has a verifiable outcome. On the default JAKA adapter, arm transport safety remains UNKNOWN unless the deployment supplies a validated state provider; therefore the adapter will not claim successful grounded transport from command acceptance alone.

## Mock body model

The Mock backend models a low-level controller that may accept AGV/lift commands while inhibiting motion if an arm is not transport-safe. This is deliberate: it creates a reproducible “accepted but not achieved” case. Benchmark success is scored independently from final physical state, so disabling verification cannot inflate the measured task outcome.

## Deliberately not claimed

- No collision geometry, swept-volume model, torque/force envelope, payload model, or human-proximity sensor is invented.
- “Transport-safe arm pose” is semantic in Mock only. Hardware classification requires robot-specific calibration.
- Lift/arm compatibility is a conservative rule, not a proven kinematic theorem.
- No global emergency-stop topic/service is asserted because the inspected Agent path did not provide one.

## Extension point

Robot-specific deployments should extend `ConstraintChecker`, populate `RobotState` from verified topics/services, and add tolerances/settle windows to each skill verifier. The execution policy should remain repair-first and bounded.
