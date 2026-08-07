from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from embodied_skill_ros.backends.mock_backend import FaultEvent, MockRobotBackend
from embodied_skill_ros.execution.outcome_verifier import OutcomeVerifier
from embodied_skill_ros.execution.skill_executor import SkillExecutor
from embodied_skill_ros.grounding.constraint_checker import ConstraintChecker
from embodied_skill_ros.grounding.plan_grounder import EmbodiedPlanGrounder
from embodied_skill_ros.grounding.plan_repairer import PlanRepairer
from embodied_skill_ros.models.freshness import StateFreshnessPolicy
from embodied_skill_ros.models.robot_state import RobotState
from embodied_skill_ros.models.skill_result import CommandReceipt
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan
from embodied_skill_ros.models.transaction import TransactionState
from embodied_skill_ros.skills.registry import build_default_registry
from embodied_skill_ros.state.state_manager import StateManager

from test_models_and_registry import ready_state


UTC = timezone.utc
NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)


def timestamp(*, milliseconds_ago: int = 0, seconds_ahead: int = 0) -> str:
    value = NOW - timedelta(milliseconds=milliseconds_ago) + timedelta(seconds=seconds_ahead)
    return value.isoformat()


def freshness_policy() -> StateFreshnessPolicy:
    return StateFreshnessPolicy(now_fn=lambda: NOW)


def registry_with_limits(skill_name: str, *, state_age_ms=None, evidence_age_ms=None):
    registry = build_default_registry()
    skill = registry.get(skill_name)
    requirements = tuple(
        replace(item, maximum_age_ms=evidence_age_ms)
        for item in skill.safety_contract.evidence_requirements
    )
    skill.safety_contract = replace(
        skill.safety_contract,
        maximum_state_age_ms=state_age_ms,
        evidence_requirements=requirements,
    )
    return registry


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class StopCountingBackend(MockRobotBackend):
    def __init__(self, initial_state, *, now_fn=lambda: NOW):
        super().__init__(initial_state, now_fn=now_fn)
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1
        return super().stop()


class SequenceObserveBackend(StopCountingBackend):
    def __init__(self, observations):
        super().__init__(observations[0])
        self._observations = list(observations)
        self._observe_index = 0

    def observe(self):
        index = min(self._observe_index, len(self._observations) - 1)
        self._observe_index += 1
        return self._observations[index].copy()


class FreshOnReobserveBackend(StopCountingBackend):
    """Simulate a later, genuine measurement without redispatching the command."""

    def __init__(self, initial_state, stale_timestamp, fresh_timestamp):
        super().__init__(initial_state)
        self.stale_timestamp = stale_timestamp
        self.fresh_timestamp = fresh_timestamp
        self._pending_reobservation = False
        self._post_dispatch_observations = 0

    def command(self, skill_name, arguments):
        if skill_name == "set_head":
            self.command_log.append((skill_name, dict(arguments)))
            self.set_state(
                head_yaw_deg=float(arguments["yaw_deg"]),
                timestamp=self.stale_timestamp,
            )
            self._pending_reobservation = True
            self._post_dispatch_observations = 0
            return CommandReceipt(True, "accepted; later measurement pending")
        return super().command(skill_name, arguments)

    def observe(self):
        if self._pending_reobservation:
            self._post_dispatch_observations += 1
            if self._post_dispatch_observations == 2:
                # This explicitly models a new measurement, not an observe-time refresh.
                self.set_state(timestamp=self.fresh_timestamp)
                self._pending_reobservation = False
        return super().observe()


