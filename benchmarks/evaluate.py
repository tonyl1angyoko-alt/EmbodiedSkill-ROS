#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Print a Markdown table from benchmark results")
    parser.add_argument("results", nargs="?", type=Path,
                        default=Path(__file__).with_name("benchmark_results.json"))
    args = parser.parse_args()
    data = json.loads(args.results.read_text(encoding="utf-8"))
    metrics = [
        "task_success_rate", "long_horizon_success_rate", "state_change_success_rate",
        "invalid_skill_call_rate", "plan_repair_success_rate", "runtime_recovery_rate",
        "outcome_verification_accuracy", "average_execution_steps", "average_task_latency_ms",
    ]
    print("| Profile | " + " | ".join(metrics) + " |")
    print("|---|" + "---:|" * len(metrics))
    for name, profile in data["profiles"].items():
        values = [str(profile["metrics"][metric]) for metric in metrics]
        print(f"| {name} | " + " | ".join(values) + " |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
