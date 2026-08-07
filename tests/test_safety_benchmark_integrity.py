from __future__ import annotations

import json
from pathlib import Path
import unittest

from benchmarks.safety.metrics import summarize_safety_runs
from benchmarks.safety.model import (
    load_safety_scenarios,
    validate_safety_scenarios,
)
from benchmarks.safety.profiles import (
    PROFILE_NAMES,
    ProfileName,
    run_safety_scenario,
)
from benchmarks.safety.run_safety_benchmark import (
    METRIC_DEFINITIONS,
    run_catalog,
)
from embodied_skill_ros.safety.hazard_catalog import load_hazard_catalog


ROOT = Path(__file__).resolve().parents[1]
SCENARIO_PATH = ROOT / "benchmarks" / "safety" / "scenarios.json"
RESULT_PATH = ROOT / "benchmarks" / "safety" / "safety_results.json"


def _contains_key(value, target: str) -> bool:
    if isinstance(value, dict):
        return target in value or any(
            _contains_key(item, target) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key(item, target) for item in value)
    return False


class SafetyBenchmarkIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_safety_scenarios(SCENARIO_PATH)
        cls.scenarios = {
            item.scenario_id: item for item in cls.catalog.scenarios
        }
        cls.hazard_ids = {
            item.hazard_id
            for item in load_hazard_catalog(ROOT / "config" / "hazards.json").hazards
        }
        cls.output = run_catalog(SCENARIO_PATH)

    def test_unique_ids_and_complete_hazard_references(self):
        ids = [item.scenario_id for item in self.catalog.scenarios]

        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            self.hazard_ids,
            {item.hazard_id for item in self.catalog.scenarios},
        )
        self.assertEqual(
            (),
            validate_safety_scenarios(
                self.catalog,
                known_hazard_ids=self.hazard_ids,
                require_balanced_hazards=True,
            ),
        )

    def test_every_hazard_has_adversarial_and_positive_control(self):
        for hazard_id in self.hazard_ids:
            family = [
                item for item in self.catalog.scenarios
                if item.hazard_id == hazard_id
            ]
            self.assertGreaterEqual(len(family), 3)
            self.assertTrue(any(item.positive_control for item in family))
            self.assertTrue(any(not item.positive_control for item in family))

    def test_positive_controls_are_exactly_one_quarter(self):
        positives = sum(item.positive_control for item in self.catalog.scenarios)

        self.assertEqual(10, positives)
        self.assertEqual(40, len(self.catalog.scenarios))

    def test_metric_denominators_are_derived_from_all_oracle_opportunities(self):
        direct = self.output["profiles"][ProfileName.DIRECT.value]["metrics"]

        self.assertEqual(20, direct["unsafe_action_execution_rate"]["denominator"])
        self.assertEqual(28, direct["false_commit_rate"]["denominator"])
        self.assertEqual(17, direct["duplicate_side_effect_rate"]["denominator"])
        self.assertEqual(3, direct["unsupported_capability_invocation_rate"]["denominator"])
        self.assertEqual(25, direct["safe_stop_attempt_coverage"]["denominator"])
        self.assertEqual(27, direct["false_refusal_rate"]["denominator"])
        self.assertEqual(40, direct["task_success_rate"]["denominator"])

    def test_every_metric_documents_numerator_and_denominator(self):
        expected = {
            "unsafe_action_execution_rate",
            "false_commit_rate",
            "duplicate_side_effect_rate",
            "unsupported_capability_invocation_rate",
            "evidence_coverage",
            "safe_recovery_rate",
            "safe_stop_attempt_coverage",
            "false_refusal_rate",
            "task_success_rate",
        }

        self.assertEqual(expected, set(METRIC_DEFINITIONS))
        for definition in METRIC_DEFINITIONS.values():
            self.assertTrue(definition["numerator"].strip())
            self.assertTrue(definition["denominator"].strip())

    def test_na_is_not_serialized_as_zero(self):
        for profile in (ProfileName.DIRECT, ProfileName.GUARDED):
            metric = self.output["profiles"][profile.value]["metrics"][
                "evidence_coverage"
            ]
            self.assertIsNone(metric["value"])
            self.assertEqual("N/A", metric["display"])
            self.assertEqual(0, metric["denominator"])

    def test_oracle_model_and_metric_evaluator_do_not_import_runtime_oracles(self):
        for relative in (
            "benchmarks/safety/model.py",
            "benchmarks/safety/metrics.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("ConstraintChecker", source)
            self.assertNotIn("OutcomeVerifier", source)
            self.assertNotIn("ExecutionReport.success", source)

    def test_profiles_use_identical_scenario_order_and_ids(self):
        expected = [item.scenario_id for item in self.catalog.scenarios]

        for profile in PROFILE_NAMES:
            observed = [
                item["scenario_id"]
                for item in self.output["profiles"][profile.value]["runs"]
            ]
            self.assertEqual(expected, observed)

    def test_profile_code_has_no_hazard_or_scenario_id_special_cases(self):
        source = (ROOT / "benchmarks/safety/profiles.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("H-001", source)
        self.assertNotIn("H-008", source)
        self.assertNotIn("allow_unsafe", source)
        self.assertIn("SkillExecutor", source)

    def test_legitimate_original_duplicate_actions_are_not_dser_violations(self):
        scenario = self.scenarios["H-004-legitimate-repeat-04"]

        for profile in PROFILE_NAMES:
            run = run_safety_scenario(scenario, profile)
            summary = summarize_safety_runs([(scenario, run)])
            metric = summary.metrics["duplicate_side_effect_rate"]
            self.assertEqual(0, metric.numerator)
            self.assertEqual(2, metric.denominator)

    def test_full_profile_stop_attempts_are_exactly_once_and_auditable(self):
        full = self.output["profiles"][ProfileName.FULL.value]
        metric = full["metrics"]["safe_stop_attempt_coverage"]

        self.assertEqual(metric["denominator"], metric["numerator"])
        self.assertEqual(
            metric["denominator"], sum(full["stop_outcomes"].values())
        )
        self.assertEqual(1, full["stop_outcomes"]["rejected"])
        self.assertEqual(1, full["stop_outcomes"]["exception"])

    def test_direct_profile_still_performs_basic_nonfinite_argument_parsing(self):
        scenario = self.scenarios["H-007-nonfinite-commands-01"]
        run = run_safety_scenario(scenario, ProfileName.DIRECT)

        self.assertEqual([0, 0, 0], [item.command_count for item in run.actions])

    def test_results_are_deterministic_and_match_tracked_artifact(self):
        second = run_catalog(SCENARIO_PATH)
        tracked = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

        self.assertEqual(self.output, second)
        self.assertEqual(self.output, tracked)

    def test_deterministic_artifact_contains_no_latency_fields(self):
        self.assertFalse(_contains_key(self.output, "latency"))
        self.assertFalse(_contains_key(self.output, "latency_ms"))
        self.assertNotIn(
            "benchmark_results.json",
            str(RESULT_PATH.relative_to(ROOT)),
        )


if __name__ == "__main__":
    unittest.main()
