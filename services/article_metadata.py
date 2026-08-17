"""Phase 16 M2: article-page image metadata discovery (docs/phase16_m2_secure_fetch_and_
validation_report.md §10/§11). Pure HTML parsing only - the caller (services/image_intelligence.py)
owns fetching the page through integrations/http/safe_fetch.py and deciding whether the response's
declared Content-Type is HTML-like before ever calling this module.

Supports exactly the methods listed in the M2 task brief - og:image(:url/:secure_url/:width/
:height/:alt), twitter:image(:src), <link rel="image_src">, and JSON-LD Article/NewsArticle image
(string, ImageObject, array, @graph-wrapped). No crawling of linked pages, no JavaScript execution,
no browser - explicitly out of scope.

Image Discovery Upgrade (forensic-audit follow-up): `extract_inline_article_images()` below adds a
second, independent extractor - real <img>/<picture><source> tags found in the article BODY, not
just head metadata. Root cause this addresses: most publishers point every head-metadata tag
(og:image, og:image:secure_url, twitter:image, JSON-LD image) at the same single canonical share
image, so `extract_article_image_metadata()` alone routinely discovers 3-5 *hints* that resolve to
only 1 *distinct* photo. This is a bounded, deterministic tag scan (a fixed priority-container
allowlist plus a fixed reject-token list, both below) - never a generic "guess the hero image"
visual/ML heuristic, never a second HTTP request (works only on the HTML already fetched by the
caller), never a browser/DOM render.

Uses Python's stdlib `html.parser.HTMLParser` only - matches services/image_intelligence.py's own
M1 precedent (`_ImgTagCollector`) of avoiding a new HTML-parsing dependency (no BeautifulSoup/lxml).
"""
import json
import logging
import re
from dataclasses import dataclass
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


# ---------------------------------------------------------------------------------------------
# Image Discovery Upgrade: inline article-body image discovery (second, independent extractor -
# see module docstring for why this exists).
# ---------------------------------------------------------------------------------------------

# Real HTML5 sectioning tags (docs' own priority list) - matched by tag name.
_PRIORITY_CONTAINER_TAGS = frozenset({"article", "main"})
# Not real tag names - common CMS class/id naming conventions for a body-content wrapper (docs'
# own priority list) - matched as a substring of the element's own `class`/`id` attribute.
_PRIORITY_CONTAINER_CLASS_TOKENS = ("content", "post", "entry", "story")

# 3DNews production forensic (https://3dnews.ru/1146956): the inline extractor correctly found
# the real article image (cdn.3dnews.ru/.../github.jpg, inside article-entry > entry-body >
# js-mediator-article) but ALSO picked up unrelated images from sibling "related content" widgets
# nested in that same priority container - a related-article slider, a "related boxes" grid, and a
# second related-slider variant. Real observed class/id values that triggered this:
#   slider-container id="newsSlider" / slider-track / slider-slide / slider-slide-content
#   content-block relatedbox rbxglob / related-box-item _isrelated
#   content-block related-slider js-related-slider
# Every one of the substrings below is present, case-insensitively, in at least one of those real
# observed values - each token is deliberately specific enough that it does not also appear in
# ordinary article-body class names (unlike "content"/"post"/"story", which the priority-container
# tokens above already claim and which would break the main article body if reused here).
# "recommend" alone (substring) already covers "recommended"/"recommendation" - not listed
# separately. Deliberately NO bare "slider"/"carousel" token: a generic in-article image gallery
# (e.g. class="article-gallery slider-container") must never be excluded on its own - see this
# constant's own module docstring note on why the ancestor-stack mechanism below already gives a
# slider inside an actually-related/news/recommend-labeled ancestor the correct exclusion without
# a bespoke "slider + nearby signal" rule (every real forensic case above already contains
# "related"/"newsslider" directly, so no such generic-slider case has ever been observed to need
# one - if the future ever produces one, it belongs here as its own named, disclosed token, never
# as a blanket "slider" ban).
_SECONDARY_CONTAINER_TOKENS = (
    "related", "recommend", "read-more", "readmore", "more-news", "news-slider", "newsslider",
)

