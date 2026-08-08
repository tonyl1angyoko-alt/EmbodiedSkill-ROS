from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .rviz_demo_bridge import VisualStateInterpolator, VisualTargets, parse_state_message


REPAIR = "repair"
FALSE_SUCCESS = "false_success"
LANES = ("baseline", "embodied")
LANE_Y = {"baseline": 0.90, "embodied": -0.90}
LANE_PREFIX = {"baseline": "baseline_", "embodied": "embodied_"}


@dataclass
class LaneSignals:
    current_skill: str | None = None
    action_started: bool = False
    action_succeeded: bool = False
    physical_transition: bool | None = None
    safe_stop_received: bool = False


def parse_runtime_event(message_data: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(message_data)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def update_lane_signals(signals: LaneSignals, event: dict[str, Any]) -> None:
    name = event.get("event")
    skill = event.get("skill")
    if isinstance(skill, str):
        signals.current_skill = skill
    if name == "action_execution_started":
        signals.action_started = True
        signals.action_succeeded = False
        signals.physical_transition = None
    elif name == "physical_transition":
        applied = event.get("applied")
        signals.physical_transition = applied if isinstance(applied, bool) else None
    elif name == "action_succeeded":
        signals.action_succeeded = True
        applied = event.get("physical_transition")
        if isinstance(applied, bool):
            signals.physical_transition = applied
    elif name == "safe_stop_received":
        signals.safe_stop_received = True


def _fmt_position(targets: VisualTargets | None) -> str:
    if targets is None or targets.agv_position_m is None:
        return "?"
    return f"{targets.agv_position_m:.2f} m"


def panel_text(
    case: str,
    lane: str,
    targets: VisualTargets | None,
    signals: LaneSignals,
) -> str:
    arm_safe = targets.left_arm_safe if targets else None
    position = targets.agv_position_m if targets else None

    if case == REPAIR and lane == "baseline":
        if position is not None and position >= 0.99:
            return (
                "POLICY: DIRECT EXECUTION\n"
                "move_agv(1.0 m)\n\n"
                "TASK REACHED x = 1.0\n"
                "ARM_SAFE = FALSE\n"
                "PRECONDITION IGNORED"
            )
        if signals.action_started:
            return (
                "POLICY: DIRECT EXECUTION\n"
                "move_agv(1.0 m)\n\n"
                "EXECUTE IMMEDIATELY\n"
                "ARM STILL EXTENDED\n"
                "NO GROUND / REPAIR"
            )
        return (
            "INPUT: move_agv(1.0 m)\n"
            "STATE: ARM_SAFE = FALSE\n\n"
            "POLICY\n"
            "TRUST PLAN AND EXECUTE"
        )

    if case == REPAIR and lane == "embodied":
        if position is not None and position >= 0.99:
            return (
                "GROUND -> REPAIR -> VERIFY\n\n"
                "retract_arm: VERIFIED\n"
                "move_agv: VERIFIED\n"
                "FINAL: SUCCESS"
            )
        if signals.current_skill == "move_agv":
            return (
                "REPAIR VERIFIED\n"
                "ARM_SAFE = TRUE\n\n"
                "RESUME ORIGINAL PLAN\n"
                "EXECUTE move_agv"
            )
        if arm_safe is True:
            return (
                "REPAIR: retract_arm(left)\n\n"
                "OBSERVE ARM_SAFE = TRUE\n"
                "VERIFY: PASS\n"
                "RESUME ORIGINAL PLAN"
            )
        if signals.current_skill == "retract_arm":
            return (
                "GROUND: PRECONDITION FAILED\n"
                "ARM_SAFE = FALSE\n\n"
                "DECISION: REPAIR\n"
                "EXECUTE retract_arm(left)"
            )
        return (
            "INPUT: move_agv(1.0 m)\n"
            "GROUND: ARM_SAFE = FALSE\n\n"
            "PRECONDITION FAILED\n"
            "DECISION: REPAIR"
        )

    if case == FALSE_SUCCESS and lane == "baseline":
        if signals.action_succeeded:
            return (
                "ROS ACTION: SUCCEEDED\n"
                f"VISUAL STATE: x = {_fmt_position(targets)}\n\n"
                "POLICY: TRUST MIDDLEWARE\n"
                "FINAL: SUCCESS\n"
                "(middleware-only)"
            )
        if signals.action_started:
            return (
                "POLICY: DIRECT EXECUTION\n"
                "move_agv(1.0 m)\n\n"
                "WAIT FOR ROS RESULT..."
            )
        return (
            "FAULT: COMMAND REPORTS SUCCESS\n"
            "BUT PHYSICAL STATE WILL NOT CHANGE\n\n"
            "POLICY: TRUST MIDDLEWARE"
        )

    if case == FALSE_SUCCESS and lane == "embodied":
        if signals.safe_stop_received:
            return (
                "ROS ACTION: SUCCEEDED\n"
                "OBSERVE x = 0.00 m\n\n"
                "VERIFY: FAILED\n"
                "EXPECTED x = 1.00 m\n"
                "FINAL: STOP"
            )
        if signals.action_succeeded:
            return (
                "ROS ACTION: SUCCEEDED\n"
                f"OBSERVE x = {_fmt_position(targets)}\n\n"
                "MIDDLEWARE != OUTCOME\n"
                "VERIFY PHYSICAL EFFECT..."
            )
        if signals.action_started:
            return (
                "EXECUTE move_agv(1.0 m)\n\n"
                "THEN OBSERVE\n"
                "THEN VERIFY"
            )
        return (
            "FAULT: COMMAND REPORTS SUCCESS\n"
            "BUT PHYSICAL STATE WILL NOT CHANGE\n\n"
            "POLICY: EXECUTE -> OBSERVE -> VERIFY"
        )

    return "WAITING FOR COMPARISON STATE"


def build_node() -> Any:
    import rclpy
    from geometry_msgs.msg import Point, TransformStamped
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import JointState
    from std_msgs.msg import String
    from tf2_ros import TransformBroadcaster
    from visualization_msgs.msg import Marker, MarkerArray

    class RvizComparisonBridge(Node):
        def __init__(self) -> None:
            super().__init__("embodied_skill_rviz_comparison_bridge")
            self.declare_parameter("comparison_case", REPAIR)
            self._case = str(self.get_parameter("comparison_case").value)
            if self._case not in {REPAIR, FALSE_SUCCESS}:
                raise ValueError(f"unknown comparison case: {self._case}")

            qos = QoSProfile(
                depth=50,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
            )
            self._interpolators = {
                lane: VisualStateInterpolator(arm_speed_rad_s=1.35, base_speed_m_s=0.50)
                for lane in LANES
            }
            self._targets: dict[str, VisualTargets | None] = {lane: None for lane in LANES}
            self._signals = {lane: LaneSignals() for lane in LANES}
            self._joint_publishers = {
                lane: self.create_publisher(
                    JointState, f"/comparison/{lane}/joint_states", 10
                )
                for lane in LANES
            }
            self._state_subscriptions = []
            self._event_subscriptions = []
            for lane in LANES:
                self._state_subscriptions.append(
                    self.create_subscription(
                        String,
                        f"/comparison/{lane}/state",
                        lambda message, lane=lane: self._state_received(lane, message),
                        qos,
                    )
                )
                self._event_subscriptions.append(
                    self.create_subscription(
                        String,
                        f"/comparison/{lane}/runtime_events",
                        lambda message, lane=lane: self._event_received(lane, message),
                        qos,
                    )
                )

            self._tf_broadcaster = TransformBroadcaster(self)
            self._marker_publisher = self.create_publisher(
                MarkerArray, "/embodied_skill/comparison_markers", 10
            )
            self._last_tick_ns = self.get_clock().now().nanoseconds
            self._timer = self.create_timer(1.0 / 25.0, self._publish_visual_state)
            self._marker_timer = self.create_timer(0.10, self._publish_markers)

        def _state_received(self, lane: str, message: Any) -> None:
            targets = parse_state_message(message.data)
            if targets is None:
                return
            self._targets[lane] = targets
            self._interpolators[lane].accept(targets)

        def _event_received(self, lane: str, message: Any) -> None:
            event = parse_runtime_event(message.data)
            if event is not None:
                update_lane_signals(self._signals[lane], event)

        def _publish_visual_state(self) -> None:
            now = self.get_clock().now()
            delta_s = max(
                0.0,
                (now.nanoseconds - self._last_tick_ns) / 1_000_000_000.0,
            )
            self._last_tick_ns = now.nanoseconds
            for lane in LANES:
                interpolator = self._interpolators[lane]
                if not interpolator.initialized:
                    continue
                (shoulder, elbow), base_x = interpolator.step(min(delta_s, 0.2))
                prefix = LANE_PREFIX[lane]

                joints = JointState()
                joints.header.stamp = now.to_msg()
                joints.name = [f"{prefix}shoulder_joint", f"{prefix}elbow_joint"]
                joints.position = [shoulder, elbow]
                self._joint_publishers[lane].publish(joints)

                transform = TransformStamped()
                transform.header.stamp = now.to_msg()
                transform.header.frame_id = "map"
                transform.child_frame_id = f"{prefix}base_link"
                transform.transform.translation.x = base_x
                transform.transform.translation.y = LANE_Y[lane]
                transform.transform.rotation.w = 1.0
                self._tf_broadcaster.sendTransform(transform)

        @staticmethod
        def _text_marker(
            marker_id: int,
            text: str,
            x: float,
            y: float,
            z: float,
            rgba: tuple[float, float, float, float],
            scale: float,
        ) -> Any:
            marker = Marker()
            marker.header.frame_id = "map"
            marker.ns = "comparison_text"
            marker.id = marker_id
            marker.type = Marker.TEXT_VIEW_FACING
            marker.action = Marker.ADD
            marker.pose.position.x = x
            marker.pose.position.y = y
            marker.pose.position.z = z
            marker.pose.orientation.w = 1.0
            marker.scale.z = scale
            marker.color.r, marker.color.g, marker.color.b, marker.color.a = rgba
            marker.text = text
            return marker

        @staticmethod
        def _line_marker(
            marker_id: int,
            y: float,
            rgba: tuple[float, float, float, float],
        ) -> Any:
            marker = Marker()
            marker.header.frame_id = "map"
            marker.ns = "comparison_lane"
            marker.id = marker_id
            marker.type = Marker.LINE_STRIP
            marker.action = Marker.ADD
            marker.scale.x = 0.035
            marker.color.r, marker.color.g, marker.color.b, marker.color.a = rgba
            start = Point()
            start.x, start.y, start.z = -0.40, y, 0.02
            end = Point()
            end.x, end.y, end.z = 1.35, y, 0.02
            marker.points = [start, end]
            return marker

        @staticmethod
        def _goal_marker(
            marker_id: int,
            y: float,
            rgba: tuple[float, float, float, float],
        ) -> Any:
            marker = Marker()
            marker.header.frame_id = "map"
            marker.ns = "comparison_goal"
            marker.id = marker_id
            marker.type = Marker.CYLINDER
            marker.action = Marker.ADD
            marker.pose.position.x = 1.0
            marker.pose.position.y = y
            marker.pose.position.z = 0.05
            marker.pose.orientation.w = 1.0
            marker.scale.x = 0.12
            marker.scale.y = 0.12
            marker.scale.z = 0.10
            marker.color.r, marker.color.g, marker.color.b, marker.color.a = rgba
            return marker

        def _publish_markers(self) -> None:
            baseline_color = (1.0, 0.48, 0.34, 1.0)
            embodied_color = (0.38, 0.88, 0.68, 1.0)
            white = (0.95, 0.95, 0.97, 1.0)
            markers = MarkerArray()
            markers.markers = [
                self._text_marker(
                    1,
                    "BASELINE\nDirect middleware execution",
                    0.45,
                    1.70,
                    1.40,
                    baseline_color,
                    0.22,
                ),
                self._text_marker(
                    2,
                    "EMBODIEDSKILL-ROS\nContract + outcome verification",
                    0.45,
                    -1.70,
                    1.40,
                    embodied_color,
                    0.22,
                ),
                self._text_marker(
                    3,
                    panel_text(
                        self._case,
                        "baseline",
                        self._targets["baseline"],
                        self._signals["baseline"],
                    ),
                    0.45,
                    1.70,
                    0.90,
                    white,
                    0.145,
                ),
                self._text_marker(
                    4,
                    panel_text(
                        self._case,
                        "embodied",
                        self._targets["embodied"],
                        self._signals["embodied"],
                    ),
                    0.45,
                    -1.70,
                    0.90,
                    white,
                    0.145,
                ),
                self._line_marker(10, LANE_Y["baseline"], baseline_color),
                self._line_marker(11, LANE_Y["embodied"], embodied_color),
                self._goal_marker(20, LANE_Y["baseline"], baseline_color),
                self._goal_marker(21, LANE_Y["embodied"], embodied_color),
            ]
            if self._case == REPAIR:
                task = (
                    "SAME TASK / SAME INITIAL STATE\n"
                    "move_agv(1.0 m)   |   left_arm_safe = FALSE"
                )
            else:
                task = (
                    "SAME FAULT INJECTION\n"
                    "ROS SUCCEEDED   |   physical transition = NONE"
                )
            markers.markers.append(
                self._text_marker(30, task, -0.55, 0.0, 1.85, white, 0.18)
            )
            self._marker_publisher.publish(markers)

    return RvizComparisonBridge()


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
