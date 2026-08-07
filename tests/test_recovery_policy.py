from dataclasses import replace
import unittest

from embodied_skill_ros.backends.mock_backend import FaultEvent, MockRobotBackend
from embodied_skill_ros.execution.recovery_manager import (
    FailureKind,
    RecoveryAction,
    RecoveryContext,
    RecoveryManager,
)
from embodied_skill_ros.execution.skill_executor import SkillExecutor
from embodied_skill_ros.models.safety_contract import RiskClass
from embodied_skill_ros.models.skill_result import CommandReceipt
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan
from embodied_skill_ros.models.transaction import TransactionState
from embodied_skill_ros.skills.registry import build_default_registry

from test_models_and_registry import ready_state


class StopCountingBackend(MockRobotBackend):
    def __init__(self, initial_state):
        super().__init__(initial_state)
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1
        return super().stop()


class RecoveryPolicyTests(unittest.TestCase):
    def test_missing_contract_context_escalates(self):
        decision = RecoveryManager(max_retries=3).decide(RecoveryContext(
            contract=None,
            failure_kind=FailureKind.EVIDENCE_UNVERIFIED,
            physical_outcome=None,
            transaction_state=TransactionState.UNVERIFIED,
            dispatch_crossed=True,
            attempt=1,
            retry_budget_remaining=3,
            replanner_available=True,
            reobserve_count=0,
        ))
        self.assertEqual(decision.action, RecoveryAction.ESCALATE)
        self.assertTrue(decision.requires_human_approval)

    def test_non_idempotent_unverified_dispatch_reobserves_then_escalates(self):
        backend = StopCountingBackend(ready_state(agv_position_m=None))
        registry = build_default_registry()
        report = SkillExecutor(
            registry,
            backend,
            max_retries=3,
            max_replans=1,
            replanner=lambda continuation, _state: continuation,
        ).execute(TaskPlan(
            "move with unavailable odometry",
            [PlanStep("move", "move_agv", {"distance_m": 1.0})],
        ))
        commands = [name for name, _ in backend.command_log]
        self.assertFalse(report.success)
        self.assertEqual(commands.count("move_agv"), 1)
        self.assertEqual(backend.stop_calls, 1)
        self.assertIn("REOBSERVE", report.trace.decisions)
        self.assertIn("ESCALATE", report.trace.decisions)
        self.assertEqual(report.trace.transactions[0].state, TransactionState.ESCALATED)

    def test_low_risk_does_not_override_non_idempotent_dispatch_rule(self):
        backend = StopCountingBackend(ready_state(agv_position_m=None))
        registry = build_default_registry()
        move = registry.get("move_agv")
        move.safety_contract = replace(
            move.safety_contract, risk_class=RiskClass.LOW
        )
        report = SkillExecutor(registry, backend, max_retries=3).execute(
            TaskPlan("move", [PlanStep("move", "move_agv", {"distance_m": 1.0})])
        )
        self.assertFalse(report.success)
        self.assertEqual(
            [name for name, _ in backend.command_log].count("move_agv"), 1
        )
        self.assertIn("ESCALATE", report.trace.decisions)

    def test_non_idempotent_failed_target_is_not_redispatched(self):
        backend = StopCountingBackend(ready_state())
        backend.inject("move_agv", FaultEvent("physical_failure", "base target missed"))
        registry = build_default_registry()
        report = SkillExecutor(registry, backend, max_retries=3).execute(
            TaskPlan("move", [PlanStep("move", "move_agv", {"distance_m": 1.0})])
        )
        self.assertFalse(report.success)
        self.assertEqual(
            [name for name, _ in backend.command_log].count("move_agv"), 1
        )
        self.assertIn("ESCALATE", report.trace.decisions)

    def test_low_idempotent_failed_action_can_retry_within_budget(self):
        backend = StopCountingBackend(ready_state())
        backend.inject("set_head", FaultEvent("physical_failure", "head target missed"))
        registry = build_default_registry()
        report = SkillExecutor(registry, backend, max_retries=1).execute(
            TaskPlan("head", [PlanStep("head", "set_head", {"yaw_deg": 5.0})])
        )
        self.assertTrue(report.success)
        self.assertEqual(
            [name for name, _ in backend.command_log].count("set_head"), 2
        )
        self.assertEqual(report.trace.transactions[0].state, TransactionState.FAILED)
        self.assertEqual(report.trace.transactions[1].state, TransactionState.COMMITTED)

    def test_replan_cannot_reintroduce_committed_non_idempotent_action(self):
        backend = StopCountingBackend(ready_state())
        backend.inject("set_head", FaultEvent("command_failure", "controller rejected"))
        registry = build_default_registry()

        def malicious_replan(_continuation, _state, _completed):
            return TaskPlan("replay", [
                PlanStep("replayed_move", "move_agv", {"distance_m": 1.0}),
                PlanStep("head_again", "set_head", {"yaw_deg": 5.0}),
            ])

        report = SkillExecutor(
            registry,
            backend,
            max_retries=0,
            max_replans=1,
            replanner=malicious_replan,
        ).execute(TaskPlan("move then head", [
            PlanStep("move", "move_agv", {"distance_m": 1.0}),
            PlanStep("head", "set_head", {"yaw_deg": 5.0}),
        ]))
        self.assertFalse(report.success)
        self.assertEqual(
            [name for name, _ in backend.command_log].count("move_agv"), 1
        )
        self.assertIn("protected non-idempotent", report.message)
        self.assertEqual(report.trace.transactions[0].state, TransactionState.COMMITTED)


if __name__ == "__main__":
    unittest.main()
