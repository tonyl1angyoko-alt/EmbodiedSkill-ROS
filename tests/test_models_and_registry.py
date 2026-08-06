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

    def test_all_numeric_parameters_reject_non_finite_values(self):
        registry = build_default_registry()
        cases = (
            ("move_agv", "distance_m", {"distance_m": 1.0}),
            ("move_agv", "speed_mps", {"distance_m": 1.0, "speed_mps": 0.2}),
            ("set_lift", "height_mm", {"height_mm": 100.0}),
            ("set_head", "yaw_deg", {"yaw_deg": 0.0}),
            ("set_head", "pitch_deg", {"pitch_deg": 0.0}),
        )
        for skill_name, parameter, valid_arguments in cases:
            for value in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(skill=skill_name, parameter=parameter, value=value):
                    arguments = dict(valid_arguments)
                    arguments[parameter] = value
                    with self.assertRaisesRegex(ParameterError, "finite"):
                        registry.get(skill_name).validate_arguments(arguments)

    def test_normal_numeric_boundary_values_are_valid(self):
        registry = build_default_registry()
        valid = (
            ("move_agv", {"distance_m": -5.0, "speed_mps": 0.01}),
            ("move_agv", {"distance_m": 5.0, "speed_mps": 0.5}),
            ("set_lift", {"height_mm": 0.0}),
            ("set_lift", {"height_mm": 780.0}),
            ("set_head", {"yaw_deg": -90.0, "pitch_deg": -45.0}),
            ("set_head", {"yaw_deg": 90.0, "pitch_deg": 20.0}),
        )
        for skill_name, arguments in valid:
            with self.subTest(skill=skill_name, arguments=arguments):
                registry.get(skill_name).validate_arguments(arguments)

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

    def test_llm_adapter_rejects_non_finite_json_constants(self):
        registry = build_default_registry()
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):
                payload = (
                    '{"goal":"bad","steps":[{"id":"s1","skill":"set_head",'
                    f'"arguments":{{"yaw_deg":{constant}}}}}]}}'
                )
                adapter = LLMPlannerAdapter(lambda _prompt, _skills: payload, registry)
                with self.assertRaisesRegex(ValueError, "non-finite"):
                    adapter.plan("bad")


if __name__ == "__main__":
    unittest.main()
