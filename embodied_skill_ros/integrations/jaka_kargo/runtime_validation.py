from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Iterator

from ...execution.skill_executor import SkillExecutor
from ...models.task_plan import PlanStep, TaskPlan
from .integration_config import ArmCommandScope, JakaKargoIntegrationConfig
from .ros2_transport import JakaKargoRos2Transport
from .skill_adapter import JakaKargoBackend
from .skills import build_jaka_kargo_registry


@contextmanager
def _stub_process(fault_mode: str, delay_s: float = 1.0) -> Iterator[subprocess.Popen]:
    command = [
        sys.executable,
        "-m",
        "embodied_skill_ros.integrations.jaka_kargo.legacy_stub_node",
        "--ros-args",
        "-p",
        f"fault_mode:={fault_mode}",
        "-p",
        f"delay_s:={delay_s}",
    ]
    environment = dict(os.environ)
    process = subprocess.Popen(
        command,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        time.sleep(0.8)
        if process.poll() is not None:
            raise RuntimeError(f"legacy-compatible stub exited with {process.returncode}")
        yield process
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5.0)


def _config(**changes) -> JakaKargoIntegrationConfig:
    defaults = {
        "motion_enabled": True,
        "whole_robot_estop_observable": True,
        "arm_pose_query_implies_ready": True,
        "transport_pose_calibrated": True,
        "left_transport_joints_rad": (0.0,) * 7,
        "right_transport_joints_rad": (0.0,) * 7,
        "service_timeout_s": 1.0,
        "observation_max_age_s": 2.0,
    }
    defaults.update(changes)
    return JakaKargoIntegrationConfig(**defaults)


def _run_plan(config: JakaKargoIntegrationConfig, plan: TaskPlan):
    transport = JakaKargoRos2Transport(config.endpoints, discovery_timeout_s=2.0)
    backend = JakaKargoBackend(transport, config)
    try:
        report = SkillExecutor(build_jaka_kargo_registry(), backend).execute(plan)
        return report, backend.integration_capabilities().to_dict()
    finally:
        backend.close()


