from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .evidence import EvidenceRequirement


class RiskClass(str, Enum):
    """Provisional policy input, not a certified or hardware-validated risk level."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class Idempotency(str, Enum):
    IDEMPOTENT = "idempotent"
    NON_IDEMPOTENT = "non_idempotent"
    UNKNOWN = "unknown"


class Rollbackability(str, Enum):
    """Whether this runtime may safely perform automatic transaction rollback."""

    SAFE_AUTOMATIC = "safe_automatic"
    COMPENSATABLE = "compensatable"
    NOT_AUTOMATIC = "not_automatic"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SkillSafetyContract:
    """Safety semantics that supplement, but never replace, a skill definition.

    ``risk_class`` is deliberately provisional research-policy metadata. Runtime
    admission remains dependent on deterministic constraints and every other
    contract field; the risk class alone never authorizes execution.
    """

    risk_class: RiskClass
    idempotency: Idempotency
    rollbackability: Rollbackability
    maximum_state_age_ms: int | None = None
    requires_human_approval: bool = False
    compensation_skill: str | None = None
    risk_class_is_provisional: bool = True
    evidence_requirements: tuple[EvidenceRequirement, ...] = ()

    def __post_init__(self) -> None:
        if (self.maximum_state_age_ms is not None
                and (isinstance(self.maximum_state_age_ms, bool)
                     or not isinstance(self.maximum_state_age_ms, int)
                     or self.maximum_state_age_ms < 0)):
            raise ValueError("maximum_state_age_ms must be a non-negative integer or None")
        if self.compensation_skill is not None and not self.compensation_skill:
            raise ValueError("compensation_skill must be a non-empty string or None")
        if not all(isinstance(item, EvidenceRequirement) for item in self.evidence_requirements):
            raise TypeError("evidence_requirements must contain EvidenceRequirement values")

    @property
    def completeness_issues(self) -> tuple[str, ...]:
        issues = []
        if self.risk_class is RiskClass.UNKNOWN:
            issues.append("risk_class is UNKNOWN")
        if self.idempotency is Idempotency.UNKNOWN:
            issues.append("idempotency is UNKNOWN")
        if self.rollbackability is Rollbackability.UNKNOWN:
            issues.append("rollbackability is UNKNOWN")
        return tuple(issues)

    @property
    def is_complete(self) -> bool:
        return not self.completeness_issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_class": self.risk_class.value,
            "risk_class_is_provisional": self.risk_class_is_provisional,
            "idempotency": self.idempotency.value,
            "rollbackability": self.rollbackability.value,
            "maximum_state_age_ms": self.maximum_state_age_ms,
            "requires_human_approval": self.requires_human_approval,
            "compensation_skill": self.compensation_skill,
            "evidence_requirements": [
                requirement.to_dict() for requirement in self.evidence_requirements
            ],
        }
