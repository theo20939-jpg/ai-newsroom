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

import ipaddress
import logging
import re
from collections.abc import Mapping
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

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

# Video Shadow Checkpoint follow-up (real live evidence: 14/19 = 74% of "hosted-platform" hints in
# a ~75-minute shadow sample were channel/user/handle/subscribe links, not actual videos - see
# docs/video_shadow_checkpoint.md §8). A YouTube/Vimeo HOSTNAME match alone is no longer
# sufficient evidence of an actual playable video - the path/query shape must also identify one of
# a small, explicitly bounded set of known real video-URL forms. Deliberately conservative: an
# unrecognized path on a real YouTube/Vimeo host now classifies as UNKNOWN rather than guessing.
_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _is_youtube_video_path(path: str, query: str) -> bool:
    """Accepts only: /watch?v=<id>, youtu.be's own /<id> (handled by the caller via host check),
    /shorts/<id>, /embed/<id>. Rejects everything else (channel/user/@handle/c/feed/results/
    playlist/subscribe/bare-host/other navigation paths) - the exact bounded list the corrective
    phase specified, not broadened beyond it."""
    normalized = path.rstrip("/") or "/"
    if normalized == "/watch":
        video_id = (parse_qs(query).get("v") or [""])[0]
        return bool(_YOUTUBE_ID_RE.match(video_id))
    segments = [s for s in path.split("/") if s]
    if len(segments) >= 2 and segments[0] in ("shorts", "embed"):
        return bool(_YOUTUBE_ID_RE.match(segments[1]))
    return False


def _is_youtu_be_video_path(path: str) -> bool:
    segments = [s for s in path.split("/") if s]
    return len(segments) >= 1 and bool(_YOUTUBE_ID_RE.match(segments[0]))


def _is_vimeo_video_path(host: str, path: str) -> bool:
    """Accepts only a numeric video-id path (vimeo.com/<digits>[/<privacy-hash>], player.vimeo.com/
    video/<digits>) - a Vimeo username/channel/showcase slug is never purely numeric, which is
    exactly the deterministic, safe signal this reuses; never broadened beyond it."""
    segments = [s for s in path.split("/") if s]
    if host.lower().endswith("player.vimeo.com"):
        return len(segments) >= 2 and segments[0] == "video" and segments[1].isdigit()
    return len(segments) >= 1 and segments[0].isdigit()


