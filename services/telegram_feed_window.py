"""DIRECTOR-CONTROL-PLANE-1A §10-11: the bounded, structured Telegram feed window Directors
actually consume. Built from services/telegram_channel_context.py's own real Telethon fetch (once
a surface is registered) + the SAME canonical services/social_learning_boundary.py::
is_eligible_for_first_party_learning() every other first-party-evidence consumer already uses -
never a second, competing eligibility check.

CRITICAL product distinction (spec §10): READ_CONTEXT_ELIGIBLE and PERFORMANCE_LEARNING_ELIGIBLE
are deliberately separate booleans on every post - a legacy NINJA VPN post is ALWAYS
read_context_eligible (understand what the current audience already saw, understand the pre-
rebrand feed) but performance_learning_eligible only when it is at/after the real
`learning_start_at` boundary AND the historical_content_policy allows it. No caller may ever use
`performance_learning_eligible=False` posts as PULSE audience-preference evidence."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from database.models.social_launch_context import SocialLaunchContext
from services.social_learning_boundary import is_eligible_for_first_party_learning


@dataclass(frozen=True)
class TelegramFeedPost:
    post_id: int
    timestamp: datetime | None
    is_legacy: bool
    media_type: str | None
    text_length: int
    views: int | None
    reactions_total: int | None
    forwards: int | None
    read_context_eligible: bool
    performance_learning_eligible: bool
    source: str = "telegram_own_channel"


@dataclass(frozen=True)
class TelegramFeedWindow:
    surface_registered: bool
    posts: list[TelegramFeedPost] = field(default_factory=list)
    # DIRECTOR-CONTROL-PLANE-1A §11's own explicit "topic repetition features" - a bounded,
    # deterministic count of posts per coarse media_type bucket, never raw text/media passed
    # through wholesale.
    media_type_distribution: dict[str, int] = field(default_factory=dict)

    @property
    def learning_eligible_posts(self) -> list[TelegramFeedPost]:
        return [p for p in self.posts if p.performance_learning_eligible]

    @property
    def legacy_posts(self) -> list[TelegramFeedPost]:
        return [p for p in self.posts if p.is_legacy]


def build_telegram_feed_window(
    raw_context: dict | None, *, launch_context: SocialLaunchContext | None,
) -> TelegramFeedWindow:
    """Pure, deterministic - no I/O, no Telethon call itself (that already happened in services/
    telegram_channel_context.py::fetch_owned_channel_context(), whose output is `raw_context`
    here). `raw_context=None` (no surface registered, or the real fetch failed/was unauthorized)
    returns an honestly empty window, never a fabricated one."""
    if raw_context is None:
        return TelegramFeedWindow(surface_registered=False)

    posts: list[TelegramFeedPost] = []
    media_counter: dict[str, int] = {}
    for raw_post in raw_context.get("recent_posts", []):
        timestamp = _parse_timestamp(raw_post.get("date"))
        performance_learning_eligible = (
            timestamp is not None
            and is_eligible_for_first_party_learning(published_at=timestamp, launch_context=launch_context)
        )
        is_legacy = not performance_learning_eligible
        media_type = raw_post.get("media_type")
        if media_type:
            media_counter[media_type] = media_counter.get(media_type, 0) + 1
        posts.append(TelegramFeedPost(
            post_id=raw_post["message_id"], timestamp=timestamp, is_legacy=is_legacy,
            media_type=media_type, text_length=raw_post.get("text_length", 0),
            views=raw_post.get("views"), reactions_total=raw_post.get("reactions_total"),
            forwards=raw_post.get("forwards"),
            # Spec §10's own explicit "ALLOWED: understand what the current audience saw" - every
            # fetched post is read-context eligible regardless of the learning boundary; only
            # PERFORMANCE learning is gated.
            read_context_eligible=True, performance_learning_eligible=performance_learning_eligible,
        ))

    return TelegramFeedWindow(surface_registered=True, posts=posts, media_type_distribution=media_counter)


def _parse_timestamp(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
