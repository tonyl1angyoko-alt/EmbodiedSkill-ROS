from dataclasses import replace
import unittest

from embodied_skill_ros.backends.mock_backend import FaultEvent, MockRobotBackend
from embodied_skill_ros.execution.skill_executor import SkillExecutor
from embodied_skill_ros.models.transaction import (
    InvalidTransactionTransition,
    SkillTransaction,
    TransactionState,
)
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan
from embodied_skill_ros.skills.registry import build_default_registry

from test_models_and_registry import ready_state


def execute_head(*, fault=None, verify_outcomes=True, remove_evidence=False):
    backend = MockRobotBackend(ready_state())
    if fault is not None:
        backend.inject("set_head", fault)
    registry = build_default_registry()
    if remove_evidence:
        skill = registry.get("set_head")
        skill.safety_contract = replace(skill.safety_contract, evidence_requirements=())
    report = SkillExecutor(registry, backend, max_retries=0).execute(
        TaskPlan("head", [PlanStep("s1", "set_head", {"yaw_deg": 5})]),
        verify_outcomes=verify_outcomes,
        allow_recovery=False,
    )
    return backend, report


class TransactionLifecycleTests(unittest.TestCase):
    def test_transaction_state_set_is_minimal(self):
        self.assertEqual(
            {state.value for state in TransactionState},
            {
                "proposed", "admitted", "dispatched", "acknowledged",
                "committed", "failed", "unverified", "rejected", "escalated",
            },
        )

    def test_illegal_acknowledged_to_admitted_transition_is_rejected(self):
        transaction = SkillTransaction("tx-1", "plan", "step", "set_head", {}, 1)
        transaction.transition(TransactionState.ADMITTED, "admission passed")
        transaction.transition(TransactionState.DISPATCHED, "backend call boundary")
        transaction.transition(TransactionState.ACKNOWLEDGED, "receipt accepted")
        with self.assertRaises(InvalidTransactionTransition):
            transaction.transition(TransactionState.ADMITTED, "illegal rewind")

    def test_acknowledged_cannot_directly_transition_to_committed(self):
        transaction = SkillTransaction("tx-1", "plan", "step", "set_head", {}, 1)
        transaction.transition(TransactionState.ADMITTED, "admission passed")
        transaction.transition(TransactionState.DISPATCHED, "backend call boundary")
        transaction.transition(TransactionState.ACKNOWLEDGED, "receipt accepted")
        with self.assertRaises(InvalidTransactionTransition):
            transaction.transition(TransactionState.COMMITTED, "receipt is not evidence")

    def test_matching_complete_evidence_commits(self):
        _backend, report = execute_head()
        transaction = report.trace.transactions[0]
        self.assertTrue(report.success)
        self.assertTrue(report.assurance_complete)
        self.assertEqual(transaction.state, TransactionState.COMMITTED)
        self.assertEqual(
            [item.to_state for item in transaction.transitions],
            [
                TransactionState.PROPOSED,
                TransactionState.ADMITTED,
                TransactionState.DISPATCHED,
                TransactionState.ACKNOWLEDGED,
                TransactionState.COMMITTED,
            ],
        )
        self.assertEqual(transaction.transitions[-1].event, "evidence_evaluated")
        self.assertTrue(transaction.evidence)

    def test_complete_evidence_mismatch_fails(self):
        _backend, report = execute_head(fault=FaultEvent("physical_failure"))
        transaction = report.trace.transactions[0]
        self.assertFalse(report.success)
        self.assertEqual(transaction.state, TransactionState.FAILED)
        self.assertTrue(transaction.evidence)
        self.assertTrue(all(item.valid for item in transaction.evidence))

    def test_accepted_without_sufficient_evidence_is_unverified(self):
        _backend, report = execute_head(remove_evidence=True)
        transaction = report.trace.transactions[0]
        self.assertFalse(report.success)
        self.assertTrue(transaction.command_accepted)
        self.assertEqual(transaction.state, TransactionState.UNVERIFIED)
        self.assertNotIn(
            TransactionState.COMMITTED,
            [item.to_state for item in transaction.transitions],
        )

    def test_verification_disabled_preserves_control_flow_but_not_assurance(self):
        _backend, report = execute_head(verify_outcomes=False)
        transaction = report.trace.transactions[0]
        self.assertTrue(report.success)
        self.assertFalse(report.assurance_complete)
        self.assertEqual(transaction.state, TransactionState.UNVERIFIED)
        self.assertIsNone(report.results[0].physical_outcome_achieved)

    def test_explicit_command_rejection_is_rejected_transaction(self):
        _backend, report = execute_head(
            fault=FaultEvent("command_failure", "controller rejected")
        )
        transaction = report.trace.transactions[0]
        self.assertFalse(report.success)
        self.assertFalse(transaction.command_accepted)
        self.assertEqual(transaction.state, TransactionState.REJECTED)

    def test_receipt_and_transaction_state_remain_separate_trace_fields(self):
        _backend, report = execute_head()
        record = report.trace.records[0]
        self.assertTrue(record.command_accepted)
        self.assertEqual(record.transaction_state, "committed")
        self.assertTrue(record.transaction_id)


if __name__ == "__main__":
    unittest.main()
