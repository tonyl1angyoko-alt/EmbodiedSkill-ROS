import inspect
import json
from dataclasses import fields
from pathlib import Path
import sys
import unittest

from embodied_skill_ros.backends.mock_backend import (
    FaultEvent, MockRobotBackend, ObservationModel,
)
from embodied_skill_ros.evaluation.oracle import BenchmarkOracle
from embodied_skill_ros.execution.outcome_verifier import OutcomeVerifier
from embodied_skill_ros.execution.skill_executor import SkillExecutor
from embodied_skill_ros.models.robot_state import RobotState
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan
from embodied_skill_ros.skills.registry import build_default_registry

BENCHMARK_DIR = Path(__file__).resolve().parents[1] / "benchmarks"
sys.path.insert(0, str(BENCHMARK_DIR))

from adversarial_v2 import (
    FAMILIES, PROFILES, run_suite, run_trial, verify_core_freeze,
)
from procedural_faults import generate_trials


def ready_state(**changes):
    state = RobotState(
        left_arm_ready=True,
        right_arm_ready=True,
        left_arm_safe=True,
        right_arm_safe=True,
        agv_ready=True,
        agv_moving=False,
        agv_position_m=0.0,
        lift_ready=True,
        lift_height_mm=100.0,
        head_ready=True,
        head_yaw_deg=0.0,
        head_pitch_deg=0.0,
        emergency_stop=False,
    )
    return state.copy(**changes)


class BenchmarkIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios = json.loads(
            (BENCHMARK_DIR / "scenarios.json").read_text(encoding="utf-8")
        )

    def test_fixture_has_unique_ids_and_required_category_coverage(self):
        ids = [item["id"] for item in self.scenarios]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 30)
        categories = {item["category"] for item in self.scenarios}
        self.assertTrue({"single", "multi", "state", "conflict", "fault"} <= categories)

    def test_expected_state_uses_declared_robot_fields(self):
        allowed = {item.name for item in fields(RobotState)}
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario["id"]):
                self.assertFalse(set(scenario["expected_state"]) - allowed)

    def test_faults_only_target_steps_in_the_scenario(self):
        for scenario in self.scenarios:
            skills = {step["skill"] for step in scenario["steps"]}
            for fault in scenario.get("faults", []):
                with self.subTest(scenario=scenario["id"]):
                    self.assertIn(fault["skill"], skills)

    def test_procedural_generation_is_seeded_and_fixture_independent(self):
        first = generate_trials(41, 64)
        second = generate_trials(41, 64)
        other = generate_trials(42, 64)
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertEqual(len({item["id"] for item in first}), 64)


class OracleBoundaryTests(unittest.TestCase):
    def test_runtime_execution_modules_have_no_oracle_dependency(self):
        source = inspect.getsource(OutcomeVerifier) + inspect.getsource(SkillExecutor)
        self.assertNotIn("oracle_state", source)
        self.assertNotIn("BenchmarkOracle", source)

    def test_oracle_does_not_reuse_runtime_verification(self):
        source = inspect.getsource(BenchmarkOracle)
        self.assertNotIn("verify_outcome", source)
        self.assertNotIn("StatePredicate", source)
        self.assertNotIn("OutcomeVerifier", source)

    def test_executor_cannot_read_hidden_truth(self):
        class OracleForbiddenBackend(MockRobotBackend):
            def oracle_state(self):
                raise AssertionError("executor attempted to read oracle truth")

        backend = OracleForbiddenBackend(ready_state())
        report = SkillExecutor(build_default_registry(), backend).execute(
            TaskPlan("head", [
                PlanStep("head", "set_head", {"yaw_deg": 12.0})
            ])
        )
        self.assertTrue(report.success)

    def test_oracle_result_is_independent_of_broken_runtime_verifier(self):
        backend = MockRobotBackend(ready_state(head_yaw_deg=31.0))
        original = OutcomeVerifier.verify

        def explode(*_args, **_kwargs):
            raise AssertionError("runtime verifier must not be called by oracle")

        OutcomeVerifier.verify = explode
        try:
            result = BenchmarkOracle().evaluate(
                backend, {"head_yaw_deg": 31.0}
            )
        finally:
            OutcomeVerifier.verify = original
        self.assertTrue(result.success)


