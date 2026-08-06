from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models.robot_state import RobotState
from ..models.task_plan import TaskPlan


@runtime_checkable
class Planner(Protocol):
    def plan(self, instruction: str, state: RobotState | None = None) -> TaskPlan:
        ...
