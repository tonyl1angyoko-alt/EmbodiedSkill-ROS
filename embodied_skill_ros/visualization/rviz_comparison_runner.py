from __future__ import annotations

from dataclasses import dataclass
import argparse
import sys
import threading
import time
from typing import Any

from ..models.robot_state import RobotState
from ..models.skill_result import CommandReceipt
from ..ros2.ros2_backend import Ros2EndpointNames
from .rviz_demo_runner import (
    FALSE_SUCCESS,
    REPAIR,
    DEMO_CASES,
    demo_definition,
    execute_demo_core,
)


@dataclass(frozen=True)
class ComparisonDefinition:
    case: str
    title: str
    baseline_scenario: dict[str, Any]
    embodied_scenario: dict[str, Any]


@dataclass
class ComparisonResult:
    definition: ComparisonDefinition
    baseline_initial: RobotState
    embodied_initial: RobotState
    baseline_receipt: CommandReceipt
    embodied_report: Any
    baseline_final: RobotState
    embodied_final: RobotState


def comparison_endpoints(lane: str) -> Ros2EndpointNames:
    if lane not in {"baseline", "embodied"}:
        raise ValueError(f"unknown comparison lane: {lane}")
    return Ros2EndpointNames(
        fake_robot_node=f"/comparison_{lane}_fake_robot",
        state_topic=f"/comparison/{lane}/state",
        event_topic=f"/comparison/{lane}/runtime_events",
        action=f"/comparison/{lane}/execute_skill",
        capabilities_service=f"/comparison/{lane}/get_capabilities",
        safe_stop_service=f"/comparison/{lane}/safe_stop",
        oracle_service=f"/comparison/{lane}/test/get_hidden_state",
    )


def comparison_definition(case: str) -> ComparisonDefinition:
    if case == REPAIR:
        common_initial = {
            "left_arm_safe": False,
            "right_arm_safe": True,
            "agv_position_m": 0.0,
        }
        return ComparisonDefinition(
            case=case,
            title="SAME TASK — DIFFERENT EXECUTION POLICY",
            baseline_scenario={
                "id": "RVIZ_comparison_baseline_repair",
                "initial_state": dict(common_initial),
                "behaviors": {
                    "move_agv": [{"mode": "normal", "duration_s": 1.70}],
                },
            },
            embodied_scenario={
                "id": "RVIZ_comparison_embodied_repair",
                "initial_state": dict(common_initial),
                "behaviors": {
                    "retract_arm": [{"mode": "normal", "duration_s": 0.55}],
                    "move_agv": [{"mode": "normal", "duration_s": 1.70}],
                },
            },
        )
    if case == FALSE_SUCCESS:
        common_initial = {
            "left_arm_safe": True,
            "right_arm_safe": True,
            "agv_position_m": 0.0,
        }
        return ComparisonDefinition(
            case=case,
            title="SAME FAULT — DIFFERENT SUCCESS CRITERION",
            baseline_scenario={
                "id": "RVIZ_comparison_baseline_false_success",
                "initial_state": dict(common_initial),
                "behaviors": {
                    "move_agv": [{"mode": "no_motion", "duration_s": 1.00}],
                },
            },
            embodied_scenario={
                "id": "RVIZ_comparison_embodied_false_success",
                "initial_state": dict(common_initial),
                "behaviors": {
                    "move_agv": [{"mode": "no_motion", "duration_s": 1.00}],
                },
            },
        )
    raise ValueError(f"unknown comparison case: {case}")


def baseline_middleware_success(receipt: CommandReceipt) -> bool:
    """The comparison baseline deliberately stops reasoning at middleware success."""

    call_result = receipt.call_result if isinstance(receipt.call_result, dict) else {}
    return bool(receipt.accepted and call_result.get("status") == "SUCCEEDED")


def run_comparison(
    baseline_backend: Any,
    embodied_backend: Any,
    definition: ComparisonDefinition,
    *,
    pre_execution_delay_s: float = 1.5,
) -> ComparisonResult:
    baseline_initial = baseline_backend.configure_scenario(definition.baseline_scenario)
    embodied_initial = embodied_backend.configure_scenario(definition.embodied_scenario)
    if pre_execution_delay_s > 0:
        time.sleep(pre_execution_delay_s)

    results: dict[str, Any] = {}
    errors: list[BaseException] = []
    start_barrier = threading.Barrier(3)

    def baseline_worker() -> None:
        try:
            start_barrier.wait()
            results["baseline_receipt"] = baseline_backend.command(
                "move_agv", {"distance_m": 1.0}
            )
        except BaseException as exc:
            errors.append(exc)

    def embodied_worker() -> None:
        try:
            start_barrier.wait()
            results["embodied_report"] = execute_demo_core(
                embodied_backend, demo_definition(definition.case)
            )
        except BaseException as exc:
            errors.append(exc)

    baseline_thread = threading.Thread(target=baseline_worker, name="baseline-direct")
    embodied_thread = threading.Thread(target=embodied_worker, name="embodied-executor")
    baseline_thread.start()
    embodied_thread.start()
    start_barrier.wait()
    baseline_thread.join()
    embodied_thread.join()
    if errors:
        raise RuntimeError(f"comparison worker failed: {errors[0]}") from errors[0]

    baseline_final = baseline_backend.observe()
    embodied_final = embodied_backend.observe()
    return ComparisonResult(
        definition=definition,
        baseline_initial=baseline_initial,
        embodied_initial=embodied_initial,
        baseline_receipt=results["baseline_receipt"],
        embodied_report=results["embodied_report"],
        baseline_final=baseline_final,
        embodied_final=embodied_final,
    )


