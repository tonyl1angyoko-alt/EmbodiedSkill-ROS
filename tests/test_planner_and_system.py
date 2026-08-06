import json
import unittest

from embodied_skill_ros import build_mock_system
from embodied_skill_ros.backends.mock_backend import FaultEvent, MockRobotBackend
from embodied_skill_ros.execution.skill_executor import SkillExecutor
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan
from embodied_skill_ros.planner import LLMPlannerAdapter, Planner
from embodied_skill_ros.planner.structured_planner import StructuredPlanner
from embodied_skill_ros.skills.registry import build_default_registry
from embodied_skill_ros.system import EmbodiedSkillSystem

from test_models_and_registry import ready_state


class PlannerAndSystemTests(unittest.TestCase):
    def make_llm_system(self, completion_fn):
        backend = MockRobotBackend(ready_state())
        registry = build_default_registry()
        planner = LLMPlannerAdapter(completion_fn, registry)
        return EmbodiedSkillSystem(
            backend,
            registry,
            planner,
            SkillExecutor(registry, backend, max_retries=0, max_replans=0),
        )

    def test_normal_multistep_instruction(self):
        system = build_mock_system(ready_state())
        report = system.run_instruction("收回右臂，移动到工作台旁，然后升高升降轴。")
        self.assertTrue(report.success)
        self.assertEqual([s.skill for s in report.plan.steps],
                         ["retract_arm", "move_agv", "set_lift"])

    def test_same_instruction_safe_state_needs_no_repair(self):
        system = build_mock_system(ready_state())
        report = system.run_instruction("移动到工作台。")
        self.assertEqual([s.skill for s in report.plan.steps], ["move_agv"])
        self.assertEqual(report.decision, "EXECUTE")

    def test_same_instruction_unsafe_state_changes_plan(self):
        system = build_mock_system(ready_state(right_arm_safe=False))
        report = system.run_instruction("移动到工作台。")
        self.assertEqual([s.skill for s in report.plan.steps], ["retract_arm", "move_agv"])
        self.assertEqual(report.decision, "REPAIR")

    def test_head_instruction(self):
        system = build_mock_system(ready_state())
        report = system.run_instruction("请抬头")
        self.assertTrue(report.success)
        self.assertEqual(system.backend.observe().head_pitch_deg, 10.0)

    def test_unsupported_instruction_is_explicit(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            StructuredPlanner().plan("唱一首歌", ready_state())

    def test_default_system_recovers_from_one_fault(self):
        system = build_mock_system(ready_state(), max_retries=1)
        system.backend.inject("move_agv", FaultEvent("physical_failure"))
        report = system.run_instruction("移动到工作台。")
        self.assertTrue(report.success)
        self.assertEqual(len(report.results), 2)

    def test_default_replanner_matches_completed_step_with_optional_defaults(self):
        system = build_mock_system(ready_state(), max_retries=0, max_replans=1)
        system.backend.inject("set_head", FaultEvent("physical_failure"))
        report = system.run_plan(TaskPlan("move then look up", [
            PlanStep("move", "move_agv", {"distance_m": 1.0}),
            PlanStep("head", "set_head", {"pitch_deg": 10.0}),
        ]))
        self.assertTrue(report.success)
        self.assertEqual(system.backend.observe().agv_position_m, 1.0)
        self.assertEqual(
            [name for name, _arguments in system.backend.command_log].count("move_agv"), 1
        )

    def test_default_replanner_does_not_conflate_distinct_optional_arguments(self):
        system = build_mock_system(ready_state(), max_retries=0, max_replans=1)
        system.backend.inject("set_lift", FaultEvent("physical_failure"))
        report = system.run_plan(TaskPlan("lift then look up", [
            PlanStep("yaw", "set_head", {"yaw_deg": 5.0}),
            PlanStep("lift", "set_lift", {"height_mm": 300.0}),
        ]))
        self.assertTrue(report.success)
        self.assertEqual(system.backend.observe().head_yaw_deg, 5.0)
        self.assertEqual(system.backend.observe().head_pitch_deg, 10.0)

    def test_llm_adapter_runs_directly_in_embodied_system(self):
        payload = json.dumps({
            "goal": "head",
            "steps": [{"id": "s1", "skill": "set_head", "arguments": {"yaw_deg": 5}}],
        })
        system = self.make_llm_system(lambda _instruction, _schema: payload)
        report = system.run_instruction("turn head")
        self.assertTrue(report.success)
        self.assertEqual(system.backend.observe().head_yaw_deg, 5.0)

    def test_planners_share_state_aware_protocol(self):
        payload = json.dumps({
            "goal": "head",
            "steps": [{"id": "s1", "skill": "set_head", "arguments": {"yaw_deg": 5}}],
        })
        adapter = LLMPlannerAdapter(lambda _instruction, _schema: payload,
                                    build_default_registry())
        self.assertIsInstance(StructuredPlanner(), Planner)
        self.assertIsInstance(adapter, Planner)
        self.assertTrue(StructuredPlanner().plan("请抬头", ready_state()).steps)
        self.assertTrue(adapter.plan("turn head", ready_state()).steps)

    def test_llm_provider_receives_state_and_complete_skill_schema(self):
        captured = {}

        def completion(instruction, state, schema):
            captured.update(instruction=instruction, state=state, schema=schema)
            return json.dumps({
                "goal": "head",
                "steps": [
                    {"id": "s1", "skill": "set_head", "arguments": {"yaw_deg": 5}}
                ],
            })

        system = self.make_llm_system(completion)
        report = system.run_instruction("turn head")
        self.assertTrue(report.success)
        self.assertFalse(captured["state"]["emergency_stop"])
        move_schema = next(item for item in captured["schema"] if item["name"] == "move_agv")
        self.assertEqual(move_schema["parameters"]["distance_m"]["minimum"], -5.0)
        self.assertEqual(move_schema["parameters"]["distance_m"]["maximum"], 5.0)
        self.assertEqual(move_schema["parameters"]["distance_m"]["type"], "number")

    def test_invalid_llm_outputs_never_reach_backend(self):
        payloads = (
            '{"goal":"bad","steps":[{"id":"s1","skill":"unknown",'
            '"arguments":{}}]}',
            '{"goal":"bad","steps":[]}',
            '{"goal":"bad","steps":[{"id":"s1","skill":"set_head",'
            '"arguments":{"yaw_deg":NaN}}]}',
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                def completion(_instruction, _schema):
                    return payload

                system = self.make_llm_system(completion)
                with self.assertRaises(ValueError):
                    system.run_instruction("bad")
                self.assertEqual(system.backend.command_log, [])


if __name__ == "__main__":
    unittest.main()
