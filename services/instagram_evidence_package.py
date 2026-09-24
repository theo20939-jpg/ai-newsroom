"""KAGE Instagram downstream evidence package: what the Director reads for ONE already-selected post, instead of arbitrary Story bodies.

Selection is not touched here: the package is built AFTER a daily slot or the weekly recap picked its story. It exists because the
Instagram lane never triggered article acquisition (services/article_acquisition.py::get_or_acquire() ran only for Telegram
CONTENT_GENERATION and radar events) and never ran source-image discovery - so an AI_HACK reached the Director with an RSS teaser and
no steps. The package reuses the EXISTING paths - `get_or_acquire` / `acquire_article` (safe_fetch policy, same extractor),
`clean_extracted_text`, `run_shadow_discovery` (image intelligence) - and adds only deterministic reading:

  - every extracted line keeps its provenance (source URL + source type) and is VERBATIM source text - never a summary, never a model;
  - STEP / FACT / LIMITATION lines are recognised by form (numbered steps, imperative openings, UI paths, commands / config), never
    inferred; an AI_HACK whose sources hold no step is BLOCKING and never reaches the Director (no invented workflow);
  - a Telegram post that links its original article follows that explicit link; an article that links an official help / docs page of
    the product enriches the SAME premise from it (bounded, allow-listed hosts);
  - a weekly-recap story only gets bodies that demonstrably talk about its selected premise (its distinctive entities) - the same
    Story id is not proof of relevance; less evidence beats polluted evidence."""
from __future__ import annotations

import html as html_lib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from services.article_cleaning import clean_extracted_text

# --- vocabulary ---------------------------------------------------------------------------------------------------------------------
ORIGINAL_ARTICLE = "ORIGINAL_ARTICLE"  # the post's own source URL, fetched
LINKED_ARTICLE = "LINKED_ARTICLE"  # the original article a Telegram post explicitly links
OFFICIAL_DOC = "OFFICIAL_DOC"  # an official help / docs / announcement page the article links
TELEGRAM_POST = "TELEGRAM_POST"  # the Telegram post itself (its own text is the primary artifact)
STORED_BODY = "STORED_BODY"  # the event's stored body / RSS description
SOURCE_PRIORITY = {OFFICIAL_DOC: 0, ORIGINAL_ARTICLE: 1, LINKED_ARTICLE: 1, TELEGRAM_POST: 2, STORED_BODY: 3}

STEP, FACT, LIMITATION = "STEP", "FACT", "LIMITATION"
STRONG, SUFFICIENT, THIN, BLOCKING = "STRONG", "SUFFICIENT", "THIN", "BLOCKING"
AVAILABLE, NOT_AVAILABLE, INVALID = "AVAILABLE", "NOT_AVAILABLE", "INVALID"

# official product help / docs / announcement hosts an article may link (enrichment of the SAME product only, at most MAX_OFFICIAL_DOCS)
OFFICIAL_DOC_HOSTS = (
    "help.openai.com", "openai.com", "support.google.com", "blog.google", "workspace.google.com", "support.anthropic.com",
    "docs.anthropic.com", "docs.claude.com", "support.claude.com", "anthropic.com", "claude.com", "helpx.adobe.com", "news.adobe.com",
    "blog.adobe.com", "plugins.jetbrains.com", "jetbrains.com", "docs.continue.dev", "platform.moonshot.ai", "moonshot.ai",
    "support.apple.com", "support.microsoft.com", "learn.microsoft.com", "help.x.com",
)
MAX_OFFICIAL_DOCS = 2
MAX_STEPS, MAX_FACTS, MAX_LIMITATIONS = 10, 6, 3
ITEM_CHARS = 300
RECAP_EXCERPTS_PER_STORY = 3

_STEP_OPEN_EN = (r"open|go to|head to|navigate|click|tap|press|select|choose|pick|type|enter|paste|copy|install|download|sign in|log in|"
                 r"sign up for|create|add|enable|disable|turn (?:on|off)|toggle|switch|set|run|launch|start|say|ask|upload|record|save|"
                 r"find|scroll|hover|drag|connect|link|visit|use|try|follow|search for|look for|pick|return|restart|check")
