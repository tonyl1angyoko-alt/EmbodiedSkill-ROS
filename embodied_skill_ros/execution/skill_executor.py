from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Callable

from .outcome_verifier import OutcomeVerifier
from .recovery_manager import RecoveryAction, RecoveryManager
from .runtime_guard import RuntimeGuard
from ..backends.base_backend import RobotBackend
from ..grounding.plan_grounder import EmbodiedPlanGrounder
from ..grounding.plan_repairer import PlanRepairer
from ..models.skill_result import SkillResult
from ..models.robot_state import KnowledgeStatus, RobotState
from ..models.task_plan import TaskPlan
from ..skills.registry import SkillRegistry
from ..state.state_manager import StateManager
from ..tracing.execution_trace import ExecutionTrace, TraceRecord, utc_now


@dataclass
class ExecutionReport:
    success: bool
    decision: str
    plan: TaskPlan
    results: list[SkillResult] = field(default_factory=list)
    trace: ExecutionTrace | None = None
    message: str = ""


class SkillExecutor:
    def __init__(self, registry: SkillRegistry, backend: RobotBackend,
                 max_retries: int = 1,
                 max_replans: int = 1,
                 max_observation_attempts: int = 1,
                 replanner: Callable[[TaskPlan, RobotState], TaskPlan | None] | None = None):
        self.registry = registry
        self.backend = backend
        self.state_manager = StateManager(backend)
        self.grounder = EmbodiedPlanGrounder(registry)
        self.repairer = PlanRepairer(registry)
        self.guard = RuntimeGuard()
        self.verifier = OutcomeVerifier()
        self.recovery = RecoveryManager(max_retries)
        if max_replans < 0:
            raise ValueError("max_replans must be non-negative")
        if max_observation_attempts < 0:
            raise ValueError("max_observation_attempts must be non-negative")
        self.max_replans = max_replans
        self.max_observation_attempts = max_observation_attempts
        self.replanner = replanner

    def _with_goal_state(self, plan: TaskPlan, state: RobotState) -> TaskPlan:
        if isinstance(plan.metadata.get("goal_state"), dict):
            return plan
        projected = state
        goals = {}
        for step in plan.steps:
            try:
                skill = self.registry.get(step.skill)
                effects = skill.expected_effects(step.arguments, projected)
            except (KeyError, TypeError, ValueError):
                continue
            goals.update({key: value for key, value in effects.items() if value is not None})
            projected = projected.copy(**effects)
        return TaskPlan(
            plan.goal, list(plan.steps), plan.plan_id, plan.revision,
            {**plan.metadata, "goal_state": goals, "goal_state_source": "projected_plan"},
        )

    @staticmethod
    def _goal_mismatches(plan: TaskPlan, state: RobotState) -> dict[str, tuple[object, object]]:
        goals = plan.metadata.get("goal_state", {})
        if not isinstance(goals, dict):
            return {"goal_state": (goals, "mapping")}
        mismatches = {}
        for field, target in goals.items():
            evidence = state.epistemic_value(field)
            actual = evidence.value
            matches = (
                isinstance(actual, (int, float))
                and abs(float(actual) - target) <= 1e-3
            ) if isinstance(target, float) else actual == target
            if evidence.status is not KnowledgeStatus.KNOWN or not matches:
                mismatches[field] = (actual, target)
        return mismatches

    def _policy_for_issue(self, plan: TaskPlan, step_id: str) -> tuple[str, ...]:
        step = next((item for item in plan.steps if item.id == step_id), None)
        if step is None:
            return ()
        try:
            return self.registry.get(step.skill).recovery_policy
        except KeyError:
            return ()

    def _observable_issue_fields(self, plan: TaskPlan, grounding: object,
                                 capabilities: object) -> set[str]:
        fields = set()
        for issue in grounding.issues:
            if (
                issue.field
                and issue.knowledge in {
                    KnowledgeStatus.UNKNOWN, KnowledgeStatus.STALE,
                    KnowledgeStatus.CONTRADICTORY,
                }
                and capabilities.can_refresh(issue.field)
                and "observe" in self._policy_for_issue(plan, issue.step_id)
            ):
                fields.add(issue.field)
        return fields

    def execute(self, plan: TaskPlan, allow_repair: bool = True,
                verify_outcomes: bool = True, allow_recovery: bool = True,
                ground_plan: bool = True, runtime_guard: bool = True,
                active_observation: bool = True,
                capability_preflight: bool = True) -> ExecutionReport:
        state = self.state_manager.refresh()
        plan = self._with_goal_state(plan, state)
        backend_capabilities = self.backend.capabilities()
        capabilities = backend_capabilities if capability_preflight else None
        decision = "EXECUTE"
        preflight_decisions: list[str] = []
        if ground_plan:
            grounding = self.grounder.ground(plan, state, capabilities)
            observation_attempts = 0
            while (
                not grounding.valid and not grounding.requires_stop
                and active_observation
                and observation_attempts < self.max_observation_attempts
            ):
                fields = self._observable_issue_fields(
                    plan, grounding, backend_capabilities
                )
                if not fields:
                    break
                state = self.state_manager.acquire(fields)
                observation_attempts += 1
                decision = "OBSERVE"
                preflight_decisions.append("OBSERVE")
                grounding = self.grounder.ground(plan, state, capabilities)
            if not grounding.valid:
                if grounding.requires_stop:
                    return ExecutionReport(False, "STOP", plan,
                                           message="; ".join(i.message for i in grounding.issues))
                repair_allowed_by_policy = all(
                    "repair" in self._policy_for_issue(plan, issue.step_id)
                    for issue in grounding.issues if issue.repairable
                )
                if not allow_repair or not repair_allowed_by_policy:
                    return ExecutionReport(False, "STOP", plan, message="plan is not grounded")
                repaired = self.repairer.repair(plan, state, grounding)
                if repaired is None:
                    return ExecutionReport(
                        False, "STOP", plan,
                        message=f"UNSATISFIABLE: plan repair failed; "
                        f"search={self.repairer.last_search_stats}",
                    )
                plan = repaired
                decision = "REPAIR"
                preflight_decisions.append("REPAIR")
                grounding = self.grounder.ground(plan, state, capabilities)
                if not grounding.valid:
                    return ExecutionReport(False, "STOP", plan, message="repaired plan remains invalid")

        trace = ExecutionTrace(
            plan.plan_id, decisions=preflight_decisions or [decision]
        )
        results: list[SkillResult] = []
        index = 0
        replan_count = 0
        runtime_repair_count = 0
        while index < len(plan.steps):
            step = plan.steps[index]
            try:
                skill = self.registry.get(step.skill)
                skill.validate_arguments(step.arguments)
            except (KeyError, TypeError, ValueError) as exc:
                self.backend.stop()
                trace.decisions.append("STOP")
                return ExecutionReport(False, "STOP", plan, results, trace, str(exc))
            before = self.state_manager.refresh()
            if runtime_guard:
                guard = self.guard.check(step, skill, before)
                if not guard.allowed:
                    # State may have drifted since initial grounding. Re-ground
                    # only the unexecuted suffix and prefer a local plan repair.
                    remaining = TaskPlan(
                        plan.goal, plan.steps[index:], plan.plan_id, plan.revision, dict(plan.metadata)
                    )
                    suffix_report = self.grounder.ground(remaining, before, capabilities)
                    repaired = None
                    if (
                        active_observation and "observe" in skill.recovery_policy
                        and runtime_repair_count < self.max_observation_attempts
                    ):
                        fields = self._observable_issue_fields(
                            remaining, suffix_report, backend_capabilities
                        )
                        if fields:
                            self.state_manager.acquire(fields)
                            runtime_repair_count += 1
                            trace.decisions.append("OBSERVE")
                            continue
                    if (
                        allow_repair and "repair" in skill.recovery_policy
                        and not suffix_report.requires_stop and runtime_repair_count < 2
                    ):
                        repaired = self.repairer.repair(remaining, before, suffix_report)
                    if repaired is not None and repaired.steps != remaining.steps:
                        plan = TaskPlan(
                            plan.goal,
                            plan.steps[:index] + repaired.steps,
                            plan.plan_id,
                            max(plan.revision, repaired.revision),
                            {**plan.metadata, "runtime_repaired": True},
                        )
                        runtime_repair_count += 1
                        decision = "REPAIR" if decision == "EXECUTE" else decision
                        trace.decisions.append("REPAIR")
                        continue
                    self.backend.stop()
                    trace.decisions.append("STOP")
                    return ExecutionReport(False, "STOP", plan, results, trace,
                                           "runtime guard: " + "; ".join(guard.reasons))
            attempt = 1
            restart_from_replan = False
            restart_current_step = False
            while True:
                started = utc_now()
                monotonic_start = time.monotonic()
                receipt = skill.execute(self.backend, step.arguments)
                elapsed = time.monotonic() - monotonic_start
                if elapsed > skill.timeout:
                    receipt.accepted = False
                    receipt.timed_out = True
                    receipt.backend_message = (
                        f"skill exceeded timeout: {elapsed:.3f}s > {skill.timeout:.3f}s"
                    )
                after = self.state_manager.refresh()
                verification = (self.verifier.verify(skill, step.arguments, before, after)
                                if receipt.accepted and verify_outcomes
                                else None)
                achieved = receipt.accepted and (verification.achieved if verification else True)
                message = verification.message if verification else receipt.backend_message
                after = self.state_manager.mark_result("success" if achieved else "failure")
                result = SkillResult(skill.name, dict(step.arguments), receipt.accepted, achieved,
                                     message, before, after, receipt.backend_message,
                                     None if achieved else message,
                                     receipt.timed_out, False, attempt)
                record = TraceRecord(skill.name, dict(step.arguments), started, utc_now(),
                                     receipt.accepted, receipt.backend_message,
                                     before.to_dict(), after.to_dict(), achieved, message,
                                     result.error, receipt.timed_out, False, attempt)
                trace.add(record)
                results.append(result)
                if achieved:
                    break
                if not allow_recovery:
                    self.backend.stop()
                    trace.decisions.append("STOP")
                    return ExecutionReport(False, "STOP", plan, results, trace, message)
                may_replan = self.replanner is not None and replan_count < self.max_replans
                recovery = self.recovery.decide(
                    attempt, receipt.timed_out, may_replan, skill.recovery_policy
                )
                result.recovery_triggered = True
                record.recovery_triggered = True
                trace.decisions.append(recovery.action.value.upper())
                if recovery.action is RecoveryAction.RETRY:
                    attempt += 1
                    before = self.state_manager.refresh()
                    if runtime_guard:
                        retry_guard = self.guard.check(step, skill, before)
                        if not retry_guard.allowed:
                            # Return to the outer loop so the changed state is
                            # re-grounded and, when possible, repaired before
                            # another physical command is sent.
                            trace.decisions.append("REGROUND")
                            restart_current_step = True
                            break
                    continue
                if recovery.action is RecoveryAction.REPLAN and self.replanner:
                    blocked = set(plan.metadata.get("blocked_skills", ()))
                    blocked.add(skill.name)
                    failed_plan = TaskPlan(
                        plan.goal, list(plan.steps), plan.plan_id, plan.revision,
                        {
                            **plan.metadata,
                            "blocked_skills": sorted(blocked),
                            "failed_skill": skill.name,
                            "failed_arguments": dict(step.arguments),
                        },
                    )
                    replanned = self.replanner(
                        failed_plan, self.state_manager.refresh()
                    )
                    if replanned is not None:
                        replanned = self._with_goal_state(replanned, self.state_manager.refresh())
                        replanned_grounding = self.grounder.ground(
                            replanned, self.state_manager.refresh(), capabilities
                        )
                        if not replanned_grounding.valid:
                            repaired = self.repairer.repair(
                                replanned, self.state_manager.refresh(), replanned_grounding
                            )
                            if repaired is None or not self.grounder.ground(
                                    repaired, self.state_manager.refresh(), capabilities).valid:
                                replanned = None
                            else:
                                replanned = repaired
                    if replanned is not None:
                        plan = replanned
                        replan_count += 1
                        decision = "REPLAN"
                        index = 0
                        restart_from_replan = True
                        break
                self.backend.stop()
                trace.decisions.append("STOP")
                return ExecutionReport(False, "STOP", plan, results, trace, recovery.reason)
            if not restart_from_replan and not restart_current_step:
                index += 1
        if verify_outcomes:
            mismatches = self._goal_mismatches(plan, self.state_manager.refresh())
            if mismatches:
                self.backend.stop()
                trace.decisions.append("STOP")
                return ExecutionReport(
                    False, "STOP", plan, results, trace,
                    f"final goal not achieved: {mismatches}",
                )
        return ExecutionReport(True, decision, plan, results, trace, "task completed")
