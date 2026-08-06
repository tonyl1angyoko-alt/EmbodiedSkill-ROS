from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from embodied_skill_ros.models.robot_state import RobotState


def state(**changes) -> RobotState:
    base = RobotState(
        left_arm_ready=True, right_arm_ready=True,
        left_arm_safe=True, right_arm_safe=True,
        agv_ready=True, agv_moving=False, agv_position_m=0.0,
        lift_ready=True, lift_height_mm=100.0,
        head_ready=True, head_yaw_deg=0.0, head_pitch_deg=0.0,
        emergency_stop=False,
    )
    return base.copy(**changes)


def show(report) -> None:
    payload = {
        "success": report.success,
        "decision": report.decision,
        "stop_attempted": report.stop_attempted,
        "stop_accepted": report.stop_accepted,
        "stop_message": report.stop_message,
        "plan": report.plan.to_dict(),
        "results": [
            {
                "skill": result.skill_name,
                "command_accepted": result.command_accepted,
                "physical_outcome_achieved": result.physical_outcome_achieved,
                "attempt": result.attempt,
                "recovery_triggered": result.recovery_triggered,
                "message": result.message,
            }
            for result in report.results
        ],
        "trace_decisions": report.trace.decisions if report.trace else [],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
