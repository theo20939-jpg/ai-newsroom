"""NINJA PULSE RECAP - Phase R2: EVENT_RECAP shadow foundation.

Given an existing production Story that already passes the FROZEN R1 Story Integrity Gate, builds
a structured, deterministic `EventRecapCandidate` from its confirmed NewsEvents - optionally
followed by a SHADOW-ONLY LLM synthesis pass through the existing LLM Gateway. This module never
publishes anything: `EventRecapCandidate.publishable` is unconditionally `False` throughout R2,
regardless of readiness, integrity, or LLM synthesis outcome - publishability gating is explicitly
out of scope for this phase (see the R2 checkpoint's own "This phase must NOT publish anything").

R1 is FROZEN and reused, never reimplemented, here:
    services.recap_event.load_story_events()               - confirmed-member loading
    services.recap_event.evaluate_recap_story_integrity()   - the Story Integrity Gate
    services.recap_event.cluster_announcements()            - announcement clustering
    services.recap_event.count_unique_sources()              - source counting (readiness only)
    services.recap_event.evaluate_recap_readiness()          - deterministic readiness
    services.recap_event.load_canonical_urls_for_events()     - already-persisted canonical URLs
    services.recap_event._sanitized_announcement_signature()  - publisher-suffix sanitization
    services.recap_event._publisher_suffix_entities()          - publisher-only entity detection
No threshold, weight, or algorithm from any of the above is touched, tuned, or duplicated here.

Phase R2.2 evidence-hygiene correction (real production finding, Sverdlovsk Story replay): R2's
own announcement/fact evidence was built from RAW `extract_story_signature()` output, never
sanitized - reintroducing exactly the publisher-suffix contamination R1.5B.1 already solved for
announcement IDENTITY (`cluster_announcements()`), just one layer downstream, in EVIDENCE. Fixed
by reusing R1's own `_sanitized_announcement_signature()`/`_publisher_suffix_entities()` (private,
imported directly rather than duplicated - the codebase's own established precedent, e.g. `services/
candidate_fact_safety.py` importing from `services/fact_safety.py`; the corrected diagnostic
scripts this session, `scripts/_recap_r1_5b_announcement_production_forensic.py` and
`scripts/_recap_r1_5b1_publisher_sanitization_diagnostic.py`, already reuse these exact same two
private functions the identical way) - never reimplementing the sanitization algorithm itself,
per the frozen-R1 discipline. A defense-in-depth invariant (`_assert_no_publisher_contamination()`)
independently re-verifies this on every build and fails loudly (`EventRecapEvidenceContaminationError`)
rather than silently tolerating a regression.

Also from the same replay: R1's `count_unique_sources()` is a domain-based READINESS signal
(frozen, unchanged, still fed to `evaluate_recap_readiness()` unmodified) - it is NOT a count of
distinct evidence references, and conflating the two produced a real, misleading `source_count=1`
for a Story with 3 distinct evidence URLs (all sharing one collector `NewsSource` row and, for two
of them, one Google News wrapper domain). `EventRecapCandidate`/`AnnouncementSummary` now
separate these explicitly: `readiness_source_count` (verbatim `count_unique_sources()` - the exact
value readiness computation saw, preserved for transparency) vs. `evidence_reference_count`
(distinct evidence identities - a canonical URL's own domain when an Article Acquisition pass has
already resolved one, no network call, else the raw event URL itself, deliberately NEVER a raw
URL's own domain, since a Google News wrapper's shared domain would silently re-collapse the exact
ambiguity this correction exists to fix).

Deterministic build flow (`build_event_recap_candidate()`) requires zero LLM/Gateway calls and
zero network access - it is exactly as safe to call as any R1 diagnostic. `force_shadow=True`
allows building a candidate even when `evaluate_recap_readiness()` returns `ready=False` (R2 has
no "Recap Research" step yet - see `evaluate_recap_readiness()`'s own docstring on
`research_complete` being a caller-supplied signal R1 never sets True on its own - so a REAL
candidate will essentially always need `force_shadow=True` until a future phase implements Recap
Research); the resulting candidate always records `readiness_overridden=True` in that case. Without
`force_shadow`, a not-READY Story is rejected outright, never silently downgraded.

Media: reuses the EXISTING, already-persisted image/video candidate read contracts
(`services.image_persistence.get_editorial_image_candidates()`,
`services.video_discovery_persistence.get_video_candidates_for_event()`) - no new media
architecture, no AI-generated recap image, no Rich Message construction (that remains entirely
out of scope for R2).

Phase R2.6b evidence-semantic-quality correction (real production findings, broader-shadow scan):
(1) Numeric publisher contamination - a real Yakutia Story's announcement title ended " - RuNews24"
(a publisher-brand suffix with a digit glued directly onto the brand name, no delimiter); unlike
entities (already publisher-suffix-sanitized since Phase R2.2), `_extract_meaningful_numbers()` has
ALWAYS scanned the RAW, unsanitized title - confirmed by direct execution that "24" is extracted
from inside "RuNews24" verbatim, the identical structural class of bug as R2.2's entity
contamination, just never fixed in the numeric path. (2) Generic entity-phrase noise - a real
Nvidia Story's English, Title-Case headline ("The CEO of This Nvidia-Backed Artificial Intelligence
(AI) Chip Company Just Bought $10 Million of His Own Stock.") produced entities "chip company just
bought"/"his own stock"/"million" - confirmed by direct execution to come from `services.
story_memory._extract_entities()`'s own capitalized-run heuristic (`_ENTITY_RUN_RE`), which (by
design, for genuine proper nouns) also captures long noise runs in Title-Case English headlines
where ordinary common words are capitalized for styling, not because they denote anything - NOT
publisher-suffix contamination (confirmed: `_publisher_suffix_entities()` finds nothing here, since
there is no trailing " - X" suffix segment in this title at all) - a structurally different,
sibling limitation to the already-documented "Тестирование ИИ" compound-capture finding from
Phase R2.4, this time in `services/story_memory.py` rather than `services/fact_safety.py`. Per this
checkpoint's own explicit instruction, `services/story_memory.py` was NOT touched (same
frozen-unless-proven-and-globally-safe discipline as Phase R2.4's fact_safety.py decision).

Both are fixed as SYNTHESIS-PROJECTION-ONLY corrections (`_synthesis_verified_facts()`, extended -
never mutating `EventRecapCandidate.verified_facts`/`AnnouncementSummary.meaningful_numbers`/
`.content_entities` themselves, which remain the complete, unfiltered forensic record exactly as
before): `_publisher_suffix_numbers()` (new - mirrors `_publisher_suffix_entities()`'s own
suffix-vs-core methodology exactly, reusing R1's own `_TRAILING_SUFFIX_RE`/
`_TRAILING_SUFFIX_MAX_WORDS`/`_title_with_normalized_punctuation` directly rather than duplicating
the suffix-parsing algorithm) marks a number as publisher-only precisely when it never appears
outside a trailing suffix segment anywhere among the announcement's own member events - a number
that ALSO occurs in the substantive/core text (even of a different member event) is never removed.
`_is_generic_entity_phrase()` (new - a small, explicit, generic pronoun/modifier/magnitude-word
check, never a per-headline or per-Story blacklist, mirrors this codebase's own established
discipline for exactly this kind of narrow list, e.g. `_INTERNAL_VOCABULARY_TERMS` above) excludes
an entity value containing a possessive pronoun or generic modifier word, or a bare magnitude word
standing alone - real proper nouns/product/company/person/place names do not contain these.

LLM synthesis (`synthesize_event_recap()`) is entirely optional and additive: it makes exactly one
`LLMGateway.generate()` call, through the SAME `capabilities.gateway_call.call_generate()`
observability wrapper every real Capability already uses - never a raw/direct provider call - using
a NEW, immutable prompt version (`prompts/event_recap/v1.yaml`). Its output is verified against the
evidence bundle using the EXISTING `services.fact_safety.evaluate_fact_safety()` utility (no
embeddings, no semantic vector verification, no new fact-safety mechanism) before being attached to
the candidate - an unsafe/uncertain verification result is recorded as a disclosed quality flag,
never silently dropped and never allowed to change `publishable`.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.gateway_call import call_generate
from core.config import settings
from database.models.news_event import NewsEvent
from database.models.story import Story
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository, RenderedPrompt
from schemas.capability import CapabilityCall, RuntimeContext
from schemas.image_candidate import ImageDiscoveryMethod
from schemas.media_ranking import MediaRankingInput
from services.fact_safety import FactEvidence, evaluate_fact_safety
from services.image_persistence import EditorialImageCandidate, get_editorial_image_candidates
from services.image_quality import aspect_ratio_band, hamming_distance
from services.image_relevance import PROVENANCE_TABLE
from services.media_ranking import _NEAR_DUPLICATE_MAX_HAMMING_DISTANCE, rank_media_candidates
from services.recap_event import (
    AnnouncementCluster,
    _publisher_suffix_entities,
    _sanitized_announcement_signature,
    _TRAILING_SUFFIX_MAX_WORDS,
    _TRAILING_SUFFIX_RE,
    _title_with_normalized_punctuation,
    cluster_announcements,
    count_unique_sources,
    evaluate_recap_readiness,
    evaluate_recap_story_integrity,
    load_canonical_urls_for_events,
    load_story_events,
)
from services.recap_eventness_shadow import (
    EventnessShadowEvaluation,
    EventnessShadowFeatures,
    evaluate_eventness_shadow,
)
from services.recap_origin_projection import build_effective_recap_members, resolve_recap_origin_projection
from services.story_memory import extract_story_signature
from services.video_discovery_persistence import get_video_candidates_for_event

EVENT_RECAP_PROMPT_NAME = "event_recap"
# Phase R2.5 (real production finding - a real Sverdlovsk synthesis call echoed the literal word
# "bundle"/"evidence bundle" into its own Russian editorial output, e.g. "в evidence bundle не
# приведены"). Root-caused by direct inspection: prompts/event_recap/v1.yaml's own `system` text
# uses "bundle" repeatedly (immutable, never edited - see prompts/event_recap/v2.yaml's own header
# comment for the full account) AND _build_synthesis_request() below independently labeled its own
# context text "EVIDENCE BUNDLE:" - both fixed; v2 is the new default.
EVENT_RECAP_PROMPT_VERSION = "3"

# Plain string constants for a small closed vocabulary (mirrors services/recap_event.py's own
# EVENT_RECAP/WEEKLY_RECAP convention, and services/story_memory.py's NEW_STORY/STORY_UPDATE/... -
# never a Python Enum here, matching this codebase's established pattern for service-internal
# closed vocabularies).
FACT_MULTI_SOURCE_CONFIRMED = "MULTI_SOURCE_CONFIRMED"
FACT_SINGLE_SOURCE_ONLY = "SINGLE_SOURCE_ONLY"

_MAX_KEY_TAKEAWAYS = 8
_MAX_MEDIA_PER_EVENT = 3
_MAX_BUNDLE_TEXT_CHARS = 12_000  # mirrors services/telegraph_research_context.py's own bound

# Mirrors services/recap_event.py's own `_NUMERIC_TOKEN_RE`/`_extract_numeric_tokens()` -
# duplicated, not imported, per this codebase's own established per-module-private-helper
# convention (see services/telegraph_research_context.py's own module docstring for the identical
# precedent: "duplicated rather than imported... this codebase's own established... convention").
# recap_event.py's own numeric-token constant/function are private (single-underscore) and belong
# to that module only - Story Integrity/announcement clustering stay fully self-contained.
_NUMERIC_TOKEN_RE = re.compile(r"\$?\d[\d,.]*\d|\$?\d")


def _normalize_numeric_token(raw: str) -> str:
    """Phase R2.10 Night 2 (real production-shadow finding, Marvell/Google Story): locale-aware
    separator normalization for one `_NUMERIC_TOKEN_RE` match. Pure, deterministic, RECAP-LOCAL
    only (`services/event_recap.py`'s own private helper - `services/recap_event.py`'s frozen
    `_extract_numeric_tokens()` duplicates the OLD naive `.replace(",", "")` behavior unchanged;
    see that function's own docstring cross-reference and this fix's own commit message for why
    that frozen copy is deliberately left untouched).

    The bug this replaces: blindly stripping every comma treated a Russian-locale decimal comma
    identically to a thousands-grouping comma - `"$12,2 млрд"` (twelve point two billion) silently
    became the fact `"122"`, a fabricated-looking value that never appeared in any evidence text,
    while the equivalent English source `"$12.2 billion"` correctly stayed `"12.2"` - the same
    real-world number was represented as two different, non-matching fact strings, which
    `_build_verified_facts()`'s own event-set grouping (keyed on exact string equality) then
    counted as two unrelated `FACT_SINGLE_SOURCE_ONLY` facts instead of one genuinely
    `FACT_MULTI_SOURCE_CONFIRMED` fact - both a hallucination-adjacent risk (a number in the
    evidence bundle that traces to no real source text) and a corroboration-detection miss.

    Deliberately NOT "replace every comma with a period" - that would silently corrupt genuine
    thousands-grouped numbers like `"$1,299"` (mis-normalizing it to `1.299`). Disambiguation
    (a narrow, conventional heuristic - never a general locale/NLP number parser):
      - BOTH a comma and a period present: whichever separator occurs LAST is the decimal
        separator (handles both `"1,234.56"` US-thousands-then-decimal and `"1.234,56"`
        EU-thousands-then-decimal); every earlier occurrence of the OTHER separator is stripped as
        thousands grouping.
      - ONLY commas present, exactly one comma, followed by exactly 1-2 digits (e.g. `"12,2"`,
        `"1,5"`, `"0,5"`): a decimal separator (no real-world thousands grouping is ever 1-2
        digits) - converted to a period.
      - Any other comma-only shape (multiple commas, or a lone comma followed by exactly 3 digits -
        conventional thousands grouping, e.g. `"1,234"`): every comma is thousands grouping,
        stripped entirely - unchanged from the previous behavior for this shape.
      - Period-only or no separator at all: already unambiguous (this codebase's own English
        evidence titles always use `.` as a decimal point) - left untouched, exactly as before."""
    body = raw.replace("$", "")
    has_comma, has_period = "," in body, "." in body
    if has_comma and has_period:
        if body.rfind(",") > body.rfind("."):
            body = body.replace(".", "").replace(",", ".")
        else:
            body = body.replace(",", "")
    elif has_comma:
        parts = body.split(",")
        if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
            body = parts[0] + "." + parts[1]
        else:
            body = body.replace(",", "")
    return body


def _extract_meaningful_numbers(title: str) -> set[str]:
    """Pure. A 2+-digit number (optional leading currency sign, locale-aware decimal/thousands
    separators normalized - see `_normalize_numeric_token()`) is distinctive; a single lone digit
    is too common to count as a meaningful fact by itself - identical reasoning to services/
    recap_event.py's own `_extract_numeric_tokens()` (whose separator-handling this deliberately
    no longer mirrors exactly - see `_normalize_numeric_token()`'s own docstring)."""
    tokens: set[str] = set()
    for match in _NUMERIC_TOKEN_RE.finditer(title):
        normalized = _normalize_numeric_token(match.group(0))
        if len(normalized) >= 2:
            tokens.add(normalized)
    return tokens