_ICON_TOKENS = ("favicon", "icon", "logo", "avatar", "profile", "sprite")
_AD_TOKENS = ("banner", "ads", "advertisement", "promo")
_TRACKING_TOKENS = ("pixel", "tracking", "analytics")

# The standard HTML5 void-element set - none of these can have children or a matching closing
# tag in ordinary (non-XHTML-self-closed) HTML. `_InlineImageCollector.handle_starttag()` must
# never push one onto its ancestor stack - see that method's own docstring comment for the real,
# confirmed leak this prevents.
_VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
    "source", "track", "wbr",
})

# "если известен размер" (docs) - a candidate with NO declared dimensions is never rejected on
# size alone; only a KNOWN width/height below these floors is excluded.
_MIN_INLINE_WIDTH = 300
_MIN_INLINE_HEIGHT = 200

# "Нельзя собирать все изображения" (docs) - a hard ceiling on how many raw <img>/<source>
# sightings this parser ever holds in memory per article, applied DURING parsing (after the cheap,
# attribute-only filters below, so the budget is spent on plausible candidates, not spent on the
# first 10 icons a page happens to declare before its first real photo - a disclosed, deliberate
# choice, not an oversight). Never adopted from an external default - a fixed, reasoned budget
# matching every other per-event cap this codebase already uses (e.g. `image_intelligence_max_
# candidate_urls_per_event`).
_MAX_RAW_INLINE_CANDIDATES = 10
# "После фильтрации: оставлять максимум 5 лучших" (docs) - the actual function output ceiling.
_MAX_FINAL_INLINE_CANDIDATES = 5

_SRCSET_DESCRIPTOR_RE = re.compile(r"^([\d.]+)(w|x)$")


@dataclass
class _RawInlineImage:
    """One <img>/<source srcset> sighting that already passed the cheap, attribute-only filters
    (never the final decision - `extract_inline_article_images()` still resolves the URL and
    sorts/truncates the survivors)."""

    url_raw: str
    declared_width: int | None
    declared_height: int | None
    alt: str
    position: int
    in_priority_container: bool


def _parse_srcset(srcset: str) -> list[tuple[str, float, str]]:
    """Returns (url, descriptor_value, descriptor_unit) triples in document order. A candidate
    with no descriptor at all gets value=0.0, unit="w" (sorts as the smallest "w" candidate if any
    real "w" descriptors are present, or is returned as-is via `_best_srcset_candidate()`'s own
    no-descriptor fallback otherwise)."""
    entries: list[tuple[str, float, str]] = []
    for part in srcset.split(","):
        pieces = part.strip().split()
        if not pieces or not pieces[0]:
            continue
        url = pieces[0]
        value, unit = 0.0, "w"
        if len(pieces) > 1:
            match = _SRCSET_DESCRIPTOR_RE.match(pieces[1])
            if match:
                value, unit = float(match.group(1)), match.group(2)
        entries.append((url, value, unit))
    return entries


def _best_srcset_candidate(srcset: str) -> tuple[str, int | None] | None:
    """Picks the highest-resolution entry: prefers width ("w") descriptors (returns the declared
    pixel width too, reused as `declared_width` - real evidence, not a guess), falls back to the
    highest pixel-density ("x") descriptor (no derivable pixel width), falls back to the first/only
    URL when no entry carries any descriptor at all. Never a CDN-specific parser (module docstring:
    "это отдельный будущий этап")."""
    entries = _parse_srcset(srcset)
    if not entries:
        return None
    width_entries = [(url, value) for url, value, unit in entries if unit == "w" and value > 0]
    if width_entries:
        url, width = max(width_entries, key=lambda pair: pair[1])
        return url, int(width)
    density_entries = [(url, value) for url, value, unit in entries if unit == "x" and value > 0]
    if density_entries:
        url, _ = max(density_entries, key=lambda pair: pair[1])
        return url, None
    return entries[0][0], None


