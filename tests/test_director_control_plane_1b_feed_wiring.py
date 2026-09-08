"""DIRECTOR-CONTROL-PLANE-1B §5-6: integration coverage for the LIVE feed-context wiring.

Proves, through the real assembler (services/telegram_feed_window.py::
assemble_live_telegram_feed_window - resolve the registered owned surface -> one bounded channel
read -> the pure builder) and the real Director functions, that a legacy NINJA VPN post is
BOTH:
  * readable transition/feed context (Strategy Director surfaces it), AND
  * never learnable as NINJA PULSE performance evidence (Growth Director synthesises no
    signal / fatigue / amplification entry from it).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.social_launch_context import (
    HistoricalContentPolicy,
    LaunchDateStatus,
    LaunchState,
    LearningBaselinePolicy,
    SocialLaunchContext,
    SocialLaunchPlatform,
)
from database.models.telegram_surface import TelegramSurfaceRole
from services.social_learning_boundary import is_eligible_for_first_party_learning
from services.telegram_feed_state import FeedState
from services.telegram_feed_window import assemble_live_telegram_feed_window
from services.telegram_growth_director import derive_growth_director_advisory
from services.telegram_strategy_director import derive_strategy_advisory
from services.telegram_surface_registry import create_surface

_NOW = datetime(2026, 9, 8, tzinfo=timezone.utc)
_LEARNING_START = _NOW - timedelta(days=7)
_TEST_CHAT_ID = -1009900112233


def _transition_launch_context() -> SocialLaunchContext:
    return SocialLaunchContext(
        platform=SocialLaunchPlatform.TELEGRAM, version=1, launch_state=LaunchState.TRANSITION,
        launch_date_status=LaunchDateStatus.CONFIRMED, planned_launch_at=None,
        learning_start_at=_LEARNING_START, baseline_policy=LearningBaselinePolicy.FROM_EXPLICIT_DATE,
        historical_content_policy=HistoricalContentPolicy.LEGACY_CONTEXT_ONLY,
        current_identity="NINJA VPN", target_identity="NINJA PULSE",
        raw_instruction="test", confirmed_structure={}, created_by=1,
    )


def _raw_channel_context() -> dict:
    """Two legacy NINJA VPN-era posts (before the learning boundary) + one post after it."""
    return {
        "chat_id": _TEST_CHAT_ID, "title": "NINJA PULSE", "username": "ninjapulse",
        "description": None, "pinned_message_id": None,
        "recent_posts": [
            {
                "message_id": 101, "date": (_LEARNING_START - timedelta(days=40)).isoformat(),
                "has_media": True, "media_type": "photo", "text_length": 55,
                "views": 4200, "forwards": 12, "reactions_total": 80,
            },
            {
                "message_id": 102, "date": (_LEARNING_START - timedelta(days=9)).isoformat(),
                "has_media": True, "media_type": "photo", "text_length": 44,
                "views": 3900, "forwards": 9, "reactions_total": 61,
            },
            {
                "message_id": 103, "date": (_LEARNING_START + timedelta(days=2)).isoformat(),
                "has_media": False, "media_type": None, "text_length": 120,
                "views": 500, "forwards": 1, "reactions_total": 7,
            },
        ],
    }


def _empty_feed_state() -> FeedState:
    return FeedState(as_of=_NOW, posts_1h=0, posts_6h=0, posts_24h=1, topic_distribution={"ai": 1})


@pytest.fixture
def _owned_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telegram_owned_channel_id", _TEST_CHAT_ID)


@pytest.mark.asyncio
async def test_legacy_vpn_posts_are_readable_context_but_never_pulse_performance_evidence(
    db_session: AsyncSession, _owned_channel: None,
) -> None:
    await create_surface(
        db_session, chat_id=_TEST_CHAT_ID, role=TelegramSurfaceRole.PUBLIC_NEWS_CHANNEL,
        name="NINJA PULSE", username="ninjapulse", active=True, analytics_enabled=True,
    )
    launch_context = _transition_launch_context()

    with patch(
        "services.telegram_channel_context.fetch_owned_channel_context",
        new=AsyncMock(return_value=_raw_channel_context()),
    ):
        window = await assemble_live_telegram_feed_window(db_session, launch_context=launch_context)

    # --- the window itself: legacy split is real -------------------------------------------------
    assert window.surface_registered is True
    assert len(window.posts) == 3
    legacy = [p for p in window.posts if p.is_legacy]
    eligible = window.learning_eligible_posts
    assert len(legacy) == 2 and len(eligible) == 1
    for post in legacy:
        assert post.read_context_eligible is True            # ALLOWED: understand what the audience saw
        assert post.performance_learning_eligible is False   # NEVER: learn PULSE performance from it
        assert is_eligible_for_first_party_learning(
            published_at=post.timestamp, launch_context=launch_context,
        ) is False
    assert eligible[0].performance_learning_eligible is True

    # --- Strategy Director: the legacy majority DOES inform transition understanding -------------
    strategy = derive_strategy_advisory(_empty_feed_state(), patterns=[], feed_window=window)
    assert any(
        "legacy/pre-boundary" in note and "never as PULSE performance evidence" in note
        for note in strategy.content_gaps
    ), strategy.content_gaps

    # --- Growth Director: the legacy engagement is NEVER turned into a learned performance rule --
    growth = derive_growth_director_advisory([], is_cold_start=True, feed_window=window)
    assert growth.signals == []
    assert growth.fatigue == []
    assert growth.amplification_candidates == []
    assert growth.first_party_baseline == "NONE"
    assert growth.confidence == 0.0


@pytest.mark.asyncio
async def test_no_registered_surface_gives_directors_an_honestly_empty_window(
    db_session: AsyncSession, _owned_channel: None,
) -> None:
    """No surface row -> assemble returns surface_registered=False, and the Directors still work."""
    window = await assemble_live_telegram_feed_window(db_session, launch_context=_transition_launch_context())
    assert window.surface_registered is False
    assert window.posts == []

    strategy = derive_strategy_advisory(_empty_feed_state(), patterns=[], feed_window=window)
    assert strategy is not None
    growth = derive_growth_director_advisory([], is_cold_start=True, feed_window=window)
    assert growth.first_party_baseline == "NONE"
