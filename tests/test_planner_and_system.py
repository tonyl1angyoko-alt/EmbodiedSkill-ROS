import unittest

from embodied_skill_ros import build_mock_system
from embodied_skill_ros.backends.mock_backend import FaultEvent
from embodied_skill_ros.planner.structured_planner import StructuredPlanner

from test_models_and_registry import ready_state


class PlannerAndSystemTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
