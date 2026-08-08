from __future__ import annotations

from typing import Any

from ...backends.base_backend import BackendCapabilities, RobotBackend
from ...models.robot_state import KnowledgeStatus, RobotState
from ...models.skill_result import CommandReceipt
from .capability_mapper import IntegrationCapabilityReport, JakaKargoCapabilityMapper
from .integration_config import ArmCommandScope, JakaKargoIntegrationConfig
from .interface_contracts import JakaKargoTransport, TransportResult
from .state_provider import JakaKargoStateProvider


class JakaKargoBackend(RobotBackend):
    """EmbodiedSkill-owned adapter over the external JAKA/Kargo ROS2 stack."""

    def __init__(
        self,
        transport: JakaKargoTransport,
        config: JakaKargoIntegrationConfig,
        state_provider: JakaKargoStateProvider | None = None,
    ) -> None:
        self.transport = transport
        self.config = config
        self.state_provider = state_provider or JakaKargoStateProvider(transport, config)

    def capabilities(self) -> BackendCapabilities:
        capabilities, _report = JakaKargoCapabilityMapper(
            self.transport, self.config
        ).map()
        return capabilities

    def integration_capabilities(self) -> IntegrationCapabilityReport:
        _capabilities, report = JakaKargoCapabilityMapper(
            self.transport, self.config
        ).map()
        return report

    def observe(self) -> RobotState:
        return self.state_provider.observe()

    def acquire(self, fields: set[str]) -> RobotState:
        # The legacy state services do not support field batching.  Re-querying all
        # sources is conservative and preserves a coherent timestamped snapshot.
        return self.observe()

    @staticmethod
    def _receipt(result: TransportResult) -> CommandReceipt:
        return CommandReceipt(
            accepted=result.accepted,
            backend_message=result.message,
            call_result=result.call_result,
            timed_out=result.timed_out,
        )

    def _admission_failure(self, skill_name: str) -> CommandReceipt | None:
        if not self.capabilities().supports(skill_name):
            return CommandReceipt(
                False,
                f"capability preflight: JAKA/Kargo backend does not guarantee {skill_name}",
            )
        state = self.observe()
        evidence = state.epistemic_value(
            "emergency_stop", max_age_s=self.config.observation_max_age_s
        )
        if evidence.status is not KnowledgeStatus.KNOWN:
            return CommandReceipt(
                False,
                f"command admission blocked: whole-robot emergency-stop evidence is "
                f"{evidence.status.value}",
            )
        if evidence.value is True:
            return CommandReceipt(False, "command admission blocked: emergency stop is active")
        if state.fault:
            return CommandReceipt(False, f"command admission blocked: {state.fault}")
        return None

    def command(self, skill_name: str, arguments: dict[str, Any]) -> CommandReceipt:
        if skill_name == "safe_stop":
            return self.stop()
        blocked = self._admission_failure(skill_name)
        if blocked is not None:
            return blocked
        timeout = self.config.service_timeout_s
        try:
            if skill_name == "retract_arm":
                if self.config.arm_command_scope is ArmCommandScope.LEGACY_BILATERAL_PRESET:
                    # A direct call must not bypass the same semantic mismatch that
                    # the core capability preflight rejects.
                    return CommandReceipt(
                        False,
                        "semantic mismatch: legacy bilateral preset cannot implement "
                        "single-arm retract contract",
                    )
                arm = str(arguments["arm"])
                target = self.config.arm_target(arm)
                if target is None:
                    return CommandReceipt(False, "calibrated transport target is unavailable")
                result = self.transport.move_arm_joints(
                    0 if arm == "left" else 1,
                    target,
                    self.config.arm_velocity_rad_s,
                    self.config.arm_acceleration_rad_s2,
                    timeout,
                )
                return self._receipt(result)

            if skill_name == "set_lift":
                result = self.transport.move_external_axis(
                    0,
                    float(arguments["height_mm"]),
                    self.config.external_axis_velocity,
                    self.config.external_axis_acceleration,
                    timeout,
                )
                return self._receipt(result)

            if skill_name == "set_waist":
                result = self.transport.move_external_axis(
                    1,
                    float(arguments["angle_deg"]),
                    self.config.external_axis_velocity,
                    self.config.external_axis_acceleration,
                    timeout,
                )
                return self._receipt(result)

            if skill_name == "set_head":
                completed: list[str] = []
                if "yaw_deg" in arguments:
                    yaw_result = self.transport.move_external_axis(
                        2,
                        float(arguments["yaw_deg"]),
                        self.config.external_axis_velocity,
                        self.config.external_axis_acceleration,
                        timeout,
                    )
                    if not yaw_result.accepted:
                        return self._receipt(yaw_result)
                    completed.append("yaw")
                if "pitch_deg" in arguments:
                    pitch_result = self.transport.move_external_axis(
                        3,
                        -float(arguments["pitch_deg"]),
                        self.config.external_axis_velocity,
                        self.config.external_axis_acceleration,
                        timeout,
                    )
                    if not pitch_result.accepted:
                        prefix = "partial effect (yaw already accepted); " if completed else ""
                        return CommandReceipt(
                            False,
                            prefix + pitch_result.message,
                            pitch_result.call_result,
                            pitch_result.timed_out,
                        )
                    completed.append("pitch")
                return CommandReceipt(True, f"legacy services accepted head axes: {completed}")

            if skill_name == "move_agv":
                before = self.observe()
                evidence = before.epistemic_value(
                    "agv_position_m", max_age_s=self.config.observation_max_age_s
                )
                if evidence.status is not KnowledgeStatus.KNOWN:
                    return CommandReceipt(
                        False,
                        f"AGV odometry x is {evidence.status.value}; target cannot be grounded",
                    )
                target = float(evidence.value) + float(arguments["distance_m"])
                result = self.transport.navigate_agv_x(
                    target,
                    float(arguments.get("speed_mps", 0.2)),
                    self.config.agv_map_name,
                    timeout,
                )
                return self._receipt(result)

            return CommandReceipt(False, f"JAKA/Kargo adapter does not implement {skill_name}")
        except TimeoutError as exc:
            return CommandReceipt(False, str(exc), timed_out=True)
        except Exception as exc:
            return CommandReceipt(False, f"JAKA/Kargo adapter error: {exc}")

    def stop(self) -> CommandReceipt:
        try:
            result = self.transport.stop_agv(self.config.service_timeout_s)
        except Exception as exc:
            return CommandReceipt(False, f"AGV stop attempt failed: {exc}")
        return CommandReceipt(
            False,
            f"AGV-only stop attempt: {result.message}; whole-robot stop remains unverified",
            result.call_result,
            result.timed_out,
        )

    def close(self) -> None:
        self.transport.close()
