from __future__ import annotations

from .base_skill import EffectSpec, ParameterSpec, RobotSkill, SkillContract, StatePredicate


class SetLiftSkill(RobotSkill):
    def __init__(self):
        super().__init__(SkillContract(
            name="set_lift",
            description="Move lift axis to an absolute measured height.",
            parameters={
                "height_mm": ParameterSpec((int, float), minimum=0.0, maximum=780.0)
            },
            resources=frozenset({"lift"}),
            preconditions=(
                StatePredicate("lift_ready", True, "LIFT_NOT_READY", "lift_ready", 5.0),
                StatePredicate(
                    "left_arm_safe", True, "LEFT_ARM_UNSAFE_FOR_LIFT",
                    "left_arm_transport_safe", 5.0,
                ),
                StatePredicate(
                    "right_arm_safe", True, "RIGHT_ARM_UNSAFE_FOR_LIFT",
                    "right_arm_transport_safe", 5.0,
                ),
            ),
            effects=(EffectSpec("lift_height_mm", argument="height_mm"),),
            timeout_s=20.0,
            incompatible_resources=frozenset({"agv", "arm"}),
        ))
