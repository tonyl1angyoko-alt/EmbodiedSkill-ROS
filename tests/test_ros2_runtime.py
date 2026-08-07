import importlib.util
import os
import unittest

try:
    import pytest
except ImportError:  # unittest remains the dependency-free runner on macOS.
    pytest = None
else:
    pytestmark = pytest.mark.ros2


ROS2_AVAILABLE = (
    importlib.util.find_spec("rclpy") is not None
    and os.environ.get("ROS_DISTRO") == "humble"
)
SKIP_REASON = "ROS2 Humble runtime unavailable on current host"


@unittest.skipUnless(ROS2_AVAILABLE, SKIP_REASON)
class Ros2RuntimeTests(unittest.TestCase):
    def test_humble_runtime_and_rclpy_context(self):
        import rclpy

        self.assertEqual(os.environ.get("ROS_DISTRO"), "humble")
        rclpy.init(args=None)
        try:
            node = rclpy.create_node("embodied_skill_ros_validation")
            self.assertEqual(node.get_name(), "embodied_skill_ros_validation")
            node.destroy_node()
        finally:
            rclpy.shutdown()

    def test_mock_bridge_node_constructs(self):
        import rclpy
        from embodied_skill_ros.ros2.mock_bridge_node import build_node

        rclpy.init(args=None)
        try:
            node = build_node()
            self.assertEqual(node.get_name(), "embodied_skill_mock_bridge")
            node.destroy_node()
        finally:
            rclpy.shutdown()


if __name__ == "__main__":
    unittest.main()
