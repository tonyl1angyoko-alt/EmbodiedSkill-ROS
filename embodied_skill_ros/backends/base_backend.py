from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models.robot_state import RobotState
from ..models.skill_result import CommandReceipt


class RobotBackend(ABC):
    @property
    def supported_skills(self) -> frozenset[str]:
        """Skills whose complete command semantics this backend implements."""
        return frozenset()

    @abstractmethod
    def observe(self) -> RobotState:
        """Return measured state; unavailable fields must be ``None``."""

    @abstractmethod
    def command(self, skill_name: str, arguments: dict[str, Any]) -> CommandReceipt:
        """Submit one command without claiming its physical effect."""

    def stop(self) -> CommandReceipt:
        return self.command("safe_stop", {})
