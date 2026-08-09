#!/usr/bin/env python3
"""Verify release metadata, the YAML registry mirror, and frozen-core hashes."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import tomli
import yaml

from embodied_skill_ros.skills.base_skill import ParameterSpec, RobotSkill
from embodied_skill_ros.skills.registry import build_default_registry


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FROZEN_FILE_COUNT = 12
EXPECTED_FROZEN_LOC = 1385


def _setup_version() -> str:
    tree = ast.parse((ROOT / "setup.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if name != "setup":
            continue
        for keyword in node.keywords:
            if keyword.arg == "version" and isinstance(keyword.value, ast.Constant):
                return str(keyword.value.value)
    raise AssertionError("setup.py does not contain a literal setup(version=...)")


def release_versions() -> dict[str, str]:
    pyproject = tomli.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    package = ET.parse(ROOT / "package.xml").getroot()
    package_version = package.findtext("version")
    if package_version is None:
        raise AssertionError("package.xml has no <version>")
    versions = {
        "pyproject.toml": str(pyproject["project"]["version"]),
        "setup.py": _setup_version(),
        "package.xml": package_version,
        "CITATION.cff": str(citation["version"]),
    }
    if len(set(versions.values())) != 1:
        raise AssertionError(f"release metadata versions differ: {versions}")
    return versions


def _parameter_type(spec: ParameterSpec) -> str:
    if spec.python_type is str:
        return "string"
    numeric = spec.python_type == (int, float) or spec.python_type in (int, float)
    if numeric:
        return "number"
    raise AssertionError(f"unsupported mirrored parameter type: {spec.python_type!r}")


def _python_skill(skill: RobotSkill) -> dict[str, Any]:
    parameters = {}
    for name, spec in skill.parameter_schema.items():
        parameters[name] = {
            "type": _parameter_type(spec),
            "required": spec.required,
            "minimum": spec.minimum,
            "maximum": spec.maximum,
            "enum": list(spec.choices),
        }
    effects = []
    for effect in skill.effect_specs:
        normalized: dict[str, Any] = {"field": effect.field}
        if effect.operation == "increment":
            normalized["increment_from_argument"] = effect.argument
        elif effect.argument is not None:
            normalized["assign_from_argument"] = effect.argument
        else:
            normalized["assign"] = effect.value
        if effect.when_argument is not None:
            normalized["when_argument"] = effect.when_argument
        effects.append(normalized)
    return {
        "resources": sorted(skill.required_resources),
        "incompatible_resources": sorted(skill.incompatible_resources),
        "parameters": parameters,
        "preconditions": [
            {"field": item.field, "equals": item.expected, "max_age_s": item.max_age_s}
            for item in skill.preconditions
        ],
        "effects": effects,
        "timeout_s": skill.timeout,
    }


def _yaml_skill(raw: dict[str, Any]) -> dict[str, Any]:
    parameters = {}
    for name, spec in raw.get("parameters", {}).items():
        parameters[name] = {
            "type": spec["type"],
            "required": spec.get("required", True),
            "minimum": spec.get("minimum"),
            "maximum": spec.get("maximum"),
            "enum": list(spec.get("enum", [])),
        }
    return {
        "resources": sorted(raw.get("resources", [])),
        "incompatible_resources": sorted(raw.get("incompatible_resources", [])),
        "parameters": parameters,
        "preconditions": raw.get("preconditions", []),
        "effects": raw.get("effects", []),
        "timeout_s": float(raw["timeout_s"]),
    }


def verify_registry_mirror() -> int:
    document = yaml.safe_load((ROOT / "config/skills.yaml").read_text(encoding="utf-8"))
    if document.get("schema_version") != 2:
        raise AssertionError("config/skills.yaml schema_version must be 2")
    if "documentation mirror" not in str(document.get("note", "")).lower():
        raise AssertionError("config/skills.yaml must declare its documentation-mirror role")
    executable = {skill.name: _python_skill(skill) for skill in build_default_registry()}
    mirror = {name: _yaml_skill(value) for name, value in document["skills"].items()}
    if executable != mirror:
        missing = sorted(set(executable) - set(mirror))
        extra = sorted(set(mirror) - set(executable))
        drift = sorted(
            name for name in set(executable) & set(mirror)
            if executable[name] != mirror[name]
        )
        raise AssertionError(
            f"config/skills.yaml drift: missing={missing}, extra={extra}, changed={drift}"
        )
    return len(executable)


def verify_freeze_manifest() -> tuple[int, int]:
    manifest = json.loads(
        (ROOT / "benchmarks/core_freeze_manifest.json").read_text(encoding="utf-8")
    )
    files = manifest["files"]
    if len(files) != EXPECTED_FROZEN_FILE_COUNT:
        raise AssertionError(f"expected {EXPECTED_FROZEN_FILE_COUNT} frozen files, got {len(files)}")
    if manifest["total_core_lines"] != EXPECTED_FROZEN_LOC:
        raise AssertionError(
            f"expected {EXPECTED_FROZEN_LOC} frozen LOC, got {manifest['total_core_lines']}"
        )
    measured_total = 0
    for relative, expected in files.items():
        data = (ROOT / relative).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        lines = len(data.decode("utf-8").splitlines())
        if digest != expected["sha256"] or lines != expected["lines"]:
            raise AssertionError(
                f"frozen core drift in {relative}: lines={lines}, sha256={digest}"
            )
        measured_total += lines
    if measured_total != EXPECTED_FROZEN_LOC:
        raise AssertionError(f"frozen file line sum is {measured_total}, expected {EXPECTED_FROZEN_LOC}")
    return len(files), measured_total


def main() -> int:
    try:
        versions = release_versions()
        skills = verify_registry_mirror()
        frozen_files, frozen_loc = verify_freeze_manifest()
    except (AssertionError, KeyError, TypeError, ValueError, OSError) as exc:
        print(f"hygiene check failed: {exc}", file=sys.stderr)
        return 1
    version = next(iter(versions.values()))
    print(f"release metadata: {version} across {len(versions)} files")
    print(f"skill registry mirror: {skills} executable contracts consistent")
    print(f"frozen core: {frozen_files} files, {frozen_loc} LOC, all hashes match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
