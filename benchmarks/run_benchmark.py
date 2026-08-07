#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import fields
import json
from pathlib import Path
import sys
import time
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from embodied_skill_ros.backends.mock_backend import FaultEvent, MockRobotBackend
from embodied_skill_ros.execution.skill_executor import SkillExecutor
from embodied_skill_ros.evaluation.oracle import BenchmarkOracle
from embodied_skill_ros.models.robot_state import RobotState
from embodied_skill_ros.models.task_plan import TaskPlan
from embodied_skill_ros.skills.registry import build_default_registry
from embodied_skill_ros.planner.goal_replanner import GoalDirectedReplanner
from embodied_skill_ros.tracing.metrics import summarize_runs


PROFILES = {
    "A_direct_function_calling": dict(
        ground_plan=False, allow_repair=False, runtime_guard=False,
        verify_outcomes=False, allow_recovery=False,
    ),
    "B_structured_sequential": dict(
        ground_plan=False, allow_repair=False, runtime_guard=False,
        verify_outcomes=True, allow_recovery=False,
    ),
    "C_state_grounded": dict(
        ground_plan=True, allow_repair=True, runtime_guard=True,
        verify_outcomes=True, allow_recovery=False,
    ),
    "D_grounded_with_recovery": dict(
        ground_plan=True, allow_repair=True, runtime_guard=True,
        verify_outcomes=True, allow_recovery=True,
    ),
}


def default_state() -> RobotState:
    return RobotState(
        left_arm_ready=True, right_arm_ready=True,
        left_arm_safe=True, right_arm_safe=True,
        agv_ready=True, agv_moving=False, agv_position_m=0.0,
        lift_ready=True, lift_height_mm=100.0,
        head_ready=True, head_yaw_deg=0.0, head_pitch_deg=0.0,
        emergency_stop=False,
    )


def make_state(changes: dict[str, Any]) -> RobotState:
    allowed = {field.name for field in fields(RobotState)}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"unknown initial state fields: {sorted(unknown)}")
    return default_state().copy(**changes)


def count_invalid_calls(report, registry) -> int:
    invalid = 0
    if report.trace is None:
        return 0
    for record in report.trace.records:
        skill = registry.get(record.skill_name)
        state_data = dict(record.before_state)
        state_data["active_resources"] = set(state_data.get("active_resources", []))
        state = RobotState(**state_data)
        if skill.check_preconditions(state, record.arguments):
            invalid += 1
    return invalid


def verification_score(report, registry) -> tuple[int, int]:
    correct = 0
    total = 0
    for result in report.results:
        skill = registry.get(result.skill_name)
        truth = skill.verify_outcome(
            result.arguments, result.before_state, result.after_state
        ).achieved
        correct += int(truth == result.physical_outcome_achieved)
        total += 1
    return correct, total


def run_one(scenario: dict[str, Any], profile_name: str) -> dict[str, Any]:
    registry = build_default_registry()
    backend = MockRobotBackend(make_state(scenario.get("initial_state", {})))
    for fault in scenario.get("faults", []):
        events = [
            FaultEvent(item["mode"], item.get("message", "injected fault"), item.get("drift"))
            for item in fault["events"]
        ]
        backend.inject(fault["skill"], *events)
    executor = SkillExecutor(
        registry, backend, max_retries=1, max_replans=1,
        replanner=GoalDirectedReplanner(registry),
    )
    plan = TaskPlan.from_dict({
        "goal": scenario["goal"],
        "steps": scenario["steps"],
        "metadata": {"goal_state": scenario["expected_state"]},
    })
    started = time.perf_counter()
    report = executor.execute(plan, **PROFILES[profile_name])
    latency_ms = (time.perf_counter() - started) * 1000.0
    oracle = BenchmarkOracle().evaluate(backend, scenario["expected_state"])
    verification_correct, verification_total = verification_score(report, registry)
    decisions = report.trace.decisions if report.trace else [report.decision]
    return {
        "scenario_id": scenario["id"],
        "category": scenario["category"],
        "success": oracle.success,
        "oracle_mismatches": oracle.mismatches,
        "executor_reported_success": report.success,
        "decision": report.decision,
        "repair_used": "REPAIR" in decisions,
        "recovery_used": any(result.recovery_triggered for result in report.results),
        "invalid_calls": count_invalid_calls(report, registry),
        "execution_steps": len(report.results),
        "verification_correct": verification_correct,
        "verification_total": verification_total,
        "latency_ms": round(latency_ms, 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic EmbodiedSkill-ROS benchmark")
    parser.add_argument("--scenarios", type=Path, default=Path(__file__).with_name("scenarios.json"))
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("benchmark_results.json"))
    args = parser.parse_args()
    scenarios = json.loads(args.scenarios.read_text(encoding="utf-8"))
    if len(scenarios) < 30:
        raise ValueError("benchmark requires at least 30 scenarios")
    output = {"scenario_count": len(scenarios), "profiles": {}}
    for profile in PROFILES:
        runs = [run_one(scenario, profile) for scenario in scenarios]
        output["profiles"][profile] = {"metrics": summarize_runs(runs), "runs": runs}
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({name: data["metrics"] for name, data in output["profiles"].items()}, indent=2))
    print(f"results: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
