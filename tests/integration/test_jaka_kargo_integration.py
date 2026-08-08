from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from embodied_skill_ros.execution.skill_executor import SkillExecutor
from embodied_skill_ros.integrations.jaka_kargo import (
    AgvObservation,
    ArmCommandScope,
    ArmObservation,
    AxisObservation,
    JakaKargoBackend,
    JakaKargoIntegrationConfig,
    JakaKargoStateProvider,
    StopScope,
    TransportResult,
)
from embodied_skill_ros.integrations.jaka_kargo.skills import build_jaka_kargo_registry
from embodied_skill_ros.models.robot_state import KnowledgeStatus
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryLegacyTransport:
    def __init__(self) -> None:
        self.endpoints = frozenset({
            "/query_status_ext",
            "/query_pose_arm",
            "/joint_move_ext",
            "/joint_move_arm",
            "/navigate_single_pose",
            "/motion_state_control",
            "/JAGV_O_01/global_nav_odom",
            "/JAGV_O_01/motion_state",
        })
        stamp = now()
        self.axes = {
            axis: AxisObservation(
                axis, position, position, True, True, False, True, stamp
            )
            for axis, position in enumerate((100.0, 0.0, 0.0, 0.0))
        }
        self.arms = {
            arm: ArmObservation(arm, (0.0,) * 7, (0.0,) * 6, stamp)
            for arm in (0, 1)
        }
        self.agv = AgvObservation(
            0.0, 0.0, (0.0, 0.0, 0.0, 1.0), False, 0, False, None, stamp
        )
        self.commands: list[tuple[str, dict]] = []
        self.command_result = TransportResult(True, "legacy service returned success")
        self.apply_transition = True
        self.fail_queries: set[str] = set()
        self.closed = False

    def available_endpoints(self):
        return self.endpoints

    def query_external_axis(self, axis_id, timeout_s):
        if f"axis:{axis_id}" in self.fail_queries:
            raise RuntimeError("axis feedback unavailable")
        return self.axes[axis_id]

    def query_arm(self, arm_id, timeout_s):
        if f"arm:{arm_id}" in self.fail_queries:
            raise RuntimeError("arm feedback unavailable")
        return self.arms[arm_id]

    def query_agv(self, timeout_s):
        if "agv" in self.fail_queries:
            raise RuntimeError("AGV observations unavailable")
        return self.agv

    def move_external_axis(self, axis_id, target, velocity, acceleration, timeout_s):
        self.commands.append(("move_external_axis", {
            "axis_id": axis_id, "target": target, "velocity": velocity,
            "acceleration": acceleration, "timeout_s": timeout_s,
        }))
        if self.command_result.accepted and self.apply_transition:
            self.axes[axis_id] = replace(
                self.axes[axis_id], position=float(target),
                commanded_position=float(target), observed_at=now(),
            )
        return self.command_result

    def move_arm_joints(
        self, arm_id, joint_positions_rad, velocity, acceleration, timeout_s
    ):
        self.commands.append(("move_arm_joints", {
            "arm_id": arm_id, "joint_positions_rad": tuple(joint_positions_rad),
            "velocity": velocity, "acceleration": acceleration,
            "timeout_s": timeout_s,
        }))
        if self.command_result.accepted and self.apply_transition and arm_id in (0, 1):
            self.arms[arm_id] = replace(
                self.arms[arm_id], joint_positions_rad=tuple(joint_positions_rad),
                observed_at=now(),
            )
        return self.command_result

    def navigate_agv_x(self, target_x_m, speed_mps, map_name, timeout_s):
        self.commands.append(("navigate_agv_x", {
            "target_x_m": target_x_m, "speed_mps": speed_mps,
            "map_name": map_name, "timeout_s": timeout_s,
        }))
        if self.command_result.accepted and self.apply_transition:
            self.agv = replace(self.agv, position_x_m=float(target_x_m), observed_at=now())
        return self.command_result

    def stop_agv(self, timeout_s):
        self.commands.append(("stop_agv", {"timeout_s": timeout_s}))
        return TransportResult(True, "AGV stop accepted")

    def close(self):
        self.closed = True


