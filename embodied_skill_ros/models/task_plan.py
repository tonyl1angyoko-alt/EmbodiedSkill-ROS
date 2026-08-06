from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PlanStep:
    id: str
    skill: str
    arguments: dict[str, Any] = field(default_factory=dict)
    expected_effect: dict[str, Any] = field(default_factory=dict)
    parallel_group: str | None = None
    inserted_by: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanStep":
        if not isinstance(data, dict):
            raise TypeError("plan step must be an object")
        if not isinstance(data.get("id"), str) or not data["id"]:
            raise ValueError("plan step requires a non-empty string id")
        if not isinstance(data.get("skill"), str) or not data["skill"]:
            raise ValueError("plan step requires a non-empty string skill")
        args = data.get("arguments", {})
        if not isinstance(args, dict):
            raise TypeError("arguments must be an object")
        effect = data.get("expected_effect", {})
        if not isinstance(effect, dict):
            raise TypeError("expected_effect must be an object")
        return cls(data["id"], data["skill"], args, effect,
                   data.get("parallel_group"), data.get("inserted_by"))


@dataclass
class TaskPlan:
    goal: str
    steps: list[PlanStep]
    plan_id: str = "plan_1"
    revision: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskPlan":
        if not isinstance(data, dict):
            raise TypeError("plan must be an object")
        goal = data.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("plan requires a non-empty goal")
        raw_steps = data.get("steps")
        if not isinstance(raw_steps, list):
            raise TypeError("steps must be a list")
        if not raw_steps:
            raise ValueError("plan requires at least one executable step")
        return cls(goal, [PlanStep.from_dict(s) for s in raw_steps],
                   str(data.get("plan_id", "plan_1")), int(data.get("revision", 0)),
                   dict(data.get("metadata", {})))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
