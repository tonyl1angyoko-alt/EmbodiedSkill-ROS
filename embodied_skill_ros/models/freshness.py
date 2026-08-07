from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Callable


def utc_now_datetime() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class FreshnessResult:
    valid: bool
    age_ms: float | None
    maximum_age_ms: int | None
    reason: str
    evaluated_at: str | None = None


class StateFreshnessPolicy:
    """Deterministic timestamp integrity and maximum-age policy.

    ``maximum_age_ms=None`` means that age expiry is not enforced. Timestamp
    integrity is still evaluated when this policy is called, which is required
    for auditable physical evidence. Admission skips this policy only when the
    skill contract does not request a state-age gate.
    """

    def __init__(self, now_fn: Callable[[], datetime] = utc_now_datetime):
        self._now_fn = now_fn

    def evaluate(
        self,
        timestamp: str | None,
        maximum_age_ms: int | None,
    ) -> FreshnessResult:
        if (maximum_age_ms is not None
                and (isinstance(maximum_age_ms, bool)
                     or not isinstance(maximum_age_ms, int)
                     or maximum_age_ms < 0)):
            raise ValueError("maximum_age_ms must be a non-negative integer or None")

        try:
            now = self._now_fn()
        except Exception as exc:
            return FreshnessResult(
                False, None, maximum_age_ms,
                f"freshness clock failed: {type(exc).__name__}: {exc}",
            )
        if (not isinstance(now, datetime)
                or now.tzinfo is None
                or now.utcoffset() is None):
            return FreshnessResult(
                False, None, maximum_age_ms,
                "freshness clock must return a timezone-aware datetime",
            )
        evaluated_at = now.isoformat()

        if not isinstance(timestamp, str) or not timestamp:
            return FreshnessResult(
                False, None, maximum_age_ms,
                "observation timestamp is missing", evaluated_at,
            )
        try:
            measured_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            return FreshnessResult(
                False, None, maximum_age_ms,
                "observation timestamp is malformed", evaluated_at,
            )
        if measured_at.tzinfo is None or measured_at.utcoffset() is None:
            return FreshnessResult(
                False, None, maximum_age_ms,
                "observation timestamp has no timezone", evaluated_at,
            )

        try:
            age_ms = (
                now.astimezone(timezone.utc) - measured_at.astimezone(timezone.utc)
            ).total_seconds() * 1000.0
        except (OverflowError, ValueError):
            return FreshnessResult(
                False, None, maximum_age_ms,
                "observation age could not be calculated", evaluated_at,
            )
        if not math.isfinite(age_ms):
            return FreshnessResult(
                False, age_ms, maximum_age_ms,
                "observation age is non-finite", evaluated_at,
            )
        if age_ms < 0:
            return FreshnessResult(
                False, age_ms, maximum_age_ms,
                f"observation timestamp is in the future by {-age_ms:.3f} ms",
                evaluated_at,
            )
        if maximum_age_ms is None:
            return FreshnessResult(
                True, age_ms, None,
                "freshness age limit is not required; timestamp is valid",
                evaluated_at,
            )
        if age_ms > maximum_age_ms:
            return FreshnessResult(
                False, age_ms, maximum_age_ms,
                f"observation is stale: age {age_ms:.3f} ms exceeds "
                f"maximum {maximum_age_ms} ms",
                evaluated_at,
            )
        return FreshnessResult(
            True, age_ms, maximum_age_ms,
            f"observation is fresh: age {age_ms:.3f} ms is within "
            f"maximum {maximum_age_ms} ms",
            evaluated_at,
        )