def _is_priority_container(tag: str, attrs: dict[str, str]) -> bool:
    if tag in _PRIORITY_CONTAINER_TAGS:
        return True
    signal = f"{attrs.get('class', '')} {attrs.get('id', '')}"
    return _matches_any_token(signal, _PRIORITY_CONTAINER_CLASS_TOKENS)


def _is_secondary_container(attrs: dict[str, str]) -> bool:
    """No tag-name signal exists for "this is a related/recommended widget" (unlike <article>/
    <main> for priority containers) - class/id substring only, see _SECONDARY_CONTAINER_TOKENS's
    own docstring for the real forensic values this was calibrated against."""
    signal = f"{attrs.get('class', '')} {attrs.get('id', '')}"
    return _matches_any_token(signal, _SECONDARY_CONTAINER_TOKENS)


def _matches_any_token(haystack: str, tokens: tuple[str, ...]) -> bool:
    lowered = haystack.lower()
    return any(token in lowered for token in tokens)


def _passes_cheap_inline_filters(*, url_raw: str, class_attr: str, id_attr: str, alt: str,
                                  declared_width: int | None, declared_height: int | None) -> bool:
    """Attribute/URL-string-only checks (docs' own filter list) - never requires a network fetch
    or decoded bytes, so this runs safely during parsing, before the raw-candidate budget is
    spent (see `_MAX_RAW_INLINE_CANDIDATES`'s own docstring)."""
    stripped = url_raw.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if lowered.startswith("data:image"):
        return False
    if lowered.split("?", 1)[0].endswith(".svg"):
        return False
    signal = f"{url_raw} {class_attr} {id_attr} {alt}"
    if _matches_any_token(signal, _ICON_TOKENS):
        return False
    if _matches_any_token(signal, _AD_TOKENS):
        return False
    if _matches_any_token(signal, _TRACKING_TOKENS):
        return False
    if declared_width is not None and declared_width < _MIN_INLINE_WIDTH:
        return False
    if declared_height is not None and declared_height < _MIN_INLINE_HEIGHT:
        return False
    return True


def _inline_sort_key(raw: _RawInlineImage) -> tuple[int, int, int]:
    """Best-first ordering, in the docs' own stated priority: (1) image size - larger pixel area
    first; (2) presence of declared width/height - known-size candidates ranked above unknown-size
    ones even when the area itself is 0/unknown; (3) position in the article - earlier first.
    "Отсутствие рекламных признаков" (the docs' own 4th criterion) is not a separate sort key here
    - every survivor already passed `_passes_cheap_inline_filters()`'s hard ad/icon/tracking
    exclusion, so there is nothing left to discriminate on by the time this function runs."""
    has_dims = raw.declared_width is not None and raw.declared_height is not None
    area = (raw.declared_width or 0) * (raw.declared_height or 0)
    return (-area, 0 if has_dims else 1, raw.position)


