import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

try:
    import pytest
except ImportError:
    pytest = None
else:
    pytestmark = pytest.mark.ros2


ROS2_AVAILABLE = (
    importlib.util.find_spec("rclpy") is not None
    and importlib.util.find_spec("action_tutorials_interfaces") is not None
    and os.environ.get("ROS_DISTRO") == "humble"
)
SKIP_REASON = "ROS2 Humble action runtime unavailable on current host"


@unittest.skipUnless(ROS2_AVAILABLE, SKIP_REASON)
class Ros2FakeRobotRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from embodied_skill_ros.ros2.runtime_validation import run_validation

        cls.output = Path(tempfile.mkdtemp(prefix="embodied_skill_ros2_test.")) / "evidence.json"
        cls.evidence = run_validation(cls.output)

    def test_all_required_process_separated_scenarios(self):
        summary = self.evidence["summary"]
        self.assertEqual(summary["required_total"], 15)
        self.assertEqual(summary["required_passed"], 15)
        self.assertTrue(summary["all_required_passed"])
        self.assertEqual(self.evidence["fake_robot"]["shutdown_returncode"], 0)

    def test_transport_success_is_not_physical_success(self):
        scenario = next(
            item for item in self.evidence["required_scenarios"]
            if item["id"] == "R3_accepted_no_motion"
        )
        self.assertTrue(scenario["checks"]["ros_goal_accepted"])
        self.assertTrue(scenario["checks"]["ros_action_succeeded"])
        self.assertTrue(scenario["checks"]["verifier_rejected"])
        self.assertFalse(scenario["scores"]["task_completion"])
        self.assertTrue(scenario["scores"]["correct_safe_handling"])

    def test_repair_replan_timeout_and_cancel_are_distinct(self):
        scenarios = {
            item["id"]: item for item in self.evidence["required_scenarios"]
        }
        self.assertEqual(
            [step["skill"] for step in scenarios["R10_generic_repair"]["final_plan"]["steps"]],
            ["retract_arm", "move_agv"],
        )
        self.assertEqual(
            [step["skill"] for step in scenarios["R11_genuine_replan"]["final_plan"]["steps"]],
            ["alternate_route"],
        )
        self.assertTrue(scenarios["R13_timeout"]["checks"]["timeout_recorded"])
        self.assertTrue(scenarios["R14_cancellation"]["checks"]["ros_terminal_canceled"])

    def test_known_runtime_limitations_remain_visible(self):
        limitations = {item["id"]: item for item in self.evidence["limitations"]}
        self.assertTrue(self.evidence["summary"]["all_limitations_reproduced"])
        self.assertTrue(
            limitations["L1_toctou_after_fresh_observation"]["unsafe_execution"]
        )
        self.assertTrue(limitations["L2_fresh_sensor_spoof"]["unsafe_execution"])


if __name__ == "__main__":
    unittest.main()
