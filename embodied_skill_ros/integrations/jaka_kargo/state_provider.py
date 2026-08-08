from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...models.robot_state import RobotState
from .integration_config import JakaKargoIntegrationConfig
from .interface_contracts import ArmObservation, JakaKargoTransport


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_seconds(stamp: str, now: datetime) -> float:
    observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return (now - observed).total_seconds()


class JakaKargoStateProvider:
    """Map measured legacy ROS feedback into epistemic ``RobotState``.

    Query failures never inherit commanded targets.  They remain ``None`` and are
    therefore UNKNOWN to the frozen grounding/verification logic.
    """

    _AXIS_LIFT = 0
    _AXIS_WAIST = 1
    _AXIS_HEAD_YAW = 2
    _AXIS_HEAD_PITCH = 3

    def __init__(self, transport: JakaKargoTransport, config: JakaKargoIntegrationConfig):
        self.transport = transport
        self.config = config

    def _arm_safe(self, arm: str, observation: ArmObservation) -> bool | None:
        if not self.config.transport_pose_calibrated:
            return None
        target = self.config.arm_target(arm)
        if target is None or len(observation.joint_positions_rad) != len(target):
            return None
        tolerance = self.config.transport_joint_tolerance_rad
        return all(abs(actual - expected) <= tolerance for actual, expected in zip(
            observation.joint_positions_rad, target
        ))

    def observe(self) -> RobotState:
        now = datetime.now(timezone.utc)
        timeout = self.config.service_timeout_s
        values: dict[str, Any] = {}
        facts: dict[str, Any] = {}
        observed_at: dict[str, str] = {}
        sources: dict[str, str] = {}
        stale_fields: set[str] = set()
        errors: dict[str, str] = {}

        def record(names: tuple[str, ...], stamp: str, source: str) -> None:
            for name in names:
                observed_at[name] = stamp
                sources[name] = source
                try:
                    if _age_seconds(stamp, now) > self.config.observation_max_age_s:
                        stale_fields.add(name)
                except (TypeError, ValueError):
                    stale_fields.add(name)

        axis_observations = {}
        for axis_id, label in (
            (self._AXIS_LIFT, "lift"),
            (self._AXIS_WAIST, "waist"),
            (self._AXIS_HEAD_YAW, "head_yaw"),
            (self._AXIS_HEAD_PITCH, "head_pitch"),
        ):
            try:
                axis_observations[axis_id] = self.transport.query_external_axis(
                    axis_id, timeout
                )
            except Exception as exc:
                errors[label] = str(exc)

        lift = axis_observations.get(self._AXIS_LIFT)
        if lift is not None:
            values["lift_height_mm"] = float(lift.position)
            values["lift_ready"] = bool(lift.powered and lift.enabled and not lift.on_limit)
            facts["lift_in_position"] = bool(lift.in_position)
            facts["lift_commanded_mm"] = lift.commanded_position
            record(
                ("lift_height_mm", "lift_ready", "lift_in_position", "lift_commanded_mm"),
                lift.observed_at,
                lift.source,
            )

        waist = axis_observations.get(self._AXIS_WAIST)
        if waist is not None:
            facts["waist_angle_deg"] = float(waist.position)
            facts["waist_ready"] = bool(waist.powered and waist.enabled and not waist.on_limit)
            facts["waist_in_position"] = bool(waist.in_position)
            record(
                ("waist_angle_deg", "waist_ready", "waist_in_position"),
                waist.observed_at,
                waist.source,
            )

        yaw = axis_observations.get(self._AXIS_HEAD_YAW)
        pitch = axis_observations.get(self._AXIS_HEAD_PITCH)
        if yaw is not None:
            values["head_yaw_deg"] = float(yaw.position)
            record(("head_yaw_deg",), yaw.observed_at, yaw.source)
        if pitch is not None:
            # The delivered skill defines user-positive pitch as head-up, while
            # external axis 3 uses the opposite sign.
            values["head_pitch_deg"] = -float(pitch.position)
            record(("head_pitch_deg",), pitch.observed_at, pitch.source)
        if yaw is not None and pitch is not None:
            values["head_ready"] = bool(
                yaw.powered and yaw.enabled and not yaw.on_limit
                and pitch.powered and pitch.enabled and not pitch.on_limit
            )
            head_stamp = min(yaw.observed_at, pitch.observed_at)
            record(("head_ready",), head_stamp, f"{yaw.source} axes 2/3")

        for arm_id, arm in ((0, "left"), (1, "right")):
            try:
                observation = self.transport.query_arm(arm_id, timeout)
            except Exception as exc:
                errors[f"{arm}_arm"] = str(exc)
                continue
            ready_field = f"{arm}_arm_ready"
            safe_field = f"{arm}_arm_safe"
            joint_field = f"{arm}_arm_joint_positions_rad"
            tcp_field = f"{arm}_arm_tcp_pose_mm_rad"
            # PoseQuery exposes joints/TCP but no powered/enabled field. Query
            # success is not motion-readiness evidence unless a deployment has
            # explicitly reviewed and asserted that interpretation.
            values[ready_field] = (
                True if self.config.arm_pose_query_implies_ready else None
            )
            values[safe_field] = self._arm_safe(arm, observation)
            facts[joint_field] = observation.joint_positions_rad
            facts[tcp_field] = observation.tcp_pose_mm_rad
            record(
                (ready_field, safe_field, joint_field, tcp_field),
                observation.observed_at,
                observation.source,
            )

        try:
            agv = self.transport.query_agv(timeout)
        except Exception as exc:
            errors["agv"] = str(exc)
        else:
            values["agv_position_m"] = agv.position_x_m
            values["agv_moving"] = agv.moving
            values["agv_ready"] = (
                agv.position_x_m is not None
                and agv.motion_state_id is not None
                and agv.emergency_stop is not None
                and not agv.emergency_stop
                and not agv.fault
            )
            facts["agv_position_y_m"] = agv.position_y_m
            facts["agv_orientation_xyzw"] = agv.orientation_xyzw
            facts["agv_motion_state_id"] = agv.motion_state_id
            facts["agv_emergency_stop"] = agv.emergency_stop
            facts["agv_fault"] = agv.fault
            agv_fields = (
                "agv_position_m", "agv_moving", "agv_ready", "agv_position_y_m",
                "agv_orientation_xyzw", "agv_motion_state_id", "agv_emergency_stop",
                "agv_fault",
            )
            record(agv_fields, agv.observed_at, agv.source)
            if self.config.whole_robot_estop_observable:
                values["emergency_stop"] = agv.emergency_stop
                values["fault"] = agv.fault
                record(("emergency_stop", "fault"), agv.observed_at, agv.source)

        if errors:
            facts["jaka_kargo_observation_errors"] = errors
        facts["jaka_kargo_observation_sources"] = sources
        return RobotState(
            **values,
            facts=facts,
            observed_at=observed_at,
            stale_fields=stale_fields,
            timestamp=now.isoformat(),
        )
