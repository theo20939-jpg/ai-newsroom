"""DIRECTOR-CONTROL-PLANE-1A §13: the bounded, structured Instagram feed context Instagram
Directors actually consume - structurally mirrors services/telegram_feed_window.py's own
TelegramFeedWindow (same field shape, same legacy-vs-learning-eligible separation), but for
Instagram's own real state today: `services/instagram_graph_adapter.py::is_configured()` is False
in this environment (no live Meta Graph API credentials exist), so `raw_media` is always None in
practice and this module always returns an honestly empty context - never a fabricated post list.

The module still exists as real, real, wired code (not a stub) so that the moment a real Instagram
connection exists, `build_instagram_feed_context()` only needs a real `raw_media` list from a
future `services/instagram_graph_adapter.py::fetch_recent_media()` implementation - no Director
call site changes are needed, exactly like the Telegram feed window's own "raw_context=None ->
empty window" contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from database.models.social_launch_context import SocialLaunchContext
from services.instagram_connection_readiness import InstagramReadinessState
from services.social_learning_boundary import is_eligible_for_first_party_learning


@dataclass(frozen=True)
class InstagramFeedPost:
    media_id: str
    timestamp: datetime | None
    is_legacy: bool
    media_type: str | None
    caption_length: int
    like_count: int | None
    comment_count: int | None
    read_context_eligible: bool
    performance_learning_eligible: bool
    source: str = "instagram_own_account"


@dataclass(frozen=True)
class InstagramFeedContext:
    readiness_state: InstagramReadinessState
    posts: list[InstagramFeedPost] = field(default_factory=list)
    media_type_distribution: dict[str, int] = field(default_factory=dict)

    @property
    def learning_eligible_posts(self) -> list[InstagramFeedPost]:
        return [p for p in self.posts if p.performance_learning_eligible]

    @property
    def legacy_posts(self) -> list[InstagramFeedPost]:
        return [p for p in self.posts if p.is_legacy]


def build_instagram_feed_context(
    raw_media: list[dict] | None, *, readiness_state: InstagramReadinessState,
    launch_context: SocialLaunchContext | None,
) -> InstagramFeedContext:
    """Pure, deterministic - no I/O. `raw_media=None` (today's honest reality: not connected, or a
    connected fetch has not been implemented/run) returns an empty-but-correctly-labeled context -
    `readiness_state` still carries real information (NOT_CONFIGURED vs CONNECTED-but-no-media-yet)
    even when `posts` is empty, so callers never conflate "no account" with "account with 0 posts"."""
    if raw_media is None:
        return InstagramFeedContext(readiness_state=readiness_state)

    posts: list[InstagramFeedPost] = []
    media_counter: dict[str, int] = {}
    for raw_post in raw_media:
        timestamp = _parse_timestamp(raw_post.get("timestamp"))
        performance_learning_eligible = (
            timestamp is not None
            and is_eligible_for_first_party_learning(published_at=timestamp, launch_context=launch_context)
        )
        is_legacy = not performance_learning_eligible
        media_type = raw_post.get("media_type")
        if media_type:
            media_counter[media_type] = media_counter.get(media_type, 0) + 1
        posts.append(InstagramFeedPost(
            media_id=raw_post["media_id"], timestamp=timestamp, is_legacy=is_legacy,
            media_type=media_type, caption_length=raw_post.get("caption_length", 0),
            like_count=raw_post.get("like_count"), comment_count=raw_post.get("comment_count"),
            read_context_eligible=True, performance_learning_eligible=performance_learning_eligible,
        ))

    return InstagramFeedContext(
        readiness_state=readiness_state, posts=posts, media_type_distribution=media_counter,
    )


def _parse_timestamp(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
