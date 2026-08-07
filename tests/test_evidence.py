import unittest

from embodied_skill_ros.execution.outcome_verifier import OutcomeVerifier
from embodied_skill_ros.models.evidence import EvidenceRequirement, PhysicalEvidence
from embodied_skill_ros.models.safety_contract import (
    Idempotency,
    RiskClass,
    Rollbackability,
    SkillSafetyContract,
)
from embodied_skill_ros.skills.base_skill import RobotSkill
from embodied_skill_ros.skills.registry import build_default_registry

from test_models_and_registry import ready_state


class UnspecifiedEvidenceSkill(RobotSkill):
    def __init__(self):
        super().__init__(
            "unspecified_evidence",
            "A test skill with an expected effect but no evidence requirement.",
            {},
            {"test"},
            {},
            1.0,
            safety_contract=SkillSafetyContract(
                risk_class=RiskClass.LOW,
                idempotency=Idempotency.IDEMPOTENT,
                rollbackability=Rollbackability.NOT_AUTOMATIC,
            ),
        )

    def expected_effects(self, arguments, before):
        return {"head_yaw_deg": 5.0}


class PhysicalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.verifier = OutcomeVerifier()
        self.head = build_default_registry().get("set_head")

    def test_evidence_models_serialize_auditable_fields(self):
        requirement = EvidenceRequirement(
            "head_yaw_deg", tolerance=0.5, maximum_age_ms=1000
        )
        evidence = PhysicalEvidence(
            source="robot_state",
            state_field="head_yaw_deg",
            measured_at="2026-01-02T03:04:05+00:00",
            received_at="2026-01-02T03:04:05.100000+00:00",
            observed_value=5.0,
            expected_value=5.0,
            tolerance=0.5,
            fresh=None,
            valid=True,
            matches_expected=True,
            reason="evidence matches expected effect",
        )
        self.assertEqual(requirement.to_dict()["maximum_age_ms"], 1000)
        self.assertEqual(evidence.to_dict()["matches_expected"], True)
        self.assertNotIn("side_effect", evidence.to_dict())

    def test_complete_matching_evidence_is_commit_ready(self):
        before = ready_state(head_yaw_deg=0.0).copy(
            timestamp="2026-01-02T03:04:05+00:00"
        )
        after = before.copy(head_yaw_deg=5.0)
        result = self.verifier.verify(self.head, {"yaw_deg": 5.0}, before, after)
        self.assertTrue(result.achieved)
        self.assertTrue(result.evidence_complete)
        self.assertTrue(result.commit_ready)
        self.assertEqual(len(result.evidence), 1)
        self.assertTrue(result.evidence[0].valid)
        self.assertTrue(result.evidence[0].matches_expected)

    def test_complete_mismatching_evidence_is_valid_but_not_achieved(self):
        before = ready_state(head_yaw_deg=0.0).copy(
            timestamp="2026-01-02T03:04:05+00:00"
        )
        after = before.copy(head_yaw_deg=2.0)
        result = self.verifier.verify(self.head, {"yaw_deg": 5.0}, before, after)
        self.assertFalse(result.achieved)
        self.assertTrue(result.evidence_complete)
        self.assertFalse(result.commit_ready)
        self.assertTrue(result.evidence[0].valid)
        self.assertFalse(result.evidence[0].matches_expected)

    def test_missing_observation_produces_explicit_invalid_evidence(self):
        before = ready_state(head_yaw_deg=0.0)
        after = before.copy(head_yaw_deg=None)
        result = self.verifier.verify(self.head, {"yaw_deg": 5.0}, before, after)
        self.assertFalse(result.evidence_complete)
        self.assertFalse(result.commit_ready)
        self.assertFalse(result.evidence[0].valid)
        self.assertIn("missing", result.evidence[0].reason)

    def test_non_finite_observation_produces_invalid_evidence(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                before = ready_state(head_yaw_deg=0.0)
                after = before.copy(head_yaw_deg=value)
                result = self.verifier.verify(
                    self.head, {"yaw_deg": 5.0}, before, after
                )
                self.assertFalse(result.evidence_complete)
                self.assertFalse(result.evidence[0].valid)
                self.assertIn("non-finite", result.evidence[0].reason)

    def test_invalid_measurement_timestamp_produces_invalid_evidence(self):
        before = ready_state(head_yaw_deg=0.0)
        after = before.copy(head_yaw_deg=5.0, timestamp="not-a-timestamp")
        result = self.verifier.verify(self.head, {"yaw_deg": 5.0}, before, after)
        self.assertFalse(result.evidence_complete)
        self.assertFalse(result.commit_ready)
        self.assertFalse(result.evidence[0].valid)
        self.assertIn("timestamp", result.evidence[0].reason)

    def test_missing_requirement_is_an_explicit_invalid_record(self):
        skill = UnspecifiedEvidenceSkill()
        before = ready_state(head_yaw_deg=0.0)
        after = before.copy(head_yaw_deg=5.0)
        result = self.verifier.verify(skill, {}, before, after)
        self.assertFalse(result.evidence_complete)
        self.assertFalse(result.commit_ready)
        self.assertEqual(len(result.evidence), 1)
        self.assertFalse(result.evidence[0].valid)
        self.assertIn("requirement", result.evidence[0].reason)

    def test_expected_value_still_comes_from_skill_expected_effects(self):
        move = build_default_registry().get("move_agv")
        before = ready_state(agv_position_m=2.0)
        after = before.copy(agv_position_m=3.0)
        result = self.verifier.verify(move, {"distance_m": 1.0}, before, after)
        position = next(
            item for item in result.evidence if item.state_field == "agv_position_m"
        )
        self.assertEqual(position.expected_value, 3.0)
        self.assertTrue(result.commit_ready)


if __name__ == "__main__":
    unittest.main()
