from __future__ import annotations

import ast
from dataclasses import dataclass, fields, is_dataclass
import importlib
import json
from pathlib import Path
import re
from typing import Any, Iterable


SYSTEM_LEVEL_TOKEN = "__system__"
REQUIRED_HAZARD_IDS = frozenset(f"H-{number:03d}" for number in range(1, 9))

# Reverse traceability baseline. These are existing deterministic mechanisms,
# not alternative runtime policy. A catalog edit cannot authorize execution.
CORE_SAFETY_MECHANISM_REFS = frozenset({
    "embodied_skill_ros.skills.base_skill:RobotSkill.preconditions",
    "embodied_skill_ros.grounding.constraint_checker:ConstraintChecker.check_step",
    "embodied_skill_ros.models.freshness:StateFreshnessPolicy.evaluate",
    "embodied_skill_ros.models.evidence:EvidenceRequirement",
    "embodied_skill_ros.execution.outcome_verifier:OutcomeVerifier.verify",
    "embodied_skill_ros.models.transaction:SkillTransaction.apply_verification",
    "embodied_skill_ros.execution.recovery_manager:RecoveryManager.decide",
    "embodied_skill_ros.execution.skill_executor:SkillExecutor._protected_replan_replay",
    "embodied_skill_ros.skills.registry:build_registry_for_backend",
    "embodied_skill_ros.execution.skill_executor:SkillExecutor._stop_and_report",
    "embodied_skill_ros.skills.base_skill:RobotSkill.validate_arguments",
    "embodied_skill_ros.planner.llm_adapter:_reject_non_finite_constant",
    "embodied_skill_ros.skills.base_skill:RobotSkill.safety_contract_violation",
})

_MINIMUM_HAZARD_ENFORCEMENT = {
    "H-003": frozenset({
        "embodied_skill_ros.execution.outcome_verifier:OutcomeVerifier.verify",
        "embodied_skill_ros.models.transaction:SkillTransaction.apply_verification",
    }),
    "H-004": frozenset({
        "embodied_skill_ros.execution.recovery_manager:RecoveryManager.decide",
        "embodied_skill_ros.execution.skill_executor:SkillExecutor._protected_replan_replay",
    }),
}
_HAZARD_ID_PATTERN = re.compile(r"^H-\d{3}$")
_TEST_REFERENCE_PATTERN = re.compile(
    r"^(tests/test_[A-Za-z0-9_]+\.py)::([A-Za-z_][A-Za-z0-9_]*)\."
    r"(test_[A-Za-z0-9_]+)$"
)


@dataclass(frozen=True)
class SafetyHazard:
    """Audit-only hazard-to-property traceability record.

    This model is a lightweight safety-case index. It is deliberately absent
    from the execution hot path and does not grant or deny runtime authority.
    """

    hazard_id: str
    title: str
    description: str
    unsafe_control_action: str
    safety_property: str
    related_skills: tuple[str, ...]
    contract_refs: tuple[str, ...]
    enforced_by: tuple[str, ...]
    regression_tests: tuple[str, ...]
    severity_note: str | None = None
    assumptions: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SafetyHazard":
        if not isinstance(data, dict):
            raise TypeError("hazard entry must be an object")

        def required_string(name: str) -> str:
            value = data.get(name)
            if not isinstance(value, str):
                raise TypeError(f"hazard {name} must be a string")
            return value

        def string_tuple(name: str) -> tuple[str, ...]:
            value = data.get(name)
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise TypeError(f"hazard {name} must be an array of strings")
            return tuple(value)

        severity_note = data.get("severity_note")
        if severity_note is not None and not isinstance(severity_note, str):
            raise TypeError("hazard severity_note must be a string or null")
        assumptions = data.get("assumptions", [])
        if not isinstance(assumptions, list) or not all(
            isinstance(item, str) for item in assumptions
        ):
            raise TypeError("hazard assumptions must be an array of strings")
        return cls(
            hazard_id=required_string("hazard_id"),
            title=required_string("title"),
            description=required_string("description"),
            unsafe_control_action=required_string("unsafe_control_action"),
            safety_property=required_string("safety_property"),
            related_skills=string_tuple("related_skills"),
            contract_refs=string_tuple("contract_refs"),
            enforced_by=string_tuple("enforced_by"),
            regression_tests=string_tuple("regression_tests"),
            severity_note=severity_note,
            assumptions=tuple(assumptions),
        )


@dataclass(frozen=True)
class HazardCatalog:
    hazards: tuple[SafetyHazard, ...]


def _reject_non_finite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def load_hazard_catalog(path: str | Path) -> HazardCatalog:
    source = Path(path)
    data = json.loads(
        source.read_text(encoding="utf-8"),
        parse_constant=_reject_non_finite_json,
    )
    if not isinstance(data, dict):
        raise TypeError("hazard catalog root must be an object")
    if data.get("schema_version") != 1:
        raise ValueError("hazard catalog schema_version must be 1")
    entries = data.get("hazards")
    if not isinstance(entries, list):
        raise TypeError("hazard catalog hazards must be an array")
    return HazardCatalog(tuple(SafetyHazard.from_dict(item) for item in entries))


