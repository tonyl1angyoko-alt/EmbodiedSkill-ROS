from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
import re
from typing import Any, Iterable


_SCENARIO_ID_PATTERN = re.compile(r"^H-\d{3}-[a-z0-9][a-z0-9-]*-\d{2}$")


class FaultClass(str, Enum):
    PLANNER = "planner_fault"
    STATE = "state_fault"
    BACKEND = "backend_fault"
    EVIDENCE = "evidence_fault"
    RECOVERY = "recovery_fault"
    CONTROL = "control"


class RecoveryAction(str, Enum):
    RETRY = "RETRY"
    REOBSERVE = "REOBSERVE"
    REPLAN_CONTINUATION = "REPLAN_CONTINUATION"
    STOP = "STOP"


def _required_string(data: dict[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{name} must be a non-empty string")
    return value


def _required_bool(data: dict[str, Any], name: str) -> bool:
    value = data.get(name)
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")
    return value


def _required_dict(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    return dict(value)


def _reject_unknown_keys(
    data: dict[str, Any], allowed: set[str], context: str
) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"{context} has unknown fields: {sorted(unknown)}")


@dataclass(frozen=True)
class SafetyPlanStep:
    step_id: str
    skill: str
    arguments: dict[str, Any]
    planner_metadata: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SafetyPlanStep":
        if not isinstance(data, dict):
            raise TypeError("plan step must be an object")
        _reject_unknown_keys(
            data,
            {"step_id", "skill", "arguments", "planner_metadata"},
            "plan step",
        )
        metadata = data.get("planner_metadata", {})
        if not isinstance(metadata, dict):
            raise TypeError("planner_metadata must be an object")
        return cls(
            step_id=_required_string(data, "step_id"),
            skill=_required_string(data, "skill"),
            arguments=_required_dict(data, "arguments"),
            planner_metadata=dict(metadata),
        )


@dataclass(frozen=True)
class ActionOracle:
    step_id: str
    dispatch_allowed: bool
    commit_allowed: bool
    max_command_count: int
    protected_non_idempotent: bool
    unsupported_capability: bool
    counts_for_frr: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionOracle":
        if not isinstance(data, dict):
            raise TypeError("action oracle must be an object")
        _reject_unknown_keys(
            data,
            {
                "step_id",
                "dispatch_allowed",
                "commit_allowed",
                "max_command_count",
                "protected_non_idempotent",
                "unsupported_capability",
                "counts_for_frr",
            },
            "action oracle",
        )
        maximum = data.get("max_command_count")
        if isinstance(maximum, bool) or not isinstance(maximum, int):
            raise TypeError("max_command_count must be an integer")
        return cls(
            step_id=_required_string(data, "step_id"),
            dispatch_allowed=_required_bool(data, "dispatch_allowed"),
            commit_allowed=_required_bool(data, "commit_allowed"),
            max_command_count=maximum,
            protected_non_idempotent=_required_bool(
                data, "protected_non_idempotent"
            ),
            unsupported_capability=_required_bool(
                data, "unsupported_capability"
            ),
            counts_for_frr=_required_bool(data, "counts_for_frr"),
        )


@dataclass(frozen=True)
class SafetyOracle:
    actions: tuple[ActionOracle, ...]
    stop_required: bool
    allowed_recovery_actions: tuple[RecoveryAction, ...]
    final_state: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SafetyOracle":
        if not isinstance(data, dict):
            raise TypeError("oracle must be an object")
        _reject_unknown_keys(
            data,
            {
                "actions",
                "stop_required",
                "allowed_recovery_actions",
                "final_state",
            },
            "oracle",
        )
        actions = data.get("actions")
        if not isinstance(actions, list):
            raise TypeError("oracle actions must be an array")
        recovery = data.get("allowed_recovery_actions")
        if not isinstance(recovery, list) or not all(
            isinstance(item, str) for item in recovery
        ):
            raise TypeError("allowed_recovery_actions must be an array of strings")
        return cls(
            actions=tuple(ActionOracle.from_dict(item) for item in actions),
            stop_required=_required_bool(data, "stop_required"),
            allowed_recovery_actions=tuple(RecoveryAction(item) for item in recovery),
            final_state=_required_dict(data, "final_state"),
        )


@dataclass(frozen=True)
class SafetyScenario:
    scenario_id: str
    hazard_id: str
    description: str
    positive_control: bool
    fault_class: FaultClass
    initial_state: dict[str, Any]
    plan: tuple[SafetyPlanStep, ...]
    injected_fault: dict[str, Any]
    expected_safe_property: str
    oracle: SafetyOracle

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SafetyScenario":
        if not isinstance(data, dict):
            raise TypeError("scenario must be an object")
        _reject_unknown_keys(
            data,
            {
                "scenario_id",
                "hazard_id",
                "description",
                "positive_control",
                "fault_class",
                "initial_state",
                "plan",
                "injected_fault",
                "expected_safe_property",
                "oracle",
            },
            "scenario",
        )
        plan = data.get("plan")
        if not isinstance(plan, list) or not plan:
            raise TypeError("plan must be a non-empty array")
        oracle = data.get("oracle")
        return cls(
            scenario_id=_required_string(data, "scenario_id"),
            hazard_id=_required_string(data, "hazard_id"),
            description=_required_string(data, "description"),
            positive_control=_required_bool(data, "positive_control"),
            fault_class=FaultClass(_required_string(data, "fault_class")),
            initial_state=_required_dict(data, "initial_state"),
            plan=tuple(SafetyPlanStep.from_dict(item) for item in plan),
            injected_fault=_required_dict(data, "injected_fault"),
            expected_safe_property=_required_string(
                data, "expected_safe_property"
            ),
            oracle=SafetyOracle.from_dict(oracle),
        )


@dataclass(frozen=True)
class SafetyBenchmarkCatalog:
    scenarios: tuple[SafetyScenario, ...]


def _reject_non_finite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def load_safety_scenarios(path: str | Path) -> SafetyBenchmarkCatalog:
    data = json.loads(
        Path(path).read_text(encoding="utf-8"),
        parse_constant=_reject_non_finite_json,
    )
    if not isinstance(data, dict):
        raise TypeError("safety scenario root must be an object")
    _reject_unknown_keys(data, {"schema_version", "scenarios"}, "scenario root")
    if data.get("schema_version") != 1:
        raise ValueError("safety scenario schema_version must be 1")
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list):
        raise TypeError("scenarios must be an array")
    return SafetyBenchmarkCatalog(
        tuple(SafetyScenario.from_dict(item) for item in scenarios)
    )


def validate_safety_scenarios(
    catalog: SafetyBenchmarkCatalog,
    *,
    known_hazard_ids: Iterable[str],
    require_balanced_hazards: bool = False,
) -> tuple[str, ...]:
    """Validate static benchmark truth without invoking runtime safety logic."""

    known = set(known_hazard_ids)
    issues: list[str] = []
    seen_ids: set[str] = set()
    by_hazard: dict[str, list[SafetyScenario]] = {}
    for scenario in catalog.scenarios:
        if not _SCENARIO_ID_PATTERN.fullmatch(scenario.scenario_id):
            issues.append(
                f"{scenario.scenario_id}: scenario_id must match "
                "H-XXX-lowercase-name-NN"
            )
        if not scenario.scenario_id.startswith(f"{scenario.hazard_id}-"):
            issues.append(
                f"{scenario.scenario_id}: scenario_id must start with hazard_id"
            )
        if scenario.scenario_id in seen_ids:
            issues.append(f"{scenario.scenario_id}: duplicate scenario_id")
        seen_ids.add(scenario.scenario_id)
        if scenario.hazard_id not in known:
            issues.append(
                f"{scenario.scenario_id}: unknown hazard_id {scenario.hazard_id}"
            )
        by_hazard.setdefault(scenario.hazard_id, []).append(scenario)

        step_ids = [step.step_id for step in scenario.plan]
        oracle_ids = [action.step_id for action in scenario.oracle.actions]
        if len(step_ids) != len(set(step_ids)):
            issues.append(f"{scenario.scenario_id}: duplicate plan step_id")
        if len(oracle_ids) != len(set(oracle_ids)):
            issues.append(f"{scenario.scenario_id}: duplicate action oracle step_id")
        if set(step_ids) != set(oracle_ids):
            issues.append(
                f"{scenario.scenario_id}: action oracle step_ids must exactly "
                "cover plan step_ids"
            )
        if not scenario.injected_fault.get("kind"):
            issues.append(
                f"{scenario.scenario_id}: injected_fault.kind must be non-empty"
            )
        if not scenario.oracle.final_state:
            issues.append(f"{scenario.scenario_id}: final_state must be non-empty")
        for action in scenario.oracle.actions:
            if action.max_command_count < 0:
                issues.append(
                    f"{scenario.scenario_id}/{action.step_id}: "
                    "max_command_count must be non-negative"
                )
            if action.commit_allowed and not action.dispatch_allowed:
                issues.append(
                    f"{scenario.scenario_id}/{action.step_id}: commit_allowed "
                    "requires dispatch_allowed"
                )

    if require_balanced_hazards:
        for hazard_id in sorted(known):
            scenarios = by_hazard.get(hazard_id, [])
            if not scenarios:
                issues.append(f"{hazard_id}: no benchmark scenarios")
                continue
            if not any(item.positive_control for item in scenarios):
                issues.append(f"{hazard_id}: missing positive control")
            if not any(not item.positive_control for item in scenarios):
                issues.append(f"{hazard_id}: missing adversarial scenario")
            if len(scenarios) < 3:
                issues.append(f"{hazard_id}: requires at least three scenarios")
    return tuple(issues)
