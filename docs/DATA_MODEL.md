# Data Model

## `RobotState`

`RobotState` is a timestamped epistemic snapshot. `None` means `UNKNOWN`;
`stale_fields` or an expired per-field `observed_at` timestamp means `STALE`.
Only `KNOWN` and fresh evidence may satisfy a precondition. Dynamic deployment facts
live in the `facts` map, allowing new skills without editing the core dataclass.

| Field group | Fields | Mock | JAKA/Kargo integration |
|---|---|---|---|
| Arms | `left/right_arm_ready`, `left/right_arm_safe` | deterministic | `PoseQuery` supplies joints/readiness; safety remains UNKNOWN without calibrated target+tolerance |
| AGV | `agv_ready`, `agv_moving`, `agv_position_m` | deterministic | odometry + `MotionState`; absent topic data remains UNKNOWN |
| Lift | `lift_ready`, `lift_height_mm` | deterministic | measured by `AxisStatusQuery(0)` |
| Head | `head_ready`, yaw, pitch | deterministic | measured by `AxisStatusQuery(2/3)`; physical pitch sign is normalized |
| Waist | dynamic `facts.waist_angle_deg`, `facts.waist_ready` | optional handler | measured by `AxisStatusQuery(1)` |
| Runtime | `active_resources`, `emergency_stop`, `fault`, `last_skill_result`, timestamp | deterministic | AGV-only E-stop/fault is not promoted to whole-robot state without an explicit deployment assertion |

Each JAKA/Kargo query or topic sample carries an observation time. Query failure
does not reuse command receipt as evidence. A sample exceeding the configured age is
marked STALE through the existing `RobotState` mechanism.

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

## `SkillContract` and `RobotSkill`

Every skill has a declarative contract containing:

- `name` and `description`;
- executable `parameter_schema`;
- `required_resources`;
- equality predicates with diagnostic codes and optional freshness bounds;
- assign/increment effects, including parameterized field templates;
- a timeout and bounded recovery policy;
- `execute()` returning only a `CommandReceipt`;
- incompatible resource declarations used for generic conflict detection;
- `expected_effects()` and `verify_outcome()` derived from the same effects.

`SkillRegistry.synthesize_step()` can invert supported effects to establish a failed
predicate or goal fact. The zero-core-code test registers `prepare_tool` and `dock_tool`
entirely through contracts and Mock handlers.

`ParameterSpec` rejects missing, unknown, incorrectly typed, and out-of-range arguments. Boolean values are not accepted as numbers.

## Result separation

- `CommandReceipt.accepted` means the backend accepted/completed its call path.
- `VerificationResult.achieved` means observed state matches the expected physical effect.
- `SkillResult` stores both values, before/after snapshots, timeout/error data, attempt number, and whether recovery was triggered.

This separation is visible in the recovery demo: the first lift command is accepted, but unchanged height makes `physical_outcome_achieved=false`.

## Trace

`ExecutionTrace` contains plan ID, decisions, and one `TraceRecord` per attempt. A record includes arguments, UTC start/end timestamps, backend response, before/after states, verification, error, timeout, recovery, and attempt number. `save()` writes JSON for offline analysis.
