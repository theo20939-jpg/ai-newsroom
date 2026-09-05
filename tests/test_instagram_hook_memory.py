"""INSTAGRAM-GROWTH-3, item 19: Hook Intelligence evidence persistence + fatigue history tests."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_hook_memory import EvidenceStage as DBEvidenceStage
from database.models.instagram_hook_memory import FatigueState as DBFatigueState
from services.instagram_content_brain import PerformancePattern
from services.instagram_hook_memory import (
    get_hook_evidence,
    get_latest_fatigue,
    list_fatigue_history,
    record_fatigue_observation,
    record_hook_evidence,
)


@pytest.mark.asyncio
async def test_thin_sample_persists_as_anomaly(db_session: AsyncSession) -> None:
    pattern = PerformancePattern(description="x", sample_size=2, effect_size=0.9, confidence=0.9, repeatability=1, baseline=0.1, recency_days=1)
    record = await record_hook_evidence(db_session, dimension="hook_family", value="contrarian", pattern=pattern)
    assert record.evidence_stage == DBEvidenceStage.ANOMALY


@pytest.mark.asyncio
async def test_hook_evidence_progresses_as_samples_accumulate(db_session: AsyncSession) -> None:
    thin = PerformancePattern(description="x", sample_size=2, effect_size=0.9, confidence=0.9, repeatability=1, baseline=0.1, recency_days=1)
    await record_hook_evidence(db_session, dimension="hook_family", value="question", pattern=thin)

    strong = PerformancePattern(description="x", sample_size=40, effect_size=0.5, confidence=0.8, repeatability=8, baseline=0.2, recency_days=20)
    updated = await record_hook_evidence(db_session, dimension="hook_family", value="question", pattern=strong)
    assert updated.evidence_stage == DBEvidenceStage.STABLE_WORKING_RULE

    fetched = await get_hook_evidence(db_session, dimension="hook_family", value="question")
    assert fetched is not None
    assert fetched.sample_size == 40


@pytest.mark.asyncio
async def test_evidence_tracked_separately_per_dimension(db_session: AsyncSession) -> None:
    pattern = PerformancePattern(description="x", sample_size=40, effect_size=0.5, confidence=0.8, repeatability=8, baseline=0.2, recency_days=20)
    await record_hook_evidence(db_session, dimension="hook_family", value="reveal", pattern=pattern)
    topic_row = await get_hook_evidence(db_session, dimension="topic", value="reveal")
    assert topic_row is None  # same VALUE, different dimension - never conflated


@pytest.mark.asyncio
async def test_fatigue_history_is_append_only(db_session: AsyncSession) -> None:
    await record_fatigue_observation(db_session, dimension="hook_family", value="curiosity_gap", repetition_count=1, window_days=14)
    await record_fatigue_observation(db_session, dimension="hook_family", value="curiosity_gap", repetition_count=5, window_days=14)
    await record_fatigue_observation(db_session, dimension="hook_family", value="curiosity_gap", repetition_count=9, window_days=14)

    history = await list_fatigue_history(db_session, dimension="hook_family", value="curiosity_gap")
    assert len(history) == 3

    latest = await get_latest_fatigue(db_session, dimension="hook_family", value="curiosity_gap")
    assert latest is not None
    assert latest.repetition_count == 9
    assert latest.fatigue_state == DBFatigueState.OVERUSED
