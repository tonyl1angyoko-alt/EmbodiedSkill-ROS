from __future__ import annotations

import json
import math
from typing import Callable

from ..models.task_plan import TaskPlan
from ..skills.registry import SkillRegistry


def _reject_non_finite_constant(value: str):
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _validate_finite_json(value) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON number is not allowed")
    if isinstance(value, dict):
        for item in value.values():
            _validate_finite_json(item)
    elif isinstance(value, list):
        for item in value:
            _validate_finite_json(item)


class LLMPlannerAdapter:
    """Provider-neutral adapter. The injected callable returns JSON; no API dependency or secret handling here."""

    def __init__(self, completion_fn: Callable[[str, tuple[str, ...]], str], registry: SkillRegistry):
        self.completion_fn = completion_fn
        self.registry = registry

    def plan(self, instruction: str) -> TaskPlan:
        raw = self.completion_fn(instruction, tuple(sorted(self.registry.names())))
        data = json.loads(raw, parse_constant=_reject_non_finite_constant)
        _validate_finite_json(data)
        plan = TaskPlan.from_dict(data)
        unknown = {s.skill for s in plan.steps} - self.registry.names()
        if unknown:
            raise ValueError(f"LLM emitted unregistered skills: {sorted(unknown)}")
        return plan