def comparison_passed(result: ComparisonResult) -> bool:
    baseline_success = baseline_middleware_success(result.baseline_receipt)
    report = result.embodied_report
    if result.definition.case == REPAIR:
        return bool(
            baseline_success
            and result.baseline_final.agv_position_m == 1.0
            and result.baseline_final.left_arm_safe is False
            and report.success
            and report.decision == "REPAIR"
            and [step.skill for step in report.plan.steps]
            == ["retract_arm", "move_agv"]
            and result.embodied_final.agv_position_m == 1.0
            and result.embodied_final.left_arm_safe is True
        )
    return bool(
        baseline_success
        and result.baseline_final.agv_position_m == 0.0
        and not report.success
        and report.decision == "STOP"
        and report.results
        and report.results[0].command_accepted
        and not report.results[0].physical_outcome_achieved
        and result.embodied_final.agv_position_m == 0.0
    )


def format_comparison_result(result: ComparisonResult) -> str:
    baseline_success = baseline_middleware_success(result.baseline_receipt)
    report = result.embodied_report
    lines = [
        "=" * 78,
        " EmbodiedSkill-ROS — A/B RViz Comparison Demo",
        f" {result.definition.title}",
        "=" * 78,
        "",
        "CONTROLLED COMPARISON",
        "  same task / same initial state / same fake-robot semantics",
        "  only the execution policy differs",
        "",
        "BASELINE — DIRECT MIDDLEWARE EXECUTION",
        f"  middleware success: {baseline_success}",
        f"  observed x:         {result.baseline_final.agv_position_m:.3f}",
        f"  observed arm_safe:  {result.baseline_final.left_arm_safe!r}",
        "",
        "EMBODIEDSKILL-ROS — CONTRACT + OUTCOME VERIFICATION",
        f"  decision:           {report.decision}",
        f"  core success:       {report.success}",
        f"  observed x:         {result.embodied_final.agv_position_m:.3f}",
        f"  observed arm_safe:  {result.embodied_final.left_arm_safe!r}",
    ]
    if result.definition.case == REPAIR:
        lines.extend([
            f"  final plan:         {' -> '.join(step.skill for step in report.plan.steps)}",
            "",
            "TAKEAWAY",
            "  Baseline moves immediately with the arm still extended.",
            "  EmbodiedSkill grounds the plan, repairs the violated precondition,",
            "  verifies the repair, then resumes the original move.",
        ])
    else:
        lines.extend([
            "",
            "TAKEAWAY",
            "  Both ROS actions report SUCCEEDED while both robots remain at x=0.",
            "  Baseline calls that success. EmbodiedSkill observes the unchanged",
            "  state, rejects the physical outcome, and returns STOP.",
        ])
    lines.extend([
        "",
        f"DEMO CHECK: {'PASS' if comparison_passed(result) else 'FAIL'}",
        "=" * 78,
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from rclpy.utilities import remove_ros_args
    from ..ros2.ros2_backend import Ros2RobotBackend

    raw_arguments = sys.argv if argv is None else ["rviz_comparison", *argv]
    arguments = remove_ros_args(args=raw_arguments)[1:]
    parser = argparse.ArgumentParser(description="Run the RViz A/B execution comparison")
    parser.add_argument("--case", choices=DEMO_CASES, default=REPAIR)
    parser.add_argument("--pre-execution-seconds", type=float, default=1.5)
    parser.add_argument("--visual-settle-seconds", type=float, default=2.4)
    args = parser.parse_args(arguments)
    if args.pre_execution_seconds < 0 or args.visual_settle_seconds < 0:
        parser.error("presentation delays must be non-negative")

    definition = comparison_definition(args.case)
    backend_kwargs = dict(
        action_timeout_s=4.0,
        observation_timeout_s=1.2,
        service_timeout_s=2.0,
    )
    with Ros2RobotBackend(
        endpoints=comparison_endpoints("baseline"), **backend_kwargs
    ) as baseline_backend, Ros2RobotBackend(
        endpoints=comparison_endpoints("embodied"), **backend_kwargs
    ) as embodied_backend:
        result = run_comparison(
            baseline_backend,
            embodied_backend,
            definition,
            pre_execution_delay_s=args.pre_execution_seconds,
        )
        if args.visual_settle_seconds:
            time.sleep(args.visual_settle_seconds)
        print(format_comparison_result(result), flush=True)
    return 0 if comparison_passed(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
