from __future__ import annotations

from typing import Any

from ..models.robot_state import RobotState
from ..models.task_plan import TaskPlan
from ..skills.registry import SkillRegistry


class GoalDirectedReplanner:
    """Re-synthesize a plan from stable goal facts and current observations."""

    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    @staticmethod
    def _satisfied(actual: Any, target: Any, tolerance: float = 1e-6) -> bool:
        if isinstance(target, float):
            return isinstance(actual, (int, float)) and abs(float(actual) - target) <= tolerance
        return actual == target

    def __call__(self, previous: TaskPlan, state: RobotState) -> TaskPlan | None:
        goals = previous.metadata.get("goal_state")
        if not isinstance(goals, dict) or not goals:
            return None
        excluded = frozenset(previous.metadata.get("blocked_skills", ()))
        steps = []
        for field, target in goals.items():
            if self._satisfied(state.raw_value(field), target):
                continue
            step = self.registry.synthesize_step(
                field,
                target,
                state,
                f"replan_{previous.revision + 1}_{len(steps) + 1}",
                "GoalDirectedReplanner",
                excluded,
            )
            if step is None:
                return None
            steps.append(step)
            skill = self.registry.get(step.skill)
            state = state.copy(**skill.expected_effects(step.arguments, state))
        old_signature = [
            (item.skill, tuple(sorted(item.arguments.items()))) for item in previous.steps
        ]
        new_signature = [
            (item.skill, tuple(sorted(item.arguments.items()))) for item in steps
        ]
        if new_signature == old_signature:
            return None
        return TaskPlan(
            previous.goal,
            steps,
            previous.plan_id,
            previous.revision + 1,
            {
                **previous.metadata,
                "replanned_from_state": True,
                "replan_structurally_changed": True,
                "replan_old_signature": old_signature,
                "replan_new_signature": new_signature,
            },
        )
