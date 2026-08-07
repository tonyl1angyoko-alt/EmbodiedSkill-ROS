from __future__ import annotations

import json
from typing import Any

from ..backends.mock_backend import MockRobotBackend


def build_node() -> Any:
    """Construct the validation node; ROS imports stay behind this call."""

    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
    from std_srvs.srv import Trigger

    class MockBridgeNode(Node):
        def __init__(self) -> None:
            super().__init__("embodied_skill_mock_bridge")
            self.backend = MockRobotBackend()
            self.publisher = self.create_publisher(String, "embodied_skill/state", 10)
            self.service = self.create_service(
                Trigger, "embodied_skill/get_capabilities", self._capabilities
            )
            self.timer = self.create_timer(0.5, self._publish_state)

        def _publish_state(self) -> None:
            message = String()
            message.data = json.dumps(self.backend.observe().to_dict(), sort_keys=True)
            self.publisher.publish(message)

        def _capabilities(self, _request: Any, response: Any) -> Any:
            capabilities = self.backend.capabilities()
            response.success = True
            response.message = json.dumps({
                "backend": capabilities.backend_name,
                "runtime": capabilities.runtime,
                "skills": sorted(capabilities.supported_skills or ()),
                "observable_fields": sorted(capabilities.observable_fields or ()),
                "supports_safe_stop": capabilities.supports_safe_stop,
            }, sort_keys=True)
            return response

    return MockBridgeNode()


def main(args: list[str] | None = None) -> None:
    import rclpy

    rclpy.init(args=args)
    node = build_node()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
