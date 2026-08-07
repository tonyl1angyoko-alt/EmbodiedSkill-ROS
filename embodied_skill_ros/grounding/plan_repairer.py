from __future__ import annotations

from dataclasses import replace
from typing import Any

from .plan_grounder import GroundingReport
from ..models.robot_state import KnowledgeStatus, RobotState
from ..models.task_plan import PlanStep, TaskPlan
from ..skills.registry import SkillRegistry, build_default_registry


class PlanRepairer:
    """Bounded backward search over declared preconditions and effects."""

    def __init__(self, registry: SkillRegistry | None = None, max_insertions: int = 16,
                 max_depth: int = 6, max_expansions: int = 64):
        self.registry = registry or build_default_registry()
        self.max_insertions = max_insertions
        self.max_depth = max_depth
        self.max_expansions = max_expansions
        self.last_search_stats: dict[str, int] = {}

    @staticmethod
    def _fact_satisfied(state: RobotState, field: str, target: Any) -> bool:
        evidence = state.epistemic_value(field)
        return evidence.status is KnowledgeStatus.KNOWN and evidence.value == target

    def _search(self, field: str, target: Any, state: RobotState,
                path: frozenset[tuple[str, str]], depth: int,
                excluded_skills: frozenset[str]) -> tuple[list[PlanStep], RobotState] | None:
        if self._fact_satisfied(state, field, target):
            return [], state
        key = (field, repr(target))
        if key in path:
            self.last_search_stats["cycles"] += 1
            return None
        if depth > self.max_depth:
            self.last_search_stats["depth_limit_hits"] += 1
            return None
        if self.last_search_stats["expanded"] >= self.max_expansions:
            self.last_search_stats["expansion_limit_hits"] += 1
            return None
        self.last_search_stats["expanded"] += 1
        candidates = self.registry.synthesize_candidates(
            field, target, state, "candidate", "PlanRepairer:effect-search",
            excluded_skills,
        )
        best: tuple[list[PlanStep], RobotState] | None = None
        for candidate in candidates:
            self.last_search_stats["candidates_considered"] += 1
            skill = self.registry.get(candidate.skill)
            projected = state
            prefix: list[PlanStep] = []
            possible = True
            for failure in skill.evaluate_preconditions(projected, candidate.arguments):
                if failure.satisfied:
                    continue
                nested = self._search(
                    failure.field, failure.expected, projected,
                    path | {key}, depth + 1, excluded_skills,
                )
                if nested is None:
                    possible = False
                    break
                nested_steps, projected = nested
                prefix.extend(nested_steps)
            if not possible or skill.check_preconditions(projected, candidate.arguments):
                continue
            projected = projected.copy(**skill.expected_effects(candidate.arguments, projected))
            if not self._fact_satisfied(projected, field, target):
                continue
            proposal = (prefix + [candidate], projected)
            if best is None or len(proposal[0]) < len(best[0]):
                best = proposal
        return best

    def repair(self, plan: TaskPlan, state: RobotState,
               report: GroundingReport) -> TaskPlan | None:
        self.last_search_stats = {
            "expanded": 0,
            "candidates_considered": 0,
            "cycles": 0,
            "depth_limit_hits": 0,
            "expansion_limit_hits": 0,
            "selected_steps": 0,
        }
        if report.requires_stop:
            return None
        excluded_skills = frozenset(plan.metadata.get("blocked_skills", ()))
        new_steps: list[PlanStep] = []
        projected = state.copy()
        repaired_goals = {}
        serial = 0
        for original in plan.steps:
            try:
                skill = self.registry.get(original.skill)
            except KeyError:
                return None
            for failure in skill.evaluate_preconditions(projected, original.arguments):
                if failure.satisfied:
                    continue
                search_start = projected
                result = self._search(
                    failure.field, failure.expected, projected,
                    frozenset(), 1, excluded_skills,
                )
                if result is None:
                    return None
                repairs, final_projected = result
                replayed = search_start
                for repair in repairs:
                    serial += 1
                    if serial > self.max_insertions:
                        return None
                    repair = replace(
                        repair,
                        id=f"repair_{serial}_{failure.field}",
                        inserted_by=f"PlanRepairer:{failure.code}",
                    )
                    repair_skill = self.registry.get(repair.skill)
                    effects = repair_skill.expected_effects(repair.arguments, replayed)
                    repaired_goals.update({
                        key: value for key, value in effects.items() if value is not None
                    })
                    new_steps.append(repair)
                    replayed = replayed.copy(**effects)
                projected = final_projected
                self.last_search_stats["selected_steps"] += len(repairs)
            step = replace(original, parallel_group=None)
            if skill.check_preconditions(projected, step.arguments):
                return None
            new_steps.append(step)
            effects = skill.expected_effects(step.arguments, projected)
            repaired_goals.update({key: value for key, value in effects.items() if value is not None})
            projected = projected.copy(**effects)
        metadata = {
            **plan.metadata,
            "repaired": True,
            "repair_strategy": "bounded-declarative-effect-search",
            "repair_search": dict(self.last_search_stats),
        }
        if metadata.get("goal_state_source") == "projected_plan":
            metadata["goal_state"] = repaired_goals
        return TaskPlan(
            plan.goal, new_steps, plan.plan_id, plan.revision + 1, metadata,
        )
