from __future__ import annotations

from statistics import fmean
from typing import Any, Iterable


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def summarize_runs(records: Iterable[dict[str, Any]]) -> dict[str, float | int]:
    """Aggregate benchmark records without depending on a dataframe library."""

    rows = list(records)
    long_horizon = [row for row in rows if row["category"] == "multi"]
    state_change = [row for row in rows if row["category"] == "state"]
    repair_attempts = [row for row in rows if row["repair_used"]]
    recovery_attempts = [row for row in rows if row["recovery_used"]]
    total_calls = sum(row["execution_steps"] for row in rows)
    invalid_calls = sum(row["invalid_calls"] for row in rows)
    verification_total = sum(row["verification_total"] for row in rows)
    verification_correct = sum(row["verification_correct"] for row in rows)
    return {
        "scenario_count": len(rows),
        "task_success_rate": _rate(sum(row["success"] for row in rows), len(rows)),
        "long_horizon_success_rate": _rate(
            sum(row["success"] for row in long_horizon), len(long_horizon)
        ),
        "state_change_success_rate": _rate(
            sum(row["success"] for row in state_change), len(state_change)
        ),
        "invalid_skill_call_rate": _rate(invalid_calls, total_calls),
        "plan_repair_success_rate": _rate(
            sum(row["success"] for row in repair_attempts), len(repair_attempts)
        ),
        "runtime_recovery_rate": _rate(
            sum(row["success"] for row in recovery_attempts), len(recovery_attempts)
        ),
        "outcome_verification_accuracy": _rate(verification_correct, verification_total),
        "average_execution_steps": round(fmean(row["execution_steps"] for row in rows), 4) if rows else 0.0,
        "average_task_latency_ms": round(fmean(row["latency_ms"] for row in rows), 4) if rows else 0.0,
    }
