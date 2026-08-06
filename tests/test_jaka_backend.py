import unittest

from embodied_skill_ros.backends.jaka_backend import JakaRobotBackend
from embodied_skill_ros.models.robot_state import RobotState
from embodied_skill_ros.skills.registry import build_registry_for_backend


class FakeAgv:
    def __init__(self, drive_result=None):
        self.drive_result = drive_result
        self.calls = []

    def drive_distance(self, *arguments):
        self.calls.append(arguments)
        return self.drive_result


class FakeArm:
    def __init__(self):
        self.preset_calls = []

    def go_preset(self, name):
        self.preset_calls.append(name)
        return True


class FakeLift:
    def lift_to(self, _height):
        return True


class FakeHead:
    def yaw_to(self, _yaw):
        return True

    def pitch_to(self, _pitch):
        return True


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
        expected = RobotState(
            agv_ready=True,
            emergency_stop=False,
            timestamp="2026-01-02T03:04:05+00:00",
        )
        observed = JakaRobotBackend(state_provider=lambda: expected).observe()
        self.assertTrue(observed.agv_ready)
        self.assertFalse(observed.emergency_stop)
        self.assertEqual(observed.timestamp, expected.timestamp)

    def test_single_arm_retract_is_not_advertised_or_executed(self):
        arm = FakeArm()
        backend = JakaRobotBackend(arm_skill=arm, transport_pose_name="dual_arm_transport")
        receipt = backend.command(
            "retract_arm", {"arm": "right"}
        )
        self.assertFalse(receipt.accepted)
        self.assertIn("single-arm", receipt.backend_message)
        self.assertEqual(arm.preset_calls, [])
        self.assertNotIn("retract_arm", backend.supported_skills)

    def test_registry_is_filtered_by_jaka_capabilities(self):
        backend = JakaRobotBackend(
            agv_skill=FakeAgv(), lift_skill=FakeLift(), head_skill=FakeHead()
        )
        registry = build_registry_for_backend(backend)
        self.assertTrue(registry.names() <= backend.supported_skills)
        self.assertNotIn("extend_arm", registry.names())
        self.assertNotIn("retract_arm", registry.names())
        self.assertEqual(registry.names(), {"move_agv", "set_lift", "set_head"})

    def test_agv_false_result_is_rejected(self):
        receipt = JakaRobotBackend(agv_skill=FakeAgv(False)).command(
            "move_agv", {"distance_m": 1.0}
        )
        self.assertFalse(receipt.accepted)
        self.assertIs(receipt.call_result, False)

    def test_fire_and_forget_agv_only_reports_submitted(self):
        receipt = JakaRobotBackend(agv_skill=FakeAgv(None)).command(
            "move_agv", {"distance_m": 1.0}
        )
        self.assertTrue(receipt.accepted)
        self.assertIn("submitted", receipt.backend_message)
        self.assertIn("physical outcome not verified", receipt.backend_message)

    def test_safe_stop_without_verified_global_stop_is_rejected(self):
        agv = FakeAgv()
        receipt = JakaRobotBackend(agv_skill=agv).stop()
        self.assertFalse(receipt.accepted)
        self.assertIn("global stop", receipt.backend_message)
        self.assertEqual(agv.calls, [])

    def test_injected_verified_global_stop_success_is_accepted(self):
        calls = []
        backend = JakaRobotBackend(stop_all_fn=lambda: calls.append("stop") or True)
        receipt = backend.stop()
        self.assertTrue(receipt.accepted)
        self.assertEqual(calls, ["stop"])

    def test_injected_verified_global_stop_false_is_rejected(self):
        receipt = JakaRobotBackend(stop_all_fn=lambda: False).stop()
        self.assertFalse(receipt.accepted)
        self.assertIn("failed", receipt.backend_message)

    def test_injected_verified_global_stop_exception_is_rejected(self):
        def fail():
            raise RuntimeError("stop transport failed")

        receipt = JakaRobotBackend(stop_all_fn=fail).stop()
        self.assertFalse(receipt.accepted)
        self.assertIn("stop transport failed", receipt.backend_message)


if __name__ == "__main__":
    unittest.main()
