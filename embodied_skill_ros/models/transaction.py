from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .evidence import PhysicalEvidence
from .skill_result import VerificationResult


class TransactionState(str, Enum):
    PROPOSED = "proposed"
    ADMITTED = "admitted"
    DISPATCHED = "dispatched"
    ACKNOWLEDGED = "acknowledged"
    COMMITTED = "committed"
    FAILED = "failed"
    UNVERIFIED = "unverified"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class InvalidTransactionTransition(RuntimeError):
    pass


@dataclass(frozen=True)
class TransactionTransition:
    from_state: TransactionState | None
    to_state: TransactionState
    occurred_at: str
    reason: str
    event: str = "state_transition"


_DIRECT_TRANSITIONS = {
    TransactionState.PROPOSED: frozenset({
        TransactionState.ADMITTED,
        TransactionState.REJECTED,
        TransactionState.ESCALATED,
    }),
    TransactionState.ADMITTED: frozenset({
        TransactionState.DISPATCHED,
        TransactionState.REJECTED,
        TransactionState.ESCALATED,
    }),
    TransactionState.DISPATCHED: frozenset({
        TransactionState.ACKNOWLEDGED,
        TransactionState.REJECTED,
        TransactionState.UNVERIFIED,
        TransactionState.ESCALATED,
    }),
    TransactionState.ACKNOWLEDGED: frozenset({TransactionState.ESCALATED}),
    TransactionState.FAILED: frozenset({TransactionState.ESCALATED}),
    TransactionState.UNVERIFIED: frozenset({TransactionState.ESCALATED}),
    TransactionState.COMMITTED: frozenset(),
    TransactionState.REJECTED: frozenset({TransactionState.ESCALATED}),
    TransactionState.ESCALATED: frozenset(),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SkillTransaction:
    transaction_id: str
    plan_id: str
    step_id: str
    skill_name: str
    arguments: dict[str, Any]
    attempt: int
    state: TransactionState = TransactionState.PROPOSED
    command_accepted: bool | None = None
    evidence: list[PhysicalEvidence] = field(default_factory=list)
    transitions: list[TransactionTransition] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.state is not TransactionState.PROPOSED:
            raise ValueError("a new skill transaction must start in PROPOSED")
        if not self.transitions:
            self.transitions.append(TransactionTransition(
                None,
                TransactionState.PROPOSED,
                _utc_now(),
                "planner or deterministic repair proposed action",
                "transaction_created",
            ))

    def transition(self, target: TransactionState, reason: str) -> None:
        allowed = _DIRECT_TRANSITIONS[self.state]
        if target not in allowed:
            raise InvalidTransactionTransition(
                f"illegal transaction transition {self.state.value} -> {target.value}"
            )
        self._record_transition(target, reason, "state_transition")

    def apply_verification(self, verification: VerificationResult | None,
                           *, verification_enabled: bool) -> None:
        if self.state not in {TransactionState.ACKNOWLEDGED, TransactionState.UNVERIFIED}:
            raise InvalidTransactionTransition(
                f"evidence cannot be applied while transaction is {self.state.value}"
            )
        if verification is not None:
            self.evidence.extend(verification.evidence)
        if not verification_enabled or verification is None:
            target = TransactionState.UNVERIFIED
            reason = "physical outcome verification was not performed"
        elif (verification.commit_ready
              and verification.achieved
              and verification.evidence_complete
              and bool(verification.evidence)
              and all(item.valid
                      and item.matches_expected is True
                      and item.fresh is not False
                      for item in verification.evidence)):
            target = TransactionState.COMMITTED
            reason = "required physical evidence satisfied commit conditions"
        elif verification.evidence_complete and not verification.achieved:
            target = TransactionState.FAILED
            reason = "complete physical evidence shows expected effect was not achieved"
        else:
            target = TransactionState.UNVERIFIED
            reason = "physical evidence is incomplete or invalid"
        self._record_transition(target, reason, "evidence_evaluated")

    def _record_transition(self, target: TransactionState, reason: str, event: str) -> None:
        previous = self.state
        self.state = target
        self.transitions.append(TransactionTransition(
            previous, target, _utc_now(), reason, event
        ))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
