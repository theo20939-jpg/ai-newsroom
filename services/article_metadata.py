"""Phase 16 M2: article-page image metadata discovery (docs/phase16_m2_secure_fetch_and_
validation_report.md §10/§11). Pure HTML parsing only - the caller (services/image_intelligence.py)
owns fetching the page through integrations/http/safe_fetch.py and deciding whether the response's
declared Content-Type is HTML-like before ever calling this module.

Supports exactly the methods listed in the M2 task brief - og:image(:url/:secure_url/:width/
:height/:alt), twitter:image(:src), <link rel="image_src">, and JSON-LD Article/NewsArticle image
(string, ImageObject, array, @graph-wrapped). No generic visual DOM hero-image heuristic, no
crawling of linked pages, no JavaScript execution, no browser - all explicitly out of M2 scope.

Uses Python's stdlib `html.parser.HTMLParser` only - matches services/image_intelligence.py's own
M1 precedent (`_ImgTagCollector`) of avoiding a new HTML-parsing dependency (no BeautifulSoup/lxml).
"""
import json
import logging
from html.parser import HTMLParser
from urllib.parse import urljoin

from schemas.image_candidate import ImageDiscoveryMethod, NativeMediaHint

logger = logging.getLogger(__name__)

_MAX_ALT_TEXT_LENGTH = 300


