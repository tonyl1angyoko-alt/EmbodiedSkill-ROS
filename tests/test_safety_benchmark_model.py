from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.safety.model import (
    FaultClass,
    load_safety_scenarios,
    validate_safety_scenarios,
)


KNOWN_HAZARDS = {f"H-{index:03d}" for index in range(1, 9)}


def valid_scenario(scenario_id: str = "H-001-model-01") -> dict:
    return {
        "scenario_id": scenario_id,
        "hazard_id": "H-001",
        "description": "A model-validation fixture.",
        "positive_control": True,
        "fault_class": "control",
        "initial_state": {"left_arm_safe": True, "right_arm_safe": True},
        "plan": [
            {
                "step_id": "move",
                "skill": "move_agv",
                "arguments": {"distance_m": 1.0},
            }
        ],
        "injected_fault": {"kind": "none"},
        "expected_safe_property": "Safe base motion may be dispatched.",
        "oracle": {
            "actions": [
                {
                    "step_id": "move",
                    "dispatch_allowed": True,
                    "commit_allowed": True,
                    "max_command_count": 1,
                    "protected_non_idempotent": False,
                    "unsupported_capability": False,
                    "counts_for_frr": True,
                }
            ],
            "stop_required": False,
            "allowed_recovery_actions": [],
            "final_state": {"agv_position_m": 1.0},
        },
    }


class SafetyBenchmarkModelTests(unittest.TestCase):
    def _load(self, scenarios: list[dict]):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenarios.json"
            path.write_text(
                json.dumps({"schema_version": 1, "scenarios": scenarios}),
                encoding="utf-8",
            )
            return load_safety_scenarios(path)

    def test_loads_typed_scenario_and_explicit_oracle(self):
        catalog = self._load([valid_scenario()])

        scenario = catalog.scenarios[0]
        self.assertEqual(FaultClass.CONTROL, scenario.fault_class)
        self.assertEqual("move_agv", scenario.plan[0].skill)
        self.assertTrue(scenario.oracle.actions[0].dispatch_allowed)
        self.assertEqual({"agv_position_m": 1.0}, scenario.oracle.final_state)

    def test_validation_rejects_duplicate_scenario_ids(self):
        catalog = self._load([valid_scenario(), valid_scenario()])

        issues = validate_safety_scenarios(catalog, known_hazard_ids=KNOWN_HAZARDS)

        self.assertTrue(any("duplicate scenario_id" in issue for issue in issues))

    def test_validation_rejects_unknown_hazard(self):
        scenario = valid_scenario()
        scenario["hazard_id"] = "H-999"
        catalog = self._load([scenario])

        issues = validate_safety_scenarios(catalog, known_hazard_ids=KNOWN_HAZARDS)

        self.assertTrue(any("unknown hazard_id" in issue for issue in issues))

    def test_validation_requires_exact_action_oracle_coverage(self):
        scenario = valid_scenario()
        scenario["oracle"]["actions"][0]["step_id"] = "different"
        catalog = self._load([scenario])

        issues = validate_safety_scenarios(catalog, known_hazard_ids=KNOWN_HAZARDS)

        self.assertTrue(any("action oracle step_ids" in issue for issue in issues))

    def test_loader_rejects_non_finite_json_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenarios.json"
            path.write_text(
                '{"schema_version": 1, "scenarios": [NaN]}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "non-finite JSON constant"):
                load_safety_scenarios(path)


if __name__ == "__main__":
    unittest.main()
