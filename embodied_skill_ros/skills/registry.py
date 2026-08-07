from __future__ import annotations

from .base_skill import RobotSkill
from .agv_skills import MoveAgvSkill
from .arm_skills import ExtendArmSkill, RetractArmSkill
from .head_skills import SetHeadSkill
from .lift_skills import SetLiftSkill
from ..models.robot_state import RobotState
from ..models.task_plan import PlanStep


class SkillRegistry:
    def __init__(self):
        self._skills: dict[str, RobotSkill] = {}

    def register(self, skill: RobotSkill) -> None:
        if skill.name in self._skills:
            raise ValueError(f"duplicate skill: {skill.name}")
        self._skills[skill.name] = skill

    def get(self, name: str) -> RobotSkill:
        if name not in self._skills:
            raise KeyError(f"unknown skill: {name}")
        return self._skills[name]

    def names(self) -> frozenset[str]:
        return frozenset(self._skills)

    def __iter__(self):
        return iter(self._skills.values())

    def synthesize_step(self, field: str, target: object, state: RobotState,
                        step_id: str, inserted_by: str,
                        excluded_skills: frozenset[str] = frozenset()) -> PlanStep | None:
        """Find a registered declarative effect that can establish a fact."""

        candidates = self.synthesize_candidates(
            field, target, state, step_id, inserted_by, excluded_skills
        )
        return candidates[0] if candidates else None

    def synthesize_candidates(self, field: str, target: object, state: RobotState,
                              step_id: str, inserted_by: str,
                              excluded_skills: frozenset[str] = frozenset()) -> list[PlanStep]:
        candidates = []
        for skill in self._skills.values():
            if skill.name in excluded_skills:
                continue
            for effect in skill.effect_specs:
                arguments = effect.synthesize_arguments(field, target, state)
                if arguments is None:
                    continue
                try:
                    skill.validate_arguments(arguments)
                except (TypeError, ValueError):
                    continue
                candidates.append(PlanStep(
                    id=step_id,
                    skill=skill.name,
                    arguments=arguments,
                    expected_effect={field: target},
                    inserted_by=inserted_by,
                ))
                break
        return candidates


def build_default_registry() -> SkillRegistry:
    registry = SkillRegistry()
    for skill in (RetractArmSkill(), ExtendArmSkill(), MoveAgvSkill(), SetLiftSkill(), SetHeadSkill()):
        registry.register(skill)
    return registry