def config(**changes) -> JakaKargoIntegrationConfig:
    values = {
        "motion_enabled": True,
        "whole_robot_estop_observable": True,
        "arm_pose_query_implies_ready": True,
        "transport_pose_calibrated": True,
        "left_transport_joints_rad": (0.0,) * 7,
        "right_transport_joints_rad": (0.0,) * 7,
    }
    values.update(changes)
    return JakaKargoIntegrationConfig(**values)


class StateProviderTests(unittest.TestCase):
    def test_pose_query_success_does_not_default_to_arm_ready(self):
        transport = MemoryLegacyTransport()
        state = JakaKargoStateProvider(
            transport, config(arm_pose_query_implies_ready=False)
        ).observe()
        self.assertIsNone(state.left_arm_ready)
        self.assertEqual(
            state.epistemic_value("left_arm_ready").status, KnowledgeStatus.UNKNOWN
        )

    def test_maps_measured_axis_arm_and_agv_state(self):
        transport = MemoryLegacyTransport()
        state = JakaKargoStateProvider(transport, config()).observe()
        self.assertEqual(state.lift_height_mm, 100.0)
        self.assertEqual(state.facts["waist_angle_deg"], 0.0)
        self.assertEqual(state.head_pitch_deg, -0.0)
        self.assertTrue(state.left_arm_safe)
        self.assertEqual(state.agv_position_m, 0.0)
        self.assertFalse(state.emergency_stop)

    def test_query_failure_maps_to_unknown_not_commanded_success(self):
        transport = MemoryLegacyTransport()
        transport.fail_queries.add("axis:0")
        state = JakaKargoStateProvider(transport, config()).observe()
        self.assertIsNone(state.lift_height_mm)
        self.assertEqual(
            state.epistemic_value("lift_height_mm").status, KnowledgeStatus.UNKNOWN
        )

    def test_old_observation_maps_to_stale(self):
        transport = MemoryLegacyTransport()
        old = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        transport.axes[0] = replace(transport.axes[0], observed_at=old)
        state = JakaKargoStateProvider(
            transport, config(observation_max_age_s=0.5)
        ).observe()
        self.assertEqual(
            state.epistemic_value("lift_height_mm").status, KnowledgeStatus.STALE
        )

    def test_agv_only_estop_is_not_promoted_to_global_safety_evidence(self):
        transport = MemoryLegacyTransport()
        state = JakaKargoStateProvider(
            transport, config(whole_robot_estop_observable=False)
        ).observe()
        self.assertIsNone(state.emergency_stop)
        self.assertFalse(state.facts["agv_emergency_stop"])


class CapabilityAndMappingTests(unittest.TestCase):
    def test_motion_disabled_advertises_no_motion_skills(self):
        backend = JakaKargoBackend(
            MemoryLegacyTransport(), config(motion_enabled=False)
        )
        self.assertEqual(backend.capabilities().supported_skills, frozenset())

    def test_missing_observation_boundary_removes_agv_capability(self):
        transport = MemoryLegacyTransport()
        transport.endpoints -= frozenset({"/JAGV_O_01/global_nav_odom"})
        backend = JakaKargoBackend(transport, config())
        self.assertNotIn("move_agv", backend.capabilities().supported_skills)

    def test_parameter_translation_for_lift(self):
        transport = MemoryLegacyTransport()
        backend = JakaKargoBackend(transport, config())
        receipt = backend.command("set_lift", {"height_mm": 250.0})
        self.assertTrue(receipt.accepted)
        name, arguments = transport.commands[-1]
        self.assertEqual(name, "move_external_axis")
        self.assertEqual(arguments["axis_id"], 0)
        self.assertEqual(arguments["target"], 250.0)

    def test_head_pitch_sign_is_translated_to_legacy_axis(self):
        transport = MemoryLegacyTransport()
        backend = JakaKargoBackend(transport, config())
        receipt = backend.command("set_head", {"pitch_deg": 15.0})
        self.assertTrue(receipt.accepted)
        self.assertEqual(transport.commands[-1][1]["axis_id"], 3)
        self.assertEqual(transport.commands[-1][1]["target"], -15.0)

    def test_single_arm_service_receives_only_selected_arm(self):
        transport = MemoryLegacyTransport()
        target = (0.1,) * 7
        backend = JakaKargoBackend(
            transport, config(left_transport_joints_rad=target)
        )
        receipt = backend.command("retract_arm", {"arm": "left"})
        self.assertTrue(receipt.accepted)
        self.assertEqual(transport.commands[-1][1]["arm_id"], 0)
        self.assertEqual(transport.commands[-1][1]["joint_positions_rad"], target)

    def test_unsupported_skill_never_reaches_transport(self):
        transport = MemoryLegacyTransport()
        receipt = JakaKargoBackend(transport, config()).command("open_gripper", {})
        self.assertFalse(receipt.accepted)
        self.assertEqual(transport.commands, [])

    def test_bilateral_effect_mismatch_rejected_before_transport(self):
        transport = MemoryLegacyTransport()
        backend = JakaKargoBackend(
            transport,
            config(arm_command_scope=ArmCommandScope.LEGACY_BILATERAL_PRESET),
        )
        report = SkillExecutor(build_jaka_kargo_registry(), backend).execute(
            TaskPlan("left only", [
                PlanStep("arm", "retract_arm", {"arm": "left"})
            ])
        )
        self.assertFalse(report.success)
        self.assertIn("unavoidable effects", report.message)
        self.assertEqual(transport.commands, [])

    def test_stop_scope_is_agv_only_and_not_safe_stop(self):
        transport = MemoryLegacyTransport()
        backend = JakaKargoBackend(transport, config())
        self.assertEqual(backend.integration_capabilities().stop_scope, StopScope.AGV_ONLY)
        self.assertFalse(backend.capabilities().supports_safe_stop)
        receipt = backend.stop()
        self.assertFalse(receipt.accepted)
        self.assertIn("whole-robot", receipt.backend_message)
        self.assertEqual(transport.commands[-1][0], "stop_agv")


