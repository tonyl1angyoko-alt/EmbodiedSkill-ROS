from __future__ import annotations

from datetime import datetime, timezone
import math
import threading
import time
from typing import Any

from .integration_config import JakaKargoEndpoints
from .interface_contracts import (
    AgvObservation,
    ArmObservation,
    AxisObservation,
    TransportResult,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp_to_iso(stamp: Any) -> str:
    seconds = int(getattr(stamp, "sec", 0))
    nanoseconds = int(getattr(stamp, "nanosec", 0))
    if seconds <= 0:
        return _utc_now()
    return datetime.fromtimestamp(
        seconds + nanoseconds / 1_000_000_000.0, timezone.utc
    ).isoformat()


class JakaKargoRos2Transport:
    """Lazy-importing ROS2 client for the delivered interface packages.

    The transport uses the exact generated ``jaka_toolbox_interfaces`` and
    ``jagv_interfaces`` types.  Those packages remain external dependencies and are
    intentionally absent from ``package.xml`` so pure-core users keep working.
    """

    def __init__(
        self,
        endpoints: JakaKargoEndpoints = JakaKargoEndpoints(),
        *,
        discovery_timeout_s: float = 3.0,
    ) -> None:
        try:
            import rclpy
            from jagv_interfaces.msg import MotionState
            from jaka_toolbox_interfaces.srv import (
                AxisStatusQuery,
                JointMove,
                PoseQuery,
                SinglePoseNavigate,
                TriggerInt,
            )
            from nav_msgs.msg import Odometry
            from rclpy.context import Context
            from rclpy.executors import MultiThreadedExecutor
            from rclpy.node import Node
        except ImportError as exc:
            raise RuntimeError(
                "JAKA/Kargo ROS interfaces are unavailable. Build and source the "
                "external jagv_interfaces and jaka_toolbox_interfaces packages."
            ) from exc

        self.endpoints = endpoints
        self._rclpy = rclpy
        self._AxisStatusQuery = AxisStatusQuery
        self._JointMove = JointMove
        self._PoseQuery = PoseQuery
        self._SinglePoseNavigate = SinglePoseNavigate
        self._TriggerInt = TriggerInt
        self._context = Context()
        rclpy.init(args=None, context=self._context)
        self._node = Node(
            f"embodied_skill_jaka_kargo_{id(self) & 0xffff:x}", context=self._context
        )
        self._executor = MultiThreadedExecutor(num_threads=4, context=self._context)
        self._executor.add_node(self._node)
        self._spin_thread = threading.Thread(
            target=self._executor.spin,
            name="embodied-skill-jaka-kargo-transport",
            daemon=True,
        )
        self._spin_thread.start()
        self._closed = False
        self._condition = threading.Condition()
        self._latest_odom: Any = None
        self._latest_odom_at: str | None = None
        self._odom_sequence = 0
        self._latest_motion: Any = None
        self._latest_motion_at: str | None = None
        self._motion_sequence = 0
        self._pending_agv_observation_barrier: tuple[int, int] | None = None

        self._axis_status = self._node.create_client(
            AxisStatusQuery, endpoints.axis_status_service
        )
        self._arm_pose = self._node.create_client(PoseQuery, endpoints.arm_pose_service)
        self._external_move = self._node.create_client(
            JointMove, endpoints.external_axis_move_service
        )
        self._arm_move = self._node.create_client(
            JointMove, endpoints.arm_joint_move_service
        )
        self._agv_navigation = self._node.create_client(
            SinglePoseNavigate, endpoints.agv_navigation_service
        )
        self._agv_stop = self._node.create_client(TriggerInt, endpoints.agv_stop_service)
        self._odom_sub = self._node.create_subscription(
            Odometry, endpoints.agv_odometry_topic, self._receive_odom, 10
        )
        self._motion_sub = self._node.create_subscription(
            MotionState, endpoints.agv_motion_state_topic, self._receive_motion, 10
        )

        # Give DDS discovery and latched test publishers a bounded opportunity to
        # appear. Missing endpoints remain absent from capability preflight.
        deadline = time.monotonic() + max(0.0, discovery_timeout_s)
        while time.monotonic() < deadline:
            if self.available_endpoints():
                with self._condition:
                    if self._latest_odom is not None and self._latest_motion is not None:
                        break
            time.sleep(0.05)

    def _receive_odom(self, message: Any) -> None:
        with self._condition:
            self._latest_odom = message
            self._latest_odom_at = _stamp_to_iso(message.header.stamp)
            self._odom_sequence += 1
            self._condition.notify_all()

    def _receive_motion(self, message: Any) -> None:
        with self._condition:
            self._latest_motion = message
            self._latest_motion_at = _utc_now()
            self._motion_sequence += 1
            self._condition.notify_all()

    @staticmethod
    def _await_future(future: Any, timeout_s: float, operation: str) -> Any:
        completed = threading.Event()
        future.add_done_callback(lambda _future: completed.set())
        if not completed.wait(timeout_s):
            # A ROS service future cannot reliably cancel the already-running
            # server callback. Report the timeout without pretending motion stopped.
            raise TimeoutError(
                f"ROS service {operation} timed out after {timeout_s:.3f}s; "
                "underlying motion may still be running"
            )
        exception = future.exception()
        if exception is not None:
            raise RuntimeError(f"ROS service {operation} failed: {exception}")
        return future.result()

    def _call(self, client: Any, request: Any, timeout_s: float, operation: str) -> Any:
        if not client.wait_for_service(timeout_sec=min(timeout_s, 2.0)):
            raise RuntimeError(f"ROS service unavailable: {operation}")
        return self._await_future(client.call_async(request), timeout_s, operation)

    def available_endpoints(self) -> frozenset[str]:
        available: set[str] = set()
        for client, name in (
            (self._axis_status, self.endpoints.axis_status_service),
            (self._arm_pose, self.endpoints.arm_pose_service),
            (self._external_move, self.endpoints.external_axis_move_service),
            (self._arm_move, self.endpoints.arm_joint_move_service),
            (self._agv_navigation, self.endpoints.agv_navigation_service),
            (self._agv_stop, self.endpoints.agv_stop_service),
        ):
            if client.service_is_ready() or client.wait_for_service(timeout_sec=0.0):
                available.add(name)
        with self._condition:
            if self._latest_odom is not None:
                available.add(self.endpoints.agv_odometry_topic)
            if self._latest_motion is not None:
                available.add(self.endpoints.agv_motion_state_topic)
        return frozenset(available)

    def query_external_axis(self, axis_id: int, timeout_s: float) -> AxisObservation:
        request = self._AxisStatusQuery.Request()
        request.id = int(axis_id)
        response = self._call(
            self._axis_status, request, timeout_s, self.endpoints.axis_status_service
        )
        if int(response.success) != 1:
            raise RuntimeError(response.message or f"axis {axis_id} query rejected")
        return AxisObservation(
            axis_id=axis_id,
            position=float(response.pos_fdb),
            commanded_position=float(response.pos_cmd),
            powered=bool(response.is_powered),
            enabled=bool(response.is_enabled),
            on_limit=bool(response.is_on_limit),
            in_position=bool(response.is_inpos),
            observed_at=_utc_now(),
            source=self.endpoints.axis_status_service,
        )

    def query_arm(self, arm_id: int, timeout_s: float) -> ArmObservation:
        request = self._PoseQuery.Request()
        request.id = int(arm_id)
        request.ref_joint_positions = []
        response = self._call(
            self._arm_pose, request, timeout_s, self.endpoints.arm_pose_service
        )
        if int(response.success) != 1:
            raise RuntimeError(response.message or f"arm {arm_id} query rejected")
        joints = tuple(float(item) for item in response.joint_positions)
        pose = tuple(float(item) for item in response.cartesian_pose)
        if len(joints) != 7 or len(pose) != 6:
            raise RuntimeError(
                f"arm {arm_id} query returned malformed dimensions: "
                f"joints={len(joints)}, pose={len(pose)}"
            )
        return ArmObservation(
            arm_id=arm_id,
            joint_positions_rad=joints,
            tcp_pose_mm_rad=pose,
            observed_at=_utc_now(),
            source=self.endpoints.arm_pose_service,
        )

    def query_agv(self, timeout_s: float) -> AgvObservation:
        deadline = time.monotonic() + timeout_s
        with self._condition:
            barrier = self._pending_agv_observation_barrier
            while (
                self._latest_odom is None
                or self._latest_motion is None
                or (
                    barrier is not None
                    and (
                        self._odom_sequence < barrier[0]
                        or self._motion_sequence < barrier[1]
                    )
                )
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if barrier is None:
                        detail = "initial"
                    else:
                        detail = "post-command"
                    raise TimeoutError(
                        f"{detail} AGV odometry/motion-state observation timed out"
                    )
                self._condition.wait(remaining)
            odom = self._latest_odom
            motion = self._latest_motion
            odom_at = self._latest_odom_at or _utc_now()
            motion_at = self._latest_motion_at or _utc_now()
            if barrier is not None:
                self._pending_agv_observation_barrier = None
        pose = odom.pose.pose
        orientation = pose.orientation
        state_id = int(motion.state_id)
        wheel_states = int(motion.wheel_states)
        drive_state = tuple(int(item) for item in motion.drive_state)
        drive_errors = tuple(int(item) for item in motion.drive_error_code)
        fault = None
        if any(item & 0b10 for item in drive_state) or any(drive_errors):
            fault = "AGV drive error reported by motion_state"
        return AgvObservation(
            position_x_m=float(pose.position.x),
            position_y_m=float(pose.position.y),
            orientation_xyzw=(
                float(orientation.x), float(orientation.y),
                float(orientation.z), float(orientation.w),
            ),
            moving=state_id == 2,
            motion_state_id=state_id,
            emergency_stop=bool(wheel_states & 0b1),
            fault=fault,
            observed_at=min(odom_at, motion_at),
            source=(
                f"{self.endpoints.agv_odometry_topic} + "
                f"{self.endpoints.agv_motion_state_topic}"
            ),
        )

    def move_external_axis(
        self,
        axis_id: int,
        target: float,
        velocity: float,
        acceleration: float,
        timeout_s: float,
    ) -> TransportResult:
        request = self._JointMove.Request()
        request.motion_unit_type = 1
        request.motion_unit_id = int(axis_id)
        request.move_mode = 0
        request.joint_positions = [float(target)]
        request.joint_velocity = float(velocity)
        request.joint_acceleration = float(acceleration)
        request.joint_jerk = 0.0
        request.blend_tolerance = 0.0
        request.use_rad = True
        try:
            response = self._call(
                self._external_move,
                request,
                timeout_s,
                self.endpoints.external_axis_move_service,
            )
        except TimeoutError as exc:
            return TransportResult(False, str(exc), timed_out=True)
        return TransportResult(
            int(response.success) == 1,
            response.message,
            call_result={"success": int(response.success)},
        )

    def move_arm_joints(
        self,
        arm_id: int,
        joint_positions_rad: tuple[float, ...],
        velocity: float,
        acceleration: float,
        timeout_s: float,
    ) -> TransportResult:
        expected = 14 if arm_id == -1 else 7
        if len(joint_positions_rad) != expected:
            return TransportResult(
                False, f"arm {arm_id} requires {expected} joint values"
            )
        request = self._JointMove.Request()
        request.motion_unit_type = 0
        request.motion_unit_id = int(arm_id)
        request.move_mode = 0
        request.joint_positions = [float(item) for item in joint_positions_rad]
        request.joint_velocity = float(velocity)
        request.joint_acceleration = float(acceleration)
        request.joint_jerk = 0.0
        request.blend_tolerance = 0.0
        request.use_rad = True
        try:
            response = self._call(
                self._arm_move,
                request,
                timeout_s,
                self.endpoints.arm_joint_move_service,
            )
        except TimeoutError as exc:
            return TransportResult(False, str(exc), timed_out=True)
        return TransportResult(
            int(response.success) == 1,
            response.message,
            call_result={"success": int(response.success)},
        )

    def navigate_agv_x(
        self,
        target_x_m: float,
        speed_mps: float,
        map_name: str,
        timeout_s: float,
    ) -> TransportResult:
        with self._condition:
            odom = self._latest_odom
        if odom is None:
            return TransportResult(False, "AGV odometry is unavailable")
        with self._condition:
            before_sequences = (self._odom_sequence, self._motion_sequence)
        request = self._SinglePoseNavigate.Request()
        # Do not assign the cached observation message into the request: generated
        # ROS message objects may retain the same nested object. Mutating request.x
        # could then make the local observation appear to reach the target before a
        # later topic sample arrives.
        request.end_pose.header.stamp = odom.header.stamp
        request.end_pose.header.frame_id = odom.header.frame_id
        request.end_pose.pose.position.y = float(odom.pose.pose.position.y)
        request.end_pose.pose.position.z = float(odom.pose.pose.position.z)
        request.end_pose.pose.orientation.x = float(odom.pose.pose.orientation.x)
        request.end_pose.pose.orientation.y = float(odom.pose.pose.orientation.y)
        request.end_pose.pose.orientation.z = float(odom.pose.pose.orientation.z)
        request.end_pose.pose.orientation.w = float(odom.pose.pose.orientation.w)
        request.end_pose.pose.position.x = float(target_x_m)
        request.linear_speed = float(speed_mps)
        request.angular_speed = 0.2
        request.dece_distance = 2.0
        request.stop_distance = 0.05
        request.move_mode = 0
        request.move_type = 0
        request.map_name = str(map_name)
        request.timeout = max(1, int(math.ceil(timeout_s)))
        try:
            response = self._call(
                self._agv_navigation,
                request,
                timeout_s,
                self.endpoints.agv_navigation_service,
            )
        except TimeoutError as exc:
            return TransportResult(False, str(exc), timed_out=True)
        accepted = int(response.success) == 1
        if accepted:
            # The verifier must consume topic evidence newer than the observation
            # used to ground this command, whether or not the physical value changed.
            with self._condition:
                self._pending_agv_observation_barrier = (
                    before_sequences[0] + 1,
                    before_sequences[1] + 1,
                )
        return TransportResult(
            accepted,
            response.message,
            call_result={"success": int(response.success)},
        )

    def stop_agv(self, timeout_s: float) -> TransportResult:
        request = self._TriggerInt.Request()
        request.id = 3
        try:
            response = self._call(
                self._agv_stop, request, timeout_s, self.endpoints.agv_stop_service
            )
        except TimeoutError as exc:
            return TransportResult(False, str(exc), timed_out=True)
        return TransportResult(
            int(response.success) == 1,
            response.message,
            call_result={"success": int(response.success), "requested_state": 3},
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(timeout_sec=2.0)
        self._executor.remove_node(self._node)
        self._node.destroy_node()
        if self._context.ok():
            self._context.shutdown()
        self._spin_thread.join(timeout=2.0)

    def __enter__(self) -> "JakaKargoRos2Transport":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()
