from __future__ import annotations

import argparse
from dataclasses import dataclass
import sys
import time
from typing import Any

from ..execution.skill_executor import ExecutionReport, SkillExecutor
from ..models.robot_state import RobotState
from ..models.task_plan import PlanStep, TaskPlan
from ..skills.registry import build_default_registry


REPAIR = "repair"
FALSE_SUCCESS = "false_success"
DEMO_CASES = (REPAIR, FALSE_SUCCESS)


@dataclass(frozen=True)
class DemoDefinition:
    case: str
    title: str
    scenario: dict[str, Any]
    plan: TaskPlan


@dataclass
class DemoResult:
    definition: DemoDefinition
    initial_state: RobotState
    report: ExecutionReport
    final_state: RobotState
    ros_events: list[dict[str, Any]]


def demo_definition(case: str) -> DemoDefinition:
    plan = TaskPlan(
        goal="agv_position_m=1.0",
        steps=[PlanStep("move", "move_agv", {"distance_m": 1.0})],
        plan_id=f"rviz_demo_{case}",
        metadata={"goal_state": {"agv_position_m": 1.0}},
    )
    if case == REPAIR:
        return DemoDefinition(
            case,
            "GENERIC REPAIR",
            {
                "id": "RVIZ_generic_repair",
                "initial_state": {
                    "left_arm_safe": False,
                    "right_arm_safe": True,
                    "agv_position_m": 0.0,
                },
                # The action remains real. Its duration simply leaves enough time
                # for the presentation-only arm interpolation to finish first.
                "behaviors": {
                    "retract_arm": [{"mode": "normal", "duration_s": 0.35}],
                    "move_agv": [{"mode": "normal", "duration_s": 1.70}],
                },
            },
            plan,
        )
    if case == FALSE_SUCCESS:
        return DemoDefinition(
            case,
            "MIDDLEWARE SUCCESS != PHYSICAL SUCCESS",
            {
                "id": "RVIZ_accepted_no_motion",
                "initial_state": {
                    "left_arm_safe": True,
                    "right_arm_safe": True,
                    "agv_position_m": 0.0,
                },
                "behaviors": {
                    "move_agv": [{"mode": "no_motion", "duration_s": 0.80}],
                },
            },
            plan,
        )
    raise ValueError(f"unknown RViz demo case: {case}")


def execute_demo_core(backend: Any, definition: DemoDefinition) -> ExecutionReport:
    """Run the real registry/executor path; suitable for ROS and unit-test backends."""

    return SkillExecutor(
        build_default_registry(),
        backend,
        max_retries=0,
        max_replans=0,
        max_observation_attempts=0,
    ).execute(definition.plan)


def run_ros_demo(
    backend: Any,
    definition: DemoDefinition,
    *,
    pre_execution_delay_s: float = 0.0,
) -> DemoResult:
    event_start = len(backend.events)
    initial_state = backend.configure_scenario(definition.scenario)
    if pre_execution_delay_s > 0.0:
        # This presentation hold lets RViz display the initial observation. It
        # neither changes that observation nor participates in core decisions.
        time.sleep(pre_execution_delay_s)
    report = execute_demo_core(backend, definition)
    final_state = backend.observe()
    return DemoResult(
        definition,
        initial_state,
        report,
        final_state,
        backend.events[event_start:],
    )


def _line(label: str, value: str) -> str:
    return f"  {label:<28}{value}"