_STEP_OPEN_RU = (r"открой(?:те)?|перейди(?:те)?|нажми(?:те)?|выбери(?:те)?|введи(?:те)?|вставь(?:те)?|скопируй(?:те)?|установи(?:те)?|"
                 r"скачай(?:те)?|зайди(?:те)?|войди(?:те)?|включи(?:те)?|выключи(?:те)?|отключи(?:те)?|создай(?:те)?|запусти(?:те)?|"
                 r"добавь(?:те)?|найди(?:те)?|укажи(?:те)?|сохрани(?:те)?|подключи(?:те)?|зарегистрируй(?:тесь)?")
_STEP_RX = re.compile(rf"^(?:\d{{1,2}}[.)]\s+|step \d+[:.]?\s*|шаг \d+[:.]?\s*|(?:then|next|finally|after that|now),?\s+)?"
                      rf"(?:(?:{_STEP_OPEN_EN}|{_STEP_OPEN_RU})\b|"
                      r"(?!(?:затем|причём|причем|всем|этим|тем|ним|потом)\b)[А-ЯЁ][а-яё]+(?:ем|ём|им)(?:ся)?\b)", re.IGNORECASE)
# a how-to written as prose: an action on a named UI element anywhere in the sentence ("simply tap the Voice icon at the far right")
_PROSE_STEP_RX = re.compile(r"\b(?:tap|click|press|select|choose|open|head(?:ing)? (?:into|to|over)|navigat\w* to|go to|scroll|swipe|"
                            r"toggle|switch|type|install|sign in|hover)\w*\b.{0,120}?\b(?:icons?|buttons?|settings|menus?|tabs?|toolbar|"
                            r"bar|panel|text box|options?|preferences|extension|plugins?|dropdown|toggle|switch)\b|"
                            r"(?:нажм|выбер|откр|перейд|зайд|включ|отключ)\w*.{0,80}?(?:кнопк|настройк|меню|вкладк|значок|иконк|панел|раздел)",
                            re.IGNORECASE)
_NUMBERED_RX = re.compile(r"^(?:\d{1,2}[.)]|step \d+|шаг \d+)\s", re.IGNORECASE)
_PATH_RX = re.compile(r"\S+\s*(?:→|->)\s*\S+|\w\s+>\s+\w")
_COMMAND_RX = re.compile(r"^\s*[{\[]\s*\"|`[^`]{3,}`|^\s*(?:\$ |pip install |npm (?:i|install) |npx |brew install |curl |git clone |uv (?:add|pip) )")
_LIMIT_RX = re.compile(r"\b(?:only|not available|isn'?t available|requires?|required|limit(?:s|ed|ation)?|however|caveat|drawbacks?|"
                       r"tradeoffs?|won'?t|can'?t|doesn'?t|may not|beta|waitlist|paid|subscribers?|region)\b|"
                       r"ограничен|только|недоступ|не работает|однако|минус|платн|подписк", re.IGNORECASE)
