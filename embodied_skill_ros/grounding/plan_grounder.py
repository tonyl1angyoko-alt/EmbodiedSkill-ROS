from __future__ import annotations

from dataclasses import dataclass, field

from .constraint_checker import ConstraintChecker
from ..models.robot_state import RobotState
from ..models.task_plan import TaskPlan
from ..skills.base_skill import ParameterError, RobotSkill
from ..skills.registry import SkillRegistry


@dataclass(frozen=True)
class GroundingIssue:
    code: str
    step_id: str
    message: str
    repairable: bool = True


@dataclass
class GroundingReport:
    valid: bool
    issues: list[GroundingIssue] = field(default_factory=list)

    @property
    def requires_stop(self) -> bool:
        return any(not i.repairable for i in self.issues)


class EmbodiedPlanGrounder:
    def __init__(self, registry: SkillRegistry, checker: ConstraintChecker | None = None):
        self.registry = registry
        self.checker = checker or ConstraintChecker()

    def ground(self, plan: TaskPlan, state: RobotState) -> GroundingReport:
        issues: list[GroundingIssue] = []
        seen: set[str] = set()
        skill_map: dict[str, RobotSkill] = {}
        simulated = state.copy()
        for step in plan.steps:
            if step.id in seen:
                issues.append(GroundingIssue("DUPLICATE_STEP_ID", step.id, "step id is duplicated", False))
            seen.add(step.id)
            try:
                skill = self.registry.get(step.skill)
            except KeyError as exc:
                issues.append(GroundingIssue("UNKNOWN_SKILL", step.id, str(exc), False))
                continue
            skill_map[step.skill] = skill
            try:
                skill.validate_arguments(step.arguments)
            except (ParameterError, TypeError, ValueError) as exc:
                issues.append(GroundingIssue("INVALID_ARGUMENTS", step.id, str(exc), False))
                continue
            for label in skill.check_preconditions(simulated, step.arguments):
                issues.append(GroundingIssue("PRECONDITION", step.id, label))
            for item in self.checker.check_step(step, skill, simulated):
                issues.append(GroundingIssue(item.code, item.step_id, item.message, item.repairable))
            effects = skill.expected_effects(step.arguments, simulated)
            for key, declared in step.expected_effect.items():
                if key not in effects:
                    issues.append(GroundingIssue(
                        "UNVERIFIABLE_EXPECTED_EFFECT", step.id,
                        f"skill {step.skill} cannot verify declared effect {key!r}", False,
                    ))
                elif effects[key] != declared:
                    issues.append(GroundingIssue(
                        "EXPECTED_EFFECT_MISMATCH", step.id,
                        f"declared {key}={declared!r}, skill predicts {effects[key]!r}", False,
                    ))
            # Planning projection is used only for ordering; UNKNOWN expected values remain UNKNOWN.
            simulated = simulated.copy(**effects)
        for item in self.checker.check_parallel(plan.steps, skill_map):
            issues.append(GroundingIssue(item.code, item.step_id, item.message, item.repairable))
        # De-duplicate equivalent diagnostics while preserving order.
        unique = list(dict.fromkeys(issues))
        return GroundingReport(not unique, unique)
