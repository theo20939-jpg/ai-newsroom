"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 5: services/trend_signal_matching.py - the pure clustering
decision core (classify_relationship/find_best_cluster_match), plus the DB-touching
assign_observation_to_cluster() orchestration. Fixture gate requirements covered here:
"same TOPIC across different sources clusters together", "same FORMAT mechanic across unrelated
topics can form a FORMAT trend", "unrelated items do not cluster"."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.trend_cluster import TrendCluster, TrendClusterStatus, TrendClusterType
from database.models.trend_observation import TrendObservation
from services.trend_fingerprint import TrendFingerprint
from services.trend_signal_matching import (
    assign_observation_to_cluster,
    classify_relationship,
    find_best_cluster_match,
    format_similarity,
    topic_similarity,
)


def _fp(**overrides) -> TrendFingerprint:
    base = dict(topic="", entities=[], format="", hook_pattern="", mechanic="", visual_pattern="")
    base.update(overrides)
    return TrendFingerprint(**base)


# ---------------------------------------------------------------------------
# Pure decision core
# ---------------------------------------------------------------------------


def test_same_topic_different_source_produces_a_topic_match() -> None:
    """Fixture: same TOPIC across different sources clusters together - two observations about
    the SAME real-world subject (a new foldable phone) but different mechanics/formats."""
    a = _fp(topic="new foldable phone launch", entities=["iPhone Duo"], format="reel", mechanic="unboxing")
    b = _fp(topic="new foldable phone launch", entities=["iPhone Duo"], format="carousel", mechanic="spec comparison")
    result = classify_relationship(a, b)
    assert result.matches is True
    assert result.cluster_type == TrendClusterType.TOPIC


def test_same_mechanic_different_topic_produces_a_format_match() -> None:
    """Fixture: same FORMAT mechanic across UNRELATED topics can form a FORMAT trend - two
    observations about completely different subjects, same recurring editing mechanic."""
    a = _fp(topic="new AI model release", entities=["GPT-6"], format="reel", hook_pattern="POV question",
            mechanic="starter pack", visual_pattern="text overlay grid")
    b = _fp(topic="a gaming console restock", entities=["PlayStation"], format="reel", hook_pattern="POV question",
            mechanic="starter pack", visual_pattern="text overlay grid")
    result = classify_relationship(a, b)
    assert result.matches is True
    assert result.cluster_type == TrendClusterType.FORMAT


def test_same_topic_and_same_mechanic_produces_hybrid() -> None:
    a = _fp(topic="new foldable phone launch", entities=["iPhone Duo"], format="reel", mechanic="starter pack")
    b = _fp(topic="new foldable phone launch", entities=["iPhone Duo"], format="reel", mechanic="starter pack")
    result = classify_relationship(a, b)
    assert result.matches is True
    assert result.cluster_type == TrendClusterType.HYBRID


def test_unrelated_items_do_not_cluster() -> None:
    """Fixture: unrelated items do not cluster - neither topic nor mechanic overlap."""
    a = _fp(topic="new foldable phone launch", entities=["iPhone Duo"], format="reel", mechanic="unboxing", hook_pattern="reveal")
    b = _fp(topic="a viral cooking recipe", entities=["pasta"], format="carousel", mechanic="recipe steps", hook_pattern="taste test")
    result = classify_relationship(a, b)
    assert result.matches is False
    assert result.cluster_type is None


def test_find_best_cluster_match_returns_none_when_nothing_matches() -> None:
    new_fp = _fp(topic="a viral cooking recipe", mechanic="recipe steps")
    candidates = [
        (uuid4(), _fp(topic="new foldable phone launch", mechanic="unboxing")),
        (uuid4(), _fp(topic="a gaming console restock", mechanic="starter pack")),
    ]
    assert find_best_cluster_match(new_fp, candidates) is None


def test_find_best_cluster_match_picks_the_strongest_match() -> None:
    new_fp = _fp(topic="new foldable phone launch", entities=["iPhone Duo"], format="reel", mechanic="starter pack")
    weak_id, strong_id = uuid4(), uuid4()
    candidates = [
        (weak_id, _fp(topic="new foldable phone launch", entities=[], format="carousel", mechanic="spec list")),
        (strong_id, _fp(topic="new foldable phone launch", entities=["iPhone Duo"], format="reel", mechanic="starter pack")),
    ]
    best = find_best_cluster_match(new_fp, candidates)
    assert best is not None
    assert best.cluster_id == strong_id


