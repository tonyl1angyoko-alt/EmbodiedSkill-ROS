from __future__ import annotations

import json
import inspect
import math
from typing import Any, Callable

from ..models.robot_state import RobotState
from ..models.task_plan import TaskPlan
from ..skills.base_skill import ParameterSpec
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


def _parameter_type(spec: ParameterSpec) -> str:
    types = spec.python_type if isinstance(spec.python_type, tuple) else (spec.python_type,)
    if set(types) <= {int, float}:
        return "number"
    if types == (str,):
        return "string"
    if types == (bool,):
        return "boolean"
    return "object"


def _skill_schema(registry: SkillRegistry) -> tuple[dict[str, Any], ...]:
    schema = []
    for skill in sorted(registry, key=lambda item: item.name):
        parameters = {}
        for name, spec in skill.parameter_schema.items():
            item = {"type": _parameter_type(spec), "required": spec.required}
            if spec.minimum is not None:
                item["minimum"] = spec.minimum
            if spec.maximum is not None:
                item["maximum"] = spec.maximum
            if spec.choices:
                item["choices"] = list(spec.choices)
            parameters[name] = item
        schema.append({
            "name": skill.name,
            "description": skill.description,
            "parameters": parameters,
            "required_resources": sorted(skill.required_resources),
            "timeout_s": skill.timeout,
        })
    return tuple(schema)


class LLMPlannerAdapter:
    """Provider-neutral adapter. The injected callable returns JSON; no API dependency or secret handling here."""

    def __init__(self, completion_fn: Callable[..., str], registry: SkillRegistry):
        self.completion_fn = completion_fn
        self.registry = registry

    def plan(self, instruction: str, state: RobotState | None = None) -> TaskPlan:
        schema = _skill_schema(self.registry)
        try:
            parameters = inspect.signature(self.completion_fn).parameters.values()
            positional = [
                item for item in parameters
                if item.kind in (item.POSITIONAL_ONLY, item.POSITIONAL_OR_KEYWORD)
            ]
            accepts_state = (
                len(positional) >= 3
                or any(item.kind is item.VAR_POSITIONAL for item in parameters)
            )
        except (TypeError, ValueError):
            accepts_state = False
        if accepts_state:
            raw = self.completion_fn(
                instruction, state.to_dict() if state is not None else None, schema
            )
        else:
            raw = self.completion_fn(instruction, schema)
        data = json.loads(raw, parse_constant=_reject_non_finite_constant)
        _validate_finite_json(data)
        plan = TaskPlan.from_dict(data)
        unknown = {s.skill for s in plan.steps} - self.registry.names()
        if unknown:
            raise ValueError(f"LLM emitted unregistered skills: {sorted(unknown)}")
        return plan
