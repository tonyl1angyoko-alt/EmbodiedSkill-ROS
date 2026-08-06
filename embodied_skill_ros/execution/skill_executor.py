from __future__ import annotations

from dataclasses import dataclass, field
import inspect
import time
from typing import Callable

from .outcome_verifier import OutcomeVerifier
from .recovery_manager import RecoveryAction, RecoveryManager
from .runtime_guard import RuntimeGuard
from ..backends.base_backend import RobotBackend
from ..grounding.plan_grounder import EmbodiedPlanGrounder
from ..grounding.plan_repairer import PlanRepairer
from ..models.robot_state import RobotState
from ..models.skill_result import SkillResult
from ..models.task_plan import PlanStep, TaskPlan
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
    stop_attempted: bool = False
    stop_accepted: bool | None = None
    stop_message: str = ""


class SkillExecutor:
    def __init__(self, registry: SkillRegistry, backend: RobotBackend,
                 max_retries: int = 1,
                 max_replans: int = 1,
                 replanner: Callable[..., TaskPlan | None] | None = None):
        self.registry = registry
        self.backend = backend
        self.state_manager = StateManager(backend)
        self.grounder = EmbodiedPlanGrounder(registry)
        self.repairer = PlanRepairer()
        self.guard = RuntimeGuard()
        self.verifier = OutcomeVerifier()
        self.recovery = RecoveryManager(max_retries)
        if max_replans < 0:
            raise ValueError("max_replans must be non-negative")
        self.max_replans = max_replans
        self.replanner = replanner

    def _stop_and_report(self, plan: TaskPlan, message: str,
                         results: list[SkillResult] | None = None,
                         trace: ExecutionTrace | None = None) -> ExecutionReport:
        if trace is not None:
            trace.decisions.append("STOP")
        try:
            receipt = self.backend.stop()
            stop_accepted = bool(receipt.accepted)
            stop_message = receipt.backend_message
        except Exception as exc:
            stop_accepted = False
            stop_message = f"backend.stop() raised {type(exc).__name__}: {exc}"
        return ExecutionReport(
            False,
            "STOP",
            plan,
            results or [],
            trace,
            message,
            stop_attempted=True,
            stop_accepted=stop_accepted,
            stop_message=stop_message,
        )

    def _invoke_replanner(self, continuation: TaskPlan, state: RobotState,
                          completed_steps: tuple[PlanStep, ...]) -> TaskPlan | None:
        if self.replanner is None:
            return None
        try:
            parameters = inspect.signature(self.replanner).parameters.values()
            positional = [
                item for item in parameters
                if item.kind in (item.POSITIONAL_ONLY, item.POSITIONAL_OR_KEYWORD)
            ]
            accepts_completed = (
                len(positional) >= 3 or any(item.kind is item.VAR_POSITIONAL for item in parameters)
            )
        except (TypeError, ValueError):
            accepts_completed = False
        if accepts_completed:
            return self.replanner(continuation, state, completed_steps)
        return self.replanner(continuation, state)

    def execute(self, plan: TaskPlan, allow_repair: bool = True,
                verify_outcomes: bool = True, allow_recovery: bool = True,
                ground_plan: bool = True, runtime_guard: bool = True) -> ExecutionReport:
        if not plan.steps:
            return self._stop_and_report(plan, "invalid empty executable plan")
        state = self.state_manager.refresh()
        decision = "EXECUTE"
        if ground_plan:
            grounding = self.grounder.ground(plan, state)
            if not grounding.valid:
                if grounding.requires_stop:
                    return self._stop_and_report(
                        plan, "; ".join(i.message for i in grounding.issues)
                    )
                if not allow_repair:
                    return self._stop_and_report(plan, "plan is not grounded")
                repaired = self.repairer.repair(plan, state, grounding)
                if repaired is None:
                    return self._stop_and_report(plan, "plan repair failed")
                plan = repaired
                decision = "REPAIR"
                grounding = self.grounder.ground(plan, state)
                if not grounding.valid:
                    return self._stop_and_report(plan, "repaired plan remains invalid")

        trace = ExecutionTrace(plan.plan_id, decisions=[decision])
        results: list[SkillResult] = []
        index = 0
        replan_count = 0
        runtime_repair_count = 0
        completed_steps: list[PlanStep] = []
        while index < len(plan.steps):
            step = plan.steps[index]
            try:
                skill = self.registry.get(step.skill)
                skill.validate_arguments(step.arguments)
            except (KeyError, TypeError, ValueError) as exc:
                return self._stop_and_report(plan, str(exc), results, trace)
            before = self.state_manager.refresh()
            if runtime_guard:
                guard = self.guard.check(step, skill, before)
                if not guard.allowed:
                    # State may have drifted since initial grounding. Re-ground
                    # only the unexecuted suffix and prefer a local plan repair.
                    remaining = TaskPlan(
                        plan.goal, plan.steps[index:], plan.plan_id, plan.revision, dict(plan.metadata)
                    )
                    suffix_report = self.grounder.ground(remaining, before)
                    repaired = None
                    if allow_repair and not suffix_report.requires_stop and runtime_repair_count < 2:
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
                    return self._stop_and_report(
                        plan,
                        "runtime guard: " + "; ".join(guard.reasons),
                        results,
                        trace,
                    )
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
                if verification is not None:
                    physical_outcome = verification.achieved
                    message = verification.message
                elif receipt.accepted:
                    physical_outcome = None
                    message = "command accepted; physical outcome not verified"
                else:
                    physical_outcome = None
                    message = receipt.backend_message
                after = self.state_manager.mark_result("success" if achieved else "failure")
                result = SkillResult(skill.name, dict(step.arguments), receipt.accepted,
                                     physical_outcome,
                                     message, before, after, receipt.backend_message,
                                     None if achieved else message,
                                     receipt.timed_out, False, attempt)
                record = TraceRecord(skill.name, dict(step.arguments), started, utc_now(),
                                     receipt.accepted, receipt.backend_message,
                                     before.to_dict(), after.to_dict(), physical_outcome, message,
                                     result.error, receipt.timed_out, False, attempt)
                trace.add(record)
                results.append(result)
                if achieved:
                    break
                if not allow_recovery:
                    return self._stop_and_report(plan, message, results, trace)
                may_replan = self.replanner is not None and replan_count < self.max_replans
                recovery = self.recovery.decide(attempt, receipt.timed_out, may_replan)
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
                    continuation = TaskPlan(
                        plan.goal,
                        plan.steps[index:],
                        plan.plan_id,
                        plan.revision,
                        {**plan.metadata, "continuation": True},
                    )
                    replan_state = self.state_manager.refresh()
                    replanned = self._invoke_replanner(
                        continuation, replan_state, tuple(completed_steps)
                    )
                    if replanned is not None:
                        if not replanned.steps:
                            return self._stop_and_report(
                                plan, "replanner returned an empty continuation", results, trace
                            )
                        grounding = self.grounder.ground(replanned, replan_state)
                        if not grounding.valid:
                            if grounding.requires_stop:
                                return self._stop_and_report(
                                    plan,
                                    "; ".join(issue.message for issue in grounding.issues),
                                    results,
                                    trace,
                                )
                            if not allow_repair:
                                return self._stop_and_report(
                                    plan, "replanned continuation is not grounded", results, trace
                                )
                            repaired = self.repairer.repair(replanned, replan_state, grounding)
                            if repaired is None:
                                return self._stop_and_report(
                                    plan, "replanned continuation repair failed", results, trace
                                )
                            replanned = repaired
                            grounding = self.grounder.ground(replanned, replan_state)
                            if not grounding.valid:
                                return self._stop_and_report(
                                    plan,
                                    "repaired replanned continuation remains invalid: "
                                    + "; ".join(issue.message for issue in grounding.issues),
                                    results,
                                    trace,
                                )
                        plan = TaskPlan(
                            replanned.goal,
                            list(completed_steps) + replanned.steps,
                            replanned.plan_id,
                            replanned.revision,
                            {**replanned.metadata, "completed_prefix_preserved": True},
                        )
                        replan_count += 1
                        decision = "REPLAN"
                        index = len(completed_steps)
                        restart_from_replan = True
                        break
                return self._stop_and_report(plan, recovery.reason, results, trace)
            if not restart_from_replan and not restart_current_step:
                completed_steps.append(step)
                index += 1
        return ExecutionReport(True, decision, plan, results, trace, "task completed")
