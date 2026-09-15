"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 5: services/trend_evidence_ranking.py - the deterministic
evidence-sufficiency gate. Fixture gate requirement: "weak evidence -> zero opportunities" - TREND
may legitimately return NO STRONG TREND, never a forced 'best available' pick."""
from __future__ import annotations

from services.instagram_content_opportunity import OpportunitySourceType
from services.trend_evidence_ranking import TrendEvidence, build_trend_opportunity, is_trend_evidence_sufficient
from services.trend_normalization import EngagementVelocity, NormalizedEngagement


def _high_engagement() -> NormalizedEngagement:
    return NormalizedEngagement(available=True, percentile=0.9, ratio_to_median=2.5, baseline_size=10)


def _low_engagement() -> NormalizedEngagement:
    return NormalizedEngagement(available=True, percentile=0.2, ratio_to_median=0.5, baseline_size=10)


def test_insufficient_cross_source_count_fails_even_if_recent() -> None:
    evidence = TrendEvidence(cross_source_count=1, recency_hours=1.0)
    result = is_trend_evidence_sufficient(evidence)
    assert result.sufficient is False
    assert any("cross_source_count" in r for r in result.reasons)


def test_sufficient_when_cross_source_and_recent() -> None:
    evidence = TrendEvidence(cross_source_count=2, recency_hours=5.0)
    result = is_trend_evidence_sufficient(evidence)
    assert result.sufficient is True


def test_stale_but_high_engagement_is_still_sufficient() -> None:
    evidence = TrendEvidence(cross_source_count=2, recency_hours=200.0, normalized_engagement=_high_engagement())
    result = is_trend_evidence_sufficient(evidence)
    assert result.sufficient is True


def test_stale_and_low_engagement_is_insufficient() -> None:
    """Weak evidence -> zero opportunities: neither recent nor unusually engaging, never forced."""
    evidence = TrendEvidence(cross_source_count=2, recency_hours=200.0, normalized_engagement=_low_engagement())
    result = is_trend_evidence_sufficient(evidence)
    assert result.sufficient is False


def test_no_normalized_engagement_and_stale_is_insufficient() -> None:
    evidence = TrendEvidence(cross_source_count=3, recency_hours=500.0, normalized_engagement=None)
    result = is_trend_evidence_sufficient(evidence)
    assert result.sufficient is False


def test_thresholds_are_tunable_parameters_not_hardcoded() -> None:
    evidence = TrendEvidence(cross_source_count=1, recency_hours=1.0)
    assert is_trend_evidence_sufficient(evidence, min_cross_source_count=1).sufficient is True


def test_build_trend_opportunity_never_fabricates_a_composite_score() -> None:
    evidence = TrendEvidence(
        cross_source_count=3, recency_hours=2.0, normalized_engagement=_high_engagement(),
        velocity=EngagementVelocity(available=True, delta_per_hour=50.0),
    )
    opportunity = build_trend_opportunity("cluster-1", evidence, representative_text="Starter Pack trend")
    assert opportunity.source_type == OpportunitySourceType.TREND
    assert opportunity.trend_id == "cluster-1"
    assert "cross_source_count=3" in opportunity.evidence
    assert any("velocity_per_hour=50.00" in e for e in opportunity.evidence)
    assert opportunity.confidence <= 1.0


def test_build_trend_opportunity_discloses_unavailable_velocity_never_fakes_zero() -> None:
    evidence = TrendEvidence(cross_source_count=2, recency_hours=1.0, velocity=None)
    opportunity = build_trend_opportunity("cluster-2", evidence, representative_text="x")
    assert any("velocity=UNAVAILABLE" in e for e in opportunity.evidence)
