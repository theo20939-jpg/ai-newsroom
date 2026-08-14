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
