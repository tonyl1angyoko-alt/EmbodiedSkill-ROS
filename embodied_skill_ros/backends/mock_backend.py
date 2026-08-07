from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import Any, Callable

from .base_backend import BackendCapabilities, RobotBackend, SkillSemantics
from ..models.robot_state import RobotState
from ..models.skill_result import CommandReceipt


@dataclass(frozen=True)
class FaultEvent:
    mode: str
    message: str = "injected fault"
    drift: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        allowed = {"timeout", "command_failure", "physical_failure", "state_drift"}
        if self.mode not in allowed:
            raise ValueError(f"unsupported fault mode: {self.mode}")


@dataclass(frozen=True)
class ObservationModel:
    """Deterministic sensor boundary, deliberately separate from world truth."""

    hidden_fields: frozenset[str] = frozenset()
    stale_fields: frozenset[str] = frozenset()
    overrides: tuple[tuple[str, Any], ...] = ()
    refreshable_fields: frozenset[str] = frozenset()
    refresh_failures: tuple[tuple[str, int], ...] = ()
    contradictions: tuple[tuple[str, tuple[Any, ...]], ...] = ()


TransitionHandler = Callable[[RobotState, dict[str, Any]], dict[str, Any]]


class MockRobotBackend(RobotBackend):
    """Deterministic hidden world with explicit command and sensor faults."""

    def __init__(self, initial_state: RobotState | None = None,
                 observation_model: ObservationModel | None = None):
        self._world = initial_state or RobotState(
            left_arm_ready=True, right_arm_ready=True,
            left_arm_safe=True, right_arm_safe=True,
            agv_ready=True, agv_moving=False, agv_position_m=0.0,
            lift_ready=True, lift_height_mm=100.0,
            head_ready=True, head_yaw_deg=0.0, head_pitch_deg=0.0,
            emergency_stop=False,
        )
        self.observation_model = observation_model or ObservationModel()
        self._faults: dict[str, deque[FaultEvent]] = defaultdict(deque)
        self._permanent_faults: dict[str, FaultEvent] = {}
        self._handlers: dict[str, TransitionHandler] = {}
        self._semantics: dict[str, SkillSemantics] = {}
        self._acquisition_attempts: dict[str, int] = defaultdict(int)
        self.command_log: list[tuple[str, dict[str, Any]]] = []

    def capabilities(self) -> BackendCapabilities:
        state_fields = {
            item.name for item in fields(RobotState)
            if item.name not in {
                "facts", "observed_at", "stale_fields", "conflicts", "timestamp"
            }
        } | set(self._world.facts)
        state_fields -= (
            set(self.observation_model.hidden_fields)
            - set(self.observation_model.refreshable_fields)
        )
        builtins = {
            "retract_arm", "extend_arm", "move_agv", "set_lift", "set_head", "safe_stop"
        }
        return BackendCapabilities(
            backend_name="MockRobotBackend",
            supported_skills=frozenset(builtins | set(self._handlers)),
            observable_fields=frozenset(state_fields),
            supports_safe_stop=True,
            runtime="deterministic-mock",
            refreshable_fields=self.observation_model.refreshable_fields,
            skill_semantics=tuple(self._semantics.values()),
        )

    def register_handler(self, skill_name: str, handler: TransitionHandler,
                         semantics: SkillSemantics | None = None) -> None:
        self._handlers[skill_name] = handler
        if semantics is not None:
            self._semantics[skill_name] = semantics

    def inject(self, skill_name: str, *events: FaultEvent) -> None:
        self._faults[skill_name].extend(events)

    def inject_permanent(self, skill_name: str, event: FaultEvent) -> None:
        self._permanent_faults[skill_name] = event

    def clear_permanent_fault(self, skill_name: str) -> None:
        self._permanent_faults.pop(skill_name, None)

    def oracle_state(self) -> RobotState:
        """Hidden physical truth; execution code must use ``observe`` instead."""

        return self._world.copy()

    def observe(self) -> RobotState:
        stamp = datetime.now(timezone.utc).isoformat()
        observed = self._world.copy(timestamp=stamp)
        failures = dict(self.observation_model.refresh_failures)

        def still_unavailable(name: str) -> bool:
            if name not in self.observation_model.refreshable_fields:
                return True
            return self._acquisition_attempts[name] <= failures.get(name, 0)

        hidden = {
            name for name in self.observation_model.hidden_fields if still_unavailable(name)
        }
        stale = {
            name for name in self.observation_model.stale_fields if still_unavailable(name)
        }
        changes = {name: None for name in hidden}
        changes.update(dict(self.observation_model.overrides))
        observed = observed.copy(
            **changes,
            conflicts=dict(self.observation_model.contradictions),
        )
        visible = {
            item.name for item in fields(RobotState)
            if item.name not in {
                "facts", "observed_at", "stale_fields", "conflicts", "timestamp"
            }
            and item.name not in hidden
            and observed.raw_value(item.name) is not None
        } | {
            name for name, value in observed.facts.items()
            if name not in hidden and value is not None
        }
        return observed.with_observation_time(visible, stamp).copy(
            stale_fields=stale
        )

    def acquire(self, fields: set[str]) -> RobotState:
        for name in fields:
            self._acquisition_attempts[name] += 1
        return self.observe()

    def set_state(self, **changes: Any) -> None:
        self._world = self._world.copy(
            **changes, timestamp=datetime.now(timezone.utc).isoformat()
        )

    def command(self, skill_name: str, arguments: dict[str, Any]) -> CommandReceipt:
        self.command_log.append((skill_name, dict(arguments)))
        event = (
            self._faults[skill_name].popleft()
            if self._faults[skill_name]
            else self._permanent_faults.get(skill_name)
        )
        if event and event.drift:
            self.set_state(**event.drift)
        if event and event.mode == "timeout":
            return CommandReceipt(False, event.message, timed_out=True)
        if event and event.mode == "command_failure":
            return CommandReceipt(False, event.message)
        if event and event.mode in {"physical_failure", "state_drift"}:
            return CommandReceipt(True, event.message)

        if skill_name in {"move_agv", "set_lift"} and (
            self._world.left_arm_safe is not True or self._world.right_arm_safe is not True
        ):
            return CommandReceipt(
                True,
                "mock command accepted; motion inhibited until both arms are transport-safe",
            )

        if skill_name in self._handlers:
            self.set_state(**self._handlers[skill_name](self.oracle_state(), dict(arguments)))
        elif skill_name == "retract_arm":
            arm = arguments["arm"]
            self.set_state(**{f"{arm}_arm_safe": True, f"{arm}_arm_ready": True})
        elif skill_name == "extend_arm":
            arm = arguments["arm"]
            self.set_state(**{f"{arm}_arm_safe": False, f"{arm}_arm_ready": True})
        elif skill_name == "move_agv":
            pos = self._world.agv_position_m
            self.set_state(
                agv_moving=False,
                agv_position_m=None if pos is None else pos + float(arguments["distance_m"]),
            )
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
