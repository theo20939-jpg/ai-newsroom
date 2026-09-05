"""INSTAGRAM GROWTH ENGINE v2, spec §42: Performance Input contract tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.instagram_performance import InstagramPerformanceObservation, UnavailableMetricError


def test_all_metrics_default_to_none_not_zero() -> None:
    observation = InstagramPerformanceObservation(
        content_id="c1", format="reel", objective="reach", observed_at=datetime.now(timezone.utc),
    )
    assert observation.reach is None
    assert observation.likes is None
    assert observation.has_any_metric() is False


def test_setting_a_metric_without_available_capability_raises() -> None:
    """No Instagram account is connected anywhere in this codebase - every read capability is
    UNAVAILABLE, so no metric may ever be set to a real value in this phase."""
    with pytest.raises(UnavailableMetricError):
        InstagramPerformanceObservation(
            content_id="c1", format="reel", objective="reach", observed_at=datetime.now(timezone.utc), reach=1000,
        )


def test_unrelated_metric_still_defaults_to_none() -> None:
    observation = InstagramPerformanceObservation(
        content_id="c2", format="single", objective="brand", observed_at=datetime.now(timezone.utc),
    )
    assert observation.follows is None
    assert observation.profile_visits is None
