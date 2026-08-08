from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class StopScope(str, Enum):
    AGV_ONLY = "AGV_ONLY"
    COMPONENT_ONLY = "COMPONENT_ONLY"
    WHOLE_ROBOT = "WHOLE_ROBOT"
    UNAVAILABLE = "UNAVAILABLE"


class CancellationSupport(str, Enum):
    NONE = "NONE"
    COMPONENT_STOP = "COMPONENT_STOP"
    CANCELLABLE_ACTION = "CANCELLABLE_ACTION"


class TimeoutSemantics(str, Enum):
    NONE = "NONE"
    CLIENT_WAIT_ONLY = "CLIENT_WAIT_ONLY"
    BACKEND_BOUNDED = "BACKEND_BOUNDED"


@dataclass(frozen=True)
class AxisObservation:
    axis_id: int
    position: float
    commanded_position: float | None
    powered: bool
    enabled: bool
    on_limit: bool
    in_position: bool
    observed_at: str
    source: str = "/query_status_ext"


@dataclass(frozen=True)
class ArmObservation:
    arm_id: int
    joint_positions_rad: tuple[float, ...]
    tcp_pose_mm_rad: tuple[float, ...]
    observed_at: str
    source: str = "/query_pose_arm"


@dataclass(frozen=True)
class AgvObservation:
    position_x_m: float | None
    position_y_m: float | None
    orientation_xyzw: tuple[float, float, float, float] | None
    moving: bool | None
    motion_state_id: int | None
    emergency_stop: bool | None
    fault: str | None
    observed_at: str
    source: str = "AGV odometry + motion-state topics"


@dataclass(frozen=True)
class TransportResult:
    accepted: bool
    message: str
    timed_out: bool = False
    call_result: Any = None


class JakaKargoTransport(Protocol):
    """Transport-neutral shape of the laboratory ROS2 interface surface."""

    def available_endpoints(self) -> frozenset[str]: ...

    def query_external_axis(self, axis_id: int, timeout_s: float) -> AxisObservation: ...

    def query_arm(self, arm_id: int, timeout_s: float) -> ArmObservation: ...

    def query_agv(self, timeout_s: float) -> AgvObservation: ...

    def move_external_axis(
        self,
        axis_id: int,
        target: float,
        velocity: float,
        acceleration: float,
        timeout_s: float,
    ) -> TransportResult: ...

    def move_arm_joints(
        self,
        arm_id: int,
        joint_positions_rad: tuple[float, ...],
        velocity: float,
        acceleration: float,
        timeout_s: float,
    ) -> TransportResult: ...

    def navigate_agv_x(
        self,
        target_x_m: float,
        speed_mps: float,
        map_name: str,
        timeout_s: float,
    ) -> TransportResult: ...

    def stop_agv(self, timeout_s: float) -> TransportResult: ...

    def close(self) -> None: ...
