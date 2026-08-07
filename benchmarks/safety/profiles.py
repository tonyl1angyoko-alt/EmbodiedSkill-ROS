from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timezone
from enum import Enum
import json
import math
from typing import Any, Iterable

from embodied_skill_ros.backends.mock_backend import FaultEvent, MockRobotBackend
from embodied_skill_ros.execution.outcome_verifier import OutcomeVerifier
from embodied_skill_ros.execution.runtime_guard import RuntimeGuard
from embodied_skill_ros.execution.skill_executor import SkillExecutor
from embodied_skill_ros.grounding.constraint_checker import ConstraintChecker
from embodied_skill_ros.models.evidence import EvidenceRequirement
from embodied_skill_ros.models.freshness import StateFreshnessPolicy
from embodied_skill_ros.models.robot_state import RobotState
from embodied_skill_ros.models.safety_contract import (
    Idempotency,
    RiskClass,
    Rollbackability,
    SkillSafetyContract,
)
from embodied_skill_ros.models.skill_result import CommandReceipt
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan
from embodied_skill_ros.models.transaction import SkillTransaction, TransactionState
from embodied_skill_ros.planner.llm_adapter import LLMPlannerAdapter
from embodied_skill_ros.skills.registry import (
    SkillRegistry,
    build_default_registry,
    build_registry_for_backend,
)

from .model import SafetyPlanStep, SafetyScenario


FIXED_NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)


class ProfileName(str, Enum):
    DIRECT = "A_direct_minimal_assurance"
    GUARDED = "B_guarded_execution"
    CONTRACT_EVIDENCE = "C_contract_evidence"
    FULL = "D_full_transactional_assurance"


PROFILE_NAMES = tuple(ProfileName)


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return "__NaN__"
        return "__Infinity__" if value > 0 else "__-Infinity__"
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


@dataclass(frozen=True)
class ActionObservation:
    step_id: str
    command_count: int = 0
    dispatch_states: tuple[dict[str, Any], ...] = ()
    claimed_physical_success: bool = False
    evidence_backed_success: bool = False
    recovery_actions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "command_count": self.command_count,
            "dispatch_states": _json_safe(self.dispatch_states),
            "claimed_physical_success": self.claimed_physical_success,
            "evidence_backed_success": self.evidence_backed_success,
            "recovery_actions": list(self.recovery_actions),
        }


@dataclass(frozen=True)
class SafetyRunObservation:
    scenario_id: str
    hazard_id: str
    profile: ProfileName
    actions: tuple[ActionObservation, ...]
    recovery_actions: tuple[str, ...]
    stop_attempts: int
    stop_results: tuple[str, ...]
    task_success: bool
    reported_success: bool
    evidence_supported: bool
    final_state: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "hazard_id": self.hazard_id,
            "profile": self.profile.value,
            "actions": [item.to_dict() for item in self.actions],
            "recovery_actions": list(self.recovery_actions),
            "stop_attempts": self.stop_attempts,
            "stop_results": list(self.stop_results),
            "task_success": self.task_success,
            "reported_success": self.reported_success,
            "evidence_supported": self.evidence_supported,
            "final_state": _json_safe(self.final_state),
        }


@dataclass
class _MutableAction:
    step_id: str
    command_count: int = 0
    dispatch_states: list[dict[str, Any]] = field(default_factory=list)
    claimed_physical_success: bool = False
    evidence_backed_success: bool = False
    recovery_actions: list[str] = field(default_factory=list)

    def freeze(self) -> ActionObservation:
        return ActionObservation(
            self.step_id,
            self.command_count,
            tuple(self.dispatch_states),
            self.claimed_physical_success,
            self.evidence_backed_success,
            tuple(self.recovery_actions),
        )


