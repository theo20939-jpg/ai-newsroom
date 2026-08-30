"""Phase 19 M10: video-candidate discovery shapes - mirrors schemas/image_candidate.py's own
NativeMediaHint/ImageDiscoveryMethod convention exactly, scoped to the bounded discovery sources
the M10 authorization allows (RSS enclosure/media_content video, HTML <video>/<source>, og:video*,
Twitter Player Card, and YouTube/Vimeo/explicit-official links already present in the selected
article HTML) - no open web search, no video search engine, no YouTube/Vimeo API.
"""
from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict


class VideoDiscoveryMethod(str, enum.Enum):
    RSS_MEDIA_CONTENT_VIDEO = "rss_media_content_video"
    RSS_ENCLOSURE_VIDEO = "rss_enclosure_video"
    HTML_VIDEO_TAG = "html_video_tag"
    OPEN_GRAPH_VIDEO_SECURE = "open_graph_video_secure"
    OPEN_GRAPH_VIDEO = "open_graph_video"
    TWITTER_PLAYER_CARD = "twitter_player_card"
    HOSTED_PLATFORM_LINK_IN_ARTICLE = "hosted_platform_link_in_article"
    # Phase V2.27A: an <iframe src> or twitter:player (the embed PAGE url, distinct from twitter:
    # player:stream's own direct-media url - see TWITTER_PLAYER_CARD above) already present in the
    # fetched article HTML, for a third-party player that is neither YouTube/Vimeo nor a direct
    # media file - see services/video_discovery.py::is_safe_embed_url()'s own docstring for the
    # real evidence-source restriction (never a bare body-text <a href>, deliberately excluded).
    EMBEDDED_PLAYER_URL = "embedded_player_url"


class VideoPlatform(str, enum.Enum):
    """URL-pattern classification only - never resolved via an API call."""

    YOUTUBE = "youtube"
    VIMEO = "vimeo"
    DIRECT_HOSTED = "direct_hosted"
    # Phase V2.27A: a third-party/publisher-site embedded player URL, evidenced by the article's
    # own HTML (iframe/twitter:player - see VideoDiscoveryMethod.EMBEDDED_PLAYER_URL above) but not
    # recognized as YouTube/Vimeo/a direct media file - real downloadability is unknown until
    # services/hosted_video_download.py actually asks yt-dlp to inspect it (yt-dlp's own generic +
    # site-specific extractors, never a new per-site classifier written here).
    EMBEDDED_PLAYER = "embedded_player"
    UNKNOWN = "unknown"


class NativeVideoHint(BaseModel):
    """What a discovery function produces the instant it sees native video referenced in already-
    fetched RSS/HTML content - before any validation, before any candidate ID is assigned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    discovery_method: VideoDiscoveryMethod
    remote_url: str
    source_url: str | None = None
    platform: VideoPlatform = VideoPlatform.UNKNOWN
    declared_width: int | None = None
    declared_height: int | None = None
    declared_mime_type: str | None = None
    declared_duration_seconds: int | None = None


class VideoValidationStatus(str, enum.Enum):
    VALID = "valid"
    REJECTED = "rejected"
    UNVALIDATED_HOSTED_PLATFORM = "unvalidated_hosted_platform"


class VideoValidation(BaseModel):
    """Direct-hosted candidates only: bounded safe_fetch + byte-size cap + stdlib magic-byte
    sniffing - never ffmpeg, never a real decode. YouTube/Vimeo candidates are validated by URL
    pattern only (VideoValidationStatus.UNVALIDATED_HOSTED_PLATFORM) and never fetched."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: VideoValidationStatus
    detected_container: str | None = None
    byte_size: int | None = None
    error_code: str | None = None
