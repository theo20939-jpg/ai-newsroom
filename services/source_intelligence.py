"""Source Intelligence (Phase 19 M8): deterministic, heuristic-only source-role classification.

Every label is deliberately hedged (`POSSIBLE_*`, never a bare `ORIGINAL_SOURCE`/`CONFIRMED`-style
factual claim) - this module estimates a role from already-available, already-deterministic
signals (this event's position in its Story's timeline, services.story_memory's own match_type,
a narrow analysis/opinion keyword lexicon, NewsSource.type/reliability_score), it never proves
one. No new external data, no LLM call, no embeddings - mirrors services/story_memory.py's own
"deterministic, hand-curated, narrow rules" convention exactly.

Persisted for review only (services/source_intelligence_persistence.py). Must never be injected
into Copywriting's prompt/output, and must never be used to generate prose asserting definitive
attribution or precedence between sources anywhere in this codebase -
tests/test_source_intelligence_isolation.py mechanically enforces the first half of that (no
capabilities/*.py file imports this module); the second half (no such phrase is ever generated)
holds structurally, since this module never produces prose at all, only a label.
"""
from __future__ import annotations

from database.models.news_source import SourceType

POSSIBLE_ORIGINAL = "POSSIBLE_ORIGINAL"
POSSIBLE_CONFIRMATION = "POSSIBLE_CONFIRMATION"
POSSIBLE_AGGREGATION = "POSSIBLE_AGGREGATION"
POSSIBLE_ANALYSIS = "POSSIBLE_ANALYSIS"
UNKNOWN = "UNKNOWN"

# A narrow, fixed lexicon distinguishing an analysis/opinion/explainer piece from straight news
# coverage - mirrors services/story_memory.py's own _TOPIC_KEYWORDS convention (a small, explicit
# word list, never a classifier model). Checked before match-type-based signals, since an
# analysis piece can legitimately be the first (or only) event seen for a topic without that
# making it "the origin" of a news story.
_ANALYSIS_KEYWORDS: tuple[str, ...] = (
    "opinion", "analysis", "explainer", "explained", "op-ed", "editorial", "commentary",
    "review", "why ", "how ", "vs.", " versus ",
    "мнение", "анализ", "объясняем", "почему", "как ",
)

def _looks_like_analysis(title: str) -> bool:
    lowered = f" {title.lower()} "
    return any(keyword in lowered for keyword in _ANALYSIS_KEYWORDS)


def classify_source_role(
    *,
    is_first_in_story: bool,
    match_type: str | None,
    title: str,
    source_type: SourceType | None = None,
    reliability_score: float | None = None,
) -> str:
    """Pure. `is_first_in_story`: this event is the earliest (by published_at/collected_at) known
    event for its Story - the closest available signal to "original," always hedged as
    POSSIBLE_ORIGINAL, never asserted as fact (a source could simply be the first one this system
    happened to collect, not the true origin). `match_type`: services.story_memory's own outcome
    vocabulary for this event's link to its Story, or None if the event has no story link at all
    (source_intelligence_mode requires story_memory_mode too, mirroring services/story_context.py's
    own dependency). `source_type`/`reliability_score` are accepted for interface completeness and
    future refinement but do not currently change the classification - reserved, not yet load-
    bearing (mirrows services/story_memory.py's own precedent of accepting `category` in
    extract_story_signature() without yet using it)."""
    del source_type, reliability_score  # reserved for future refinement - see docstring

    if _looks_like_analysis(title):
        return POSSIBLE_ANALYSIS
    if is_first_in_story:
        return POSSIBLE_ORIGINAL
    if match_type in ("semantic_duplicate", "supporting_source"):
        return POSSIBLE_CONFIRMATION
    if match_type == "story_update":
        return POSSIBLE_AGGREGATION
    return UNKNOWN
