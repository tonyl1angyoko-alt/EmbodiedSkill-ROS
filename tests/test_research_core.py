import math
import random
import unittest
import sys
from datetime import datetime, timedelta, timezone

from embodied_skill_ros.backends.mock_backend import (
    FaultEvent, MockRobotBackend, ObservationModel,
)
from embodied_skill_ros.evaluation.oracle import BenchmarkOracle
from embodied_skill_ros.execution.skill_executor import SkillExecutor
from embodied_skill_ros.grounding.plan_grounder import EmbodiedPlanGrounder
from embodied_skill_ros.grounding.plan_repairer import PlanRepairer
from embodied_skill_ros.models.robot_state import KnowledgeStatus
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan
from embodied_skill_ros.planner.goal_replanner import GoalDirectedReplanner
from embodied_skill_ros.skills.base_skill import (
    DeclarativeSkill, EffectSpec, ParameterError, SkillContract, StatePredicate,
)
from embodied_skill_ros.skills.registry import SkillRegistry, build_default_registry

from test_models_and_registry import ready_state


def custom_registry(policy=("observe", "repair", "local_retry", "replan", "safe_stop")):
    registry = SkillRegistry()
    registry.register(DeclarativeSkill(SkillContract(
        "prepare_tool", "Prepare a generic tool.", {}, frozenset({"tool"}), (),
        (EffectSpec("tool_ready", value=True),), 1.0,
    )))
    registry.register(DeclarativeSkill(SkillContract(
        "dock_tool", "Dock a generic tool.", {}, frozenset({"tool"}),
        (StatePredicate("tool_ready", True, "TOOL_NOT_READY", "tool_ready", 5.0),),
        (EffectSpec("tool_docked", value=True),), 1.0, policy,
    )))
    return registry