class _InlineImageCollector(HTMLParser):
    """Single-pass, streaming article-body image scan. Tolerant of unclosed/mismatched tags (real-
    world "tag soup") - an end tag with no matching open tag on the stack is simply ignored, never
    raises, mirrors `_MetadataCollector`'s own "malformed HTML must never crash" discipline."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.raw_images: list[_RawInlineImage] = []
        self.any_priority_container_seen = False
        # (tag, is_priority, is_secondary) - one entry per currently-open element, popped on its
        # own matching end tag (handle_endtag below, unchanged - it only ever reads index 0).
        self._container_stack: list[tuple[str, bool, bool]] = []
        # Each open <picture> gets one entry: True once a child <source srcset> has already
        # contributed a candidate for it - the fallback <img> inside that same <picture> is then
        # skipped (docs: "picture/source", never double-counted against the same visual slot).
        self._picture_stack: list[bool] = []
        self._position = 0

    def _in_priority_container(self) -> bool:
        return any(is_priority for _, is_priority, _ in self._container_stack)

    def _in_secondary_container(self) -> bool:
        """3DNews fix: secondary (related/recommended/read-more) ancestors take priority over
        priority-container membership - an <img> nested inside e.g. entry-body > related-slider
        is excluded even though entry-body itself is a priority container (the task's own explicit
        "secondary ancestor должен иметь приоритет над priority ancestor" requirement)."""
        return any(is_secondary for _, _, is_secondary in self._container_stack)

    def _try_add(self, *, url_raw: str | None, declared_width: int | None, declared_height: int | None,
                 alt: str, class_attr: str, id_attr: str, is_priority: bool, is_secondary: bool) -> bool:
        """Returns True if a candidate was actually added (used by <source>/<img> handling to
        decide whether a <picture>'s fallback <img> should be skipped). `is_priority`/`is_secondary`
        are the void tag's OWN computed flags (img/source are never pushed onto `_container_stack`
        - see its own docstring for why); combined here with `self._in_*_container()`, which now
        reflects only real, still-open ancestors, this reproduces the exact same "does this
        candidate's own class/id or any ancestor's count" semantics the stack-based check gave
        before the void-element fix, just without leaking into siblings."""
        if len(self.raw_images) >= _MAX_RAW_INLINE_CANDIDATES:
            return False
        if is_secondary or self._in_secondary_container():
            return False
        if url_raw is None:
            return False
        if not _passes_cheap_inline_filters(
            url_raw=url_raw, class_attr=class_attr, id_attr=id_attr, alt=alt,
            declared_width=declared_width, declared_height=declared_height,
        ):
            return False
        self._position += 1
        self.raw_images.append(_RawInlineImage(
            url_raw=url_raw.strip(), declared_width=declared_width, declared_height=declared_height,
            alt=alt, position=self._position,
            in_priority_container=is_priority or self._in_priority_container(),
        ))
        return True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        attrs_dict = {name.lower(): (value or "") for name, value in attrs}

        is_priority = _is_priority_container(lowered, attrs_dict)
        is_secondary = _is_secondary_container(attrs_dict)
        if lowered not in _VOID_ELEMENTS:
            # Void elements (img/source and the rest of the HTML5 void-element set) can never have
            # children and, in ordinary (non-XHTML-self-closed) HTML, never trigger a matching
            # handle_endtag() call at all - html.parser.HTMLParser does not synthesize one; only an
            # explicitly self-closed `<tag ... />` reaches handle_endtag(), via the base class's
            # own default handle_startendtag(). Pushing a void element here would leave a stale
            # entry on the stack until some UNRELATED ancestor's later closing tag happens to
            # truncate far enough to remove it - silently poisoning every sibling element's
            # _in_priority_container()/_in_secondary_container() check in between. Confirmed as a
            # real bug (not hypothetical), traced against the live parser: a `class="related-
            # thumbnail"` <img> immediately followed by a legitimate sibling <img> caused the
            # sibling to be wrongly excluded too, until the enclosing <div> finally closed.
            self._container_stack.append((lowered, is_priority, is_secondary))
        if is_priority:
            self.any_priority_container_seen = True

        if lowered == "picture":
            self._picture_stack.append(False)
            return

        if lowered == "source":
            if not self._picture_stack:
                return  # a <source> outside <picture>/<video>/<audio> carries no image meaning
            srcset = attrs_dict.get("srcset")
            if not srcset:
                return
            best = _best_srcset_candidate(srcset)
            if best is None:
                return
            source_url_raw, source_declared_width = best
            added = self._try_add(
                url_raw=source_url_raw, declared_width=source_declared_width, declared_height=None,
                alt="", class_attr=attrs_dict.get("class", ""), id_attr=attrs_dict.get("id", ""),
                is_priority=is_priority, is_secondary=is_secondary,
            )
            if added:
                self._picture_stack[-1] = True
            return

        if lowered == "img":
            if self._picture_stack and self._picture_stack[-1]:
                return  # already satisfied by a <source> in this same <picture>
            declared_width = _safe_int(attrs_dict.get("width"))
            declared_height = _safe_int(attrs_dict.get("height"))
            url_raw = None
            srcset = attrs_dict.get("srcset")
            if srcset:
                best = _best_srcset_candidate(srcset)
                if best is not None:
                    url_raw, srcset_width = best
                    # The tag's own width= attribute commonly reflects the smallest/placeholder
                    # rendered size, not the intrinsic size of the srcset-selected (larger) file -
                    # a real declared srcset width always describes the URL actually chosen, so it
                    # takes priority over the tag attribute, never the reverse.
                    declared_width = srcset_width or declared_width
            if url_raw is None:
                url_raw = attrs_dict.get("src")
            self._try_add(
                url_raw=url_raw, declared_width=declared_width, declared_height=declared_height,
                alt=attrs_dict.get("alt", ""), class_attr=attrs_dict.get("class", ""),
                id_attr=attrs_dict.get("id", ""), is_priority=is_priority, is_secondary=is_secondary,
            )

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "picture" and self._picture_stack:
            self._picture_stack.pop()
        for index in range(len(self._container_stack) - 1, -1, -1):
            if self._container_stack[index][0] == lowered:
                del self._container_stack[index:]
                break


def extract_inline_article_images(html: str, *, base_url: str) -> list[NativeMediaHint]:
    """The second, independent article-image extractor (see module docstring). Scans <img> and
    <picture><source> tags in the article body - never issues a network request, never renders a
    DOM/JavaScript, never touches head <meta>/<link> tags (that remains `extract_article_image_
    metadata()`'s own exclusive concern; callers combine both lists, see services/image_
    intelligence.py::_fetch_article_metadata_hints()).

    Scoping (docs' own explicit rule): if the document contains at least one priority container
    (<article>, <main>, or an element whose class/id contains "content"/"post"/"entry"/"story"),
    ONLY images found inside such a container are considered - a stray body-level image outside
    every priority container is dropped, not merely deprioritized. Falls back to the whole
    document when no priority container exists anywhere.

    Secondary-subtree exclusion (3DNews production forensic - see `_SECONDARY_CONTAINER_TOKENS`'s
    own docstring for the real class/id values this was calibrated against): an <img>/<source>
    nested inside a related/recommended/read-more/news-slider ancestor is dropped entirely, even
    when that same element is ALSO inside a priority container - secondary always wins over
    priority (`_InlineImageCollector._try_add()` checks it before the candidate is ever recorded,
    never merely deprioritizes it the way `in_priority_container=False` does).

    Returns at most `_MAX_FINAL_INLINE_CANDIDATES` (5) hints, best-first per `_inline_sort_key()`,
    drawn from at most `_MAX_RAW_INLINE_CANDIDATES` (10) raw sightings that already passed the
    cheap icon/ad/tracking/svg/data-uri/too-small/secondary-subtree filters during parsing."""
    if not html:
        return []

    parser = _InlineImageCollector()
    try:
        parser.feed(html)
    except Exception:
        logger.warning("inline_article_image_parse_failed")
        return []

    candidates = parser.raw_images
    if parser.any_priority_container_seen:
        candidates = [c for c in candidates if c.in_priority_container]

    resolved: list[tuple[_RawInlineImage, str]] = []
    for raw in candidates:
        url = _resolve_url(raw.url_raw, base_url)
        if url:
            resolved.append((raw, url))

    resolved.sort(key=lambda pair: _inline_sort_key(pair[0]))

    return [
        NativeMediaHint(
            discovery_method=ImageDiscoveryMethod.ARTICLE_INLINE_IMAGE,
            remote_url=url,
            source_url=base_url,
            declared_width=raw.declared_width,
            declared_height=raw.declared_height,
            alt_text=_truncated_alt(raw.alt) or None,
        )
        for raw, url in resolved[:_MAX_FINAL_INLINE_CANDIDATES]
    ]
