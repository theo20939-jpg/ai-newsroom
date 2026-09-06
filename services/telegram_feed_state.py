"""NINJA Social Intelligence Foundation, Part III §40: FeedState - platform context derived from
recent TelegramChannelMemory history, NOT News Importance (spec §41's own explicit separation).
Deterministic, zero LLM calls - pure counting/aggregation over already-persisted rows.

SOCIAL-INTELLIGENCE-PRELAUNCH-1A §4/§21: TelegramChannelMemory may contain PRE-REBRAND content
(the current real situation - NINJA VPN's own history, before the NINJA PULSE transition). Without
filtering, compute_feed_state() would silently treat old VPN posts as real PULSE feed history,
contaminating topic/entity distributions and streaks with content that has nothing to do with the
new brand. When a `launch_context` is supplied and pre-launch/transition, rows are filtered through
the SAME canonical services/social_learning_boundary.py::is_eligible_for_first_party_learning()
every other first-party-evidence consumer uses - never a second, ad hoc boundary check.
`is_cold_start=True` on the returned FeedState is a truthful, explicit signal (spec §4's own "use
an explicit cold-start/feed state rather than pretending a normal feed exists") - never silently
indistinguishable from "a real live channel that merely posted nothing recently"."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.social_launch_context import SocialLaunchContext
from database.models.telegram_channel_memory import StoryRole, TelegramChannelMemory
from services.social_learning_boundary import is_eligible_for_first_party_learning
from services.social_launch_context_service import is_prelaunch_or_transition

# Best-effort proxy only (spec §12) - TelegramChannelMemory has no dedicated commercial/product
# flag; `content_objective` is the nearest available structural signal.
_COMMERCIAL_OBJECTIVES = {"product", "commercial", "promotional", "promo"}


@dataclass(frozen=True)
class FeedState:
    as_of: datetime
    posts_1h: int
    posts_6h: int
    posts_24h: int
    # SOCIAL-INTELLIGENCE-PRELAUNCH-1A §4: True whenever a launch_context was supplied, the
    # platform is PRE_LAUNCH/TRANSITION, and zero first-party-eligible posts exist yet (learning
    # has not started, or every real row predates the boundary) - a truthful, explicit signal, not
    # merely "all the counts below happen to be zero".
    is_cold_start: bool = False
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

    # Spec §12 extensions - all derived from columns TelegramChannelMemory already has, no new
    # migration needed. `commercial_content_share` is a best-effort proxy over `content_objective`
    # (this table has no dedicated commercial/product flag) - documented here rather than silently
    # treated as authoritative; `campaign_content_share` is structural (campaign_id is not None) and
    # IS authoritative. `cta_streak` is likewise a best-effort proxy over `content_objective`, since
    # no dedicated CTA-family column exists either - a future phase should add one if precise CTA
    # tracking becomes load-bearing.
    story_role_mix: dict[str, int] = field(default_factory=dict)
    commercial_content_share: float = 0.0
    campaign_content_share: float = 0.0
    recent_update_recap_density: float = 0.0
    visual_family_streak: int = 0
    cta_streak: int = 0
    topic_saturation: float = 0.0
    entity_saturation: float = 0.0
    source_saturation: float = 0.0


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


async def compute_feed_state(
    session: AsyncSession, *, now: datetime, lookback_count: int = 100,
    launch_context: SocialLaunchContext | None = None,
) -> FeedState:
    """`launch_context=None` (every existing call site before PRELAUNCH-1A) preserves the exact
    prior behavior - unfiltered rows, is_cold_start=False - so this is purely additive. Only when a
    real launch_context is passed AND the platform is pre-launch/transition are rows filtered down
    to first-party-eligible ones (spec §4/§21) - a live, already-launched channel's own feed state
    is never affected by this parameter existing."""
    stmt = (
        select(TelegramChannelMemory)
        .where(TelegramChannelMemory.published_at <= now)
        .order_by(TelegramChannelMemory.published_at.desc())
        .limit(lookback_count)
    )
    rows = list((await session.execute(stmt)).scalars().all())

    cold_start = False
    if launch_context is not None and is_prelaunch_or_transition(launch_context):
        rows = [r for r in rows if is_eligible_for_first_party_learning(published_at=r.published_at, launch_context=launch_context)]
        cold_start = len(rows) == 0

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
    commercial_posts = sum(
        1 for r in rows if (r.content_objective or "").lower() in _COMMERCIAL_OBJECTIVES
    )
    update_recap_posts = sum(
        1 for r in rows if r.story_role in (StoryRole.UPDATE, StoryRole.RECAP)
    )
    story_role_counter = Counter(r.story_role.value for r in rows if r.story_role is not None)

    total = len(rows)
    topic_total = sum(topic_counter.values())
    entity_total = sum(entity_counter.values())
    source_total = sum(source_counter.values())

    return FeedState(
        as_of=now, posts_1h=posts_1h, posts_6h=posts_6h, posts_24h=posts_24h, is_cold_start=cold_start,
        topic_distribution=dict(topic_counter), entity_distribution=dict(entity_counter),
        source_distribution=dict(source_counter), presentation_mix=dict(presentation_counter),
        topic_streak=_longest_leading_streak([(r.topics or [None])[0] for r in rows]),
        entity_streak=_longest_leading_streak([(r.entities or [None])[0] for r in rows]),
        source_streak=_longest_leading_streak([r.source for r in rows]),
        recent_story_roles=[r.story_role.value for r in rows[:10] if r.story_role is not None],
        recent_visual_families=[r.visual_family for r in rows[:10] if r.visual_family is not None],
        recent_campaign_post_count=campaign_posts,
        story_role_mix=dict(story_role_counter),
        commercial_content_share=(commercial_posts / total) if total else 0.0,
        campaign_content_share=(campaign_posts / total) if total else 0.0,
        recent_update_recap_density=(update_recap_posts / total) if total else 0.0,
        visual_family_streak=_longest_leading_streak([r.visual_family for r in rows]),
        cta_streak=_longest_leading_streak([r.content_objective for r in rows]),
        topic_saturation=(max(topic_counter.values()) / topic_total) if topic_total else 0.0,
        entity_saturation=(max(entity_counter.values()) / entity_total) if entity_total else 0.0,
        source_saturation=(max(source_counter.values()) / source_total) if source_total else 0.0,
    )
