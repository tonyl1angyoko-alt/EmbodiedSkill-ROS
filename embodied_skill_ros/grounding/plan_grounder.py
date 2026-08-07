from __future__ import annotations

from dataclasses import dataclass, field

from .constraint_checker import ConstraintChecker
from ..backends.base_backend import BackendCapabilities
from ..models.robot_state import RobotState
from ..models.robot_state import KnowledgeStatus
from ..models.task_plan import TaskPlan
from ..skills.base_skill import ParameterError, RobotSkill
from ..skills.registry import SkillRegistry


@dataclass(frozen=True)
class GroundingIssue:
    code: str
    step_id: str
    message: str
    repairable: bool = True
    field: str | None = None
    knowledge: KnowledgeStatus | None = None


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

    def ground(self, plan: TaskPlan, state: RobotState,
               capabilities: BackendCapabilities | None = None) -> GroundingReport:
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
            if capabilities is not None and not capabilities.supports(step.skill):
                issues.append(GroundingIssue(
                    "BACKEND_SKILL_UNSUPPORTED", step.id,
                    f"backend {capabilities.backend_name} does not support {step.skill}", False,
                ))
                continue
            try:
                skill.validate_arguments(step.arguments)
            except (ParameterError, TypeError, ValueError) as exc:
                issues.append(GroundingIssue("INVALID_ARGUMENTS", step.id, str(exc), False))
                continue
            for evaluation in skill.evaluate_preconditions(simulated, step.arguments):
                if not evaluation.satisfied:
                    issues.append(GroundingIssue(
                        evaluation.code, step.id, evaluation.message, True,
                        evaluation.field, evaluation.knowledge,
                    ))
            for item in self.checker.check_step(step, skill, simulated):
                issues.append(GroundingIssue(item.code, item.step_id, item.message, item.repairable))
            effects = skill.expected_effects(step.arguments, simulated)
            for key, value in effects.items():
                if value is None:
                    issues.append(GroundingIssue(
                        "UNPROJECTABLE_EFFECT", step.id,
                        f"cannot predict or verify {key} from UNKNOWN prior state", False,
                    ))
            if capabilities is not None:
                semantics = capabilities.semantics_for(step.skill)
                if semantics is not None:
                    allowed_effects = set(effects) | set(
                        skill.contract.allowed_backend_side_effects
                    )
                    for reason in semantics.validate(step.arguments, allowed_effects):
                        issues.append(GroundingIssue(
                            "BACKEND_SEMANTIC_MISMATCH", step.id, reason, False,
                        ))
                for key in effects:
                    if not capabilities.can_observe(key):
                        issues.append(GroundingIssue(
                            "BACKEND_EFFECT_UNOBSERVABLE", step.id,
                            f"backend {capabilities.backend_name} cannot observe {key}", False,
                            key,
                        ))
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
        groups: dict[str, list[PlanStep]] = {}
        for step in plan.steps:
            if step.parallel_group:
                groups.setdefault(step.parallel_group, []).append(step)
        for group_steps in groups.values():
            effects_by_field: dict[str, tuple[object, str]] = {}
            for step in group_steps:
                try:
                    skill = self.registry.get(step.skill)
                    effects = skill.expected_effects(step.arguments, state)
                except (KeyError, TypeError, ValueError):
                    continue
                for field_name, target in effects.items():
                    previous = effects_by_field.get(field_name)
                    if previous is not None and previous[0] != target:
                        issues.append(GroundingIssue(
                            "PARALLEL_EFFECT_CONFLICT", step.id,
                            f"parallel steps require incompatible {field_name} values: "
                            f"{previous[0]!r} vs {target!r}", False, field_name,
                        ))
                    else:
                        effects_by_field[field_name] = (target, step.id)
        # De-duplicate equivalent diagnostics while preserving order.
        unique = list(dict.fromkeys(issues))
        return GroundingReport(not unique, unique)