def run_scenarios() -> list[dict]:
    scenarios: list[dict] = []

    with _stub_process("normal"):
        report, capabilities = _run_plan(
            _config(),
            TaskPlan("measured lift", [
                PlanStep("lift", "set_lift", {"height_mm": 150.0})
            ]),
        )
        scenarios.append({
            "id": "J1",
            "name": "nominal measured lift",
            "passed": report.success,
            "decision": report.decision,
            "command_accepted": report.results[-1].command_accepted,
            "physical_outcome_achieved": report.results[-1].physical_outcome_achieved,
            "capabilities": capabilities,
        })

    with _stub_process("accepted_no_motion"):
        report, capabilities = _run_plan(
            _config(),
            TaskPlan("negative control", [
                PlanStep("lift", "set_lift", {"height_mm": 175.0})
            ]),
        )
        accepted = bool(report.results and report.results[0].command_accepted)
        physically_failed = bool(
            report.results and not report.results[0].physical_outcome_achieved
        )
        scenarios.append({
            "id": "J2",
            "name": "service success without measured transition",
            "passed": (not report.success and accepted and physically_failed),
            "decision": report.decision,
            "command_accepted": accepted,
            "physical_outcome_achieved": not physically_failed,
            "capabilities": capabilities,
        })

    with _stub_process("normal"):
        report, capabilities = _run_plan(
            _config(arm_command_scope=ArmCommandScope.LEGACY_BILATERAL_PRESET),
            TaskPlan("single arm semantic mismatch", [
                PlanStep("arm", "retract_arm", {"arm": "left"})
            ]),
        )
        scenarios.append({
            "id": "J3",
            "name": "bilateral preset rejected before dispatch",
            "passed": (not report.success and "unavoidable effects" in report.message),
            "decision": report.decision,
            "message": report.message,
            "capabilities": capabilities,
        })

    with _stub_process("normal"):
        report, capabilities = _run_plan(
            _config(whole_robot_estop_observable=False),
            TaskPlan("unknown global stop state", [
                PlanStep("head", "set_head", {"yaw_deg": 10.0})
            ]),
        )
        scenarios.append({
            "id": "J4",
            "name": "unknown whole-robot emergency-stop evidence",
            "passed": (not report.success and report.decision == "STOP"),
            "decision": report.decision,
            "message": report.message,
            "capabilities": capabilities,
        })

    with _stub_process("timeout", delay_s=0.8):
        report, capabilities = _run_plan(
            _config(service_timeout_s=0.2),
            TaskPlan("bounded client timeout", [
                PlanStep("waist", "set_waist", {"angle_deg": 10.0})
            ]),
        )
        timed_out = any(item.timed_out for item in report.results)
        scenarios.append({
            "id": "J5",
            "name": "service timeout remains non-cancellable",
            "passed": (not report.success and timed_out),
            "decision": report.decision,
            "timed_out": timed_out,
            "capabilities": capabilities,
        })

    with _stub_process("normal"):
        report, capabilities = _run_plan(
            _config(left_transport_joints_rad=(0.1,) * 7),
            TaskPlan("single-arm transport pose", [
                PlanStep("arm", "retract_arm", {"arm": "left"})
            ]),
        )
        scenarios.append({
            "id": "J6",
            "name": "single-arm service mapping and measured joints",
            "passed": bool(report.success and report.results[-1].physical_outcome_achieved),
            "decision": report.decision,
            "command_accepted": report.results[-1].command_accepted,
            "physical_outcome_achieved": report.results[-1].physical_outcome_achieved,
            "capabilities": capabilities,
        })

    with _stub_process("normal"):
        report, capabilities = _run_plan(
            _config(),
            TaskPlan("map x navigation", [
                PlanStep("agv", "move_agv", {"distance_m": 0.5, "speed_mps": 0.2})
            ]),
        )
        scenarios.append({
            "id": "J7",
            "name": "AGV navigation service and odometry verification",
            "passed": bool(report.success and report.results[-1].physical_outcome_achieved),
            "decision": report.decision,
            "command_accepted": report.results[-1].command_accepted,
            "physical_outcome_achieved": report.results[-1].physical_outcome_achieved,
            "capabilities": capabilities,
        })

    with _stub_process("normal"):
        report, capabilities = _run_plan(
            _config(),
            TaskPlan("head and waist", [
                PlanStep("head", "set_head", {"yaw_deg": 12.0, "pitch_deg": 8.0}),
                PlanStep("waist", "set_waist", {"angle_deg": 15.0}),
            ]),
        )
        scenarios.append({
            "id": "J8",
            "name": "head sign conversion and waist dynamic state",
            "passed": bool(
                report.success
                and len(report.results) == 2
                and all(item.physical_outcome_achieved for item in report.results)
            ),
            "decision": report.decision,
            "commands_verified": len(report.results),
            "capabilities": capabilities,
        })

    with _stub_process("accepted_no_motion"):
        report, capabilities = _run_plan(
            _config(),
            TaskPlan("AGV negative control", [
                PlanStep("agv", "move_agv", {"distance_m": 0.5, "speed_mps": 0.2})
            ]),
        )
        accepted = bool(report.results and report.results[0].command_accepted)
        physically_failed = bool(
            report.results and not report.results[0].physical_outcome_achieved
        )
        scenarios.append({
            "id": "J9",
            "name": "navigation success without odometry transition",
            "passed": (not report.success and accepted and physically_failed),
            "decision": report.decision,
            "command_accepted": accepted,
            "physical_outcome_achieved": not physically_failed,
            "capabilities": capabilities,
        })

    return scenarios


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", default="local_validation_outputs/jaka_kargo_integration_scenarios.json"
    )
    args = parser.parse_args(argv)
    scenarios = run_scenarios()
    payload = {
        "schema_version": 1,
        "runtime": "ROS2 Humble legacy-compatible process stub",
        "hardware": "NOT EXECUTED",
        "scenarios": scenarios,
        "summary": {
            "passed": sum(bool(item["passed"]) for item in scenarios),
            "total": len(scenarios),
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload["summary"], sort_keys=True))
    return 0 if all(item["passed"] for item in scenarios) else 1


if __name__ == "__main__":
    raise SystemExit(main())
