#!/usr/bin/env python3
from _common import show, state
from embodied_skill_ros import build_mock_system
from embodied_skill_ros.backends.mock_backend import FaultEvent
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan


system = build_mock_system(state(), max_retries=0, max_replans=1)
system.backend.inject("set_head", FaultEvent("physical_failure", "first head motion failed"))
report = system.run_plan(TaskPlan("move then look up", [
    PlanStep("move", "move_agv", {"distance_m": 1.0}),
    PlanStep("head", "set_head", {"pitch_deg": 10.0}),
]))
show(report)
print("final AGV position:", system.backend.observe().agv_position_m)
print("commands:", [name for name, _arguments in system.backend.command_log])
