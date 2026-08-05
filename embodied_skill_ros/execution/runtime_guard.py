from __future__ import annotations

from dataclasses import dataclass

from ..grounding.constraint_checker import ConstraintChecker
from ..models.robot_state import RobotState
from ..models.task_plan import PlanStep
from ..skills.base_skill import RobotSkill


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    reasons: tuple[str, ...] = ()


class RuntimeGuard:
    def __init__(self, checker: ConstraintChecker | None = None):
        self.checker = checker or ConstraintChecker()

    def check(self, step: PlanStep, skill: RobotSkill, state: RobotState) -> GuardDecision:
        reasons = skill.check_preconditions(state, step.arguments)
        reasons.extend(v.message for v in self.checker.check_step(step, skill, state))
        return GuardDecision(not reasons, tuple(dict.fromkeys(reasons)))
