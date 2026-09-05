"""NINJA Social Intelligence Foundation, Part III §41: EditorialNeed - advisory-only, derived from
FeedState alone. CRITICAL separation (spec §41): this module NEVER reads/touches News Importance
or rewrites it - a "feed need" is platform-balance advice, never a claim about a Story's objective
newsworthiness."""
from __future__ import annotations

from dataclasses import dataclass

from services.telegram_feed_state import FeedState

# Narrow, explicit thresholds - not a learned/tunable model. A future phase may replace these with
# calibrated values; today they exist only to prove the EditorialNeed contract is reachable and
# testable, never to make a real production balancing decision (feature-flagged off, spec §57).
_SATURATION_STREAK_THRESHOLD = 3
_HIGH_CAMPAIGN_SHARE_THRESHOLD = 0.5


@dataclass(frozen=True)
class EditorialNeed:
    saturated_topic: str | None
    saturated_entity: str | None
    saturated_source: str | None
    feed_too_commercial: bool
    notes: list[str]


def derive_editorial_need(feed_state: FeedState) -> EditorialNeed:
    notes: list[str] = []

    saturated_topic = None
    if feed_state.topic_streak >= _SATURATION_STREAK_THRESHOLD and feed_state.topic_distribution:
        top_topic = max(feed_state.topic_distribution, key=lambda k: feed_state.topic_distribution[k])
        saturated_topic = top_topic
        notes.append(f"topic saturation: {feed_state.topic_streak} consecutive posts on {top_topic!r}")

    saturated_entity = None
    if feed_state.entity_streak >= _SATURATION_STREAK_THRESHOLD and feed_state.entity_distribution:
        top_entity = max(feed_state.entity_distribution, key=lambda k: feed_state.entity_distribution[k])
        saturated_entity = top_entity
        notes.append(f"entity saturation: {feed_state.entity_streak} consecutive posts on {top_entity!r}")

    saturated_source = None
    if feed_state.source_streak >= _SATURATION_STREAK_THRESHOLD and feed_state.source_distribution:
        top_source = max(feed_state.source_distribution, key=lambda k: feed_state.source_distribution[k])
        saturated_source = top_source
        notes.append(f"source saturation: {feed_state.source_streak} consecutive posts from {top_source!r}")

    total_recent = feed_state.posts_24h
    commercial_share = (feed_state.recent_campaign_post_count / total_recent) if total_recent > 0 else 0.0
    feed_too_commercial = commercial_share >= _HIGH_CAMPAIGN_SHARE_THRESHOLD
    if feed_too_commercial:
        notes.append(f"feed too commercial: {commercial_share:.0%} of recent posts are campaign-linked")

    return EditorialNeed(
        saturated_topic=saturated_topic, saturated_entity=saturated_entity, saturated_source=saturated_source,
        feed_too_commercial=feed_too_commercial, notes=notes,
    )
