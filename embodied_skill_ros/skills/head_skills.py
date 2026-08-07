from __future__ import annotations

from typing import Any

from .base_skill import (
    EffectSpec, ParameterSpec, RobotSkill, SkillContract, StatePredicate,
)


class SetHeadSkill(RobotSkill):
    def __init__(self):
        super().__init__(SkillContract(
            name="set_head",
            description="Set head yaw and/or pitch.",
            parameters={
                "yaw_deg": ParameterSpec(
                    (int, float), required=False, minimum=-90.0, maximum=90.0
                ),
                "pitch_deg": ParameterSpec(
                    (int, float), required=False, minimum=-45.0, maximum=20.0
                ),
            },
            resources=frozenset({"head"}),
            preconditions=(
                StatePredicate("head_ready", True, "HEAD_NOT_READY", "head_ready", 5.0),
            ),
            effects=(
                EffectSpec("head_yaw_deg", argument="yaw_deg", when_argument="yaw_deg"),
                EffectSpec(
                    "head_pitch_deg", argument="pitch_deg", when_argument="pitch_deg"
                ),
            ),
            timeout_s=10.0,
        ))

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        super().validate_arguments(arguments)
        if not arguments:
            raise ValueError("set_head requires yaw_deg or pitch_deg")
