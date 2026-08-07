from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .evidence import PhysicalEvidence
from .robot_state import RobotState


@dataclass
class CommandReceipt:
    accepted: bool
    backend_message: str
    call_result: Any = None
    timed_out: bool = False


@dataclass
class VerificationResult:
    achieved: bool
    message: str
    observed: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[PhysicalEvidence, ...] = ()
    evidence_complete: bool = False
    commit_ready: bool = False


@dataclass
class SkillResult:
    skill_name: str
    arguments: dict[str, Any]
    command_accepted: bool
    physical_outcome_achieved: bool | None
    message: str
    before_state: RobotState
    after_state: RobotState
    backend_message: str = ""
    error: str | None = None
    timed_out: bool = False
    recovery_triggered: bool = False
    attempt: int = 1
