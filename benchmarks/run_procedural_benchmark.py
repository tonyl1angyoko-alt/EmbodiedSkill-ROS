#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from procedural_faults import generate_trials
from embodied_skill_ros.backends.mock_backend import FaultEvent, MockRobotBackend
from embodied_skill_ros.evaluation.oracle import BenchmarkOracle
from embodied_skill_ros.execution.skill_executor import SkillExecutor
from embodied_skill_ros.models.robot_state import RobotState
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan
from embodied_skill_ros.planner.goal_replanner import GoalDirectedReplanner
from embodied_skill_ros.skills.registry import build_default_registry


PROFILES = {
    "direct_unverified": dict(
        ground_plan=False, allow_repair=False, runtime_guard=False,
        verify_outcomes=False, allow_recovery=False,
    ),
    "grounded_no_recovery": dict(
        ground_plan=True, allow_repair=True, runtime_guard=True,
        verify_outcomes=True, allow_recovery=False,
    ),
    "grounded_with_recovery": dict(
        ground_plan=True, allow_repair=True, runtime_guard=True,
        verify_outcomes=True, allow_recovery=True,
    ),
}


def initial_state() -> RobotState:
    return RobotState(
        left_arm_ready=True, right_arm_ready=True,
        left_arm_safe=True, right_arm_safe=True,
        agv_ready=True, agv_moving=False, agv_position_m=0.0,
        lift_ready=True, lift_height_mm=100.0,
        head_ready=True, head_yaw_deg=0.0, head_pitch_deg=0.0,
        emergency_stop=False,
    )


def target_for(trial: dict[str, Any]) -> float:
    if trial["skill"] == "move_agv":
        return float(trial["arguments"]["distance_m"])
    return float(next(iter(trial["arguments"].values())))


def run_trial(trial: dict[str, Any], profile: str) -> dict[str, Any]:
    registry = build_default_registry()
    backend = MockRobotBackend(initial_state())
    if trial["fault_mode"] != "none":
        backend.inject(trial["skill"], FaultEvent(trial["fault_mode"]))
    target = target_for(trial)
    plan = TaskPlan(
        trial["id"],
        [PlanStep("step_1", trial["skill"], trial["arguments"])],
        metadata={"goal_state": {trial["target_field"]: target}},
    )
    report = SkillExecutor(
        registry, backend, max_retries=1, max_replans=1,
        replanner=GoalDirectedReplanner(registry),
    ).execute(plan, **PROFILES[profile])
    oracle = BenchmarkOracle().evaluate(backend, {trial["target_field"]: target})
    return {
        "id": trial["id"],
        "fault_mode": trial["fault_mode"],
        "success": oracle.success,
        "executor_reported_success": report.success,
        "attempts": len(report.results),
        "false_positive": report.success and not oracle.success,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    modes = sorted({row["fault_mode"] for row in rows})
    return {
        "trials": len(rows),
        "success_rate": round(sum(row["success"] for row in rows) / len(rows), 4),
        "false_positive_rate": round(
            sum(row["false_positive"] for row in rows) / len(rows), 4
        ),
        "success_by_fault": {
            mode: round(
                sum(row["success"] for row in rows if row["fault_mode"] == mode)
                / sum(row["fault_mode"] == mode for row in rows),
                4,
            )
            for mode in modes
        },
        "fault_counts": dict(Counter(row["fault_mode"] for row in rows)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run seeded procedural fault trials")
    parser.add_argument("--seed", type=int, default=20260808)
    parser.add_argument("--trials", type=int, default=200)
    parser.add_argument(
        "--output", type=Path,
        default=PROJECT_ROOT / "local_validation_outputs" / "procedural_results.json",
    )
    args = parser.parse_args()
    if args.trials <= 0:
        raise ValueError("trials must be positive")
    trials = generate_trials(args.seed, args.trials)
    output = {"seed": args.seed, "trial_count": args.trials, "profiles": {}}
    for profile in PROFILES:
        rows = [run_trial(trial, profile) for trial in trials]
        output["profiles"][profile] = {"metrics": summarize(rows), "runs": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        profile: data["metrics"] for profile, data in output["profiles"].items()
    }, indent=2, sort_keys=True))
    print(f"results: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
