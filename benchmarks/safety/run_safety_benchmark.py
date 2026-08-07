#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.safety.metrics import summarize_safety_runs
from benchmarks.safety.model import (
    load_safety_scenarios,
    validate_safety_scenarios,
)
from benchmarks.safety.profiles import PROFILE_NAMES, run_safety_scenario
from embodied_skill_ros.safety.hazard_catalog import load_hazard_catalog


METRIC_DEFINITIONS = {
    "unsafe_action_execution_rate": {
        "numerator": "oracle-unsafe action opportunities with at least one unsafe backend dispatch",
        "denominator": "actions classified by the scenario oracle as unsafe-to-dispatch before any explicit safe-state condition is satisfied",
    },
    "false_commit_rate": {
        "numerator": "commit-disallowed transactions reported as physically successful without sufficient valid/fresh evidence",
        "denominator": "action transactions for which the scenario oracle disallows commit",
    },
    "duplicate_side_effect_rate": {
        "numerator": "dispatches above the oracle maximum for protected non-idempotent transactions",
        "denominator": "protected non-idempotent transaction opportunities",
    },
    "unsupported_capability_invocation_rate": {
        "numerator": "unsupported capability requests that reach backend command",
        "denominator": "unsupported capability requests",
    },
    "evidence_coverage": {
        "numerator": "reported physical successes backed by complete valid fresh matching required evidence",
        "denominator": "all actions reported as physically successful; N/A for profiles without an evidence concept",
    },
    "safe_recovery_rate": {
        "numerator": "automatically recovered transactions whose actions stay within the explicit recovery oracle and duplicate-dispatch limit",
        "denominator": "transactions that enter RETRY, REOBSERVE, or continuation REPLAN",
    },
    "safe_stop_attempt_coverage": {
        "numerator": "STOP-required executions with exactly one backend safe-stop attempt",
        "denominator": "executions whose scenario oracle requires STOP",
    },
    "false_refusal_rate": {
        "numerator": "oracle-safe legal dispatch opportunities that receive no backend command",
        "denominator": "oracle-safe legal actions explicitly marked as false-refusal controls",
    },
    "task_success_rate": {
        "numerator": "executions whose final physical state satisfies the scenario oracle constraint",
        "denominator": "all scenario executions",
    },
}


def run_catalog(scenario_path: Path) -> dict:
    catalog = load_safety_scenarios(scenario_path)
    hazards = load_hazard_catalog(PROJECT_ROOT / "config" / "hazards.json")
    hazard_ids = {item.hazard_id for item in hazards.hazards}
    issues = validate_safety_scenarios(
        catalog,
        known_hazard_ids=hazard_ids,
        require_balanced_hazards=True,
    )
    if issues:
        raise ValueError("invalid safety benchmark catalog:\n" + "\n".join(issues))

    output = {
        "schema_version": 1,
        "deterministic": True,
        "scenario_count": len(catalog.scenarios),
        "positive_control_count": sum(
            item.positive_control for item in catalog.scenarios
        ),
        "hazard_distribution": dict(sorted(Counter(
            item.hazard_id for item in catalog.scenarios
        ).items())),
        "metric_definitions": METRIC_DEFINITIONS,
        "profiles": {},
    }
    for profile in PROFILE_NAMES:
        runs = [
            run_safety_scenario(scenario, profile)
            for scenario in catalog.scenarios
        ]
        summary = summarize_safety_runs(zip(catalog.scenarios, runs))
        output["profiles"][profile.value] = {
            **summary.to_dict(),
            "runs": [item.to_dict() for item in runs],
        }
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the deterministic hazard-driven safety benchmark"
    )
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=Path(__file__).with_name("scenarios.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("safety_results.json"),
    )
    args = parser.parse_args()
    output = run_catalog(args.scenarios)
    args.output.write_text(
        json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    compact = {
        profile: data["metrics"]
        for profile, data in output["profiles"].items()
    }
    print(json.dumps(compact, indent=2, ensure_ascii=False))
    print(f"deterministic results: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
