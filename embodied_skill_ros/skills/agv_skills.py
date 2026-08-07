from __future__ import annotations

from .base_skill import EffectSpec, ParameterSpec, RobotSkill, SkillContract, StatePredicate


class MoveAgvSkill(RobotSkill):
    def __init__(self):
        super().__init__(SkillContract(
            name="move_agv",
            description="Move the AGV by a signed distance.",
            parameters={
                "distance_m": ParameterSpec((int, float), minimum=-5.0, maximum=5.0),
                "speed_mps": ParameterSpec(
                    (int, float), required=False, minimum=0.01, maximum=0.5
                ),
            },
            resources=frozenset({"agv"}),
            preconditions=(
                StatePredicate("agv_ready", True, "AGV_NOT_READY", "agv_ready", 5.0),
                StatePredicate(
                    "left_arm_safe", True, "LEFT_ARM_UNSAFE_FOR_AGV",
                    "left_arm_transport_safe", 5.0,
                ),
                StatePredicate(
                    "right_arm_safe", True, "RIGHT_ARM_UNSAFE_FOR_AGV",
                    "right_arm_transport_safe", 5.0,
                ),
            ),
            effects=(
                EffectSpec("agv_position_m", operation="increment", argument="distance_m"),
            ),
            timeout_s=30.0,
            incompatible_resources=frozenset({"arm", "lift"}),
        ))