class _MetadataCollector(HTMLParser):
    """Collects `<meta>`/`<link>` attributes and the raw text of every `application/ld+json`
    `<script>` block, in document order. `convert_charrefs=True` (the default) already HTML-entity
    -decodes attribute values."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta_tags: list[dict[str, str]] = []
        self.link_tags: list[dict[str, str]] = []
        self.jsonld_blocks: list[str] = []
        self._in_jsonld_script = False
        self._jsonld_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered_tag = tag.lower()
        attrs_dict = {name.lower(): value for name, value in attrs if value is not None}
        if lowered_tag == "meta":
            self.meta_tags.append(attrs_dict)
        elif lowered_tag == "link":
            self.link_tags.append(attrs_dict)
        elif lowered_tag == "script" and attrs_dict.get("type", "").lower() == "application/ld+json":
            self._in_jsonld_script = True
            self._jsonld_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_jsonld_script:
            self.jsonld_blocks.append("".join(self._jsonld_buffer))
            self._in_jsonld_script = False

    def handle_data(self, data: str) -> None:
        if self._in_jsonld_script:
            self._jsonld_buffer.append(data)


def _safe_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _resolve_url(raw_url: str | None, base_url: str) -> str | None:
    if not raw_url or not raw_url.strip():
        return None
    return urljoin(base_url, raw_url.strip())


def _truncated_alt(alt: str | None) -> str | None:
    return alt[:_MAX_ALT_TEXT_LENGTH] if alt else None


def _extract_og_image_entries(meta_tags: list[dict[str, str]]) -> list[dict[str, str | None]]:
    """Groups `og:image*` meta tags into per-image entries, following the Open Graph convention
    that `og:image:width`/`:height`/`:alt`/`:secure_url` apply to the most recently declared
    `og:image`/`og:image:url` tag."""
    entries: list[dict[str, str | None]] = []
    current: dict[str, str | None] | None = None
    for tag in meta_tags:
        prop = (tag.get("property") or tag.get("name") or "").lower()
        content = tag.get("content")
        if not content:
            continue
        if prop in ("og:image", "og:image:url"):
            current = {"url": content, "secure_url": None, "width": None, "height": None, "alt": None}
            entries.append(current)
        elif prop == "og:image:secure_url":
            if current is None:
                current = {"url": None, "secure_url": content, "width": None, "height": None, "alt": None}
                entries.append(current)
            else:
                current["secure_url"] = content
        elif prop == "og:image:width" and current is not None:
            current["width"] = content
        elif prop == "og:image:height" and current is not None:
            current["height"] = content
        elif prop == "og:image:alt" and current is not None:
            current["alt"] = content
    return entries


def _flatten_jsonld_nodes(data: object) -> list[dict]:
    """Every dict node reachable from a JSON-LD document, including `@graph`-wrapped nodes."""
    if isinstance(data, list):
        nodes: list[dict] = []
        for item in data:
            nodes.extend(_flatten_jsonld_nodes(item))
        return nodes
    if isinstance(data, dict):
        nodes = [data]
        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                nodes.extend(_flatten_jsonld_nodes(item))
        return nodes
    return []


def _jsonld_image_urls(image_field: object) -> list[str]:
    """Handles every shape schema.org allows for `image`: a plain URL string, an `ImageObject`
    (`url` or `contentUrl`), or an array of either."""
    if isinstance(image_field, str):
        return [image_field]
    if isinstance(image_field, dict):
        url = image_field.get("url") or image_field.get("contentUrl")
        return [url] if isinstance(url, str) else []
    if isinstance(image_field, list):
        urls: list[str] = []
        for item in image_field:
            urls.extend(_jsonld_image_urls(item))
        return urls
    return []


def _extract_jsonld_image_urls(jsonld_blocks: list[str]) -> list[str]:
    urls: list[str] = []
    for block in jsonld_blocks:
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue  # malformed JSON-LD must never crash extraction
        for node in _flatten_jsonld_nodes(data):
            image_field = node.get("image")
            if image_field is not None:
                urls.extend(_jsonld_image_urls(image_field))
    return urls


def extract_article_image_metadata(html: str, *, base_url: str) -> list[NativeMediaHint]:
    """The sole entry point. Returns hints in deterministic priority order (og:image:secure_url >
    og:image > JSON-LD > twitter:image > image_src link) - callers/consolidation decide final
    ranking and truncation; nothing here drops a discovered candidate. URL validity (scheme,
    malformed-ness) is deliberately not checked here - centralized in services.image_intelligence.
    consolidate_candidates(), exactly mirroring the M1 RSS-extraction split of "extraction
    interprets structure, consolidation judges safety."""
    if not html:
        return []

    parser = _MetadataCollector()
    try:
        parser.feed(html)
    except Exception:
        logger.warning("article_metadata_html_parse_failed")
        return []

    hints: list[NativeMediaHint] = []
    og_entries = _extract_og_image_entries(parser.meta_tags)

    for entry in og_entries:
        url = _resolve_url(entry.get("secure_url"), base_url)
        if url:
            hints.append(
                NativeMediaHint(
                    discovery_method=ImageDiscoveryMethod.OPEN_GRAPH_SECURE_IMAGE,
                    remote_url=url,
                    source_url=base_url,
                    declared_width=_safe_int(entry.get("width")),
                    declared_height=_safe_int(entry.get("height")),
                    alt_text=_truncated_alt(entry.get("alt")),
                )
            )

    for entry in og_entries:
        url = _resolve_url(entry.get("url"), base_url)
        if url:
            hints.append(
                NativeMediaHint(
                    discovery_method=ImageDiscoveryMethod.OPEN_GRAPH_IMAGE,
                    remote_url=url,
                    source_url=base_url,
                    declared_width=_safe_int(entry.get("width")),
                    declared_height=_safe_int(entry.get("height")),
                    alt_text=_truncated_alt(entry.get("alt")),
                )
            )

    for raw_url in _extract_jsonld_image_urls(parser.jsonld_blocks):
        url = _resolve_url(raw_url, base_url)
        if url:
            hints.append(NativeMediaHint(discovery_method=ImageDiscoveryMethod.JSONLD_ARTICLE_IMAGE, remote_url=url, source_url=base_url))

    for tag in parser.meta_tags:
        name = (tag.get("name") or tag.get("property") or "").lower()
        if name in ("twitter:image", "twitter:image:src"):
            url = _resolve_url(tag.get("content"), base_url)
            if url:
                hints.append(NativeMediaHint(discovery_method=ImageDiscoveryMethod.TWITTER_IMAGE, remote_url=url, source_url=base_url))

    for tag in parser.link_tags:
        rel_values = (tag.get("rel") or "").lower().split()
        if "image_src" in rel_values:
            url = _resolve_url(tag.get("href"), base_url)
            if url:
                hints.append(NativeMediaHint(discovery_method=ImageDiscoveryMethod.IMAGE_SRC_LINK, remote_url=url, source_url=base_url))

    return hints
