from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RecoveryAction(str, Enum):
    RETRY = "local_retry"
    REPLAN = "replan"
    STOP = "safe_stop"


@dataclass(frozen=True)
class RecoveryDecision:
    action: RecoveryAction
    reason: str


class RecoveryManager:
    def __init__(self, max_retries: int = 1):
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        self.max_retries = max_retries

    def decide(self, attempt: int, timed_out: bool, replanner_available: bool) -> RecoveryDecision:
        if attempt <= self.max_retries:
            reason = "bounded local retry after timeout" if timed_out else "bounded local retry"
            return RecoveryDecision(RecoveryAction.RETRY, reason)
        if replanner_available:
            return RecoveryDecision(RecoveryAction.REPLAN, "retry budget exhausted")
        return RecoveryDecision(RecoveryAction.STOP, "no recovery path remains")
