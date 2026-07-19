"""Tests for services.freshness. Pure unit tests - no DB, no network, no LLM."""
from datetime import datetime, timedelta, timezone

import pytest

from services.freshness import TIER_LABELS, TIER_WEIGHTS, compute_freshness

UTC = timezone.utc
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_published_at_present_gives_correct_tier() -> None:
    published_at = NOW - timedelta(hours=1)
    result = compute_freshness(published_at, NOW - timedelta(hours=1), NOW)

    assert result.tier_label == "0-2h"
    assert result.weight == TIER_WEIGHTS[0]
    assert result.used_collected_at_fallback is False
    assert result.age_seconds == pytest.approx(3600.0)


def test_published_at_none_falls_back_to_collected_at_and_flags_it() -> None:
    collected_at = NOW - timedelta(hours=3)
    result = compute_freshness(None, collected_at, NOW)

    assert result.used_collected_at_fallback is True
    assert result.tier_label == "2-6h"
    assert result.age_seconds == pytest.approx(3 * 3600.0)


def test_future_published_at_clamps_to_zero_age_no_raise() -> None:
    published_at = NOW + timedelta(hours=5)
    result = compute_freshness(published_at, NOW - timedelta(hours=1), NOW)

    assert result.age_seconds == 0.0
    assert result.tier_label == "0-2h"


def test_zero_age_boundary_published_at_equals_reference_now() -> None:
    result = compute_freshness(NOW, NOW - timedelta(hours=1), NOW)

    assert result.age_seconds == 0.0
    assert result.tier_label == "0-2h"
    assert result.weight == TIER_WEIGHTS[0]


def test_zero_age_boundary_collected_at_fallback_equals_reference_now() -> None:
    result = compute_freshness(None, NOW, NOW)

    assert result.age_seconds == 0.0
    assert result.tier_label == "0-2h"
    assert result.used_collected_at_fallback is True


@pytest.mark.parametrize(
    ("age_hours", "expected_tier"),
    [
        (0.0, "0-2h"),
        (1.999, "0-2h"),
        (2.0, "2-6h"),  # exact lower boundary belongs to the next tier
        (5.999, "2-6h"),
        (6.0, "6-12h"),
        (11.999, "6-12h"),
        (12.0, "12-24h"),
        (23.999, "12-24h"),
        (24.0, "24-48h"),
        (47.999, "24-48h"),
        (48.0, "48h+"),
        (200.0, "48h+"),
    ],
)
def test_exact_tier_boundaries(age_hours: float, expected_tier: str) -> None:
    published_at = NOW - timedelta(hours=age_hours)
    result = compute_freshness(published_at, NOW - timedelta(hours=age_hours), NOW)

    assert result.tier_label == expected_tier
    assert result.tier_label in TIER_LABELS


def test_naive_reference_now_raises_value_error() -> None:
    naive_now = datetime(2026, 1, 1, 12, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        compute_freshness(NOW - timedelta(hours=1), NOW - timedelta(hours=1), naive_now)


def test_naive_published_at_raises_value_error() -> None:
    naive_published = datetime(2026, 1, 1, 11, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        compute_freshness(naive_published, NOW - timedelta(hours=1), NOW)


def test_naive_collected_at_raises_value_error() -> None:
    naive_collected = datetime(2026, 1, 1, 11, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        compute_freshness(None, naive_collected, NOW)


def test_deterministic_repeated_calls_are_byte_identical() -> None:
    published_at = NOW - timedelta(hours=7)
    collected_at = NOW - timedelta(hours=7, minutes=1)

    first = compute_freshness(published_at, collected_at, NOW)
    second = compute_freshness(published_at, collected_at, NOW)

    assert first == second


def test_no_internal_clock_read_same_reference_now_is_reproducible_later() -> None:
    """§5.1 rule 7: deterministic means reproducible given a fixed reference_now, not
    idempotent across wall-clock time - calling this "later" (in test-wall-clock terms)
    with the same reference_now must still produce the same result."""
    published_at = NOW - timedelta(hours=10)
    collected_at = NOW - timedelta(hours=10)

    result_a = compute_freshness(published_at, collected_at, NOW)
    result_b = compute_freshness(published_at, collected_at, NOW)

    assert result_a == result_b
