"""NINJA Social Intelligence Foundation, Part IV §94: Instagram Platform Capabilities Registry.
Built from a real forensic sweep of this codebase (grepped for "instagram"/"meta_api"/
"graph.facebook" across services/, integrations/, bot/) - the only real hits are
`core/config.py::instagram_topic_id` (an internal Telegram forum-topic setting for discussing
Instagram content INSIDE the newsroom chat, not an Instagram API integration at all) and unrelated
matches in services/beginner_friendly.py/services/news_editorial_relevance.py. There is no Meta
Graph API client, no Instagram credential setting, no publish/read call anywhere. Every capability
below is therefore honestly UNAVAILABLE - never guessed as AVAILABLE from memory (spec §94's own
explicit "Do not assume Meta API capability from memory" instruction)."""
from __future__ import annotations

import enum
from dataclasses import dataclass


class CapabilityStatus(str, enum.Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    MANUAL_ONLY = "manual_only"


@dataclass(frozen=True)
class PlatformCapability:
    name: str
    status: CapabilityStatus
    evidence: str


_NO_META_INTEGRATION_EVIDENCE = (
    "No Meta Graph API client, no Instagram credential setting, and no publish/read call exist "
    "anywhere in this codebase (forensic sweep, this module's own docstring) - this phase adds no "
    "credentials and makes no live capability claim."
)

INSTAGRAM_PLATFORM_CAPABILITIES: dict[str, PlatformCapability] = {
    "publish_single": PlatformCapability("publish_single", CapabilityStatus.UNAVAILABLE, _NO_META_INTEGRATION_EVIDENCE),
    "publish_carousel": PlatformCapability("publish_carousel", CapabilityStatus.UNAVAILABLE, _NO_META_INTEGRATION_EVIDENCE),
    "publish_reel": PlatformCapability("publish_reel", CapabilityStatus.UNAVAILABLE, _NO_META_INTEGRATION_EVIDENCE),
    "publish_story": PlatformCapability("publish_story", CapabilityStatus.UNAVAILABLE, _NO_META_INTEGRATION_EVIDENCE),
    "read_insights": PlatformCapability("read_insights", CapabilityStatus.UNAVAILABLE, _NO_META_INTEGRATION_EVIDENCE),
    "read_post_insights": PlatformCapability("read_post_insights", CapabilityStatus.UNAVAILABLE, _NO_META_INTEGRATION_EVIDENCE),
    "read_reel_insights": PlatformCapability("read_reel_insights", CapabilityStatus.UNAVAILABLE, _NO_META_INTEGRATION_EVIDENCE),
    "read_comments": PlatformCapability("read_comments", CapabilityStatus.UNAVAILABLE, _NO_META_INTEGRATION_EVIDENCE),
    "read_follower_stats": PlatformCapability("read_follower_stats", CapabilityStatus.UNAVAILABLE, _NO_META_INTEGRATION_EVIDENCE),
    "read_profile_metrics": PlatformCapability("read_profile_metrics", CapabilityStatus.UNAVAILABLE, _NO_META_INTEGRATION_EVIDENCE),
    "read_follower_count": PlatformCapability("read_follower_count", CapabilityStatus.UNAVAILABLE, _NO_META_INTEGRATION_EVIDENCE),
    "audio_trend_data": PlatformCapability("audio_trend_data", CapabilityStatus.UNKNOWN, "No first-party or third-party audio-trend data source is wired anywhere - never verified either way."),
    "collab_posting": PlatformCapability("collab_posting", CapabilityStatus.UNAVAILABLE, _NO_META_INTEGRATION_EVIDENCE),
    "creator_discovery": PlatformCapability("creator_discovery", CapabilityStatus.UNKNOWN, "No creator-discovery data source is wired anywhere - never verified either way."),
    "stories_publishing": PlatformCapability("stories_publishing", CapabilityStatus.UNAVAILABLE, _NO_META_INTEGRATION_EVIDENCE),
}


def get_capability(name: str) -> PlatformCapability | None:
    return INSTAGRAM_PLATFORM_CAPABILITIES.get(name)
