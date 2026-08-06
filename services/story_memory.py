"""Story Memory Layer (Phase 18.10 M1/M2, docs/phase18_10_editorial_intelligence_report.md).

Recognizes when a new NewsEvent is likely describing the same developing real-world story as one
already seen, so the system can link it as an update (or flag it as a near-duplicate rehash from
a different source) instead of treating every source's coverage of the same event as an
unrelated new item.

Deliberately deterministic and narrow - no embeddings, no vector store, no new LLM capability
(this codebase has neither pgvector nor any embedding column anywhere, and this phase does not
add one). Reuses services/text_normalization.py, which is explicitly documented as "the shared
layer for entity/phrase matching" and "deliberately NOT a general NLP engine" - a fixed, small,
explicit set of narrow rules, exactly the convention this module follows too (mirrors
services/fact_safety.py's and services/image_deduplication.py's own hand-curated, threshold-based
style, never a statistical/ML model).

Split into a pure calculator (`extract_story_signature`, `score_candidate` - no I/O, fully
unit-testable) and one thin async orchestration function (`match_story`, the only piece
services/triage_orchestrator.py calls) - mirrors services/editorial_scoring.py's own established
split exactly.

Shadow-mode only in this phase: `match_story()`'s result is persisted (by the caller) for
observability, but never suppresses any downstream processing - see
services/triage_orchestrator.py's own `story_memory_mode` gating for the enforcement boundary,
which does not exist yet in this delivery.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import EventCategory
from database.models.story import Story
from services.text_normalization import normalize_for_entity_match, token_overlap_ratio

# --- outcomes -----------------------------------------------------------------------------

NEW_STORY = "new_story"
STORY_UPDATE = "story_update"
# Phase 18.10 M7 (novelty scoring): a confident match whose title is substantially similar to an
# existing story - most often another outlet corroborating the same core event without adding
# new substance - distinct from SEMANTIC_DUPLICATE (near-identical/rehash title) and from
# STORY_UPDATE (materially different title, a real new development). Sits between the two on the
# title-overlap spectrum, not a separate scoring dimension.
SUPPORTING_SOURCE = "supporting_source"
SEMANTIC_DUPLICATE = "semantic_duplicate"
UNCERTAIN_MATCH = "uncertain_match"

# --- topic buckets --------------------------------------------------------------------------
# Deliberately few and broad (not one bucket per news-type) - the false-positive-protection goal
# is separating clearly-unrelated categories of news about the same entity (a product launch vs.
# a regulatory-commentary story about the same company), not finely taxonomizing every possible
# angle. "product" in particular is intentionally broad enough to keep a launch and its own
# follow-up benchmark/feature coverage in the same bucket (docs/phase18_10_editorial_intelligence_
# report.md's own worked example) - splitting those into separate buckets would defeat the
# feature's own purpose.
TOPIC_PRODUCT = "product"
TOPIC_FINANCIAL = "financial"
TOPIC_CORPORATE = "corporate"
TOPIC_LEGAL_REGULATORY = "legal_regulatory"
TOPIC_SECURITY_INCIDENT = "security_incident"
TOPIC_OTHER = "other"

# Checked narrowest/most-specific first, since a title could plausibly contain generic
# product-ish words alongside a more specific signal (e.g. "regulator opens probe into new AI
# chip" should classify as legal_regulatory, not product, even though "chip" would match product
# too) - first match wins, in this fixed priority order.
_TOPIC_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        TOPIC_SECURITY_INCIDENT,
        (
            "breach", "hack", "hacked", "vulnerability", "exploit", "leaked", "leak", "malware",
            "cyberattack", "взлом", "утечка", "уязвимость", "кибератака", "вредонос",
        ),
    ),
    (
        TOPIC_LEGAL_REGULATORY,
        (
            "lawsuit", "sue", "sues", "sued", "regulation", "regulator", "antitrust", "ban",
            "banned", "fine", "fined", "investigation", "court", "probe", "compliance", "law",
            "суд", "иск", "регулятор", "закон", "штраф", "расследование", "запрет", "запретил",
        ),
    ),
    (
        TOPIC_FINANCIAL,
        (
            "earnings", "revenue", "profit", "loss", "funding", "raised", "raises", "valuation",
            "ipo", "quarterly", "financial results", "выручка", "прибыль", "убыток",
            "инвестиции", "раунд", "оценка", "финансовые результаты",
        ),
    ),
    (
        TOPIC_CORPORATE,
        (
            "ceo", "executive", "hires", "hired", "resigns", "resigned", "appoints", "appointed",
            "merger", "acquisition", "acquires", "partnership", "board", "leadership",
            "гендиректор", "директор", "назначил", "партнёрство", "партнерство", "слияние",
            "поглощение", "совет директоров",
        ),
    ),
    (
        TOPIC_PRODUCT,
        (
            "launch", "launches", "launched", "release", "releases", "released", "unveil",
            "unveils", "unveiled", "introduce", "introduces", "introduced", "announce",
            "announces", "announced", "update", "updated", "upgrade", "feature", "benchmark",
            "benchmarks", "version", "model", "релиз", "выпустил", "представил", "анонсировал",
            "бенчмарк", "версия", "обновление", "запустил",
        ),
    ),
)

# Capitalized-run entity heuristic: one or more consecutive words each starting with an
# uppercase Latin/Cyrillic letter, allowing internal digits/hyphens/dots (so "GPT-4", "GPT-5.6",
# "iPhone"-style would still need the leading capital - a documented, narrow heuristic, not a
# real NER model). Deliberately a new, narrow regex here rather than reusing
# services/fact_safety.py's own quote-extraction regexes - different purpose, same
# intentional-narrow-duplication convention this codebase already uses between
# capabilities/copywriting_capability.py's and capabilities/intelligence_capability.py's own
# duplicated _floor_validate.
_ENTITY_RUN_RE = re.compile(r"[A-ZА-ЯЁ][\w\-.]*(?:\s+[A-ZА-ЯЁ][\w\-.]*)*")
_MIN_ENTITY_LEN = 2

# Significant title keyword extraction - length-filtered, matches text_normalization's own
# min_token_len=3 convention for token_overlap_ratio.
_WORD_RE = re.compile(r"[\w\-]+", re.UNICODE)
_MIN_KEYWORD_LEN = 3

# Bounded candidate window (mirrors services/editorial_scoring.py::fetch_engagement_baseline()'s
# own "bounded window, scored in Python" pattern exactly) - recent, same-category stories only,
# never the full table.
STORY_MATCH_LOOKBACK_DAYS = 14
STORY_MATCH_CANDIDATE_LIMIT = 50

# Reasoned, not fit to historical outcome data (none exists yet - this is a brand-new signal,
# same disclosed-limitation convention as services/editorial_scoring.py's own weight comments).
# Tunable without a code change is deliberately NOT offered yet (unlike editorial_scoring's
# weights) - shadow-mode data from this phase's own bake period is what should inform whether
# these need to become settings, not a guess made before any real data exists.
_LOW_THRESHOLD = 0.35
_HIGH_THRESHOLD = 0.65
# Within the confident-match zone (combined >= _HIGH_THRESHOLD), title_overlap alone decides the
# 3-way split between SEMANTIC_DUPLICATE / SUPPORTING_SOURCE / STORY_UPDATE - a near-identical
# title is a rehash, a substantially-similar-but-not-identical title is another source
# corroborating the same event, and a materially different title (while still clearing the
# entity-driven combined-score floor) signals real new information. Reasoned, not fit to
# historical data (none exists yet - same disclosed-limitation convention as
# services/editorial_scoring.py's own weight comments).
_DUPLICATE_TITLE_OVERLAP_THRESHOLD = 0.75
_SUPPORTING_SOURCE_TITLE_OVERLAP_THRESHOLD = 0.55

_ENTITY_WEIGHT = 0.6
_TITLE_WEIGHT = 0.4


@dataclass(frozen=True)
class StorySignature:
    entities: list[str]
    keywords: list[str]
    topic_bucket: str


@dataclass(frozen=True)
class MatchResult:
    outcome: str  # NEW_STORY | STORY_UPDATE | SUPPORTING_SOURCE | SEMANTIC_DUPLICATE | UNCERTAIN_MATCH
    matched_story_id: UUID | None
    confidence: float
    similarity_reason: str


def _extract_entities(title: str) -> list[str]:
    """Normalized, de-duplicated, order-preserving. A bare first-word capital (sentence-initial
    capitalization, not a real entity) is not specially excluded - a documented, accepted
    imprecision of this narrow heuristic (see module docstring)."""
    seen: dict[str, None] = {}
    for match in _ENTITY_RUN_RE.finditer(title):
        candidate = match.group(0).strip()
        if len(candidate) < _MIN_ENTITY_LEN:
            continue
        normalized = normalize_for_entity_match(candidate)
        if normalized and normalized not in seen:
            seen[normalized] = None
    return list(seen.keys())


def _extract_keywords(title: str) -> list[str]:
    from services.text_normalization import normalize_loose

    seen: dict[str, None] = {}
    for token in _WORD_RE.findall(normalize_loose(title)):
        if len(token) >= _MIN_KEYWORD_LEN and token not in seen:
            seen[token] = None
    return list(seen.keys())


def _classify_topic(title: str) -> str:
    from services.text_normalization import normalize_loose

    normalized = normalize_loose(title)
    for bucket, keywords in _TOPIC_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return bucket
    return TOPIC_OTHER


def extract_story_signature(title: str, category: EventCategory) -> StorySignature:
    """Pure. Deterministic: identical input always produces an identical signature.
    `category` is accepted for interface symmetry with `match_story()` (both take the same two
    facts about an event) even though the signature itself does not currently vary by category -
    matching is scoped to same-category candidates by the caller, not by this function."""
    del category  # not used in the signature itself - see docstring
    return StorySignature(
        entities=_extract_entities(title),
        keywords=_extract_keywords(title),
        topic_bucket=_classify_topic(title),
    )


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def score_candidate(
    title: str, signature: StorySignature, candidate_title: str, candidate: Story
) -> tuple[float, float, float]:
    """Pure. Returns (combined_score, entity_overlap, title_overlap) for one candidate story -
    the caller is responsible for the hard topic-bucket gate (candidates with a different
    topic_bucket are never even scored, per the module's own false-positive-protection design -
    see docs/phase18_10_editorial_intelligence_report.md's worked examples)."""
    candidate_entities = set(candidate.entities or [])
    entity_overlap = _jaccard(set(signature.entities), candidate_entities)
    title_overlap = token_overlap_ratio(title, candidate_title)
    combined = _ENTITY_WEIGHT * entity_overlap + _TITLE_WEIGHT * title_overlap
    return combined, entity_overlap, title_overlap


async def _fetch_candidate_stories(
    session: AsyncSession, category: EventCategory, *, now: datetime
) -> list[Story]:
    cutoff = now - timedelta(days=STORY_MATCH_LOOKBACK_DAYS)
    stmt = (
        select(Story)
        .where(Story.category == category, Story.updated_at >= cutoff)
        .order_by(Story.updated_at.desc())
        .limit(STORY_MATCH_CANDIDATE_LIMIT)
    )
    return list((await session.execute(stmt)).scalars().all())


async def match_story(
    session: AsyncSession, *, title: str, category: EventCategory, now: datetime | None = None
) -> tuple[StorySignature, MatchResult]:
    """The only orchestration entry point services/triage_orchestrator.py calls. Does one bounded,
    indexed, same-category query (see `_fetch_candidate_stories`) - never an unbounded table scan.

    Returns both the extracted signature (the caller persists it onto the new Story if this
    becomes a new_story) and the match result. Never creates or mutates a Story row itself - that
    is the caller's responsibility (keeps this module read-only/pure-adjacent, mirroring
    services/editorial_scoring.py's own apply_editorial_scoring_v2() not owning persistence
    either)."""
    reference_now = now if now is not None else datetime.now(timezone.utc)
    signature = extract_story_signature(title, category)
    candidates = await _fetch_candidate_stories(session, category, now=reference_now)

    topic_matches = [c for c in candidates if c.topic_bucket == signature.topic_bucket]
    if not topic_matches:
        reason = (
            "no candidate stories in matching category/topic_bucket "
            f"(topic_bucket={signature.topic_bucket})"
        )
        return signature, MatchResult(NEW_STORY, None, 1.0, reason)

    best: tuple[float, float, float, Story] | None = None
    for candidate in topic_matches:
        combined, entity_overlap, title_overlap = score_candidate(title, signature, candidate.title, candidate)
        if best is None or combined > best[0]:
            best = (combined, entity_overlap, title_overlap, candidate)

    assert best is not None  # topic_matches is non-empty, so the loop ran at least once
    combined, entity_overlap, title_overlap, candidate = best

    if combined < _LOW_THRESHOLD:
        reason = (
            f"best same-bucket candidate score {combined:.2f} below low threshold "
            f"{_LOW_THRESHOLD:.2f} (entity_overlap={entity_overlap:.2f}, title_overlap={title_overlap:.2f})"
        )
        return signature, MatchResult(NEW_STORY, None, 1.0 - combined, reason)

    if combined >= _HIGH_THRESHOLD:
        if title_overlap >= _DUPLICATE_TITLE_OVERLAP_THRESHOLD:
            reason = (
                f"near-identical title (title_overlap={title_overlap:.2f}) - same event, "
                f"likely a different source's coverage (entity_overlap={entity_overlap:.2f}, "
                f"topic_bucket={signature.topic_bucket} match)"
            )
            return signature, MatchResult(SEMANTIC_DUPLICATE, candidate.id, combined, reason)
        if title_overlap >= _SUPPORTING_SOURCE_TITLE_OVERLAP_THRESHOLD:
            reason = (
                f"confident match, substantially similar but not identical title "
                f"(title_overlap={title_overlap:.2f}) - likely a corroborating source, not new "
                f"substance (entity_overlap={entity_overlap:.2f}, topic_bucket="
                f"{signature.topic_bucket} match)"
            )
            return signature, MatchResult(SUPPORTING_SOURCE, candidate.id, combined, reason)
        reason = (
            f"confident match, materially different title (entity_overlap={entity_overlap:.2f}, "
            f"title_overlap={title_overlap:.2f}, topic_bucket={signature.topic_bucket} match)"
        )
        return signature, MatchResult(STORY_UPDATE, candidate.id, combined, reason)

    reason = (
        f"borderline score {combined:.2f} between thresholds [{_LOW_THRESHOLD:.2f}, "
        f"{_HIGH_THRESHOLD:.2f}) - not confidently new or matched "
        f"(entity_overlap={entity_overlap:.2f}, title_overlap={title_overlap:.2f})"
    )
    return signature, MatchResult(UNCERTAIN_MATCH, candidate.id, combined, reason)
