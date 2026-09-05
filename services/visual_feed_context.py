"""VISUAL-DESIGN-AUTONOMY-1, spec §11-13: VisualFeedContext - lets the Visual Design Director see
how the recent feed actually LOOKS. Derived entirely from real TelegramChannelMemory columns
(category/presentation_type/visual_family/story_role/published_at) - the exact same table
services/telegram_feed_state.py already reads for editorial FeedState, read here a second time for
a VISUAL summary instead of an editorial one (deliberately not merged into FeedState itself: that
module's own fields are all editorial-mix concepts, and mixing visual-repetition fields into it
would blur two independently-evolving concerns).

CRITICAL (spec §12): every field here is ADVISORY context, never a rule. Nothing in this module
computes an "avoid X" instruction - it only counts and describes; services/visual_director_context.py
passes the counts through as plain facts, and the Visual Design Director (an LLM call) decides
whether repetition matters for THIS Story."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.telegram_channel_memory import TelegramChannelMemory

_DEFAULT_LOOKBACK = 8


@dataclass(frozen=True)
class VisualFeedContext:
    as_of: datetime
    posts_considered: int
    presentation_type_counts: dict[str, int] = field(default_factory=dict)
    visual_family_counts: dict[str, int] = field(default_factory=dict)
    category_counts: dict[str, int] = field(default_factory=dict)
    longest_visual_family_streak: int = 0
    recent_visual_families: list[str] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        """A short, deterministic, bounded-length textual summary (spec §30's own "bound context
        lengths, use deterministic summaries" instruction) - fed into VisualDirectorContext, never
        the raw rows themselves."""
        if self.posts_considered == 0:
            return ["no recent channel post history available"]
        lines = [f"last {self.posts_considered} posts considered"]
        if self.longest_visual_family_streak >= 3:
            top_family = max(self.visual_family_counts, key=lambda k: self.visual_family_counts[k], default=None)
            if top_family:
                lines.append(f"visual family {top_family!r} repeated {self.longest_visual_family_streak} times in a row")
        for label, counts in (("presentation types", self.presentation_type_counts), ("categories", self.category_counts)):
            if counts:
                top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
                lines.append(f"recent {label}: " + ", ".join(f"{k}×{v}" for k, v in top))
        return lines


def _longest_leading_streak(values: list[str | None]) -> int:
    streak = 0
    first = next((v for v in values if v is not None), None)
    if first is None:
        return 0
    for v in values:
        if v is None:
            continue
        if v == first:
            streak += 1
        else:
            break
    return streak


async def compute_visual_feed_context(
    session: AsyncSession, *, now: datetime, lookback_count: int = _DEFAULT_LOOKBACK,
) -> VisualFeedContext:
    stmt = (
        select(TelegramChannelMemory)
        .where(TelegramChannelMemory.published_at <= now)
        .order_by(TelegramChannelMemory.published_at.desc())
        .limit(lookback_count)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    if not rows:
        return VisualFeedContext(as_of=now, posts_considered=0)

    presentation_counts = Counter(r.presentation_type for r in rows if r.presentation_type)
    visual_family_counts = Counter(r.visual_family for r in rows if r.visual_family)
    category_counts = Counter(r.category for r in rows if r.category)

    return VisualFeedContext(
        as_of=now, posts_considered=len(rows),
        presentation_type_counts=dict(presentation_counts), visual_family_counts=dict(visual_family_counts),
        category_counts=dict(category_counts),
        longest_visual_family_streak=_longest_leading_streak([r.visual_family for r in rows]),
        recent_visual_families=[r.visual_family for r in rows[:10] if r.visual_family is not None],
    )
