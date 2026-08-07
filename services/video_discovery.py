"""Phase 19 M10: bounded, source-local video discovery.

Allowed discovery sources ONLY (the overnight authorization's own explicit, closed list):
RSS enclosure `video/*`, RSS `media_content[medium=video]`, HTML `<video>`/`<source>`,
`og:video`/`og:video:url`/`og:video:secure_url`, Twitter Player Card metadata, and YouTube/Vimeo/
explicit-official-video links already present in the selected article HTML. NO open web search,
NO video search engine, NO YouTube/Vimeo API, NO transcoding, NO ffmpeg dependency.

Direct-hosted candidates are validated via `integrations/http/safe_fetch.py::safe_fetch()` (never
a raw client) with a byte-size cap and stdlib magic-byte sniffing only - never a real decode.
YouTube/Vimeo candidates are validated by URL pattern only, never fetched.

Split exactly like services/article_metadata.py/services/image_intelligence.py's own established
"extraction interprets structure, a separate step judges safety/validity" convention.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

from core.config import settings
from integrations.http.safe_fetch import SafeFetchError, SafeFetchPolicy, safe_fetch
from schemas.video_candidate import (
    NativeVideoHint,
    VideoDiscoveryMethod,
    VideoPlatform,
    VideoValidation,
    VideoValidationStatus,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# URL-pattern-only platform classification - never resolved via an API call, never fetched for
# YouTube/Vimeo (docs/phase19_m10_video_discovery.md).
# ---------------------------------------------------------------------------

_YOUTUBE_HOST_RE = re.compile(r"(^|\.)(youtube\.com|youtube-nocookie\.com|youtu\.be)$", re.IGNORECASE)
_VIMEO_HOST_RE = re.compile(r"(^|\.)(vimeo\.com|player\.vimeo\.com)$", re.IGNORECASE)
_DIRECT_VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".m4v", ".ogv")


def classify_video_url(url: str) -> VideoPlatform:
    """Pure, URL-pattern-only. Never inspects the URL's content - only its host/path shape."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return VideoPlatform.UNKNOWN
    host = parsed.hostname or ""
    if _YOUTUBE_HOST_RE.search(host):
        return VideoPlatform.YOUTUBE
    if _VIMEO_HOST_RE.search(host):
        return VideoPlatform.VIMEO
    if parsed.scheme in ("http", "https") and parsed.path.lower().endswith(_DIRECT_VIDEO_EXTENSIONS):
        return VideoPlatform.DIRECT_HOSTED
    return VideoPlatform.UNKNOWN


# ---------------------------------------------------------------------------
# RSS enclosure / media_content video extraction - mirrors services/image_intelligence.py::
# extract_rss_native_media()'s own established shape, filtering FOR video instead of image.
# ---------------------------------------------------------------------------


def _safe_list(entry: Mapping[str, Any], key: str) -> list[Any]:
    value = entry.get(key) if hasattr(entry, "get") else None
    return list(value) if value else []


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _media_content_video_hint(media: Mapping[str, Any]) -> NativeVideoHint | None:
    medium = (media.get("medium") or "").lower()
    mime_type = (media.get("type") or "").lower()
    if medium != "video" and not mime_type.startswith("video/"):
        return None
    url = media.get("url")
    if not url:
        return None
    return NativeVideoHint(
        discovery_method=VideoDiscoveryMethod.RSS_MEDIA_CONTENT_VIDEO, remote_url=url,
        platform=classify_video_url(url), declared_width=_safe_int(media.get("width")),
        declared_height=_safe_int(media.get("height")), declared_mime_type=mime_type or None,
        declared_duration_seconds=_safe_int(media.get("duration")),
    )


def _enclosure_video_hint(enclosure: Mapping[str, Any]) -> NativeVideoHint | None:
    mime_type = (enclosure.get("type") or "").lower()
    if not mime_type.startswith("video/"):
        return None
    url = enclosure.get("href") or enclosure.get("url")
    if not url:
        return None
    return NativeVideoHint(
        discovery_method=VideoDiscoveryMethod.RSS_ENCLOSURE_VIDEO, remote_url=url,
        platform=classify_video_url(url), declared_mime_type=mime_type,
        declared_width=_safe_int(enclosure.get("width")), declared_height=_safe_int(enclosure.get("height")),
    )


