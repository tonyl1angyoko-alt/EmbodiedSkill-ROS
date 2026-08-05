#!/usr/bin/env python3
from _common import show, state
from embodied_skill_ros import build_mock_system
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan


unsafe_parallel_plan = TaskPlan("extend arm while requesting fast base motion", [
    PlanStep("extend", "extend_arm", {"arm": "right"}, parallel_group="unsafe"),
    PlanStep(
        "drive", "move_agv", {"distance_m": 1.0, "speed_mps": 0.5},
        parallel_group="unsafe",
    ),
])
show(build_mock_system(state()).run_plan(unsafe_parallel_plan))
