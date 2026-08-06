from __future__ import annotations

from typing import Any

from .base_skill import ParameterSpec, RobotSkill
from ..models.robot_state import RobotState


class MoveAgvSkill(RobotSkill):
    def __init__(self):
        super().__init__("move_agv", "Move the AGV by a signed open-loop distance.",
                         {"distance_m": ParameterSpec((int, float), minimum=-5.0, maximum=5.0),
                          "speed_mps": ParameterSpec((int, float), required=False, minimum=0.01, maximum=0.5)},
                         {"agv"},
                         {"agv_ready": lambda s, a: s.agv_ready,
                          "left_arm_transport_safe": lambda s, a: s.left_arm_safe,
                          "right_arm_transport_safe": lambda s, a: s.right_arm_safe}, 30.0)

    def canonical_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(arguments)
        normalized.setdefault("speed_mps", 0.2)
        return normalized

    def expected_effects(self, arguments: dict[str, Any], before: RobotState) -> dict[str, Any]:
        if before.agv_position_m is None:
            return {"agv_moving": False, "agv_position_m": None}
        return {"agv_moving": False,
                "agv_position_m": float(before.agv_position_m) + float(arguments["distance_m"])}
