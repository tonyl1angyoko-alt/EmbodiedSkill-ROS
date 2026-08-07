from __future__ import annotations

from typing import Any

from .base_skill import ParameterSpec, RobotSkill
from ..models.robot_state import RobotState
from ..models.safety_contract import Idempotency, RiskClass, Rollbackability, SkillSafetyContract


class RetractArmSkill(RobotSkill):
    def __init__(self):
        super().__init__("retract_arm", "Move one arm to a configured transport-safe pose.",
                         {"arm": ParameterSpec(str, choices=("left", "right"))},
                         {"arm"}, {"arm_ready": lambda s, a: getattr(s, f"{a['arm']}_arm_ready")}, 15.0,
                         safety_contract=SkillSafetyContract(
                             risk_class=RiskClass.MEDIUM,
                             idempotency=Idempotency.IDEMPOTENT,
                             rollbackability=Rollbackability.NOT_AUTOMATIC,
                         ))

    def expected_effects(self, arguments: dict[str, Any], before: RobotState) -> dict[str, Any]:
        arm = arguments["arm"]
        return {f"{arm}_arm_safe": True, f"{arm}_arm_ready": True}


class ExtendArmSkill(RobotSkill):
    def __init__(self):
        super().__init__("extend_arm", "Extend one arm for manipulation in the Mock benchmark.",
                         {"arm": ParameterSpec(str, choices=("left", "right"))},
                         {"arm"}, {"arm_ready": lambda s, a: getattr(s, f"{a['arm']}_arm_ready")}, 15.0,
                         safety_contract=SkillSafetyContract(
                             risk_class=RiskClass.HIGH,
                             idempotency=Idempotency.IDEMPOTENT,
                             rollbackability=Rollbackability.NOT_AUTOMATIC,
                         ))

    def expected_effects(self, arguments: dict[str, Any], before: RobotState) -> dict[str, Any]:
        return {f"{arguments['arm']}_arm_safe": False}