def _normalize_domain(url: str | None) -> str | None:
    """Mirrors services/recap_event.py's own `_normalize_domain()` (duplicated, not imported - a
    trivial, generic URL-parsing utility, not RECAP business logic, so this follows this module's
    own established per-module-helper-duplication precedent - see `_extract_meaningful_numbers()`
    above - rather than reaching into R1's private surface for something that isn't part of the
    publisher-suffix sanitization algorithm itself)."""
    if not url:
        return None
    netloc = urlsplit(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc or None


def _publisher_suffix_numbers(title: str) -> set[str]:
    """Phase R2.6b (real production finding, Yakutia Story - module docstring). Mirrors
    `services.recap_event._publisher_suffix_entities()`'s own suffix-vs-core methodology exactly,
    applied to NUMERIC tokens instead of entities - reuses that module's own suffix-segmentation
    primitives directly (`_TRAILING_SUFFIX_RE`/`_TRAILING_SUFFIX_MAX_WORDS`/
    `_title_with_normalized_punctuation`), never a new suffix heuristic. A number present ONLY in
    the trailing suffix segment (e.g. "24" in "... - RuNews24") is publisher-derived noise; a number
    that also occurs in the suffix-stripped core is real content evidence and is never flagged.
    Returns an empty set whenever no title-suffix candidate exists at all (the same guard
    `_publisher_suffix_entities()` already applies)."""
    display_title = _title_with_normalized_punctuation(title)
    match = _TRAILING_SUFFIX_RE.search(display_title)
    if not match or len(match.group(1).split()) > _TRAILING_SUFFIX_MAX_WORDS:
        return set()
    suffix_numbers = _extract_meaningful_numbers(match.group(1))
    core_numbers = _extract_meaningful_numbers(display_title[: match.start()])
    return suffix_numbers - core_numbers


# Phase R2.6b (item 8 - real production finding, Nvidia Story: an English Title-Case headline
# produced entities "chip company just bought"/"his own stock"/"million" via services.story_memory.
# _extract_entities()'s own capitalized-run heuristic - confirmed by direct execution to be
# structural, not publisher-suffix contamination). Deliberately a short, explicit, hand-reviewed
# list, never general inference (mirrors services/fact_safety.py's own _ENTITY_ALIAS_GROUPS
# discipline, referenced in that module's own docstring): a genuine proper noun/product/company/
# person/place name never contains a possessive pronoun or a generic modifier word, and a bare
# magnitude word standing alone ("million"/"billion"/"thousand") is not itself a named entity - it
# belongs with a NUMBER, not an entity fact. Deliberately does NOT attempt to filter every possible
# noise phrase (item 8's own explicit "if existing entity-signature structure cannot safely
# distinguish these, classify the limitation explicitly instead of overfitting") - a borderline
# phrase like "artificial intelligence" is legitimately kept, since it names the actual subject
# matter rather than being a syntactic fragment.
_GENERIC_ENTITY_STOPWORDS: frozenset[str] = frozenset({
    "his", "her", "its", "their", "my", "our", "your",
    "just", "very", "own",
    "million", "billion", "thousand",
})


def _is_generic_entity_phrase(entity: str) -> bool:
    """Pure. `entity` is already normalized/lowercased (services.story_memory.normalize_for_entity_
    match()'s own output, by the time it reaches this function). A single bare stopword, or ANY
    word within a multi-word entity matching the stopword list, marks the whole entity as generic
    phrase noise rather than a genuine named entity."""
    return any(word in _GENERIC_ENTITY_STOPWORDS for word in entity.split())


def _evidence_reference_identity(event: NewsEvent, canonical_url: str | None) -> str:
    """Deterministic, read-only, zero network (Phase R2.2 item 7's own explicit priority order).
    Prefers the CANONICAL url's own domain when an Article Acquisition pass has already resolved
    one (an already-persisted read, `load_canonical_urls_for_events()` - the one signal that can
    see past a Google News wrapper without a new fetch). Otherwise falls back to the raw event URL
    ITSELF (never its domain - a Google News wrapper's own domain is identical for every wrapped
    article and would silently re-collapse the exact ambiguity this correction exists to fix), or
    the event id as an absolute last resort when no URL exists at all. This is deliberately a
    distinct-REFERENCE count, not a claim of independently-verified publisher identity - Phase
    R2.2 item 7's own explicit "do not claim they are independently verified publishers if they
    are only distinct URLs.\""""
    canonical_domain = _normalize_domain(canonical_url)
    if canonical_domain:
        return canonical_domain
    return event.url or f"event:{event.id}"


class EventRecapEvidenceContaminationError(RuntimeError):
    """Raised (never silently tolerated) when a publisher-only entity - one
    `_publisher_suffix_entities()` attributes solely to a title's trailing source suffix, never to
    its actual content - is found inside sanitized `content_entities`. Defense-in-depth only: this
    should never fire given `_sanitized_announcement_signature()` already removes these; if it
    ever does, evidence hygiene has regressed and the build must fail loudly rather than silently
    publish contaminated evidence (Phase R2.2 item 5's own explicit "flag/reject... do not
    silently allow contamination")."""


def _assert_no_publisher_contamination(member_events: list[NewsEvent], content_entities: list[str]) -> None:
    content_entity_set = set(content_entities)
    for event in member_events:
        leaked = _publisher_suffix_entities(event.title) & content_entity_set
        if leaked:
            raise EventRecapEvidenceContaminationError(
                f"event {event.id}: publisher-only entities {sorted(leaked)} leaked into sanitized "
                "content_entities - evidence hygiene invariant violated"
            )


@dataclass(frozen=True)
class AnnouncementSummary:
    """One frozen R1 `AnnouncementCluster`, summarized for EVENT_RECAP purposes. Never recomputes
    or second-guesses the cluster itself - `cluster_id`/`member_event_ids`/`headline`/
    `first_seen_at`/`last_seen_at` are taken verbatim from the real `AnnouncementCluster`.
    `content_entities` are derived from R1's own SANITIZED (publisher-suffix-free) signatures -
    see module docstring's Phase R2.2 correction. `evidence_reference_count` is a distinct-
    evidence-reference count (module docstring), never conflated with any R1 readiness signal -
    this dataclass has no readiness-facing count at all, since only the Story-level candidate's
    own `readiness_source_count` ever feeds `evaluate_recap_readiness()`."""

    cluster_id: int
    stable_event_id: UUID
    member_event_ids: list[UUID]
    headline: str
    first_seen_at: datetime
    last_seen_at: datetime
    meaningful_numbers: list[str]
    content_entities: list[str]
    evidence_reference_count: int
    source_refs: list[str]
    # Phase R2.6b: the subset of `meaningful_numbers` that, across every one of this announcement's
    # own member events, was found ONLY inside a trailing publisher-suffix segment, never in the
    # substantive/core title text - diagnostic metadata only, never removed from `meaningful_numbers`
    # itself (the forensic record stays complete). Used exclusively by `_synthesis_verified_facts()`
    # to decide what the LLM-facing evidence projection shows.
    publisher_derived_numbers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TimelineEntry:
    """One announcement-level (never raw-NewsEvent-level) timeline entry - built one-per-cluster,
    so N syndicated copies of one announcement never produce N duplicate timeline entries."""

    timestamp: datetime
    announcement_id: int
    label: str
    source_refs: list[str]
    supporting_event_ids: list[UUID]


@dataclass(frozen=True)
class VerifiedFactCandidate:
    """A deterministically-extracted candidate fact (never LLM-generated). `status` is a plain
    categorical string, never a fabricated 0-100 confidence score (spec's own explicit
    prohibition). `conflicting_evidence` is deliberately always `False` in R2 - detecting a
    genuine cross-announcement factual conflict from titles alone is not reliably possible
    without over-claiming precision this phase does not have; this is a disclosed limitation,
    never a silently-invented signal."""

    fact_type: str  # "numeric" | "entity"
    value: str
    source_event_ids: list[UUID]
    source_count: int
    status: str  # FACT_MULTI_SOURCE_CONFIRMED | FACT_SINGLE_SOURCE_ONLY
    conflicting_evidence: bool = False


@dataclass(frozen=True)
class MediaCandidateRef:
    """A reference into an ALREADY-persisted, already-ranked image/video candidate row - never a
    new fetch, never a new ranking computation. No AI-generated recap image, no collage - see
    module docstring."""

    kind: str  # "image" | "video"
    event_id: UUID
    remote_url: str | None
    rank: int | None


@dataclass(frozen=True)
class SelectedMediaItem:
    """One representative media item. For `tier="story_pool"`/`"discovered"` (Phase H.1/H.3B),
    `candidate_id` + `originating_event_id` is the stable, re-resolvable pointer a future sender
    re-queries `get_editorial_image_candidates()` with - never a copy of `ImageCandidateRecord`
    itself. For `tier="branded_fallback"` (Phase H.3C) there is no `ImageCandidateRecord` row at
    all (nothing was discovered from a real source) - `candidate_id`/`originating_event_id` are
    `None` in that case, and `storage_key`/`sha256` (populated directly by `services.event_recap_
    processor.render_branded_fallback_media()` via the same `integrations.storage.image_storage.
    ImageStorage` abstraction Tier 1/2B candidates already use) are the ONLY resolution path.
    `telegram_file_id`/`remote_url` remain purely audit/display fields for every tier, never the
    sole source of truth."""

    media_type: str  # "image" - every tier so far is images only
    recommended_role: str  # RecommendedRole.value ("hero"/"supporting") for story_pool/discovered;
    # a fixed "hero" for branded_fallback (module docstring - it is always the sole/representative
    # visual when it exists at all, never ranked against alternatives).
    candidate_id: str | None = None
    originating_event_id: UUID | None = None
    storage_key: str | None = None
    telegram_file_id: str | None = None
    sha256: str | None = None
    remote_url: str | None = None  # supplemental fallback only - never the primary resolution path


@dataclass(frozen=True)
class SelectedMediaPlan:
    """The deterministic media-selection outcome for one `EventRecapCandidate` build. `tier`:
    "story_pool" (H.1, confirmed Story media pool), "discovered" (H.3B/Tier 2B, re-acquired from a
    confirmed/effective event's own article page via `services.event_recap_processor.discover_
    event_recap_media_if_needed()`), "branded_fallback" (H.3C/Tier 3, a deterministic, source-
    photo-free NINJA PULSE card via `services.event_recap_processor.render_branded_fallback_media
    ()` - Pillow only, never an AI image-generation call; deliberately NOT named "generated" to
    avoid ever being confused with a future real AI-generated-background tier, which would get its
    own distinct value, e.g. "ai_generated", later), or "none" (no usable visual at all - the
    ordinary, expected fail-soft outcome, never an error). `_select_representative_media()` below
    still only ever produces "story_pool" or "none" itself - "discovered"/"branded_fallback" are
    set by their own processor-level callers via `dataclasses.replace()`, never by this module.
    Absence of a representative item is a normal, expected outcome, never an error."""

    tier: Literal["story_pool", "discovered", "branded_fallback", "none"]
    representative: SelectedMediaItem | None


_NO_MEDIA_PLAN = SelectedMediaPlan(tier="none", representative=None)

# Phase H.3C: bounded, deterministic subject text for the branded fallback card - see
# derive_recap_visual_subject()'s own docstring for the full priority/reasoning.
_MAX_VISUAL_SUBJECT_ENTITIES = 2
_MAX_VISUAL_SUBJECT_CHARS = 60


def derive_recap_visual_subject(candidate: EventRecapCandidate) -> str:
    """Phase H.3C: a short, deterministic, LLM-free label for the Tier 3 branded fallback card -
    never new copywriting, never a semantic rewrite, never a second LLM call. Priority: (1) the
    ANCHOR announcement's own already-deterministically-extracted `content_entities` (R1's
    sanitized entity signatures - the exact same field `render_event_recap_bundle_text()` already
    trusts) - deliberately the anchor's OWN announcement only (found via the same `stable_event_id
    == candidate.anchor_event_id` check that function already uses to label ORIGIN vs FOLLOW_UP),
    never a union across every announcement, since a later comparison/follow-up announcement can
    introduce an unrelated entity (e.g. a competitor named only in a "vs Samsung" headline) that
    would misrepresent the Story's own real subject; bounded to `_MAX_VISUAL_SUBJECT_ENTITIES`,
    joined with " × " (matches the Twitch/Amazon-style "two named entities" case). (2) `candidate.
    story_title` (always non-empty - Story.title is NOT NULL) when the anchor announcement has no
    usable entities. No further, invented "category" fallback exists below that - `EventRecapCandidate`
    carries no category field, and adding one here would be exactly the kind of new NLP/signal
    surface this phase's own "no new subsystem" instruction forbids. Bounded to
    `_MAX_VISUAL_SUBJECT_CHARS`, truncated with an ellipsis if needed - never a giant phrase."""
    anchor_announcement = next(
        (a for a in candidate.announcements if a.stable_event_id == candidate.anchor_event_id), None,
    )
    entities: dict[str, None] = {}
    if anchor_announcement is not None:
        for entity in anchor_announcement.content_entities:
            entities.setdefault(entity, None)
            if len(entities) >= _MAX_VISUAL_SUBJECT_ENTITIES:
                break
    subject = " × ".join(entities.keys()) if entities else candidate.story_title
    if len(subject) > _MAX_VISUAL_SUBJECT_CHARS:
        subject = subject[: _MAX_VISUAL_SUBJECT_CHARS - 1].rstrip() + "…"
    return subject


def serialize_selected_media_plan(plan: SelectedMediaPlan) -> dict[str, Any]:
    """Plain-dict, JSON-safe (UUID -> str) projection of a `SelectedMediaPlan` - `dataclasses.
    dataclass` (unlike this module's Pydantic schemas elsewhere) has no built-in `model_dump(mode=
    "json")`, so this is the one place that conversion happens, kept next to the dataclasses it
    serializes rather than duplicated at each caller. `candidate_id`/`originating_event_id` may
    both be `None` (Phase H.3C's `tier="branded_fallback"` - see `SelectedMediaItem`'s own
    docstring)."""
    if plan.representative is None:
        return {"tier": plan.tier, "representative": None}
    item = plan.representative
    return {
        "tier": plan.tier,
        "representative": {
            "candidate_id": item.candidate_id,
            "originating_event_id": str(item.originating_event_id) if item.originating_event_id else None,
            "media_type": item.media_type,
            "recommended_role": item.recommended_role,
            "storage_key": item.storage_key,
            "telegram_file_id": item.telegram_file_id,
            "sha256": item.sha256,
            "remote_url": item.remote_url,
        },
    }


def serialize_verified_facts(facts: list[VerifiedFactCandidate]) -> list[dict[str, Any]]:
    """Phase I.1 (Final Post Authoring - source-snapshot persistence): plain-dict, JSON-safe
    (UUID -> str) projection of `EventRecapCandidate.verified_facts`, mirroring
    `serialize_selected_media_plan()`'s own established shape/placement exactly - the one place
    this dataclass-to-JSON conversion happens for `VerifiedFactCandidate`, kept next to the
    dataclass it serializes rather than duplicated at each caller. Used by
    `services.event_recap_processor._persist_source_snapshot()` to make the SAME verified-facts
    list `synthesize_event_recap()`'s own fact-safety check already used durable, for future Final
    Post authoring to read without ever rebuilding the Story."""
    return [
        {
            "fact_type": fact.fact_type,
            "value": fact.value,
            "source_event_ids": [str(event_id) for event_id in fact.source_event_ids],
            "source_count": fact.source_count,
            "status": fact.status,
            "conflicting_evidence": fact.conflicting_evidence,
        }
        for fact in facts
    ]


@dataclass(frozen=True)
class FactVerificationResult:
    """The result of running `services.fact_safety.evaluate_fact_safety()` (reused, unmodified)
    against the LLM-synthesized text. `status` is that function's own categorical
    "pass"/"review"/"block" - never invented here. `"not_run"` when no LLM synthesis has been
    attempted yet (the deterministic-only candidate's default)."""

    status: str  # "pass" | "review" | "block" | "not_run"
    claims_checked: int
    supported: int
    uncertain: int
    unsupported: int
    flagged_claims: list[str]


_NOT_RUN_VERIFICATION = FactVerificationResult(
    status="not_run", claims_checked=0, supported=0, uncertain=0, unsupported=0, flagged_claims=[],
)


@dataclass(frozen=True)
class EventRecapCandidate:
    """The complete, immutable EVENT_RECAP shadow candidate. `publishable` is unconditionally
    `False` throughout R2 (module docstring) - no code path in this module ever sets it `True`.

    `readiness_source_count` vs `evidence_reference_count` (Phase R2.2 correction, module
    docstring): `readiness_source_count` is `services.recap_event.count_unique_sources()` VERBATIM
    - the exact value `evaluate_recap_story_integrity()`'s sibling readiness call already saw,
    preserved here only for transparency, NEVER recomputed or reinterpreted. `evidence_reference_
    count` is a separate, R2-only, distinct-evidence-reference count - never fed to readiness,
    never a claim of independently-verified publisher identity."""

    story_id: UUID
    anchor_event_id: UUID
    story_title: str
    generated_at: datetime
    readiness_state: str
    readiness_overridden: bool
    story_integrity_eligible: bool
    story_integrity_reasons: list[str]
    announcement_count: int
    readiness_source_count: int
    evidence_reference_count: int

    announcements: list[AnnouncementSummary]
    timeline: list[TimelineEntry]
    verified_facts: list[VerifiedFactCandidate]
    source_refs: list[str]
    media_candidates: list[MediaCandidateRef]

    recap_title: str | None = None
    recap_summary: str | None = None
    key_takeaways: list[str] = field(default_factory=list)
    uncertainty_notes: list[str] = field(default_factory=list)

    fact_verification: FactVerificationResult = _NOT_RUN_VERIFICATION
    quality_flags: list[str] = field(default_factory=list)
    publishable: bool = False

    # Phase R2.9 (services.recap_origin_projection): True only when this candidate's anchor/member
    # set came from the RECAP-only origin membership projection rather than from `story.
    # first_event_id` being directly present in confirmed membership - never a hidden/implicit
    # signal (module docstring's own "avoid hidden implicit fallback behavior" discipline). Stored
    # Story/link semantics are never affected by this flag either way - see services/
    # recap_origin_projection.py's own module docstring for the full contract.
    origin_projection_applied: bool = False

    # Phase H.1: the Story-level confirmed-membership media selection, computed once in the same
    # pass as `media_candidates` above (never a second Story query) - see `_select_representative_
    # media()`'s own docstring. Defaulted so every pre-H.1 direct construction site (tests) is
    # unaffected.
    selected_media: SelectedMediaPlan = field(default_factory=lambda: _NO_MEDIA_PLAN)

    # R2.10G3-E1: SHADOW-ONLY diagnostic, additive and default-None. Populated only when
    # `settings.recap_eventness_shadow_enabled` is True (default False everywhere) - see
    # services/recap_eventness_shadow.py's own module docstring for the full safety contract.
    # NEVER read by `readiness_state`/`rejection_reasons`/`publishable`/anything above - it is
    # computed strictly after readiness is already finalized, from the same `clusters`/
    # `unique_sources` values readiness itself already used, and attached here purely for
    # observability.
    eventness_shadow: EventnessShadowEvaluation | None = None


@dataclass(frozen=True)
class EventRecapBuildResult:
    """Mirrors `StoryIntegrityResult`/`ReadinessResult`'s own "eligible + reasons" shape (never a
    raised exception for an ordinary, expected rejection - fail-closed and explicit)."""

    candidate: EventRecapCandidate | None
    rejected: bool
    rejection_reasons: list[str]


def _build_announcement_summaries(
    events_by_id: dict[UUID, NewsEvent], clusters: list[AnnouncementCluster],
    canonical_urls_by_event: dict[UUID, str | None],
) -> list[AnnouncementSummary]:
    summaries: list[AnnouncementSummary] = []
    for cluster in clusters:
        numbers: set[str] = set()
        substantive_numbers: set[str] = set()
        entities: dict[str, None] = {}
        member_events = [events_by_id[event_id] for event_id in cluster.event_ids]
        for event in member_events:
            event_numbers = _extract_meaningful_numbers(event.title)
            numbers |= event_numbers
            # Phase R2.6b: a number confirmed substantive by ANY member event's own core text (even
            # a different event in the same announcement) is never treated as publisher-derived
            # overall - only a number that is suffix-only across EVERY event that mentions it ends
            # up in publisher_derived_numbers below.
            substantive_numbers |= event_numbers - _publisher_suffix_numbers(event.title)
            # Phase R2.2: SANITIZED signature (publisher-suffix entities removed) - the same real,
            # unmodified R1 helper `cluster_announcements()` itself feeds its own signature
            # construction to (module docstring). Never the raw `extract_story_signature()` output
            # directly - that was the R2.2 contamination bug.
            raw_signature = extract_story_signature(event.title, event.category)
            sanitized_signature = _sanitized_announcement_signature(raw_signature, event.title)
            for entity in sanitized_signature.entities:
                entities.setdefault(entity, None)
        content_entities = list(entities.keys())
        _assert_no_publisher_contamination(member_events, content_entities)

        evidence_identities = {
            _evidence_reference_identity(event, canonical_urls_by_event.get(event.id))
            for event in member_events
        }
        summaries.append(
            AnnouncementSummary(
                cluster_id=cluster.cluster_id,
                stable_event_id=cluster.event_ids[0],
                member_event_ids=list(cluster.event_ids),
                headline=cluster.headline,
                first_seen_at=cluster.first_seen_at,
                last_seen_at=cluster.last_seen_at,
                meaningful_numbers=sorted(numbers),
                content_entities=content_entities,
                evidence_reference_count=len(evidence_identities),
                source_refs=list(dict.fromkeys(cluster.source_urls)),
                publisher_derived_numbers=sorted(numbers - substantive_numbers),
            )
        )
    return summaries


def _build_timeline(announcements: list[AnnouncementSummary]) -> list[TimelineEntry]:
    entries = [
        TimelineEntry(
            timestamp=a.first_seen_at, announcement_id=a.cluster_id, label=a.headline,
            source_refs=a.source_refs, supporting_event_ids=a.member_event_ids,
        )
        for a in announcements
    ]
    entries.sort(key=lambda entry: entry.timestamp)
    return entries


def _build_verified_facts(announcements: list[AnnouncementSummary]) -> list[VerifiedFactCandidate]:
    number_to_events: dict[str, set[UUID]] = {}
    entity_to_events: dict[str, set[UUID]] = {}
    for announcement in announcements:
        for number in announcement.meaningful_numbers:
            number_to_events.setdefault(number, set()).update(announcement.member_event_ids)
        for entity in announcement.content_entities:
            entity_to_events.setdefault(entity, set()).update(announcement.member_event_ids)

    facts: list[VerifiedFactCandidate] = []
    for number, event_ids in sorted(number_to_events.items()):
        status = FACT_MULTI_SOURCE_CONFIRMED if len(event_ids) >= 2 else FACT_SINGLE_SOURCE_ONLY
        facts.append(
            VerifiedFactCandidate(
                fact_type="numeric", value=number, source_event_ids=sorted(event_ids),
                source_count=len(event_ids), status=status,
            )
        )
    for entity, event_ids in sorted(entity_to_events.items()):
        status = FACT_MULTI_SOURCE_CONFIRMED if len(event_ids) >= 2 else FACT_SINGLE_SOURCE_ONLY
        facts.append(
            VerifiedFactCandidate(
                fact_type="entity", value=entity, source_event_ids=sorted(event_ids),
                source_count=len(event_ids), status=status,
            )
        )
    return facts


def _build_media_ranking_input(
    candidate: EditorialImageCandidate, *, is_duplicate_within_event: bool = False,
) -> MediaRankingInput:
    """Phase H.1: duplicated from `worker/content_cycle.py::_build_media_ranking_input()`
    verbatim (this codebase's own established small-single-purpose-helper duplication convention -
    see this module's own docstring on `_sanitized_announcement_signature()` for the identical
    precedent) - never a divergent field mapping, never importing across the services->worker
    boundary. Assembles `services.media_ranking.MediaRankingInput` from an already-persisted
    `EditorialImageCandidate`'s own already-computed signals - never recomputes any of them."""
    try:
        method = ImageDiscoveryMethod(candidate.discovery_method)
    except ValueError:
        method = None
    warnings = candidate.warnings or []
    width, height = candidate.width, candidate.height
    return MediaRankingInput(
        media_item_id=candidate.id,
        media_type="image",
        quality_score=candidate.quality_score if candidate.quality_score is not None else 0,
        source_priority=round((PROVENANCE_TABLE.get(method, 20) if method is not None else 20) / 100 * 20),
        relevance_score=candidate.relevance_score,
        is_duplicate_within_event=is_duplicate_within_event,
        possible_logo="possible_logo" in warnings,
        possible_banner="possible_banner" in warnings,
        possible_watermark="possible_watermark" in warnings,
        possible_tv_lower_third="possible_tv_lower_third" in warnings,
        possible_branded_screenshot="possible_branded_screenshot" in warnings,
        aspect_ratio_band=aspect_ratio_band(width / height).value if width and height else None,
    )


def _compute_duplicate_flags(candidates: list[EditorialImageCandidate]) -> dict[UUID, bool]:
    """Phase H.1: a deliberately NARROWER sibling of `worker/content_cycle.py::_compute_within_
    event_duplicate_flags()` - exact `sha256` match or near-duplicate `perceptual_hash` (Hamming
    distance <= the existing, imported, calibrated `_NEAR_DUPLICATE_MAX_HAMMING_DISTANCE`) only.
    Deliberately excludes that sibling's own CDN-proxy/origin-URL normalization (Jetpack/Photon
    etc.) - that logic is real, forensically-tuned, and actively evolving; duplicating it here
    would violate "не переписывать dedup" in spirit even though it is a real, disclosed, narrower-
    than-NEWS limitation. Applied across the WHOLE cross-event Story pool at once (not per-event),
    which is what makes it also catch a cross-event duplicate a purely event-scoped check
    (`eligible_for_editorial`, already applied upstream) cannot."""
    seen_sha256: set[str] = set()
    seen_hashes: list[str] = []
    flags: dict[UUID, bool] = {}
    for candidate in candidates:
        is_duplicate = False
        if candidate.sha256 and candidate.sha256 in seen_sha256:
            is_duplicate = True
        elif candidate.perceptual_hash:
            for known_hash in seen_hashes:
                if hamming_distance(candidate.perceptual_hash, known_hash) <= _NEAR_DUPLICATE_MAX_HAMMING_DISTANCE:
                    is_duplicate = True
                    break
        flags[candidate.id] = is_duplicate
        if not is_duplicate:
            if candidate.sha256:
                seen_sha256.add(candidate.sha256)
            if candidate.perceptual_hash:
                seen_hashes.append(candidate.perceptual_hash)
    return flags


def _select_representative_media(image_pool: list[tuple[UUID, EditorialImageCandidate]]) -> SelectedMediaPlan:
    """Pure (no I/O). Phase H.1: ranks the combined, cross-event Story image pool through the
    existing, unmodified `services.media_ranking.rank_media_candidates()` and returns exactly ONE
    representative item - H.1 scope is a single HERO/SUPPORTING pick, never an album (Phase H.0/
    H.0.2's own "не увеличивать scope до album curation" instruction). Video is deliberately not
    ranked here - mirrors the real, existing NEWS production path (`worker/content_cycle.py`),
    which never feeds video through `rank_media_candidates()` either; it always just takes the
    first available video candidate as a structurally separate media type.

    Returns `tier="none"` (never raises, never fails the Story) when the pool is empty or nothing
    in it clears `MediaRankingResult.eligible_for_delivery` - a Story with no usable image is a
    normal, expected outcome (Phase H.0.2's fail-soft discipline), not an error."""
    if not image_pool:
        return _NO_MEDIA_PLAN

    candidates = [candidate for _event_id, candidate in image_pool]
    event_by_candidate_id = {candidate.id: event_id for event_id, candidate in image_pool}
    by_id = {candidate.id: candidate for candidate in candidates}
    duplicate_flags = _compute_duplicate_flags(candidates)

    inputs = [
        _build_media_ranking_input(candidate, is_duplicate_within_event=duplicate_flags.get(candidate.id, False))
        for candidate in candidates
    ]
    ranked = rank_media_candidates(inputs)

    for result in ranked:
        if not result.eligible_for_delivery:
            continue
        candidate = by_id[result.media_item_id]
        return SelectedMediaPlan(
            tier="story_pool",
            representative=SelectedMediaItem(
                candidate_id=candidate.candidate_id,
                originating_event_id=event_by_candidate_id[candidate.id],
                media_type="image",
                recommended_role=result.recommended_role.value,
                storage_key=candidate.storage_key,
                telegram_file_id=candidate.telegram_file_id,
                sha256=candidate.sha256,
                remote_url=candidate.final_url or candidate.source_url or candidate.article_url,
            ),
        )
    return _NO_MEDIA_PLAN


async def _collect_media_candidates(
    session: AsyncSession, events: list[NewsEvent], *, per_event_limit: int = _MAX_MEDIA_PER_EVENT,
) -> tuple[list[MediaCandidateRef], SelectedMediaPlan]:
    """Read-only. Reuses `get_editorial_image_candidates()`/`get_video_candidates_for_event()`
    unchanged - no new query beyond what this function already made before Phase H.1. The same
    per-event `images` rows already fetched for `MediaCandidateRef` are also fed to `_select_
    representative_media()` in this same pass - one Story query, one set of per-event media reads,
    never a second, independent Story-level media query (Phase G.1's build-once discipline,
    extended to media)."""
    media: list[MediaCandidateRef] = []
    seen: set[tuple[str, str]] = set()
    image_pool: list[tuple[UUID, EditorialImageCandidate]] = []
    for event in events:
        images = await get_editorial_image_candidates(session, news_event_id=event.id, limit=per_event_limit)
        for image in images:
            url = image.source_url or image.article_url
            key = ("image", url or image.candidate_id)
            if key in seen:
                continue
            seen.add(key)
            media.append(MediaCandidateRef(kind="image", event_id=event.id, remote_url=url, rank=image.rank))
            image_pool.append((event.id, image))

        videos = await get_video_candidates_for_event(session, event.id, limit=per_event_limit)
        for video in videos:
            key = ("video", video.remote_url)
            if key in seen:
                continue
            seen.add(key)
            media.append(MediaCandidateRef(kind="video", event_id=event.id, remote_url=video.remote_url, rank=None))

    return media, _select_representative_media(image_pool)


async def build_event_recap_candidate(
    session: AsyncSession, story: Story, *, force_shadow: bool = False, now: datetime | None = None,
    research_complete: bool = False,
) -> EventRecapBuildResult:
    """The one deterministic entry point. Zero LLM/Gateway calls, zero network access - exactly as
    safe to call as any R1 diagnostic. Rejects (fail-closed, never silently degrades) when:
    the declared `first_event_id` is missing from confirmed membership AND the RECAP-only origin
    membership projection (Phase R2.9, `services.recap_origin_projection` - see that module's own
    docstring for the full contract) is not itself eligible; Story Integrity fails; or readiness is
    not READY and `force_shadow` was not explicitly passed.

    Phase R2.10A.3: `research_complete` (default `False`, unchanged behavior for every existing
    caller that omits it) is threaded straight through to `services.recap_event.
    evaluate_recap_readiness()` unmodified - mirroring R1's OWN already-established caller-supplied-
    signal convention exactly (`services.recap_event.build_recap_event_snapshot(research_complete:
    bool = False, ...)`, already exercised with `research_complete=True` throughout tests/
    test_recap_event.py). R2 itself still runs no Recap Research step and still never sets this True
    on its own; this only lets a caller that legitimately knows research is complete (e.g. a future
    Recap Research phase, or a test proving the natural non-`force_shadow` READY path is reachable at
    all) supply that already-existing signal, exactly as R1 always allowed. No new architecture, no
    new persistent state, no change to `evaluate_recap_readiness()` itself or any of its thresholds.

    Phase R2.9: when `first_event_id` is absent from confirmed membership but the origin event's
    own current link proves it is a `RELATED_STORY`/weak-`UNCERTAIN_MATCH` own-Story-creation
    artifact (never a stale/ambiguous/conflicting state - fail-closed otherwise), the origin is
    used as the anchor and as an effective RECAP member (`EventRecapCandidate.
    origin_projection_applied=True` records this transparently). This NEVER writes `first_event_id`
    or any `NewsEventStoryLink` row, and NEVER changes what `services.recap_event.load_story_events
    ()`/`_CONFIRMED_MEMBERSHIP_MATCH_TYPES` mean globally - purely a RECAP-local read.

    `force_shadow=True` allows building a candidate from a not-READY Story - `EventRecapCandidate.
    readiness_overridden` records this unconditionally whenever it happens; readiness itself is
    NEVER silently bypassed (`readiness.reasons` are still computed and still visible via
    `readiness_state`, they simply do not block candidate construction under this explicit
    override). Readiness (`recap_min_event_count` etc.) is entirely unaffected by R2.9 - a
    single-event Story (origin-projected or not) still fails readiness exactly as before; Story
    Integrity PASS is never treated as equivalent to readiness or publishability."""
    now = now or datetime.now(timezone.utc)
    events = await load_story_events(session, story.id)
    anchor = next((e for e in events if e.id == story.first_event_id), None)

    # Phase R2.9 (services.recap_origin_projection): only reached when the declared origin is
    # genuinely absent from confirmed membership - the ordinary/majority case above already found
    # `anchor` directly and this branch never runs for it. RECAP-only, read-only, fail-closed - see
    # that module's own docstring for the full contract and the R2.7/R2.8 evidence behind it.
    # Neither `story.first_event_id` nor any `NewsEventStoryLink` row is ever written to here.
    origin_projection_applied = False
    if anchor is None:
        origin_event, projection_decision = await resolve_recap_origin_projection(session, story)
        if projection_decision.eligible and origin_event is not None:
            anchor = origin_event
            events = build_effective_recap_members(origin_event, events)
            origin_projection_applied = True
        else:
            reason = (
                f"declared first_event_id {story.first_event_id} is not among this story's confirmed "
                f"member events - true anchor missing, failing closed "
                f"(origin_projection={projection_decision.reason_code})"
                if events else
                f"no confirmed member events loaded (origin_projection={projection_decision.reason_code})"
            )
            return EventRecapBuildResult(candidate=None, rejected=True, rejection_reasons=[reason])

    integrity = evaluate_recap_story_integrity(anchor, events)
    if not integrity.eligible:
        return EventRecapBuildResult(candidate=None, rejected=True, rejection_reasons=list(integrity.reasons))

    clusters = cluster_announcements(events)
    unique_sources = count_unique_sources(events)
    # Phase R2.10A.1 MissingGreenlet hardening (real production hazard, not a fixture artifact):
    # `events` is guaranteed non-empty by every path that reaches this line - either `anchor` was
    # found directly above (so `events`, its source list, already contained it), or the R2.9 origin-
    # projection branch above reassigned `events` via `build_effective_recap_members()`, which always
    # returns `[origin_event] + confirmed_members` (never empty) - any other outcome of that branch
    # returns early before this point. The previous `default=story.updated_at` fallback was therefore
    # unreachable dead code, yet Python still evaluates a `default=` expression unconditionally on
    # every call regardless of whether the iterable is empty - forcing an eager, unconditional read
    # of `story.updated_at` on every single invocation. `Story.updated_at` is a server-side
    # `onupdate=func.now()` column (database/models/story.py): whenever a caller flushes ANY change
    # to that same `Story` row earlier in the same session (e.g. `services/triage_orchestrator.py`'s
    # own `matched_story.event_count += 1`) without an explicit `session.refresh()` in between, the
    # attribute is left expired, and this eager read triggered an implicit lazy-load - a real
    # `sqlalchemy.exc.MissingGreenlet` under asyncpg outside a greenlet context (reproduced exactly
    # in tests/test_event_recap.py::test_missinggreenlet_regression_no_story_refresh_needed). Removing
    # the unreachable default eliminates the hazard with zero behavior change - the fallback value
    # was never actually reachable/used - and fails loudly instead of fabricating a timestamp if this
    # invariant is ever violated by a future code change.
    assert events, "unreachable: both call paths above guarantee non-empty events by this point"
    last_event_at = max(e.published_at or e.collected_at for e in events)

    readiness = evaluate_recap_readiness(
        event_count=len(events), announcement_count=len(clusters), unique_source_count=unique_sources,
        last_event_at=last_event_at, now=now, research_complete=research_complete, unresolved_conflict_count=0,
        story_integrity_eligible=integrity.eligible, story_integrity_reasons=integrity.reasons,
    )

    if not readiness.ready and not force_shadow:
        return EventRecapBuildResult(candidate=None, rejected=True, rejection_reasons=list(readiness.reasons))

    readiness_overridden = force_shadow and not readiness.ready

    events_by_id = {event.id: event for event in events}
    # Read-only, already-persisted (services.recap_event.load_canonical_urls_for_events() - no
    # network call) - the one signal that lets evidence-reference identity see past a Google News
    # wrapper without a new fetch (module docstring's Phase R2.2 correction).
    canonical_urls = await load_canonical_urls_for_events(session, [event.id for event in events])
    announcements = _build_announcement_summaries(events_by_id, clusters, canonical_urls)
    timeline = _build_timeline(announcements)
    verified_facts = _build_verified_facts(announcements)
    source_refs = list(dict.fromkeys(ref for a in announcements for ref in a.source_refs))
    media_candidates, selected_media = await _collect_media_candidates(session, events)

    evidence_reference_count = len(
        {_evidence_reference_identity(event, canonical_urls.get(event.id)) for event in events}
    )

    # R2.10G3-E1: SHADOW ONLY - computed from the exact same `clusters`/`unique_sources` values
    # `readiness` above already used, never a second, divergent feature computation. `readiness`/
    # `readiness_state`/`readiness_overridden` are already fully finalized above and are never
    # touched by this block; nothing below this point can change them.
    eventness_shadow: EventnessShadowEvaluation | None = None
    if settings.recap_eventness_shadow_enabled:
        timestamps = [e.published_at or e.collected_at for e in events]
        span_hours = (max(timestamps) - min(timestamps)).total_seconds() / 3600 if len(timestamps) > 1 else 0.0
        domains = frozenset(d for e in events if (d := _normalize_domain(e.url)))
        eventness_shadow = evaluate_eventness_shadow(EventnessShadowFeatures(
            story_span_hours=span_hours, unique_source_count=unique_sources,
            announcement_count=len(clusters), source_domains=domains,
        ))

    candidate = EventRecapCandidate(
        story_id=story.id, anchor_event_id=anchor.id, story_title=story.title, generated_at=now,
        readiness_state=readiness.state, readiness_overridden=readiness_overridden,
        story_integrity_eligible=integrity.eligible, story_integrity_reasons=list(integrity.reasons),
        announcement_count=len(clusters), readiness_source_count=unique_sources,
        evidence_reference_count=evidence_reference_count,
        announcements=announcements, timeline=timeline, verified_facts=verified_facts,
        source_refs=source_refs, media_candidates=media_candidates,
        origin_projection_applied=origin_projection_applied, selected_media=selected_media,
        eventness_shadow=eventness_shadow,
    )
    return EventRecapBuildResult(candidate=candidate, rejected=False, rejection_reasons=[])


def _synthesis_verified_facts(
    verified_facts: list[VerifiedFactCandidate], announcements: list[AnnouncementSummary],
) -> list[VerifiedFactCandidate]:
    """Phase R2.4 (real production finding, Sverdlovsk synthesis replay - see module docstring's
    Phase R2.4 note below): the smallest deterministic synthesis-evidence projection. Excludes a
    fact if and only if it is a raw, SINGLE-SOURCE ENTITY token (`fact_type == "entity" and status
    == FACT_SINGLE_SOURCE_ONLY`) - a class of noisy, un-narrated evidence a real production
    candidate exposed (a bare token like "областн", a `_publisher_suffix_entities()`-boundary
    artifact - see services/recap_event.py's own R1.5B.1 docstring - that survived sanitization for
    a title whose suffix regex could not match it, R1's own frozen, disclosed limitation, never
    patched here). Never excludes a meaningful NUMBER (any source count) or a MULTI-SOURCE entity -
    those carry real, corroborated factual content. Generic and Story-agnostic: no publisher
    dictionary, no hardcoded word, no Sverdlovsk-specific string anywhere in this function.

    Phase R2.6b additions (module docstring - real Yakutia/Nvidia production findings): also
    excludes a NUMERIC fact whose value never appears as substantive/core content across any
    announcement (`_publisher_suffix_numbers()` - publisher-derived-only), and an ENTITY fact whose
    value is a generic pronoun/modifier/magnitude phrase (`_is_generic_entity_phrase()`) -
    regardless of source_count/status for the latter, since a generic phrase carries no meaningful
    content signal no matter how many events happen to repeat it.

    `EventRecapCandidate.verified_facts`/`AnnouncementSummary.meaningful_numbers`/`.content_entities`
    are NEVER filtered - the full, unfiltered set stays available for diagnostic/provenance purposes
    (the CLI's own `.txt` report prints it directly, and `AnnouncementSummary.publisher_derived_
    numbers` records exactly which numbers this projection removes and why); this projection exists
    only for what is actually shown to the LLM (via `render_event_recap_bundle_text()`, used both
    for the synthesis prompt and its own pre-synthesis audit file)."""
    confirmed_substantive_numbers = {
        number
        for announcement in announcements
        for number in set(announcement.meaningful_numbers) - set(announcement.publisher_derived_numbers)
    }
    result: list[VerifiedFactCandidate] = []
    for fact in verified_facts:
        if fact.fact_type == "entity" and fact.status == FACT_SINGLE_SOURCE_ONLY:
            continue
        if fact.fact_type == "entity" and _is_generic_entity_phrase(fact.value):
            continue
        if fact.fact_type == "numeric" and fact.value not in confirmed_substantive_numbers:
            continue
        result.append(fact)
    return result


def _describe_fact_provenance(fact: VerifiedFactCandidate) -> str:
    """Phase R2.4 (item 8's own explicit requirement): plain editorial language only - never the
    internal `fact_type`/`status` implementation vocabulary ("entity", "MULTI_SOURCE_CONFIRMED",
    etc.), which a real production synthesis call was observed echoing verbatim into
    uncertainty_notes once it appeared literally in the bundle text it was given.

    Phase R2.5 correction (real production finding - the R2.4 wording below, "multiple
    INDEPENDENT reports", was itself the exact, direct root cause of a real synthesis call writing
    "подтверждено несколькими независимыми сообщениями" - a corroboration claim stronger than the
    evidence actually supports). `FACT_MULTI_SOURCE_CONFIRMED` means only "appears across >=2
    distinct confirmed member events" (services.event_recap._build_verified_facts()'s own
    `len(event_ids) >= 2` check) - it says nothing about whether those events came from
    independently-operated publishers (Sverdlovsk's own real `readiness_source_count=1`
    demonstrates exactly this: 3 distinct evidence references, ALL attributed to one collector
    NewsSource row). No `independent_publisher_count` metric exists in this codebase (module
    docstring's Phase R2.5 note) and none is invented here - wording now says only what is
    actually known: how many stored reports/references mention the fact, never whether they are
    independently sourced."""
    if fact.status == FACT_MULTI_SOURCE_CONFIRMED:
        return f"{fact.value} - appears in multiple stored reports"
    return f"{fact.value} - mentioned in a single stored report only"


def render_event_recap_bundle_text(candidate: EventRecapCandidate) -> str:
    """Deterministic, bounded plain-text rendering - the exact text the EVENT_RECAP synthesis
    prompt reads, and the exact text fed to `services.fact_safety.evaluate_fact_safety()` as
    `FactEvidence.source_content`. Mirrors services/telegraph_research_context.py::
    render_bundle_text()'s own shape/discipline: never article prose, never a raw JSON/repr dump.

    Phase R2.4 correction (real production finding - a real Sverdlovsk synthesis call): this is
    now the "clean editorial synthesis input" (module docstring) - it (1) shows only `_synthesis_
    verified_facts()`'s filtered set, in plain editorial language via `_describe_fact_provenance()`
    (never the raw `[fact_type] value - STATUS` internal-vocabulary form the full diagnostic
    candidate's own CLI `.txt` report still uses), and (2) explicitly caveats the timeline as
    PUBLICATION chronology, not proven event-progression stages (item 9) - a real synthesis output
    once narrated "three sequential announcements" from timestamp order alone, which the ordering
    itself never proves. `EventRecapCandidate.verified_facts`/`.announcements` themselves are
    completely unaffected - this function only changes what THIS rendering shows."""
    lines: list[str] = [
        f"Story: {candidate.story_title}",
        f"Announcement count: {candidate.announcement_count} | "
        f"readiness source count: {candidate.readiness_source_count} | "
        f"evidence reference count: {candidate.evidence_reference_count}",
        "",
        "ANNOUNCEMENT CONTEXT:",
    ]
    for announcement in candidate.announcements:
        role = "ORIGIN" if announcement.stable_event_id == candidate.anchor_event_id else "FOLLOW_UP"
        lines.append("")
        lines.append(f"- [{role}]")
        lines.append(announcement.headline)

    lines.append("")
    lines.append(
        "TIMELINE (order of PUBLICATION only, oldest first - this reflects when each report "
        "appeared, not necessarily separate stages of the underlying event's own development; "
        "do not narrate multiple publications as proven sequential developments unless the "
        "evidence itself states that):"
    )
    for entry in candidate.timeline:
        lines.append(
            f"- {entry.timestamp.isoformat()} | {entry.label} "
            f"(sources: {len(entry.source_refs)}, supporting events: {len(entry.supporting_event_ids)})"
        )

    lines.append("")
    lines.append("VERIFIED FACTS (from stored evidence, not LLM-generated):")
    synthesis_facts = _synthesis_verified_facts(candidate.verified_facts, candidate.announcements)
    if synthesis_facts:
        for fact in synthesis_facts:
            lines.append(f"- {_describe_fact_provenance(fact)}")
    else:
        lines.append("- (none recorded)")

    # Phase R2.10 correction (real diagnostic finding, Story 2cb29dab-de57-493d-bf2b-09f80db875a7):
    # a per-announcement "ANNOUNCEMENTS (detail)" section used to follow here, repeating the same
    # announcement headlines already shown in ANNOUNCEMENT CONTEXT and TIMELINE above as a third
    # one-bullet-per-announcement block. That structural repetition - not the prompt's own wording -
    # was the dominant signal pushing synthesis toward one key_takeaway per announcement, so this
    # rendering no longer includes it. `EventRecapCandidate.announcements` itself (cluster_id,
    # meaningful_numbers, content_entities, evidence_reference_count per announcement) is completely
    # unaffected - only this LLM-facing text changes; ANNOUNCEMENT CONTEXT (ORIGIN/FOLLOW_UP roles)
    # and TIMELINE (chronology) still carry every announcement's headline exactly once each.
    text = "\n".join(lines)
    if len(text) > _MAX_BUNDLE_TEXT_CHARS:
        text = text[:_MAX_BUNDLE_TEXT_CHARS] + "\n[... truncated at bounded length ...]"
    return text


# Telegram's own hard limit for a plain text message, in UTF-16 code units (mirrors bot/
# telegraph_shortlist_formatting.py's own SAFE_LIMIT constant and "fail loud, never silently
# truncate" discipline exactly - this codebase's own established convention for Telegram text).
_TELEGRAM_SAFE_LIMIT = 4096
_MAX_TIMELINE_ENTRIES_IN_PREVIEW = 6
_MAX_SOURCE_DOMAINS_IN_PREVIEW = 5


class EventRecapTelegramPreviewTooLongError(RuntimeError):
    """Raised when the rendered preview exceeds `_TELEGRAM_SAFE_LIMIT` - never silently truncated
    (mirrors bot/telegraph_shortlist_formatting.py::TelegraphShortlistTextTooLongError's identical
    "fail loud, let the caller decide" discipline)."""


def render_event_recap_telegram_preview(candidate: EventRecapCandidate) -> str:
    """Phase R2.10 Night 2 (Phase 18) - PURE PROTOTYPE ONLY. A pure, deterministic formatting
    function - no `aiogram`/`Bot` import anywhere in this module, never wired into any router,
    worker, or delivery path (repo-wide, this is enforced by the same AST check tests/
    test_event_recap.py::test_no_bot_or_worker_or_telegram_imports_anywhere_in_r2() already applies
    to this whole module). Exists to prototype the SHAPE of an eventual Telegram-facing rendering,
    never to send anything - `EventRecapCandidate.publishable` stays unconditionally `False`
    regardless of what this function returns, and nothing calls this function anywhere except its
    own tests.

    Deliberately respects the two hard Telegram constraints already known in this codebase (never
    assumed, never guessed): a channel post cannot place arbitrary text INSIDE/OVER an image, so
    this renders text-only (media selection/attachment is a delivery-layer decision, entirely out
    of scope here - see the R2.10 Night 2 report's own Media Readiness Audit); and a forwarded
    message strips inline buttons, so this never emits a button/callback shape of any kind - the
    source attribution is a plain trailing text line, nothing else.

    Renders (in order): title (the synthesized `recap_title` if synthesis has run, else the real,
    deterministic `story_title` - never a placeholder), a short intro (`recap_summary`), a bounded
    "key developments" section (from `candidate.timeline`, publication order, the same "not
    necessarily proven event stages" caveat `render_event_recap_bundle_text()` already applies),
    key takeaways, an uncertainty note section (only rendered when non-empty - never a "no
    uncertainty" filler line, mirrors this module's own `_build_verified_facts()`-adjacent "never
    pad" discipline elsewhere), and a bounded source-attribution line (deduplicated domains only,
    never a raw URL dump - mirrors `_evidence_reference_identity()`'s own domain-first identity
    preference). Raises `EventRecapTelegramPreviewTooLongError` rather than silently truncating."""
    title = candidate.recap_title or candidate.story_title
    lines: list[str] = [title, ""]

    if candidate.recap_summary:
        lines.append(candidate.recap_summary)
        lines.append("")

    if candidate.timeline:
        lines.append("Key developments:")
        for entry in candidate.timeline[:_MAX_TIMELINE_ENTRIES_IN_PREVIEW]:
            lines.append(f"- {entry.timestamp.date().isoformat()}: {entry.label}")
        if len(candidate.timeline) > _MAX_TIMELINE_ENTRIES_IN_PREVIEW:
            lines.append(f"- (+{len(candidate.timeline) - _MAX_TIMELINE_ENTRIES_IN_PREVIEW} more)")
        lines.append("")

    if candidate.key_takeaways:
        lines.append("Key takeaways:")
        for takeaway in candidate.key_takeaways:
            lines.append(f"- {takeaway}")
        lines.append("")

    if candidate.uncertainty_notes:
        lines.append("What remains uncertain:")
        for note in candidate.uncertainty_notes:
            lines.append(f"- {note}")
        lines.append("")

    domains = sorted({d for d in (_normalize_domain(ref) for ref in candidate.source_refs) if d})
    if domains:
        shown = domains[:_MAX_SOURCE_DOMAINS_IN_PREVIEW]
        more = len(domains) - len(shown)
        suffix = f" (+{more} more)" if more > 0 else ""
        lines.append(f"Sources: {', '.join(shown)}{suffix}")

    text = "\n".join(lines).strip()
    if len(text) > _TELEGRAM_SAFE_LIMIT:
        raise EventRecapTelegramPreviewTooLongError(
            f"rendered preview is {len(text)} chars, exceeds Telegram's {_TELEGRAM_SAFE_LIMIT}-char limit"
        )
    return text


class EventRecapSynthesisError(RuntimeError):
    """Raised on any LLM Gateway failure or malformed/incomplete structured output during
    EVENT_RECAP synthesis - never silently swallowed, never returns a partially-fabricated
    candidate."""


def _build_synthesis_request(
    candidate: EventRecapCandidate, prompt: RenderedPrompt, language: str,
) -> GenerateRequest:
    """Phase R2.5 correction (real production finding): this function's own context/task labels
    previously read "EVIDENCE BUNDLE:"/"the evidence bundle above" - a direct, literal source of
    the "bundle" vocabulary a real synthesis call echoed into its own Russian editorial output.
    Neither label is part of the immutable prompt file (never touched here) - both are plain
    Python string literals this function itself constructs, now reworded to avoid the word
    entirely.

    `language` (Phase F.4.9): appended to `task_text` as a plain instruction line, byte-for-byte
    the same `f"Target output language: {...}"` convention every other Capability's own
    `execute()` already appends to its own Gateway request content (e.g. capabilities/
    research_capability.py, capabilities/copywriting_capability.py) - reusing the codebase's one
    existing, capability-agnostic language mechanism (`BusinessContext.language`, sourced from
    `core.config.settings.default_content_language`), never a new one. The immutable prompt file
    itself (`prompts/event_recap/v3.yaml`) is untouched - this is a plain Python string this
    function already constructs, exactly like the "SOURCE EVIDENCE:"/"TASK:" labels above it.

    Phase I.2.2L correction (real production finding, first live full-chain canary): a real
    synthesis call against English-sourced evidence, targeting `language="ru"`, produced hybrid
    words - a Russian grammatical ending grafted directly onto an untranslated English stem
    ("turbulentных", "disruptive-последствий") - because the bare "Target output language: ru"
    instruction said WHICH language to write in but never said anything about HOW to translate
    ordinary vocabulary fully rather than only conjugating/declining it. The addition below is a
    general language-quality rule (works for whatever `language` value is passed, never hardcoded
    to Russian) with one illustrative counter-example of the forbidden SHAPE, not a fixed
    replacement dictionary - it explicitly still allows proper nouns/brand/product names to stay
    unchanged and exact quotations to stay in their original language, so it cannot be satisfied
    by blindly translating everything. This is purely additive to `task_text`, EventRecap-only
    (this function is called from nowhere but `synthesize_event_recap()`), and does not touch
    `prompts/event_recap/v3.yaml` or any other capability's own identical language-instruction
    convention."""
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    evidence_text = render_event_recap_bundle_text(candidate)
    context_text = f"SOURCE EVIDENCE:\n{evidence_text}"
    task_text = (
        "Synthesize a structured EVENT recap strictly from the source evidence above, for internal "
        "review only. Produce fewer takeaways than the maximum if the evidence supports fewer - "
        "never pad.\n\n"
        f"Target output language: {language}. Write in fluent, natural {language} throughout - "
        f"never construct a hybrid word by attaching a {language} grammatical ending directly onto "
        "an untranslated English word stem (for example, do not write something shaped like "
        "\"turbulentных\" or \"disruptive-последствий\" - translate the ordinary descriptive word "
        f"itself into {language}). Translate ordinary descriptive and narrative vocabulary fully "
        f"into {language}. Proper nouns, trademarks, product/model names, and established technical "
        f"terms that have no natural {language} equivalent may remain in their original form "
        f"unchanged - never invent a {language} translation for a brand or product name. If the "
        "evidence contains an exact quotation that must be preserved verbatim, you may keep that "
        "quotation in its original language, clearly marked as a quotation - do not extend that "
        "exception to ordinary prose."
    )
    return GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[ContentPart(type="text", text=f"CONTEXT:\n{context_text}\n\nTASK:\n{task_text}")]),
        ],
        response_mode="json_schema",
        response_schema=prompt.output_schema,
    )


