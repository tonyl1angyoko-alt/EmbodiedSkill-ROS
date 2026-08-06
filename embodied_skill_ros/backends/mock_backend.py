from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from .base_backend import RobotBackend
from ..models.robot_state import RobotState
from ..models.skill_result import CommandReceipt


@dataclass(frozen=True)
class FaultEvent:
    mode: str
    message: str = "injected fault"
    drift: dict[str, Any] | None = None


class MockRobotBackend(RobotBackend):
    """Deterministic backend with explicit command/physics fault injection."""

    def __init__(self, initial_state: RobotState | None = None):
        self._state = initial_state or RobotState(
            left_arm_ready=True, right_arm_ready=True,
            left_arm_safe=True, right_arm_safe=True,
            agv_ready=True, agv_moving=False, agv_position_m=0.0,
            lift_ready=True, lift_height_mm=100.0,
            head_ready=True, head_yaw_deg=0.0, head_pitch_deg=0.0,
            emergency_stop=False,
        )
        self._faults: dict[str, deque[FaultEvent]] = defaultdict(deque)
        self.command_log: list[tuple[str, dict[str, Any]]] = []

    @property
    def supported_skills(self) -> frozenset[str]:
        return frozenset({"retract_arm", "extend_arm", "move_agv", "set_lift", "set_head"})

    def inject(self, skill_name: str, *events: FaultEvent) -> None:
        self._faults[skill_name].extend(events)

    def observe(self) -> RobotState:
        return self._state.copy()

    def set_state(self, **changes: Any) -> None:
        self._state = self._state.copy(**changes)

    def command(self, skill_name: str, arguments: dict[str, Any]) -> CommandReceipt:
        self.command_log.append((skill_name, dict(arguments)))
        event = self._faults[skill_name].popleft() if self._faults[skill_name] else None
        if event and event.drift:
            self.set_state(**event.drift)
        if event and event.mode == "timeout":
            return CommandReceipt(False, event.message, timed_out=True)
        if event and event.mode == "command_failure":
            return CommandReceipt(False, event.message)
        if event and event.mode in {"physical_failure", "state_drift"}:
            return CommandReceipt(True, event.message)

        # The benchmark models a lower-level motion controller that accepts the
        # request but inhibits unsafe body motion. This deliberately exposes the
        # difference between a command receipt and a physical outcome.
        if skill_name in {"move_agv", "set_lift"} and (
            self._state.left_arm_safe is not True or self._state.right_arm_safe is not True
        ):
            return CommandReceipt(True, "mock command accepted; motion inhibited until both arms are transport-safe")

        if skill_name == "retract_arm":
            arm = arguments["arm"]
            self.set_state(**{f"{arm}_arm_safe": True, f"{arm}_arm_ready": True})
        elif skill_name == "extend_arm":
            arm = arguments["arm"]
            self.set_state(**{f"{arm}_arm_safe": False, f"{arm}_arm_ready": True})
        elif skill_name == "move_agv":
            pos = self._state.agv_position_m
            self.set_state(agv_moving=False,
                           agv_position_m=None if pos is None else pos + float(arguments["distance_m"]))
        elif skill_name == "set_lift":
            self.set_state(lift_height_mm=float(arguments["height_mm"]))
        elif skill_name == "set_head":
            changes = {}
            if "yaw_deg" in arguments:
                changes["head_yaw_deg"] = float(arguments["yaw_deg"])
            if "pitch_deg" in arguments:
                changes["head_pitch_deg"] = float(arguments["pitch_deg"])
            self.set_state(**changes)
        elif skill_name == "safe_stop":
            self.set_state(agv_moving=False, active_resources=set())
        else:
            return CommandReceipt(False, f"mock backend does not implement {skill_name}")
        return CommandReceipt(True, "mock command accepted")
