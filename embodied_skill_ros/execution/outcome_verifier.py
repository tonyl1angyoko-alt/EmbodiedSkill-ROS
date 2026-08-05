from __future__ import annotations

from ..models.robot_state import RobotState
from ..models.skill_result import VerificationResult
from ..skills.base_skill import RobotSkill


class OutcomeVerifier:
    def verify(self, skill: RobotSkill, arguments: dict, before: RobotState,
               after: RobotState) -> VerificationResult:
        return skill.verify_outcome(arguments, before, after)
