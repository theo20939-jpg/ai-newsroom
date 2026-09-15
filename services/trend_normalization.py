"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 5: cross-source engagement normalization + velocity.

Raw engagement across platforms must NEVER be compared directly (a YouTube viewCount and a
Bluesky likeCount are not the same unit) - every number is converted to a source-relative measure,
computed from that SAME source's own recent observation history, before it ever contributes to
cross-source ranking. Explainable methods only (percentile-within-source, ratio-to-source-median) -
no invented universal "engagement unit".

Velocity requires >= 2 real, timestamped observations of the SAME (source, source_item_id) - a
single observation NEVER produces a velocity (honest UNAVAILABLE, never a fabricated zero)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median


def _primary_metric(engagement_snapshot: dict, *, primary_metric_key: str) -> float | None:
    value = engagement_snapshot.get(primary_metric_key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


@dataclass(frozen=True)
class NormalizedEngagement:
    available: bool
    percentile: float | None = None
    ratio_to_median: float | None = None
    baseline_size: int = 0
    unavailable_reason: str | None = None


def normalize_engagement(
    target_snapshot: dict, *, source_baseline_snapshots: list[dict], primary_metric_key: str,
) -> NormalizedEngagement:
    """`source_baseline_snapshots` must already be scoped to the SAME source as `target_snapshot`
    by the caller (this function has no source concept of its own - it only ever compares numbers
    it's handed, so mixing sources in the baseline would silently defeat the whole point)."""
    target_value = _primary_metric(target_snapshot, primary_metric_key=primary_metric_key)
    if target_value is None:
        return NormalizedEngagement(available=False, unavailable_reason=f"target has no real '{primary_metric_key}' value")

    baseline_values = [
        v for v in (_primary_metric(s, primary_metric_key=primary_metric_key) for s in source_baseline_snapshots)
        if v is not None
    ]
    if not baseline_values:
        return NormalizedEngagement(available=False, unavailable_reason="no real baseline observations from this source yet")

    rank = sum(1 for v in baseline_values if v <= target_value)
    percentile = rank / len(baseline_values)
    baseline_median = median(baseline_values)
    ratio = (target_value / baseline_median) if baseline_median > 0 else None
    return NormalizedEngagement(
        available=True, percentile=percentile, ratio_to_median=ratio, baseline_size=len(baseline_values),
    )


@dataclass(frozen=True)
class EngagementVelocity:
    available: bool
    delta_per_hour: float | None = None
    unavailable_reason: str | None = None


def compute_velocity(
    observations: list[tuple[datetime, dict]], *, primary_metric_key: str,
) -> EngagementVelocity:
    """`observations`: `[(observed_at, engagement_snapshot), ...]` for the SAME
    `(source, source_item_id)`, any order - real, append-only rows from `trend_observations`."""
    pairs: list[tuple[datetime, float]] = []
    for observed_at, snapshot in observations:
        value = _primary_metric(snapshot, primary_metric_key=primary_metric_key)
        if value is not None:
            pairs.append((observed_at, value))

    if len(pairs) < 2:
        return EngagementVelocity(available=False, unavailable_reason="fewer than 2 real observations")

    pairs.sort(key=lambda p: p[0])
    first_at, first_val = pairs[0]
    last_at, last_val = pairs[-1]
    elapsed_hours = (last_at - first_at).total_seconds() / 3600
    if elapsed_hours <= 0:
        return EngagementVelocity(available=False, unavailable_reason="no elapsed time between observations")

    return EngagementVelocity(available=True, delta_per_hour=(last_val - first_val) / elapsed_hours)
