from __future__ import annotations

from dataclasses import dataclass

from ..models.freshness import FreshnessResult, StateFreshnessPolicy
from ..models.robot_state import RobotState
from ..models.task_plan import PlanStep
from ..skills.base_skill import RobotSkill


@dataclass(frozen=True)
class ConstraintViolation:
    code: str
    step_id: str
    message: str
    repairable: bool = True


class ConstraintChecker:
    def __init__(self, freshness_policy: StateFreshnessPolicy | None = None):
        self.freshness_policy = freshness_policy or StateFreshnessPolicy()

    def evaluate_state_freshness(
        self, skill: RobotSkill, state: RobotState
    ) -> FreshnessResult | None:
        contract = skill.safety_contract
        if contract is None or contract.maximum_state_age_ms is None:
            return None
        return self.freshness_policy.evaluate(
            state.timestamp, contract.maximum_state_age_ms
        )

    def check_step(self, step: PlanStep, skill: RobotSkill, state: RobotState) -> list[ConstraintViolation]:
        out: list[ConstraintViolation] = []
        contract_violation = skill.safety_contract_violation()
        if contract_violation is not None:
            code, message = contract_violation
            out.append(ConstraintViolation(code, step.id, message, False))
        freshness = self.evaluate_state_freshness(skill, state)
        if freshness is not None and not freshness.valid:
            out.append(ConstraintViolation(
                "STATE_FRESHNESS_INVALID",
                step.id,
                f"state freshness invalid for skill {skill.name}: {freshness.reason}",
                False,
            ))
        if state.emergency_stop is True:
            out.append(ConstraintViolation("EMERGENCY_STOP_ACTIVE", step.id,
                                           "emergency stop is active", False))
        elif state.emergency_stop is None:
            out.append(ConstraintViolation("EMERGENCY_STOP_UNKNOWN", step.id,
                                           "emergency stop state is UNKNOWN", False))
        if state.fault:
            out.append(ConstraintViolation("ROBOT_FAULT", step.id, state.fault, False))
        busy = state.active_resources & skill.required_resources
        if busy:
            out.append(ConstraintViolation("RESOURCE_BUSY", step.id, f"resources busy: {sorted(busy)}"))
        if step.skill == "move_agv":
            if state.left_arm_safe is not True:
                out.append(ConstraintViolation("LEFT_ARM_UNSAFE_FOR_AGV", step.id, "left arm is not transport-safe"))
            if state.right_arm_safe is not True:
                out.append(ConstraintViolation("RIGHT_ARM_UNSAFE_FOR_AGV", step.id, "right arm is not transport-safe"))
        if step.skill == "set_lift" and (state.left_arm_safe is not True or state.right_arm_safe is not True):
            out.append(ConstraintViolation("ARM_LIFT_INCOMPATIBLE", step.id, "retract arms before lift motion"))
        return out

    def check_parallel(self, steps: list[PlanStep], skills: dict[str, RobotSkill]) -> list[ConstraintViolation]:
        out = []
        groups: dict[str, list[PlanStep]] = {}
        for step in steps:
            if step.parallel_group:
                groups.setdefault(step.parallel_group, []).append(step)
        for group_steps in groups.values():
            used: set[str] = set()
            for step in group_steps:
                skill = skills.get(step.skill)
                if skill is None:
                    continue
                overlap = used & skill.required_resources
                if overlap:
                    out.append(ConstraintViolation("PARALLEL_RESOURCE_CONFLICT", step.id,
                                                   f"parallel resources conflict: {sorted(overlap)}"))
                used |= skill.required_resources
            names = {s.skill for s in group_steps}
            if "move_agv" in names and ("extend_arm" in names or "set_lift" in names):
                out.append(ConstraintViolation("BODY_CONFLICT", group_steps[-1].id,
                                               "AGV motion conflicts with arm extension/lift motion"))
        return out