class StateFreshnessPolicyTests(unittest.TestCase):
    def test_fresh_timestamp_is_accepted(self):
        result = freshness_policy().evaluate(timestamp(milliseconds_ago=250), 500)
        self.assertTrue(result.valid)
        self.assertEqual(result.age_ms, 250.0)

    def test_exact_maximum_age_boundary_is_accepted(self):
        result = freshness_policy().evaluate(timestamp(milliseconds_ago=500), 500)
        self.assertTrue(result.valid)
        self.assertEqual(result.age_ms, 500.0)

    def test_stale_timestamp_is_rejected(self):
        result = freshness_policy().evaluate(timestamp(milliseconds_ago=501), 500)
        self.assertFalse(result.valid)
        self.assertIn("stale", result.reason)

    def test_missing_timestamp_is_rejected(self):
        for value in (None, ""):
            with self.subTest(value=value):
                result = freshness_policy().evaluate(value, 500)
                self.assertFalse(result.valid)
                self.assertIn("missing", result.reason)

    def test_malformed_timestamp_is_rejected(self):
        result = freshness_policy().evaluate("not-a-timestamp", 500)
        self.assertFalse(result.valid)
        self.assertIn("malformed", result.reason)

    def test_naive_timestamp_is_rejected(self):
        result = freshness_policy().evaluate("2026-08-07T12:00:00", 500)
        self.assertFalse(result.valid)
        self.assertIn("timezone", result.reason)

    def test_future_timestamp_is_rejected(self):
        result = freshness_policy().evaluate(timestamp(seconds_ahead=5), 500)
        self.assertFalse(result.valid)
        self.assertLess(result.age_ms, 0)
        self.assertIn("future", result.reason)

    def test_no_maximum_age_disables_expiry_but_keeps_timestamp_integrity(self):
        old = freshness_policy().evaluate(timestamp(milliseconds_ago=60_000), None)
        malformed = freshness_policy().evaluate("bad", None)
        self.assertTrue(old.valid)
        self.assertIn("not required", old.reason)
        self.assertFalse(malformed.valid)


class AdmissionFreshnessTests(unittest.TestCase):
    def test_fresh_state_allows_normal_movement(self):
        backend = StopCountingBackend(ready_state(timestamp=timestamp()))
        registry = registry_with_limits("move_agv", state_age_ms=500)
        report = SkillExecutor(
            registry, backend, max_retries=0, freshness_policy=freshness_policy()
        ).execute(TaskPlan("move", [
            PlanStep("move", "move_agv", {"distance_m": 1.0}),
        ]))
        self.assertTrue(report.success)
        self.assertEqual([name for name, _ in backend.command_log], ["move_agv"])

    def test_stale_state_blocks_move_agv_before_dispatch(self):
        backend = StopCountingBackend(
            ready_state(timestamp=timestamp(milliseconds_ago=2000))
        )
        registry = registry_with_limits("move_agv", state_age_ms=500)
        report = SkillExecutor(
            registry, backend, freshness_policy=freshness_policy()
        ).execute(TaskPlan("move", [
            PlanStep("move", "move_agv", {"distance_m": 1.0}),
        ]))
        self.assertFalse(report.success)
        self.assertNotIn("move_agv", [name for name, _ in backend.command_log])
        self.assertEqual(backend.stop_calls, 1)
        self.assertIn("stale", report.message)
        self.assertEqual(report.trace.transactions[0].state, TransactionState.REJECTED)

    def test_clear_emergency_stop_in_stale_snapshot_still_blocks_motion(self):
        backend = StopCountingBackend(ready_state(
            emergency_stop=False,
            timestamp=timestamp(milliseconds_ago=2000),
        ))
        registry = registry_with_limits("move_agv", state_age_ms=500)
        report = SkillExecutor(
            registry, backend, freshness_policy=freshness_policy()
        ).execute(TaskPlan("move", [
            PlanStep("move", "move_agv", {"distance_m": 1.0}),
        ]))
        self.assertFalse(report.success)
        self.assertNotIn("move_agv", [name for name, _ in backend.command_log])
        self.assertIn("state freshness", report.message)

    def test_grounding_fresh_but_runtime_state_stale_blocks_dispatch(self):
        fresh = ready_state(timestamp=timestamp(milliseconds_ago=100))
        stale = ready_state(timestamp=timestamp(milliseconds_ago=2000))
        backend = SequenceObserveBackend([fresh, fresh, stale])
        registry = registry_with_limits("move_agv", state_age_ms=500)
        executor = SkillExecutor(
            registry, backend, freshness_policy=freshness_policy()
        )
        report = executor.execute(TaskPlan("move", [
            PlanStep("move", "move_agv", {"distance_m": 1.0}),
        ]))
        self.assertFalse(report.success)
        self.assertNotIn("move_agv", [name for name, _ in backend.command_log])
        self.assertIn("stale", report.message)
        self.assertIs(
            executor.grounder.checker.freshness_policy,
            executor.guard.checker.freshness_policy,
        )

    def test_plan_metadata_cannot_relax_registry_freshness_contract(self):
        backend = StopCountingBackend(
            ready_state(timestamp=timestamp(milliseconds_ago=2000))
        )
        registry = registry_with_limits("move_agv", state_age_ms=500)
        plan = TaskPlan(
            "move",
            [PlanStep("move", "move_agv", {"distance_m": 1.0})],
            metadata={"safety_contract": {"maximum_state_age_ms": None}},
        )
        report = SkillExecutor(
            registry, backend, freshness_policy=freshness_policy()
        ).execute(plan)
        self.assertFalse(report.success)
        self.assertNotIn("move_agv", [name for name, _ in backend.command_log])

    def test_execution_flags_cannot_bypass_contract_freshness(self):
        backend = StopCountingBackend(
            ready_state(timestamp=timestamp(milliseconds_ago=2000))
        )
        registry = registry_with_limits("move_agv", state_age_ms=500)
        report = SkillExecutor(
            registry, backend, freshness_policy=freshness_policy()
        ).execute(
            TaskPlan("move", [
                PlanStep("move", "move_agv", {"distance_m": 1.0}),
            ]),
            ground_plan=False,
            runtime_guard=False,
        )
        self.assertFalse(report.success)
        self.assertNotIn("move_agv", [name for name, _ in backend.command_log])
        self.assertEqual(report.trace.transactions[0].state, TransactionState.REJECTED)


class EvidenceFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.registry = registry_with_limits("set_head", evidence_age_ms=500)
        self.skill = self.registry.get("set_head")
        self.verifier = OutcomeVerifier(freshness_policy=freshness_policy())
        self.before = ready_state(
            head_yaw_deg=0.0, timestamp=timestamp(milliseconds_ago=100)
        )

    def verify(self, value, measured_at):
        after = self.before.copy(head_yaw_deg=value, timestamp=measured_at)
        return self.verifier.verify(
            self.skill, {"yaw_deg": 5.0}, self.before, after
        )

    def test_correct_fresh_evidence_is_commit_ready(self):
        result = self.verify(5.0, timestamp(milliseconds_ago=100))
        evidence = result.evidence[0]
        self.assertTrue(result.commit_ready)
        self.assertTrue(evidence.fresh)
        self.assertEqual(evidence.age_ms, 100.0)
        self.assertEqual(evidence.maximum_age_ms, 500)

    def test_incorrect_fresh_evidence_is_complete_failure_evidence(self):
        result = self.verify(2.0, timestamp(milliseconds_ago=100))
        self.assertFalse(result.achieved)
        self.assertTrue(result.evidence_complete)
        self.assertFalse(result.commit_ready)
        self.assertTrue(result.evidence[0].fresh)

    def test_correct_stale_evidence_is_unverified_not_failed(self):
        result = self.verify(5.0, timestamp(milliseconds_ago=2000))
        evidence = result.evidence[0]
        self.assertFalse(result.evidence_complete)
        self.assertFalse(result.commit_ready)
        self.assertTrue(evidence.matches_expected)
        self.assertFalse(evidence.fresh)
        self.assertFalse(evidence.valid)
        self.assertIn("stale", evidence.reason)

    def test_missing_evidence_timestamp_is_unverified(self):
        result = self.verify(5.0, None)
        self.assertFalse(result.evidence_complete)
        self.assertFalse(result.evidence[0].fresh)
        self.assertIn("missing", result.evidence[0].reason)

    def test_malformed_evidence_timestamp_is_unverified(self):
        result = self.verify(5.0, "bad")
        self.assertFalse(result.evidence_complete)
        self.assertFalse(result.evidence[0].fresh)
        self.assertIn("malformed", result.evidence[0].reason)

    def test_non_finite_evidence_remains_invalid(self):
        result = self.verify(float("nan"), timestamp(milliseconds_ago=100))
        self.assertFalse(result.evidence_complete)
        self.assertFalse(result.evidence[0].valid)
        self.assertIn("non-finite", result.evidence[0].reason)

    def test_no_evidence_age_limit_is_explicitly_not_evaluated(self):
        skill = build_default_registry().get("set_head")
        old = self.before.copy(
            head_yaw_deg=5.0, timestamp=timestamp(milliseconds_ago=60_000)
        )
        result = self.verifier.verify(skill, {"yaw_deg": 5.0}, self.before, old)
        self.assertTrue(result.commit_ready)
        self.assertIsNone(result.evidence[0].fresh)
        self.assertIsNone(result.evidence[0].maximum_age_ms)
        self.assertGreater(result.evidence[0].age_ms, 500)


