from __future__ import annotations

from dataclasses import dataclass

from .backends.base_backend import RobotBackend
from .backends.mock_backend import MockRobotBackend
from .execution.skill_executor import ExecutionReport, SkillExecutor
from .models.robot_state import RobotState
from .models.task_plan import TaskPlan
from .planner.structured_planner import StructuredPlanner
from .planner.goal_replanner import GoalDirectedReplanner
from .skills.registry import SkillRegistry, build_default_registry


@dataclass
class EmbodiedSkillSystem:
    backend: RobotBackend
    registry: SkillRegistry
    planner: StructuredPlanner
    executor: SkillExecutor

    def run_instruction(self, instruction: str) -> ExecutionReport:
        state = self.backend.observe()
        plan = self.planner.plan(instruction, state)
        return self.executor.execute(plan)

    def run_plan(self, plan: TaskPlan) -> ExecutionReport:
        return self.executor.execute(plan)


def build_mock_system(initial_state: RobotState | None = None, max_retries: int = 1,
                      max_replans: int = 1) -> EmbodiedSkillSystem:
    backend = MockRobotBackend(initial_state)
    registry = build_default_registry()
    planner = StructuredPlanner()

    replan = GoalDirectedReplanner(registry)

    return EmbodiedSkillSystem(
        backend,
        registry,
        planner,
        SkillExecutor(
            registry,
            backend,
            max_retries=max_retries,
            max_replans=max_replans,
            replanner=replan,
        ),
    )