def _decode_special(value: Any) -> Any:
    if value == "__NaN__":
        return float("nan")
    if value == "__Infinity__":
        return float("inf")
    if value == "__-Infinity__":
        return float("-inf")
    if isinstance(value, dict):
        return {key: _decode_special(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_special(item) for item in value]
    return value


def _default_state(changes: dict[str, Any]) -> RobotState:
    values: dict[str, Any] = {
        "left_arm_ready": True,
        "right_arm_ready": True,
        "left_arm_safe": True,
        "right_arm_safe": True,
        "agv_ready": True,
        "agv_moving": False,
        "agv_position_m": 0.0,
        "lift_ready": True,
        "lift_height_mm": 100.0,
        "head_ready": True,
        "head_yaw_deg": 0.0,
        "head_pitch_deg": 0.0,
        "emergency_stop": False,
        "timestamp": FIXED_NOW.isoformat(),
    }
    values.update(_decode_special(changes))
    values["active_resources"] = set(values.get("active_resources", ()))
    allowed = {item.name for item in fields(RobotState)}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"unknown RobotState fixture fields: {sorted(unknown)}")
    return RobotState(**values)


class SafetyBenchmarkBackend(MockRobotBackend):
    """Benchmark-only deterministic backend; it never alters production APIs."""

    def __init__(self, scenario: SafetyScenario):
        super().__init__(_default_state(scenario.initial_state), now_fn=lambda: FIXED_NOW)
        self.scenario = scenario
        fault = scenario.injected_fault
        supported = fault.get("supported_skills")
        self._supported = (
            frozenset(supported) if isinstance(supported, list)
            else super().supported_skills
        )
        self._observe_count = 0
        self._runtime_drift_applied = False
        self.stop_calls = 0
        self.stop_results: list[str] = []
        for event in fault.get("events", []):
            self.inject(
                event["skill"],
                FaultEvent(
                    event["mode"],
                    event.get("message", "benchmark injected fault"),
                    _decode_special(event.get("drift")),
                ),
            )

    @property
    def supported_skills(self) -> frozenset[str]:
        return self._supported

    def peek_state(self) -> RobotState:
        return self._state.copy()

    def observe(self) -> RobotState:
        self._observe_count += 1
        fault = self.scenario.injected_fault
        if (fault.get("kind") == "runtime_state_drift"
                and self._observe_count == 2
                and not self._runtime_drift_applied):
            self._runtime_drift_applied = True
            self.set_state(**_decode_special(fault.get("changes", {})))
        return super().observe()

    def command(self, skill_name: str, arguments: dict[str, Any]) -> CommandReceipt:
        if skill_name != "safe_stop" and skill_name not in self._supported:
            self.command_log.append((skill_name, dict(arguments)))
            return CommandReceipt(False, f"benchmark backend does not support {skill_name}")
        receipt = super().command(skill_name, arguments)
        if receipt.accepted and skill_name != "safe_stop":
            fault = self.scenario.injected_fault
            if fault.get("kind") == "evidence_timestamp":
                self._state = self._state.copy(timestamp=fault.get("timestamp"))
            elif fault.get("kind") == "evidence_value":
                self._state = self._state.copy(
                    **{fault["field"]: _decode_special(fault.get("value"))}
                )
        return receipt

    def stop(self) -> CommandReceipt:
        self.stop_calls += 1
        mode = self.scenario.injected_fault.get("mode")
        if self.scenario.injected_fault.get("kind") == "safe_stop":
            if mode == "exception":
                self.stop_results.append("exception")
                raise RuntimeError("benchmark safe-stop exception")
            if mode == "rejected":
                self.stop_results.append("rejected")
                return CommandReceipt(False, "benchmark safe-stop rejected")
        receipt = super().stop()
        self.stop_results.append("accepted" if receipt.accepted else "rejected")
        return receipt


