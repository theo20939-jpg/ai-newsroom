"""INSTAGRAM-GROWTH-3, item 19: Series persistence/lifecycle tests."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_series_memory import SeriesStatus as DBSeriesStatus
from services.instagram_content_brain import EvidenceStage
from services.instagram_series_memory import create_series, promote_series, record_episode


@pytest.mark.asyncio
async def test_new_series_persists_as_hypothesis(db_session: AsyncSession) -> None:
    series = await create_series(db_session, name="Myth Monday", description="d", objective="saves")
    assert series.status == DBSeriesStatus.SERIES_HYPOTHESIS
    assert series.episode_count == 0


@pytest.mark.asyncio
async def test_single_strong_post_cannot_immediately_create_active_franchise(db_session: AsyncSession) -> None:
    series = await create_series(db_session, name="One Hit Wonder", description="d", objective="reach")
    series = await record_episode(db_session, series.id)
    assert series.episode_count == 1

    promoted = await promote_series(db_session, series.id, evidence_stage=EvidenceStage.STABLE_WORKING_RULE)
    assert promoted.status == DBSeriesStatus.SERIES_HYPOTHESIS


@pytest.mark.asyncio
async def test_repeated_evidence_promotes_to_active(db_session: AsyncSession) -> None:
    series = await create_series(db_session, name="Weekly Comparison", description="d", objective="saves")
    for _ in range(5):
        series = await record_episode(db_session, series.id)
    promoted = await promote_series(db_session, series.id, evidence_stage=EvidenceStage.REPEATED_PATTERN)
    assert promoted.status == DBSeriesStatus.SERIES_ACTIVE


@pytest.mark.asyncio
async def test_active_series_can_become_fatigued(db_session: AsyncSession) -> None:
    series = await create_series(db_session, name="Fatiguing Series", description="d", objective="reach")
    for _ in range(6):
        series = await record_episode(db_session, series.id)
    series = await promote_series(db_session, series.id, evidence_stage=EvidenceStage.STABLE_WORKING_RULE)
    assert series.status == DBSeriesStatus.SERIES_ACTIVE

    fatigued = await promote_series(db_session, series.id, evidence_stage=EvidenceStage.STABLE_WORKING_RULE, is_fatigued=True)
    assert fatigued.status == DBSeriesStatus.SERIES_FATIGUED
