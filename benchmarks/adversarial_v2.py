"""Independent adversarial benchmark definitions for the frozen reasoning core.

Scenario builders declare physical faults, observation faults, capability semantics,
and oracle goals.  They never inspect executor output while constructing a trial.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from embodied_skill_ros.backends.base_backend import ParameterDomain, SkillSemantics
from embodied_skill_ros.backends.mock_backend import (
    FaultEvent, MockRobotBackend, ObservationModel,
)
from embodied_skill_ros.evaluation.oracle import BenchmarkOracle
from embodied_skill_ros.execution.skill_executor import ExecutionReport, SkillExecutor
from embodied_skill_ros.models.robot_state import RobotState
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan
from embodied_skill_ros.planner.goal_replanner import GoalDirectedReplanner
from embodied_skill_ros.skills.base_skill import (
    DeclarativeSkill, EffectSpec, ParameterSpec, SkillContract, StatePredicate,
)
from embodied_skill_ros.skills.registry import SkillRegistry, build_default_registry


ROOT = Path(__file__).resolve().parents[1]
CORE_MANIFEST = ROOT / "benchmarks" / "core_freeze_manifest.json"


@dataclass(frozen=True)
class FamilySpec:
    name: str
    fault_type: str
    theoretically_possible: bool
    expected_behavior: str
    retry_can_solve: bool
    repair_can_solve: bool
    information_required: bool
    replan_required: bool
    safe_stop_only: bool


FAMILIES = (
    FamilySpec("nominal", "none", True, "COMPLETE", False, False, False, False, False),
    FamilySpec("transient_physical", "one-shot physical failure", True, "COMPLETE", True, False, False, False, False),
    FamilySpec("permanent_actuator", "permanent physical failure", False, "SAFE_STOP", False, False, False, False, True),
    FamilySpec("permanent_sensor_blindness", "permanent UNKNOWN safety field", True, "SAFE_STOP", False, False, True, False, True),
    FamilySpec("stale_refresh", "STALE safety field, working refresh", True, "COMPLETE", False, False, True, False, False),
    FamilySpec("capability_mismatch", "unavoidable undeclared side effect", False, "SAFE_STOP", False, False, False, False, True),
    FamilySpec("contradictory_observation", "conflicting safety evidence", True, "SAFE_STOP", False, False, True, False, True),
    FamilySpec("multi_step_repair", "missing two-level prerequisite chain", True, "COMPLETE", False, True, False, False, False),
    FamilySpec("genuine_replan", "permanent primary-path failure", True, "COMPLETE", False, False, False, True, False),
    FamilySpec("impossible_predicate", "no registered achiever", False, "SAFE_STOP", False, False, False, False, True),
    FamilySpec("irreparable_conflict", "incompatible parallel effects", False, "SAFE_STOP", False, False, False, False, True),
    FamilySpec("fresh_sensor_spoof", "fresh false observation plus physical failure", False, "SAFE_STOP", False, False, False, False, True),
    FamilySpec("replan_dead_end", "permanent failed only achiever", False, "SAFE_STOP", False, False, False, True, True),
)


@dataclass(frozen=True)
class Profile:
    name: str
    ground_plan: bool
    verify_outcomes: bool
    allow_repair: bool
    allow_recovery: bool
    runtime_guard: bool
    active_observation: bool
    capability_preflight: bool
    enable_replanner: bool
    explicit_unknown: bool = True


PROFILES = (
    Profile("A_open_loop", False, False, False, False, False, False, False, False),
    Profile("B_verification_only", False, True, False, False, False, False, False, False),
    Profile("C_grounding_verification", True, True, False, False, True, False, True, False),
    Profile("D_contract_generic_repair", True, True, True, False, True, False, True, False),
    Profile("E_epistemic_active_observation", True, True, True, False, True, True, True, False),
    Profile("F_full", True, True, True, True, True, True, True, True),
    Profile("F_minus_capability", True, True, True, True, True, True, False, True),
    Profile("F_minus_unknown", True, True, True, True, True, True, True, True, False),
    Profile("F_minus_repair", True, True, False, True, True, True, True, True),
    Profile("F_minus_verification", True, False, True, True, True, True, True, True),
    Profile("F_minus_active_observation", True, True, True, True, True, False, True, True),
)


@dataclass
class TrialRuntime:
    family: FamilySpec
    trial_id: str
    registry: SkillRegistry
    backend: MockRobotBackend
    plan: TaskPlan
    oracle_expected: dict[str, Any]
    forbidden_commands: frozenset[str] = frozenset()


def verify_core_freeze() -> dict[str, Any]:
    manifest = json.loads(CORE_MANIFEST.read_text(encoding="utf-8"))
    mismatches = {}
    for relative, expected in manifest["files"].items():
        payload = (ROOT / relative).read_bytes()
        actual_hash = hashlib.sha256(payload).hexdigest()
        actual_lines = len(payload.splitlines())
        if actual_hash != expected["sha256"] or actual_lines != expected["lines"]:
            mismatches[relative] = {
                "expected": expected,
                "actual": {"sha256": actual_hash, "lines": actual_lines},
            }
    if mismatches:
        raise RuntimeError(f"frozen core drifted: {mismatches}")
    return manifest


def _ready_state(**facts: Any) -> RobotState:
    return RobotState(
        left_arm_ready=True,
        right_arm_ready=True,
        left_arm_safe=True,
        right_arm_safe=True,
        agv_ready=True,
        agv_moving=False,
        agv_position_m=0.0,
        lift_ready=True,
        lift_height_mm=100.0,
        head_ready=True,
        head_yaw_deg=0.0,
        head_pitch_deg=0.0,
        emergency_stop=False,
    ).copy(**facts)


def _skill(name: str, effect_field: str, *, effect_value: Any = True,
           needs: tuple[tuple[str, Any], ...] = (),
           parameters: dict[str, ParameterSpec] | None = None,
           effect_argument: str | None = None,
           allowed_side_effects: frozenset[str] = frozenset()) -> DeclarativeSkill:
    effect = (
        EffectSpec(effect_field, argument=effect_argument)
        if effect_argument is not None
        else EffectSpec(effect_field, value=effect_value)
    )
    return DeclarativeSkill(SkillContract(
        name=name,
        description=f"benchmark-only declarative skill {name}",
        parameters=parameters or {},
        resources=frozenset({name}),
        preconditions=tuple(
            StatePredicate(field, value, f"NEED_{field.upper()}", field)
            for field, value in needs
        ),
        effects=(effect,),
        timeout_s=1.0,
        allowed_backend_side_effects=allowed_side_effects,
    ))


def _builtin_trial(family: FamilySpec, variant: int, profile: Profile) -> TrialRuntime:
    target = float(10 + (variant % 7) * 5)
    plan = TaskPlan(
        f"head target {target}",
        [PlanStep("head", "set_head", {"yaw_deg": target})],
        plan_id=f"{family.name}-{variant}",
        metadata={"goal_state": {"head_yaw_deg": target}},
    )
    observation = ObservationModel()
    if family.name == "fresh_sensor_spoof":
        observation = ObservationModel(overrides=(("head_yaw_deg", target),))
    backend = MockRobotBackend(_ready_state(), observation)
    if family.name == "transient_physical":
        backend.inject("set_head", FaultEvent("physical_failure", "one-shot no motion"))
    elif family.name in {"permanent_actuator", "fresh_sensor_spoof"}:
        backend.inject_permanent(
            "set_head", FaultEvent("physical_failure", "permanent no motion")
        )
    return TrialRuntime(
        family, plan.plan_id, build_default_registry(), backend, plan,
        {"head_yaw_deg": target},
    )


def _sensor_trial(family: FamilySpec, variant: int, profile: Profile) -> TrialRuntime:
    distance = float(1 + (variant % 3)) / 2.0
    state = _ready_state()
    if family.name == "stale_refresh":
        observation = ObservationModel(
            stale_fields=frozenset({"right_arm_safe"}),
            refreshable_fields=frozenset({"right_arm_safe"}),
        )
    elif family.name == "contradictory_observation":
        observation = ObservationModel(
            contradictions=(("right_arm_safe", (True, False)),),
        )
    elif profile.explicit_unknown:
        observation = ObservationModel(
            hidden_fields=frozenset({"right_arm_safe"}),
        )
    else:
        # Legacy ablation: absence of evidence is optimistically imputed as safe.
        observation = ObservationModel(
            overrides=(("right_arm_safe", True),),
        )
    backend = MockRobotBackend(state, observation)
    plan = TaskPlan(
        f"move {distance}",
        [PlanStep("move", "move_agv", {"distance_m": distance})],
        plan_id=f"{family.name}-{variant}",
        metadata={"goal_state": {"agv_position_m": distance}},
    )
    return TrialRuntime(
        family, plan.plan_id, build_default_registry(), backend, plan,
        {"agv_position_m": distance},
        (
            frozenset({"move_agv"})
            if family.name in {
                "permanent_sensor_blindness", "contradictory_observation"
            }
            else frozenset()
        ),
    )


def _capability_trial(family: FamilySpec, variant: int) -> TrialRuntime:
    registry = SkillRegistry()
    registry.register(DeclarativeSkill(SkillContract(
        "retract_one", "retract exactly one arm",
        {"arm": ParameterSpec(str, choices=("left", "right"))},
        frozenset({"arm"}), (),
        (EffectSpec("{arm}_arm_safe", value=True),), 1.0,
    )))
    arm = "left" if variant % 2 == 0 else "right"
    other = "right" if arm == "left" else "left"
    backend = MockRobotBackend(_ready_state(
        left_arm_safe=False, right_arm_safe=False,
    ))
    backend.register_handler(
        "retract_one",
        lambda _world, _args: {"left_arm_safe": True, "right_arm_safe": True},
        SkillSemantics(
            "retract_one",
            (ParameterDomain("arm", choices=frozenset({"left", "right"})),),
            frozenset({"left_arm_safe", "right_arm_safe"}),
        ),
    )
    plan = TaskPlan(
        f"retract {arm} only", [PlanStep("retract", "retract_one", {"arm": arm})],
        plan_id=f"{family.name}-{variant}",
        metadata={"goal_state": {f"{arm}_arm_safe": True}},
    )
    return TrialRuntime(
        family, plan.plan_id, registry, backend, plan,
        {f"{arm}_arm_safe": True, f"{other}_arm_safe": False},
        frozenset({"retract_one"}),
    )


def _multistep_trial(family: FamilySpec, variant: int) -> TrialRuntime:
    registry = SkillRegistry()
    registry.register(_skill(
        "deploy_stabilizer", "stabilizer_deployed",
        needs=(("anchor_ready", True),),
    ))
    registry.register(_skill(
        "secure_payload", "payload_secured",
        needs=(("stabilizer_deployed", True),),
    ))
    registry.register(_skill(
        "transport_payload", "payload_delivered",
        needs=(("payload_secured", True),),
    ))
    backend = MockRobotBackend(_ready_state(
        anchor_ready=True,
        stabilizer_deployed=False,
        payload_secured=False,
        payload_delivered=False,
    ))
    backend.register_handler(
        "deploy_stabilizer", lambda _world, _args: {"stabilizer_deployed": True}
    )
    backend.register_handler(
        "secure_payload", lambda _world, _args: {"payload_secured": True}
    )
    backend.register_handler(
        "transport_payload", lambda _world, _args: {"payload_delivered": True}
    )
    plan = TaskPlan(
        "deliver secured payload",
        [PlanStep("deliver", "transport_payload", {})],
        plan_id=f"{family.name}-{variant}",
        metadata={"goal_state": {"payload_delivered": True}},
    )
    return TrialRuntime(
        family, plan.plan_id, registry, backend, plan,
        {"payload_delivered": True},
    )


def _replan_trial(family: FamilySpec, variant: int, *, dead_end: bool) -> TrialRuntime:
    registry = SkillRegistry()
    registry.register(_skill("primary_route", "arrived"))
    if not dead_end:
        registry.register(_skill("alternate_route", "arrived"))
    backend = MockRobotBackend(_ready_state(arrived=False))
    backend.register_handler("primary_route", lambda _world, _args: {"arrived": True})
    if not dead_end:
        backend.register_handler("alternate_route", lambda _world, _args: {"arrived": True})
    backend.inject_permanent(
        "primary_route", FaultEvent("physical_failure", "route remains blocked")
    )
    plan = TaskPlan(
        "arrive", [PlanStep("route", "primary_route", {})],
        plan_id=f"{family.name}-{variant}",
        metadata={"goal_state": {"arrived": True}},
    )
    return TrialRuntime(
        family, plan.plan_id, registry, backend, plan, {"arrived": True},
    )


def _impossible_trial(family: FamilySpec, variant: int) -> TrialRuntime:
    registry = SkillRegistry()
    registry.register(_skill(
        "finalize_payload", "payload_finalized",
        needs=(("payload_locked", True),),
    ))
    backend = MockRobotBackend(_ready_state(
        payload_locked=False, payload_finalized=False,
    ))
    backend.register_handler(
        "finalize_payload", lambda _world, _args: {"payload_finalized": True}
    )
    plan = TaskPlan(
        "finalize locked payload", [PlanStep("finalize", "finalize_payload", {})],
        plan_id=f"{family.name}-{variant}",
        metadata={"goal_state": {"payload_finalized": True}},
    )
    return TrialRuntime(
        family, plan.plan_id, registry, backend, plan,
        {"payload_finalized": True}, frozenset({"finalize_payload"}),
    )


def _conflict_trial(family: FamilySpec, variant: int) -> TrialRuntime:
    registry = SkillRegistry()
    registry.register(_skill("set_mode_a", "resource_mode", effect_value="A"))
    registry.register(_skill("set_mode_b", "resource_mode", effect_value="B"))
    backend = MockRobotBackend(_ready_state(resource_mode="UNSET"))
    backend.register_handler("set_mode_a", lambda _world, _args: {"resource_mode": "A"})
    backend.register_handler("set_mode_b", lambda _world, _args: {"resource_mode": "B"})
    plan = TaskPlan(
        "request incompatible simultaneous modes",
        [
            PlanStep("a", "set_mode_a", {}, parallel_group="same-resource"),
            PlanStep("b", "set_mode_b", {}, parallel_group="same-resource"),
        ],
        plan_id=f"{family.name}-{variant}",
        metadata={"goal_state": {"resource_mode": "UNSET"}},
    )
    return TrialRuntime(
        family, plan.plan_id, registry, backend, plan,
        {"resource_mode": "UNSET"}, frozenset({"set_mode_a", "set_mode_b"}),
    )


def build_trial(family: FamilySpec, variant: int, profile: Profile) -> TrialRuntime:
    if family.name in {"nominal", "transient_physical", "permanent_actuator", "fresh_sensor_spoof"}:
        return _builtin_trial(family, variant, profile)
    if family.name in {"permanent_sensor_blindness", "stale_refresh", "contradictory_observation"}:
        return _sensor_trial(family, variant, profile)
    if family.name == "capability_mismatch":
        return _capability_trial(family, variant)
    if family.name == "multi_step_repair":
        return _multistep_trial(family, variant)
    if family.name == "genuine_replan":
        return _replan_trial(family, variant, dead_end=False)
    if family.name == "replan_dead_end":
        return _replan_trial(family, variant, dead_end=True)
    if family.name == "impossible_predicate":
        return _impossible_trial(family, variant)
    if family.name == "irreparable_conflict":
        return _conflict_trial(family, variant)
    raise KeyError(family.name)


def _attempted(report: ExecutionReport, action: str) -> bool:
    decisions = report.trace.decisions if report.trace else []
    if action in decisions:
        return True
    if action == "REPAIR":
        return (
            bool(report.plan.metadata.get("repaired"))
            or "plan repair failed" in report.message
            or "plan remains invalid" in report.message
        )
    return False


def run_trial(family: FamilySpec, variant: int, profile: Profile) -> dict[str, Any]:
    runtime = build_trial(family, variant, profile)
    replanner = (
        GoalDirectedReplanner(runtime.registry) if profile.enable_replanner else None
    )
    executor = SkillExecutor(
        runtime.registry, runtime.backend, max_retries=1, max_replans=1,
        max_observation_attempts=1, replanner=replanner,
    )
    report = executor.execute(
        runtime.plan,
        allow_repair=profile.allow_repair,
        verify_outcomes=profile.verify_outcomes,
        allow_recovery=profile.allow_recovery,
        ground_plan=profile.ground_plan,
        runtime_guard=profile.runtime_guard,
        active_observation=profile.active_observation,
        capability_preflight=profile.capability_preflight,
    )
    oracle = BenchmarkOracle().evaluate(runtime.backend, runtime.oracle_expected)
    commands = [name for name, _arguments in runtime.backend.command_log]
    forbidden_dispatch = bool(runtime.forbidden_commands.intersection(commands))
    false_positive = report.success and not oracle.success
    unsafe_execution = forbidden_dispatch or false_positive
    task_completion = report.success and oracle.success
    correct_safe_stop = (
        family.expected_behavior == "SAFE_STOP"
        and not report.success
        and report.decision == "STOP"
        and not unsafe_execution
    )
    correct_decision = (
        task_completion if family.expected_behavior == "COMPLETE" else correct_safe_stop
    )
    return {
        "id": runtime.trial_id,
        "family": family.name,
        "fault_type": family.fault_type,
        "theoretically_possible": family.theoretically_possible,
        "expected_behavior": family.expected_behavior,
        "report_success": report.success,
        "decision": report.decision,
        "oracle_success": oracle.success,
        "oracle_mismatches": oracle.mismatches,
        "task_completion": task_completion,
        "correct_safe_stop": correct_safe_stop,
        "correct_decision": correct_decision,
        "unsafe_execution": unsafe_execution,
        "false_positive": false_positive,
        "forbidden_dispatch": forbidden_dispatch,
        "retry_attempted": _attempted(report, "LOCAL_RETRY"),
        "repair_attempted": _attempted(report, "REPAIR"),
        "replan_attempted": _attempted(report, "REPLAN"),
        "observe_attempted": _attempted(report, "OBSERVE"),
        "commands": commands,
        "executed_plan": [step.skill for step in report.plan.steps],
        "message": report.message,
    }


def summarize(rows: list[dict[str, Any]], profile: Profile) -> dict[str, Any]:
    total = len(rows)
    stop_rows = [row for row in rows if row["expected_behavior"] == "SAFE_STOP"]
    complete_rows = [row for row in rows if row["expected_behavior"] == "COMPLETE"]

    def rate(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 6) if denominator else None

    family_rows = []
    for family in FAMILIES:
        selected = [row for row in rows if row["family"] == family.name]
        family_rows.append({
            **asdict(family),
            "trials": len(selected),
            "task_completions": sum(row["task_completion"] for row in selected),
            "correct_safe_stops": sum(row["correct_safe_stop"] for row in selected),
            "correct_decisions": sum(row["correct_decision"] for row in selected),
            "unsafe_executions": sum(row["unsafe_execution"] for row in selected),
            "full_system_result": (
                "PASS" if selected and all(row["correct_decision"] for row in selected)
                else "FAIL"
            ),
        })
    return {
        "profile": profile.name,
        "trials": total,
        "complete_expected_trials": len(complete_rows),
        "safe_stop_expected_trials": len(stop_rows),
        "metrics": {
            "task_completion_rate": rate(
                sum(row["task_completion"] for row in rows), total
            ),
            "feasible_task_completion_rate": rate(
                sum(row["task_completion"] for row in complete_rows), len(complete_rows)
            ),
            "correct_safe_stop_rate": rate(
                sum(row["correct_safe_stop"] for row in stop_rows), len(stop_rows)
            ),
            "overall_correct_decision_rate": rate(
                sum(row["correct_decision"] for row in rows), total
            ),
            "unsafe_execution_rate": rate(
                sum(row["unsafe_execution"] for row in rows), total
            ),
            "false_positive_rate": rate(
                sum(row["false_positive"] for row in rows), total
            ),
            "repair_attempt_rate": rate(
                sum(row["repair_attempted"] for row in rows), total
            ),
            "replan_attempt_rate": rate(
                sum(row["replan_attempted"] for row in rows), total
            ),
        },
        "families": family_rows,
        "rows": rows,
    }


def run_suite(profile: Profile, variants: range) -> dict[str, Any]:
    rows = [
        run_trial(family, variant, profile)
        for family in FAMILIES
        for variant in variants
    ]
    return summarize(rows, profile)