def _configure_registry(
    registry: SkillRegistry, scenario: SafetyScenario
) -> SkillRegistry:
    fault = scenario.injected_fault
    kind = fault.get("kind")
    if kind == "contract_override":
        try:
            skill = registry.get(fault["skill"])
        except KeyError:
            return registry
        if fault.get("contract") == "missing":
            skill.safety_contract = None
        elif fault.get("contract") == "unknown":
            evidence = (
                skill.safety_contract.evidence_requirements
                if skill.safety_contract is not None else ()
            )
            skill.safety_contract = SkillSafetyContract(
                risk_class=RiskClass.UNKNOWN,
                idempotency=Idempotency.UNKNOWN,
                rollbackability=Rollbackability.UNKNOWN,
                evidence_requirements=evidence,
            )
    state_age = fault.get("maximum_state_age_ms")
    evidence_age = (
        fault.get("maximum_age_ms")
        if kind in {"evidence_timestamp", "evidence_freshness"} else None
    )
    for skill in registry:
        contract = skill.safety_contract
        if contract is None:
            continue
        changes: dict[str, Any] = {}
        if state_age is not None:
            changes["maximum_state_age_ms"] = state_age
        if evidence_age is not None:
            changes["evidence_requirements"] = tuple(
                replace(item, maximum_age_ms=evidence_age)
                for item in contract.evidence_requirements
            )
        if changes:
            skill.safety_contract = replace(contract, **changes)
    return registry


def _scenario_steps(scenario: SafetyScenario) -> list[PlanStep]:
    return [
        PlanStep(item.step_id, item.skill, _decode_special(item.arguments))
        for item in scenario.plan
    ]


def _make_plan(
    scenario: SafetyScenario,
    profile: ProfileName,
    registry: SkillRegistry,
    state: RobotState,
) -> TaskPlan:
    fault = scenario.injected_fault
    if fault.get("kind") == "llm_raw_plan":
        raw = fault["completion"]
        if profile in {ProfileName.CONTRACT_EVIDENCE, ProfileName.FULL}:
            return LLMPlannerAdapter(lambda *_: raw, registry).plan(
                scenario.description, state
            )
        data = json.loads(raw)
        return TaskPlan.from_dict(data)
    return TaskPlan(
        scenario.description,
        _scenario_steps(scenario),
        plan_id=scenario.scenario_id,
    )


def _step_key(
    scenario: SafetyScenario,
    step_id: str,
    skill_name: str,
    arguments: dict[str, Any],
) -> str | None:
    oracle_ids = {item.step_id for item in scenario.oracle.actions}
    if step_id in oracle_ids:
        return step_id
    matches = [
        item.step_id for item in scenario.plan
        if item.skill == skill_name
        and _decode_special(item.arguments) == arguments
    ]
    return matches[0] if len(matches) == 1 else None


def _new_actions(scenario: SafetyScenario) -> dict[str, _MutableAction]:
    return {
        item.step_id: _MutableAction(item.step_id)
        for item in scenario.oracle.actions
    }


def _record_dispatch(
    actions: dict[str, _MutableAction],
    key: str | None,
    state: RobotState | dict[str, Any],
) -> None:
    if key is None or key not in actions:
        return
    action = actions[key]
    action.command_count += 1
    action.dispatch_states.append(
        state.to_dict() if isinstance(state, RobotState) else dict(state)
    )


def _mark_claim(
    actions: dict[str, _MutableAction],
    key: str | None,
    *,
    claimed: bool,
    evidence_backed: bool,
) -> None:
    if key is None or key not in actions:
        return
    actions[key].claimed_physical_success |= claimed
    actions[key].evidence_backed_success |= evidence_backed


def _record_recovery(
    actions: dict[str, _MutableAction], key: str | None, action: str
) -> None:
    if key is not None and key in actions:
        if action not in actions[key].recovery_actions:
            actions[key].recovery_actions.append(action)


def _matches_state(actual: RobotState, expected: dict[str, Any]) -> bool:
    for field_name, target in expected.items():
        observed = getattr(actual, field_name, None)
        if isinstance(target, (int, float)) and not isinstance(target, bool):
            if (not isinstance(observed, (int, float))
                    or isinstance(observed, bool)
                    or not math.isfinite(float(observed))
                    or abs(float(observed) - float(target)) > 1e-6):
                return False
        elif observed != target:
            return False
    return True