def format_demo_result(result: DemoResult) -> str:
    definition = result.definition
    report = result.report
    lines = [
        "=" * 68,
        " EmbodiedSkill-ROS — RViz State Visualization Demo",
        f" Case: {definition.title}",
        "=" * 68,
        "",
        "INPUT PLAN",
        "  move_agv(distance_m=1.0)",
        "",
        "INITIAL ROS OBSERVATION",
        _line("left_arm_safe =", repr(result.initial_state.left_arm_safe)),
        _line("agv_position_m =", f"{result.initial_state.agv_position_m:.3f}"),
    ]

    if definition.case == REPAIR:
        inserted = [step for step in report.plan.steps if step.inserted_by]
        lines.extend([
            "",
            "GROUNDING / DECISION",
            _line("precondition =", "left_arm_safe == True"),
            _line("decision =", report.decision),
            _line(
                "inserted step =",
                (
                    f'{inserted[0].skill}(arm="{inserted[0].arguments["arm"]}")'
                    if inserted else "NONE"
                ),
            ),
            _line(
                "final plan =",
                " -> ".join(step.skill for step in report.plan.steps),
            ),
            "",
            "EXECUTE / OBSERVE / VERIFY",
        ])
        for item in report.results:
            observed = (
                item.after_state.raw_value("left_arm_safe")
                if item.skill_name == "retract_arm"
                else item.after_state.raw_value("agv_position_m")
            )
            lines.append(
                _line(
                    f"{item.skill_name} =",
                    f"accepted={item.command_accepted}, observed={observed!r}, "
                    f"verified={item.physical_outcome_achieved}",
                )
            )
        lines.extend([
            "",
            "FINAL",
            _line("decision =", report.decision),
            _line("outcome =", "SUCCESS" if report.success else "FAILURE"),
        ])
    else:
        action_accepted = any(
            event.get("event") == "action_goal_response" and event.get("accepted")
            for event in result.ros_events
        )
        action_succeeded = any(
            event.get("event") == "action_result" and event.get("status") == "SUCCEEDED"
            for event in result.ros_events
        )
        first_result = report.results[0] if report.results else None
        lines.extend([
            "",
            "ROS TRANSPORT",
            _line("goal accepted =", repr(action_accepted)),
            _line("action status =", "SUCCEEDED" if action_succeeded else "NOT SUCCEEDED"),
            "",
            "EXPECTED / OBSERVED PHYSICAL EFFECT",
            _line("expected agv_position_m =", "1.000"),
            _line("observed agv_position_m =", f"{result.final_state.agv_position_m:.3f}"),
            "",
            "OUTCOME VERIFICATION",
            _line(
                "physical effect verified =",
                repr(bool(first_result and first_result.physical_outcome_achieved)),
            ),
            _line("decision =", report.decision),
            "",
            "IMPORTANT",
            "  Middleware SUCCEEDED was not treated as physical success.",
            "  RViz remains at the observed position; no motion is fabricated.",
            "",
            "FINAL",
            _line("outcome =", "FAILURE / STOP" if not report.success else "SUCCESS"),
        ])
    lines.append("=" * 68)
    return "\n".join(lines)


def demo_passed(result: DemoResult) -> bool:
    report = result.report
    if result.definition.case == REPAIR:
        return bool(
            report.success
            and report.decision == "REPAIR"
            and [step.skill for step in report.plan.steps]
            == ["retract_arm", "move_agv"]
            and report.plan.steps[0].inserted_by
            and report.plan.steps[0].inserted_by.startswith("PlanRepairer:")
            and all(item.physical_outcome_achieved for item in report.results)
        )
    action_accepted = any(
        event.get("event") == "action_goal_response" and event.get("accepted")
        for event in result.ros_events
    )
    action_succeeded = any(
        event.get("event") == "action_result" and event.get("status") == "SUCCEEDED"
        for event in result.ros_events
    )
    return bool(
        not report.success
        and report.decision == "STOP"
        and action_accepted
        and action_succeeded
        and report.results
        and not report.results[0].physical_outcome_achieved
        and result.final_state.agv_position_m == 0.0
    )


def main(argv: list[str] | None = None) -> int:
    from rclpy.utilities import remove_ros_args

    raw_arguments = sys.argv if argv is None else ["rviz_demo", *argv]
    arguments = remove_ros_args(args=raw_arguments)[1:]
    parser = argparse.ArgumentParser(
        description="Run an authentic EmbodiedSkill scenario for the RViz display"
    )
    parser.add_argument("--case", choices=DEMO_CASES, default=REPAIR)
    parser.add_argument(
        "--pre-execution-seconds",
        type=float,
        default=1.5,
        help="presentation-only hold of the initial observed pose",
    )
    parser.add_argument(
        "--visual-settle-seconds",
        type=float,
        default=2.2,
        help="presentation-only wait for RViz interpolation after execution",
    )
    args = parser.parse_args(arguments)
    if args.pre_execution_seconds < 0.0 or args.visual_settle_seconds < 0.0:
        parser.error("presentation delays must be non-negative")

    from ..ros2.ros2_backend import Ros2RobotBackend

    with Ros2RobotBackend(
        action_timeout_s=4.0,
        observation_timeout_s=1.0,
        service_timeout_s=2.0,
    ) as backend:
        result = run_ros_demo(
            backend,
            demo_definition(args.case),
            pre_execution_delay_s=args.pre_execution_seconds,
        )
        if args.visual_settle_seconds:
            time.sleep(args.visual_settle_seconds)
        print(format_demo_result(result), flush=True)
    return 0 if demo_passed(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
