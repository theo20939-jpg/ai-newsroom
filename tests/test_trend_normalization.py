"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 5: services/trend_normalization.py - cross-source
engagement normalization + velocity. Fixture gate requirements covered here: "one snapshot -> no
velocity", "two snapshots -> real velocity", "cross-source normalization required" (raw numbers
from different sources are never compared without going through this module first)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.trend_normalization import compute_velocity, normalize_engagement


# ---------------------------------------------------------------------------
# Velocity: one snapshot -> UNAVAILABLE, two -> real velocity
# ---------------------------------------------------------------------------


def test_one_observation_never_produces_velocity() -> None:
    now = datetime.now(timezone.utc)
    result = compute_velocity([(now, {"like_count": 100})], primary_metric_key="like_count")
    assert result.available is False
    assert result.delta_per_hour is None
    assert "fewer than 2" in (result.unavailable_reason or "")


def test_zero_observations_never_produces_velocity() -> None:
    result = compute_velocity([], primary_metric_key="like_count")
    assert result.available is False


def test_two_observations_produce_real_velocity() -> None:
    now = datetime.now(timezone.utc)
    observations = [
        (now, {"like_count": 100}),
        (now + timedelta(hours=2), {"like_count": 300}),
    ]
    result = compute_velocity(observations, primary_metric_key="like_count")
    assert result.available is True
    assert result.delta_per_hour == 100.0  # (300-100)/2h


def test_velocity_is_order_independent() -> None:
    """Real observations may arrive in any order - the function sorts by observed_at itself."""
    now = datetime.now(timezone.utc)
    observations = [
        (now + timedelta(hours=2), {"like_count": 300}),
        (now, {"like_count": 100}),
    ]
    result = compute_velocity(observations, primary_metric_key="like_count")
    assert result.available is True
    assert result.delta_per_hour == 100.0


def test_missing_metric_values_are_excluded_never_treated_as_zero() -> None:
    now = datetime.now(timezone.utc)
    observations = [
        (now, {"like_count": 100}),
        (now + timedelta(hours=1), {}),  # no real value this observation - excluded, not zero
        (now + timedelta(hours=2), {"like_count": 300}),
    ]
    result = compute_velocity(observations, primary_metric_key="like_count")
    assert result.available is True
    assert result.delta_per_hour == 100.0  # computed only from the two REAL observations


# ---------------------------------------------------------------------------
# Cross-source normalization: explainable methods only, never a fabricated universal unit
# ---------------------------------------------------------------------------


def test_normalization_unavailable_without_a_real_baseline() -> None:
    result = normalize_engagement({"view_count": 5000}, source_baseline_snapshots=[], primary_metric_key="view_count")
    assert result.available is False
    assert "baseline" in (result.unavailable_reason or "")


def test_normalization_unavailable_when_target_has_no_real_value() -> None:
    result = normalize_engagement(
        {}, source_baseline_snapshots=[{"view_count": 100}], primary_metric_key="view_count",
    )
    assert result.available is False


def test_percentile_and_ratio_to_median_are_real_computed_values() -> None:
    baseline = [{"view_count": v} for v in (10, 20, 30, 40, 50)]
    result = normalize_engagement({"view_count": 60}, source_baseline_snapshots=baseline, primary_metric_key="view_count")
    assert result.available is True
    assert result.percentile == 1.0  # higher than every baseline observation
    assert result.ratio_to_median == 2.0  # 60 / median(10,20,30,40,50)=30
    assert result.baseline_size == 5


def test_below_median_produces_a_low_percentile() -> None:
    baseline = [{"view_count": v} for v in (100, 200, 300, 400, 500)]
    result = normalize_engagement({"view_count": 50}, source_baseline_snapshots=baseline, primary_metric_key="view_count")
    assert result.available is True
    assert result.percentile == 0.0
    assert result.ratio_to_median < 1.0


def test_raw_cross_source_numbers_are_never_directly_comparable_without_this_module() -> None:
    """A structural proof of the plan's own requirement: a YouTube view_count and a Bluesky
    like_count normalized independently (against their OWN source's baseline) can be meaningfully
    compared as percentiles/ratios - but the raw numbers themselves never should be, and this test
    demonstrates why: wildly different raw magnitudes normalize to comparable, explainable units."""
    youtube_target = {"view_count": 50000}
    youtube_baseline = [{"view_count": v} for v in (10000, 20000, 30000, 40000, 45000)]
    bluesky_target = {"like_count": 40}
    bluesky_baseline = [{"like_count": v} for v in (5, 10, 15, 20, 25)]

    youtube_normalized = normalize_engagement(youtube_target, source_baseline_snapshots=youtube_baseline, primary_metric_key="view_count")
    bluesky_normalized = normalize_engagement(bluesky_target, source_baseline_snapshots=bluesky_baseline, primary_metric_key="like_count")

    # The raw numbers (50000 vs 40) are meaningless to compare directly - the NORMALIZED
    # percentiles are the only thing a cross-source ranking should ever read.
    assert youtube_normalized.available and bluesky_normalized.available
    assert youtube_normalized.percentile == 1.0
    assert bluesky_normalized.percentile == 1.0
    assert youtube_target["view_count"] != bluesky_target["like_count"]  # raw magnitudes stay incomparable
