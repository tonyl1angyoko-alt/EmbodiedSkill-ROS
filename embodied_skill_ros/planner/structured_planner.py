from __future__ import annotations

from ..models.robot_state import RobotState
from ..models.task_plan import PlanStep, TaskPlan


class StructuredPlanner:
    """Small deterministic planner for the documented demo; LLM output can use TaskPlan.from_dict."""

    def plan(self, instruction: str, state: RobotState | None = None) -> TaskPlan:
        text = instruction.strip().lower()
        steps: list[PlanStep] = []
        number = 0

        def add(skill: str, arguments: dict, effect: dict | None = None) -> None:
            nonlocal number
            number += 1
            steps.append(PlanStep(f"step_{number}", skill, arguments, effect or {}))

        if ("收回" in text or "retract" in text) and ("右" in text or "right" in text):
            add("retract_arm", {"arm": "right"}, {"right_arm_safe": True})
        if ("收回" in text or "retract" in text) and ("左" in text or "left" in text):
            add("retract_arm", {"arm": "left"}, {"left_arm_safe": True})
        if any(word in text for word in ("移动", "工作台", "move", "workstation")):
            add("move_agv", {"distance_m": 1.0, "speed_mps": 0.2})
        if any(word in text for word in ("升高", "升降轴", "lift")):
            current = state.lift_height_mm if state and state.lift_height_mm is not None else 100.0
            add("set_lift", {"height_mm": min(780.0, current + 200.0)})
        if any(word in text for word in ("抬头", "look up")):
            add("set_head", {"pitch_deg": 10.0})
        if not steps:
            raise ValueError("instruction is outside the deterministic demo planner; provide a structured TaskPlan")
        return TaskPlan(instruction, steps)
