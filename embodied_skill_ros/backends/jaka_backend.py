from __future__ import annotations

from typing import Any, Callable

from .base_backend import RobotBackend
from ..models.robot_state import RobotState
from ..models.skill_result import CommandReceipt


class JakaRobotBackend(RobotBackend):
    """Adapter over verified legacy skill objects; importing it does not require ROS2.

    Arm transport safety cannot be inferred from an arbitrary named preset. It is
    therefore UNKNOWN unless the integrator explicitly supplies and validates a
    ``transport_pose_name`` for the deployed robot.
    """

    def __init__(self, *, arm_skill: Any = None, agv_skill: Any = None,
                 lift_skill: Any = None, head_skill: Any = None,
                 transport_pose_name: str | None = None,
                 state_provider: Callable[[], RobotState] | None = None,
                 agv_position_provider: Callable[[], float] | None = None):
        self.arm = arm_skill
        self.agv = agv_skill
        self.lift = lift_skill
        self.head = head_skill
        self.transport_pose_name = transport_pose_name
        self.state_provider = state_provider
        self.agv_position_provider = agv_position_provider
        self._last_agv_position: float | None = None  # No odometry adapter confirmed in chat_agent path.

    def observe(self) -> RobotState:
        if self.state_provider is not None:
            return self.state_provider().copy()
        state = RobotState(
            left_arm_ready=False if self.arm is None else None,
            right_arm_ready=False if self.arm is None else None,
            left_arm_safe=None,
            right_arm_safe=None,
            agv_ready=False if self.agv is None else None,
            agv_moving=None,
            agv_position_m=self._last_agv_position,
            lift_ready=False if self.lift is None else None,
            head_ready=False if self.head is None else None,
            emergency_stop=None,
        )
        try:
            if self.arm is not None and hasattr(self.arm, "_query_arm"):
                self.arm._query_arm(0)
                self.arm._query_arm(1)
                state.left_arm_ready = state.right_arm_ready = True
        except Exception:
            state.left_arm_ready = state.right_arm_ready = False
        try:
            if self.lift is not None:
                state.lift_height_mm = float(self.lift.backend.get_j1_mm())
                state.lift_ready = True
        except Exception:
            state.lift_height_mm = None
            state.lift_ready = False
        try:
            if self.head is not None:
                state.head_yaw_deg = float(self.head.backend.get_yaw_deg())
                state.head_pitch_deg = float(self.head.backend.get_pitch_deg())
                state.head_ready = True
        except Exception:
            state.head_yaw_deg = state.head_pitch_deg = None
            state.head_ready = False
        try:
            if self.agv_position_provider is not None:
                state.agv_position_m = float(self.agv_position_provider())
                state.agv_ready = self.agv is not None
        except Exception:
            state.agv_position_m = None
            state.agv_ready = False
        return state

    def command(self, skill_name: str, arguments: dict[str, Any]) -> CommandReceipt:
        try:
            if skill_name == "retract_arm":
                if self.arm is None or self.transport_pose_name is None:
                    return CommandReceipt(False, "UNKNOWN: validated transport arm pose is not configured")
                # Legacy API moves both arms; single-arm transport is not confirmed.
                ok = bool(self.arm.go_preset(self.transport_pose_name))
            elif skill_name == "move_agv":
                if self.agv is None:
                    return CommandReceipt(False, "AGV adapter unavailable")
                direction = "forward" if arguments["distance_m"] >= 0 else "backward"
                self.agv.drive_distance(direction, abs(arguments["distance_m"]),
                                        arguments.get("speed_mps", 0.2))
                ok = True
            elif skill_name == "set_lift":
                ok = self.lift is not None and bool(self.lift.lift_to(arguments["height_mm"]))
            elif skill_name == "set_head":
                if self.head is None:
                    return CommandReceipt(False, "head adapter unavailable")
                ok = True
                if "yaw_deg" in arguments:
                    ok = bool(self.head.yaw_to(arguments["yaw_deg"])) and ok
                if "pitch_deg" in arguments:
                    ok = bool(self.head.pitch_to(arguments["pitch_deg"])) and ok
            elif skill_name == "safe_stop":
                if self.agv is not None:
                    self.agv.stop()
                ok = True
            else:
                return CommandReceipt(False, f"JAKA adapter does not implement {skill_name}")
            return CommandReceipt(bool(ok), "legacy ROS2/SDK call returned success" if ok else "legacy call failed")
        except TimeoutError as exc:
            return CommandReceipt(False, str(exc), timed_out=True)
        except Exception as exc:
            return CommandReceipt(False, f"adapter error: {exc}")
