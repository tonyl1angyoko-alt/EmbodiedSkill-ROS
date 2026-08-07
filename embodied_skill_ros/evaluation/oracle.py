from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..models.robot_state import RobotState


class PhysicalTruthProvider(Protocol):
    def oracle_state(self) -> RobotState:
        ...


@dataclass(frozen=True)
class OracleResult:
    success: bool
    mismatches: dict[str, tuple[Any, Any]] = field(default_factory=dict)


class BenchmarkOracle:
    """Scores hidden physical truth without consulting reports or observations."""

    def __init__(self, tolerance: float = 1e-6):
        self.tolerance = tolerance

    def evaluate(self, backend: PhysicalTruthProvider,
                 expected: dict[str, Any]) -> OracleResult:
        state = backend.oracle_state()
        mismatches = {}
        for key, target in expected.items():
            actual = state.raw_value(key)
            matches = (
                isinstance(actual, (int, float))
                and abs(float(actual) - target) <= self.tolerance
            ) if isinstance(target, float) else actual == target
            if not matches:
                mismatches[key] = (actual, target)
        return OracleResult(not mismatches, mismatches)
