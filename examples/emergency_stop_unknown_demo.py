#!/usr/bin/env python3
from _common import show, state
from embodied_skill_ros import build_mock_system
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan


system = build_mock_system(state(emergency_stop=None))
report = system.run_plan(TaskPlan(
    "move while emergency-stop state is unavailable",
    [PlanStep("move", "move_agv", {"distance_m": 1.0})],
))
show(report)
print("commands:", [name for name, _arguments in system.backend.command_log])