class FreshnessExecutorAndRecoveryTests(unittest.TestCase):
    def test_correct_stale_value_never_commits_in_executor(self):
        stale = timestamp(milliseconds_ago=2000)
        backend = StopCountingBackend(ready_state(timestamp=timestamp()))
        backend.inject("set_head", FaultEvent(
            "physical_failure",
            "accepted with stale measurement",
            {"head_yaw_deg": 5.0, "timestamp": stale},
        ))
        registry = registry_with_limits("set_head", evidence_age_ms=500)
        report = SkillExecutor(
            registry, backend, max_retries=0, freshness_policy=freshness_policy()
        ).execute(
            TaskPlan("head", [PlanStep("head", "set_head", {"yaw_deg": 5.0})]),
            allow_recovery=False,
        )
        transaction = report.trace.transactions[0]
        evidence = transaction.evidence[0]
        self.assertEqual(transaction.state, TransactionState.UNVERIFIED)
        self.assertIsNone(report.results[0].physical_outcome_achieved)
        self.assertFalse(evidence.fresh)
        self.assertFalse(evidence.valid)
        self.assertIn("stale", report.results[0].message)
        serialized = report.trace.to_dict()["transactions"][0]["evidence"][0]
        self.assertEqual(serialized["age_ms"], 2000.0)
        self.assertEqual(serialized["maximum_age_ms"], 500)
        self.assertFalse(serialized["fresh"])
        self.assertIn("stale", serialized["reason"])
        self.assertEqual(backend.stop_calls, 1)

    def test_idempotent_stale_evidence_reobserves_before_any_retry(self):
        stale = timestamp(milliseconds_ago=2000)
        backend = StopCountingBackend(ready_state(timestamp=timestamp()))
        backend.inject("set_head", FaultEvent(
            "physical_failure", "stale", {"head_yaw_deg": 5.0, "timestamp": stale}
        ))
        registry = registry_with_limits("set_head", evidence_age_ms=500)
        report = SkillExecutor(
            registry, backend, max_retries=3, freshness_policy=freshness_policy()
        ).execute(TaskPlan(
            "head", [PlanStep("head", "set_head", {"yaw_deg": 5.0})]
        ))
        self.assertFalse(report.success)
        self.assertEqual(report.trace.decisions[1], "REOBSERVE")
        self.assertEqual(
            [name for name, _ in backend.command_log].count("set_head"), 1
        )

    def test_fresh_reobservation_resolves_without_redispatch(self):
        backend = FreshOnReobserveBackend(
            ready_state(timestamp=timestamp()),
            timestamp(milliseconds_ago=2000),
            timestamp(milliseconds_ago=100),
        )
        registry = registry_with_limits("set_head", evidence_age_ms=500)
        report = SkillExecutor(
            registry, backend, max_retries=3, freshness_policy=freshness_policy()
        ).execute(TaskPlan(
            "head", [PlanStep("head", "set_head", {"yaw_deg": 5.0})]
        ))
        self.assertTrue(report.success)
        self.assertEqual(
            [name for name, _ in backend.command_log].count("set_head"), 1
        )
        self.assertEqual(report.trace.transactions[0].state, TransactionState.COMMITTED)
        self.assertIn("REOBSERVE", report.trace.decisions)

    def test_persistent_stale_evidence_escalates_and_stops_once(self):
        stale = timestamp(milliseconds_ago=2000)
        backend = StopCountingBackend(ready_state(timestamp=timestamp()))
        backend.inject("set_head", FaultEvent(
            "physical_failure", "stale", {"head_yaw_deg": 5.0, "timestamp": stale}
        ))
        registry = registry_with_limits("set_head", evidence_age_ms=500)
        report = SkillExecutor(
            registry, backend, max_retries=3, freshness_policy=freshness_policy()
        ).execute(TaskPlan(
            "head", [PlanStep("head", "set_head", {"yaw_deg": 5.0})]
        ))
        self.assertFalse(report.success)
        self.assertEqual(
            [name for name, _ in backend.command_log].count("set_head"), 1
        )
        self.assertEqual(backend.stop_calls, 1)
        self.assertEqual(report.trace.transactions[0].state, TransactionState.ESCALATED)
        self.assertIn("stale", report.message)

    def test_non_idempotent_stale_outcome_never_redispatches(self):
        stale = timestamp(milliseconds_ago=2000)
        backend = StopCountingBackend(ready_state(timestamp=timestamp()))
        backend.inject("move_agv", FaultEvent(
            "physical_failure",
            "stale odometry",
            {"agv_position_m": 1.0, "agv_moving": False, "timestamp": stale},
        ))
        registry = registry_with_limits("move_agv", evidence_age_ms=500)
        report = SkillExecutor(
            registry, backend, max_retries=3, freshness_policy=freshness_policy()
        ).execute(TaskPlan(
            "move", [PlanStep("move", "move_agv", {"distance_m": 1.0})]
        ))
        self.assertFalse(report.success)
        self.assertEqual(
            [name for name, _ in backend.command_log].count("move_agv"), 1
        )
        self.assertIn("REOBSERVE", report.trace.decisions)
        self.assertIn("ESCALATE", report.trace.decisions)


