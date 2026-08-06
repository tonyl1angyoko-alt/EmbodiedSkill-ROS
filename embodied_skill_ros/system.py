from __future__ import annotations

from dataclasses import dataclass

from .backends.base_backend import RobotBackend
from .backends.mock_backend import MockRobotBackend
from .execution.skill_executor import ExecutionReport, SkillExecutor
from .models.robot_state import RobotState
from .models.task_plan import TaskPlan
from .planner.base import Planner
from .planner.structured_planner import StructuredPlanner
from .skills.registry import SkillRegistry, build_registry_for_backend


@dataclass
class EmbodiedSkillSystem:
    backend: RobotBackend
    registry: SkillRegistry
    planner: Planner
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
    registry = build_registry_for_backend(backend)
    planner = StructuredPlanner()

    def replan(previous: TaskPlan, state: RobotState,
               completed_steps: tuple = ()) -> TaskPlan | None:
        try:
            generated = planner.plan(previous.goal, state)
        except ValueError:
            return None
        unmatched_completed = list(completed_steps)

        def matches_completed(candidate, completed) -> bool:
            if candidate.skill != completed.skill:
                return False
            skill = registry.get(candidate.skill)
            return (
                skill.canonical_arguments(candidate.arguments)
                == skill.canonical_arguments(completed.arguments)
            )

        continuation = []
        for step in generated.steps:
            match = next(
                (index for index, completed in enumerate(unmatched_completed)
                 if matches_completed(step, completed)),
                None,
            )
            if match is None:
                continuation.append(step)
            else:
                unmatched_completed.pop(match)
        return TaskPlan(generated.goal, continuation, generated.plan_id,
                        generated.revision + 1, {**generated.metadata, "continuation": True})

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