def _freeze_run(
    scenario: SafetyScenario,
    profile: ProfileName,
    actions: dict[str, _MutableAction],
    backend: SafetyBenchmarkBackend,
    recovery_actions: Iterable[str],
    reported_success: bool,
    evidence_supported: bool,
) -> SafetyRunObservation:
    final = backend.peek_state()
    return SafetyRunObservation(
        scenario_id=scenario.scenario_id,
        hazard_id=scenario.hazard_id,
        profile=profile,
        actions=tuple(actions[item.step_id].freeze() for item in scenario.oracle.actions),
        recovery_actions=tuple(recovery_actions),
        stop_attempts=backend.stop_calls,
        stop_results=tuple(backend.stop_results),
        task_success=_matches_state(final, scenario.oracle.final_state),
        reported_success=reported_success,
        evidence_supported=evidence_supported,
        final_state=final.to_dict(),
    )


def _run_direct_or_guarded(
    scenario: SafetyScenario, profile: ProfileName
) -> SafetyRunObservation:
    backend = SafetyBenchmarkBackend(scenario)
    validation_registry = build_default_registry()
    guarded_registry = _configure_registry(
        build_registry_for_backend(backend), scenario
    )
    actions = _new_actions(scenario)
    try:
        plan = _make_plan(
            scenario,
            profile,
            guarded_registry if profile is ProfileName.GUARDED else validation_registry,
            backend.peek_state(),
        )
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return _freeze_run(
            scenario, profile, actions, backend, (), False, False
        )

    initial = backend.observe()
    completed = True
    checker = ConstraintChecker(StateFreshnessPolicy(lambda: FIXED_NOW))
    ignored_guard_codes = {
        "MISSING_SAFETY_CONTRACT",
        "INCOMPLETE_SAFETY_CONTRACT",
        "HUMAN_APPROVAL_REQUIRED",
        "STATE_FRESHNESS_INVALID",
    }
    for step in plan.steps:
        key = _step_key(scenario, step.id, step.skill, step.arguments)
        if profile is ProfileName.DIRECT:
            try:
                skill = validation_registry.get(step.skill)
            except KeyError:
                skill = None
            if skill is not None:
                try:
                    skill.validate_arguments(step.arguments)
                except (TypeError, ValueError):
                    completed = False
                    break
            before = backend.observe()
        else:
            try:
                skill = guarded_registry.get(step.skill)
                skill.validate_arguments(step.arguments)
            except (KeyError, TypeError, ValueError):
                completed = False
                break
            initial_reasons = skill.check_preconditions(initial, step.arguments)
            initial_reasons.extend(
                item.message for item in checker.check_step(step, skill, initial)
                if item.code not in ignored_guard_codes
            )
            if initial_reasons:
                completed = False
                break
            before = backend.observe()
            runtime_reasons = skill.check_preconditions(before, step.arguments)
            runtime_reasons.extend(
                item.message for item in checker.check_step(step, skill, before)
                if item.code not in ignored_guard_codes
            )
            if runtime_reasons:
                completed = False
                break
        _record_dispatch(actions, key, before)
        receipt = backend.command(step.skill, step.arguments)
        _mark_claim(
            actions, key, claimed=receipt.accepted, evidence_backed=False
        )
        if not receipt.accepted:
            completed = False
            break
        initial = backend.observe()
    return _freeze_run(
        scenario, profile, actions, backend, (), completed, False
    )


def _guard_reasons(
    checker: ConstraintChecker,
    step: PlanStep,
    skill,
    state: RobotState,
) -> list[str]:
    reasons = skill.check_preconditions(state, step.arguments)
    reasons.extend(item.message for item in checker.check_step(step, skill, state))
    return list(dict.fromkeys(reasons))


def _stop_once(backend: SafetyBenchmarkBackend) -> None:
    try:
        backend.stop()
    except Exception:
        pass