def test_topic_and_format_similarity_are_symmetric() -> None:
    a = _fp(topic="a b c", entities=["x"])
    b = _fp(topic="a b c", entities=["x"])
    assert topic_similarity(a, b) == topic_similarity(b, a)
    assert format_similarity(a, b) == format_similarity(b, a)


# ---------------------------------------------------------------------------
# assign_observation_to_cluster(): DB orchestration
# ---------------------------------------------------------------------------


def _observation(*, fingerprint: TrendFingerprint | None, source: str = "youtube", observed_at: datetime | None = None) -> TrendObservation:
    return TrendObservation(
        source=source, source_item_id=str(uuid4()), observed_at=observed_at or datetime.now(timezone.utc),
        raw_topic_text="raw text", trend_fingerprint=fingerprint.as_dict() if fingerprint else None,
        engagement_snapshot={"view_count": 100},
    )


@pytest.mark.asyncio
async def test_first_observation_founds_a_new_cluster(db_session: AsyncSession) -> None:
    fp = _fp(topic="new foldable phone launch", entities=["iPhone Duo"])
    observation = _observation(fingerprint=fp)
    db_session.add(observation)
    await db_session.flush()

    cluster = await assign_observation_to_cluster(db_session, observation)
    assert cluster is not None
    assert observation.cluster_id == cluster.id
    assert cluster.trend_fingerprint == fp.as_dict()


@pytest.mark.asyncio
async def test_second_matching_observation_joins_the_same_cluster(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    fp1 = _fp(topic="new foldable phone launch", entities=["iPhone Duo"], format="reel")
    obs1 = _observation(fingerprint=fp1, source="youtube", observed_at=now)
    db_session.add(obs1)
    await db_session.flush()
    cluster1 = await assign_observation_to_cluster(db_session, obs1, now=now)

    fp2 = _fp(topic="new foldable phone launch", entities=["iPhone Duo"], format="carousel")
    obs2 = _observation(fingerprint=fp2, source="bluesky", observed_at=now + timedelta(hours=1))
    db_session.add(obs2)
    await db_session.flush()
    cluster2 = await assign_observation_to_cluster(db_session, obs2, now=now + timedelta(hours=1))

    assert cluster1 is not None and cluster2 is not None
    assert cluster1.id == cluster2.id  # same real-world topic, different source -> SAME cluster

    count = (await db_session.execute(select(TrendCluster).where(TrendCluster.id == cluster1.id))).scalars().all()
    assert len(count) == 1  # never duplicated


@pytest.mark.asyncio
async def test_unrelated_observation_founds_its_own_cluster(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    fp1 = _fp(topic="new foldable phone launch", entities=["iPhone Duo"], mechanic="unboxing")
    obs1 = _observation(fingerprint=fp1, observed_at=now)
    db_session.add(obs1)
    await db_session.flush()
    cluster1 = await assign_observation_to_cluster(db_session, obs1, now=now)

    fp2 = _fp(topic="a viral cooking recipe", entities=["pasta"], mechanic="recipe steps")
    obs2 = _observation(fingerprint=fp2, observed_at=now)
    db_session.add(obs2)
    await db_session.flush()
    cluster2 = await assign_observation_to_cluster(db_session, obs2, now=now)

    assert cluster1 is not None and cluster2 is not None
    assert cluster1.id != cluster2.id


@pytest.mark.asyncio
async def test_observation_without_a_fingerprint_is_not_clustered(db_session: AsyncSession) -> None:
    observation = _observation(fingerprint=None)
    db_session.add(observation)
    await db_session.flush()
    result = await assign_observation_to_cluster(db_session, observation)
    assert result is None
    assert observation.cluster_id is None


@pytest.mark.asyncio
async def test_stale_cluster_outside_lookback_is_never_matched_against(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    old_cluster = TrendCluster(
        representative_text="old", cluster_type=TrendClusterType.TOPIC,
        trend_fingerprint=_fp(topic="new foldable phone launch", entities=["iPhone Duo"]).as_dict(),
        first_observed_at=now - timedelta(days=30), last_observed_at=now - timedelta(days=30),
        status=TrendClusterStatus.ACTIVE,
    )
    db_session.add(old_cluster)
    await db_session.flush()

    fp = _fp(topic="new foldable phone launch", entities=["iPhone Duo"])
    observation = _observation(fingerprint=fp, observed_at=now)
    db_session.add(observation)
    await db_session.flush()

    new_cluster = await assign_observation_to_cluster(db_session, observation, now=now, lookback=timedelta(days=14))
    assert new_cluster is not None
    assert new_cluster.id != old_cluster.id  # the stale cluster was outside the lookback window
