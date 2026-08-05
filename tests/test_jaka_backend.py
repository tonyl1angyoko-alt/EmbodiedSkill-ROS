import unittest

from embodied_skill_ros.backends.jaka_backend import JakaRobotBackend
from embodied_skill_ros.models.robot_state import RobotState


class JakaBackendTests(unittest.TestCase):
    def test_import_and_empty_observation_do_not_require_ros2(self):
        state = JakaRobotBackend().observe()
        self.assertFalse(state.left_arm_ready)
        self.assertIsNone(state.emergency_stop)

    def test_presence_of_adapter_is_not_assumed_ready(self):
        state = JakaRobotBackend(agv_skill=object()).observe()
        self.assertIsNone(state.agv_ready)
        self.assertIsNone(state.agv_position_m)

    def test_explicit_state_provider_is_authoritative(self):
        expected = RobotState(agv_ready=True, emergency_stop=False)
        observed = JakaRobotBackend(state_provider=lambda: expected).observe()
        self.assertTrue(observed.agv_ready)
        self.assertFalse(observed.emergency_stop)

    def test_unconfigured_transport_pose_is_unknown(self):
        receipt = JakaRobotBackend(arm_skill=object()).command(
            "retract_arm", {"arm": "right"}
        )
        self.assertFalse(receipt.accepted)
        self.assertIn("UNKNOWN", receipt.backend_message)


if __name__ == "__main__":
    unittest.main()
