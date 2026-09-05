"""INSTAGRAM-GROWTH-3, item 19: Audience Intelligence persistence/provenance tests."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_audience_memory import AudienceEvidenceSource
from database.models.instagram_shared import IntelligenceEvidenceStage
from services.instagram_audience_memory import (
    UnsupportedAudienceInsightError,
    add_audience_evidence,
    create_audience_insight,
    list_audience_insights,
)


@pytest.mark.asyncio
async def test_non_hypothesis_insight_requires_initial_evidence(db_session: AsyncSession) -> None:
    with pytest.raises(UnsupportedAudienceInsightError):
        await create_audience_insight(
            db_session, segment_name="new users", need="save time", source=AudienceEvidenceSource.COMMENTS,
        )


@pytest.mark.asyncio
async def test_hypothesis_insight_can_be_created_without_evidence(db_session: AsyncSession) -> None:
    insight = await create_audience_insight(
        db_session, segment_name="new users", need="save time", source=AudienceEvidenceSource.HYPOTHESIS,
    )
    assert insight.evidence_stage == IntelligenceEvidenceStage.HYPOTHESIS
    assert insight.observation_count == 0


@pytest.mark.asyncio
async def test_evidence_backed_insight_starts_at_observation_stage(db_session: AsyncSession) -> None:
    insight = await create_audience_insight(
        db_session, segment_name="considering", need="compare options", source=AudienceEvidenceSource.COMMENTS,
        initial_evidence="3 comments asked for a comparison table",
    )
    assert insight.evidence_stage == IntelligenceEvidenceStage.OBSERVATION
    assert insight.observation_count == 1
    assert insight.evidence == ["3 comments asked for a comparison table"]


@pytest.mark.asyncio
async def test_evidence_evolves_as_more_observations_arrive(db_session: AsyncSession) -> None:
    insight = await create_audience_insight(
        db_session, segment_name="considering2", need="compare options", source=AudienceEvidenceSource.COMMENTS,
        initial_evidence="evidence 1",
    )
    initial_confidence = insight.confidence
    for i in range(2, 5):
        insight = await add_audience_evidence(db_session, insight.id, evidence_text=f"evidence {i}")
    assert insight.observation_count == 4
    assert len(insight.evidence) == 4
    assert insight.evidence_stage == IntelligenceEvidenceStage.REPEATED_PATTERN
    assert insight.confidence > initial_confidence


@pytest.mark.asyncio
async def test_list_audience_insights_filters_by_segment(db_session: AsyncSession) -> None:
    await create_audience_insight(
        db_session, segment_name="seg-a", need="n", source=AudienceEvidenceSource.HYPOTHESIS,
    )
    await create_audience_insight(
        db_session, segment_name="seg-b", need="n", source=AudienceEvidenceSource.HYPOTHESIS,
    )
    results = await list_audience_insights(db_session, segment_name="seg-a")
    assert len(results) == 1
    assert results[0].segment_name == "seg-a"
