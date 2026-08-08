from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...backends.base_backend import (
    BackendCapabilities,
    ParameterDomain,
    SkillSemantics,
)
from .integration_config import ArmCommandScope, JakaKargoIntegrationConfig
from .interface_contracts import (
    CancellationSupport,
    JakaKargoTransport,
    StopScope,
    TimeoutSemantics,
)


@dataclass(frozen=True)
class IntegrationCapabilityReport:
    stop_scope: StopScope
    cancellation: tuple[tuple[str, CancellationSupport], ...]
    timeout_semantics: tuple[tuple[str, TimeoutSemantics], ...]
    available_endpoints: frozenset[str]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stop_scope": self.stop_scope.value,
            "cancellation": {name: value.value for name, value in self.cancellation},
            "timeout_semantics": {
                name: value.value for name, value in self.timeout_semantics
            },
            "available_endpoints": sorted(self.available_endpoints),
            "blockers": list(self.blockers),
        }


class JakaKargoCapabilityMapper:
    """Derive core capabilities from discovered legacy endpoints and semantics."""

    def __init__(self, transport: JakaKargoTransport, config: JakaKargoIntegrationConfig):
        self.transport = transport
        self.config = config

    def map(self) -> tuple[BackendCapabilities, IntegrationCapabilityReport]:
        endpoints = self.transport.available_endpoints()
        names = self.config.endpoints
        observable: set[str] = {"last_skill_result"}
        supported: set[str] = set()
        blockers: list[str] = []

        if names.axis_status_service in endpoints:
            observable.update({
                "lift_height_mm", "lift_ready", "head_yaw_deg", "head_pitch_deg",
                "head_ready", "waist_angle_deg", "waist_ready",
            })
        if names.arm_pose_service in endpoints:
            if self.config.arm_pose_query_implies_ready:
                observable.update({"left_arm_ready", "right_arm_ready"})
            if self.config.transport_pose_calibrated:
                observable.update({"left_arm_safe", "right_arm_safe"})
        if names.agv_odometry_topic in endpoints:
            observable.update({"agv_position_m", "agv_position_y_m"})
        if names.agv_motion_state_topic in endpoints:
            observable.update({
                "agv_moving", "agv_ready", "agv_emergency_stop", "agv_fault",
            })
            if self.config.whole_robot_estop_observable:
                observable.update({"emergency_stop", "fault"})

        admission_allowed = self.config.motion_enabled
        if not self.config.motion_enabled:
            blockers.append("motion is disabled by configuration")
        if not self.config.whole_robot_estop_observable:
            admission_allowed = False
            blockers.append("whole-robot emergency-stop state is not observable")

        def has(*required: str) -> bool:
            return all(item in endpoints for item in required)

        if admission_allowed:
            if has(names.external_axis_move_service, names.axis_status_service):
                supported.update({"set_lift", "set_head", "set_waist"})
            else:
                blockers.append("external-axis command/status endpoint is unavailable")

            if (
                self.config.transport_pose_calibrated
                and self.config.arm_pose_query_implies_ready
                and has(names.arm_joint_move_service, names.arm_pose_service)
            ):
                supported.add("retract_arm")
            else:
                blockers.append(
                    "calibrated arm target, reviewed readiness semantics, or arm "
                    "command/status endpoint is unavailable"
                )

            if has(
                names.agv_navigation_service,
                names.agv_odometry_topic,
                names.agv_motion_state_topic,
                names.agv_stop_service,
            ):
                supported.add("move_agv")
            else:
                blockers.append("AGV navigation/odometry/motion-state/stop boundary is incomplete")

        semantics: list[SkillSemantics] = []
        if "retract_arm" in supported:
            effects = frozenset()
            if self.config.arm_command_scope is ArmCommandScope.LEGACY_BILATERAL_PRESET:
                effects = frozenset({"left_arm_safe", "right_arm_safe"})
            semantics.append(SkillSemantics(
                "retract_arm",
                (ParameterDomain("arm", choices=frozenset({"left", "right"})),),
                effects,
            ))
        if "move_agv" in supported:
            semantics.append(SkillSemantics(
                "move_agv", (ParameterDomain("speed_mps", minimum=0.01, maximum=0.5),)
            ))
        if "set_lift" in supported:
            semantics.append(SkillSemantics(
                "set_lift",
                (ParameterDomain(
                    "height_mm", minimum=self.config.lift_min_mm,
                    maximum=self.config.lift_max_mm,
                ),),
            ))
        if "set_head" in supported:
            semantics.append(SkillSemantics(
                "set_head",
                (
                    ParameterDomain(
                        "yaw_deg", minimum=self.config.head_yaw_min_deg,
                        maximum=self.config.head_yaw_max_deg,
                    ),
                    ParameterDomain(
                        "pitch_deg", minimum=self.config.head_pitch_min_deg,
                        maximum=self.config.head_pitch_max_deg,
                    ),
                ),
            ))
        if "set_waist" in supported:
            semantics.append(SkillSemantics(
                "set_waist",
                (ParameterDomain(
                    "angle_deg", minimum=self.config.waist_min_deg,
                    maximum=self.config.waist_max_deg,
                ),),
            ))

        core = BackendCapabilities(
            backend_name="JakaKargoBackend",
            supported_skills=frozenset(supported),
            observable_fields=frozenset(observable),
            # The audited legacy stop endpoint is AGV-only, never a whole-robot
            # safety certificate.
            supports_safe_stop=False,
            runtime="optional-jaka-kargo-ros2-humble",
            refreshable_fields=frozenset(observable),
            skill_semantics=tuple(semantics),
        )
        report = IntegrationCapabilityReport(
            stop_scope=self.config.stop_scope,
            cancellation=(
                ("retract_arm", CancellationSupport.NONE),
                ("set_lift", CancellationSupport.NONE),
                ("set_head", CancellationSupport.NONE),
                ("set_waist", CancellationSupport.NONE),
                ("move_agv", CancellationSupport.COMPONENT_STOP),
            ),
            timeout_semantics=(
                ("retract_arm", TimeoutSemantics.CLIENT_WAIT_ONLY),
                ("set_lift", TimeoutSemantics.CLIENT_WAIT_ONLY),
                ("set_head", TimeoutSemantics.CLIENT_WAIT_ONLY),
                ("set_waist", TimeoutSemantics.CLIENT_WAIT_ONLY),
                ("move_agv", TimeoutSemantics.BACKEND_BOUNDED),
            ),
            available_endpoints=endpoints,
            blockers=tuple(dict.fromkeys(blockers)),
        )
        return core, report
