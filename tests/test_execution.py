import unittest

from embodied_skill_ros.backends.mock_backend import FaultEvent, MockRobotBackend
from embodied_skill_ros.execution.skill_executor import SkillExecutor
from embodied_skill_ros.models.skill_result import CommandReceipt
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan
from embodied_skill_ros.skills.registry import build_default_registry

from test_models_and_registry import ready_state


def executor_for(backend, *, retries=1, replans=0, replanner=None):
    registry = build_default_registry()
    return SkillExecutor(
        registry, backend, max_retries=retries, max_replans=replans, replanner=replanner
    )


class SpyBackend(MockRobotBackend):
    def __init__(self, initial_state, *, stop_mode="accepted"):
        super().__init__(initial_state)
        self.stop_mode = stop_mode
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1
        if self.stop_mode == "rejected":
            return CommandReceipt(False, "safe-stop request rejected")
        if self.stop_mode == "raises":
            raise RuntimeError("safe-stop transport unavailable")
        return super().stop()


class ExecutionTests(unittest.TestCase):
    def assert_stop_attempted_once(self, backend, report):
        self.assertFalse(report.success)
        self.assertEqual(report.decision, "STOP")
        self.assertEqual(backend.stop_calls, 1)
        self.assertTrue(report.stop_attempted)
        self.assertTrue(report.stop_accepted)
        if report.trace is not None:
            self.assertEqual(report.trace.decisions.count("STOP"), 1)

    def test_sequential_plan_executes_in_order(self):
        backend = MockRobotBackend(ready_state())
        plan = TaskPlan("task", [
            PlanStep("s1", "retract_arm", {"arm": "right"}),
            PlanStep("s2", "move_agv", {"distance_m": 1.0}),
            PlanStep("s3", "set_lift", {"height_mm": 300.0}),
        ])
        report = executor_for(backend).execute(plan)
        self.assertTrue(report.success)
        self.assertEqual([name for name, _ in backend.command_log],
                         ["retract_arm", "move_agv", "set_lift"])

    def test_first_failure_stops_following_step(self):
        backend = MockRobotBackend(ready_state())
        backend.inject("set_head", FaultEvent("command_failure"))
        plan = TaskPlan("fail", [
            PlanStep("s1", "set_head", {"yaw_deg": 5}),
            PlanStep("s2", "move_agv", {"distance_m": 1.0}),
        ])
        report = executor_for(backend, retries=0).execute(plan)
        self.assertFalse(report.success)
        self.assertNotIn("move_agv", [name for name, _ in backend.command_log])

    def test_timeout_is_recorded(self):
        backend = MockRobotBackend(ready_state())
        backend.inject("set_head", FaultEvent("timeout", "service timeout"))
        report = executor_for(backend, retries=0).execute(
            TaskPlan("timeout", [PlanStep("s1", "set_head", {"yaw_deg": 5})])
        )
        self.assertTrue(report.results[0].timed_out)
        self.assertFalse(report.success)

    def test_command_acceptance_is_distinct_from_physical_failure(self):
        backend = MockRobotBackend(ready_state())
        backend.inject("set_lift", FaultEvent("physical_failure", "motor slipped"))
        report = executor_for(backend, retries=0).execute(
            TaskPlan("lift", [PlanStep("s1", "set_lift", {"height_mm": 400.0})])
        )
        self.assertTrue(report.results[0].command_accepted)
        self.assertFalse(report.results[0].physical_outcome_achieved)

    def test_local_retry_can_recover(self):
        backend = MockRobotBackend(ready_state())
        backend.inject("set_head", FaultEvent("physical_failure"))
        report = executor_for(backend, retries=1).execute(
            TaskPlan("head", [PlanStep("s1", "set_head", {"yaw_deg": 5})])
        )
        self.assertTrue(report.success)
        self.assertEqual(len(report.results), 2)
        self.assertTrue(report.results[0].recovery_triggered)

    def test_retry_budget_exhaustion_stops(self):
        backend = MockRobotBackend(ready_state())
        backend.inject("set_head", FaultEvent("physical_failure"), FaultEvent("physical_failure"))
        report = executor_for(backend, retries=1).execute(
            TaskPlan("head", [PlanStep("s1", "set_head", {"yaw_deg": 5})])
        )
        self.assertFalse(report.success)
        self.assertEqual(len(report.results), 2)
        self.assertIn("STOP", report.trace.decisions)

    def test_replanner_is_triggered(self):
        backend = MockRobotBackend(ready_state())
        backend.inject("set_head", FaultEvent("physical_failure"))
        replanned = TaskPlan("head", [PlanStep("new", "set_head", {"yaw_deg": 5})])
        report = executor_for(
            backend, retries=0, replans=1, replanner=lambda _plan, _state: replanned
        ).execute(TaskPlan("head", [PlanStep("s1", "set_head", {"yaw_deg": 5})]))
        self.assertTrue(report.success)
        self.assertEqual(report.decision, "REPLAN")
        self.assertIn("REPLAN", report.trace.decisions)

    def test_replan_budget_prevents_infinite_loop(self):
        backend = MockRobotBackend(ready_state())
        backend.inject("set_head", *[FaultEvent("physical_failure") for _ in range(3)])
        make_plan = lambda _plan, _state: TaskPlan(
            "head", [PlanStep("new", "set_head", {"yaw_deg": 5})]
        )
        report = executor_for(backend, retries=0, replans=1, replanner=make_plan).execute(
            TaskPlan("head", [PlanStep("s1", "set_head", {"yaw_deg": 5})])
        )
        self.assertFalse(report.success)
        self.assertEqual(report.trace.decisions.count("REPLAN"), 1)

    def test_unrecoverable_failure_calls_safe_stop(self):
        backend = MockRobotBackend(ready_state(agv_moving=True))
        backend.inject("set_head", FaultEvent("command_failure"))
        report = executor_for(backend, retries=0).execute(
            TaskPlan("fail", [PlanStep("s1", "set_head", {"yaw_deg": 5})])
        )
        self.assertFalse(report.success)
        self.assertEqual(backend.command_log[-1][0], "safe_stop")
        self.assertFalse(backend.observe().agv_moving)

    def test_nonrepairable_grounding_stop_attempts_stop_once(self):
        backend = SpyBackend(ready_state(emergency_stop=True))
        report = executor_for(backend).execute(
            TaskPlan("blocked", [PlanStep("s1", "set_head", {"yaw_deg": 5})])
        )
        self.assert_stop_attempted_once(backend, report)
        self.assertIn("emergency stop is active", report.message)

    def test_repair_disabled_stop_attempts_stop_once(self):
        backend = SpyBackend(ready_state(right_arm_safe=False))
        report = executor_for(backend).execute(
            TaskPlan("move", [PlanStep("s1", "move_agv", {"distance_m": 1.0})]),
            allow_repair=False,
        )
        self.assert_stop_attempted_once(backend, report)
        self.assertEqual(report.message, "plan is not grounded")

    def test_repair_failure_stop_attempts_stop_once(self):
        backend = SpyBackend(ready_state(right_arm_safe=False))
        executor = executor_for(backend)
        executor.repairer.repair = lambda _plan, _state, _report: None
        report = executor.execute(
            TaskPlan("move", [PlanStep("s1", "move_agv", {"distance_m": 1.0})])
        )
        self.assert_stop_attempted_once(backend, report)
        self.assertEqual(report.message, "plan repair failed")

    def test_invalid_repaired_plan_stop_attempts_stop_once(self):
        backend = SpyBackend(ready_state(right_arm_ready=False, right_arm_safe=False))
        report = executor_for(backend).execute(
            TaskPlan("move", [PlanStep("s1", "move_agv", {"distance_m": 1.0})])
        )
        self.assert_stop_attempted_once(backend, report)
        self.assertEqual(report.message, "repaired plan remains invalid")

    def test_runtime_validation_stop_attempts_stop_once(self):
        backend = SpyBackend(ready_state())
        report = executor_for(backend).execute(
            TaskPlan("bad", [PlanStep("s1", "unknown_skill", {})]),
            ground_plan=False,
        )
        self.assert_stop_attempted_once(backend, report)
        self.assertIn("unknown skill", report.message)

    def test_runtime_guard_stop_attempts_stop_once(self):
        backend = SpyBackend(ready_state(active_resources={"head"}))
        report = executor_for(backend).execute(
            TaskPlan("busy", [PlanStep("s1", "set_head", {"yaw_deg": 5})]),
            ground_plan=False,
        )
        self.assert_stop_attempted_once(backend, report)
        self.assertIn("runtime guard", report.message)

    def test_recovery_disabled_stop_attempts_stop_once(self):
        backend = SpyBackend(ready_state())
        backend.inject("set_head", FaultEvent("command_failure", "head command failed"))
        report = executor_for(backend).execute(
            TaskPlan("head", [PlanStep("s1", "set_head", {"yaw_deg": 5})]),
            allow_recovery=False,
        )
        self.assert_stop_attempted_once(backend, report)
        self.assertEqual(report.message, "head command failed")

    def test_recovery_exhaustion_stop_attempts_stop_once(self):
        backend = SpyBackend(ready_state())
        backend.inject("set_head", FaultEvent("command_failure", "head command failed"))
        report = executor_for(backend, retries=0).execute(
            TaskPlan("head", [PlanStep("s1", "set_head", {"yaw_deg": 5})])
        )
        self.assert_stop_attempted_once(backend, report)
        self.assertEqual(report.message, "no recovery path remains")

    def test_failed_replan_stop_attempts_stop_once(self):
        backend = SpyBackend(ready_state())
        backend.inject("set_head", FaultEvent("command_failure", "head command failed"))
        report = executor_for(
            backend, retries=0, replans=1, replanner=lambda _plan, _state: None
        ).execute(TaskPlan("head", [PlanStep("s1", "set_head", {"yaw_deg": 5})]))
        self.assert_stop_attempted_once(backend, report)
        self.assertEqual(report.message, "retry budget exhausted")

    def test_rejected_stop_preserves_original_failure(self):
        backend = SpyBackend(ready_state(), stop_mode="rejected")
        backend.inject("set_head", FaultEvent("command_failure", "original command failure"))
        report = executor_for(backend, retries=0).execute(
            TaskPlan("head", [PlanStep("s1", "set_head", {"yaw_deg": 5})])
        )
        self.assertEqual(backend.stop_calls, 1)
        self.assertEqual(report.decision, "STOP")
        self.assertEqual(report.message, "no recovery path remains")
        self.assertTrue(report.stop_attempted)
        self.assertFalse(report.stop_accepted)
        self.assertEqual(report.stop_message, "safe-stop request rejected")

    def test_stop_exception_preserves_original_failure(self):
        backend = SpyBackend(ready_state(), stop_mode="raises")
        backend.inject("set_head", FaultEvent("command_failure", "original command failure"))
        report = executor_for(backend, retries=0).execute(
            TaskPlan("head", [PlanStep("s1", "set_head", {"yaw_deg": 5})])
        )
        self.assertEqual(backend.stop_calls, 1)
        self.assertEqual(report.decision, "STOP")
        self.assertEqual(report.message, "no recovery path remains")
        self.assertTrue(report.stop_attempted)
        self.assertFalse(report.stop_accepted)
        self.assertIn("safe-stop transport unavailable", report.stop_message)

    def test_robot_state_last_result_is_persisted(self):
        backend = MockRobotBackend(ready_state())
        executor = executor_for(backend)
        executor.execute(TaskPlan("head", [PlanStep("s1", "set_head", {"yaw_deg": 5})]))
        self.assertEqual(executor.state_manager.refresh().last_skill_result, "success")

    def test_execution_trace_contains_closed_loop_fields(self):
        backend = MockRobotBackend(ready_state())
        report = executor_for(backend).execute(
            TaskPlan("head", [PlanStep("s1", "set_head", {"yaw_deg": 5})])
        )
        record = report.trace.records[0]
        self.assertTrue(record.started_at)
        self.assertTrue(record.ended_at)
        self.assertEqual(record.skill_name, "set_head")
        self.assertTrue(record.command_accepted)
        self.assertTrue(record.outcome_verified)
        self.assertIn("head_yaw_deg", record.after_state)

    def test_runtime_state_drift_is_repaired_before_motion(self):
        backend = MockRobotBackend(ready_state())
        original_observe = backend.observe
        calls = 0

        def drifting_observe():
            nonlocal calls
            calls += 1
            if calls == 3:
                backend.set_state(right_arm_safe=False)
            return original_observe()

        backend.observe = drifting_observe
        report = executor_for(backend).execute(
            TaskPlan("move", [PlanStep("s1", "move_agv", {"distance_m": 1.0})])
        )
        self.assertTrue(report.success)
        self.assertEqual([name for name, _ in backend.command_log[:2]], ["retract_arm", "move_agv"])

    def test_retry_rechecks_guard_and_repairs_drift(self):
        backend = MockRobotBackend(ready_state())
        backend.inject(
            "move_agv",
            FaultEvent("physical_failure", "base did not move", {"right_arm_safe": False}),
        )
        report = executor_for(backend, retries=1).execute(
            TaskPlan("move", [PlanStep("s1", "move_agv", {"distance_m": 1.0})])
        )
        self.assertTrue(report.success)
        self.assertEqual(
            [name for name, _ in backend.command_log[:3]],
            ["move_agv", "retract_arm", "move_agv"],
        )
        self.assertIn("REGROUND", report.trace.decisions)

    def test_without_verification_accepted_command_looks_successful(self):
        backend = MockRobotBackend(ready_state())
        backend.inject("set_lift", FaultEvent("physical_failure"))
        report = executor_for(backend, retries=0).execute(
            TaskPlan("lift", [PlanStep("s1", "set_lift", {"height_mm": 400.0})]),
            verify_outcomes=False,
        )
        self.assertTrue(report.success)
        self.assertEqual(backend.observe().lift_height_mm, 100.0)

    def test_direct_mode_exposes_unsafe_unverified_call(self):
        backend = MockRobotBackend(ready_state(right_arm_safe=False))
        report = executor_for(backend, retries=0).execute(
            TaskPlan("move", [PlanStep("s1", "move_agv", {"distance_m": 1.0})]),
            ground_plan=False,
            runtime_guard=False,
            verify_outcomes=False,
            allow_recovery=False,
        )
        self.assertTrue(report.success)
        self.assertEqual(backend.observe().agv_position_m, 0.0)


if __name__ == "__main__":
    unittest.main()
