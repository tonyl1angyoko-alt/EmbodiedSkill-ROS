from __future__ import annotations

from .base_skill import EffectSpec, ParameterSpec, RobotSkill, SkillContract, StatePredicate


def _arm_contract(name: str, description: str, safe: bool) -> SkillContract:
    return SkillContract(
        name=name,
        description=description,
        parameters={"arm": ParameterSpec(str, choices=("left", "right"))},
        resources=frozenset({"arm"}),
        preconditions=(
            StatePredicate("{arm}_arm_ready", True, "ARM_NOT_READY", "arm_ready", 5.0),
        ),
        effects=(
            EffectSpec("{arm}_arm_safe", value=safe),
            EffectSpec("{arm}_arm_ready", value=True),
        ) if safe else (EffectSpec("{arm}_arm_safe", value=False),),
        timeout_s=15.0,
        incompatible_resources=frozenset({"agv", "lift"}),
    )


class RetractArmSkill(RobotSkill):
    def __init__(self):
        super().__init__(_arm_contract(
            "retract_arm", "Move one arm to a configured transport-safe pose.", True
        ))


class ExtendArmSkill(RobotSkill):
    def __init__(self):
        super().__init__(_arm_contract(
            "extend_arm", "Extend one arm for manipulation in the Mock benchmark.", False
        ))
