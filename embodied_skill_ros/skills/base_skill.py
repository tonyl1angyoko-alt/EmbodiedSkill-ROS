from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
import math
from typing import Any, Callable

from ..backends.base_backend import RobotBackend
from ..models.robot_state import RobotState
from ..models.skill_result import CommandReceipt, VerificationResult


class ParameterError(ValueError):
    pass


@dataclass(frozen=True)
class ParameterSpec:
    python_type: type | tuple[type, ...]
    required: bool = True
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[Any, ...] = ()


@dataclass
class RobotSkill(ABC):
    name: str
    description: str
    parameter_schema: dict[str, ParameterSpec]
    required_resources: set[str]
    preconditions: dict[str, Callable[[RobotState, dict[str, Any]], bool | None]]
    timeout: float
    recovery_policy: tuple[str, ...] = ("local_retry", "replan", "safe_stop")

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        if not isinstance(arguments, dict):
            raise ParameterError("arguments must be an object")
        unknown = set(arguments) - set(self.parameter_schema)
        if unknown:
            raise ParameterError(f"unknown parameters: {sorted(unknown)}")
        for name, spec in self.parameter_schema.items():
            if spec.required and name not in arguments:
                raise ParameterError(f"missing parameter: {name}")
            if name not in arguments:
                continue
            value = arguments[name]
            if isinstance(value, bool) and spec.python_type in (int, float, (int, float)):
                raise ParameterError(f"{name} has wrong type")
            if not isinstance(value, spec.python_type):
                raise ParameterError(f"{name} has wrong type")
            if isinstance(value, (int, float)) and not math.isfinite(float(value)):
                raise ParameterError(f"{name} must be finite")
            if spec.minimum is not None and value < spec.minimum:
                raise ParameterError(f"{name} below minimum {spec.minimum}")
            if spec.maximum is not None and value > spec.maximum:
                raise ParameterError(f"{name} above maximum {spec.maximum}")
            if spec.choices and value not in spec.choices:
                raise ParameterError(f"{name} must be one of {spec.choices}")

    def check_preconditions(self, state: RobotState, arguments: dict[str, Any]) -> list[str]:
        failures = []
        for label, predicate in self.preconditions.items():
            value = predicate(state, arguments)
            if value is not True:
                failures.append(f"{label}: {'UNKNOWN' if value is None else 'false'}")
        return failures

    def execute(self, backend: RobotBackend, arguments: dict[str, Any]) -> CommandReceipt:
        return backend.command(self.name, arguments)

    def expected_effects(self, arguments: dict[str, Any], before: RobotState) -> dict[str, Any]:
        return {}

    def verify_outcome(self, arguments: dict[str, Any], before: RobotState,
                       after: RobotState, tolerance: float = 1e-3) -> VerificationResult:
        expected = self.expected_effects(arguments, before)
        observed = {key: getattr(after, key, None) for key in expected}
        failures = []
        for key, target in expected.items():
            actual = observed[key]
            if isinstance(target, (int, float)) and not math.isfinite(float(target)):
                failures.append(f"expected {key} is non-finite: {target!r}")
            elif isinstance(actual, (int, float)) and not math.isfinite(float(actual)):
                failures.append(f"observed {key} is non-finite: {actual!r}")
            elif actual is None:
                failures.append(f"{key}=UNKNOWN")
            elif isinstance(target, float):
                if not isinstance(actual, (int, float)) or abs(float(actual) - target) > tolerance:
                    failures.append(f"{key}={actual!r}, expected {target!r}")
            elif actual != target:
                failures.append(f"{key}={actual!r}, expected {target!r}")
        return VerificationResult(not failures, "outcome verified" if not failures else "; ".join(failures), observed)
