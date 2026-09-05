"""VISUAL-DESIGN-AUTONOMY-1, spec §68: VisualFeedContext tests - recent repetition represented,
dark/light-style dimensions represented via visual_family, presentation repetition represented,
and repetition is exposed as advisory data only (no enforcement inside this module itself)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.telegram_channel_memory import TelegramChannelMemory
from services.visual_feed_context import compute_visual_feed_context


async def _post(db_session: AsyncSession, *, published_at: datetime, **kwargs: object) -> None:
    db_session.add(TelegramChannelMemory(published_at=published_at, **kwargs))  # type: ignore[arg-type]
    await db_session.flush()


@pytest.mark.asyncio
async def test_empty_history_is_honest(db_session: AsyncSession) -> None:
    context = await compute_visual_feed_context(db_session, now=datetime.now(timezone.utc))
    assert context.posts_considered == 0
    assert "no recent" in context.summary_lines()[0]


@pytest.mark.asyncio
async def test_visual_family_repetition_is_represented(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    for i in range(4):
        await _post(db_session, published_at=now - timedelta(hours=i), visual_family="dark_photo", category="ai")
    context = await compute_visual_feed_context(db_session, now=now)
    assert context.longest_visual_family_streak == 4
    assert context.visual_family_counts["dark_photo"] == 4
    summary = context.summary_lines()
    assert any("dark_photo" in line for line in summary)


@pytest.mark.asyncio
async def test_presentation_type_distribution_represented(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    await _post(db_session, published_at=now - timedelta(hours=1), presentation_type="NEWS")
    await _post(db_session, published_at=now - timedelta(hours=2), presentation_type="NEWS")
    await _post(db_session, published_at=now - timedelta(hours=3), presentation_type="DATA")
    context = await compute_visual_feed_context(db_session, now=now)
    assert context.presentation_type_counts == {"NEWS": 2, "DATA": 1}


@pytest.mark.asyncio
async def test_repetition_is_advisory_not_a_prohibition(db_session: AsyncSession) -> None:
    """This module only counts and describes - it must never itself decide that repetition is
    disallowed (that judgment belongs entirely to the LLM-driven Visual Design Director)."""
    now = datetime.now(timezone.utc)
    for i in range(6):
        await _post(db_session, published_at=now - timedelta(hours=i), visual_family="red_heavy")
    context = await compute_visual_feed_context(db_session, now=now)
    assert context.longest_visual_family_streak == 6
    # No "blocked"/"disallowed"/boolean-veto field exists on the dataclass at all.
    assert not hasattr(context, "blocked")
    assert not hasattr(context, "disallowed")