class TimestampRegressionTests(unittest.TestCase):
    def test_robot_state_copy_still_preserves_timestamp(self):
        state = ready_state(timestamp=timestamp(milliseconds_ago=2000))
        self.assertEqual(state.copy().timestamp, state.timestamp)

    def test_planning_projection_and_repair_preserve_timestamp(self):
        state = ready_state(
            right_arm_safe=False,
            timestamp=timestamp(milliseconds_ago=2000),
        )
        copied_timestamps = []
        original_copy = RobotState.copy

        def recording_copy(current, **changes):
            result = original_copy(current, **changes)
            copied_timestamps.append((current.timestamp, result.timestamp))
            return result

        plan = TaskPlan("move", [
            PlanStep("move", "move_agv", {"distance_m": 1.0}),
        ])
        grounder = EmbodiedPlanGrounder(build_default_registry())
        with patch.object(RobotState, "copy", recording_copy):
            grounding = grounder.ground(plan, state)
            PlanRepairer().repair(plan, state, grounding)
        self.assertTrue(copied_timestamps)
        self.assertTrue(all(before == after for before, after in copied_timestamps))

    def test_repeated_observe_does_not_refresh_stale_measurement(self):
        stale = timestamp(milliseconds_ago=2000)
        backend = MockRobotBackend(ready_state(timestamp=stale), now_fn=lambda: NOW)
        self.assertEqual(backend.observe().timestamp, stale)
        self.assertEqual(backend.observe().timestamp, stale)

    def test_explicit_mock_state_update_uses_controlled_measurement_clock(self):
        clock = MutableClock(NOW)
        backend = MockRobotBackend(
            ready_state(timestamp=timestamp(milliseconds_ago=2000)), now_fn=clock
        )
        stale = backend.observe().timestamp
        clock.value = NOW + timedelta(seconds=1)
        backend.set_state(head_yaw_deg=5.0)
        updated = backend.observe()
        self.assertNotEqual(updated.timestamp, stale)
        self.assertEqual(updated.timestamp, clock.value.isoformat())
        self.assertEqual(backend.observe().timestamp, updated.timestamp)

    def test_state_manager_metadata_update_does_not_refresh_measurement_time(self):
        stale = timestamp(milliseconds_ago=2000)
        manager = StateManager(MockRobotBackend(
            ready_state(timestamp=stale), now_fn=lambda: NOW
        ))
        self.assertEqual(manager.refresh().timestamp, stale)
        self.assertEqual(manager.mark_result("failure").timestamp, stale)


if __name__ == "__main__":
    unittest.main()