def _verify_synthesis_facts(
    candidate: EventRecapCandidate, recap_title: str, recap_summary: str, key_takeaways: list[str],
) -> FactVerificationResult:
    """Reuses `services.fact_safety.evaluate_fact_safety()` directly, unmodified - no embeddings,
    no semantic vector verification, no new fact-safety mechanism (module docstring).

    Phase R2.4 correction (real production finding, proven by direct execution - never a guess):
    a real Sverdlovsk synthesis call produced the LLM-generated recap_title "Тестирование ИИ для
    диагностики рака кожи в Свердловской области". `services.fact_safety._extract_entities()`
    captured "Тестирование ИИ" as a single 2-word entity run purely because both words happen to
    be capitalized (one sentence-initial, one an all-caps abbreviation) - confirmed by direct
    execution to be a GENERAL mechanism (not RECAP-specific: a plain synthetic title "Разработка
    ИИ ускоряется в Китае" triggers the identical extraction), but with no evidence this has
    actually affected any other real caller (NEWS_ANALYSIS/CONTENT_GENERATION) - so, per this
    checkpoint's own explicit instruction, `services/fact_safety.py` was NOT touched. Passing
    `recap_title` as `draft_title` (the previous behavior) made `_entity_severity()`'s own
    `is_central` check trivially True (the entity is, by definition, always a substring of the
    title it was extracted from) - escalating an unsupported entity to "high" severity, which
    `_draft_status()` treats as a hard BLOCK, regardless of what the entity actually is.

    Fixed on the RECAP side only: `draft_title` is now `candidate.story_title` - the REAL,
    deterministic Story title (never LLM-generated, so it can never itself introduce a spurious
    entity) - while `recap_title` moves into `draft_body` instead, so its own content is still
    fully extracted and verified, just no longer automatically granted "central to this draft"
    severity escalation merely for having occupied the title slot. Confirmed by direct execution:
    this flips the real Sverdlovsk case from status="block" to status="review" (medium severity,
    still flagged, never silently hidden - `evaluate_fact_safety()`'s own "unknown -> REVIEW, not
    BLOCK" design already treats this as the correct signal), while a genuine high-severity
    fabrication (e.g. an invented percentage) still blocks unchanged - neither `_extract_entities()`
    nor any severity/threshold constant was touched."""
    bundle_text = render_event_recap_bundle_text(candidate)
    evidence = FactEvidence(
        source_title=candidate.story_title,
        source_content=bundle_text,
        source_url=None,
        research_facts=[f"{fact.fact_type}: {fact.value}" for fact in candidate.verified_facts],
    )
    draft_body = recap_title + "\n" + recap_summary + "\n" + "\n".join(key_takeaways)
    result = evaluate_fact_safety(candidate.story_title, draft_body, evidence)
    return FactVerificationResult(
        status=result["status"], claims_checked=result["claims_checked"],
        supported=result["supported"], uncertain=result["uncertain"], unsupported=result["unsupported"],
        flagged_claims=[finding["claim"] for finding in result["findings"]],
    )