def _run_contract_evidence(scenario: SafetyScenario) -> SafetyRunObservation:
    profile = ProfileName.CONTRACT_EVIDENCE
    backend = SafetyBenchmarkBackend(scenario)
    registry = _configure_registry(build_registry_for_backend(backend), scenario)
    actions = _new_actions(scenario)
    recovery_actions: list[str] = []
    policy = StateFreshnessPolicy(lambda: FIXED_NOW)
    checker = ConstraintChecker(policy)
    verifier = OutcomeVerifier(policy)
    try:
        plan = _make_plan(scenario, profile, registry, backend.peek_state())
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return _freeze_run(
            scenario, profile, actions, backend, recovery_actions, False, True
        )

    pending = list(plan.steps)
    index = 0
    replan_used = False
    state = backend.observe()
    completed = True
    serial = 0
    while index < len(pending):
        step = pending[index]
        key = _step_key(scenario, step.id, step.skill, step.arguments)
        try:
            skill = registry.get(step.skill)
            skill.validate_arguments(step.arguments)
        except (KeyError, TypeError, ValueError):
            completed = False
            _stop_once(backend)
            break
        violation = skill.safety_contract_violation()
        if violation is not None or _guard_reasons(checker, step, skill, state):
            completed = False
            _stop_once(backend)
            break

        step_complete = False
        for attempt in (1, 2):
            serial += 1
            transaction = SkillTransaction(
                f"C:{scenario.scenario_id}:{step.id}:{attempt}:{serial}",
                scenario.scenario_id,
                step.id,
                step.skill,
                dict(step.arguments),
                attempt,
            )
            transaction.transition(TransactionState.ADMITTED, "benchmark contract admission")
            before = backend.observe()
            reasons = _guard_reasons(checker, step, skill, before)
            if reasons:
                transaction.transition(TransactionState.REJECTED, "; ".join(reasons))
                completed = False
                _stop_once(backend)
                break
            transaction.transition(TransactionState.DISPATCHED, "benchmark dispatch boundary")
            _record_dispatch(actions, key, before)
            try:
                receipt = backend.command(step.skill, step.arguments)
            except Exception as exc:
                receipt = CommandReceipt(False, f"command exception: {exc}", timed_out=True)
            after = backend.observe()
            transaction.command_accepted = receipt.accepted
            if receipt.accepted:
                transaction.transition(TransactionState.ACKNOWLEDGED, "command accepted")
                verification = verifier.verify(skill, step.arguments, before, after)
                transaction.apply_verification(verification, verification_enabled=True)
            elif receipt.timed_out:
                transaction.transition(TransactionState.UNVERIFIED, "dispatch outcome uncertain")
            else:
                transaction.transition(TransactionState.REJECTED, "command rejected")
            committed = transaction.state is TransactionState.COMMITTED
            _mark_claim(
                actions,
                key,
                claimed=committed,
                evidence_backed=(
                    committed and bool(transaction.evidence)
                    and all(
                        item.valid and item.matches_expected is True
                        and item.fresh is not False
                        for item in transaction.evidence
                    )
                ),
            )
            state = after
            if committed:
                step_complete = True
                break
            if attempt == 1:
                # Deliberately traditional benchmark-only ablation: it ignores
                # idempotency and retries every uncommitted dispatch once.
                recovery_actions.append("RETRY")
                _record_recovery(actions, key, "RETRY")
                continue
        if not completed:
            break
        if step_complete:
            index += 1
            continue
        fault = scenario.injected_fault
        if fault.get("kind") == "replan" and not replan_used:
            recovery_actions.append("REPLAN_CONTINUATION")
            _record_recovery(actions, key, "REPLAN_CONTINUATION")
            pending = [
                PlanStep(item["step_id"], item["skill"], _decode_special(item["arguments"]))
                for item in fault.get("continuation", [])
            ]
            index = 0
            replan_used = True
            continue
        completed = False
        recovery_actions.append("STOP")
        _record_recovery(actions, key, "STOP")
        _stop_once(backend)
        break
    return _freeze_run(
        scenario, profile, actions, backend, recovery_actions, completed, True
    )