def extract_rss_native_video(entry: Mapping[str, Any]) -> list[NativeVideoHint]:
    """Extraction failure for any single item must never break extraction of the rest - mirrors
    extract_rss_native_media()'s own per-item try/except-at-the-caller discipline (the caller,
    integrations/sources/rss_source.py-style adapters, wraps this whole call)."""
    hints: list[NativeVideoHint] = []
    for media in _safe_list(entry, "media_content"):
        hint = _media_content_video_hint(media)
        if hint is not None:
            hints.append(hint)
    for enclosure in _safe_list(entry, "enclosures"):
        hint = _enclosure_video_hint(enclosure)
        if hint is not None:
            hints.append(hint)
    return hints


# ---------------------------------------------------------------------------
# Article-page HTML video metadata discovery - mirrors services/article_metadata.py's own
# stdlib-HTMLParser-only convention exactly (no BeautifulSoup/lxml).
# ---------------------------------------------------------------------------


class _VideoMetadataCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta_tags: list[dict[str, str]] = []
        self.video_tags: list[dict[str, str]] = []
        self.source_tags: list[dict[str, str]] = []
        self.anchor_hrefs: list[str] = []
        self.iframe_srcs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered_tag = tag.lower()
        attrs_dict = {name.lower(): value for name, value in attrs if value is not None}
        if lowered_tag == "meta":
            self.meta_tags.append(attrs_dict)
        elif lowered_tag == "video":
            self.video_tags.append(attrs_dict)
        elif lowered_tag == "source":
            self.source_tags.append(attrs_dict)
        elif lowered_tag == "a" and attrs_dict.get("href"):
            self.anchor_hrefs.append(attrs_dict["href"])
        elif lowered_tag == "iframe" and attrs_dict.get("src"):
            self.iframe_srcs.append(attrs_dict["src"])


def _resolve_url(raw_url: str | None, base_url: str) -> str | None:
    if not raw_url or not raw_url.strip():
        return None
    return urljoin(base_url, raw_url.strip())


def extract_article_video_metadata(html: str, *, base_url: str) -> list[NativeVideoHint]:
    """The sole entry point for article-page discovery. Returns hints in the deterministic
    priority order og:video:secure_url > og:video > <video>/<source> > twitter:player >
    YouTube/Vimeo links already present in the HTML - nothing here drops a discovered candidate."""
    if not html:
        return []

    parser = _VideoMetadataCollector()
    try:
        parser.feed(html)
    except Exception:
        logger.warning("article_video_metadata_html_parse_failed")
        return []

    hints: list[NativeVideoHint] = []

    og_secure_url: str | None = None
    og_url: str | None = None
    og_width: str | None = None
    og_height: str | None = None
    og_type: str | None = None
    for tag in parser.meta_tags:
        prop = (tag.get("property") or tag.get("name") or "").lower()
        content = tag.get("content")
        if not content:
            continue
        if prop == "og:video:secure_url":
            og_secure_url = content
        elif prop in ("og:video", "og:video:url"):
            og_url = content
        elif prop == "og:video:width":
            og_width = content
        elif prop == "og:video:height":
            og_height = content
        elif prop == "og:video:type":
            og_type = content

    if og_secure_url:
        url = _resolve_url(og_secure_url, base_url)
        if url:
            hints.append(
                NativeVideoHint(
                    discovery_method=VideoDiscoveryMethod.OPEN_GRAPH_VIDEO_SECURE, remote_url=url,
                    source_url=base_url, platform=classify_video_url(url),
                    declared_width=_safe_int(og_width), declared_height=_safe_int(og_height),
                    declared_mime_type=og_type,
                )
            )
    if og_url:
        url = _resolve_url(og_url, base_url)
        if url:
            hints.append(
                NativeVideoHint(
                    discovery_method=VideoDiscoveryMethod.OPEN_GRAPH_VIDEO, remote_url=url,
                    source_url=base_url, platform=classify_video_url(url),
                    declared_width=_safe_int(og_width), declared_height=_safe_int(og_height),
                    declared_mime_type=og_type,
                )
            )

    for video_tag in parser.video_tags:
        src = video_tag.get("src")
        url = _resolve_url(src, base_url)
        if url:
            hints.append(
                NativeVideoHint(
                    discovery_method=VideoDiscoveryMethod.HTML_VIDEO_TAG, remote_url=url,
                    source_url=base_url, platform=classify_video_url(url),
                )
            )
    for source_tag in parser.source_tags:
        url = _resolve_url(source_tag.get("src"), base_url)
        if url:
            hints.append(
                NativeVideoHint(
                    discovery_method=VideoDiscoveryMethod.HTML_VIDEO_TAG, remote_url=url,
                    source_url=base_url, platform=classify_video_url(url),
                    declared_mime_type=source_tag.get("type"),
                )
            )

    player_stream: str | None = None
    for tag in parser.meta_tags:
        name = (tag.get("name") or tag.get("property") or "").lower()
        if name == "twitter:player:stream":
            player_stream = tag.get("content")
    if player_stream:
        url = _resolve_url(player_stream, base_url)
        if url:
            hints.append(
                NativeVideoHint(
                    discovery_method=VideoDiscoveryMethod.TWITTER_PLAYER_CARD, remote_url=url,
                    source_url=base_url, platform=classify_video_url(url),
                )
            )

    for href in parser.anchor_hrefs + parser.iframe_srcs:
        url = _resolve_url(href, base_url)
        if url and classify_video_url(url) in (VideoPlatform.YOUTUBE, VideoPlatform.VIMEO):
            hints.append(
                NativeVideoHint(
                    discovery_method=VideoDiscoveryMethod.HOSTED_PLATFORM_LINK_IN_ARTICLE,
                    remote_url=url, source_url=base_url, platform=classify_video_url(url),
                )
            )

    return hints