# Phase R2.5 (item 12) - small, explicit, hand-curated, never a general classifier or a large
# blacklist (mirrors this codebase's own established discipline for exactly this kind of narrow
# term list - e.g. services/fact_safety.py's own _ENTITY_ALIAS_GROUPS: "Deliberately a short,
# explicit, hand-reviewed list, never general... inference"). Exactly the internal-pipeline terms a
# real production synthesis call was observed leaking, plus the terms this checkpoint's own items
# 5/8 explicitly enumerate - never expanded beyond what was actually requested/observed.
_INTERNAL_VOCABULARY_TERMS: frozenset[str] = frozenset({
    "bundle", "evidence bundle", "candidate", "parser", "entity token",
    "single_source_only", "multi_source_confirmed", "fact verification",
    "internal evidence status",
})


def _detect_internal_vocabulary_leak(
    recap_title: str, recap_summary: str, key_takeaways: list[str], uncertainty_notes: list[str],
) -> list[str]:
    """Phase R2.5 defense-in-depth (item 12) - a deterministic, RECAP-only post-synthesis guard,
    never a rewrite/sanitizer (item 11's own explicit "do not silently rewrite generated prose
    with brittle string replacement"). Case-insensitive substring search across all four final
    editorial fields for the small, explicit term list above. Returns the terms actually found
    (empty if none) - the caller (synthesize_event_recap()) turns a non-empty result into a
    disclosed `quality_flags` entry; `publishable` is already unconditionally `False` regardless,
    so this never needs to change any gating decision, only surface the finding."""
    haystack = " ".join([recap_title, recap_summary, *key_takeaways, *uncertainty_notes]).lower()
    return sorted(term for term in _INTERNAL_VOCABULARY_TERMS if term in haystack)