def _full_replanner(scenario: SafetyScenario):
    fault = scenario.injected_fault
    if fault.get("kind") != "replan":
        return None

    def replan(
        continuation: TaskPlan,
        _state: RobotState,
        _completed: tuple[PlanStep, ...],
    ) -> TaskPlan:
        return TaskPlan(
            continuation.goal,
            [
                PlanStep(item["step_id"], item["skill"], _decode_special(item["arguments"]))
                for item in fault.get("continuation", [])
            ],
            continuation.plan_id,
            continuation.revision + 1,
        )

    return replan


def _normalize_decisions(decisions: Iterable[str]) -> tuple[str, ...]:
    mapping = {
        "LOCAL_RETRY": "RETRY",
        "REOBSERVE": "REOBSERVE",
        "REPLAN": "REPLAN_CONTINUATION",
        "STOP": "STOP",
    }
    return tuple(mapping[item] for item in decisions if item in mapping)


def _run_full(scenario: SafetyScenario) -> SafetyRunObservation:
    profile = ProfileName.FULL
    backend = SafetyBenchmarkBackend(scenario)
    registry = _configure_registry(build_registry_for_backend(backend), scenario)
    actions = _new_actions(scenario)
    try:
        plan = _make_plan(scenario, profile, registry, backend.peek_state())
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return _freeze_run(
            scenario, profile, actions, backend, (), False, True
        )
    executor = SkillExecutor(
        registry,
        backend,
        max_retries=1,
        max_replans=1,
        replanner=_full_replanner(scenario),
        freshness_policy=StateFreshnessPolicy(lambda: FIXED_NOW),
    )
    report = executor.execute(plan)
    trace = report.trace
    records = {
        item.transaction_id: item
        for item in (trace.records if trace is not None else [])
        if item.transaction_id is not None
    }
    for transaction in trace.transactions if trace is not None else ():
        key = _step_key(
            scenario,
            transaction.step_id,
            transaction.skill_name,
            transaction.arguments,
        )
        dispatched = any(
            item.to_state is TransactionState.DISPATCHED
            for item in transaction.transitions
        )
        if dispatched:
            record = records.get(transaction.transaction_id)
            state = record.before_state if record is not None else backend.peek_state().to_dict()
            _record_dispatch(actions, key, state)
        committed = transaction.state is TransactionState.COMMITTED
        _mark_claim(
            actions,
            key,
            claimed=committed,
            evidence_backed=(
                committed and bool(transaction.evidence)
                and all(
                    item.valid and item.matches_expected is True
                    and item.fresh is not False
                    for item in transaction.evidence
                )
            ),
        )
    recovery = _normalize_decisions(trace.decisions if trace is not None else ())
    if trace is not None:
        for record in trace.records:
            if not record.recovery_triggered:
                continue
            transaction = next(
                (
                    item for item in trace.transactions
                    if item.transaction_id == record.transaction_id
                ),
                None,
            )
            if transaction is None:
                continue
            key = _step_key(
                scenario,
                transaction.step_id,
                transaction.skill_name,
                transaction.arguments,
            )
            for action in recovery:
                _record_recovery(actions, key, action)
    return _freeze_run(
        scenario, profile, actions, backend, recovery, report.success, True
    )


def run_safety_scenario(
    scenario: SafetyScenario, profile: ProfileName
) -> SafetyRunObservation:
    if profile in {ProfileName.DIRECT, ProfileName.GUARDED}:
        return _run_direct_or_guarded(scenario, profile)
    if profile is ProfileName.CONTRACT_EVIDENCE:
        return _run_contract_evidence(scenario)
    if profile is ProfileName.FULL:
        return _run_full(scenario)
    raise ValueError(f"unknown safety benchmark profile: {profile}")
