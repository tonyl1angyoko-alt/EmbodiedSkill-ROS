from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any


EXTENDED_ARM_POSE = (0.20, 0.20)
RETRACTED_ARM_POSE = (-1.10, 1.80)


@dataclass(frozen=True)
class VisualTargets:
    """Read-only projection of authoritative state used by the display layer."""

    left_arm_safe: bool | None
    agv_position_m: float | None
    sequence: int | None = None


def parse_state_message(message_data: str) -> VisualTargets | None:
    """Parse the fake robot state topic without inventing unavailable values."""

    try:
        payload = json.loads(message_data)
        state = payload["state"]
        if not isinstance(state, dict):
            return None
        arm_value = state.get("left_arm_safe")
        left_arm_safe = arm_value if isinstance(arm_value, bool) else None
        position_value = state.get("agv_position_m")
        if isinstance(position_value, bool) or not isinstance(position_value, (int, float)):
            agv_position_m = None
        else:
            agv_position_m = float(position_value)
            if not math.isfinite(agv_position_m):
                agv_position_m = None
        sequence_value = payload.get("sequence")
        sequence = sequence_value if isinstance(sequence_value, int) else None
        return VisualTargets(left_arm_safe, agv_position_m, sequence)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def arm_pose_for_state(left_arm_safe: bool) -> tuple[float, float]:
    return RETRACTED_ARM_POSE if left_arm_safe else EXTENDED_ARM_POSE


def base_x_for_state(agv_position_m: float) -> float:
    return float(agv_position_m)


def _approach(current: float, target: float, maximum_delta: float) -> float:
    if maximum_delta <= 0.0:
        return current
    difference = target - current
    if abs(difference) <= maximum_delta:
        return target
    return current + math.copysign(maximum_delta, difference)


class VisualStateInterpolator:
    """Smooth display state that is deliberately isolated from execution state."""

    def __init__(
        self,
        *,
        arm_speed_rad_s: float = 1.35,
        base_speed_m_s: float = 0.50,
    ) -> None:
        if arm_speed_rad_s <= 0.0 or base_speed_m_s <= 0.0:
            raise ValueError("visual interpolation speeds must be positive")
        self.arm_speed_rad_s = arm_speed_rad_s
        self.base_speed_m_s = base_speed_m_s
        self.shoulder = RETRACTED_ARM_POSE[0]
        self.elbow = RETRACTED_ARM_POSE[1]
        self.base_x = 0.0
        self.target_shoulder = self.shoulder
        self.target_elbow = self.elbow
        self.target_base_x = self.base_x
        self.initialized = False
        self.last_sequence: int | None = None

    def accept(self, targets: VisualTargets) -> None:
        """Set display targets; never mutates or returns authoritative state."""

        if targets.left_arm_safe is not None:
            self.target_shoulder, self.target_elbow = arm_pose_for_state(
                targets.left_arm_safe
            )
        if targets.agv_position_m is not None:
            self.target_base_x = base_x_for_state(targets.agv_position_m)
        self.last_sequence = targets.sequence
        if not self.initialized:
            self.shoulder = self.target_shoulder
            self.elbow = self.target_elbow
            self.base_x = self.target_base_x
            self.initialized = True

    def step(self, delta_s: float) -> tuple[tuple[float, float], float]:
        if delta_s < 0.0:
            raise ValueError("delta_s must be non-negative")
        arm_delta = self.arm_speed_rad_s * delta_s
        base_delta = self.base_speed_m_s * delta_s
        self.shoulder = _approach(self.shoulder, self.target_shoulder, arm_delta)
        self.elbow = _approach(self.elbow, self.target_elbow, arm_delta)
        self.base_x = _approach(self.base_x, self.target_base_x, base_delta)
        return (self.shoulder, self.elbow), self.base_x


def build_node() -> Any:
    import rclpy
    from geometry_msgs.msg import TransformStamped
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import JointState
    from std_msgs.msg import String
    from tf2_ros import TransformBroadcaster

    class RvizDemoBridge(Node):
        def __init__(self) -> None:
            super().__init__("embodied_skill_rviz_demo_bridge")
            self._interpolator = VisualStateInterpolator()
            qos = QoSProfile(
                depth=20,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
            )
            self._subscription = self.create_subscription(
                String, "/embodied_skill/state", self._state_received, qos
            )
            self._joint_publisher = self.create_publisher(JointState, "/joint_states", 10)
            self._tf_broadcaster = TransformBroadcaster(self)
            self._timer = self.create_timer(1.0 / 25.0, self._publish_visual_state)
            self._last_tick_ns = self.get_clock().now().nanoseconds
            self._warned_about_invalid_state = False

        def _state_received(self, message: Any) -> None:
            targets = parse_state_message(message.data)
            if targets is None:
                if not self._warned_about_invalid_state:
                    self.get_logger().warning(
                        "ignoring malformed /embodied_skill/state observation"
                    )
                    self._warned_about_invalid_state = True
                return
            self._warned_about_invalid_state = False
            self._interpolator.accept(targets)

        def _publish_visual_state(self) -> None:
            now = self.get_clock().now()
            delta_s = max(0.0, (now.nanoseconds - self._last_tick_ns) / 1_000_000_000.0)
            self._last_tick_ns = now.nanoseconds
            if not self._interpolator.initialized:
                return
            (shoulder, elbow), base_x = self._interpolator.step(min(delta_s, 0.2))

            joints = JointState()
            joints.header.stamp = now.to_msg()
            joints.name = ["shoulder_joint", "elbow_joint"]
            joints.position = [shoulder, elbow]
            self._joint_publisher.publish(joints)

            transform = TransformStamped()
            transform.header.stamp = now.to_msg()
            transform.header.frame_id = "map"
            transform.child_frame_id = "base_link"
            transform.transform.translation.x = base_x
            transform.transform.rotation.w = 1.0
            self._tf_broadcaster.sendTransform(transform)

    return RvizDemoBridge()


def main(args: list[str] | None = None) -> None:
    import rclpy

    rclpy.init(args=args)
    node = build_node()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
