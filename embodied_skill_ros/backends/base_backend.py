from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..models.robot_state import RobotState
from ..models.skill_result import CommandReceipt


@dataclass(frozen=True)
class ParameterDomain:
    name: str
    choices: frozenset[Any] | None = None
    minimum: float | None = None
    maximum: float | None = None

    def accepts(self, value: Any) -> bool:
        if self.choices is not None and value not in self.choices:
            return False
        if self.minimum is not None and value < self.minimum:
            return False
        if self.maximum is not None and value > self.maximum:
            return False
        return True


@dataclass(frozen=True)
class SkillSemantics:
    """Backend-specific restrictions not visible in an abstract skill name."""

    skill_name: str
    parameter_domains: tuple[ParameterDomain, ...] = ()
    unavoidable_effect_fields: frozenset[str] = frozenset()

    def validate(self, arguments: dict[str, Any], allowed_effect_fields: set[str]) -> tuple[str, ...]:
        reasons = []
        for domain in self.parameter_domains:
            if domain.name in arguments and not domain.accepts(arguments[domain.name]):
                reasons.append(
                    f"backend parameter domain rejects {domain.name}={arguments[domain.name]!r}"
                )
        extra = self.unavoidable_effect_fields - allowed_effect_fields
        if extra:
            reasons.append(f"backend has undeclared unavoidable effects: {sorted(extra)}")
        return tuple(reasons)


@dataclass(frozen=True)
class BackendCapabilities:
    """Machine-checkable backend boundary used before dispatch."""

    backend_name: str
    supported_skills: frozenset[str] | None = None
    observable_fields: frozenset[str] | None = None
    supports_safe_stop: bool = True
    runtime: str = "python"
    refreshable_fields: frozenset[str] = frozenset()
    skill_semantics: tuple[SkillSemantics, ...] = ()

    def supports(self, skill_name: str) -> bool:
        return self.supported_skills is None or skill_name in self.supported_skills

    def can_observe(self, field: str) -> bool:
        return self.observable_fields is None or field in self.observable_fields

    def can_refresh(self, field: str) -> bool:
        return field in self.refreshable_fields

    def semantics_for(self, skill_name: str) -> SkillSemantics | None:
        return next(
            (item for item in self.skill_semantics if item.skill_name == skill_name), None
        )


class RobotBackend(ABC):
    def capabilities(self) -> BackendCapabilities:
        """Return explicit capabilities; ``None`` sets mean unspecified."""

        return BackendCapabilities(type(self).__name__)

    @abstractmethod
    def observe(self) -> RobotState:
        """Return measured state; unavailable fields must be ``None``."""

    @abstractmethod
    def command(self, skill_name: str, arguments: dict[str, Any]) -> CommandReceipt:
        """Submit one command without claiming its physical effect."""

    def stop(self) -> CommandReceipt:
        return self.command("safe_stop", {})

    def acquire(self, fields: set[str]) -> RobotState:
        """Request fresh evidence. Backends without active sensing just observe."""

        return self.observe()
