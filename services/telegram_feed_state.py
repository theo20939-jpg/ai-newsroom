"""NINJA Social Intelligence Foundation, Part III §40: FeedState - platform context derived from
recent TelegramChannelMemory history, NOT News Importance (spec §41's own explicit separation).
Deterministic, zero LLM calls - pure counting/aggregation over already-persisted rows."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.telegram_channel_memory import TelegramChannelMemory


@dataclass(frozen=True)
class FeedState:
    as_of: datetime
    posts_1h: int
    posts_6h: int
    posts_24h: int
    topic_distribution: dict[str, int] = field(default_factory=dict)
    entity_distribution: dict[str, int] = field(default_factory=dict)
    source_distribution: dict[str, int] = field(default_factory=dict)
    presentation_mix: dict[str, int] = field(default_factory=dict)
    # Longest current run of consecutive posts (most-recent-first) sharing the same
    # topic/entity/source - a streak of 1 means "no repetition at all".
    topic_streak: int = 0
    entity_streak: int = 0
    source_streak: int = 0
    recent_story_roles: list[str] = field(default_factory=list)
    recent_visual_families: list[str] = field(default_factory=list)
    recent_campaign_post_count: int = 0


def _longest_leading_streak(values: list[str | None]) -> int:
    """Counts how many of the most-recent posts (in order) share the SAME single value as the
    very latest post - e.g. [A, A, A, B, ...] -> 3, never counting past the first differing post
    or past a `None` (unknown) entry."""
    if not values or values[0] is None:
        return 0
    streak = 0
    first = values[0]
    for value in values:
        if value != first:
            break
        streak += 1
    return streak


async def compute_feed_state(session: AsyncSession, *, now: datetime, lookback_count: int = 100) -> FeedState:
    stmt = (
        select(TelegramChannelMemory)
        .where(TelegramChannelMemory.published_at <= now)
        .order_by(TelegramChannelMemory.published_at.desc())
        .limit(lookback_count)
    )
    rows = list((await session.execute(stmt)).scalars().all())

    posts_1h = sum(1 for r in rows if r.published_at >= now - timedelta(hours=1))
    posts_6h = sum(1 for r in rows if r.published_at >= now - timedelta(hours=6))
    posts_24h = sum(1 for r in rows if r.published_at >= now - timedelta(hours=24))

    topic_counter: Counter[str] = Counter()
    entity_counter: Counter[str] = Counter()
    for r in rows:
        for topic in (r.topics or []):
            topic_counter[topic] += 1
        for entity in (r.entities or []):
            entity_counter[entity] += 1
    source_counter = Counter(r.source for r in rows if r.source)
    presentation_counter = Counter(r.presentation_type for r in rows if r.presentation_type)

    campaign_posts = sum(1 for r in rows if r.campaign_id is not None)

    return FeedState(
        as_of=now, posts_1h=posts_1h, posts_6h=posts_6h, posts_24h=posts_24h,
        topic_distribution=dict(topic_counter), entity_distribution=dict(entity_counter),
        source_distribution=dict(source_counter), presentation_mix=dict(presentation_counter),
        topic_streak=_longest_leading_streak([(r.topics or [None])[0] for r in rows]),
        entity_streak=_longest_leading_streak([(r.entities or [None])[0] for r in rows]),
        source_streak=_longest_leading_streak([r.source for r in rows]),
        recent_story_roles=[r.story_role.value for r in rows[:10] if r.story_role is not None],
        recent_visual_families=[r.visual_family for r in rows[:10] if r.visual_family is not None],
        recent_campaign_post_count=campaign_posts,
    )
