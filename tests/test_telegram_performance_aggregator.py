"""SOCIAL-INTELLIGENCE-OPS-1, spec §61: TelegramPerformanceAggregator tests - gate on real
analytics-enabled PUBLIC surface, comparable-window-only baselines, missing-denominator-never-zero,
and the anti-overfit evidence-stage gate carried through from services/telegram_performance_memory.py."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.social_launch_context import (
    HistoricalContentPolicy,
    LaunchDateStatus,
    LaunchState,
    LearningBaselinePolicy,
    SocialLaunchPlatform,
)
from database.models.telegram_channel_memory import TelegramChannelMemory
from database.models.telegram_post_performance import SnapshotWindow, TelegramPostPerformanceSnapshot
from database.models.telegram_surface import TelegramSurfaceRole
from services.social_launch_context_service import create_next_version
from services.telegram_performance_aggregator import compute_telegram_performance_aggregate
from services.telegram_performance_memory import EvidenceStage
from services.telegram_surface_registry import create_surface

_OWNED_CHAT_ID = -1005551234567


async def _enable_public_analytics_surface(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "telegram_owned_channel_id", _OWNED_CHAT_ID)
    await create_surface(
        db_session, chat_id=_OWNED_CHAT_ID, role=TelegramSurfaceRole.PUBLIC_NEWS_CHANNEL,
        name="NINJA PULSE", analytics_enabled=True, active=True,
    )


async def _post_with_snapshot(
    db_session: AsyncSession, *, published_at: datetime, views: int, age_seconds: int = 86400,
    window: SnapshotWindow = SnapshotWindow.H24, **kwargs: object,
) -> TelegramChannelMemory:
    memory = TelegramChannelMemory(published_at=published_at, **kwargs)  # type: ignore[arg-type]
    db_session.add(memory)
    await db_session.flush()
    snapshot = TelegramPostPerformanceSnapshot(
        id=uuid4(), channel_memory_id=memory.id, telegram_message_id=None, window=window,
        captured_at=published_at + timedelta(seconds=age_seconds), age_seconds=age_seconds, views=views,
        forwards=None, reactions_total=None, comments_total=None, capability_version="test-v1", collector="test",
    )
    db_session.add(snapshot)
    await db_session.commit()
    return memory


@pytest.mark.asyncio
async def test_gate_blocks_when_no_public_analytics_surface(db_session: AsyncSession) -> None:
    aggregate = await compute_telegram_performance_aggregate(db_session, now=datetime.now(timezone.utc))
    assert aggregate.status == "PUBLIC_CHANNEL_NOT_CONFIGURED"
    assert aggregate.patterns == []


@pytest.mark.asyncio
async def test_waiting_for_data_when_no_posts(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_public_analytics_surface(db_session, monkeypatch)
    aggregate = await compute_telegram_performance_aggregate(db_session, now=datetime.now(timezone.utc))
    assert aggregate.status == "WAITING_FOR_DATA"


@pytest.mark.asyncio
async def test_waiting_for_data_when_posts_exist_but_no_comparable_snapshots(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _enable_public_analytics_surface(db_session, monkeypatch)
    now = datetime.now(timezone.utc)
    db_session.add(TelegramChannelMemory(published_at=now - timedelta(hours=1)))
    await db_session.commit()
    aggregate = await compute_telegram_performance_aggregate(db_session, now=now, window=SnapshotWindow.H24)
    assert aggregate.status == "WAITING_FOR_DATA"


@pytest.mark.asyncio
async def test_insufficient_evidence_below_minimum_sample(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_public_analytics_surface(db_session, monkeypatch)
    now = datetime.now(timezone.utc)
    await _post_with_snapshot(db_session, published_at=now - timedelta(days=1), views=1000, category="news")
    aggregate = await compute_telegram_performance_aggregate(db_session, now=now)
    assert aggregate.status == "INSUFFICIENT_EVIDENCE"
    assert aggregate.total_posts_considered == 1


@pytest.mark.asyncio
async def test_mismatched_window_snapshot_is_excluded_not_zeroed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post with only a 5m-window snapshot must never be silently compared against 24h posts -
    it should be entirely excluded from the 24h aggregation, not counted with a fabricated 0 rate."""
    await _enable_public_analytics_surface(db_session, monkeypatch)
    now = datetime.now(timezone.utc)
    for i in range(3):
        await _post_with_snapshot(db_session, published_at=now - timedelta(days=1, hours=i), views=1000, category="news")
    await _post_with_snapshot(
        db_session, published_at=now - timedelta(minutes=5), views=999999, age_seconds=300,
        window=SnapshotWindow.M5, category="news",
    )
    aggregate = await compute_telegram_performance_aggregate(db_session, now=now, window=SnapshotWindow.H24)
    assert aggregate.status == "OK"
    assert aggregate.total_posts_considered == 3  # the M5-only post is excluded, not counted as a 4th


