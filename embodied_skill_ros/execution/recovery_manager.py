from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..models.safety_contract import Idempotency, RiskClass, SkillSafetyContract
from ..models.transaction import TransactionState


class RecoveryAction(str, Enum):
    RETRY = "local_retry"
    REOBSERVE = "reobserve"
    REPLAN = "replan"
    STOP = "safe_stop"
    ESCALATE = "escalate"


class FailureKind(str, Enum):
    COMMAND_REJECTED = "command_rejected"
    DISPATCH_UNCERTAIN = "dispatch_uncertain"
    OUTCOME_FAILED = "outcome_failed"
    EVIDENCE_UNVERIFIED = "evidence_unverified"
    EVIDENCE_STALE = "evidence_stale"


@dataclass(frozen=True)
class RecoveryContext:
    contract: SkillSafetyContract | None
    failure_kind: FailureKind
    physical_outcome: bool | None
    transaction_state: TransactionState
    dispatch_crossed: bool
    attempt: int
    retry_budget_remaining: int
    replanner_available: bool
    reobserve_count: int = 0


@dataclass(frozen=True)
class RecoveryDecision:
    action: RecoveryAction
    reason: str
    requires_human_approval: bool = False


class RecoveryManager:
    """Conservative recovery policy over explicit transaction semantics.

    Risk classes are provisional policy inputs. They can make a response more
    conservative, but never override contract completeness, deterministic
    constraints, idempotency, rollbackability, or physical evidence.
    """

    def __init__(self, max_retries: int = 1, max_reobservations: int = 1):
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if max_reobservations < 0:
            raise ValueError("max_reobservations must be non-negative")
        self.max_retries = max_retries
        self.max_reobservations = max_reobservations

    def decide(self, context: RecoveryContext) -> RecoveryDecision:
        contract = context.contract
        if contract is None:
            return self._escalate("recovery blocked by MISSING_SAFETY_CONTRACT")
        if not contract.is_complete:
            return self._escalate("recovery blocked by INCOMPLETE_SAFETY_CONTRACT")
        if contract.requires_human_approval:
            return self._escalate("skill contract requires human approval")
        if context.transaction_state is TransactionState.COMMITTED:
            if context.physical_outcome is not True:
                return self._escalate(
                    "inconsistent recovery context: COMMITTED requires physical outcome True"
                )
            return RecoveryDecision(
                RecoveryAction.STOP,
                "committed transactions are not eligible for recovery dispatch",
            )
        if (context.transaction_state is TransactionState.FAILED
                and context.physical_outcome is not False):
            return self._escalate(
                "inconsistent recovery context: FAILED requires physical outcome False"
            )
        if (context.transaction_state is TransactionState.UNVERIFIED
                and context.physical_outcome is not None):
            return self._escalate(
                "inconsistent recovery context: UNVERIFIED requires unknown physical outcome"
            )
        if (context.failure_kind is FailureKind.DISPATCH_UNCERTAIN
                and not context.dispatch_crossed):
            return self._escalate(
                "inconsistent recovery context: uncertain dispatch did not cross boundary"
            )

        non_idempotent = contract.idempotency in {
            Idempotency.NON_IDEMPOTENT,
            Idempotency.UNKNOWN,
        }
        if context.dispatch_crossed and non_idempotent:
            if (context.transaction_state is TransactionState.UNVERIFIED
                    and context.reobserve_count < self.max_reobservations):
                return RecoveryDecision(
                    RecoveryAction.REOBSERVE,
                    "non-idempotent dispatch is unverified; observe without redispatch",
                )
            detail = (
                "stale or invalid-timestamp evidence persisted; "
                if context.failure_kind is FailureKind.EVIDENCE_STALE else ""
            )
            return self._escalate(
                detail + "non-idempotent dispatch did not commit; "
                "automatic redispatch is prohibited "
                f"with rollbackability={contract.rollbackability.value}"
            )

        if (context.transaction_state is TransactionState.UNVERIFIED
                and context.reobserve_count < self.max_reobservations):
            return RecoveryDecision(
                RecoveryAction.REOBSERVE,
                "outcome is unverified; observe again before any redispatch",
            )

        if context.failure_kind is FailureKind.EVIDENCE_STALE:
            return self._escalate(
                "stale or invalid-timestamp evidence persisted after bounded reobservation"
            )

        if (contract.risk_class is RiskClass.CRITICAL
                or (contract.risk_class is RiskClass.HIGH
                    and context.transaction_state is TransactionState.UNVERIFIED)):
            return self._escalate(
                "provisional high-risk policy prohibits automatic uncertain recovery"
            )

        retryable_failure = context.failure_kind in {
            FailureKind.COMMAND_REJECTED,
            FailureKind.OUTCOME_FAILED,
            FailureKind.EVIDENCE_UNVERIFIED,
        }
        if (contract.idempotency is Idempotency.IDEMPOTENT
                and contract.risk_class in {RiskClass.LOW, RiskClass.MEDIUM}
                and retryable_failure
                and context.retry_budget_remaining > 0):
            return RecoveryDecision(
                RecoveryAction.RETRY,
                "bounded redispatch of a low/medium-risk idempotent transaction",
            )

        if context.replanner_available:
            return RecoveryDecision(
                RecoveryAction.REPLAN,
                "retry budget exhausted",
            )
        return RecoveryDecision(RecoveryAction.STOP, "no recovery path remains")

    @staticmethod
    def _escalate(reason: str) -> RecoveryDecision:
        return RecoveryDecision(
            RecoveryAction.ESCALATE,
            reason,
            requires_human_approval=True,
        )