def _resolve_python_reference(reference: str) -> str | None:
    if reference.count(":") != 1:
        return "must use module:qualified_name syntax"
    module_name, qualified_name = reference.split(":", 1)
    if not module_name or not qualified_name:
        return "module and qualified name must be non-empty"
    try:
        current: Any = importlib.import_module(module_name)
    except (ImportError, ValueError) as exc:
        return f"module import failed: {exc}"
    for part in qualified_name.split("."):
        if hasattr(current, part):
            current = getattr(current, part)
            continue
        if is_dataclass(current):
            dataclass_fields = {item.name: item for item in fields(current)}
            if part in dataclass_fields:
                current = dataclass_fields[part]
                continue
        return f"qualified member {part!r} does not exist"
    return None


def _validate_test_reference(reference: str, project_root: Path) -> str | None:
    match = _TEST_REFERENCE_PATTERN.fullmatch(reference)
    if match is None:
        return "must use tests/test_file.py::TestCase.test_method syntax"
    relative_path, class_name, method_name = match.groups()
    path = project_root / relative_path
    if not path.is_file():
        return f"test file does not exist: {relative_path}"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        return f"test source cannot be parsed: {exc}"
    test_class = next(
        (node for node in tree.body
         if isinstance(node, ast.ClassDef) and node.name == class_name),
        None,
    )
    if test_class is None:
        return f"test class does not exist: {class_name}"
    base_names = {ast.unparse(base) for base in test_class.bases}
    if not any(name.endswith("TestCase") for name in base_names):
        return f"test class is not a unittest TestCase: {class_name}"
    test_method = next(
        (node for node in test_class.body
         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
         and node.name == method_name),
        None,
    )
    if test_method is None:
        return f"test method does not exist: {class_name}.{method_name}"
    return None


def _nonempty_text_issues(hazard: SafetyHazard) -> Iterable[str]:
    for name in (
        "title", "description", "unsafe_control_action", "safety_property"
    ):
        if not getattr(hazard, name).strip():
            yield f"{hazard.hazard_id}: {name} must be non-empty"


def validate_hazard_catalog(
    catalog: HazardCatalog,
    *,
    project_root: str | Path,
    registered_skills: Iterable[str],
) -> tuple[str, ...]:
    """Validate traceability only; never evaluate runtime authorization."""

    issues: list[str] = []
    root = Path(project_root)
    skill_names = set(registered_skills)
    hazard_ids = [hazard.hazard_id for hazard in catalog.hazards]
    seen: set[str] = set()
    for hazard in catalog.hazards:
        if not _HAZARD_ID_PATTERN.fullmatch(hazard.hazard_id):
            issues.append(f"{hazard.hazard_id}: hazard_id must match H-XXX")
        if hazard.hazard_id in seen:
            issues.append(f"{hazard.hazard_id}: duplicate hazard_id")
        seen.add(hazard.hazard_id)
        issues.extend(_nonempty_text_issues(hazard))
        if not hazard.related_skills:
            issues.append(f"{hazard.hazard_id}: related_skills must be non-empty")
        invalid_skills = set(hazard.related_skills) - skill_names - {SYSTEM_LEVEL_TOKEN}
        if invalid_skills:
            issues.append(
                f"{hazard.hazard_id}: unknown related skills {sorted(invalid_skills)}"
            )
        if not hazard.contract_refs:
            issues.append(f"{hazard.hazard_id}: contract_refs must be non-empty")
        if not hazard.enforced_by:
            issues.append(f"{hazard.hazard_id}: enforced_by must be non-empty")
        if not hazard.regression_tests:
            issues.append(f"{hazard.hazard_id}: regression_tests must be non-empty")
        for reference in (*hazard.contract_refs, *hazard.enforced_by):
            error = _resolve_python_reference(reference)
            if error is not None:
                issues.append(f"{hazard.hazard_id}: invalid Python ref {reference}: {error}")
        for reference in hazard.regression_tests:
            if "test_hazard_catalog.py" in reference:
                issues.append(
                    f"{hazard.hazard_id}: catalog self-test is not a behavioral regression"
                )
            error = _validate_test_reference(reference, root)
            if error is not None:
                issues.append(f"{hazard.hazard_id}: invalid test ref {reference}: {error}")

    missing_hazards = REQUIRED_HAZARD_IDS - set(hazard_ids)
    if missing_hazards:
        issues.append(f"missing required hazards: {sorted(missing_hazards)}")
    for hazard_id, required in _MINIMUM_HAZARD_ENFORCEMENT.items():
        hazard = next(
            (item for item in catalog.hazards if item.hazard_id == hazard_id), None
        )
        if hazard is not None:
            missing = required - set(hazard.enforced_by)
            if missing:
                issues.append(
                    f"{hazard_id}: missing required enforcement {sorted(missing)}"
                )
    referenced = {
        reference
        for hazard in catalog.hazards
        for reference in (*hazard.contract_refs, *hazard.enforced_by)
    }
    orphaned = CORE_SAFETY_MECHANISM_REFS - referenced
    if orphaned:
        issues.append(f"orphaned core safety mechanisms: {sorted(orphaned)}")
    return tuple(issues)
