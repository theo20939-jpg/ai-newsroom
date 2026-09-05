"""INSTAGRAM GROWTH ENGINE v2, spec §65: Competitor Intelligence tests. Persistence tests use the
real db_session fixture (mirrors tests/test_business_context_snapshot_service.py's own
conventions); pattern/gap derivation tests build CompetitorContentObservation rows in-memory
(never persisted) since that logic is pure Python over already-fetched rows."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.competitor import CompetitorContentObservation, ObservationSource
from services.instagram_competitor_intelligence import (
    EvidenceStage,
    create_competitor_account,
    derive_patterns,
    find_format_gaps,
    find_topic_gaps,
    list_observations,
    record_observation,
)


def _obs(**overrides: object) -> CompetitorContentObservation:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(), competitor_id=uuid.uuid4(), observed_at=datetime.now(timezone.utc),
        format="reel", topic="ai productivity hacks", hook_family="question",
        observation_source=ObservationSource.MANUAL, confidence=0.3,
    )
    defaults.update(overrides)
    return CompetitorContentObservation(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_competitor_account_and_observation_persist(db_session: AsyncSession) -> None:
    account = await create_competitor_account(db_session, platform="instagram", handle="@rival")
    observation = await record_observation(
        db_session, competitor_id=account.id, observed_at=datetime.now(timezone.utc), format="reel",
        topic="ai productivity hacks", hook_family="question", observable_metrics={"likes": 500},
    )
    fetched = await list_observations(db_session, competitor_id=account.id)
    assert len(fetched) == 1
    assert fetched[0].id == observation.id
    assert fetched[0].observable_metrics == {"likes": 500}


@pytest.mark.asyncio
async def test_unavailable_metrics_are_stored_as_none_not_zero(db_session: AsyncSession) -> None:
    account = await create_competitor_account(db_session, platform="instagram", handle="@rival2")
    observation = await record_observation(
        db_session, competitor_id=account.id, observed_at=datetime.now(timezone.utc), format="carousel",
        topic="topic x", observable_metrics=None,
    )
    assert observation.observable_metrics is None


def test_single_observation_cannot_become_a_pattern() -> None:
    patterns = derive_patterns([_obs(hook_family="contrarian")], dimension="hook_family")
    assert len(patterns) == 1
    assert patterns[0].evidence_stage == EvidenceStage.OBSERVATION
    assert patterns[0].sample_size == 1


def test_pattern_requires_multiple_observations() -> None:
    observations = [_obs(hook_family="motion") for _ in range(3)]
    patterns = derive_patterns(observations, dimension="hook_family")
    assert len(patterns) == 1
    assert patterns[0].evidence_stage == EvidenceStage.PATTERN
    assert patterns[0].sample_size == 3
    assert len(patterns[0].supporting_observation_ids) == 3


def test_two_observations_are_only_a_hypothesis_not_a_pattern() -> None:
    observations = [_obs(hook_family="reveal") for _ in range(2)]
    patterns = derive_patterns(observations, dimension="hook_family")
    assert patterns[0].evidence_stage == EvidenceStage.HYPOTHESIS


def test_competitor_gap_contains_supporting_evidence() -> None:
    observations = [_obs(topic="ai productivity hacks") for _ in range(3)]
    gaps = find_topic_gaps(observations, own_covered_topics=["unrelated topic"])
    assert len(gaps) == 1
    assert gaps[0].sample_size == 3
    assert len(gaps[0].supporting_observation_ids) == 3
    assert gaps[0].content_hypothesis
    assert gaps[0].recommended_test


def test_topic_gap_excluded_when_own_content_already_covers_it() -> None:
    observations = [_obs(topic="ai productivity hacks") for _ in range(3)]
    gaps = find_topic_gaps(observations, own_covered_topics=["AI Productivity Hacks"])
    assert gaps == []


def test_format_gap_requires_minimum_sample_size() -> None:
    observations = [_obs(format="story")]
    gaps = find_format_gaps(observations, own_used_formats=["reel", "carousel"])
    assert gaps == []  # single observation - not enough evidence for a gap claim
