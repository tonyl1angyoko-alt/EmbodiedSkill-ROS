from dataclasses import replace
from pathlib import Path
import unittest

from embodied_skill_ros.safety.hazard_catalog import (
    CORE_SAFETY_MECHANISM_REFS,
    REQUIRED_HAZARD_IDS,
    SYSTEM_LEVEL_TOKEN,
    HazardCatalog,
    load_hazard_catalog,
    validate_hazard_catalog,
)
from embodied_skill_ros.skills.registry import build_default_registry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = PROJECT_ROOT / "config" / "hazards.json"


class HazardCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_hazard_catalog(CATALOG_PATH)
        cls.hazards = {item.hazard_id: item for item in cls.catalog.hazards}
        cls.validation_issues = validate_hazard_catalog(
            cls.catalog,
            project_root=PROJECT_ROOT,
            registered_skills=build_default_registry().names(),
        )

    def test_catalog_loads_required_unique_hazards(self):
        self.assertLessEqual(REQUIRED_HAZARD_IDS, set(self.hazards))
        self.assertEqual(len(self.catalog.hazards), len(self.hazards))
        self.assertTrue(all(item.hazard_id.startswith("H-00") for item in self.catalog.hazards))

    def test_catalog_has_no_validation_issues(self):
        self.assertEqual(self.validation_issues, ())

    def test_hazards_have_machine_testable_safety_properties(self):
        for hazard in self.catalog.hazards:
            with self.subTest(hazard=hazard.hazard_id):
                self.assertTrue(hazard.title.strip())
                self.assertTrue(hazard.description.strip())
                self.assertTrue(hazard.unsafe_control_action.strip())
                self.assertTrue(hazard.safety_property.strip())
                self.assertIn("MUST", hazard.safety_property)
                self.assertTrue(hazard.enforced_by)
                self.assertTrue(hazard.regression_tests)

    def test_related_skills_are_registered_or_system_level(self):
        allowed = set(build_default_registry().names()) | {SYSTEM_LEVEL_TOKEN}
        for hazard in self.catalog.hazards:
            with self.subTest(hazard=hazard.hazard_id):
                self.assertTrue(hazard.related_skills)
                self.assertLessEqual(set(hazard.related_skills), allowed)

    def test_false_commit_hazard_references_evidence_and_transaction_gates(self):
        hazard = self.hazards["H-003"]
        self.assertIn(
            "embodied_skill_ros.execution.outcome_verifier:OutcomeVerifier.verify",
            hazard.enforced_by,
        )
        self.assertIn(
            "embodied_skill_ros.models.transaction:SkillTransaction.apply_verification",
            hazard.enforced_by,
        )
        self.assertTrue(any("EvidenceRequirement" in ref for ref in hazard.contract_refs))

    def test_non_idempotency_hazard_references_recovery_and_checkpoint(self):
        hazard = self.hazards["H-004"]
        self.assertIn(
            "embodied_skill_ros.execution.recovery_manager:RecoveryManager.decide",
            hazard.enforced_by,
        )
        self.assertIn(
            "embodied_skill_ros.execution.skill_executor:SkillExecutor._protected_replan_replay",
            hazard.enforced_by,
        )

    def test_reverse_coverage_has_no_orphan_core_mechanisms(self):
        referenced = {
            ref
            for hazard in self.catalog.hazards
            for ref in (*hazard.contract_refs, *hazard.enforced_by)
        }
        self.assertEqual(CORE_SAFETY_MECHANISM_REFS - referenced, frozenset())

    def test_regressions_are_behavioral_tests_not_catalog_self_tests(self):
        references = {
            ref for hazard in self.catalog.hazards for ref in hazard.regression_tests
        }
        self.assertTrue(any("test_execution.py" in ref for ref in references))
        self.assertTrue(any("test_freshness.py" in ref for ref in references))
        self.assertTrue(any("test_transactions.py" in ref for ref in references))
        self.assertTrue(any("test_recovery_policy.py" in ref for ref in references))
        self.assertFalse(any("test_hazard_catalog.py" in ref for ref in references))

    def test_validator_rejects_nonexistent_python_and_test_references(self):
        original = self.catalog.hazards[0]
        invalid = replace(
            original,
            enforced_by=("embodied_skill_ros.missing:NoSuchEnforcement",),
            regression_tests=(
                "tests/test_execution.py::ExecutionTests.test_does_not_exist",
            ),
        )
        catalog = HazardCatalog((invalid, *self.catalog.hazards[1:]))
        issues = validate_hazard_catalog(
            catalog,
            project_root=PROJECT_ROOT,
            registered_skills=build_default_registry().names(),
        )
        self.assertTrue(any("NoSuchEnforcement" in issue for issue in issues))
        self.assertTrue(any("test_does_not_exist" in issue for issue in issues))

    def test_validator_rejects_malformed_duplicate_ids_and_unknown_skills(self):
        malformed = replace(
            self.catalog.hazards[0],
            hazard_id="hazard-one",
            related_skills=("teleport",),
        )
        duplicate = replace(self.catalog.hazards[1], hazard_id="hazard-one")
        catalog = HazardCatalog((malformed, duplicate, *self.catalog.hazards[2:]))
        issues = validate_hazard_catalog(
            catalog,
            project_root=PROJECT_ROOT,
            registered_skills=build_default_registry().names(),
        )
        self.assertTrue(any("must match H-XXX" in issue for issue in issues))
        self.assertTrue(any("duplicate hazard_id" in issue for issue in issues))
        self.assertTrue(any("teleport" in issue for issue in issues))

    def test_catalog_is_not_a_runtime_authorization_dependency(self):
        runtime_files = list((PROJECT_ROOT / "embodied_skill_ros").rglob("*.py"))
        runtime_files = [
            path for path in runtime_files
            if "/safety/" not in path.as_posix()
        ]
        for path in runtime_files:
            with self.subTest(path=path.relative_to(PROJECT_ROOT)):
                self.assertNotIn("hazard_catalog", path.read_text(encoding="utf-8"))

    def test_catalog_avoids_certification_and_formal_claims(self):
        text = CATALOG_PATH.read_text(encoding="utf-8").lower()
        for prohibited in (
            "stpa compliant",
            "formal safety case",
            "iso certified",
            "verified safe",
            "production safe",
        ):
            with self.subTest(prohibited=prohibited):
                self.assertNotIn(prohibited, text)


if __name__ == "__main__":
    unittest.main()
