#!/usr/bin/env python3
from _common import show, state
from embodied_skill_ros import build_mock_system
from embodied_skill_ros.backends.mock_backend import FaultEvent


system = build_mock_system(state(), max_retries=1)
system.backend.inject(
    "set_lift",
    FaultEvent("physical_failure", "command accepted, but lift feedback did not change"),
)
show(system.run_instruction("升高升降轴。"))