class FalsePositiveEvidenceTests(unittest.TestCase):
    @staticmethod
    def _plan():
        return TaskPlan(
            "set hidden head pose",
            [PlanStep("head", "set_head", {"yaw_deg": 25.0})],
            metadata={"goal_state": {"head_yaw_deg": 25.0}},
        )

    @staticmethod
    def _backend(*, stale):
        return MockRobotBackend(
            ready_state(head_yaw_deg=0.0),
            ObservationModel(
                stale_fields=(frozenset({"head_yaw_deg"}) if stale else frozenset()),
                overrides=(("head_yaw_deg", 25.0),),
            ),
        )

    def test_direct_unverified_accepts_command_but_oracle_rejects(self):
        backend = self._backend(stale=True)
        backend.inject_permanent(
            "set_head", FaultEvent("physical_failure", "motor did not move")
        )
        report = SkillExecutor(build_default_registry(), backend).execute(
            self._plan(), verify_outcomes=False, allow_recovery=False
        )
        oracle = BenchmarkOracle().evaluate(
            backend, {"head_yaw_deg": 25.0}
        )
        self.assertTrue(report.success)
        self.assertTrue(report.results[0].command_accepted)
        self.assertFalse(oracle.success)

    def test_stale_misleading_observation_is_rejected_by_full_verifier(self):
        backend = self._backend(stale=True)
        backend.inject_permanent(
            "set_head", FaultEvent("physical_failure", "motor did not move")
        )
        report = SkillExecutor(
            build_default_registry(), backend, max_retries=0
        ).execute(self._plan())
        oracle = BenchmarkOracle().evaluate(
            backend, {"head_yaw_deg": 25.0}
        )
        self.assertFalse(report.success)
        self.assertFalse(report.results[0].physical_outcome_achieved)
        self.assertIn("STALE", report.results[0].message)
        self.assertFalse(oracle.success)

    def test_fresh_spoof_is_a_real_full_system_false_positive(self):
        backend = self._backend(stale=False)
        backend.inject_permanent(
            "set_head", FaultEvent("physical_failure", "motor did not move")
        )
        report = SkillExecutor(build_default_registry(), backend).execute(
            self._plan()
        )
        oracle = BenchmarkOracle().evaluate(
            backend, {"head_yaw_deg": 25.0}
        )
        self.assertTrue(report.success)
        self.assertTrue(report.results[0].physical_outcome_achieved)
        self.assertFalse(oracle.success)
        self.assertEqual(
            backend.oracle_state().head_yaw_deg, 0.0,
            "physical truth must remain unchanged despite fresh spoof",
        )


class FrozenCoreAdversarialBenchmarkTests(unittest.TestCase):
    @staticmethod
    def _full_profile():
        return next(item for item in PROFILES if item.name == "F_full")

    def test_core_freeze_manifest_still_matches_exact_bytes_and_loc(self):
        manifest = verify_core_freeze()
        self.assertEqual(manifest["total_core_lines"], 1385)

    def test_two_new_skills_require_zero_frozen_core_changes(self):
        family = next(item for item in FAMILIES if item.name == "multi_step_repair")
        row = run_trial(family, 999, self._full_profile())
        self.assertTrue(row["task_completion"])
        self.assertEqual(
            row["executed_plan"],
            ["deploy_stabilizer", "secure_payload", "transport_payload"],
        )
        manifest = verify_core_freeze()
        for relative in manifest["files"]:
            source = (Path(__file__).resolve().parents[1] / relative).read_text(
                encoding="utf-8"
            )
            self.assertNotIn("deploy_stabilizer", source)
            self.assertNotIn("secure_payload", source)

    def test_full_suite_includes_unrecoverable_cases_and_real_failure(self):
        result = run_suite(self._full_profile(), range(0, 1))
        by_name = {item["name"]: item for item in result["families"]}
        required = {
            "permanent_actuator", "permanent_sensor_blindness",
            "capability_mismatch", "contradictory_observation",
            "impossible_predicate", "irreparable_conflict",
            "replan_dead_end", "fresh_sensor_spoof",
        }
        self.assertTrue(required <= set(by_name))
        self.assertEqual(by_name["fresh_sensor_spoof"]["full_system_result"], "FAIL")
        self.assertLess(result["metrics"]["overall_correct_decision_rate"], 1.0)
        self.assertLess(result["metrics"]["task_completion_rate"], 1.0)

    def test_replan_changes_failed_skill_and_dead_end_does_not_fake_success(self):
        full = self._full_profile()
        alternate = run_trial(
            next(item for item in FAMILIES if item.name == "genuine_replan"),
            1, full,
        )
        dead_end = run_trial(
            next(item for item in FAMILIES if item.name == "replan_dead_end"),
            1, full,
        )
        self.assertTrue(alternate["replan_attempted"])
        self.assertEqual(alternate["executed_plan"], ["alternate_route"])
        self.assertEqual(alternate["commands"][-1], "alternate_route")
        self.assertTrue(dead_end["replan_attempted"])
        self.assertFalse(dead_end["report_success"])
        self.assertFalse(dead_end["oracle_success"])

    def test_holdout_cardinality_is_between_fifty_and_one_hundred(self):
        result = run_suite(self._full_profile(), range(100, 106))
        self.assertEqual(result["trials"], 78)
        self.assertGreaterEqual(result["trials"], 50)
        self.assertLessEqual(result["trials"], 100)


if __name__ == "__main__":
    unittest.main()
