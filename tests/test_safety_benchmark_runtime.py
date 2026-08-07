from __future__ import annotations

from pathlib import Path
import unittest

from benchmarks.safety.metrics import MetricValue, summarize_safety_runs
from benchmarks.safety.model import load_safety_scenarios
from benchmarks.safety.profiles import (
    PROFILE_NAMES,
    ActionObservation,
    ProfileName,
    SafetyRunObservation,
    run_safety_scenario,
)


ROOT = Path(__file__).resolve().parents[1]


class SafetyMetricsTests(unittest.TestCase):
    def test_zero_denominator_is_na_not_zero(self):
        value = MetricValue.from_counts(0, 0)

        self.assertIsNone(value.value)
        self.assertEqual("N/A", value.display)

    def test_evidence_coverage_is_na_for_profiles_without_evidence_concept(self):
        scenario = load_safety_scenarios(
            ROOT / "benchmarks" / "safety" / "scenarios.json"
        ).scenarios[-1]
        action = ActionObservation(
            step_id="head",
            command_count=1,
            dispatch_states=({},),
            claimed_physical_success=True,
            evidence_backed_success=False,
        )
        run = SafetyRunObservation(
            scenario_id=scenario.scenario_id,
            hazard_id=scenario.hazard_id,
            profile=ProfileName.DIRECT,
            actions=(action,),
            recovery_actions=(),
            stop_attempts=0,
            stop_results=(),
            task_success=True,
            reported_success=True,
            evidence_supported=False,
            final_state={},
        )

        summary = summarize_safety_runs([(scenario, run)])

        self.assertIsNone(summary.metrics["evidence_coverage"].value)


class SafetyProfileBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catalog = load_safety_scenarios(
            ROOT / "benchmarks" / "safety" / "scenarios.json"
        )
        cls.scenarios = {item.scenario_id: item for item in catalog.scenarios}

    def test_all_profiles_receive_the_same_typed_scenario(self):
        scenario = self.scenarios["H-003-accepted-no-effect-01"]

        runs = [run_safety_scenario(scenario, profile) for profile in PROFILE_NAMES]

        self.assertEqual(
            {scenario.scenario_id}, {run.scenario_id for run in runs}
        )

    def test_accepted_without_effect_exposes_false_baseline_claims(self):
        scenario = self.scenarios["H-003-accepted-no-effect-01"]

        runs = {
            profile: run_safety_scenario(scenario, profile)
            for profile in PROFILE_NAMES
        }

        self.assertTrue(runs[ProfileName.DIRECT].actions[0].claimed_physical_success)
        self.assertTrue(runs[ProfileName.GUARDED].actions[0].claimed_physical_success)
        self.assertTrue(runs[ProfileName.CONTRACT_EVIDENCE].actions[0].claimed_physical_success)
        self.assertTrue(runs[ProfileName.CONTRACT_EVIDENCE].actions[0].evidence_backed_success)
        self.assertFalse(runs[ProfileName.FULL].actions[0].claimed_physical_success)

    def test_non_idempotent_uncertain_outcome_separates_c_and_d(self):
        scenario = self.scenarios["H-004-uncertain-dispatch-02"]

        contract_evidence = run_safety_scenario(
            scenario, ProfileName.CONTRACT_EVIDENCE
        )
        full = run_safety_scenario(scenario, ProfileName.FULL)

        self.assertEqual(2, contract_evidence.actions[0].command_count)
        self.assertEqual(1, full.actions[0].command_count)
        self.assertIn("REOBSERVE", full.recovery_actions)

    def test_stale_state_is_ignored_only_by_profiles_without_freshness(self):
        scenario = self.scenarios["H-002-stale-safe-state-03"]

        runs = {
            profile: run_safety_scenario(scenario, profile)
            for profile in PROFILE_NAMES
        }

        self.assertEqual(1, runs[ProfileName.DIRECT].actions[0].command_count)
        self.assertEqual(1, runs[ProfileName.GUARDED].actions[0].command_count)
        self.assertEqual(0, runs[ProfileName.CONTRACT_EVIDENCE].actions[0].command_count)
        self.assertEqual(0, runs[ProfileName.FULL].actions[0].command_count)

    def test_unknown_capability_reaches_only_direct_backend_boundary(self):
        scenario = self.scenarios["H-005-unknown-skill-01"]

        runs = {
            profile: run_safety_scenario(scenario, profile)
            for profile in PROFILE_NAMES
        }

        self.assertEqual(1, runs[ProfileName.DIRECT].actions[0].command_count)
        self.assertEqual(0, runs[ProfileName.GUARDED].actions[0].command_count)
        self.assertEqual(0, runs[ProfileName.CONTRACT_EVIDENCE].actions[0].command_count)
        self.assertEqual(0, runs[ProfileName.FULL].actions[0].command_count)


if __name__ == "__main__":
    unittest.main()
