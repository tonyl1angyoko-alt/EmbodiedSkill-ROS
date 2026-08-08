from __future__ import annotations

from dataclasses import fields
from typing import Any

from ..models.robot_state import RobotState


_CONTAINER_FIELDS = {
    "active_resources",
    "facts",
    "observed_at",
    "stale_fields",
    "conflicts",
}
_ROBOT_STATE_FIELDS = {item.name for item in fields(RobotState)}


def robot_state_from_dict(payload: dict[str, Any]) -> RobotState:
    """Decode a JSON-compatible state without making its evidence fresh again."""

    values = {key: value for key, value in payload.items() if key in _ROBOT_STATE_FIELDS}
    values["active_resources"] = set(values.get("active_resources", ()))
    values["stale_fields"] = set(values.get("stale_fields", ()))
    values["observed_at"] = dict(values.get("observed_at", {}))
    values["facts"] = dict(values.get("facts", {}))
    values["conflicts"] = {
        key: tuple(items) for key, items in dict(values.get("conflicts", {})).items()
    }
    return RobotState(**values)


def robot_state_field_names() -> frozenset[str]:
    return frozenset(_ROBOT_STATE_FIELDS - _CONTAINER_FIELDS - {"timestamp"})
