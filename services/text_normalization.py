"""Small, controlled text-normalization helpers for Phase 17 M5's Editorial Completeness Gate and
Fact Safety calibration layer (docs/phase17_m5_editorial_completeness_gate_shadow_report.md) -
shared by both, never duplicated.

Deliberately NOT a general NLP engine (M5's own explicit "не создавай universal NLP engine"
instruction): a fixed, small, explicit set of narrow rules only - quote/guillemet stripping, dash
normalization, casefold, and a conservative Russian case-suffix stripper for the specific
declension mismatch class already observed in real Phase 17 M4.1 output ("Ходячих мертвецов"
genitive vs. source "Ходячие мертвецы" nominative,
docs/phase17_m4_1_reasoning_budget_fix_report.md §11). Money/percentage/date matching already has
its own dedicated, more precise parser in `services/fact_safety.py` and is never re-implemented
here - this module is for entity/phrase-level matching only.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

_QUOTE_CHARS = "«»“”‘’\"'`"
_DASH_RE = re.compile(r"[‐-―−]")  # unicode dash variants -> ascii hyphen
_WHITESPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[\w-]+", re.UNICODE)

# Moved here from services/article_acquisition.py (originally added for the Google News
# sibling-reuse fix, docs/google_news_sibling_reuse_fix_checkpoint.md) so a second caller
# (services/story_delta_engine.py) can reuse the exact same, already-proven regex without
# importing that much heavier service module (DB models, HTTP fetch, video discovery) just for
# one small pure helper. Behavior is byte-for-byte unchanged from the original.
_GOOGLE_NEWS_TITLE_SUFFIX_RE = re.compile(r"\s+-\s+[^-\n]{2,60}$")

# Moved here alongside _GOOGLE_NEWS_TITLE_SUFFIX_RE above, same reasoning: a second caller
# (services/story_delta_engine.py::compute_story_delta()) needs the actual Google News URL
# provenance signal - not just the title-shape regex - to know when neutralizing the suffix is
# safe (docs/<this fix's own report>: title shape alone is provably insufficient, since a short
# genuine semantic continuation can have the exact same " - X" shape as a publisher credit).
# Host-suffix matching only (never payload decoding) - see the original docstring this was moved
# from for the full rationale.
_GOOGLE_NEWS_HOST_RE = re.compile(r"(^|\.)news\.google\.[a-z]{2,3}(\.[a-z]{2})?$", re.IGNORECASE)

# Conservative Russian case-suffix list: only endings that matter for the declension mismatch
# class actually observed (docs/phase17_m4_1_reasoning_budget_fix_report.md §11). Ordered longest
# first so a longer, more specific ending is tried before a shorter one it would otherwise shadow.
# Never applied to a token <= 4 characters or an ALL-CAPS token (acronyms) - guarded in
# `strip_ru_case_suffix()` - to avoid truncating a short real word or a real acronym.
_RU_CASE_SUFFIXES: tuple[str, ...] = (
    "иями", "ями", "ами", "ого", "его", "ому", "ему", "ыми", "ими",
    "ой", "ей", "ый", "ий", "ая", "яя", "ое", "ее", "ых", "их", "ие", "ые", "ов", "ев",
    "у", "ю", "а", "я", "ы", "и", "е", "о",
)


def strip_quotes(text: str) -> str:
    """Removes guillemets and curly/straight quote characters only - never touches apostrophes
    inside a word (M5's own "не создавай universal NLP" scope: this is a fixed character strip,
    not a grammar-aware quote parser)."""
    return "".join(ch for ch in text if ch not in _QUOTE_CHARS)


def normalize_dashes(text: str) -> str:
    return _DASH_RE.sub("-", text)


def normalize_loose(text: str) -> str:
    """NFKC + casefold + guillemet/quote stripping + dash normalization + collapsed whitespace -
    the base normalization both the completeness gate and the calibration layer apply before any
    comparison. Never strips digits or numeric punctuation - those have their own dedicated
    parsers in `services/fact_safety.py`."""
    text = unicodedata.normalize("NFKC", text)
    text = strip_quotes(text)
    text = normalize_dashes(text)
    return _WHITESPACE_RE.sub(" ", text).strip().casefold()


def is_google_news_redirect_host(url: str) -> bool:
    """Pure, hostname-only, no network call. True for news.google.com and its known locale
    variants (news.google.co.uk, news.google.de, etc.). The provenance signal
    strip_google_news_title_suffix() itself deliberately does NOT check on its own - callers
    that need to know WHY a suffix is safe to strip (not just that its shape matches) combine
    the two explicitly."""
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return False
    return bool(_GOOGLE_NEWS_HOST_RE.search(host))


def is_google_news_provenance(event_url: str | None, source_url: str | None) -> bool:
    """Phase V2.22 (Story Memory match-quality fix, real production evidence: a "Южная Корея..."
    story collected via a NewsSource literally named "Google News RU" kept its "- 3DNews" RSS
    publisher-attribution suffix uncorrupted through Story Memory matching). `is_google_news_
    redirect_host(event_url)` alone (the pre-existing check) only catches a STILL-LIVE
    news.google.com redirect link - a real collector commonly resolves that redirect to the
    publisher's own real article URL before persisting `NewsEvent.url`, so the per-article check
    can miss a genuine Google-News-sourced item even though its TITLE still carries the feed's own
    suffix (a Google News RSS item's title always carries it, independent of whether the stored
    URL happens to still be the aggregator redirect or the already-resolved publisher page). This
    reuses the exact same, already-tested `is_google_news_redirect_host()` hostname check against
    the event's OWN `NewsSource.url` (the feed endpoint itself) as a second, independent
    provenance signal - never a new heuristic, never inferred from title shape (the same "shape
    alone is insufficient" rule `strip_google_news_title_suffix()`'s own docstring already
    establishes). True if EITHER URL resolves to a google-news host."""
    return bool(
        (event_url and is_google_news_redirect_host(event_url))
        or (source_url and is_google_news_redirect_host(source_url))
    )


def strip_google_news_title_suffix(title: str) -> str:
    """Pure. Strips a trailing ' - {Publisher}' suffix if present - Google News RSS entries
    reliably append this to the real headline (confirmed empirically against real cases:
    '...традиционные ценности - 3DNews' vs. the direct feed's own bare '...традиционные
    ценности'; also 'ИИ-модель DeepSeek V4 Pro выпущена официально - 3DNews' vs. the direct
    feed's bare title). A no-op when no such suffix is present.

    Shared by services/article_acquisition.py (sibling-reuse title matching) and
    services/story_delta_engine.py (Story Delta title-comparison normalization) - never a second,
    divergent regex for the same known publisher-attribution pattern."""
    return _GOOGLE_NEWS_TITLE_SUFFIX_RE.sub("", title.strip()).strip()


# --- STORY-CONTINUITY-P0 (2026-09): identity-normalization for Story matching -----------------
# Boilerplate that is publisher/format provenance, NOT story identity. Every pattern below is a
# fixed, closed, linguistically/journalistically-principled marker - never a calibration-derived
# list of any one incident's company or product names (mirrors the same discipline
# services/story_memory.py's own generic-entity sets already document).

# Russian legal-designation boilerplate. Real production evidence (META-AI-DUPLICATE forensics):
# every Russian-language Meta item carries a mandatory legal disclaimer prefix/parenthetical
# ("Запрещённая в России Meta ...", "Meta (признана экстремистской и запрещена в РФ) ...") which,
# left in place, dominates title-token overlap so that two editorially-unrelated Meta stories
# score a high title_dice purely on the shared disclaimer. Matched case-insensitively against the
# already-casefolded output of normalize_loose(). Deliberately narrow: only the disclaimer's own
# fixed phrasing, plus the trailing organization token it always wraps, is removed - no other
# word is touched.
_RU_LEGAL_DESIGNATION_RE = re.compile(
    r"(?:запрещённая\s+в\s+россии|запрещенная\s+в\s+россии|"
    r"признанн(?:ая|ой)\s+экстремистской(?:\s+и\s+запрещённой?\s+в\s+(?:рф|россии))?|"
    r"экстремистск(?:ая|ой)\s+и\s+запрещённая\s+в\s+(?:рф|россии)|"
    r"принадлежит\s+запрещённой\s+в\s+россии|принадлежащ(?:ая|ей)\s+запрещённой)"
    r"(?:\s+(?:организации|компании))?",
    re.IGNORECASE,
)
# A parenthetical carrying only the disclaimer, e.g. "Meta (признана экстремистской...)".
_RU_LEGAL_PARENTHETICAL_RE = re.compile(
    r"\s*\((?:[^()]*(?:запрещ|экстремист)[^()]*)\)", re.IGNORECASE
)

# Leading wire-service / editorial-format labels. These announce the ARTICLE FORMAT (an
# investigation, a Q&A, an internal memo, an opinion column) - not a different real-world story.
# Two unrelated same-company items can both open "Investigation: ..." and must not gain identity
# similarity from that shared label. Closed English/Russian set, anchored to the start of the
# title only, single leading label stripped (never recursively).
_WIRE_FORMAT_PREFIX_RE = re.compile(
    r"^\s*(?:investigation|exclusive|analysis|opinion|editorial|explainer|explained|"
    r"q&a(?:\s+with[^:]{0,80})?|memo|report|update|breaking|live|watch|video|photos?|"
    r"review|first\s+look|hands[- ]on|deep\s+dive|the\s+download|расследование|"
    r"мнение|интервью|обзор|видео|фото|репортаж|эксклюзив)\s*[:\-–—]\s+",
    re.IGNORECASE,
)

# URL tracking / session params that never change which article a URL points at. Removing them
# lets two syndicated copies of the same story with differently-decorated URLs canonicalize to
# one key. Closed, well-known set - not a generic "strip every query param" (some params are
# load-bearing, e.g. ?id=, ?p=, ?story=).
_URL_TRACKING_PARAM_PREFIXES: tuple[str, ...] = (
    "utm_", "fbclid", "gclid", "gclsrc", "dclid", "msclkid", "mc_cid", "mc_eid",
    "igshid", "ref", "ref_src", "ref_url", "cmpid", "ncid", "spm", "_hsenc", "_hsmi",
    "vero_id", "yclid", "oc", "share", "__twitter_impression", "s_kwcid", "at_medium",
    "at_campaign", "cid",
)


def strip_ru_legal_designation(title: str) -> str:
    """Pure. Removes the fixed Russian legal-designation disclaimer (a mandatory publisher
    boilerplate around the word "Meta"/"Instagram"/"Facebook", never part of the actual
    headline). A no-op when no such phrasing is present. Comparison/identity use only - the raw
    title is never mutated in place."""
    out = _RU_LEGAL_PARENTHETICAL_RE.sub("", title)
    out = _RU_LEGAL_DESIGNATION_RE.sub("", out)
    return _WHITESPACE_RE.sub(" ", out).strip(" —–-:,;")


def strip_wire_format_prefix(title: str) -> str:
    """Pure. Removes a single leading wire-service / editorial-format label ("Investigation:",
    "Q&A with X on ...:", "Memo: ...", "Опрос: ..."). Format provenance, not story identity. A
    no-op when the title does not open with a recognised label."""
    return _WIRE_FORMAT_PREFIX_RE.sub("", title, count=1).strip()


def normalize_story_identity_title(title: str) -> str:
    """Pure. The one shared identity-normalization pass Story Memory applies to every title
    before entity/keyword extraction and before title-similarity scoring: strip the Russian
    legal-designation disclaimer and a leading wire-format label - both fixed, unambiguous
    boilerplate phrases. Deliberately does NOT strip the Google News ' - Publisher' suffix: that
    is shape-only and provenance-gated (a short genuine semantic tail ' - в России' has the same
    shape), handled by callers that hold real URL provenance (see
    services/story_delta_engine.py's own docstring on why shape alone is insufficient, and
    services/triage_orchestrator.py::_apply_story_memory()'s provenance-gated strip). Never
    strips ordinary words. Returns the cleaned title (human-readable, not casefolded)."""
    out = strip_ru_legal_designation(title)
    out = strip_wire_format_prefix(out)
    return out.strip() or title.strip()


def canonicalize_url(url: str | None) -> str | None:
    """Pure, no network. Lower-cases the host, drops the fragment, removes well-known tracking /
    session query params (see _URL_TRACKING_PARAM_PREFIXES), sorts the surviving params, and
    trims a trailing slash - so two syndicated copies of the same article whose URLs differ only
    by tracking decoration produce the same canonical key. Returns None for None/empty input and
    leaves an unparseable URL untouched (returned casefolded-trimmed only)."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().casefold() or None
    if not parts.scheme and not parts.netloc:
        return url.strip().casefold() or None
    kept: list[str] = []
    for pair in parts.query.split("&"):
        if not pair:
            continue
        key = pair.split("=", 1)[0].lower()
        if any(key == p or key.startswith(p) for p in _URL_TRACKING_PARAM_PREFIXES):
            continue
        kept.append(pair)
    query = "&".join(sorted(kept))
    path = parts.path.rstrip("/") or "/"
    host = (parts.hostname or "").lower()
    if parts.port:
        host = f"{host}:{parts.port}"
    return f"{parts.scheme.lower()}://{host}{path}" + (f"?{query}" if query else "")


def strip_ru_case_suffix(token: str) -> str:
    """Conservative single-pass suffix stripping - a small, explicit, hand-curated ending list,
    never a general morphological analyzer. Skipped entirely for short tokens (<=4 chars) and
    ALL-CAPS tokens (acronyms), and never allowed to strip a token down to fewer than 3
    characters - both guards exist because blind suffix removal is more likely to damage a short
    real word or a real acronym than to fix a real declension mismatch."""
    if len(token) <= 4 or token.isupper():
        return token
    lower = token.lower()
    for suffix in _RU_CASE_SUFFIXES:
        if lower.endswith(suffix) and len(lower) - len(suffix) >= 3:
            return lower[: -len(suffix)]
    return lower


def normalize_for_entity_match(text: str) -> str:
    """`normalize_loose()` plus, per word, `strip_ru_case_suffix()` - used only for entity/name/
    phrase comparison (never for numeric/date/quote matching, which must stay exact after their
    own dedicated normalization in `services/fact_safety.py`)."""
    loose = normalize_loose(text)
    words = _WORD_RE.findall(loose)
    return " ".join(strip_ru_case_suffix(w) for w in words)


def fuzzy_phrase_contains(needle: str, haystack: str) -> bool:
    """Whole-word-normalized containment check: True when `needle`'s own case-stripped, quote-
    stripped normalized form appears as a contiguous word sequence inside `haystack`'s equally
    normalized form. Never a short raw-substring match (M5's own explicit "не считать слова
    совпавшими только по короткому substring" instruction) - both sides go through the same
    word-boundary tokenization first, and an empty/whitespace-only needle never matches."""
    needle_norm = normalize_for_entity_match(needle)
    haystack_norm = normalize_for_entity_match(haystack)
    if not needle_norm.strip():
        return False
    return f" {needle_norm} " in f" {haystack_norm} "


def token_overlap_ratio(a: str, b: str, *, min_token_len: int = 3) -> float:
    """Fraction of `a`'s own distinct, length-filtered tokens that also appear in `b` - the same
    style of vocabulary-overlap signal M0's own headline-rewrite proxy used
    (docs/phase17_m0_output_quality_discovery_report.md §6), kept here only as one input signal
    among several inside `services/editorial_completeness.py`, never the sole basis for a rewrite
    verdict - relying on it alone was M0's own disclosed, measured mistake (0% vs. 18.75-21.9%)."""
    tokens_a = {t for t in _WORD_RE.findall(normalize_loose(a)) if len(t) >= min_token_len}
    tokens_b = {t for t in _WORD_RE.findall(normalize_loose(b)) if len(t) >= min_token_len}
    if not tokens_a:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a)


def symmetric_token_overlap(a: str, b: str, *, min_token_len: int = 3) -> float:
    """Phase 20 M4: Dice coefficient (2*|A∩B|/(|A|+|B|)) over the same length-filtered token sets
    `token_overlap_ratio()` uses - symmetric, unlike that function, which was found (Phase 20
    calibration dataset's `ai_olympiad_cluster` case) to penalize a longer, differently-worded
    restatement of the same story purely because it divides by the *new* event's own (larger)
    token count. Added as a new function rather than changing `token_overlap_ratio()` itself -
    that function's existing caller (`services/editorial_completeness.py`) keeps its own,
    unchanged, already-calibrated asymmetric behavior; only services/story_memory.py uses this
    one. Returns 0.0 if either side has no length-filtered tokens (never divides by zero)."""
    tokens_a = {t for t in _WORD_RE.findall(normalize_loose(a)) if len(t) >= min_token_len}
    tokens_b = {t for t in _WORD_RE.findall(normalize_loose(b)) if len(t) >= min_token_len}
    if not tokens_a or not tokens_b:
        return 0.0
    return 2 * len(tokens_a & tokens_b) / (len(tokens_a) + len(tokens_b))


def count_paragraphs(text: str) -> int:
    """Splits on any blank line (one or more consecutive `\\n\\n+`) - matches how every prior
    Phase 17 milestone's own `paragraph_target` field is produced (`services/adaptive_length.py`/
    `services/beginner_friendly.py`), so the two stay directly comparable."""
    parts = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    return max(1, len(parts)) if text.strip() else 0
