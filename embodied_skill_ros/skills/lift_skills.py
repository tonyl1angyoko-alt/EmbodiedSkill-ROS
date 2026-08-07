from __future__ import annotations

from typing import Any

from .base_skill import ParameterSpec, RobotSkill
from ..models.robot_state import RobotState
from ..models.safety_contract import Idempotency, RiskClass, Rollbackability, SkillSafetyContract


class SetLiftSkill(RobotSkill):
    def __init__(self):
        super().__init__("set_lift", "Move lift axis to an absolute measured height.",
                         {"height_mm": ParameterSpec((int, float), minimum=0.0, maximum=780.0)},
                         {"lift"}, {"lift_ready": lambda s, a: s.lift_ready,
                                    "arms_transport_safe": lambda s, a: (
                                        None if s.left_arm_safe is None or s.right_arm_safe is None
                                        else s.left_arm_safe and s.right_arm_safe)}, 20.0,
                         safety_contract=SkillSafetyContract(
                             risk_class=RiskClass.MEDIUM,
                             idempotency=Idempotency.IDEMPOTENT,
                             rollbackability=Rollbackability.NOT_AUTOMATIC,
                         ))

    def expected_effects(self, arguments: dict[str, Any], before: RobotState) -> dict[str, Any]:
        return {"lift_height_mm": float(arguments["height_mm"])}