_BOILERPLATE_RX = re.compile(r"subscribe|newsletter|sign up for (?:our|the)|follow (?:us|zdnet|engadget)|add (?:us|engadget|zdnet) "
                             r"|preferred source|read (?:more|full bio)|all rights reserved|cookie|affiliate|commission|advertis|"
                             r"skip to (?:main )?content|save (?:on|up to|\$)|% off|shop (?:now|the)|buy (?:now|it)|coupon|deals?\b|"
                             r"published:|share article|save article|by [A-Z][a-z]+ [A-Z][a-z]+ published|\b\d+ мин \d+K\b|"
                             r"подпис|реклам|комментари|читать далее|войти|скидк", re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+(?=[\"«“(]?[A-ZА-ЯЁ0-9])")
_WORD = re.compile(r"[a-zа-яё0-9][a-zа-яё0-9+'’-]{2,}", re.IGNORECASE)
_STOP = frozenset("the and for with that this from your you are was have has will can how what when into their about more than just "
                  "new now its it's our out get got use using one two all any not but also after before over under here there "
                  "как что это для при или его она они был была было уже ещё еще так все всё если чтобы только можно".split())
_URL_RX = re.compile(r"https?://[^\s)\]>\"']+|(?<![\w/.])(?:[a-z0-9-]+\.)+(?:ru|com|io|ai|net|org|dev)/[^\s)\]>\"']+", re.IGNORECASE)


@dataclass(frozen=True)
class EvidenceSource:
    url: str | None
    source_type: str
    text: str
    status: str = "OK"


@dataclass(frozen=True)
class EvidenceItem:
    kind: str  # STEP / FACT / LIMITATION
    text: str  # verbatim source text (whitespace-normalised, clipped)
    source_url: str | None
    source_type: str
    grounding: str = "verbatim_source_text"


@dataclass(frozen=True)
class SourceMedia:
    status: str  # AVAILABLE / NOT_AVAILABLE / INVALID
    url: str | None = None
    width: int | None = None
    height: int | None = None
    mime_type: str | None = None
    source: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class InstagramEvidencePackage:
    post_id: str
    format: str  # ai_hack / meme_trend / weekly_recap_story
    premise: str
    sources: tuple[EvidenceSource, ...]
    steps: tuple[EvidenceItem, ...]
    facts: tuple[EvidenceItem, ...]
    limitations: tuple[EvidenceItem, ...]
    media: SourceMedia
    quality: str
    why: str
    excluded_bodies: tuple[str, ...] = field(default=())

    @property
    def primary_sources(self) -> tuple[EvidenceSource, ...]:
        return tuple(s for s in self.sources if s.source_type in (ORIGINAL_ARTICLE, LINKED_ARTICLE, TELEGRAM_POST) and s.text)

    @property
    def supporting_sources(self) -> tuple[EvidenceSource, ...]:
        return tuple(s for s in self.sources if s.source_type in (OFFICIAL_DOC, STORED_BODY) and s.text)

    def director_evidence(self) -> list[str]:
        """What the Director may cite: the premise, then the verbatim STEP / FACT / LIMITATION texts, then the media truth. Each item is
        EXACTLY the source text, because the Director's evidence_used must quote an item verbatim (assert_evidence_grounded); the
        provenance (source URL / type) and the STEP / FACT / LIMITATION kind stay in the package itself, never glued onto the text."""
        lines = [self.premise] + [item.text for item in (*self.steps, *self.facts, *self.limitations)]
        lines.append("SOURCE MEDIA: " + (f"{self.media.width}x{self.media.height} source image available" if self.media.status == AVAILABLE
                                         else "NONE - do not plan a source-image-dependent layout"))
        return list(dict.fromkeys(lines))


# --- reading ------------------------------------------------------------------------------------------------------------------------

def _stems(text: str) -> set[str]:
    return {w.lower()[:6] for w in _WORD.findall(text) if w.lower() not in _STOP}


def _clip(text: str, limit: int = ITEM_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def article_span(text: str, title: str) -> str:
    """The article itself: from the first occurrence of its own title that is followed by real prose (a line of 120+ characters within
    the next 40 lines). Site navigation repeats the title among short menu lines; the article's own headline is followed by its body."""
    lines = [line.strip() for line in text.splitlines()]
    target = _stems(title)
    if not target:
        return text
    matches = [i for i, line in enumerate(lines) if (w := _stems(line)) and len(w & target) >= max(2, int(0.6 * len(target)))]
    for index in matches:
        if any(len(line) >= 120 for line in lines[index + 1:index + 41]):
            return "\n".join(lines[index + 1:])
    return "\n".join(lines[matches[0] + 1:]) if matches else text


def _navigation_like(text: str) -> bool:
    """Menu / index text: mostly Capitalised words with almost no sentence punctuation."""
    words = text.split()
    if len(words) < 8:
        return False
    capitalised = sum(1 for w in words if w[:1].isupper())
    return capitalised / len(words) > 0.5 and text.count(",") + text.count(".") <= 2


def plain_text(value: str) -> str:
    """Stored RSS / Telegram bodies are often HTML: tags, entities and markdown link targets are not evidence."""
    value = html_lib.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    return " ".join(re.sub(r"\]\((?:https?://)?[^)]*\)", "]", value).split())


def _blocks(text: str) -> list[str]:
    """Extracted text breaks inline links into separate lines: rejoin a paragraph, keep list items, UI paths and code apart."""
    blocks: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # a full-length instruction line starts its own block even after an unpunctuated caption ("Courtesy of ..."); a SHORT
        # capitalised UI label ("Turn off") stays inside the sentence an inline link split it out of
        starts_new = (not blocks or _NUMBERED_RX.match(line) or line[:1] in "{[•-–" or blocks[-1].rstrip()[-1:] in ".!?:;…}]"
                      or _COMMAND_RX.search(line) is not None or (len(line) >= 25 and _STEP_RX.match(line) is not None))
        if starts_new:
            blocks.append(line)
        else:
            joiner = "" if line[:1] in ".,;:)!?»”" or blocks[-1].endswith(("(", "«", "“")) else " "
            blocks[-1] = blocks[-1] + joiner + line
    return blocks


def _sentences(block: str) -> list[str]:
    if _COMMAND_RX.search(block) and block.lstrip()[:1] in "{[":
        return [block]
    return [s.strip() for s in _SENTENCE_SPLIT.split(block) if s.strip()]


def classify_line(sentence: str) -> str | None:
    """STEP / LIMITATION / FACT by FORM, never by guessing intent. None for navigation / boilerplate / fragments."""
    text = sentence.strip()
    if len(text) < 12 or _BOILERPLATE_RX.search(text) or _navigation_like(text):
        return None
    if _STEP_RX.match(text) or (_PATH_RX.search(text) and len(text) < 260) or _COMMAND_RX.search(text) or _PROSE_STEP_RX.search(text):
        return STEP
    if len(text) < 40:
        return None
    if _LIMIT_RX.search(text):
        return LIMITATION
    return FACT


def extract_items(source: EvidenceSource, *, premise: str, how_to: bool = True) -> list[EvidenceItem]:
    """Verbatim, provenance-tagged lines of one source. The post's OWN article (or the article its Telegram post links) is about this
    story by construction: its prose lines are facts. Any other body (stored description, official doc, a recap body) contributes a
    FACT only when it shares at least two premise words. A STEP / LIMITATION inside the article span is kept on form alone (a how-to's
    steps rarely repeat its headline)."""
    own = source.source_type in (ORIGINAL_ARTICLE, LINKED_ARTICLE)
    body = article_span(source.text, premise) if source.source_type in (ORIGINAL_ARTICLE, LINKED_ARTICLE, OFFICIAL_DOC) else source.text
    target = _stems(premise)
    items: list[EvidenceItem] = []
    for block in _blocks(body):
        for sentence in _sentences(block):
            kind = classify_line(sentence)
            if kind is None:
                continue
            if kind == LIMITATION and not how_to:
                kind = FACT  # a story that mentions a restriction states a fact; a caveat is a how-to's limitation
            if kind == FACT and (len(sentence) < 60 if own else len(_stems(sentence) & target) < 2):
                continue
            items.append(EvidenceItem(kind=kind, text=_clip(sentence, 400 if kind == STEP else ITEM_CHARS), source_url=source.url,
                                      source_type=source.source_type))
    return items


def _dedupe(items: Iterable[EvidenceItem], limit: int) -> tuple[EvidenceItem, ...]:
    seen: set[str] = set()
    out: list[EvidenceItem] = []
    for item in sorted(items, key=lambda i: SOURCE_PRIORITY.get(i.source_type, 9)):  # stable: keeps source order within a type
        key = " ".join(sorted(_stems(item.text)))[:160]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return tuple(out[:limit])


def _has_location(steps: Sequence[EvidenceItem]) -> bool:
    return any(_PATH_RX.search(s.text) or _COMMAND_RX.search(s.text) or re.search(r"\b(?:settings|menu|preferences|button|icon|tab|"
                                                                                      r"настройк|меню|кнопк|вкладк)\w*", s.text, re.I)
               for s in steps)


def grade(fmt: str, steps: Sequence[EvidenceItem], facts: Sequence[EvidenceItem], sources: Sequence[EvidenceSource]) -> tuple[str, str]:
    """AI_HACK: does the evidence answer "what does the user actually do?". TREND / recap story: are the premise's key facts there?"""
    fetched = [s for s in sources if s.source_type in (ORIGINAL_ARTICLE, LINKED_ARTICLE, OFFICIAL_DOC, TELEGRAM_POST) and s.text]
    body = sum(len(s.text) for s in fetched)
    if fmt == "ai_hack":
        if not steps:
            return BLOCKING, "no step, path, command or setting in any source - the Director would have to invent the workflow"
        if len(steps) >= 4 and _has_location(steps):
            return STRONG, f"{len(steps)} verbatim steps incl. a concrete location / command"
        if len(steps) >= 2:
            return SUFFICIENT, f"{len(steps)} verbatim steps" + ("" if _has_location(steps) else ", no exact settings path")
        return THIN, "a single step - not a workflow"
    if not facts:
        return BLOCKING, "nothing beyond the headline"
    if len(facts) >= 6 and body >= 2000:
        return STRONG, f"{len(facts)} premise facts from {len(fetched)} fetched source(s)"
    if len(facts) >= 3:
        return SUFFICIENT, f"{len(facts)} premise facts"
    return THIN, f"only {len(facts)} premise fact(s) - the shareable detail is missing"


def assemble_package(*, post_id: str, fmt: str, premise: str, sources: Sequence[EvidenceSource], media: SourceMedia,
                     excluded_bodies: Sequence[str] = ()) -> InstagramEvidencePackage:
    items = [item for source in sources if source.text for item in extract_items(source, premise=premise, how_to=fmt == "ai_hack")]
    steps = _dedupe((i for i in items if i.kind == STEP), MAX_STEPS) if fmt == "ai_hack" else ()
    facts = _dedupe((i for i in items if i.kind == FACT), MAX_FACTS)
    limitations = _dedupe((i for i in items if i.kind == LIMITATION), MAX_LIMITATIONS)
    quality, why = grade(fmt, steps, facts, sources)
    return InstagramEvidencePackage(post_id=post_id, format=fmt, premise=premise, sources=tuple(sources), steps=steps, facts=facts,
                                    limitations=limitations, media=media, quality=quality, why=why,
                                    excluded_bodies=tuple(excluded_bodies))


# --- links ----------------------------------------------------------------------------------------------------------------------------

class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def official_doc_links(html: str, *, base_url: str, premise: str, limit: int = MAX_OFFICIAL_DOCS) -> list[str]:
    """Links the article itself gives to an allow-listed official help / docs / announcement host whose PATH names the premise's own
    product or feature (a help-centre index or a home page is navigation, not evidence) - help and docs pages first."""
    target = _stems(premise)
    parser = _LinkCollector()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - malformed HTML simply yields no links
        return []
    own_host = urlparse(base_url).netloc.removeprefix("www.")
    found: list[str] = []
    for href in parser.hrefs:
        url = urljoin(base_url, html_lib.unescape(href)).split("#", 1)[0]
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if not host or host == own_host or not any(host == h or host.endswith("." + h) for h in OFFICIAL_DOC_HOSTS):
            continue
        path_words = {w.lower()[:6] for w in re.split(r"[/_\-.]+", urlparse(url).path) if len(w) >= 3}
        if urlparse(url).path in ("", "/") or not path_words & target:
            continue
        found.append(url)
    ranked = sorted(dict.fromkeys(found), key=lambda u: (not re.search(r"help|support|docs|learn", u), len(u)))
    return ranked[:limit]


def telegram_outbound_link(text: str) -> str | None:
    """The original article a Telegram post explicitly links (never another t.me link)."""
    for match in _URL_RX.finditer(text or ""):
        url = match.group(0).rstrip(".,;")
        if not url.lower().startswith("http"):
            url = "https://" + url
        if "t.me/" in url.lower() or "telegram.me" in url.lower():
            continue
        return url
    return None


# --- weekly recap sanitation ----------------------------------------------------------------------------------------------------------

def recap_anchors(premise: str, headlines: Sequence[str]) -> set[str]:
    """The selected story's distinctive words: word stems carried by the premise AND by at least one cited headline (in any language
    they share - brand and product names), or by at least two cited headlines."""
    premise_stems = _stems(premise)
    counts: dict[str, int] = {}
    for headline in headlines:
        for stem in _stems(headline):
            counts[stem] = counts.get(stem, 0) + 1
    return {s for s, n in counts.items() if (s in premise_stems and n >= 1) or n >= 2}


def relevant_to_recap(body: str, anchors: set[str], *, minimum: int = 2) -> bool:
    """A body supports the selected premise only when its opening talks about it: at least `minimum` of the premise anchors (all of them
    when fewer exist). The same Story id is NOT evidence of relevance."""
    if not anchors:
        return False
    opening = _stems(body[:2500])
    return len(opening & anchors) >= min(minimum, len(anchors))


def sanitize_recap_bodies(premise: str, headlines: Sequence[str], bodies: Sequence[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[str]]:
    """(kept (ref, body), excluded refs) - excluded bodies never reach the Director."""
    anchors = recap_anchors(premise, headlines)
    kept: list[tuple[str, str]] = []
    excluded: list[str] = []
    for ref, body in bodies:
        if body and relevant_to_recap(body, anchors):
            kept.append((ref, body))
        else:
            excluded.append(ref)
    return kept, excluded


def clean_body(raw_text: str | None, title: str | None = None) -> str:
    """The project's own cleaner (services/article_cleaning.py), applied on the fly exactly as evidence_package / the executor do -
    `cleaned_text` is never persisted on the acquisition row."""
    if not raw_text:
        return ""
    return clean_extracted_text(raw_text, title=title).cleaned_text or ""


def media_from_image_intelligence(result) -> SourceMedia:
    """Source media readiness from the EXISTING image-intelligence result (run_shadow_discovery)."""
    candidates = list(getattr(result, "candidates", []) or [])
    if not candidates:
        reason = getattr(result, "article_fetch_error", None) or "no source image discovered"
        return SourceMedia(status=NOT_AVAILABLE, reason=str(reason))
    for c in candidates:
        status = getattr(getattr(c, "status", None), "value", str(getattr(c, "status", "")))
        quality = getattr(c, "quality_validation", None)
        quality_ok = quality is None or getattr(getattr(quality, "status", None), "value", None) == "accepted"
        if status == "validated" and quality_ok:
            tv = getattr(c, "technical_validation", None)
            width = getattr(tv, "width", None) or c.declared_width
            height = getattr(tv, "height", None) or c.declared_height
            if width and height and min(width, height) < 256:
                continue
            return SourceMedia(status=AVAILABLE, url=c.remote_url, width=width, height=height,
                               mime_type=getattr(tv, "observed_mime", None) or c.declared_mime_type,
                               source=getattr(getattr(c, "discovery_method", None), "value", None), reason="validated source image")
    return SourceMedia(status=INVALID, reason=f"{len(candidates)} candidate(s), none validated at a usable size")


# --- acquisition (existing paths) ---------------------------------------------------------------------------------------------------

async def _fetch_article(url: str, *, event_id) -> tuple[str, str, str | None]:
    """(raw text, status, final url) through the EXISTING acquire_article() - same safe_fetch policy, same extractor, never raises."""
    from services.article_acquisition import acquire_article

    outcome = await acquire_article(url, event_id=event_id)
    return outcome.raw_extracted_text or "", outcome.status, outcome.canonical_url or url


async def _fetch_html(url: str) -> str:
    from integrations.http.safe_fetch import safe_fetch
    from services.article_acquisition import _fetch_policy

    try:
        result = await safe_fetch(url, policy=_fetch_policy())
    except Exception:  # noqa: BLE001 - link discovery is best-effort enrichment
        return ""
    return result.body.decode("utf-8", errors="replace") if result.status_code < 400 else ""


async def _own_article(session, event, url: str) -> tuple[str, str]:
    """With a session: the existing get_or_acquire() (persisted, idempotent, reuse-aware) read back through get_effective_acquisition();
    without one (an offline historical replay): a plain acquire_article() fetch."""
    from database.models.news_event_article_acquisition import TRIGGERED_BY_INSTAGRAM_SELECTED
    from services.article_acquisition import get_effective_acquisition, get_or_acquire
    from services.evidence_package import TRUSTED_FULL_ARTICLE_STATUSES

    if session is None or event is None:
        text, status, _ = await _fetch_article(url, event_id=getattr(event, "id", None))
        return text, status
    await get_or_acquire(session, event, triggered_by=TRIGGERED_BY_INSTAGRAM_SELECTED)
    await session.flush()
    row = await get_effective_acquisition(session, event.id)
    if row is None:
        return "", "NO_ROW"
    trusted = row.acquisition_status in TRUSTED_FULL_ARTICLE_STATUSES
    return (row.raw_extracted_text or "") if trusted else "", row.acquisition_status


async def build_daily_evidence_package(
    *, post_id: str, fmt: str, title: str, url: str | None, source_type: str, source_name: str | None, stored_body: str | None,
    event=None, event_id=None, session=None, acquisition_enabled: bool = True, media_mode: str = "shadow",
) -> InstagramEvidencePackage:
    """ONE selected daily post: its own article (or, for a Telegram post, the article it explicitly links), official docs that article
    links, its stored body, and its source media - all through existing acquisition paths. Never raises: a failed fetch is just a
    source with no text, and the grade says what is missing."""
    from uuid import UUID

    from database.models.news_source import SourceType
    from services.image_intelligence import run_shadow_discovery

    telegram = str(source_type).upper().endswith("TELEGRAM")
    sources: list[EvidenceSource] = []
    if stored_body:
        sources.append(EvidenceSource(url=None if not telegram else url, source_type=TELEGRAM_POST if telegram else STORED_BODY,
                                      text=plain_text(stored_body)))
    article_url = telegram_outbound_link(stored_body or "") if telegram else url
    if article_url and acquisition_enabled:
        try:
            if telegram:
                raw, status, _ = await _fetch_article(article_url, event_id=event_id)
            else:
                raw, status = await _own_article(session, event, article_url)
        except Exception:  # noqa: BLE001 - acquisition never blocks the post; the grade reports the gap
            raw, status = "", "FETCH_FAILED"
        # the RAW extraction, read inside its article span: the project cleaner drops short standalone lines, and a UI name split out
        # by an inline link ("Click / Gemini / in the menu bar") is exactly such a line
        sources.append(EvidenceSource(url=article_url, source_type=LINKED_ARTICLE if telegram else ORIGINAL_ARTICLE,
                                      text=raw, status=status))
        if raw and fmt == "ai_hack":
            html = await _fetch_html(article_url)
            for doc_url in official_doc_links(html, base_url=article_url, premise=title):
                doc_raw, doc_status, _ = await _fetch_article(doc_url, event_id=event_id)
                sources.append(EvidenceSource(url=doc_url, source_type=OFFICIAL_DOC, text=doc_raw, status=doc_status))
    media = SourceMedia(status=NOT_AVAILABLE, reason="image intelligence off")
    if media_mode != "off" and event_id is not None:
        try:
            result = await run_shadow_discovery(
                event_id=event_id if not isinstance(event_id, str) else UUID(event_id),
                source_type=SourceType.RSS if telegram and article_url else SourceType(str(source_type).upper().split(".")[-1]),
                content=stored_body, article_url=article_url, mode="shadow", event_title=title, source_name=source_name,
                session=session,
            )
            media = media_from_image_intelligence(result)
        except Exception as exc:  # noqa: BLE001 - media is optional; the Director is told SOURCE MEDIA = NONE
            media = SourceMedia(status=NOT_AVAILABLE, reason=f"image discovery failed: {type(exc).__name__}")
    return assemble_package(post_id=post_id, fmt=fmt, premise=title, sources=sources, media=media)


async def build_recap_story_package(
    *, post_id: str, premise: str, headlines: Sequence[str], bodies: Sequence[tuple[str, str]],
) -> InstagramEvidencePackage:
    """ONE weekly-recap story: only bodies that talk about its selected premise survive (sanitize_recap_bodies)."""
    kept, excluded = sanitize_recap_bodies(premise, headlines, [(ref, plain_text(body)) for ref, body in bodies])
    sources = [EvidenceSource(url=ref if ref.startswith("http") else None, source_type=STORED_BODY, text=body) for ref, body in kept]
    focus = premise + " " + " ".join(headlines)
    package = assemble_package(post_id=post_id, fmt="weekly_recap_story", premise=focus, sources=sources,
                               media=SourceMedia(status=NOT_AVAILABLE, reason="recap media is resolved per story by the recap bundle"),
                               excluded_bodies=excluded)
    return InstagramEvidencePackage(**{**package.__dict__, "premise": premise})