def classify_video_url(url: str) -> VideoPlatform:
    """Pure, URL-pattern-only, no network call. Host match alone is never sufficient for YouTube/
    Vimeo - see _is_youtube_video_path()/_is_vimeo_video_path() above for the exact accepted
    shapes."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return VideoPlatform.UNKNOWN
    host = parsed.hostname or ""
    if _YOUTUBE_HOST_RE.search(host):
        if host.lower().endswith("youtu.be"):
            return VideoPlatform.YOUTUBE if _is_youtu_be_video_path(parsed.path) else VideoPlatform.UNKNOWN
        return VideoPlatform.YOUTUBE if _is_youtube_video_path(parsed.path, parsed.query) else VideoPlatform.UNKNOWN
    if _VIMEO_HOST_RE.search(host):
        return VideoPlatform.VIMEO if _is_vimeo_video_path(host, parsed.path) else VideoPlatform.UNKNOWN
    if parsed.scheme in ("http", "https") and parsed.path.lower().endswith(_DIRECT_VIDEO_EXTENSIONS):
        return VideoPlatform.DIRECT_HOSTED
    return VideoPlatform.UNKNOWN


# ---------------------------------------------------------------------------
# Phase V2.27A - source-site/third-party embedded player support (Case C from the V2.27 wiring
# audit): a URL already evidenced by the article's own HTML as an embedded player (<iframe src>,
# twitter:player - never a bare body-text <a href>, see extract_article_video_metadata() below)
# but not YouTube/Vimeo/a direct media file. Real downloadability is unknown until services/
# hosted_video_download.py actually asks yt-dlp to inspect it - this function only gates whether
# that URL is safe enough to even attempt, never a downloadability check itself.
# ---------------------------------------------------------------------------

_EMBED_PATH_DENYLIST_SEGMENTS = frozenset({
    "channel", "channels", "user", "users", "profile", "profiles", "playlist", "playlists",
    "search", "results", "subscribe", "subscriptions", "tag", "tags", "category", "categories",
    "feed", "feeds", "topics", "c",
})
_EMBED_HOSTNAME_DENYLIST_SUFFIXES = (".local", ".localdomain", ".internal", ".home", ".lan")


def is_safe_embed_url(url: str) -> bool:
    """Best-effort safety pre-filter for a third-party embedded-player URL. Unlike
    classify_video_url()'s YouTube/Vimeo check (an exact, closed hostname + path-shape allowlist),
    an arbitrary publisher embed domain cannot be allowlisted the same way - this is necessarily a
    denylist-based heuristic, not a guarantee, and is disclosed as such rather than oversold.

    NOT a substitute for integrations/http/safe_fetch.py's own DNS-rebinding-resistant, IP-pinned
    SSRF protection - yt-dlp performs its own networking as a subprocess this codebase does not
    control the sockets of, so a malicious DNS answer returned only at yt-dlp's own connection
    time cannot be prevented from here. This function only rejects the cheap, obvious cases: a
    literal loopback/private/link-local/reserved/multicast IP, a well-known non-routable hostname
    suffix, and a small set of known non-single-video path markers (channel/playlist/search/etc.,
    mirroring the same real evidence category _is_youtube_video_path()/_is_vimeo_video_path()
    above already reject for YouTube/Vimeo specifically) - real, disclosed limitations, never a
    claim of complete SSRF hardening for an arbitrary third-party host."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    lowered_host = hostname.lower()
    if lowered_host == "localhost" or lowered_host.endswith(_EMBED_HOSTNAME_DENYLIST_SUFFIXES):
        return False
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved
        or ip.is_multicast or ip.is_unspecified
    ):
        return False
    if not parsed.path or parsed.path == "/":
        return False  # bare host, no specific resource - too weak evidence of one specific video
    path_segments = {s.lower() for s in parsed.path.split("/") if s}
    if path_segments & _EMBED_PATH_DENYLIST_SEGMENTS:
        return False
    query_keys = {k.lower() for k in parse_qs(parsed.query)}
    if "list" in query_keys or "q" in query_keys:
        return False
    return True


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
    player_page: str | None = None
    for tag in parser.meta_tags:
        name = (tag.get("name") or tag.get("property") or "").lower()
        if name == "twitter:player:stream":
            player_stream = tag.get("content")
        elif name == "twitter:player":
            # Phase V2.27A: the embed PAGE url (an iframe target), distinct from twitter:player:
            # stream's own direct-media url above - real evidence of a third-party embedded
            # player, handled below alongside <iframe src>, never alongside player_stream.
            player_page = tag.get("content")
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

    # Phase V2.27A (Case C - source-site/third-party embedded player): a URL structurally
    # evidenced by the article as an embed target (<iframe src>, twitter:player) that is NOT
    # YouTube/Vimeo/a direct file - deliberately restricted to iframe_srcs + the twitter:player
    # meta tag ONLY, never anchor_hrefs (a bare body-text <a href> is far weaker evidence - it
    # could be any link in the article, including navigation/share links, not necessarily an
    # embedded player at all).
    for embed_url_raw in [*parser.iframe_srcs, *([player_page] if player_page else [])]:
        url = _resolve_url(embed_url_raw, base_url)
        if url is None:
            continue
        platform = classify_video_url(url)
        if platform in (VideoPlatform.YOUTUBE, VideoPlatform.VIMEO):
            continue  # already captured above with its own real platform, never duplicated here
        if is_safe_embed_url(url):
            hints.append(
                NativeVideoHint(
                    discovery_method=VideoDiscoveryMethod.EMBEDDED_PLAYER_URL, remote_url=url,
                    source_url=base_url, platform=VideoPlatform.EMBEDDED_PLAYER,
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
