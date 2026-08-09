"""Process-separated test double for the audited legacy ROS interface schema.

This is not a physics simulator and is never a hardware backend.  It exists only to
exercise the integration adapter with the exact generated service/message types.
"""

from __future__ import annotations

import json
import threading
import time


def main(args=None) -> None:
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
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from sensor_msgs.msg import JointState
    from std_srvs.srv import Trigger

    class LegacyCompatibleStubNode(Node):
        def __init__(self) -> None:
            super().__init__("jaka_kargo_legacy_compatible_stub")
            self.declare_parameter("fault_mode", "normal")
            self.declare_parameter("delay_s", 1.0)
            self._lock = threading.Lock()
            self._group = ReentrantCallbackGroup()
            self._axes = [100.0, 0.0, 0.0, 0.0]
            self._axis_targets = list(self._axes)
            self._arms = [[0.0] * 7, [0.0] * 7]
            self._agv_x = 0.0
            self._agv_y = 0.0
            self._agv_moving = False
            self._agv_estop = False
            self._commands = 0
            self._stop_requests = 0

            self._joint_pub = self.create_publisher(
                JointState, "/upperlimb_joint_states", 10
            )
            self._odom_pub = self.create_publisher(
                Odometry, "/JAGV_O_01/global_nav_odom", 10
            )
            self._motion_pub = self.create_publisher(
                MotionState, "/JAGV_O_01/motion_state", 10
            )
            self.create_service(
                AxisStatusQuery, "/query_status_ext", self._query_axis,
                callback_group=self._group,
            )
            self.create_service(
                PoseQuery, "/query_pose_arm", self._query_arm,
                callback_group=self._group,
            )
            self.create_service(
                JointMove, "/joint_move_ext", self._move_axis,
                callback_group=self._group,
            )
            self.create_service(
                JointMove, "/joint_move_arm", self._move_arm,
                callback_group=self._group,
            )
            self.create_service(
                SinglePoseNavigate, "/navigate_single_pose", self._navigate,
                callback_group=self._group,
            )
            self.create_service(
                TriggerInt, "/motion_state_control", self._motion_control,
                callback_group=self._group,
            )
            self.create_service(
                Trigger, "/embodied_skill/jaka_kargo_stub/status", self._status,
                callback_group=self._group,
            )
            self.create_timer(0.05, self._publish_state, callback_group=self._group)

        def _fault_mode(self) -> str:
            return str(self.get_parameter("fault_mode").value)

        def _delay(self) -> None:
            if self._fault_mode() == "timeout":
                time.sleep(float(self.get_parameter("delay_s").value))

        def _accepted_without_transition(self) -> bool:
            return self._fault_mode() == "accepted_no_motion"

        def _rejected(self) -> bool:
            return self._fault_mode() == "command_rejected"

        def _query_axis(self, request, response):
            axis_id = int(request.id)
            with self._lock:
                if axis_id < 0 or axis_id >= len(self._axes):
                    response.success = 0
                    response.message = "invalid external axis"
                    return response
                response.success = 1
                response.message = "stub measured external-axis state"
                response.is_powered = True
                response.is_enabled = True
                response.is_on_limit = False
                response.is_inpos = True
                response.pos_cmd = self._axis_targets[axis_id]
                response.pos_fdb = self._axes[axis_id]
            return response

        def _query_arm(self, request, response):
            arm_id = int(request.id)
            with self._lock:
                if arm_id not in (0, 1):
                    response.success = 0
                    response.message = "invalid arm"
                    return response
                response.success = 1
                response.message = "stub measured arm state"
                response.joint_positions = list(self._arms[arm_id])
                response.cartesian_pose = [0.0] * 6
                response.use_mm = True
                response.use_rad = True
            return response

        def _move_axis(self, request, response):
            with self._lock:
                self._commands += 1
            if self._rejected():
                response.success = 0
                response.message = "stub rejected command"
                return response
            self._delay()
            axis_id = int(request.motion_unit_id)
            if axis_id not in range(4) or not request.joint_positions:
                response.success = 0
                response.message = "invalid external-axis request"
                return response
            with self._lock:
                if int(request.move_mode) == 3:
                    self._stop_requests += 1
                elif not self._accepted_without_transition():
                    target = float(request.joint_positions[0])
                    self._axis_targets[axis_id] = target
                    self._axes[axis_id] = target
            response.success = 1
            response.message = "stub SDK call returned success"
            return response

        def _move_arm(self, request, response):
            with self._lock:
                self._commands += 1
            if self._rejected():
                response.success = 0
                response.message = "stub rejected command"
                return response
            self._delay()
            arm_id = int(request.motion_unit_id)
            positions = [float(item) for item in request.joint_positions]
            if arm_id == -1 and len(positions) != 14:
                response.success = 0
                response.message = "bilateral request requires 14 joints"
                return response
            if arm_id in (0, 1) and len(positions) != 7:
                response.success = 0
                response.message = "single-arm request requires 7 joints"
                return response
            with self._lock:
                if not self._accepted_without_transition():
                    if arm_id == -1:
                        self._arms = [positions[:7], positions[7:]]
                    elif arm_id in (0, 1):
                        self._arms[arm_id] = positions
                    else:
                        response.success = 0
                        response.message = "invalid arm"
                        return response
            response.success = 1
            response.message = "stub SDK call returned success"
            return response

        def _navigate(self, request, response):
            with self._lock:
                self._commands += 1
                self._agv_moving = True
            if self._rejected():
                with self._lock:
                    self._agv_moving = False
                response.success = 0
                response.message = "stub rejected navigation"
                return response
            self._delay()
            with self._lock:
                if not self._accepted_without_transition():
                    self._agv_x = float(request.end_pose.pose.position.x)
                    self._agv_y = float(request.end_pose.pose.position.y)
                self._agv_moving = False
            response.success = 1
            response.message = "stub navigation service returned success"
            return response

        def _motion_control(self, request, response):
            with self._lock:
                if int(request.id) == 3:
                    self._agv_moving = False
                    self._stop_requests += 1
                    response.success = 1
                    response.message = "stub AGV stop accepted"
                else:
                    response.success = 0
                    response.message = "stub supports stop code 3 only"
            return response

        def _status(self, _request, response):
            with self._lock:
                payload = {
                    "commands": self._commands,
                    "stop_requests": self._stop_requests,
                    "axes": list(self._axes),
                    "agv_x": self._agv_x,
                }
            response.success = True
            response.message = json.dumps(payload, sort_keys=True)
            return response

        def _publish_state(self) -> None:
            now = self.get_clock().now().to_msg()
            with self._lock:
                axes = list(self._axes)
                arms = [list(item) for item in self._arms]
                agv_x = self._agv_x
                agv_y = self._agv_y
                moving = self._agv_moving
                estop = self._agv_estop

            joints = JointState()
            joints.header.stamp = now
            joints.name = [
                "body_j1", "body_j2", "body_j3", "body_j4",
                "arm_lj1", "arm_lj2", "arm_lj3", "arm_lj4", "arm_lj5",
                "arm_lj6", "arm_lj7", "arm_rj1", "arm_rj2", "arm_rj3",
                "arm_rj4", "arm_rj5", "arm_rj6", "arm_rj7",
            ]
            joints.position = [axes[0] / 1000.0] + axes[1:] + arms[0] + arms[1]
            self._joint_pub.publish(joints)

            odom = Odometry()
            odom.header.stamp = now
            odom.header.frame_id = "map"
            odom.child_frame_id = "base_link"
            odom.pose.pose.position.x = agv_x
            odom.pose.pose.position.y = agv_y
            odom.pose.pose.orientation.w = 1.0
            self._odom_pub.publish(odom)

            motion = MotionState()
            motion.state_id = 2 if moving else 0
            motion.drive_state = [1, 1, 1, 1]
            motion.drive_error_code = [0, 0, 0, 0]
            motion.wheel_states = 1 if estop else 0
            self._motion_pub.publish(motion)

    rclpy.init(args=args)
    node = LegacyCompatibleStubNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        executor.remove_node(node)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
