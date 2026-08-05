from __future__ import annotations

from dataclasses import replace

from .plan_grounder import GroundingReport
from ..models.robot_state import RobotState
from ..models.task_plan import PlanStep, TaskPlan


class PlanRepairer:
    """Deterministic body-state repair: insert transport poses and serialize conflicts."""

    def repair(self, plan: TaskPlan, state: RobotState, report: GroundingReport) -> TaskPlan | None:
        if report.requires_stop:
            return None
        new_steps: list[PlanStep] = []
        projected = state.copy()
        serial = 0
        for step in plan.steps:
            requires_safe_arms = step.skill in {"move_agv", "set_lift"}
            if requires_safe_arms:
                for arm in ("left", "right"):
                    if getattr(projected, f"{arm}_arm_safe") is not True:
                        serial += 1
                        repair = PlanStep(
                            id=f"repair_{serial}_{arm}_arm",
                            skill="retract_arm",
                            arguments={"arm": arm},
                            expected_effect={f"{arm}_arm_safe": True},
                            inserted_by="PlanRepairer:transport_safe_pose",
                        )
                        new_steps.append(repair)
                        projected = projected.copy(**{f"{arm}_arm_safe": True, f"{arm}_arm_ready": True})
            # The first implementation executes parallel requests sequentially after repair.
            new_steps.append(replace(step, parallel_group=None if step.parallel_group else step.parallel_group))
            if step.skill == "extend_arm":
                projected = projected.copy(**{f"{step.arguments['arm']}_arm_safe": False})
            elif step.skill == "retract_arm":
                projected = projected.copy(**{f"{step.arguments['arm']}_arm_safe": True})
        return TaskPlan(plan.goal, new_steps, plan.plan_id, plan.revision + 1,
                        {**plan.metadata, "repaired": True})
