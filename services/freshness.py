"""Freshness: a pure function computing a recency signal for one NewsEvent.

Phase 9 Contract §2.1/§5. Deliberately dependency-free beyond the stdlib - no
database access, no system-clock read, no other services/ module - see
scripts/validate_architecture.py's freshness-purity rule, which mechanically
enforces this boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# Six ordered tiers (Contract §5.2; the windows docs/phase9_decision_resolution.md §2
# already recommended), each with a monotonically-decreasing placeholder weight.
# PRODUCT CONFIGURATION (Contract §22) - the boundary/weight *values* are provisional
# and product-tunable; the requirement that Freshness compute *some* ordered tier and
# weight, deterministically, is architecture (Contract §5.1) and is not.
TIER_BOUNDARIES_HOURS: tuple[float, ...] = (2.0, 6.0, 12.0, 24.0, 48.0)
TIER_LABELS: tuple[str, ...] = ("0-2h", "2-6h", "6-12h", "12-24h", "24-48h", "48h+")
TIER_WEIGHTS: tuple[float, ...] = (1.0, 0.8, 0.6, 0.4, 0.2, 0.1)


@dataclass(frozen=True)
class FreshnessResult:
    """JSON-serializable, immutable - Contract §3's "Output shape" requirement,
    applied to Freshness's own result as well as Triage's."""

    tier_index: int
    tier_label: str
    weight: float
    age_seconds: float
    used_collected_at_fallback: bool


def _require_timezone_aware(value: datetime, *, name: str) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware (Contract §5.1 rule 6); got a naive datetime.")


def compute_freshness(
    published_at: datetime | None,
    collected_at: datetime,
    reference_now: datetime,
) -> FreshnessResult:
    """Pure. Implements Contract §5.1 rules 1-7:

    1. No internal clock read - reference_now is always an explicit argument.
    2. published_at, when present, is the freshness anchor.
    3. published_at missing -> collected_at (never null) is used instead, flagged
       in the result.
    4. A negative computed age (a future timestamp: clock skew, a malformed feed,
       a pre-dated post) is clamped to zero, never raised as an error.
    5. collected_at is assumed always present and valid for any persisted NewsEvent.
    6. All comparisons are timezone-aware; a naive datetime raises ValueError rather
       than silently comparing incorrectly.
    7. "Deterministic" means reproducible for a fixed reference_now, not idempotent
       across time - recomputing later legitimately yields a different result.
    """
    _require_timezone_aware(reference_now, name="reference_now")
    _require_timezone_aware(collected_at, name="collected_at")

    used_fallback = published_at is None
    if published_at is None:
        anchor = collected_at
    else:
        _require_timezone_aware(published_at, name="published_at")
        anchor = published_at

    age: timedelta = reference_now - anchor
    age_seconds = max(age.total_seconds(), 0.0)
    age_hours = age_seconds / 3600.0

    tier_index = len(TIER_BOUNDARIES_HOURS)
    for index, boundary_hours in enumerate(TIER_BOUNDARIES_HOURS):
        if age_hours < boundary_hours:
            tier_index = index
            break

    return FreshnessResult(
        tier_index=tier_index,
        tier_label=TIER_LABELS[tier_index],
        weight=TIER_WEIGHTS[tier_index],
        age_seconds=age_seconds,
        used_collected_at_fallback=used_fallback,
    )
