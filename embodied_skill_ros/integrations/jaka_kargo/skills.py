from __future__ import annotations

from ...skills.base_skill import (
    EffectSpec,
    ParameterSpec,
    RobotSkill,
    SkillContract,
    StatePredicate,
)
from ...skills.registry import SkillRegistry, build_default_registry


class SetWaistSkill(RobotSkill):
    """Integration-only skill using the core's dynamic fact extension point."""

    def __init__(self) -> None:
        super().__init__(SkillContract(
            name="set_waist",
            description="Move the Kargo waist external axis to a measured angle.",
            parameters={
                "angle_deg": ParameterSpec((int, float), minimum=0.0, maximum=84.0)
            },
            resources=frozenset({"waist"}),
            preconditions=(
                StatePredicate("waist_ready", True, "WAIST_NOT_READY", "waist_ready", 5.0),
            ),
            effects=(EffectSpec("waist_angle_deg", argument="angle_deg"),),
            timeout_s=20.0,
            incompatible_resources=frozenset({"agv", "arm", "lift"}),
        ))


def build_jaka_kargo_registry() -> SkillRegistry:
    registry = build_default_registry()
    registry.register(SetWaistSkill())
    return registry
