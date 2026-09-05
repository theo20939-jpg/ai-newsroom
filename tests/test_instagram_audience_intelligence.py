"""INSTAGRAM GROWTH ENGINE v2, spec §66: Audience Intelligence tests."""
from __future__ import annotations

import pytest

from services.instagram_audience_intelligence import (
    AudienceEvidenceSource,
    AudienceInsight,
    AudienceSegment,
    FunnelStage,
)


def test_audience_insight_requires_provenance() -> None:
    with pytest.raises(ValueError):
        AudienceInsight(segment_name="new users", need="save time", source=AudienceEvidenceSource.COMMENTS, evidence=[])


def test_hypothesis_source_does_not_require_evidence() -> None:
    insight = AudienceInsight(segment_name="new users", need="save time", source=AudienceEvidenceSource.HYPOTHESIS)
    assert insight.is_hypothesis is True


def test_hypothesis_is_distinguishable_from_evidence_backed_insight() -> None:
    hypothesis = AudienceInsight(segment_name="s1", need="n1", source=AudienceEvidenceSource.HYPOTHESIS)
    evidenced = AudienceInsight(
        segment_name="s1", need="n1", source=AudienceEvidenceSource.COMMENTS, evidence=["3 comments asked about X"],
    )
    assert hypothesis.is_hypothesis and not evidenced.is_hypothesis


def test_audience_segment_carries_no_demographic_fields() -> None:
    """Spec §18/§66: unknown demographics remain unknown - AudienceSegment has no age/gender/
    location/income field to fabricate a value into at all."""
    segment = AudienceSegment(name="Category-curious", description="aware of the problem, not the product", funnel_stage=FunnelStage.PROBLEM_AWARE)
    for forbidden in ("age", "gender", "location", "income"):
        assert not hasattr(segment, forbidden)


def test_funnel_stage_is_preserved_on_segment_and_insight() -> None:
    segment = AudienceSegment(name="s", description="d", funnel_stage=FunnelStage.CONSIDERING)
    insight = AudienceInsight(
        segment_name=segment.name, need="n", source=AudienceEvidenceSource.PRODUCT_DATA, evidence=["e"],
        conversion_stage=FunnelStage.CONSIDERING,
    )
    assert segment.funnel_stage == FunnelStage.CONSIDERING
    assert insight.conversion_stage == FunnelStage.CONSIDERING
