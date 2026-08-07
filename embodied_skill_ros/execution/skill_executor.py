from __future__ import annotations

from dataclasses import dataclass, field
import inspect
import time
from typing import Callable

from .outcome_verifier import OutcomeVerifier
from .recovery_manager import (
    FailureKind,
    RecoveryAction,
    RecoveryContext,
    RecoveryManager,
)
from .runtime_guard import RuntimeGuard
from ..backends.base_backend import RobotBackend
from ..grounding.plan_grounder import EmbodiedPlanGrounder
from ..grounding.plan_repairer import PlanRepairer
from ..grounding.constraint_checker import ConstraintChecker
from ..models.freshness import StateFreshnessPolicy
from ..models.robot_state import RobotState
from ..models.skill_result import CommandReceipt, SkillResult
from ..models.task_plan import PlanStep, TaskPlan
from ..models.transaction import SkillTransaction, TransactionState
from ..models.safety_contract import Idempotency
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
    assurance_complete: bool = False


class SkillExecutor:
    def __init__(self, registry: SkillRegistry, backend: RobotBackend,
                 max_retries: int = 1,
                 max_replans: int = 1,
                 replanner: Callable[..., TaskPlan | None] | None = None,
                 freshness_policy: StateFreshnessPolicy | None = None):
        self.registry = registry
        self.backend = backend
        self.state_manager = StateManager(backend)
        self.freshness_policy = freshness_policy or StateFreshnessPolicy()
        checker = ConstraintChecker(self.freshness_policy)
        self.grounder = EmbodiedPlanGrounder(registry, checker)
        self.repairer = PlanRepairer()
        self.guard = RuntimeGuard(checker)
        self.verifier = OutcomeVerifier(self.freshness_policy)
        self.recovery = RecoveryManager(max_retries)
        if max_replans < 0:
            raise ValueError("max_replans must be non-negative")
        self.max_replans = max_replans
        self.replanner = replanner
        self._transaction_serial = 0

    def _new_transaction(self, plan: TaskPlan, step: PlanStep, attempt: int,
                         trace: ExecutionTrace) -> SkillTransaction:
        self._transaction_serial += 1
        transaction = SkillTransaction(
            transaction_id=(
                f"{plan.plan_id}:{plan.revision}:{step.id}:{attempt}:{self._transaction_serial}"
            ),
            plan_id=plan.plan_id,
            step_id=step.id,
            skill_name=step.skill,
            arguments=dict(step.arguments),
            attempt=attempt,
        )
        trace.add_transaction(transaction)
        return transaction

    def _reject_plan_transactions(
        self,
        plan: TaskPlan,
        trace: ExecutionTrace,
        reason: str,
        target: TransactionState = TransactionState.REJECTED,
    ) -> None:
        for step in plan.steps:
            transaction = self._new_transaction(plan, step, 1, trace)
            transaction.transition(target, reason)

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

    def _same_step_semantics(self, first: PlanStep, second: PlanStep) -> bool:
        if first.skill != second.skill:
            return False
        try:
            skill = self.registry.get(first.skill)
        except KeyError:
            return False
        return (
            skill.canonical_arguments(first.arguments)
            == skill.canonical_arguments(second.arguments)
        )

    def _protected_replan_replay(
        self,
        replanned: TaskPlan,
        original_continuation: TaskPlan,
        completed_steps: list[PlanStep],
        completed_states: list[TransactionState],
    ) -> PlanStep | None:
        # Preserve legitimate repeated actions that were already present in the
        # unexecuted continuation. Only additional reintroduced actions are
        # compared with runtime-owned checkpoints.
        unmatched_continuation = list(original_continuation.steps)
        for candidate in replanned.steps:
            continuation_match = next(
                (index for index, pending in enumerate(unmatched_continuation)
                 if self._same_step_semantics(candidate, pending)),
                None,
            )
            if continuation_match is not None:
                unmatched_continuation.pop(continuation_match)
                continue
            for completed, state in zip(completed_steps, completed_states):
                contract = self.registry.get(completed.skill).safety_contract
                protected = state is TransactionState.COMMITTED or (
                    state is TransactionState.UNVERIFIED
                    and contract is not None
                    and contract.idempotency is not Idempotency.IDEMPOTENT
                )
                if protected and self._same_step_semantics(candidate, completed):
                    return candidate
        return None

    @staticmethod
    def _failure_kind(transaction: SkillTransaction, receipt: CommandReceipt,
                      dispatch_exception: Exception | None,
                      verification=None) -> FailureKind:
        if transaction.state is TransactionState.FAILED:
            return FailureKind.OUTCOME_FAILED
        if transaction.state is TransactionState.REJECTED:
            return FailureKind.COMMAND_REJECTED
        if receipt.timed_out or dispatch_exception is not None:
            return FailureKind.DISPATCH_UNCERTAIN
        if (verification is not None
                and any(item.fresh is False for item in verification.evidence)):
            return FailureKind.EVIDENCE_STALE
        return FailureKind.EVIDENCE_UNVERIFIED

    def execute(self, plan: TaskPlan, allow_repair: bool = True,
                verify_outcomes: bool = True, allow_recovery: bool = True,
                ground_plan: bool = True, runtime_guard: bool = True) -> ExecutionReport:
        if not plan.steps:
            return self._stop_and_report(plan, "invalid empty executable plan")
        trace = ExecutionTrace(plan.plan_id)
        state = self.state_manager.refresh()
        decision = "EXECUTE"
        if ground_plan:
            grounding = self.grounder.ground(plan, state)
            if not grounding.valid:
                if grounding.requires_stop:
                    message = "; ".join(i.message for i in grounding.issues)
                    target = (
                        TransactionState.ESCALATED
                        if any(issue.code == "HUMAN_APPROVAL_REQUIRED"
                               for issue in grounding.issues)
                        else TransactionState.REJECTED
                    )
                    self._reject_plan_transactions(plan, trace, message, target)
                    return self._stop_and_report(
                        plan, message, trace=trace
                    )
                if not allow_repair:
                    self._reject_plan_transactions(plan, trace, "plan is not grounded")
                    return self._stop_and_report(plan, "plan is not grounded", trace=trace)
                repaired = self.repairer.repair(plan, state, grounding)
                if repaired is None:
                    self._reject_plan_transactions(plan, trace, "plan repair failed")
                    return self._stop_and_report(plan, "plan repair failed", trace=trace)
                plan = repaired
                decision = "REPAIR"
                grounding = self.grounder.ground(plan, state)
                if not grounding.valid:
                    self._reject_plan_transactions(
                        plan, trace, "repaired plan remains invalid"
                    )
                    return self._stop_and_report(
                        plan, "repaired plan remains invalid", trace=trace
                    )

        trace.decisions.append(decision)
        results: list[SkillResult] = []
        index = 0
        replan_count = 0
        runtime_repair_count = 0
        completed_steps: list[PlanStep] = []
        completed_transaction_states: list[TransactionState] = []
        while index < len(plan.steps):
            step = plan.steps[index]
            try:
                skill = self.registry.get(step.skill)
                skill.validate_arguments(step.arguments)
            except (KeyError, TypeError, ValueError) as exc:
                rejected = self._new_transaction(plan, step, 1, trace)
                rejected.transition(TransactionState.REJECTED, str(exc))
                return self._stop_and_report(plan, str(exc), results, trace)
            contract_violation = skill.safety_contract_violation()
            if contract_violation is not None:
                rejected = self._new_transaction(plan, step, 1, trace)
                target = (
                    TransactionState.ESCALATED
                    if contract_violation[0] == "HUMAN_APPROVAL_REQUIRED"
                    else TransactionState.REJECTED
                )
                rejected.transition(target, contract_violation[1])
                return self._stop_and_report(
                    plan, contract_violation[1], results, trace
                )
            attempt = 1
            admitted_transaction = self._new_transaction(plan, step, attempt, trace)
            admitted_transaction.transition(
                TransactionState.ADMITTED,
                "initial grounding and safety contract admission passed",
            )
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
                        admitted_transaction.transition(
                            TransactionState.REJECTED,
                            "runtime revalidation requires a repaired continuation",
                        )
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
                    admitted_transaction.transition(
                        TransactionState.REJECTED,
                        "runtime guard: " + "; ".join(guard.reasons),
                    )
                    return self._stop_and_report(
                        plan,
                        "runtime guard: " + "; ".join(guard.reasons),
                        results,
                        trace,
                    )
            restart_from_replan = False
            restart_current_step = False
            completed_transaction_state: TransactionState | None = None
            while True:
                transaction = admitted_transaction
                freshness = self.grounder.checker.evaluate_state_freshness(
                    skill, before
                )
                if freshness is not None and not freshness.valid:
                    message = (
                        f"state freshness invalid for skill {skill.name}: "
                        f"{freshness.reason}"
                    )
                    transaction.transition(TransactionState.REJECTED, message)
                    return self._stop_and_report(plan, message, results, trace)
                started = utc_now()
                monotonic_start = time.monotonic()
                transaction.transition(
                    TransactionState.DISPATCHED,
                    "runtime revalidation passed; backend command side-effect boundary entered",
                )
                dispatch_exception = None
                try:
                    receipt = skill.execute(self.backend, step.arguments)
                except Exception as exc:
                    dispatch_exception = exc
                    receipt = CommandReceipt(
                        False,
                        f"backend command raised {type(exc).__name__}: {exc}",
                    )
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
                transaction.command_accepted = receipt.accepted
                if receipt.accepted:
                    transaction.transition(
                        TransactionState.ACKNOWLEDGED,
                        "backend returned an accepted command receipt",
                    )
                    transaction.apply_verification(
                        verification, verification_enabled=verify_outcomes
                    )
                elif receipt.timed_out or dispatch_exception is not None:
                    transaction.transition(
                        TransactionState.UNVERIFIED,
                        "dispatch crossed the backend boundary but its outcome is uncertain",
                    )
                else:
                    transaction.transition(
                        TransactionState.REJECTED,
                        "backend explicitly rejected the command",
                    )
                achieved = receipt.accepted and (
                    transaction.state is TransactionState.COMMITTED
                    if verify_outcomes else True
                )
                if transaction.state is TransactionState.COMMITTED:
                    physical_outcome = True
                    message = verification.message
                elif transaction.state is TransactionState.FAILED:
                    physical_outcome = False
                    message = verification.message
                elif receipt.accepted:
                    physical_outcome = None
                    message = (verification.message if verification is not None
                               else "command accepted; physical outcome not verified")
                else:
                    physical_outcome = None
                    message = receipt.backend_message
                after = self.state_manager.mark_result("success" if achieved else "failure")
                result = SkillResult(skill.name, dict(step.arguments), receipt.accepted,
                                     physical_outcome,
                                     message, before, after, receipt.backend_message,
                                     None if achieved else message,
                                     receipt.timed_out, False, attempt,
                                     transaction.transaction_id, transaction.state.value)
                record = TraceRecord(skill.name, dict(step.arguments), started, utc_now(),
                                     receipt.accepted, receipt.backend_message,
                                     before.to_dict(), after.to_dict(), physical_outcome, message,
                                     result.error, receipt.timed_out, False, attempt,
                                     transaction.transaction_id, transaction.state.value)
                trace.add(record)
                results.append(result)
                if achieved:
                    completed_transaction_state = transaction.state
                    break
                if not allow_recovery:
                    return self._stop_and_report(plan, message, results, trace)
                may_replan = self.replanner is not None and replan_count < self.max_replans
                result.recovery_triggered = True
                record.recovery_triggered = True
                reobserve_count = 0
                recovery = self.recovery.decide(RecoveryContext(
                    contract=skill.safety_contract,
                    failure_kind=self._failure_kind(
                        transaction, receipt, dispatch_exception, verification
                    ),
                    physical_outcome=physical_outcome,
                    transaction_state=transaction.state,
                    dispatch_crossed=True,
                    attempt=attempt,
                    retry_budget_remaining=max(
                        0, self.recovery.max_retries - attempt + 1
                    ),
                    replanner_available=may_replan,
                    reobserve_count=reobserve_count,
                ))
                while recovery.action is RecoveryAction.REOBSERVE:
                    trace.decisions.append("REOBSERVE")
                    reobserve_count += 1
                    observed = self.state_manager.refresh()
                    reobservation = self.verifier.verify(
                        skill, step.arguments, before, observed
                    )
                    transaction.apply_verification(
                        reobservation, verification_enabled=True
                    )
                    if transaction.state is TransactionState.COMMITTED:
                        physical_outcome = True
                        message = reobservation.message
                        achieved = True
                    elif transaction.state is TransactionState.FAILED:
                        physical_outcome = False
                        message = reobservation.message
                        achieved = False
                    else:
                        physical_outcome = None
                        message = reobservation.message
                        achieved = False
                    observed = self.state_manager.mark_result(
                        "success" if achieved else "failure"
                    )
                    result.after_state = observed
                    result.physical_outcome_achieved = physical_outcome
                    result.message = message
                    result.error = None if achieved else message
                    result.transaction_state = transaction.state.value
                    record.after_state = observed.to_dict()
                    record.outcome_verified = physical_outcome
                    record.verification_message = message
                    record.error = result.error
                    record.transaction_state = transaction.state.value
                    if achieved:
                        completed_transaction_state = TransactionState.COMMITTED
                        break
                    recovery = self.recovery.decide(RecoveryContext(
                        contract=skill.safety_contract,
                        failure_kind=self._failure_kind(
                            transaction, receipt, dispatch_exception, reobservation
                        ),
                        physical_outcome=physical_outcome,
                        transaction_state=transaction.state,
                        dispatch_crossed=True,
                        attempt=attempt,
                        retry_budget_remaining=max(
                            0, self.recovery.max_retries - attempt + 1
                        ),
                        replanner_available=may_replan,
                        reobserve_count=reobserve_count,
                    ))
                if achieved:
                    break
                trace.decisions.append(recovery.action.value.upper())
                if recovery.action is RecoveryAction.RETRY:
                    attempt += 1
                    before = self.state_manager.refresh()
                    admitted_transaction = self._new_transaction(
                        plan, step, attempt, trace
                    )
                    admitted_transaction.transition(
                        TransactionState.ADMITTED,
                        "bounded retry passed contract admission",
                    )
                    if runtime_guard:
                        retry_guard = self.guard.check(step, skill, before)
                        if not retry_guard.allowed:
                            admitted_transaction.transition(
                                TransactionState.REJECTED,
                                "retry runtime guard: "
                                + "; ".join(retry_guard.reasons),
                            )
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
                        replayed = self._protected_replan_replay(
                            replanned,
                            continuation,
                            completed_steps,
                            completed_transaction_states,
                        )
                        if replayed is not None:
                            return self._stop_and_report(
                                plan,
                                "replan would replay protected non-idempotent or committed "
                                f"transaction: {replayed.skill}",
                                results,
                                trace,
                            )
                        grounding = self.grounder.ground(replanned, replan_state)
                        if not grounding.valid:
                            if grounding.requires_stop:
                                message = "; ".join(
                                    issue.message for issue in grounding.issues
                                )
                                target = (
                                    TransactionState.ESCALATED
                                    if any(issue.code == "HUMAN_APPROVAL_REQUIRED"
                                           for issue in grounding.issues)
                                    else TransactionState.REJECTED
                                )
                                self._reject_plan_transactions(
                                    replanned, trace, message, target
                                )
                                return self._stop_and_report(
                                    plan,
                                    message,
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
                if recovery.action is RecoveryAction.ESCALATE:
                    transaction.transition(TransactionState.ESCALATED, recovery.reason)
                    result.transaction_state = transaction.state.value
                    record.transaction_state = transaction.state.value
                    return self._stop_and_report(
                        plan, recovery.reason, results, trace
                    )
                return self._stop_and_report(plan, recovery.reason, results, trace)
            if not restart_from_replan and not restart_current_step:
                completed_steps.append(step)
                if completed_transaction_state is not None:
                    completed_transaction_states.append(completed_transaction_state)
                index += 1
        return ExecutionReport(
            True,
            decision,
            plan,
            results,
            trace,
            "task completed",
            assurance_complete=(
                bool(completed_transaction_states)
                and all(state is TransactionState.COMMITTED
                        for state in completed_transaction_states)
            ),
        )
