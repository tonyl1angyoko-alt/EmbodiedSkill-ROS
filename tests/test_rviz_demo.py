import json
import unittest

from embodied_skill_ros.backends.mock_backend import FaultEvent, MockRobotBackend
from embodied_skill_ros.models.robot_state import RobotState
from embodied_skill_ros.visualization.rviz_demo_bridge import (
    EXTENDED_ARM_POSE,
    RETRACTED_ARM_POSE,
    VisualStateInterpolator,
    VisualTargets,
    arm_pose_for_state,
    base_x_for_state,
    parse_state_message,
)
from embodied_skill_ros.visualization.rviz_demo_runner import (
    FALSE_SUCCESS,
    REPAIR,
    demo_definition,
    execute_demo_core,
)


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


class RvizStateProjectionTests(unittest.TestCase):
    def test_ros_state_parsing(self):
        payload = json.dumps({
            "sequence": 7,
            "state": {"left_arm_safe": False, "agv_position_m": 1.25},
        })
        self.assertEqual(parse_state_message(payload), VisualTargets(False, 1.25, 7))

    def test_unsafe_arm_maps_to_extended_pose(self):
        self.assertEqual(arm_pose_for_state(False), EXTENDED_ARM_POSE)

    def test_safe_arm_maps_to_retracted_pose(self):
        self.assertEqual(arm_pose_for_state(True), RETRACTED_ARM_POSE)

    def test_agv_position_maps_to_tf_x(self):
        self.assertEqual(base_x_for_state(1.75), 1.75)

    def test_malformed_state_is_ignored(self):
        for payload in ("not json", "{}", '{"state": []}', '{"state": null}'):
            self.assertIsNone(parse_state_message(payload))

    def test_unknown_fields_are_not_fabricated(self):
        parsed = parse_state_message(json.dumps({"state": {
            "left_arm_safe": None,
            "agv_position_m": "unknown",
        }}))
        self.assertEqual(parsed, VisualTargets(None, None, None))

    def test_visual_interpolation_does_not_mutate_authoritative_state(self):
        authoritative = VisualTargets(False, 0.0, 1)
        interpolator = VisualStateInterpolator()
        interpolator.accept(authoritative)
        interpolator.accept(VisualTargets(True, 1.0, 2))
        before = (authoritative.left_arm_safe, authoritative.agv_position_m)
        (shoulder, elbow), base_x = interpolator.step(0.1)
        self.assertEqual(before, (False, 0.0))
        self.assertNotEqual((shoulder, elbow), RETRACTED_ARM_POSE)
        self.assertGreater(base_x, 0.0)
        self.assertLess(base_x, 1.0)


class RvizDemoDecisionTests(unittest.TestCase):
    def test_repair_case_uses_real_plan_repairer(self):
        backend = MockRobotBackend(ready_state(left_arm_safe=False))
        report = execute_demo_core(backend, demo_definition(REPAIR))
        self.assertTrue(report.success)
        self.assertEqual(report.decision, "REPAIR")
        self.assertEqual(
            [step.skill for step in report.plan.steps],
            ["retract_arm", "move_agv"],
        )
        self.assertTrue(report.plan.steps[0].inserted_by.startswith("PlanRepairer:"))
        self.assertEqual(
            [name for name, _arguments in backend.command_log],
            ["retract_arm", "move_agv"],
        )

    def test_false_success_case_stops_after_verification(self):
        backend = MockRobotBackend(ready_state())
        backend.inject("move_agv", FaultEvent("physical_failure", "accepted, no motion"))
        report = execute_demo_core(backend, demo_definition(FALSE_SUCCESS))
        self.assertFalse(report.success)
        self.assertEqual(report.decision, "STOP")
        self.assertTrue(report.results[0].command_accepted)
        self.assertFalse(report.results[0].physical_outcome_achieved)
        self.assertEqual(backend.oracle_state().agv_position_m, 0.0)


if __name__ == "__main__":
    unittest.main()
