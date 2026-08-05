from __future__ import annotations

from .base_skill import RobotSkill
from .agv_skills import MoveAgvSkill
from .arm_skills import ExtendArmSkill, RetractArmSkill
from .head_skills import SetHeadSkill
from .lift_skills import SetLiftSkill


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


def build_default_registry() -> SkillRegistry:
    registry = SkillRegistry()
    for skill in (RetractArmSkill(), ExtendArmSkill(), MoveAgvSkill(), SetLiftSkill(), SetHeadSkill()):
        registry.register(skill)
    return registry
