from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Any

from ..backends.base_backend import RobotBackend
from ..models.robot_state import KnowledgeStatus, RobotState
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


class TruthValue(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PredicateEvaluation:
    code: str
    field: str
    expected: Any
    actual: Any
    truth: TruthValue
    knowledge: KnowledgeStatus
    label: str

    @property
    def satisfied(self) -> bool:
        return self.truth is TruthValue.TRUE

    @property
    def message(self) -> str:
        if self.knowledge is not KnowledgeStatus.KNOWN:
            detail = self.knowledge.value
        else:
            detail = f"{self.actual!r}, expected {self.expected!r}"
        return f"{self.label}: {detail}"


@dataclass(frozen=True)
class StatePredicate:
    """A serializable equality predicate over epistemic robot state."""

    field: str
    expected: Any
    code: str
    label: str
    max_age_s: float | None = None

    def resolved_field(self, arguments: dict[str, Any]) -> str:
        return self.field.format(**arguments)

    def evaluate(self, state: RobotState, arguments: dict[str, Any]) -> PredicateEvaluation:
        field_name = self.resolved_field(arguments)
        evidence = state.epistemic_value(field_name, max_age_s=self.max_age_s)
        if evidence.status is not KnowledgeStatus.KNOWN:
            truth = TruthValue.UNKNOWN
        else:
            truth = TruthValue.TRUE if evidence.value == self.expected else TruthValue.FALSE
        return PredicateEvaluation(
            self.code, field_name, self.expected, evidence.value, truth,
            evidence.status, self.label,
        )


_UNSET = object()


@dataclass(frozen=True)
class EffectSpec:
    """Declarative state transition and verification rule.

    ``operation`` is either ``assign`` or ``increment``. A value can come from
    a literal or an argument. Field templates (for example
    ``{arm}_arm_safe``) allow one contract to describe parameterized state.
    """

    field: str
    operation: str = "assign"
    value: Any = _UNSET
    argument: str | None = None
    when_argument: str | None = None
    tolerance: float = 1e-3

    def __post_init__(self) -> None:
        if self.operation not in {"assign", "increment"}:
            raise ValueError(f"unsupported effect operation: {self.operation}")
        if self.value is _UNSET and self.argument is None:
            raise ValueError("effect requires a literal value or argument")

    def active(self, arguments: dict[str, Any]) -> bool:
        return self.when_argument is None or self.when_argument in arguments

    def resolved_field(self, arguments: dict[str, Any]) -> str:
        return self.field.format(**arguments)

    def expected_value(self, arguments: dict[str, Any], before: RobotState) -> Any:
        operand = arguments[self.argument] if self.argument is not None else self.value
        if self.operation == "assign":
            return float(operand) if isinstance(operand, (int, float)) and not isinstance(operand, bool) else operand
        current = before.raw_value(self.resolved_field(arguments))
        if current is None:
            return None
        return float(current) + float(operand)

    def _bindings_for_field(self, concrete_field: str) -> dict[str, str] | None:
        names = re.findall(r"{([A-Za-z_][A-Za-z0-9_]*)}", self.field)
        pattern = re.escape(self.field)
        for name in names:
            pattern = pattern.replace(r"\{" + name + r"\}", f"(?P<{name}>[^.]+?)")
        match = re.fullmatch(pattern, concrete_field)
        return match.groupdict() if match else None

    def synthesize_arguments(self, concrete_field: str, target: Any,
                             state: RobotState) -> dict[str, Any] | None:
        bindings = self._bindings_for_field(concrete_field)
        if bindings is None:
            return None
        arguments: dict[str, Any] = dict(bindings)
        if self.operation == "assign":
            if self.argument is None:
                if self.value != target:
                    return None
            else:
                arguments[self.argument] = target
        else:
            if self.argument is None:
                return None
            current = state.raw_value(concrete_field)
            if not isinstance(current, (int, float)) or not isinstance(target, (int, float)):
                return None
            arguments[self.argument] = float(target) - float(current)
        return arguments


@dataclass(frozen=True)
class SkillContract:
    name: str
    description: str
    parameters: dict[str, ParameterSpec]
    resources: frozenset[str]
    preconditions: tuple[StatePredicate, ...]
    effects: tuple[EffectSpec, ...]
    timeout_s: float
    recovery_policy: tuple[str, ...] = (
        "observe", "repair", "local_retry", "replan", "safe_stop"
    )
    incompatible_resources: frozenset[str] = frozenset()
    allowed_backend_side_effects: frozenset[str] = frozenset()


class RobotSkill:
    """Executable skill whose planning semantics live in a declarative contract."""

    def __init__(self, contract: SkillContract):
        self.contract = contract

    @property
    def name(self) -> str:
        return self.contract.name

    @property
    def description(self) -> str:
        return self.contract.description

    @property
    def parameter_schema(self) -> dict[str, ParameterSpec]:
        return self.contract.parameters

    @property
    def required_resources(self) -> set[str]:
        return set(self.contract.resources)

    @property
    def preconditions(self) -> tuple[StatePredicate, ...]:
        return self.contract.preconditions

    @property
    def effect_specs(self) -> tuple[EffectSpec, ...]:
        return self.contract.effects

    @property
    def timeout(self) -> float:
        return self.contract.timeout_s

    @property
    def recovery_policy(self) -> tuple[str, ...]:
        return self.contract.recovery_policy

    @property
    def incompatible_resources(self) -> set[str]:
        return set(self.contract.incompatible_resources)

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
            if isinstance(value, float) and not math.isfinite(value):
                raise ParameterError(f"{name} must be finite")
            if spec.minimum is not None and value < spec.minimum:
                raise ParameterError(f"{name} below minimum {spec.minimum}")
            if spec.maximum is not None and value > spec.maximum:
                raise ParameterError(f"{name} above maximum {spec.maximum}")
            if spec.choices and value not in spec.choices:
                raise ParameterError(f"{name} must be one of {spec.choices}")

    def evaluate_preconditions(self, state: RobotState,
                               arguments: dict[str, Any]) -> list[PredicateEvaluation]:
        return [item.evaluate(state, arguments) for item in self.preconditions]

    def check_preconditions(self, state: RobotState, arguments: dict[str, Any]) -> list[str]:
        return [item.message for item in self.evaluate_preconditions(state, arguments)
                if not item.satisfied]

    def execute(self, backend: RobotBackend, arguments: dict[str, Any]) -> CommandReceipt:
        return backend.command(self.name, arguments)

    def expected_effects(self, arguments: dict[str, Any], before: RobotState) -> dict[str, Any]:
        return {
            effect.resolved_field(arguments): effect.expected_value(arguments, before)
            for effect in self.effect_specs if effect.active(arguments)
        }

    def verify_outcome(self, arguments: dict[str, Any], before: RobotState,
                       after: RobotState, tolerance: float | None = None) -> VerificationResult:
        expected = self.expected_effects(arguments, before)
        evidence = {key: after.epistemic_value(key) for key in expected}
        observed = {key: item.value for key, item in evidence.items()}
        failures = []
        specs = {
            effect.resolved_field(arguments): effect
            for effect in self.effect_specs if effect.active(arguments)
        }
        for key, target in expected.items():
            actual = observed[key]
            if evidence[key].status is not KnowledgeStatus.KNOWN:
                failures.append(f"{key}={evidence[key].status.value}")
            elif actual is None or target is None:
                failures.append(f"{key}=UNKNOWN")
            elif isinstance(target, float):
                allowed = specs[key].tolerance if tolerance is None else tolerance
                if not isinstance(actual, (int, float)) or abs(float(actual) - target) > allowed:
                    failures.append(f"{key}={actual!r}, expected {target!r}")
            elif actual != target:
                failures.append(f"{key}={actual!r}, expected {target!r}")
        return VerificationResult(
            not failures,
            "outcome verified" if not failures else "; ".join(failures),
            observed,
        )


class DeclarativeSkill(RobotSkill):
    """A skill extension point requiring no core subclass implementation."""
    pass
