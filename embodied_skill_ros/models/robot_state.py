from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class KnowledgeStatus(str, Enum):
    """Whether a state value is usable as current evidence."""

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"
    CONTRADICTORY = "CONTRADICTORY"


@dataclass(frozen=True)
class EpistemicValue:
    field: str
    value: Any
    status: KnowledgeStatus
    observed_at: str | None = None

    @property
    def usable_value(self) -> Any:
        return self.value if self.status is KnowledgeStatus.KNOWN else None


@dataclass
class RobotState:
    """Observable robot state. ``None`` means UNKNOWN, never an assumed value."""

    left_arm_ready: bool | None = None
    right_arm_ready: bool | None = None
    left_arm_safe: bool | None = None
    right_arm_safe: bool | None = None
    agv_ready: bool | None = None
    agv_moving: bool | None = None
    agv_position_m: float | None = None
    lift_ready: bool | None = None
    lift_height_mm: float | None = None
    head_ready: bool | None = None
    head_yaw_deg: float | None = None
    head_pitch_deg: float | None = None
    active_resources: set[str] = field(default_factory=set)
    emergency_stop: bool | None = None
    fault: str | None = None
    last_skill_result: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    observed_at: dict[str, str] = field(default_factory=dict)
    stale_fields: set[str] = field(default_factory=set)
    conflicts: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def copy(self, **changes: Any) -> "RobotState":
        """Copy a snapshot without making old evidence look newly observed.

        Unknown keys are stored in ``facts`` so deployments can add state facts
        without modifying this core dataclass.
        """

        field_names = {item.name for item in fields(self)}
        dynamic = {key: changes.pop(key) for key in list(changes) if key not in field_names}
        changes.setdefault("active_resources", set(self.active_resources))
        changes.setdefault("facts", {**self.facts, **dynamic})
        changes.setdefault("observed_at", dict(self.observed_at))
        changes.setdefault("stale_fields", set(self.stale_fields))
        changes.setdefault("conflicts", dict(self.conflicts))
        return replace(self, **changes)

    def raw_value(self, name: str) -> Any:
        return getattr(self, name) if hasattr(self, name) else self.facts.get(name)

    def epistemic_value(self, name: str, *, max_age_s: float | None = None,
                        now: datetime | None = None) -> EpistemicValue:
        value = self.raw_value(name)
        observed_at = self.observed_at.get(name, self.timestamp)
        if name in self.conflicts and len(set(map(repr, self.conflicts[name]))) > 1:
            return EpistemicValue(
                name, value, KnowledgeStatus.CONTRADICTORY, observed_at
            )
        if value is None:
            return EpistemicValue(name, None, KnowledgeStatus.UNKNOWN, observed_at)
        if name in self.stale_fields:
            return EpistemicValue(name, value, KnowledgeStatus.STALE, observed_at)
        if max_age_s is not None:
            try:
                observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
                reference = now or datetime.now(timezone.utc)
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
                if (reference - observed).total_seconds() > max_age_s:
                    return EpistemicValue(name, value, KnowledgeStatus.STALE, observed_at)
            except (AttributeError, TypeError, ValueError):
                return EpistemicValue(name, value, KnowledgeStatus.STALE, observed_at)
        return EpistemicValue(name, value, KnowledgeStatus.KNOWN, observed_at)

    def with_observation_time(self, names: set[str] | None = None,
                              observed_at: str | None = None) -> "RobotState":
        stamp = observed_at or datetime.now(timezone.utc).isoformat()
        names = names or {
            item.name for item in fields(self)
            if item.name not in {
                "facts", "observed_at", "stale_fields", "conflicts", "timestamp"
            }
            and self.raw_value(item.name) is not None
        } | {name for name, value in self.facts.items() if value is not None}
        times = dict(self.observed_at)
        times.update({name: stamp for name in names})
        return self.copy(timestamp=stamp, observed_at=times)

    def mark_stale(self, *names: str) -> "RobotState":
        return self.copy(stale_fields=self.stale_fields | set(names))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["active_resources"] = sorted(self.active_resources)
        data["stale_fields"] = sorted(self.stale_fields)
        data["conflicts"] = {
            key: list(values) for key, values in sorted(self.conflicts.items())
        }
        return data
