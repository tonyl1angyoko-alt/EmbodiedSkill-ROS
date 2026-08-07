from __future__ import annotations

from datetime import datetime
import math

from ..models.evidence import EvidenceRequirement, PhysicalEvidence
from ..models.robot_state import RobotState
from ..models.skill_result import VerificationResult
from ..skills.base_skill import RobotSkill
from ..tracing.execution_trace import utc_now


def _valid_timestamp(value: str | None) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _is_finite_number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _missing_requirement(field: str, target, after: RobotState) -> PhysicalEvidence:
    return PhysicalEvidence(
        source="robot_state",
        state_field=field,
        measured_at=after.timestamp,
        received_at=utc_now(),
        observed_value=getattr(after, field, None),
        expected_value=target,
        tolerance=None,
        fresh=None,
        valid=False,
        matches_expected=None,
        reason=f"missing evidence requirement for expected field {field}",
    )


def _evaluate_requirement(requirement: EvidenceRequirement, field: str, target,
                          after: RobotState) -> PhysicalEvidence:
    actual = getattr(after, field, None)
    valid = True
    matches: bool | None = None
    if requirement.source != "robot_state":
        valid = False
        reason = f"unsupported evidence source: {requirement.source}"
    elif target is None:
        valid = False
        reason = f"expected {field} is missing"
    elif isinstance(target, (int, float)) and not isinstance(target, bool) and not _is_finite_number(target):
        valid = False
        reason = f"expected {field} is non-finite"
    elif actual is None:
        valid = False
        reason = f"observed {field} is missing"
    elif isinstance(actual, (int, float)) and not isinstance(actual, bool) and not _is_finite_number(actual):
        valid = False
        reason = f"observed {field} is non-finite"
    elif not _valid_timestamp(after.timestamp):
        valid = False
        reason = f"measurement timestamp for {field} is invalid"
    else:
        if (_is_finite_number(target) and _is_finite_number(actual)
                and requirement.tolerance is not None):
            matches = abs(float(actual) - float(target)) <= requirement.tolerance
        else:
            matches = actual == target
        reason = ("evidence matches expected effect" if matches
                  else f"{field}={actual!r}, expected {target!r}")
    return PhysicalEvidence(
        source=requirement.source,
        state_field=field,
        measured_at=after.timestamp,
        received_at=utc_now(),
        observed_value=actual,
        expected_value=target,
        tolerance=requirement.tolerance,
        # Phase 2A validates timestamp shape. Age enforcement is Phase 2B.
        fresh=None,
        valid=valid,
        matches_expected=matches,
        reason=reason,
    )


class OutcomeVerifier:
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
                _missing_requirement(field, target, after)
                if requirement is None
                else _evaluate_requirement(requirement, field, target, after)
            )
        evidence_complete = bool(expected) and all(
            item.valid for item in evidence
        )
        achieved = semantic.achieved and all(
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
