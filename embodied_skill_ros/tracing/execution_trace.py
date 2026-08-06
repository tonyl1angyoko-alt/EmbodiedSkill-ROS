from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


@dataclass
class TraceRecord:
    skill_name: str
    arguments: dict[str, Any]
    started_at: str
    ended_at: str
    command_accepted: bool
    backend_message: str
    before_state: dict[str, Any]
    after_state: dict[str, Any]
    outcome_verified: bool | None
    verification_message: str
    error: str | None = None
    timed_out: bool = False
    recovery_triggered: bool = False
    attempt: int = 1


@dataclass
class ExecutionTrace:
    plan_id: str
    records: list[TraceRecord] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)

    def add(self, record: TraceRecord) -> None:
        self.records.append(record)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