class EpistemicAndContractTests(unittest.TestCase):
    def test_ros2_bridge_module_import_is_optional(self):
        had_rclpy = "rclpy" in sys.modules
        from embodied_skill_ros.ros2 import mock_bridge_node
        self.assertTrue(callable(mock_bridge_node.build_node))
        self.assertEqual("rclpy" in sys.modules, had_rclpy)

    def test_explicit_stale_state_is_not_usable(self):
        state = ready_state().mark_stale("right_arm_safe")
        value = state.epistemic_value("right_arm_safe", max_age_s=5.0)
        self.assertEqual(value.status, KnowledgeStatus.STALE)
        plan = TaskPlan("move", [PlanStep("s1", "move_agv", {"distance_m": 1.0})])
        report = EmbodiedPlanGrounder(build_default_registry()).ground(plan, state)
        self.assertFalse(report.valid)
        self.assertIn("STALE", "; ".join(issue.message for issue in report.issues))

    def test_timestamp_age_produces_stale_evidence(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        value = ready_state(timestamp=old).epistemic_value("agv_ready", max_age_s=5.0)
        self.assertEqual(value.status, KnowledgeStatus.STALE)

    def test_non_finite_numeric_argument_is_rejected(self):
        skill = build_default_registry().get("move_agv")
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaisesRegex(ParameterError, "finite"):
                skill.validate_arguments({"distance_m": value})

    def test_relative_effect_with_unknown_base_is_nonrepairable(self):
        registry = build_default_registry()
        plan = TaskPlan("move", [PlanStep("move", "move_agv", {"distance_m": 1.0})])
        report = EmbodiedPlanGrounder(registry).ground(
            plan, ready_state(agv_position_m=None)
        )
        self.assertTrue(report.requires_stop)
        self.assertIn("UNPROJECTABLE_EFFECT", {item.code for item in report.issues})

    def test_fault_mode_typo_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported fault mode"):
            FaultEvent("typo")

    def test_zero_core_code_new_skill_is_repaired_and_executed(self):
        registry = custom_registry()
        backend = MockRobotBackend(ready_state(tool_ready=False, tool_docked=False))
        backend.register_handler("prepare_tool", lambda _world, _args: {"tool_ready": True})
        backend.register_handler("dock_tool", lambda _world, _args: {"tool_docked": True})
        report = SkillExecutor(registry, backend).execute(
            TaskPlan("dock", [PlanStep("dock", "dock_tool", {})])
        )
        self.assertTrue(report.success)
        self.assertEqual([name for name, _ in backend.command_log], ["prepare_tool", "dock_tool"])
        self.assertTrue(backend.oracle_state().raw_value("tool_docked"))

    def test_backend_capability_contract_blocks_dispatch(self):
        registry = custom_registry()
        backend = MockRobotBackend(ready_state(tool_ready=True, tool_docked=False))
        report = SkillExecutor(registry, backend).execute(
            TaskPlan("dock", [PlanStep("dock", "dock_tool", {})])
        )
        self.assertFalse(report.success)
        self.assertIn("does not support", report.message)
        self.assertEqual(backend.command_log, [])


class OracleReplanAndRecoveryTests(unittest.TestCase):
    def test_verified_execution_rejects_unachieved_global_goal(self):
        registry = build_default_registry()
        backend = MockRobotBackend(ready_state())
        plan = TaskPlan(
            "inconsistent goal",
            [PlanStep("head", "set_head", {"yaw_deg": 10.0})],
            metadata={"goal_state": {"lift_height_mm": 500.0}},
        )
        report = SkillExecutor(registry, backend).execute(plan)
        self.assertFalse(report.success)
        self.assertIn("final goal not achieved", report.message)

    def test_oracle_uses_hidden_world_not_sensor_override(self):
        backend = MockRobotBackend(
            ready_state(head_yaw_deg=0.0),
            ObservationModel(overrides=(("head_yaw_deg", 20.0),)),
        )
        self.assertEqual(backend.observe().head_yaw_deg, 20.0)
        result = BenchmarkOracle().evaluate(backend, {"head_yaw_deg": 20.0})
        self.assertFalse(result.success)
        self.assertEqual(result.mismatches["head_yaw_deg"], (0.0, 20.0))

    def test_goal_replanner_recomputes_relative_motion(self):
        registry = build_default_registry()
        previous = TaskPlan(
            "reach one metre",
            [PlanStep("old", "move_agv", {"distance_m": 1.0})],
            metadata={"goal_state": {"agv_position_m": 1.0}},
        )
        replanned = GoalDirectedReplanner(registry)(
            previous, ready_state(agv_position_m=0.4)
        )
        self.assertIsNotNone(replanned)
        self.assertEqual(replanned.steps[0].id, "replan_1_1")
        self.assertAlmostEqual(replanned.steps[0].arguments["distance_m"], 0.6)

    def test_recovery_policy_can_forbid_retry(self):
        registry = custom_registry(policy=("safe_stop",))
        backend = MockRobotBackend(ready_state(tool_ready=True, tool_docked=False))
        backend.register_handler("dock_tool", lambda _world, _args: {"tool_docked": True})
        backend.inject("dock_tool", FaultEvent("physical_failure"))
        report = SkillExecutor(registry, backend, max_retries=5).execute(
            TaskPlan("dock", [PlanStep("dock", "dock_tool", {})])
        )
        self.assertFalse(report.success)
        self.assertEqual([name for name, _ in backend.command_log].count("dock_tool"), 1)
        self.assertEqual(backend.command_log[-1][0], "safe_stop")

    def test_randomized_arm_states_always_repair_before_agv(self):
        rng = random.Random(20260808)
        registry = build_default_registry()
        grounder = EmbodiedPlanGrounder(registry)
        repairer = PlanRepairer(registry)
        plan = TaskPlan("move", [PlanStep("move", "move_agv", {"distance_m": 0.25})])
        for _ in range(128):
            left = rng.choice((True, False, None))
            right = rng.choice((True, False, None))
            state = ready_state(left_arm_safe=left, right_arm_safe=right)
            report = grounder.ground(plan, state)
            repaired = plan if report.valid else repairer.repair(plan, state, report)
            self.assertIsNotNone(repaired)
            self.assertTrue(grounder.ground(repaired, state).valid)
            names = [step.skill for step in repaired.steps]
            self.assertEqual(names[-1], "move_agv")
            self.assertEqual(names.count("retract_arm"), int(left is not True) + int(right is not True))


if __name__ == "__main__":
    unittest.main()
