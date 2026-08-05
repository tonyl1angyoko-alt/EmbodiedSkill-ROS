#!/usr/bin/env python3
from _common import show, state
from embodied_skill_ros import build_mock_system


system = build_mock_system(state(right_arm_safe=False))
show(system.run_instruction("收回右臂，移动到工作台旁，然后升高升降轴。"))