async def synthesize_event_recap(
    candidate: EventRecapCandidate, gateway: LLMGateway, prompt_repository: PromptRepository,
    *, runtime: RuntimeContext, language: str,
    call_observer: Callable[[CapabilityCall], None] | None = None,
) -> EventRecapCandidate:
    """SHADOW ONLY - the returned candidate's `publishable` remains unconditionally `False`
    regardless of the synthesis or verification outcome (module docstring). Makes exactly one
    `LLMGateway.generate()` call, through the existing `capabilities.gateway_call.call_generate()`
    observability wrapper - never a raw/direct provider call. Raises `EventRecapSynthesisError` on
    any Gateway failure or malformed/incomplete structured output; never returns a partially
    populated candidate on failure - the caller's own `candidate` is untouched until this function
    returns successfully.

    `language` (Phase F.4.9 - required, deliberately no default): the editorial output language,
    reusing `schemas.capability.BusinessContext.language`'s own existing, codebase-wide contract
    verbatim - "never left to that schema field's own implicit default" (BusinessContext's own
    comment). The one production caller (capabilities/event_recap_capability.py) passes
    `context.business.language` directly, exactly like every sibling Capability's own `execute()`
    already does for its own Gateway request. Threaded into `_build_synthesis_request()` as a
    plain appended instruction line - never a second LLM call, never a post-generation translation
    pass, never a new prompt version (`prompts/event_recap/v3.yaml` is untouched).

    `call_observer` (Phase R2 integration, Phase B.2 - purely additive, never changes synthesis
    behavior): optional, called once with the real `CapabilityCall` `call_generate()` itself
    already produced (`GatewayCallOutcome.call` - "always populated... on both success and
    failure", capabilities/gateway_call.py's own docstring), on BOTH the success and the
    `EventRecapSynthesisError` path. Exists because this function's own return shape (the updated
    `candidate`, or a raised exception) never otherwise exposes that `CapabilityCall` - a direct
    caller (capabilities/event_recap_capability.py::EventRecapCapability) needs it to populate its
    own `CapabilityResult.calls`/error `calls=` for cost accounting
    (capabilities/executor.py::CapabilityExecutor._record_cost() reads exactly that list). Never
    called with anything else, never influences the synthesis/verification outcome itself - a
    caller that omits it (every caller before Phase B.2) is completely unaffected."""
    prompt = prompt_repository.resolve(EVENT_RECAP_PROMPT_NAME, EVENT_RECAP_PROMPT_VERSION)
    request = _build_synthesis_request(candidate, prompt, language)
    outcome = await call_generate(gateway, request, runtime=runtime, sequence=0)
    if call_observer is not None:
        call_observer(outcome.call)
    if outcome.error is not None:
        raise EventRecapSynthesisError(str(outcome.error)) from outcome.error

    response = outcome.response
    assert response is not None  # GatewayCallOutcome guarantees exactly one of response/error is set

    structured = response.structured_output
    if not isinstance(structured, dict):
        raise EventRecapSynthesisError("EVENT_RECAP synthesis returned no structured_output.")

    required = prompt.output_schema.get("required", [])
    missing = [key for key in required if key not in structured]
    if missing:
        raise EventRecapSynthesisError(f"EVENT_RECAP synthesis output missing required key(s): {missing}")

    recap_title = structured.get("recap_title")
    recap_summary = structured.get("recap_summary")
    key_takeaways = structured.get("key_takeaways")
    uncertainty_notes = structured.get("uncertainty_notes")
    if not isinstance(recap_title, str) or not isinstance(recap_summary, str):
        raise EventRecapSynthesisError("EVENT_RECAP synthesis output has a malformed recap_title/recap_summary.")
    if not isinstance(key_takeaways, list) or not all(isinstance(item, str) for item in key_takeaways):
        raise EventRecapSynthesisError("EVENT_RECAP synthesis output has a malformed key_takeaways list.")
    if not isinstance(uncertainty_notes, list) or not all(isinstance(item, str) for item in uncertainty_notes):
        raise EventRecapSynthesisError("EVENT_RECAP synthesis output has a malformed uncertainty_notes list.")

    # Enforce the declared cap defensively even though the prompt's own schema/rules already ask
    # for it - never trust model output alone for a hard structural bound. Never pads a short list.
    key_takeaways = key_takeaways[:_MAX_KEY_TAKEAWAYS]

    verification = _verify_synthesis_facts(candidate, recap_title, recap_summary, key_takeaways)
    quality_flags = list(candidate.quality_flags)
    if verification.status != "pass":
        quality_flags = [*quality_flags, f"fact_verification_{verification.status}"]

    leaked_terms = _detect_internal_vocabulary_leak(recap_title, recap_summary, key_takeaways, uncertainty_notes)
    if leaked_terms:
        quality_flags = [*quality_flags, f"internal_vocabulary_leak_detected:{','.join(leaked_terms)}"]

    return replace(
        candidate,
        recap_title=recap_title, recap_summary=recap_summary,
        key_takeaways=key_takeaways, uncertainty_notes=uncertainty_notes,
        fact_verification=verification, quality_flags=quality_flags,
        publishable=False,
    )