class IntegrationExecutionTests(unittest.TestCase):
    def _lift(self, transport: MemoryLegacyTransport):
        backend = JakaKargoBackend(transport, config())
        return SkillExecutor(build_jaka_kargo_registry(), backend).execute(
            TaskPlan("lift", [PlanStep("lift", "set_lift", {"height_mm": 200.0})])
        )

    def test_nominal_command_is_verified_from_later_measurement(self):
        report = self._lift(MemoryLegacyTransport())
        self.assertTrue(report.success)
        self.assertTrue(report.results[-1].physical_outcome_achieved)

    def test_command_rejection_is_normalized(self):
        transport = MemoryLegacyTransport()
        transport.command_result = TransportResult(False, "SDK rejected")
        report = self._lift(transport)
        self.assertFalse(report.success)
        self.assertFalse(report.results[0].command_accepted)

    def test_accepted_command_without_observed_motion_fails_verification(self):
        transport = MemoryLegacyTransport()
        transport.apply_transition = False
        report = self._lift(transport)
        self.assertFalse(report.success)
        self.assertTrue(report.results[0].command_accepted)
        self.assertFalse(report.results[0].physical_outcome_achieved)

    def test_transport_timeout_is_preserved(self):
        transport = MemoryLegacyTransport()
        transport.command_result = TransportResult(
            False, "client wait expired; motion may continue", timed_out=True
        )
        report = self._lift(transport)
        self.assertFalse(report.success)
        self.assertTrue(report.results[0].timed_out)

    def test_backend_unavailable_stops_before_command(self):
        transport = MemoryLegacyTransport()
        transport.endpoints = frozenset()
        report = self._lift(transport)
        self.assertFalse(report.success)
        self.assertEqual(transport.commands, [])

    def test_unknown_global_estop_stops_before_command(self):
        transport = MemoryLegacyTransport()
        backend = JakaKargoBackend(
            transport, config(whole_robot_estop_observable=False)
        )
        report = SkillExecutor(build_jaka_kargo_registry(), backend).execute(
            TaskPlan("head", [PlanStep("head", "set_head", {"yaw_deg": 10.0})])
        )
        self.assertFalse(report.success)
        self.assertEqual(transport.commands, [])

    def test_integration_only_waist_skill_uses_dynamic_fact(self):
        transport = MemoryLegacyTransport()
        backend = JakaKargoBackend(transport, config())
        report = SkillExecutor(build_jaka_kargo_registry(), backend).execute(
            TaskPlan("waist", [
                PlanStep("waist", "set_waist", {"angle_deg": 20.0})
            ])
        )
        self.assertTrue(report.success)
        self.assertEqual(report.results[-1].after_state.facts["waist_angle_deg"], 20.0)


if __name__ == "__main__":
    unittest.main()
