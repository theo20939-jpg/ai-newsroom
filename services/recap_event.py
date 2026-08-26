"""NINJA PULSE RECAP - Phase R1: offline EVENT_RECAP foundation (event model, announcement
clustering, lifecycle state, deterministic readiness).

Pure, deterministic, LLM-free, network-free - no exception anywhere in this module. Built
entirely on top of already-existing, already-shipped machinery:

    database/models/story.py::Story              - the RecapEvent's underlying grouping entity
    database/models/story_link.py::NewsEventStoryLink - confirmed story membership
    services/story_memory.py::extract_story_signature/symmetric_token_overlap - reused primitives

RecapEvent is a DERIVED, service-layer representation in R1 - no new ORM model, no new table, no
migration. A `Story` row already *is* the grouping; this module only adds recap-specific
interpretation on top of it (announcement clustering, lifecycle state, readiness), read-only.

Story membership caveat (a real forensic finding, not an assumption): `services/
triage_orchestrator.py` writes a `NewsEventStoryLink` row for EVERY event considered against a
story, including weak/rejected matches (UNCERTAIN_MATCH, RELATED_STORY) - "for observability,"
per that module's own comment - not only confirmed continuations. `Story.event_count` only counts
NEW_STORY (the origin event) + STORY_UPDATE/SUPPORTING_SOURCE/SEMANTIC_DUPLICATE. `load_story_events()`
below filters to exactly that same set, so "events belonging to this story" here means the same
thing `Story.event_count` already means - never the wider, unfiltered link set.

Zero AI editorial scoring: `evaluate_recap_readiness()` returns explicit deterministic reasons,
never a synthetic 0-100 "readiness score" (spec's own explicit "no AI score" instruction).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.news_event import NewsEvent
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from services.story_memory import (
    NEW_STORY,
    STORY_UPDATE,
    SUPPORTING_SOURCE,
    SEMANTIC_DUPLICATE,
    StorySignature,
    _extract_entities,
    extract_story_signature,
)
from services.text_normalization import normalize_loose, symmetric_token_overlap

# --- RecapMode (plain string constants - mirrors this codebase's own established convention for
# small closed vocabularies, e.g. services/editorial_treatment.py's SKIP/BRIEF/STANDARD/MAJOR,
# services/story_memory.py's own NEW_STORY/STORY_UPDATE/... - never a Python Enum class here). ---
EVENT_RECAP = "EVENT_RECAP"
WEEKLY_RECAP = "WEEKLY_RECAP"

# --- RecapEventState -----------------------------------------------------------------------
DISCOVERED = "DISCOVERED"
ACTIVE = "ACTIVE"
COOLING = "COOLING"
READY = "READY"
# Declared for future compatibility (spec §6's own explicit "may exist for future compatibility")
# - R1 never assigns these; they would require durable delivery-state persistence this checkpoint
# deliberately does not add (spec §17: "RECAP ContentDraft persistence" is out of scope).
PUBLISHED = "PUBLISHED"
CLOSED = "CLOSED"

# The exact NewsEventStoryLink.match_type values that count as CONFIRMED membership in a story -
# the same set Story.event_count already counts (services/triage_orchestrator.py's own write
# path) - RELATED_STORY and UNCERTAIN_MATCH are deliberately excluded (present in the link table
# "for observability" only, never a confirmed continuation of this story's own event history).
_CONFIRMED_MEMBERSHIP_MATCH_TYPES = frozenset({NEW_STORY, STORY_UPDATE, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE})


@dataclass(frozen=True)
class AnnouncementCluster:
    cluster_id: int
    event_ids: list[UUID]
    headline: str  # the earliest (anchor) event's own title, verbatim - never generated
    source_urls: list[str]
    source_domains: list[str]
    first_seen_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class RecapEventSnapshot:
    story_id: UUID
    first_event_id: UUID
    # Phase R1.3 correction (real forensic finding, R1.2 production replay: repeated mismatches
    # like 6->5, 11->10, 8->7, 5->4, 4->3 between Story.event_count and the actual confirmed-member
    # link count): `event_count` here is ALWAYS len(load_story_events(...)) - the authoritative
    # signal for readiness/diagnostics - never `Story.event_count` itself. `declared_event_count`
    # is `Story.event_count` verbatim, kept ONLY as a diagnostic/storage-field comparison value -
    # never used for any eligibility decision. `Story.event_count` itself is never written to here.
    event_count: int
    declared_event_count: int
    created_at: datetime
    updated_at: datetime
    state: str
    announcement_count: int
    unique_source_count: int
    has_primary_source: bool | None  # None = UNKNOWN (spec §5's own explicit "do not guess")
    cooling_elapsed: bool
    research_complete: bool
    unresolved_conflict_count: int
    readiness_reason: str
    # Phase R1.3: the Story Integrity Gate's own verdict, carried alongside readiness so a caller
    # never has to re-derive "was this story even coherent" from the announcement/readiness fields
    # alone - see StoryIntegrityResult/evaluate_recap_story_integrity() below.
    story_integrity_eligible: bool
    story_integrity_reasons: list[str]
    announcements: list[AnnouncementCluster] = field(default_factory=list)


@dataclass(frozen=True)
class StoryIntegrityResult:
    """Phase R1.3: pure, deterministic. Answers "do these confirmed member NewsEvents plausibly
    describe ONE real-world developing story/event?" - a question distinct from and answered BEFORE
    announcement clustering (which instead answers "are these separate announcements WITHIN an
    already-presumed-coherent story?"). See evaluate_recap_story_integrity()'s own docstring for
    the full algorithm and the real production false-positive examples (R1.2 replay) this exists to
    catch - e.g. a Story titled "What are you doing this weekend?" that had accumulated unrelated
    articles about hybrid batteries, a robot companion, app tracking, and retro consoles, or arXiv
    Story clusters grouped purely because titles share a generic lexical opening ("Large language
    models...", "Recent...", "Despite...", "Autonomous...").

    No synthetic 0-100 score (mirrors evaluate_recap_readiness()'s own explicit "no AI score"
    discipline) - `eligible` is an explicit boolean, `reasons` is human-readable, `metrics` exposes
    the raw signals (never hidden inside a single number)."""
    eligible: bool
    reasons: list[str]
    metrics: dict[str, object]


@dataclass(frozen=True)
class ReadinessResult:
    ready: bool
    state: str
    reasons: list[str]
    metrics: dict[str, object]


# ---------------------------------------------------------------------------
# 1. Story event loading (§3)
# ---------------------------------------------------------------------------


async def load_story_events(session: AsyncSession, story_id: UUID) -> list[NewsEvent]:
    """Loads exactly the NewsEvents CONFIRMED as belonging to `story_id` (see module docstring's
    "Story membership caveat"), in deterministic chronological order (published_at, falling back
    to collected_at when published_at is unknown - the same coalesce anchor worker/content_cycle.py
    already established as this codebase's one authoritative freshness field, reused here for the
    same reason: consistency, not a new convention). No external fetch, no unrelated events."""
    stmt = (
        select(NewsEvent)
        .join(NewsEventStoryLink, NewsEventStoryLink.news_event_id == NewsEvent.id)
        .where(
            NewsEventStoryLink.story_id == story_id,
            NewsEventStoryLink.match_type.in_(_CONFIRMED_MEMBERSHIP_MATCH_TYPES),
        )
        .order_by(NewsEvent.published_at.asc().nulls_last(), NewsEvent.collected_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# 1.5. Story Integrity Gate (Phase R1.3) - runs BEFORE announcement clustering/readiness.
# ---------------------------------------------------------------------------

# Mirrors services/story_memory.py's own _ENTITY_WEIGHT/_TITLE_WEIGHT (0.6/0.4) exactly, NOT
# services/recap_event.py's own inverted 0.4/0.6 announcement-clustering weights below - a
# deliberate distinction (see module-level note above _ANNOUNCEMENT_ENTITY_WEIGHT for why
# clustering inverts it). Story integrity asks the SAME question story_memory.py's own
# score_candidate() asks when first deciding whether a candidate event belongs to a story at all
# ("is this genuinely the same real-world story"), so it reuses that function's own weighting
# philosophy (entity evidence dominates) rather than announcement clustering's finer-grained,
# title-dominant weighting.
_INTEGRITY_ENTITY_WEIGHT = 0.6
_INTEGRITY_TITLE_WEIGHT = 0.4

# Coherence-score floor for a non-anchor member to count as "plausibly coherent with the Story's
# original event" - deliberately LOWER than announcement clustering's 0.75 (that threshold asks a
# much narrower question: "is this the SAME SPECIFIC announcement" - integrity only asks "is this
# plausibly part of the same real-world story," which real developing coverage can satisfy with
# much looser wording/entity overlap). Two floors: entities-available (both anchor and event
# extracted at least one real entity after generic-leading-entity stripping) uses the lower floor;
# entities-unavailable falls back to title overlap alone, which is inherently weaker evidence, so
# it must clear a higher bar (spec §5.C's own "do not fail solely because entity extraction is
# empty" - a floor exists specifically so this fallback isn't a free pass either).
_INTEGRITY_ANCHOR_COHERENCE_MIN_SCORE = 0.30
_INTEGRITY_ANCHOR_COHERENCE_MIN_SCORE_NO_ENTITIES = 0.45

# Phase R1.5A.2 correction (real PRODUCTION forensic finding, R1.5A.1 replay - see the R1.5A.2
# report's own item A): R1.5A's anchor-centered rule decided generic-leading-entity exclusion once,
# GLOBALLY, for the entire Story (a FRACTION of the anchor's same-leading-entity links had to
# qualify before the entity was "preserved" for every pairwise comparison). Real production data
# proved this is STILL a spillover-authority bug, just relocated to anchor scope: a Story with one
# genuine near-duplicate member (anchor residual ~1.0) plus several genuinely unrelated members
# (anchor residual ~0.0) can clear a small qualifying fraction (e.g. 1/3 = 0.33 >= 0.20) from the
# ONE duplicate alone, which then globally preserves the entity and hands every unrelated member a
# free `entity_jaccard=1.0` it never earned on its own (real "Recent"/"Despite" Stories, both
# confirmed PASS in production despite containing clearly unrelated papers).
#
# Fixed by removing Story-wide authority entirely: whether the anchor's leading entity counts as
# evidence is now decided PER anchor->member PAIR, independently, inside
# `evaluate_recap_story_integrity()` itself (no separate story-wide helper). For a given pair, if
# the member shares the anchor's own leading entity, `_residual_overlap_excluding_entity()` is
# measured for THAT pair; below `_INTEGRITY_ANCHOR_RESIDUAL_FLOOR` the entity is excluded from BOTH
# sides for THAT pair only (every other pair is unaffected) - a genuine duplicate can still get full
# entity credit while an unrelated member sharing only the same generic opener cannot free-ride on
# it. This is a stricter guarantee than the old fraction-based rescue: no single pair, however
# strong, can ever hand entity credit to a DIFFERENT pair again.
#
# The floor value itself (0.40) is unchanged from R1.5A - re-verified against real production
# Bashkiria evidence in R1.5A.1: the real anchor's best single link (0.429) still clears it, its
# other two links (0.000, 0.133-0.167 range) still do not - do not retune this checkpoint.
_INTEGRITY_ANCHOR_RESIDUAL_FLOOR = 0.40

_INTEGRITY_MIN_ANCHOR_COHERENT_RATIO = 0.5

_INTEGRITY_WORD_RE = re.compile(r"[\w\-]+", re.UNICODE)


def _leading_entity(signature: StorySignature) -> str | None:
    return signature.entities[0] if signature.entities else None


def _residual_overlap_excluding_entity(entity: str, title_a: str, title_b: str) -> float:
    """Pure. Dice overlap between `title_a`/`title_b` after removing the candidate `entity`'s own
    words from both token sets first - isolates whether real content evidence exists BEYOND the
    shared leading entity itself (mirrors the same "exclude the shared fact's own words" technique
    Phase R1.4.2 established for announcement-identity evidence, reimplemented independently here
    - deliberately not imported from that module, to keep the Story Integrity Gate's own primitives
    fully self-contained per spec R1.5A's explicit "integrity-only" scope)."""
    entity_words = set(entity.split())
    tokens_a = {t for t in _INTEGRITY_WORD_RE.findall(normalize_loose(title_a)) if len(t) >= 3 and t not in entity_words}
    tokens_b = {t for t in _INTEGRITY_WORD_RE.findall(normalize_loose(title_b)) if len(t) >= 3 and t not in entity_words}
    if not tokens_a or not tokens_b:
        return 0.0
    return 2 * len(tokens_a & tokens_b) / (len(tokens_a) + len(tokens_b))


def _integrity_coherence_score(
    anchor_entities: set[str], anchor_title: str, event_entities: set[str], event_title: str,
) -> float:
    if not anchor_entities or not event_entities:
        return symmetric_token_overlap(anchor_title, event_title)
    entity_overlap = _jaccard(anchor_entities, event_entities)
    title_overlap = symmetric_token_overlap(anchor_title, event_title)
    return min(1.0, _INTEGRITY_ENTITY_WEIGHT * entity_overlap + _INTEGRITY_TITLE_WEIGHT * title_overlap)


def evaluate_recap_story_integrity(
    anchor_event: NewsEvent, member_events: list[NewsEvent],
) -> StoryIntegrityResult:
    """Pure, deterministic. Answers "do these confirmed member events plausibly describe one
    real-world developing story?" - NOT "are these separate announcements" (that remains
    cluster_announcements()'s own, separate job - spec §4's explicit layering).

    Algorithm: `anchor_event` (the Story's own `first_event_id` row - spec §8's own explicit
    instruction to use the actual first/original event as the existing system defines it, not
    merely the chronologically-earliest confirmed event, though in practice these coincide since
    `first_event_id` is set once, at Story creation, to the event that originated the story -
    confirmed via services/triage_orchestrator.py's own Story(...) construction, never updated
    afterward) is compared against every OTHER confirmed member event, one PAIR at a time.

    Phase R1.5A.2 correction (real PRODUCTION forensic finding - see the R1.5A.2 report's own item
    A/N and `_INTEGRITY_ANCHOR_RESIDUAL_FLOOR`'s own docstring for the full derivation): generic-
    leading-entity filtering is now decided PER anchor->member pair, never once for the whole Story.
    For each `event` in `others`: if `event` shares the anchor's own leading entity, this function
    measures `_residual_overlap_excluding_entity()` for THAT PAIR ALONE; below
    `_INTEGRITY_ANCHOR_RESIDUAL_FLOOR` the shared entity is removed from BOTH sides for THAT PAIR's
    own coherence score only - every other pair's entity sets are entirely unaffected, so one
    genuine near-duplicate member can never again hand a free `entity_jaccard=1.0` to an unrelated
    one. The resulting (possibly pair-filtered) entity sets feed `_integrity_coherence_score()`
    (entity overlap weighted 0.6, title Dice overlap weighted 0.4 - mirrors story_memory.py's own
    matching weights, see the module-level constants above for why this differs from announcement
    clustering's inverted weights). A member counts as "anchor-coherent" if its score clears
    `_INTEGRITY_ANCHOR_COHERENCE_MIN_SCORE` (or the stricter `_INTEGRITY_ANCHOR_COHERENCE_MIN_SCORE_
    NO_ENTITIES` floor when either side's pair-specific entities are empty - spec §5.C's own "do not
    fail solely because entity extraction is empty," i.e. this is a fallback, not an automatic
    failure).

    `eligible = True` iff at least `_INTEGRITY_MIN_ANCHOR_COHERENT_RATIO` of the non-anchor members
    are anchor-coherent. A single-event Story (no other confirmed members) trivially passes - there
    is no group to be incoherent (spec §3's own conceptual flow only concerns itself with grouped
    Stories; a lone event's readiness is still separately gated by recap_min_event_count elsewhere).

    Temporal compactness (spec §5.E) is reported as a `metrics`/informational `reasons` entry when
    it exceeds `settings.recap_integrity_max_time_span_hours`, but is deliberately NOT itself a
    blocking condition - a genuinely coherent, slow-developing real story (e.g. a weeks-long legal
    case) should not fail integrity purely for taking a long time; §5.E's own wording ("should be
    suspicious," not "must fail") supports a soft, disclosed signal rather than a hard gate here."""
    others = [e for e in member_events if e.id != anchor_event.id]
    if not others:
        return StoryIntegrityResult(
            eligible=True,
            reasons=["single-event story - no group coherence to evaluate"],
            metrics={"member_count": 1, "anchor_coherent_count": 0, "anchor_total_others": 0, "anchor_coherent_ratio": 1.0},
        )

    anchor_signature = extract_story_signature(anchor_event.title, anchor_event.category)
    anchor_leading = _leading_entity(anchor_signature)
    anchor_entities_full = set(anchor_signature.entities)

    coherent_count = 0
    per_event_scores: dict[str, float] = {}
    pair_entity_exclusions: dict[str, str] = {}
    for event in others:
        event_signature = extract_story_signature(event.title, event.category)
        pair_anchor_entities = set(anchor_entities_full)
        pair_event_entities = set(event_signature.entities)

        if anchor_leading is not None and _leading_entity(event_signature) == anchor_leading:
            residual = _residual_overlap_excluding_entity(anchor_leading, anchor_event.title, event.title)
            if residual < _INTEGRITY_ANCHOR_RESIDUAL_FLOOR:
                pair_anchor_entities.discard(anchor_leading)
                pair_event_entities.discard(anchor_leading)
                pair_entity_exclusions[str(event.id)] = anchor_leading

        score = _integrity_coherence_score(pair_anchor_entities, anchor_event.title, pair_event_entities, event.title)
        per_event_scores[str(event.id)] = round(score, 3)
        floor = (
            _INTEGRITY_ANCHOR_COHERENCE_MIN_SCORE if (pair_anchor_entities and pair_event_entities)
            else _INTEGRITY_ANCHOR_COHERENCE_MIN_SCORE_NO_ENTITIES
        )
        if score >= floor:
            coherent_count += 1

    ratio = coherent_count / len(others)
    reasons: list[str] = []
    if ratio < _INTEGRITY_MIN_ANCHOR_COHERENT_RATIO:
        reasons.append(
            f"anchor_coherent_ratio {ratio:.2f} < required {_INTEGRITY_MIN_ANCHOR_COHERENT_RATIO} "
            f"({coherent_count}/{len(others)} members plausibly coherent with the Story's original event)"
        )
    eligible = not reasons

    all_events = [anchor_event, *others]
    anchor_time = anchor_event.published_at or anchor_event.collected_at
    all_times = [e.published_at or e.collected_at for e in all_events]
    time_span_hours = (max(all_times) - min(all_times)).total_seconds() / 3600
    if time_span_hours > settings.recap_integrity_max_time_span_hours:
        reasons.append(
            f"time span {time_span_hours:.1f}h exceeds configured max "
            f"{settings.recap_integrity_max_time_span_hours}h - long-running grouping, verify "
            "coherence carefully (informational only, not itself disqualifying)"
        )

    if eligible and not any("time span" in r for r in reasons):
        reasons.insert(
            0,
            f"{coherent_count}/{len(others)} members plausibly coherent with the Story's original "
            f"event (ratio {ratio:.2f})",
        )

    metrics: dict[str, object] = {
        "member_count": len(all_events),
        "anchor_coherent_count": coherent_count,
        "anchor_total_others": len(others),
        "anchor_coherent_ratio": round(ratio, 3),
        # Phase R1.5A.2: per-pair, not Story-wide - only members whose OWN pair with the anchor had
        # the shared leading entity excluded appear here, keyed by event_id. Replaces R1.5A's
        # Story-wide "generic_leading_entities_stripped" list (removed - no longer a meaningful
        # concept once filtering is pair-specific; see this function's own docstring).
        "pair_entity_exclusions": pair_entity_exclusions,
        "time_span_hours": round(time_span_hours, 1),
        "anchor_event_id": str(anchor_event.id),
        "anchor_time": anchor_time.isoformat(),
        "per_event_coherence_scores": per_event_scores,
    }
    return StoryIntegrityResult(eligible=eligible, reasons=reasons, metrics=metrics)


# ---------------------------------------------------------------------------
# 2. Announcement clustering (§4)
# ---------------------------------------------------------------------------

# Deliberately the INVERSE weighting of services/story_memory.py's own _ENTITY_WEIGHT/_TITLE_WEIGHT
# (0.6/0.4) - reasoned, not copied: every event reaching this function already shares confirmed
# story membership, so entity overlap between two of THESE events is expected to be high and
# comparatively uninformative (the same company/product entities recur throughout one story);
# title-level wording differences carry the real "same announcement or a new development" signal
# at this finer grain. A reasoned starting point, explicitly NOT calibrated against a real replay
# dataset yet - the same disclosed-default discipline services/story_memory.py's own thresholds
# document for themselves.
_ANNOUNCEMENT_ENTITY_WEIGHT = 0.4
_ANNOUNCEMENT_TITLE_WEIGHT = 0.6

# Phase R1.5B.1: see `_announcement_similarity()`'s own docstring for the real regression this
# closes. Comfortably below `settings.recap_announcement_cluster_threshold` (0.75) so a proven
# conflicting-fact pair can never cross it via ordinary fuzzy similarity alone, regardless of how
# high title overlap happens to measure (two titles differing only in a conflicting number can
# measure very high title overlap - this cap does not depend on that number staying small).
_CONFLICTING_FACTS_SIMILARITY_CAP = 0.5


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _announcement_similarity(sig_a: StorySignature, title_a: str, sig_b: StorySignature, title_b: str) -> float:
    """Phase R1.4 bug fix (real production forensic finding, confirmed by direct execution before
    this fix): when EITHER title's extracted entity set is empty (a common, ordinary case - e.g.
    "The rapid growth of social media..." legitimately extracts zero entities, since "The" is
    already correctly excluded as a generic determiner by services/story_memory.py's own existing
    logic), the original formula computed `_jaccard(a, b)` over two EMPTY sets, which
    `_jaccard()` itself defines as 0.0 ("no evidence" - a reasonable definition for THAT function in
    isolation). But blended into `0.4*entity + 0.6*title` unconditionally, this silently CAPPED the
    combined score at 0.6 (0.4*0.0 + 0.6*1.0) for ANY pair of titles whose entities are empty -
    including two BYTE-IDENTICAL titles (title_dice=1.0) - permanently below the 0.75 threshold.
    Confirmed by direct execution, not assumed: this is an algorithmic flaw, not a threshold-
    calibration issue (spec R1.4 §4's own required distinction).

    Fix: when either side's entities are empty, fall back to title overlap ALONE (mirrors the exact
    same fallback services/recap_event.py's own Story Integrity Gate coherence score already uses
    for the identical structural reason - see `_integrity_coherence_score()`) - entity evidence
    being unavailable is not the same as entity evidence proving dissimilarity.

    Phase R1.5B.1 addition (real regression found and fixed WITHIN this same checkpoint, via this
    checkpoint's own required negative-control test - spec R1.5B.1 §11): when the two titles have a
    PROVEN conflicting distinctive fact (`_has_conflicting_distinctive_facts()` - a different number,
    or an asymmetric distinctive entity), entity evidence is excluded from this score entirely and
    the result is capped at `_CONFLICTING_FACTS_SIMILARITY_CAP` (comfortably below the 0.75
    announcement threshold) - mirroring the exact same protective role the same conflict check
    already plays for `_has_distinctive_shared_evidence()`/`_has_temporally_corroborated_distinctive_
    evidence()`, just extended to the ordinary weighted-fuzzy path too. Necessary because this
    checkpoint's own publisher-suffix sanitization (`_sanitized_announcement_signature()`)
    legitimately raises entity_jaccard for genuinely-same-content pairs that previously relied on
    incidental publisher-entity noise to stay below threshold - confirmed by direct execution: two
    titles differing ONLY in a conflicting number ("$314" vs "$500", same publisher-suffix pattern)
    measured entity_jaccard=1.0 and title_overlap=0.875 once publisher noise was removed from both
    sides, crossing 0.75 via ordinary fuzzy alone even though the numbers explicitly conflict."""
    if _has_conflicting_distinctive_facts(sig_a, title_a, sig_b, title_b):
        return min(symmetric_token_overlap(title_a, title_b), _CONFLICTING_FACTS_SIMILARITY_CAP)
    entities_a, entities_b = set(sig_a.entities), set(sig_b.entities)
    title_overlap = symmetric_token_overlap(title_a, title_b)
    if not entities_a or not entities_b:
        return title_overlap
    entity_overlap = _jaccard(entities_a, entities_b)
    return min(1.0, _ANNOUNCEMENT_ENTITY_WEIGHT * entity_overlap + _ANNOUNCEMENT_TITLE_WEIGHT * title_overlap)


# ---------------------------------------------------------------------------
# 2.1 Announcement identity precedence (Phase R1.4 §5-9) - deterministic strong-evidence rules
# that run BEFORE the weighted fuzzy formula above. Exact/near-exact lexical identity, or a
# distinctive shared fact (a real entity or a specific number), is stronger evidence of "same
# announcement" than noisy entity extraction - and must not be vetoed by it.
# ---------------------------------------------------------------------------

# A trailing " - X" / " | X" / " — X" style segment, where X is short (<=4 words), is a candidate
# publisher/source suffix (spec §6's own "3DNews"/"Хабр"/"Yahoo Finance"/"The AI Journal" examples)
# - NEVER stripped unconditionally (spec's own "do not aggressively strip legitimate headline
# text"): only ever tried as an ALTERNATE candidate string when checking near-exact equality
# against ANOTHER title (see `_is_near_exact_title_match()`) - a coincidental false strip can only
# ever matter if it happens to also exactly match a different real title's own stripped form,
# which is not a realistic accident.
_TRAILING_SUFFIX_RE = re.compile(r"\s*[-–—|]\s*([^-–—|]{1,60})$")
_TRAILING_SUFFIX_MAX_WORDS = 4

# Phase I.2.2F (real production forensic finding, I.2.2E - a real AWS blog series: "... Part 1:
# Setting up your" / "... Part 2: Data preparation and" / "... Part 3: Visualizing insights"):
# an enumerated-series installment marker ("Part <N>: ...") can coincidentally satisfy the generic
# trailing-suffix shape (short, delimiter-introduced segment) exactly like a real "Title -
# Publisher" suffix does, but it is genuine content - the series numbering IS the distinguishing
# fact between sibling announcements, never publisher noise. Deliberately narrow (English "Part
# <digits>:" only, anchored at the START of the candidate segment) - does not touch any other
# colon-containing suffix shape (e.g. "BREAKING: ... - CNN" still strips "CNN" normally).
_ENUMERATED_SERIES_SUFFIX_RE = re.compile(r"(?i)^part\s+\d+\s*:")

# Phase I.2.2F: an isolated "/ <short segment>" path/breadcrumb immediately preceding the real
# trailing publisher suffix - see `_publisher_suffix_entities()`'s own docstring for the exact real
# case this matches ("... / Хабр - Хабр"). Deliberately a distinct delimiter ("/") from
# `_TRAILING_SUFFIX_RE`'s own `-–—|` set - breadcrumb-style path segments, never the suffix itself.
_BREADCRUMB_SEGMENT_RE = re.compile(r"/\s*([^/\-–—|]{1,40})\s*$")

_QUOTE_TRANSLATION = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "«": '"', "»": '"', "–": "-", "—": "-",
})
_WHITESPACE_RE = re.compile(r"\s+")
_TRAILING_PUNCTUATION_RE = re.compile(r"[.!?…\s]+$")

# Near-exact title Dice floor - deliberately much higher than the main 0.75 fuzzy-cluster
# threshold (this is a high-confidence precedence layer, not a replacement for it - spec §7's own
# "do not replace the main weighted clustering algorithm").
_NEAR_EXACT_TITLE_OVERLAP = 0.90

# A shared entity/number counts as "distinctive shared evidence" (spec §8/§9) only alongside
# EITHER real title overlap OR close temporal proximity - see _has_distinctive_shared_evidence()'s
# own docstring for the full reasoning and the real production numbers behind both constants.
# 5 minutes deliberately narrow - calibrated to catch near-simultaneous syndicated pickup of one
# wire/press-release announcement (multiple outlets republishing within a few minutes of each
# other) while NOT catching a real staged multi-part announcement sequence (e.g. this module's own
# "developing launch" fixture spaces genuinely distinct announcements 10 minutes apart - that must
# NOT collapse into one via temporal proximity alone).
_DISTINCTIVE_EVIDENCE_TITLE_FLOOR = 0.60
_DISTINCTIVE_EVIDENCE_TIME_WINDOW_MINUTES = 5.0
_DISTINCTIVE_EVIDENCE_SCORE = 0.95  # always clears every realistic threshold (0.65-0.85 range)

# Phase R1.4.2 (see _has_temporally_corroborated_distinctive_evidence()'s own docstring for the
# full derivation): the minimum real, measured ENTITY-EXCLUDED content overlap required BEFORE
# temporal proximity is ever allowed to corroborate a shared entity/number - see
# `_entity_excluded_content_overlap()`'s own docstring for why plain title dice was insufficient
# (short titles where the shared entity's own words dominate the raw ratio). Calibrated between
# the measured Taiwan/Bashkiria minimum necessary connections (0.133-0.235) and the measured
# "genuinely different sub-announcement" danger cases (0.0-0.167) - see the R1.4.2 report's own
# item E/F/G/H for the full real-number table this sits between.
_TEMPORAL_EVIDENCE_CONTENT_FLOOR = 0.20

# Phase R1.4.1 §6-9 fix: time_gap alone was found to be an UNSAFE sufficient corroborator - two
# genuinely different announcements from one live event (a product launch, its pricing, its
# availability date) can share an entity and occur minutes apart just as easily as two paraphrased
# reports of ONE real announcement can. See `_has_conflicting_distinctive_facts()`'s own docstring
# for the fix: temporal proximity may only corroborate a shared entity/number when neither title
# ALSO introduces its own additional distinctive fact (a different number, or a different specific
# entity) that the other lacks - that asymmetry is itself real content evidence of a genuinely
# different sub-announcement, and is checked BEFORE temporal proximity is ever consulted.

_NUMERIC_TOKEN_RE = re.compile(r"\$?\d[\d,.]*\d|\$?\d")
_ANNOUNCEMENT_WORD_RE = re.compile(r"[\w\-]+", re.UNICODE)


def _entity_excluded_content_overlap(
    sig_a: StorySignature, title_a: str, sig_b: StorySignature, title_b: str,
) -> float:
    """Pure. Phase R1.4.2 fix for a real measurement gap: plain `symmetric_token_overlap()` on the
    FULL title was found to be an unreliable content signal for the temporal-corroboration path
    specifically, because for a short title the shared entity's OWN words can dominate the ratio.
    Confirmed by direct execution: "Apple improves iPhone camera low-light performance" vs "Apple
    extends iPhone battery life with new update" - two titles about completely different features
    - still measure meaningfully above zero on plain dice purely because "apple"/"phone" (the
    shared entity) are 2 of each side's ~6-8 tokens. This function recomputes the same Dice overlap
    with the shared entity's own words removed from BOTH token sets first, isolating whether real
    content EVIDENCE exists beyond the shared identity fact itself - "camera"/"low-light"/
    "performance" vs "battery"/"life"/"update" share nothing once "apple"/"phone" are excluded,
    correctly reading as near-zero; Taiwan/Bashkiria's real paraphrase pairs retain meaningful
    overlap ("pay"/"citizen"/"dividend"/"314", or shared Cyrillic medicine/AI vocabulary) once their
    own shared entity words are excluded the same way."""
    shared_entities = set(sig_a.entities) & set(sig_b.entities)
    shared_words: set[str] = set()
    for entity in shared_entities:
        shared_words.update(entity.split())
    tokens_a = {
        t for t in _ANNOUNCEMENT_WORD_RE.findall(normalize_loose(title_a))
        if len(t) >= 3 and t not in shared_words
    }
    tokens_b = {
        t for t in _ANNOUNCEMENT_WORD_RE.findall(normalize_loose(title_b))
        if len(t) >= 3 and t not in shared_words
    }
    if not tokens_a or not tokens_b:
        return 0.0
    return 2 * len(tokens_a & tokens_b) / (len(tokens_a) + len(tokens_b))


def _title_with_normalized_punctuation(title: str) -> str:
    """Pure. The same whitespace/Unicode-quote-and-dash/trailing-punctuation normalization
    `_normalize_announcement_title()` applies, WITHOUT the final casefold - factored out so
    `_publisher_suffix_entities()` below can locate the same trailing-suffix segment while keeping
    the capitalization `services.story_memory._extract_entities()`'s own capitalized-run heuristic
    depends on (casefolding first would make every entity in the segment invisible to it)."""
    normalized = title.translate(_QUOTE_TRANSLATION)
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    return _TRAILING_PUNCTUATION_RE.sub("", normalized)


def _normalize_announcement_title(title: str) -> str:
    """Pure. Whitespace/punctuation/Unicode-quote-and-dash/case normalization only (spec §6) - no
    suffix stripping here (that is a separate, conditional step - see module comment above)."""
    return _title_with_normalized_punctuation(title).casefold()


def _trailing_suffix_stripped(normalized_title: str) -> str | None:
    match = _TRAILING_SUFFIX_RE.search(normalized_title)
    if (
        match
        and len(match.group(1).split()) <= _TRAILING_SUFFIX_MAX_WORDS
        and not _ENUMERATED_SERIES_SUFFIX_RE.match(match.group(1))
    ):
        return normalized_title[: match.start()].rstrip()
    return None


# Phase R1.5B.1 (real production forensic finding, R1.5B replay - see the R1.5B.1 report's own item
# A): `services.story_memory._extract_entities()`'s capitalized-run heuristic - correctly, by
# design, for genuine proper nouns - also captures a trailing publisher/source-suffix segment
# ("Ведомости", "Хабр", "Эксперт", "CNews.ru") as its own spurious "entity," since a publisher name
# is capitalized for the same reason a real entity is. Three real Taiwan "$314 AI dividend" reports
# share the exact same CONTENT entities (тайвань/ии) and the exact same distinctive number (314),
# yet measured only entity_jaccard=0.500 and `has_conflicting_distinctive_facts=True` in production
# - proven, by direct execution, to be caused entirely by each report's own DIFFERENT publisher
# entity being added as a fourth, non-overlapping set member (inflating the union) and by the
# entity-asymmetry check in `_has_conflicting_distinctive_facts()` reading "a publisher name absent
# from the other title" as if it were a genuine distinguishing content fact.
def _publisher_suffix_entities(title: str) -> set[str]:
    """Pure, deterministic, language-agnostic (spec R1.5B.1's own explicit "do NOT hardcode
    publisher names" instruction - no lexicon, no alias table, nothing per-language). Derives which
    of `title`'s own extracted entities are attributable ONLY to a trailing publisher/source-suffix
    segment, reusing the SAME suffix-parsing machinery `_trailing_suffix_stripped()`/
    `_is_near_exact_title_match()` already use (`_TRAILING_SUFFIX_RE`, `_TRAILING_SUFFIX_MAX_WORDS`)
    - never a new suffix heuristic.

    Method: run `services.story_memory._extract_entities()` (the real, unmodified entity extractor -
    reused, not reimplemented, so the result is guaranteed to match what's actually present in the
    real `StorySignature.entities`) separately on the suffix segment's own text and on the
    suffix-STRIPPED core text. An entity present in the suffix segment but ALSO present in the core
    is real content evidence and is never removed (e.g. a title that genuinely discusses "CNews" as
    its subject, not merely bylines it, would keep "cnews" as a content entity for anyone comparing
    against it - because it would also appear in the core) - UNLESS that core occurrence is itself
    nothing more than an isolated "/"-delimited breadcrumb repeating the same already-established
    publisher name immediately before the suffix (Phase I.2.2F - see the breadcrumb-handling block
    below for the exact real case this covers). An entity present ONLY in the suffix segment (or
    only via such a breadcrumb) is publisher noise. Returns an empty set (no filtering) whenever no
    title-suffix candidate exists at all, or the candidate is an enumerated-series marker like
    "Part 3: ..." (Phase I.2.2F) - the exact same guards `_trailing_suffix_stripped()` already
    applies, so a title with no dash/pipe-delimited trailing segment, or a genuine series
    installment, is never touched."""
    display_title = _title_with_normalized_punctuation(title)
    match = _TRAILING_SUFFIX_RE.search(display_title)
    if (
        not match
        or len(match.group(1).split()) > _TRAILING_SUFFIX_MAX_WORDS
        or _ENUMERATED_SERIES_SUFFIX_RE.match(match.group(1))
    ):
        return set()
    suffix_entities = set(_extract_entities(match.group(1)))
    core_text = display_title[: match.start()]
    core_entities = set(_extract_entities(core_text))

    # Phase I.2.2F (real production forensic finding, I.2.2E - Google News RU mirrors of Habr
    # articles: "... / Хабр - Хабр", "... / Комментарии / Хабр - Хабр"): an isolated "/ <segment>"
    # breadcrumb immediately preceding the real trailing publisher suffix, whose own entities are
    # already fully accounted for by that suffix's own publisher entity, is itself publisher noise
    # - a second, differently-positioned mention of the SAME publisher attribution, not genuine
    # core content that happens to "protect" the entity from removal. Only the single breadcrumb
    # segment immediately adjacent to the real suffix is ever consumed (search() with a `$` anchor,
    # never a chained/recursive strip) - deliberately narrow, matching the two real reproduced
    # cases. A breadcrumb segment containing anything beyond a repeat of the publisher name (its
    # entities are not a subset of the suffix's own) is left completely untouched - this can never
    # remove a genuine content entity that merely happens to sit near a "/".
    breadcrumb_match = _BREADCRUMB_SEGMENT_RE.search(core_text)
    if breadcrumb_match:
        breadcrumb_entities = set(_extract_entities(breadcrumb_match.group(1)))
        if breadcrumb_entities and breadcrumb_entities <= suffix_entities:
            core_entities -= breadcrumb_entities

    return suffix_entities - core_entities


def _sanitized_announcement_signature(signature: StorySignature, title: str) -> StorySignature:
    """Phase R1.5B.1: the "local sanitized view used only by announcement identity" the spec
    requires - builds a NEW `StorySignature` with publisher-suffix-only entities removed, for use
    ONLY within announcement-identity comparisons (`_announcement_similarity()`,
    `_has_distinctive_shared_evidence()`, `_has_conflicting_distinctive_facts()` via
    `_has_temporally_corroborated_distinctive_evidence()`). Never mutates `signature` itself
    (frozen dataclass, and this returns a distinct object), never touches `services/story_memory.py`
    or any DB-persisted entity list, and is never consulted by
    `evaluate_recap_story_integrity()` (which calls `extract_story_signature()` directly, its own
    separate call, entirely unaffected - Story Integrity remains frozen per spec R1.5B.1 §15).
    Keyword/topic_bucket fields and entity ORDER are preserved unchanged; only publisher-only
    entities are removed, and only when at least one is actually found (returns the original object
    unchanged otherwise, avoiding a pointless allocation on the common no-suffix case)."""
    publisher_entities = _publisher_suffix_entities(title)
    if not publisher_entities:
        return signature
    sanitized_entities = [e for e in signature.entities if e not in publisher_entities]
    if len(sanitized_entities) == len(signature.entities):
        return signature
    return StorySignature(entities=sanitized_entities, keywords=signature.keywords, topic_bucket=signature.topic_bucket)


def _is_near_exact_title_match(title_a: str, title_b: str) -> bool:
    """Spec §7: same headline / same headline + publisher suffix / tiny wording variation. Reuses
    `symmetric_token_overlap()` unchanged - no embeddings, no new NLP."""
    norm_a, norm_b = _normalize_announcement_title(title_a), _normalize_announcement_title(title_b)
    if norm_a == norm_b:
        return True
    candidates_a = [norm_a] + ([s] if (s := _trailing_suffix_stripped(norm_a)) else [])
    candidates_b = [norm_b] + ([s] if (s := _trailing_suffix_stripped(norm_b)) else [])
    if set(candidates_a) & set(candidates_b):
        return True
    core_a, core_b = candidates_a[-1], candidates_b[-1]
    return symmetric_token_overlap(core_a, core_b) >= _NEAR_EXACT_TITLE_OVERLAP


def _extract_numeric_tokens(title: str) -> set[str]:
    """Pure. General distinctive-number extraction (spec §9's own "use general distinctive-token
    logic," never a Taiwan-specific rule) - a 2+-digit number (with an optional leading currency
    sign, commas/decimals stripped) is distinctive; a single lone digit is too common/weak on its
    own (e.g. the "3" in "GPT-3") to count as distinctive evidence by itself."""
    tokens: set[str] = set()
    for match in _NUMERIC_TOKEN_RE.finditer(title):
        normalized = match.group(0).replace(",", "").replace("$", "")
        if len(normalized) >= 2:
            tokens.add(normalized)
    return tokens


def _has_distinctive_shared_evidence(
    sig_a: StorySignature, title_a: str, sig_b: StorySignature, title_b: str,
) -> bool:
    """Spec §8/§9: a second high-confidence path for paraphrased same-announcement reports that
    exact/near-exact title matching alone cannot catch. A shared entity or a shared distinctive
    number is necessary but not sufficient - it must be corroborated by real title overlap
    (`_DISTINCTIVE_EVIDENCE_TITLE_FLOOR`, 0.60 - deliberately set ABOVE the real "Apple unveils
    iPhone X" vs "Apple announces iPhone X pricing" pair's own measured overlap, 0.571, spec
    §13.F's own explicit requirement that a launch and its pricing follow-up stay separate even
    though they share a company/product entity), AND the two titles must not introduce conflicting
    distinctive facts (`_has_conflicting_distinctive_facts()`).

    Phase R1.4.1 §1-4 correction: this lexical-floor path is driven by essentially the same signal
    shape as ordinary weighted fuzzy similarity (a numeric title-overlap threshold) - the R1.4.1
    A/B/C reproduction proved that letting ANY lexically-driven signal compare against every
    cluster member reintroduces exactly the transitive-chaining bug this checkpoint fixes, even
    when nominally routed through this "distinctive evidence" function rather than `_announcement_
    similarity()` directly. This function is therefore checked ONLY against a cluster's stable
    reference (see `_best_cluster_match_score()`), never against arbitrary members - only
    `_has_temporally_corroborated_distinctive_evidence()` below (a qualitatively different,
    identity-like signal - see its own docstring) may compare against any member.

    Never category equality alone, never match_type alone (spec's own explicit prohibitions - this
    function never receives either)."""
    if _has_conflicting_distinctive_facts(sig_a, title_a, sig_b, title_b):
        return False
    shared_entities = set(sig_a.entities) & set(sig_b.entities)
    shared_numbers = _extract_numeric_tokens(title_a) & _extract_numeric_tokens(title_b)
    if not shared_entities and not shared_numbers:
        return False
    return symmetric_token_overlap(title_a, title_b) >= _DISTINCTIVE_EVIDENCE_TITLE_FLOOR


def _has_temporally_corroborated_distinctive_evidence(
    sig_a: StorySignature, title_a: str, time_a: datetime,
    sig_b: StorySignature, title_b: str, time_b: datetime,
) -> bool:
    """Spec §7's "time may support, not prove" correction, kept as its own function precisely
    because it is the ONE path allowed to compare against ANY cluster member (see
    `_best_cluster_match_score()`) - distinct in kind, not just in threshold, from the purely
    lexical-floor `_has_distinctive_shared_evidence()` above.

    Catches near-simultaneous syndicated/paraphrased duplicate coverage of ONE real announcement
    (e.g. Taiwan's "$314" dividend, or Bashkiria's regional AI-in-medicine announcement - both can
    legitimately have LOW or even ZERO title-token overlap between some pairs, since Russian
    grammatical case variation alone zeroed `symmetric_token_overlap()` between two real paraphrases
    of the identical fact, confirmed by direct execution). Requires ALL of:
    1. a shared entity or shared distinctive number (real content, never absent);
    2. NO conflicting distinctive fact on either side (`_has_conflicting_distinctive_facts()` -
       this is the actual R1.4.1 §6-9 fix: a genuinely different sub-announcement from the same
       live event - a price, an availability date, a different product - always introduces its own
       new distinctive fact the other title lacks, and is vetoed here regardless of how close in
       time the two events are);
    3. `time_gap <= _DISTINCTIVE_EVIDENCE_TIME_WINDOW_MINUTES` (5 minutes - near-simultaneous
       syndication, not a staged announcement sequence).

    Time proximity therefore never stands in for content evidence (spec §7's own "cannot replace
    lexical/content evidence") - it only corroborates a real shared fact once the conflict check has
    already ruled out the specific failure mode (shared entity + close time, but genuinely different
    sub-announcements) spec §6 describes.

    Phase R1.4.2 correction (real forensic finding - see the R1.4.2 report's own item A/B): the
    conflict check alone was NOT sufficient. "Apple announces iPhone camera improvements" vs
    "Apple announces iPhone battery improvements" share entities {"apple","phone"}, have NO
    conflicting fact (neither introduces a number or an entity absent from the other), and 2
    minutes apart - so this function returned True for them, meaning TIME ALONE (once the conflict
    veto passed) was sufficient to corroborate two genuinely different sub-announcements. This
    violates the required contract ("temporal proximity may support identity, never prove it by
    itself"). Fixed by requiring `_entity_excluded_content_overlap() >= _TEMPORAL_EVIDENCE_CONTENT_
    FLOOR` (0.20) as a fourth, mandatory condition - real, measured, non-zero content evidence
    BEYOND the shared entity itself must exist BEFORE temporal proximity is allowed to corroborate
    anything; time is additive confirmation on top of that floor, never a substitute for it. Plain
    `symmetric_token_overlap()` on the full title was tried first and rejected - see `_entity_
    excluded_content_overlap()`'s own docstring for why (short titles where the shared entity's own
    words dominate the ratio, letting genuinely different topics like camera-vs-battery measure
    misleadingly high). 0.20 sits between the measured "genuinely different sub-announcement"
    danger-case values (0.0-0.167) and the measured Taiwan/Bashkiria minimum necessary connections
    (0.133-0.235, several distinct real pairs) - the R1.4.2 report's own item E-H disclose the full
    real-number table this was calibrated against, including the specific real pairs that remain
    unresolved by any single floor value (per spec §5's own "prefer conservative split over unsafe
    general merge - quality > recall" instruction)."""
    if _has_conflicting_distinctive_facts(sig_a, title_a, sig_b, title_b):
        return False
    shared_entities = set(sig_a.entities) & set(sig_b.entities)
    shared_numbers = _extract_numeric_tokens(title_a) & _extract_numeric_tokens(title_b)
    if not shared_entities and not shared_numbers:
        return False
    if _entity_excluded_content_overlap(sig_a, title_a, sig_b, title_b) < _TEMPORAL_EVIDENCE_CONTENT_FLOOR:
        return False
    time_gap_minutes = abs((time_a - time_b).total_seconds()) / 60
    return time_gap_minutes <= _DISTINCTIVE_EVIDENCE_TIME_WINDOW_MINUTES


def _has_conflicting_distinctive_facts(
    sig_a: StorySignature, title_a: str, sig_b: StorySignature, title_b: str,
) -> bool:
    """Phase R1.4.1 §6-9: the real fix for the "same entity + close time" false-corroboration risk
    (spec's own Apple product-launch/pricing/availability and Google model-launch/API-pricing/
    feature counterexamples - all plausibly sharing one entity and occurring minutes apart, while
    being genuinely different announcements). A shared entity or number is real evidence ONLY when
    neither title ALSO introduces its OWN additional distinctive fact absent from the other -
    that one-sided (or two-sided) introduction of a NEW specific number or entity is itself
    positive content evidence of a distinct sub-announcement, general and language-agnostic (no
    "price"/"availability" word list - spec's own repeated "no hardcoded word list" discipline).

    Two checks:
    1. Numeric asymmetry: either side has a number the other lacks, OR both have numbers but they
       differ (spec §8's own "same date/time window, different numbers/announcements" example -
       999 vs 256 vs 18 must never merge just because a company entity is also shared).
    2. Entity asymmetry: after removing the entities actually SHARED between the two titles, each
       side still has at least one entity of its own (e.g. "Product X" only in one title, "Watch Y"
       only in the other) - evidence the two titles are about different specific subjects, not a
       paraphrase of the same one."""
    numbers_a, numbers_b = _extract_numeric_tokens(title_a), _extract_numeric_tokens(title_b)
    if (numbers_a or numbers_b) and numbers_a != numbers_b:
        return True
    entities_a, entities_b = set(sig_a.entities), set(sig_b.entities)
    shared = entities_a & entities_b
    if (entities_a - shared) and (entities_b - shared):
        return True
    return False


def _normalize_domain(url: str | None) -> str | None:
    if not url:
        return None
    netloc = urlsplit(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc or None


def _best_cluster_match_score(
    signature: StorySignature, title: str, time: datetime,
    members: list[tuple[StorySignature, str, datetime]],
) -> float:
    """Phase R1.4.1 §1-4 correction of the R1.4 §10 fix.

    R1.4's original design ("compare a candidate against every current member, take the best
    evidence") was PROVEN transitive/single-linkage for ordinary fuzzy similarity (see the R1.4.1
    report's own minimal A/B/C reproduction: sim(A,B)=0.80, sim(B,C)=0.775, sim(A,C)=0.72 - A and C
    do NOT satisfy the threshold directly, yet all three merged into one cluster via B). That is a
    real correctness bug, not the intended behavior, and this function no longer has it.

    Two-tier comparison scope, not one:
    - HIGH-CONFIDENCE IDENTITY (near-exact title match, `_is_near_exact_title_match()` - includes
      exact match and same-headline-plus-publisher-suffix) MAY be checked against ANY current
      member. This mirrors spec §5's own explicit "if B/C are exact or near-exact identity: document
      separately" allowance - near-textual identity is close to a true equivalence relation, so
      limited chaining through it is safe.
    - Everything else - ORDINARY WEIGHTED FUZZY SIMILARITY (`_announcement_similarity()`), the
      LEXICAL-FLOOR distinctive-evidence path (`_has_distinctive_shared_evidence()`), AND (Phase
      R1.4.2 correction) `_has_temporally_corroborated_distinctive_evidence()` - is checked ONLY
      against the cluster's STABLE REFERENCE - `members[0]`, the event that originally started this
      cluster (spec §3's own first suggested stable-reference option). Phase R1.4.2's own real A/B/C
      reproduction (three "OpenAI safety research..." titles, same entity throughout, no conflicting
      facts) proved temporal distinctive evidence ALSO chains via single-linkage exactly like
      ordinary fuzzy does, once each pairwise link individually clears the temporal-evidence bar
      (sim(A,B) and sim(B,C) qualify, sim(A,C) does not, yet all three merged when compared against
      "any member") - so it no longer gets any-member treatment either, per spec R1.4.2 §6's own
      explicit "all non-identity evidence, including temporal distinctive evidence, must satisfy
      stable cluster reference" instruction. A candidate must always be evidenced against the SAME
      fixed reference point for all three non-identity signals, never merely against whichever
      member happened to join most recently."""
    stable_reference_sig, stable_reference_title, stable_reference_time = members[0]
    best = _announcement_similarity(signature, title, stable_reference_sig, stable_reference_title)
    if _has_distinctive_shared_evidence(signature, title, stable_reference_sig, stable_reference_title):
        best = max(best, _DISTINCTIVE_EVIDENCE_SCORE)
    if _has_temporally_corroborated_distinctive_evidence(
        signature, title, time, stable_reference_sig, stable_reference_title, stable_reference_time,
    ):
        best = max(best, _DISTINCTIVE_EVIDENCE_SCORE)
    for member_sig, member_title, _member_time in members:
        if _is_near_exact_title_match(title, member_title):
            return 1.0
    return best


def cluster_announcements(events: list[NewsEvent], *, threshold: float | None = None) -> list[AnnouncementCluster]:
    """Pure, deterministic. Greedy single-pass clustering in chronological order (`events` is
    assumed already sorted, as `load_story_events()` returns it): each event joins the existing
    cluster with the best evidence of shared identity (see `_best_cluster_match_score()` - identity/
    distinctive-evidence signals check every current member, ordinary fuzzy similarity checks only
    the cluster's original stable reference - not a single uniform comparison scope) if that
    evidence clears `threshold`, else starts a new cluster. No embeddings, no LLM, no second global
    dedup engine - reuses `services.
    story_memory.extract_story_signature()` (the exact same entity/keyword/topic extraction every
    Story match already uses) and `services.text_normalization.symmetric_token_overlap()`
    unchanged; only the combining weights, the identity-precedence layer, and the threshold are new,
    and only apply within one story's own event set (never a cross-story comparison).

    `threshold`: defaults to `settings.recap_announcement_cluster_threshold` (every real caller
    omits this - no behavior change). Phase R1.1 §7 added the explicit override parameter solely
    for offline threshold-sensitivity diagnostics - it never mutates the global setting, so
    production/default behavior is unaffected by exercising this parameter."""
    effective_threshold = settings.recap_announcement_cluster_threshold if threshold is None else threshold
    clusters: list[dict] = []  # each: {"members": [(sig, title, time), ...], "title": anchor headline, event/url/time lists}

    for event in events:
        # Phase R1.5B.1: sanitized for ANNOUNCEMENT IDENTITY purposes only - see
        # `_sanitized_announcement_signature()`'s own docstring. The stored cluster headline
        # (`cluster["title"]` below) always uses `event.title` verbatim, never this sanitized view.
        signature = _sanitized_announcement_signature(
            extract_story_signature(event.title, event.category), event.title,
        )
        anchor_time = event.published_at or event.collected_at
        best_idx: int | None = None
        best_score = 0.0
        for idx, cluster in enumerate(clusters):
            score = _best_cluster_match_score(signature, event.title, anchor_time, cluster["members"])
            if score > best_score:
                best_score = score
                best_idx = idx

        if best_idx is not None and best_score >= effective_threshold:
            cluster = clusters[best_idx]
            cluster["members"].append((signature, event.title, anchor_time))
            cluster["event_ids"].append(event.id)
            if event.url:
                cluster["source_urls"].append(event.url)
                domain = _normalize_domain(event.url)
                if domain and domain not in cluster["source_domains"]:
                    cluster["source_domains"].append(domain)
            cluster["last_seen_at"] = max(cluster["last_seen_at"], anchor_time)
            cluster["first_seen_at"] = min(cluster["first_seen_at"], anchor_time)
        else:
            clusters.append({
                "members": [(signature, event.title, anchor_time)], "title": event.title, "event_ids": [event.id],
                "source_urls": [event.url] if event.url else [],
                "source_domains": [d] if (d := _normalize_domain(event.url)) else [],
                "first_seen_at": anchor_time, "last_seen_at": anchor_time,
            })

    return [
        AnnouncementCluster(
            cluster_id=i, event_ids=c["event_ids"], headline=c["title"],
            source_urls=c["source_urls"], source_domains=c["source_domains"],
            first_seen_at=c["first_seen_at"], last_seen_at=c["last_seen_at"],
        )
        for i, c in enumerate(clusters)
    ]


# ---------------------------------------------------------------------------
# 3. Source counting (§5)
# ---------------------------------------------------------------------------


def count_unique_sources(events: list[NewsEvent]) -> int:
    """Deduplicates by normalized URL domain (host, `www.` stripped) when a URL exists, falling
    back to the event's own `source_id` (the existing NewsSource identity - spec's own "same
    normalized source where existing source identity is available") when it does not - every
    event contributes exactly one identity, never silently dropped, never double-counted."""
    identities: set[str] = set()
    for event in events:
        domain = _normalize_domain(event.url)
        identities.add(domain if domain else f"source:{event.source_id}")
    return len(identities)


def count_unique_sources_with_canonical_urls(
    events: list[NewsEvent], canonical_urls_by_event_id: dict[UUID, str | None],
) -> int:
    """Phase R1.3 §11 finding: `NewsEvent.url` is frequently a Google News aggregator wrapper
    (`news.google.com`) that hides the real originating outlet - R1.2's production replay found
    many Story rows where every member's `_normalize_domain(event.url)` collapsed to the SAME
    `news.google.com` host despite the underlying articles coming from different real outlets,
    silently undercounting `unique_source_count`.

    Real, existing, already-computed data can fix this WITHOUT any new network call:
    `services/article_acquisition.py::resolve_canonical_url()` already resolves and persists the
    real destination URL (via `<link rel="canonical">`, extracted from HTML already fetched for an
    unrelated purpose - article acquisition) into `NewsEventArticleAcquisition.canonical_url` for
    every event whose acquisition pipeline has already run. `canonical_urls_by_event_id` is that
    already-persisted data, read-only, keyed by `news_event_id` (see `load_canonical_urls_for_
    events()` below for the loader) - never a new fetch.

    Deliberately a SEPARATE function from `count_unique_sources()`, not a parameter added to it:
    NOT every confirmed member event has a corresponding `NewsEventArticleAcquisition` row (only
    events whose content actually went through acquisition do), so this function falls back to the
    plain `NewsEvent.url` domain (identical to `count_unique_sources()`'s own behavior) whenever no
    canonical URL is available for a given event - never guessing, never inventing independence
    where the data doesn't exist. NOT wired into `build_recap_event_snapshot()`'s default path in
    this checkpoint (a deliberately minimal, disclosed scope decision - see the R1.3 report's own
    §H) - available for a future checkpoint to adopt as the default."""
    identities: set[str] = set()
    for event in events:
        canonical = canonical_urls_by_event_id.get(event.id)
        domain = _normalize_domain(canonical) or _normalize_domain(event.url)
        identities.add(domain if domain else f"source:{event.source_id}")
    return len(identities)


async def load_canonical_urls_for_events(
    session: AsyncSession, event_ids: list[UUID],
) -> dict[UUID, str | None]:
    """Read-only lookup of already-persisted `NewsEventArticleAcquisition.canonical_url` rows for
    the given event ids - no fetch, no write. Events with no acquisition row simply do not appear
    in the returned dict (`count_unique_sources_with_canonical_urls()`'s own `.get()` handles that
    as "no canonical URL available")."""
    from database.models.news_event_article_acquisition import NewsEventArticleAcquisition

    if not event_ids:
        return {}
    stmt = select(NewsEventArticleAcquisition.news_event_id, NewsEventArticleAcquisition.canonical_url).where(
        NewsEventArticleAcquisition.news_event_id.in_(event_ids)
    )
    result = await session.execute(stmt)
    return {event_id: canonical_url for event_id, canonical_url in result}


# has_primary_source is deliberately always None (UNKNOWN) in R1 - see module docstring/spec §5:
# no existing schema field distinguishes an "official/primary" source from any other (NewsSource.
# reliability_score is a general quality signal, not an official-ness flag; SourceType is a fetch
# mechanism, not a tier) - guessing one would be exactly the "fabricate source quality" the spec
# explicitly forbids.
def has_primary_source_unknown() -> bool | None:
    return None


# ---------------------------------------------------------------------------
# 4. Lifecycle state + readiness (§6/§7/§8)
# ---------------------------------------------------------------------------


def _cooling_elapsed(*, last_event_at: datetime, now: datetime) -> bool:
    elapsed_minutes = (now - last_event_at).total_seconds() / 60
    return elapsed_minutes >= settings.recap_cooling_window_minutes


def evaluate_recap_readiness(
    *,
    event_count: int,
    announcement_count: int,
    unique_source_count: int,
    last_event_at: datetime,
    now: datetime,
    research_complete: bool,
    unresolved_conflict_count: int,
    story_integrity_eligible: bool,
    story_integrity_reasons: list[str] | None = None,
) -> ReadinessResult:
    """Pure. Explicit deterministic conditions + structured reasons - never a synthetic 0-100
    score (spec §8's own explicit instruction). Every threshold is config-driven
    (`settings.recap_min_*`/`recap_cooling_window_minutes`).

    Phase R1.3: `event_count` here MUST be the confirmed-member count (`len(load_story_events(...))`
    ), never `Story.event_count` - see RecapEventSnapshot's own docstring for the real production
    mismatch this corrects. `story_integrity_eligible` is an unconditional gate (spec §12's own
    "Readiness requires story_integrity_eligible == True before any other conditions can produce
    READY" / spec §10's "do not let bad Story integrity be compensated by high announcement_count") -
    when False, its reasons are added FIRST and unconditionally, forcing `ready = False` regardless
    of every other individual condition, since `ready = not reasons` and this list is never empty
    in that case."""
    reasons: list[str] = []
    if not story_integrity_eligible:
        reasons.extend(story_integrity_reasons or ["story integrity gate failed - not a recap candidate"])

    cooling_elapsed = _cooling_elapsed(last_event_at=last_event_at, now=now)
    time_since_last_update_minutes = round((now - last_event_at).total_seconds() / 60, 1)

    metrics: dict[str, object] = {
        "event_count": event_count,
        "announcement_count": announcement_count,
        "unique_source_count": unique_source_count,
        "time_since_last_update_minutes": time_since_last_update_minutes,
        "cooling_elapsed": cooling_elapsed,
        "research_complete": research_complete,
        "unresolved_conflicts": unresolved_conflict_count,
        "story_integrity_eligible": story_integrity_eligible,
    }

    if event_count < settings.recap_min_event_count:
        reasons.append(f"event_count {event_count} < required {settings.recap_min_event_count}")
    if announcement_count < settings.recap_min_announcement_count:
        reasons.append(f"announcement_count {announcement_count} < required {settings.recap_min_announcement_count}")
    if unique_source_count < settings.recap_min_unique_sources:
        reasons.append(f"unique_source_count {unique_source_count} < required {settings.recap_min_unique_sources}")
    if not cooling_elapsed:
        reasons.append(
            f"cooling window not elapsed ({time_since_last_update_minutes:.1f}m < "
            f"{settings.recap_cooling_window_minutes}m)"
        )
    if unresolved_conflict_count > 0:
        reasons.append(f"{unresolved_conflict_count} unresolved factual conflict(s)")
    if not research_complete:
        reasons.append("recap research not complete")

    ready = not reasons

    # State derivation - a pure function of the same signals, never a second source of truth.
    if event_count < settings.recap_min_event_count and announcement_count <= 1:
        state = DISCOVERED
    elif ready:
        state = READY
    elif cooling_elapsed:
        # Enough material has cooled but something else (sources/research/conflicts) still gates.
        state = COOLING
    else:
        state = ACTIVE

    if ready:
        reasons = [
            f"{announcement_count} announcement clusters, {unique_source_count} unique sources, "
            "cooling elapsed, research complete, zero unresolved conflicts",
        ]

    return ReadinessResult(ready=ready, state=state, reasons=reasons, metrics=metrics)


# ---------------------------------------------------------------------------
# 5. Orchestration (async, read-only)
# ---------------------------------------------------------------------------


async def build_recap_event_snapshot(
    session: AsyncSession, story: Story, *, now: datetime | None = None,
    research_complete: bool = False, unresolved_conflict_count: int = 0,
) -> RecapEventSnapshot:
    """The one async orchestration entry point - loads events, runs the Story Integrity Gate,
    clusters announcements, counts sources, evaluates readiness/state, and returns one immutable
    snapshot. Read-only: issues no writes, calls no LLM, makes no network request.
    `research_complete`/`unresolved_conflict_count` are caller-supplied signals (R1 does not run
    Recap Research at all - spec §7's own explicit "research_complete must be an input/signal...
    may default False" instruction); tests may supply `research_complete=True` to exercise the
    READY branch.

    Phase R1.3: announcement clustering and readiness are always COMPUTED regardless of the
    integrity gate's verdict (keeps every pure function independently composable/testable, and
    preserves real diagnostic numbers rather than hiding them) - the gate's actual ENFORCEMENT
    point is `evaluate_recap_readiness()`'s own unconditional `story_integrity_eligible` check,
    which forces `ready=False` whenever integrity fails, regardless of every other condition (spec
    §10's own "do not let bad Story integrity be compensated by high announcement_count"). The
    offline diagnostic script (scripts/_recap_r1_3_offline_diagnostic.py) is the layer that chooses
    to SUPPRESS printing announcement/readiness detail for a FAILED story, as a presentation
    decision - not this function.

    Phase R1.5A.2 correction (real forensic finding, R1.5A.1 production replay - see the R1.5A.2
    report's own item K/L): the original contract silently fell back to `events[0]` (the
    chronologically-earliest CONFIRMED member) as a substitute anchor whenever `story.first_event_id`
    was not itself present among the confirmed-membership set - which real production data showed
    does happen (a Story's declared `first_event_id` can point to an event whose own link row never
    reached confirmed-membership status). That fallback is unsafe: it lets a Story become eligible
    purely because SOME other confirmed event happens to look coherent, never verifying the Story's
    actual declared origin at all. Fixed to fail closed instead - when the declared anchor is missing
    from the confirmed-member set, integrity is unconditionally `eligible=False` with an explicit
    reason, and no substitute anchor is ever chosen."""
    now = now or datetime.now(timezone.utc)
    events = await load_story_events(session, story.id)
    anchor_event = next((e for e in events if e.id == story.first_event_id), None)

    if anchor_event is not None:
        integrity = evaluate_recap_story_integrity(anchor_event, events)
    elif events:
        integrity = StoryIntegrityResult(
            eligible=False,
            reasons=[
                f"declared first_event_id {story.first_event_id} is not among this story's "
                "confirmed member events - true anchor missing, failing closed rather than "
                "substituting a fallback event"
            ],
            metrics={"member_count": len(events)},
        )
    else:
        integrity = StoryIntegrityResult(eligible=False, reasons=["no confirmed member events loaded"], metrics={})

    announcements = cluster_announcements(events)
    unique_sources = count_unique_sources(events)
    last_event_at = max((e.published_at or e.collected_at for e in events), default=story.updated_at)

    readiness = evaluate_recap_readiness(
        event_count=len(events), announcement_count=len(announcements), unique_source_count=unique_sources,
        last_event_at=last_event_at, now=now, research_complete=research_complete,
        unresolved_conflict_count=unresolved_conflict_count,
        story_integrity_eligible=integrity.eligible, story_integrity_reasons=integrity.reasons,
    )

    return RecapEventSnapshot(
        story_id=story.id, first_event_id=story.first_event_id, event_count=len(events),
        declared_event_count=story.event_count,
        created_at=story.created_at, updated_at=story.updated_at, state=readiness.state,
        announcement_count=len(announcements), unique_source_count=unique_sources,
        has_primary_source=has_primary_source_unknown(), cooling_elapsed=bool(readiness.metrics["cooling_elapsed"]),
        research_complete=research_complete, unresolved_conflict_count=unresolved_conflict_count,
        readiness_reason="; ".join(readiness.reasons),
        story_integrity_eligible=integrity.eligible, story_integrity_reasons=integrity.reasons,
        announcements=announcements,
    )
