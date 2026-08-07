from __future__ import annotations

from dataclasses import dataclass

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
    def check_step(self, step: PlanStep, skill: RobotSkill, state: RobotState) -> list[ConstraintViolation]:
        out: list[ConstraintViolation] = []
        if state.emergency_stop is True:
            out.append(ConstraintViolation("EMERGENCY_STOP", step.id, "emergency stop is active", False))
        if state.fault:
            out.append(ConstraintViolation("ROBOT_FAULT", step.id, state.fault, False))
        busy = state.active_resources & skill.required_resources
        if busy:
            out.append(ConstraintViolation("RESOURCE_BUSY", step.id, f"resources busy: {sorted(busy)}"))
        return out

    def check_parallel(self, steps: list[PlanStep], skills: dict[str, RobotSkill]) -> list[ConstraintViolation]:
        out = []
        groups: dict[str, list[PlanStep]] = {}
        for step in steps:
            if step.parallel_group:
                groups.setdefault(step.parallel_group, []).append(step)
        for group_steps in groups.values():
            used: set[str] = set()
            prior_skills: list[RobotSkill] = []
            for step in group_steps:
                skill = skills.get(step.skill)
                if skill is None:
                    continue
                overlap = used & skill.required_resources
                if overlap:
                    out.append(ConstraintViolation("PARALLEL_RESOURCE_CONFLICT", step.id,
                                                   f"parallel resources conflict: {sorted(overlap)}"))
                used |= skill.required_resources
                for prior in prior_skills:
                    if (skill.required_resources & prior.incompatible_resources
                            or prior.required_resources & skill.incompatible_resources):
                        out.append(ConstraintViolation(
                            "BODY_CONFLICT", step.id,
                            f"incompatible resources in parallel group: "
                            f"{sorted(skill.required_resources | prior.required_resources)}",
                        ))
                prior_skills.append(skill)
        return out
