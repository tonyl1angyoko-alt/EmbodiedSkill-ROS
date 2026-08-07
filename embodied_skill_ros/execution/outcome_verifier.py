from __future__ import annotations

import math

from ..models.evidence import EvidenceRequirement, PhysicalEvidence
from ..models.freshness import StateFreshnessPolicy
from ..models.robot_state import RobotState
from ..models.skill_result import VerificationResult
from ..skills.base_skill import RobotSkill


def _is_finite_number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _missing_requirement(field: str, target, after: RobotState,
                         freshness_policy: StateFreshnessPolicy) -> PhysicalEvidence:
    freshness = freshness_policy.evaluate(after.timestamp, None)
    return PhysicalEvidence(
        source="robot_state",
        state_field=field,
        measured_at=after.timestamp,
        received_at=freshness.evaluated_at,
        observed_value=getattr(after, field, None),
        expected_value=target,
        tolerance=None,
        fresh=(freshness.valid if freshness.maximum_age_ms is not None
               else (False if not freshness.valid else None)),
        valid=False,
        matches_expected=None,
        reason=f"missing evidence requirement for expected field {field}",
        age_ms=freshness.age_ms,
        maximum_age_ms=None,
    )


def _evaluate_requirement(requirement: EvidenceRequirement, field: str, target,
                          after: RobotState,
                          freshness_policy: StateFreshnessPolicy) -> PhysicalEvidence:
    actual = getattr(after, field, None)
    freshness = freshness_policy.evaluate(
        after.timestamp, requirement.maximum_age_ms
    )
    value_valid = True
    matches: bool | None = None
    reasons = []
    if requirement.source != "robot_state":
        value_valid = False
        reasons.append(f"unsupported evidence source: {requirement.source}")
    elif target is None:
        value_valid = False
        reasons.append(f"expected {field} is missing")
    elif isinstance(target, (int, float)) and not isinstance(target, bool) and not _is_finite_number(target):
        value_valid = False
        reasons.append(f"expected {field} is non-finite")
    elif actual is None:
        value_valid = False
        reasons.append(f"observed {field} is missing")
    elif isinstance(actual, (int, float)) and not isinstance(actual, bool) and not _is_finite_number(actual):
        value_valid = False
        reasons.append(f"observed {field} is non-finite")
    else:
        if (_is_finite_number(target) and _is_finite_number(actual)
                and requirement.tolerance is not None):
            matches = abs(float(actual) - float(target)) <= requirement.tolerance
        else:
            matches = actual == target
        reasons.append(
            "evidence matches expected effect" if matches
            else f"{field}={actual!r}, expected {target!r}"
        )
    if not freshness.valid:
        reasons.append(f"evidence freshness invalid: {freshness.reason}")
    valid = value_valid and freshness.valid
    return PhysicalEvidence(
        source=requirement.source,
        state_field=field,
        measured_at=after.timestamp,
        received_at=freshness.evaluated_at,
        observed_value=actual,
        expected_value=target,
        tolerance=requirement.tolerance,
        fresh=(freshness.valid if requirement.maximum_age_ms is not None
               else (False if not freshness.valid else None)),
        valid=valid,
        matches_expected=matches,
        reason="; ".join(reasons),
        age_ms=freshness.age_ms,
        maximum_age_ms=freshness.maximum_age_ms,
    )


class OutcomeVerifier:
    def __init__(self, freshness_policy: StateFreshnessPolicy | None = None):
        self.freshness_policy = freshness_policy or StateFreshnessPolicy()

    def verify(self, skill: RobotSkill, arguments: dict, before: RobotState,
               after: RobotState) -> VerificationResult:
        semantic = skill.verify_outcome(arguments, before, after)
        expected = skill.expected_effects(arguments, before)
        requirements: dict[str, EvidenceRequirement] = {}
        if skill.safety_contract is not None:
            for requirement in skill.safety_contract.evidence_requirements:
                try:
                    field = requirement.resolved_field(arguments)
                except (KeyError, ValueError):
                    continue
                requirements[field] = requirement
        evidence = []
        for field, target in expected.items():
            requirement = requirements.get(field)
            evidence.append(
                _missing_requirement(field, target, after, self.freshness_policy)
                if requirement is None
                else _evaluate_requirement(
                    requirement, field, target, after, self.freshness_policy
                )
            )
        evidence_complete = bool(expected) and all(
            item.valid for item in evidence
        )
        achieved = evidence_complete and semantic.achieved and all(
            item.matches_expected is True for item in evidence
        )
        commit_ready = evidence_complete and achieved
        message = semantic.message
        if not evidence_complete and evidence:
            message = "; ".join(item.reason for item in evidence if not item.valid)
        return VerificationResult(
            achieved,
            message,
            semantic.observed,
            tuple(evidence),
            evidence_complete,
            commit_ready,
        )
