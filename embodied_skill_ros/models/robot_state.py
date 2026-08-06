from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Any


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
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def copy(self, **changes: Any) -> "RobotState":
        changes.setdefault("active_resources", set(self.active_resources))
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["active_resources"] = sorted(self.active_resources)
        return data
