from __future__ import annotations

from typing import Any

from .base_skill import ParameterSpec, RobotSkill
from ..models.robot_state import RobotState


class SetHeadSkill(RobotSkill):
    def __init__(self):
        super().__init__("set_head", "Set head yaw and/or pitch.",
                         {"yaw_deg": ParameterSpec((int, float), required=False, minimum=-90.0, maximum=90.0),
                          "pitch_deg": ParameterSpec((int, float), required=False, minimum=-45.0, maximum=20.0)},
                         {"head"}, {"head_ready": lambda s, a: s.head_ready}, 10.0)

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        super().validate_arguments(arguments)
        if not arguments:
            raise ValueError("set_head requires yaw_deg or pitch_deg")

    def expected_effects(self, arguments: dict[str, Any], before: RobotState) -> dict[str, Any]:
        effects = {}
        if "yaw_deg" in arguments:
            effects["head_yaw_deg"] = float(arguments["yaw_deg"])
        if "pitch_deg" in arguments:
            effects["head_pitch_deg"] = float(arguments["pitch_deg"])
        return effects
