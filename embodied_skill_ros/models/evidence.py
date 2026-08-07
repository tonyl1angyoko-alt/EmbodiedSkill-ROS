from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any


@dataclass(frozen=True)
class EvidenceRequirement:
    """Evidence needed for one dynamic expected-effect field.

    ``state_field`` may contain named argument placeholders such as
    ``{arm}_arm_safe``. The expected value itself remains owned by the skill's
    ``expected_effects`` implementation.
    """

    state_field: str
    source: str = "robot_state"
    tolerance: float | None = 1e-3
    maximum_age_ms: int | None = None
    required: bool = True

    def __post_init__(self) -> None:
        if not self.state_field:
            raise ValueError("evidence state_field must be non-empty")
        if not self.source:
            raise ValueError("evidence source must be non-empty")
        if self.tolerance is not None:
            if (isinstance(self.tolerance, bool)
                    or not isinstance(self.tolerance, (int, float))
                    or not math.isfinite(float(self.tolerance))
                    or self.tolerance < 0):
                raise ValueError("evidence tolerance must be finite and non-negative")
        if (self.maximum_age_ms is not None
                and (isinstance(self.maximum_age_ms, bool)
                     or not isinstance(self.maximum_age_ms, int)
                     or self.maximum_age_ms < 0)):
            raise ValueError("evidence maximum_age_ms must be a non-negative integer or None")

    def resolved_field(self, arguments: dict[str, Any]) -> str:
        return self.state_field.format(**arguments)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PhysicalEvidence:
    """One auditable observation used to evaluate a target effect.

    A missing target effect is not evidence that no physical side effect
    occurred. This model intentionally makes no such claim.
    """

    source: str
    state_field: str
    measured_at: str | None
    received_at: str | None
    observed_value: Any
    expected_value: Any
    tolerance: float | None
    fresh: bool | None
    valid: bool
    matches_expected: bool | None
    reason: str
    age_ms: float | None = None
    maximum_age_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
