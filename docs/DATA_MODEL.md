# Data Model

## `RobotState`

`RobotState` is a timestamped observation snapshot. `None` always means UNKNOWN; it never means safe or ready. Ordinary copies, planning projections, and execution metadata updates preserve the observation timestamp. A backend must create a new timestamp only when it has a new observation or physical state update.

| Field group | Fields | Mock | Default JAKA adapter |
|---|---|---|---|
| Arms | `left/right_arm_ready`, `left/right_arm_safe` | deterministic | readiness queried where legacy `_query_arm` is available; safety UNKNOWN without validated provider |
| AGV | `agv_ready`, `agv_moving`, `agv_position_m` | deterministic | UNKNOWN unless an odometry/state provider is supplied |
| Lift | `lift_ready`, `lift_height_mm` | deterministic | measured through legacy external-axis backend |
| Head | `head_ready`, yaw, pitch | deterministic | measured through legacy external-axis backend |
| Runtime | `active_resources`, `emergency_stop`, `fault`, `last_skill_result`, timestamp | deterministic | UNKNOWN unless provided; last result maintained by `StateManager` |

## `TaskPlan` and `PlanStep`

```json
{
  "goal": "move to workstation",
  "plan_id": "plan_1",
  "revision": 0,
  "steps": [
    {
      "id": "step_1",
      "skill": "move_agv",
      "arguments": {"distance_m": 1.0},
      "expected_effect": {},
      "parallel_group": null,
      "inserted_by": null
    }
  ]
}
```

The parser validates shape and identity fields. The registry validates skill names and parameter schemas. `parallel_group` expresses a planner request, not permission: the first executor serializes it after conflict analysis.

## `RobotSkill`

Every skill has:

- `name` and `description`;
- executable `parameter_schema`;
- `required_resources`;
- state-aware `preconditions`;
- a timeout and bounded recovery policy;
- `execute()` returning only a `CommandReceipt`;
- `expected_effects()` and `verify_outcome()` for physical validation.

`ParameterSpec` rejects missing, unknown, incorrectly typed, non-finite, and out-of-range arguments. Boolean values are not accepted as numbers.

## Result separation

- `CommandReceipt.accepted` means the backend accepted/completed its call path.
- `VerificationResult.achieved` means observed state matches the expected physical effect.
- `SkillResult.physical_outcome_achieved` and trace `outcome_verified` are tri-state: `True` verified achieved, `False` verified not achieved, and `None` not physically verified.
- Direct/baseline execution may advance after command acceptance, but it records `None` and an explicit “physical outcome not verified” message.

This separation is visible in the recovery demo: the first lift command is accepted, but unchanged height makes `physical_outcome_achieved=false`.

## Trace

`ExecutionTrace` contains plan ID, decisions, and one `TraceRecord` per attempt. A record includes arguments, UTC start/end timestamps, backend response, before/after states, verification, error, timeout, recovery, and attempt number. `save()` writes JSON for offline analysis.
