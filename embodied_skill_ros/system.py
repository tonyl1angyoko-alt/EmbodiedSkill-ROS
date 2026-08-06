from __future__ import annotations

from dataclasses import dataclass
import json

from .backends.base_backend import RobotBackend
from .backends.mock_backend import MockRobotBackend
from .execution.skill_executor import ExecutionReport, SkillExecutor
from .models.robot_state import RobotState
from .models.task_plan import TaskPlan
from .planner.structured_planner import StructuredPlanner
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

    def replan(previous: TaskPlan, state: RobotState,
               completed_steps: tuple = ()) -> TaskPlan | None:
        try:
            generated = planner.plan(previous.goal, state)
        except ValueError:
            return None
        completed_signatures: dict[tuple[str, str], int] = {}
        for step in completed_steps:
            signature = (step.skill, json.dumps(step.arguments, sort_keys=True))
            completed_signatures[signature] = completed_signatures.get(signature, 0) + 1
        continuation = []
        for step in generated.steps:
            signature = (step.skill, json.dumps(step.arguments, sort_keys=True))
            if completed_signatures.get(signature, 0):
                completed_signatures[signature] -= 1
            else:
                continuation.append(step)
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