# ---------------------------------------------------------------------------
# Direct-hosted video validation - bounded safe_fetch + byte-size cap + stdlib magic-byte
# sniffing only. Never ffmpeg, never a real decode, never used for YouTube/Vimeo.
# ---------------------------------------------------------------------------

# MP4/MOV/M4V family: an ISO base media file's 'ftyp' box always starts at byte offset 4.
_MP4_FTYP_OFFSET = 4
_MP4_FTYP_MAGIC = b"ftyp"
# WebM/MKV: EBML header magic at offset 0.
_EBML_MAGIC = b"\x1a\x45\xdf\xa3"


def _sniff_container(data: bytes) -> str | None:
    if len(data) >= _MP4_FTYP_OFFSET + 4 and data[_MP4_FTYP_OFFSET:_MP4_FTYP_OFFSET + 4] == _MP4_FTYP_MAGIC:
        return "mp4"
    if data[:4] == _EBML_MAGIC:
        return "webm_mkv"
    return None


def video_discovery_fetch_policy() -> SafeFetchPolicy:
    """Builds a SafeFetchPolicy from core/config.py's own video_discovery_* bounds - mirrors
    services/article_acquisition.py::_fetch_policy()'s identical pattern, exported (not
    module-private) since services/article_acquisition.py is the one caller that needs it, from
    the module that owns the bounded-fetch validation logic itself."""
    return SafeFetchPolicy(
        connect_timeout_seconds=settings.video_discovery_connect_timeout_seconds,
        read_timeout_seconds=settings.video_discovery_read_timeout_seconds,
        total_timeout_seconds=settings.video_discovery_total_timeout_seconds,
        max_redirects=settings.video_discovery_max_redirects,
        max_bytes=settings.video_discovery_max_bytes,
    )


async def validate_direct_hosted_video(url: str, *, policy: SafeFetchPolicy) -> VideoValidation:
    """Direct-hosted candidates only - the caller must never call this for a YouTube/Vimeo URL
    (see classify_video_url()). Bounded by `policy.max_bytes`, exactly like every other
    safe_fetch() caller in this codebase - never an unbounded download."""
    try:
        result = await safe_fetch(url, policy=policy)
    except SafeFetchError as error:
        return VideoValidation(status=VideoValidationStatus.REJECTED, error_code=error.code.value)

    container = _sniff_container(result.body)
    if container is None:
        return VideoValidation(
            status=VideoValidationStatus.REJECTED, byte_size=result.received_byte_count,
            error_code="signature_mismatch",
        )
    return VideoValidation(
        status=VideoValidationStatus.VALID, detected_container=container,
        byte_size=result.received_byte_count,
    )