@pytest.mark.asyncio
async def test_real_dimension_pattern_with_positive_lift(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_public_analytics_surface(db_session, monkeypatch)
    now = datetime.now(timezone.utc)
    # Three low-performing "update" posts, three high-performing "news" posts.
    for i in range(3):
        await _post_with_snapshot(
            db_session, published_at=now - timedelta(days=1, hours=i), views=100, category="update",
        )
    for i in range(3):
        await _post_with_snapshot(
            db_session, published_at=now - timedelta(days=1, hours=i), views=10000, category="news",
        )
    aggregate = await compute_telegram_performance_aggregate(db_session, now=now)
    assert aggregate.status == "OK"
    assert aggregate.total_posts_considered == 6
    news_pattern = next(p for p in aggregate.patterns if p.dimension == "content_role" and p.dimension_value == "news")
    update_pattern = next(p for p in aggregate.patterns if p.dimension == "content_role" and p.dimension_value == "update")
    assert news_pattern.effect_size > 0
    assert update_pattern.effect_size < 0
    assert news_pattern.sample_size == 3
    # Anti-overfit: 3 independent same-value posts clears POSSIBLE_SIGNAL's repeatability floor
    # but never STABLE_WORKING_RULE (needs >=30 samples) - the existing gate is trusted, not reimplemented.
    assert news_pattern.stage in (EvidenceStage.POSSIBLE_SIGNAL, EvidenceStage.ANOMALY)
    assert news_pattern.stage != EvidenceStage.STABLE_WORKING_RULE


@pytest.mark.asyncio
async def test_topic_and_entity_dimensions_from_list_fields(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_public_analytics_surface(db_session, monkeypatch)
    now = datetime.now(timezone.utc)
    for i in range(3):
        await _post_with_snapshot(
            db_session, published_at=now - timedelta(days=1, hours=i), views=500,
            topics=["ai", "gaming"], entities=["OpenAI"],
        )
    aggregate = await compute_telegram_performance_aggregate(db_session, now=now)
    dims = {(p.dimension, p.dimension_value) for p in aggregate.patterns}
    assert ("topic", "ai") in dims
    assert ("topic", "gaming") in dims
    assert ("entity", "OpenAI") in dims


@pytest.mark.asyncio
async def test_single_post_pattern_never_reaches_stable_rule(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await _enable_public_analytics_surface(db_session, monkeypatch)
    now = datetime.now(timezone.utc)
    await _post_with_snapshot(db_session, published_at=now - timedelta(days=1), views=1000, category="a")
    await _post_with_snapshot(db_session, published_at=now - timedelta(days=1), views=1000, category="b")
    await _post_with_snapshot(db_session, published_at=now - timedelta(days=1), views=50000, category="unique")
    aggregate = await compute_telegram_performance_aggregate(db_session, now=now)
    unique_pattern = next(p for p in aggregate.patterns if p.dimension_value == "unique")
    assert unique_pattern.sample_size == 1
    assert unique_pattern.stage == EvidenceStage.ANOMALY


@pytest.mark.asyncio
async def test_no_launch_context_configured_applies_no_learning_boundary_filter(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SOCIAL-INTELLIGENCE-PRELAUNCH-1A §21: a channel that has never run /launch (the real,
    current production state) sees ZERO behavior change - every post still counts, exactly as
    before this phase."""
    await _enable_public_analytics_surface(db_session, monkeypatch)
    now = datetime.now(timezone.utc)
    for i in range(3):
        await _post_with_snapshot(db_session, published_at=now - timedelta(days=10, hours=i), views=500, category="news")
    aggregate = await compute_telegram_performance_aggregate(db_session, now=now)
    assert aggregate.status == "OK"
    assert aggregate.total_posts_considered == 3


@pytest.mark.asyncio
async def test_legacy_posts_before_learning_boundary_never_count_even_when_live(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SOCIAL-INTELLIGENCE-PRELAUNCH-1A §21: once a real learning_start_at boundary exists, posts
    published before it (the old NINJA VPN channel's own history) NEVER count toward NINJA PULSE
    performance evidence - not even after the channel has since gone LIVE. The boundary is a
    permanent historical fact, never re-opened by a later launch_state change."""
    await _enable_public_analytics_surface(db_session, monkeypatch)
    now = datetime.now(timezone.utc)
    learning_start_at = now - timedelta(days=5)
    await create_next_version(
        db_session, platform=SocialLaunchPlatform.TELEGRAM, target_identity="NINJA PULSE",
        current_identity="NINJA VPN news", launch_state=LaunchState.LIVE, planned_launch_at=None,
        launch_date_status=LaunchDateStatus.CONFIRMED, learning_start_at=learning_start_at,
        baseline_policy=LearningBaselinePolicy.FROM_EXPLICIT_DATE,
        historical_content_policy=HistoricalContentPolicy.LEGACY_CONTEXT_ONLY,
        raw_instruction="test setup", confirmed_structure={}, created_by=5507703201,
    )
    # 3 legacy (pre-boundary) posts - must never count.
    for i in range(3):
        await _post_with_snapshot(db_session, published_at=now - timedelta(days=10, hours=i), views=999999, category="legacy_vpn")
    # 3 real post-boundary PULSE posts - these are the only ones that should count.
    for i in range(3):
        await _post_with_snapshot(db_session, published_at=now - timedelta(days=1, hours=i), views=500, category="news")

    aggregate = await compute_telegram_performance_aggregate(db_session, now=now)
    assert aggregate.status == "OK"
    assert aggregate.total_posts_considered == 3
    dims = {(p.dimension, p.dimension_value) for p in aggregate.patterns}
    assert ("content_role", "legacy_vpn") not in dims
    assert ("content_role", "news") in dims
