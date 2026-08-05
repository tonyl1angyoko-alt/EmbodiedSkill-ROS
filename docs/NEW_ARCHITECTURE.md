# New Architecture

EmbodiedSkill-ROS separates planning semantics from robot transport. The core depends only on typed Python interfaces; ROS2 and JAKA imports remain inside the optional legacy adapter objects supplied by the integrator.

## Component architecture

```mermaid
flowchart TB
    I["Natural-language instruction"] --> P["StructuredPlanner or LLMPlannerAdapter"]
    P --> TP["TaskPlan"]
    SR["SkillRegistry"] --> G["EmbodiedPlanGrounder"]
    SM["StateManager"] --> G
    TP --> G
    G -->|valid| E["SkillExecutor"]
    G -->|repairable| PR["PlanRepairer"]
    PR --> G
    G -->|non-repairable| ST["Safe stop"]
    E --> RG["RuntimeGuard"]
    SR --> RG
    SM --> RG
    RG --> B["RobotBackend"]
    B --> M["MockRobotBackend"]
    B --> J["JakaRobotBackend"]
    J --> L["Existing ROS2 / SDK skill objects"]
    B --> O["Observed RobotState"]
    O --> V["OutcomeVerifier"]
    V --> E
    E --> R["RecoveryManager"]
    R -->|retry| RG
    R -->|state changed| G
    R -->|replan| P
    R -->|unmitigated| ST
    E --> T["ExecutionTrace + metrics"]
```

## Closed-loop execution sequence

```mermaid
sequenceDiagram
    participant User
    participant Planner
    participant Grounder
    participant Executor
    participant Guard
    participant Backend
    participant Verifier
    participant Recovery

    User->>Planner: instruction
    Planner->>Grounder: TaskPlan
    Grounder->>Backend: observe state
    alt plan is repairable
        Grounder->>Grounder: insert preparation / serialize conflict
    else non-repairable fault
        Grounder-->>User: STOP with evidence
    end
    loop every plan step
        Executor->>Backend: observe before state
        Executor->>Guard: preconditions + resources + body constraints
        Guard-->>Executor: execute or re-ground
        Executor->>Backend: command(skill, arguments)
        Backend-->>Executor: CommandReceipt
        Executor->>Backend: observe after state
        Executor->>Verifier: expected effects vs observed state
        Verifier-->>Executor: VerificationResult
        alt physical outcome achieved
            Executor->>Executor: update state and continue
        else recoverable failure
            Executor->>Recovery: failure + retry/replan budget
            Recovery-->>Executor: RETRY / REGROUND / REPLAN
        else risk cannot be mitigated
            Executor->>Backend: safe_stop
        end
    end
```

## Decision policy

The executor implements `EXECUTE → REPAIR → REPLAN → STOP` as an escalation order:

1. Execute a grounded plan.
2. Repair unsafe/UNKNOWN arm state before AGV or lift motion and serialize conflicting parallel groups.
3. Replan once bounded local retry is exhausted, if a replanner is configured.
4. Stop when emergency/fault state is explicit, a repair remains invalid, or retry/replan budgets are exhausted.

`STOP` is therefore a terminal mitigation, not the default response to every mismatch.

## Backend boundary

- `MockRobotBackend` provides deterministic state transitions, command failure, timeout, physical failure, and state-drift injection.
- `JakaRobotBackend` imports no ROS2 module itself. It calls legacy skill objects that are constructed by the original ROS2 application.
- Unobservable fields are `None` (`UNKNOWN`). A callback-based `state_provider` and `agv_position_provider` allow an integrator to add verified observations without changing core code.

## Minimum implemented scope

Five executable skills cover four components: arm retract/extend, AGV move, lift position, and head pose. The deterministic planner intentionally handles only the documented demo language. Arbitrary natural language belongs behind `LLMPlannerAdapter`, whose output is still registry-constrained and grounded before execution.
