from __future__ import annotations

import json
from typing import Callable

from ..models.task_plan import TaskPlan
from ..skills.registry import SkillRegistry


class LLMPlannerAdapter:
    """Provider-neutral adapter. The injected callable returns JSON; no API dependency or secret handling here."""

    def __init__(self, completion_fn: Callable[[str, tuple[str, ...]], str], registry: SkillRegistry):
        self.completion_fn = completion_fn
        self.registry = registry

    def plan(self, instruction: str) -> TaskPlan:
        raw = self.completion_fn(instruction, tuple(sorted(self.registry.names())))
        plan = TaskPlan.from_dict(json.loads(raw))
        unknown = {s.skill for s in plan.steps} - self.registry.names()
        if unknown:
            raise ValueError(f"LLM emitted unregistered skills: {sorted(unknown)}")
        return plan
