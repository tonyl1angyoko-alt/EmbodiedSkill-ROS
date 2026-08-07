import json
import unittest

from embodied_skill_ros.backends.mock_backend import MockRobotBackend
from embodied_skill_ros.execution.skill_executor import SkillExecutor
from embodied_skill_ros.models.safety_contract import (
    Idempotency,
    RiskClass,
    Rollbackability,
    SkillSafetyContract,
)
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan
from embodied_skill_ros.planner.llm_adapter import LLMPlannerAdapter
from embodied_skill_ros.skills.base_skill import RobotSkill
from embodied_skill_ros.skills.registry import SkillRegistry, build_default_registry

from test_models_and_registry import ready_state


class MissingContractSkill(RobotSkill):
    def __init__(self):
        super().__init__("missing_contract", "Test skill without a safety contract.",
                         {}, {"test"}, {}, 1.0)


class UnknownContractSkill(RobotSkill):
    def __init__(self):
        super().__init__(
            "unknown_contract",
            "Test skill whose contract exists but is incomplete.",
            {},
            {"test"},
            {},
            1.0,
            safety_contract=SkillSafetyContract(
                risk_class=RiskClass.UNKNOWN,
                idempotency=Idempotency.UNKNOWN,
                rollbackability=Rollbackability.UNKNOWN,
            ),
        )


class SafetyContractTests(unittest.TestCase):
    def test_default_skills_have_explicit_complete_provisional_contracts(self):
        for skill in build_default_registry():
            with self.subTest(skill=skill.name):
                self.assertIsNotNone(skill.safety_contract)
                self.assertTrue(skill.safety_contract.is_complete)
                self.assertTrue(skill.safety_contract.risk_class_is_provisional)

    def test_contract_serialization_uses_stable_string_values(self):
        contract = SkillSafetyContract(
            risk_class=RiskClass.HIGH,
            idempotency=Idempotency.NON_IDEMPOTENT,
            rollbackability=Rollbackability.NOT_AUTOMATIC,
            maximum_state_age_ms=750,
            requires_human_approval=True,
            compensation_skill="recover_pose",
        )
        self.assertEqual(contract.to_dict(), {
            "risk_class": "high",
            "risk_class_is_provisional": True,
            "idempotency": "non_idempotent",
            "rollbackability": "not_automatic",
            "maximum_state_age_ms": 750,
            "requires_human_approval": True,
            "compensation_skill": "recover_pose",
        })

    def test_missing_contract_fails_closed_before_dispatch(self):
        backend = MockRobotBackend(ready_state())
        registry = SkillRegistry()
        registry.register(MissingContractSkill())
        report = SkillExecutor(registry, backend, max_retries=0).execute(
            TaskPlan("missing", [PlanStep("s1", "missing_contract", {})])
        )
        self.assertFalse(report.success)
        self.assertIn("MISSING_SAFETY_CONTRACT", report.message)
        self.assertNotIn("missing_contract", [name for name, _ in backend.command_log])

    def test_explicit_unknown_contract_is_distinct_and_fails_closed(self):
        backend = MockRobotBackend(ready_state())
        registry = SkillRegistry()
        registry.register(UnknownContractSkill())
        report = SkillExecutor(registry, backend, max_retries=0).execute(
            TaskPlan("unknown", [PlanStep("s1", "unknown_contract", {})])
        )
        self.assertFalse(report.success)
        self.assertIn("INCOMPLETE_SAFETY_CONTRACT", report.message)
        self.assertNotIn("MISSING_SAFETY_CONTRACT", report.message)
        self.assertNotIn("unknown_contract", [name for name, _ in backend.command_log])

    def test_planner_metadata_cannot_override_registry_contract(self):
        backend = MockRobotBackend(ready_state())
        registry = SkillRegistry()
        registry.register(MissingContractSkill())
        report = SkillExecutor(registry, backend, max_retries=0).execute(TaskPlan(
            "override attempt",
            [PlanStep("s1", "missing_contract", {})],
            metadata={"safety_contract": {"risk_class": "low"}},
        ))
        self.assertFalse(report.success)
        self.assertIn("MISSING_SAFETY_CONTRACT", report.message)
        self.assertNotIn("missing_contract", [name for name, _ in backend.command_log])

    def test_llm_schema_exposes_registry_contract_as_metadata(self):
        captured = {}

        def completion(_instruction, schema):
            captured["schema"] = schema
            return json.dumps({
                "goal": "head",
                "steps": [{"id": "s1", "skill": "set_head",
                           "arguments": {"yaw_deg": 5}}],
            })

        adapter = LLMPlannerAdapter(completion, build_default_registry())
        adapter.plan("turn head")
        head = next(item for item in captured["schema"] if item["name"] == "set_head")
        self.assertEqual(head["safety_contract"]["risk_class"], "low")
        self.assertTrue(head["safety_contract"]["risk_class_is_provisional"])


if __name__ == "__main__":
    unittest.main()
