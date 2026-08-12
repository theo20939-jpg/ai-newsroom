"""Phase 20.7 - Editorial Content Type layer.

Answers "what KIND of editorial object is this title?" (a review, a guide, an announcement, a
research paper, ...) - deliberately NOT "is this the same story?" (that remains services/
story_memory.py's own job). Deterministic, title-pattern-based (mirrors services/story_memory.py::
_classify_topic()'s own established "fixed keyword list, first match wins" convention exactly -
same style, same discipline, same explicit non-goal of perfect classification). No embeddings, no
LLM, no paid call, no new NLP dependency.

Computed purely at runtime from a title string - never persisted anywhere. Story Memory already
has a precedent for this: `services/story_memory.py::extract_story_signature()`'s own
`topic_bucket` is computed the same way and stored on `Story` only because it is cheap to persist
alongside an already-existing column; content type needs no such persistence at all here, since
`match_story()` can recompute it from `candidate.title` (already available) exactly as it already
recomputes `entity_overlap`/`title_overlap` fresh on every call - no schema change, no migration.

Every keyword pattern below was checked against the real Phase 20 replay corpus
(docs/phase20_7_editorial_content_type_report.md §6) before being chosen - not merely invented.
"""
from __future__ import annotations

import re

# --- content types --------------------------------------------------------------------------
# NEWS is the neutral default - "no specific editorial marker detected", not "definitely a plain
# news item". It is deliberately treated as compatible with everything (see
# is_content_type_mismatch() below) since the overwhelming majority of ordinary same-story
# follow-up coverage carries no special marker at all.
NEWS = "news"
ANNOUNCEMENT = "announcement"
REVIEW = "review"
GUIDE = "guide"
TUTORIAL = "tutorial"
ANALYSIS = "analysis"
INTERVIEW = "interview"
LEAK = "leak"
RUMOR = "rumor"
PATCH_NOTE = "patch_note"
RESEARCH = "research"
REPORT = "report"
OPINION = "opinion"

# Checked narrowest/most-specific first, mirroring services/story_memory.py::_TOPIC_KEYWORDS's own
# documented priority-order rationale (a title could plausibly match more than one pattern; first
# match in this fixed order wins, deterministically). English + Russian, matching this codebase's
# existing bilingual scope throughout services/story_memory.py and services/text_normalization.py.
_CONTENT_TYPE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        TUTORIAL,
        ("how to", "step-by-step", "как настроить", "как сделать"),
    ),
    (
        GUIDE,
        (
            "guide", "walkthrough", "tips for", "tips and tricks", "советы", "гайд",
        ),
    ),
    (
        REVIEW,
        ("review", "hands-on", "impressions", "tested", "обзор", "тест-драйв"),
    ),
    (
        PATCH_NOTE,
        ("patch notes", "changelog", "change log", "update notes", "hotfix", "патч-нот", "патчноут"),
    ),
    (
        RESEARCH,
        (
            "this paper", "this research", "this study", "arxiv", "researchers propose",
            "researchers present", "исследователи",
        ),
    ),
    (
        INTERVIEW,
        ("interview", "talks to", "speaks with", "q&a", "q & a", "интервью"),
    ),
    (
        LEAK,
        ("leaked", "leak", "утечка", "слив"),
    ),
    (
        RUMOR,
        ("rumor", "rumour", "rumored", "rumoured", "reportedly", "sources say", "слух", "по слухам"),
    ),
    (
        ANALYSIS,
        ("analysis", "deep dive", "explained", "breakdown", "анализ", "разбор"),
    ),
    (
        OPINION,
        ("opinion", "op-ed", "commentary", "мнение"),
    ),
    (
        REPORT,
        ("report finds", "according to a report", "survey finds", "survey shows", "согласно отчёту"),
    ),
    (
        ANNOUNCEMENT,
        (
            "launches", "launched", "announces", "announced", "unveils", "unveiled",
            "introduces", "introduced", "debuts", "debuted", "releases", "released",
            "запустил", "анонсировал", "представил", "выпустил",
        ),
    ),
)

_WORD_BOUNDARY_CACHE: dict[str, re.Pattern[str]] = {}


def _phrase_present(phrase: str, normalized_title: str) -> bool:
    """Whole-word/phrase containment - reuses the same word-boundary discipline services/
    story_memory.py::_classify_topic() already established (not a raw substring check, which
    would false-positive e.g. "leak" inside an unrelated longer word)."""
    pattern = _WORD_BOUNDARY_CACHE.get(phrase)
    if pattern is None:
        pattern = re.compile(r"\b" + re.escape(phrase) + r"\b")
        _WORD_BOUNDARY_CACHE[phrase] = pattern
    return bool(pattern.search(normalized_title))


def classify_content_type(title: str) -> str:
    """Pure, deterministic. Returns one of the module's own content-type constants, defaulting to
    `NEWS` when no specific pattern matches - mirrors `_classify_topic()`'s own `TOPIC_OTHER`
    fallback convention exactly. Case-insensitive; matches both English and Russian patterns
    against the same title unconditionally (no language detection - cheap and sufficient, since
    each pattern list only contains words specific to its own language anyway)."""
    normalized = title.lower()
    for content_type, phrases in _CONTENT_TYPE_PATTERNS:
        if any(_phrase_present(phrase, normalized) for phrase in phrases):
            return content_type
    return NEWS


def is_content_type_mismatch(new_type: str, candidate_type: str) -> bool:
    """Pure. The identity-relevant question: should these two content types block a confident
    same-story classification? True only when BOTH sides have a specific (non-`NEWS`) type AND
    those types differ - e.g. a `GUIDE` and a `REVIEW` about the same game are different editorial
    objects, but two `ANNOUNCEMENT`s (or a `NEWS` and anything else - `NEWS` is the neutral
    default, not itself a specific claim) are not blocked. `NEWS` is deliberately never a
    mismatch source: the overwhelming majority of genuine same-story follow-up coverage
    ("Apple confirms rollout date" following "Apple releases feature") carries no special
    editorial marker at all, and treating the ABSENCE of a marker as evidence of a different
    story would block real updates, not just false ones (Phase 20.7's own Case E)."""
    if new_type == NEWS or candidate_type == NEWS:
        return False
    return new_type != candidate_type
