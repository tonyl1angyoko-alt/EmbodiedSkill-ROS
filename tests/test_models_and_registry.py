import json
import unittest

from embodied_skill_ros.grounding.plan_grounder import EmbodiedPlanGrounder
from embodied_skill_ros.models.robot_state import RobotState
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan
from embodied_skill_ros.planner.llm_adapter import LLMPlannerAdapter
from embodied_skill_ros.skills.agv_skills import MoveAgvSkill
from embodied_skill_ros.skills.base_skill import ParameterError
from embodied_skill_ros.skills.registry import SkillRegistry, build_default_registry


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


class ModelsAndRegistryTests(unittest.TestCase):
    def test_default_skills_register(self):
        self.assertEqual(
            build_default_registry().names(),
            {"retract_arm", "extend_arm", "move_agv", "set_lift", "set_head"},
        )

    def test_duplicate_skill_registration_fails(self):
        registry = SkillRegistry()
        registry.register(MoveAgvSkill())
        with self.assertRaisesRegex(ValueError, "duplicate"):
            registry.register(MoveAgvSkill())

    def test_unknown_skill_lookup_fails(self):
        with self.assertRaisesRegex(KeyError, "unknown skill"):
            build_default_registry().get("teleport")

    def test_missing_parameter_fails(self):
        with self.assertRaisesRegex(ParameterError, "missing parameter"):
            MoveAgvSkill().validate_arguments({})

    def test_wrong_parameter_type_fails(self):
        with self.assertRaisesRegex(ParameterError, "wrong type"):
            MoveAgvSkill().validate_arguments({"distance_m": "one"})

    def test_boolean_is_not_a_number(self):
        with self.assertRaisesRegex(ParameterError, "wrong type"):
            MoveAgvSkill().validate_arguments({"distance_m": True})

    def test_out_of_range_parameter_fails(self):
        with self.assertRaisesRegex(ParameterError, "above maximum"):
            MoveAgvSkill().validate_arguments({"distance_m": 8.0})

    def test_unknown_parameter_fails(self):
        with self.assertRaisesRegex(ParameterError, "unknown parameters"):
            MoveAgvSkill().validate_arguments({"distance_m": 1.0, "magic": 1})

    def test_task_plan_round_trip(self):
        source = {
            "goal": "move",
            "plan_id": "p7",
            "steps": [{"id": "s1", "skill": "move_agv", "arguments": {"distance_m": 1.0}}],
        }
        self.assertEqual(TaskPlan.from_dict(source).to_dict()["plan_id"], "p7")

    def test_invalid_plan_step_arguments_shape(self):
        with self.assertRaisesRegex(TypeError, "arguments"):
            PlanStep.from_dict({"id": "s1", "skill": "move_agv", "arguments": []})

    def test_duplicate_step_ids_are_nonrepairable(self):
        plan = TaskPlan("bad", [
            PlanStep("s", "set_head", {"yaw_deg": 5}),
            PlanStep("s", "set_head", {"yaw_deg": 10}),
        ])
        report = EmbodiedPlanGrounder(build_default_registry()).ground(plan, ready_state())
        self.assertTrue(report.requires_stop)
        self.assertIn("DUPLICATE_STEP_ID", {issue.code for issue in report.issues})

    def test_llm_adapter_rejects_unregistered_skill(self):
        payload = json.dumps({
            "goal": "bad",
            "steps": [{"id": "s1", "skill": "teleport", "arguments": {}}],
        })
        adapter = LLMPlannerAdapter(lambda _prompt, _skills: payload, build_default_registry())
        with self.assertRaisesRegex(ValueError, "unregistered"):
            adapter.plan("bad")


if __name__ == "__main__":
    unittest.main()
