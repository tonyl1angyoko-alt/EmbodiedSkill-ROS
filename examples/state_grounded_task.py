#!/usr/bin/env python3
from _common import show, state
from embodied_skill_ros import build_mock_system


for label, robot_state in (
    ("STATE A: right_arm_safe=true", state(right_arm_safe=True)),
    ("STATE B: right_arm_safe=false", state(right_arm_safe=False)),
):
    print(f"\n--- {label} ---")
    show(build_mock_system(robot_state).run_instruction("移动到工作台。"))
