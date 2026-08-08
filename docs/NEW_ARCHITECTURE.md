# New Architecture

EmbodiedSkill-ROS separates planning semantics from robot transport. The core depends
only on typed Python interfaces; ROS2 and JAKA imports remain inside optional
transport adapters.

## Component architecture

```mermaid
flowchart TB
    I["Natural-language instruction"] --> P["StructuredPlanner or LLMPlannerAdapter"]
    P --> TP["TaskPlan"]
    SR["SkillRegistry"] --> G["EmbodiedPlanGrounder"]
    SM["StateManager"] --> G
    TP --> G
    BC["BackendCapabilities"] --> G
    SC["Declarative SkillContract"] --> G
    G -->|valid| E["SkillExecutor"]
    G -->|repairable| PR["PlanRepairer"]
    PR --> G
    G -->|non-repairable| ST["Safe stop"]
    E --> RG["RuntimeGuard"]
    SR --> RG
    SM --> RG
    RG --> B["RobotBackend"]
    B --> M["MockRobotBackend"]
    B --> J["JakaKargoBackend"]
    J --> SP["State Provider + Capability Mapper"]
    SP --> JT["Lazy exact-schema ROS2 Transport"]
    JT --> L["External JAKA/Kargo ROS2 stack"]
    B --> O["Observed RobotState"]
    B --> HW["Hidden Mock physical world"]
    HW --> BO["Independent benchmark oracle"]
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
2. Repair false/UNKNOWN/STALE predicates by finding registered effects that can
   establish the missing fact; serialize incompatible parallel resources.
3. Re-synthesize unsatisfied goal facts from current observations after bounded retry.
4. Stop when emergency/fault state is explicit, a repair remains invalid, or retry/replan budgets are exhausted.

`STOP` is therefore a terminal mitigation, not the default response to every mismatch.

## Backend boundary

- `MockRobotBackend` keeps physical world truth private from its observation model,
  provides deterministic transitions and fault injection, and exposes truth only to
  the benchmark oracle.
- The earlier `JakaRobotBackend` remains a lightweight object adapter. The v0.3
  `JakaKargoBackend` adds an explicit transport, state provider, and capability
  mapper for the audited laboratory stack; neither path adds vendor imports to the
  frozen core.
- `JakaKargoRos2Transport` lazily loads externally built generated interfaces. The
  original workspace and SDK remain an external deployment dependency.
- Unobservable or uncalibrated fields are `None` (`UNKNOWN`). Service receipt never
  fabricates a state effect.
- Every backend declares supported skills, observable effects, safe-stop support, and
  runtime identity. Unsupported execution stops before command dispatch.
- The optional `mock_bridge` node imports `rclpy` only when invoked and is reserved for
  Ubuntu/Humble runtime validation.

## Minimum implemented scope

The default registry contains five executable skills across arm, AGV, lift, and
head. The JAKA/Kargo integration registry also adds a waist contract without editing
the frozen registry. New declarative skills can be registered without core edits;
the test suite demonstrates this with a tool-preparation/docking pair. The deterministic
planner intentionally handles only the documented demo language. Arbitrary natural
language belongs behind `LLMPlannerAdapter`, whose output is still registry-constrained
and grounded before execution.
