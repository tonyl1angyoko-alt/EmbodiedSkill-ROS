from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .interface_contracts import StopScope


class ArmCommandScope(str, Enum):
    """How the deployed arm transport command affects components."""

    SINGLE_ARM_SERVICE = "SINGLE_ARM_SERVICE"
    LEGACY_BILATERAL_PRESET = "LEGACY_BILATERAL_PRESET"


@dataclass(frozen=True)
class JakaKargoEndpoints:
    axis_status_service: str = "/query_status_ext"
    arm_pose_service: str = "/query_pose_arm"
    external_axis_move_service: str = "/joint_move_ext"
    arm_joint_move_service: str = "/joint_move_arm"
    agv_navigation_service: str = "/navigate_single_pose"
    agv_stop_service: str = "/motion_state_control"
    upper_limb_joint_topic: str = "/upperlimb_joint_states"
    agv_odometry_topic: str = "/JAGV_O_01/global_nav_odom"
    agv_motion_state_topic: str = "/JAGV_O_01/motion_state"


@dataclass(frozen=True)
class JakaKargoIntegrationConfig:
    """Deployment facts that must be explicit instead of inferred from success."""

    endpoints: JakaKargoEndpoints = field(default_factory=JakaKargoEndpoints)
    motion_enabled: bool = False
    whole_robot_estop_observable: bool = False
    stop_scope: StopScope = StopScope.AGV_ONLY
    arm_command_scope: ArmCommandScope = ArmCommandScope.SINGLE_ARM_SERVICE
    arm_pose_query_implies_ready: bool = False
    left_transport_joints_rad: tuple[float, ...] | None = None
    right_transport_joints_rad: tuple[float, ...] | None = None
    transport_pose_calibrated: bool = False
    transport_joint_tolerance_rad: float = 0.03
    observation_max_age_s: float = 2.0
    service_timeout_s: float = 10.0
    arm_velocity_rad_s: float = 0.35
    arm_acceleration_rad_s2: float = 0.35
    external_axis_velocity: float = 20.0
    external_axis_acceleration: float = 20.0
    lift_min_mm: float = 0.0
    lift_max_mm: float = 780.0
    waist_min_deg: float = 0.0
    waist_max_deg: float = 84.0
    head_yaw_min_deg: float = -90.0
    head_yaw_max_deg: float = 90.0
    head_pitch_min_deg: float = -45.0
    head_pitch_max_deg: float = 20.0
    agv_map_name: str = ""

    def __post_init__(self) -> None:
        if self.observation_max_age_s <= 0 or self.service_timeout_s <= 0:
            raise ValueError("timeouts and freshness bounds must be positive")
        for name, target in (
            ("left_transport_joints_rad", self.left_transport_joints_rad),
            ("right_transport_joints_rad", self.right_transport_joints_rad),
        ):
            if target is not None and len(target) != 7:
                raise ValueError(f"{name} must contain seven joints")
        if self.transport_pose_calibrated and (
            self.left_transport_joints_rad is None
            or self.right_transport_joints_rad is None
        ):
            raise ValueError("calibrated transport pose requires both seven-joint targets")
        if self.stop_scope is StopScope.WHOLE_ROBOT:
            raise ValueError(
                "the audited legacy transport exposes only AGV stop; "
                "WHOLE_ROBOT cannot be configured here"
            )

    def arm_target(self, arm: str) -> tuple[float, ...] | None:
        if arm == "left":
            return self.left_transport_joints_rad
        if arm == "right":
            return self.right_transport_joints_rad
        raise ValueError(f"unknown arm: {arm}")
