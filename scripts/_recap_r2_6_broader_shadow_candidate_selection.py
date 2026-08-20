"""NINJA PULSE RECAP Phase R2.6 - broader production shadow candidate selection + no-LLM preflight.

DIAGNOSTIC ONLY. Selection + deterministic classification - makes ZERO LLM/Gateway calls, ZERO
network calls beyond the one read-only DB transaction. Does not modify `services/recap_event.py`,
`services/story_memory.py`, or `services/fact_safety.py`; does not tune Story Integrity,
announcement clustering, readiness, or `prompts/event_recap/v2.yaml`.

Flow, for each scanned Story:
    load confirmed events -> Story Integrity (frozen, unmodified) -> editorial relevance
    (services.news_editorial_relevance.classify_editorial_relevance(), reused, not reimplemented)
    -> build_event_recap_candidate(force_shadow=True) [see note below] -> evidence hygiene scan
    (the exact forbidden-term list Phase R2.5 established) -> deterministic synthesis-input
    quality classification (PASS/PARTIAL/FAIL across 9 dimensions) -> shortlist selection.

force_shadow=True note (spec R2.6 item 6/7's own required distinction): `build_event_recap_
candidate()` is always called with `force_shadow=True` here so a full candidate (announcements,
timeline, verified facts, evidence hygiene) can be inspected for EVERY Story that passes Story
Integrity, regardless of whether it is naturally READY - `research_complete` is always False in R2
(no Recap Research step exists yet), so a real Story is essentially never naturally ready anyway
(see services/event_recap.py's own module docstring). The TRUE, unforced readiness is never hidden:
`original_ready = not candidate.readiness_overridden` is computed and reported for every Story
exactly as scripts/_recap_r2_event_shadow.py's own CLI report already does - a force-shadow-built
candidate is NEVER described as "naturally ready" anywhere in this script's own output.

Story Integrity itself is never bypassed by this - it is the FIRST gate, checked identically
regardless of force_shadow, and a Story that fails it is excluded from the shortlist outright
(spec item 8 - "hard", never overridden).

Known excluded Story (spec item 5): 859ffea0-9b54-41cb-be25-13c061ca75ad (Taiwan) - a proven,
frozen fail-closed case (declared first_event_id not among confirmed members) - excluded
unconditionally unless the live read-only scan shows it no longer exists in the current pool.

Phase R2.6a correction (real production R2.6 scan returned pool_inspected=60, integrity_pass=27,
quality_verdicts={'PASS': 1, 'PARTIAL': 26}, shortlist_size=5 - mechanically correct, but the
shortlist itself was editorially unacceptable: it included the CLOSED Sverdlovsk Story and two
research-paper abstracts). Root cause (proven by reading services/news_editorial_relevance.py,
not modifying it): `classify_editorial_relevance()`'s ADJACENT tier is overloaded - it is returned
both for a genuine keyword-based adjacency hit (robotics/space/datacenter/semiconductor,
rank_adjustment=3) AND as the fallback "no keyword evidence found at all" default
(rank_adjustment=0, reason="no editorial-relevance keyword evidence - neutral default", see that
module's own final `return` statement). The old `_ACCEPTABLE_RELEVANCE_TIERS = {CORE, ADJACENT}`
check could not tell these apart, so anything with zero keyword signal - academic abstracts, book
promos, off-topic finance pieces that happen not to hit the PERIPHERAL phrase list - passed
through as if genuinely adjacent. Fixed here, diagnostic-side only, via `_relevance_accepted()`,
which additionally requires the reason string not be the neutral-default one. This is a stricter
SHORTLIST gate, not a change to production's own tiering/ranking semantics.

R2.6a also adds (all diagnostic-only, none touching production selection/ranking code):
  - EXCLUDED_STORY_IDS now also excludes the Sverdlovsk Story (60be3f72-28d3-4c5a-af65-f0550923fe94)
    - already used for three controlled paid validation runs (R2.3/R2.4/R2.5) and explicitly
      declared CLOSED; must never be selected again for broader-transfer testing (spec item 5/H).
  - `_is_research_abstract_like()` - a small, conservative, regex/phrase heuristic (never an LLM,
    never embeddings, never a giant blacklist) distinguishing an academic-abstract-shaped title
    from a journalistic headline, calibrated against the two real production titles the R2.6a
    checkpoint reported ("Diffusion models have recently shown strong potential for multivariate
    time-series anomaly detection...", "On-policy distillation (OPD) offers a promising way...").
    False negatives (missing an abstract) are accepted; false positives (rejecting a real headline)
    are not - the marker list stays short and specific, never a generic word like "aims to" alone.
  - `_is_finance_advice_like()` - a small, additive diagnostic-only marker list for
    investment-advice/wealth-story shapes not already covered by
    services/news_editorial_relevance.py's own (untouched) `_PERIPHERAL_PHRASES` (e.g.
    "should you buy", "billionaire", "net worth" - none of which appear in that module's real
    PERIPHERAL list, confirmed by reading it).
  - `editorial_event_class` per usable Story: NEWS_EVENT / MINIMAL_EDGE (single-announcement,
    explicitly labeled, spec item 9) / RESEARCH_ABSTRACT_REJECTED / FINANCE_ADVICE_REJECTED /
    RELEVANCE_NEUTRAL_REJECTED - shown in the report and used by `_select_shortlist()`.
  - `_select_shortlist()` now hard-caps at most ONE MINIMAL_EDGE Story, never pads the shortlist
    with weak/duplicate single-announcement Stories to hit TARGET_SHORTLIST, and returns fewer than
    5 if fewer than 5 genuinely pass every gate (spec item 10 - "quality over quota").
  - Full `render_event_recap_bundle_text(candidate)` is now printed for every shortlisted Story
    (spec item 13) - previously only counts were shown.
  - A "PRIOR R2.6a SHORTLIST DISPOSITION" report section explicitly states, for the five Stories
    the earlier unacceptable shortlist selected, whether the new policy retains or rejects each and
    why (spec item 15) - evaluated live against whatever the current scan finds, never hardcoded.

Phase R2.6b correction (real production R2.6a rescan - shortlist_size=2, both Stories exposed
NEW deterministic evidence-quality problems the R2.6a policy did not catch):
  - Yakutia (2a39731e...) - a real production announcement title ended " - RuNews24"; numeric
    extraction (`services.event_recap._extract_meaningful_numbers()`) scanned the RAW title and
    captured "24" out of the publisher-brand suffix "RuNews24" - the identical structural bug class
    as R1.5B.1's entity contamination, never previously fixed for numbers. Fixed in
    `services/event_recap.py` (R2, not R1) via a new synthesis-projection-only correction
    (`_publisher_suffix_numbers()`/extended `_synthesis_verified_facts()`) - the raw, forensic
    candidate is completely unchanged; only the LLM-facing evidence view excludes numbers proven
    (by direct execution) to occur ONLY inside a publisher suffix.
  - Nvidia stock Story (0d7e1ee3...) - editorially ordinary insider-stock-purchase-disclosure
    content ("...CEO...Just Bought $10 Million of His Own Stock"), not a NINJA PULSE event; slipped
    through R2.6a's finance filter (no marker for this specific finance-content shape) and was
    classified MINIMAL_EDGE. Fixed: `_FINANCE_ADVICE_MARKERS` extended with "own stock"/"bought
    shares"/"stock purchase"/"insider buying" (calibrated against this real title, verified offline
    to not false-positive on "in stock" inventory-availability headlines). The SAME title's English
    Title-Case headline also produced generic non-entity phrases ("chip company just bought", "his
    own stock", "million") via `services.story_memory._extract_entities()`'s own capitalized-run
    heuristic (proven by direct execution, NOT publisher-suffix contamination - `services/story_
    memory.py` is R1/frozen and was NOT touched) - fixed the same way as the numeric case, via a
    new `_is_generic_entity_phrase()` synthesis-projection filter in `services/event_recap.py`.
  - This script's own `_evidence_shape_reason()`/`_quality_preflight()` D/E dimensions now read the
    SYNTHESIS-PROJECTED facts (`_synthesis_verified_facts()`, imported directly from
    services.event_recap) rather than the raw forensic `candidate.verified_facts` - so a Story whose
    only numeric/entity signal turns out to be projection-filtered noise is no longer misreported as
    "numeric-heavy"/D=PASS (spec item 10's own "truthful evidence shape" requirement).
  - `_evidence_hygiene_findings()` extended (spec item 15) to flag STRUCTURAL semantic contamination
    - a raw fact that the projection removes for being publisher-derived-numeric or a generic-entity
    -phrase - explicitly NEVER flagging an ordinary single-source entity/fact as "contamination" on
    its own (spec item 15's own "do NOT label all single-source facts as garbage").
  - `render_story()`'s aggregate now separately counts Stories rejected because the declared
    `first_event_id` was not among confirmed members ("anchor_missing_fail") vs genuine Story
    Integrity Gate FAILs ("story_integrity_gate_fail") - spec item 13's own explicit request to
    quantify how many editorially-attractive Stories are lost to the anchor-integrity fail-closed
    path specifically.
  - The SHORTLIST report section now prints raw vs synthesis-projected verified facts side by side,
    plus the full `render_event_recap_bundle_text()` evidence preview, for every shortlisted Story
    (spec item 14) - proving the projection never mutates the forensic candidate.

Phase R2.6c correction (real production R2.6b rescan - pool_inspected=60, integrity_pass=26,
structurally_usable=26, quality_verdicts={'FAIL': 26}, shortlist_size=0 - a diagnostic-POLICY bug,
not evidence of zero usable Stories): R2.6b's own `_evidence_hygiene_findings()` fed BOTH the
forbidden-vocabulary/independence-language scan of the actual rendered `bundle_text` (a legitimate
"is this still present in what the LLM would see" check) AND `_semantic_contamination_findings()`'s
raw-vs-projected DIFF (i.e. exactly what the R2.6b synthesis projection already safely removed) into
ONE combined list that then failed `C_evidence_cleanliness`/`H_publisher_noise_exposure` for ANY
raw contamination - even contamination the projection had already excluded from the LLM-facing view.
Yakutia (a genuine NEWS_EVENT, Story Integrity PASS) was rejected purely because its RAW candidate
still (correctly, by design - the forensic record is never mutated) contains the publisher-derived
"24" - even though `render_event_recap_bundle_text()`'s actual output never shows it.

Fixed by explicitly separating two quality surfaces (spec items 3/4/6), never conflated again:
  - RAW_FORENSIC quality (`_semantic_contamination_findings()`, unchanged from R2.6b) - informational
    only, printed for debugging, NEVER blocks shortlist eligibility by itself.
  - SYNTHESIS_INPUT quality (new `_synthesis_input_findings()`) - the actual paid-shadow eligibility
    gate. Per spec item 6's own explicit "do not infer projected cleanliness only from helper intent
    - actually inspect the rendered synthesis-facing content deterministically": this function does
    NOT trust that `_synthesis_verified_facts()` successfully removed something just because it
    isn't in the projected fact list - it re-scans the ACTUAL rendered `bundle_text`'s own
    FACT-BEARING sections (`_fact_bearing_synthesis_text()` - the VERIFIED FACTS section body plus
    each announcement's own `numbers=`/`entities=` fields, deliberately EXCLUDING the TIMELINE
    section's headline-display labels, which legitimately echo each announcement's real, raw title
    text and are not themselves a factual claim - see tests/test_event_recap.py's own R2.6b
    test-fix precedent for why that exclusion is necessary and correct) for each RAW-forensic
    contamination value. Only a value PROVEN still present there becomes a synthesis-input finding
    (`still-present-in-rendered-synthesis:<raw-finding>`) - a hard FAIL. A value proven absent is
    safely projected away and never blocks eligibility. The forbidden-vocabulary/independence-
    language scan (unchanged from R2.5/R2.6a) still runs directly against the full rendered
    `bundle_text`, since those ARE genuine "is it in the actual LLM-facing output" checks already.
    `_quality_preflight()`'s C/H dimensions now key off `synthesis_input_findings`, never the raw
    findings - I_editorial_relevance (research-abstract/finance-advice/neutral-relevance rejection)
    remains a completely independent, unrelated gate (spec item 9 - Nvidia stays rejected regardless
    of synthesis cleanliness).
  - `render_story()`'s report block and the returned per-Story record now show BOTH surfaces
    explicitly (`raw_forensic_findings`/`raw_forensic_quality` vs `synthesis_input_findings`/
    `synthesis_input_quality`) - raw visibility is never removed (spec item 7).
  - New `ANCHOR_MISSING_EDITORIAL_FORENSIC` report section (spec item 11) - for every Story rejected
    at the anchor-missing fail-closed path, forensically (read-only, zero mutation, no replacement
    logic) reports: editorial relevance classification, confirmed member count, whether the declared
    `first_event_id` exists in the DB at all, which OTHER Story (if any) it is actually linked to via
    `NewsEventStoryLink`, and a "plausible replacement anchor" (the earliest confirmed member event)
    shown for visibility only, never applied. New aggregate counters (spec item 12) quantify how many
    anchor-missing Stories are CORE / genuinely ADJACENT / neutral-default / research-abstract-like /
    finance-like - answering whether anchor integrity is materially blocking real NINJA PULSE events.
    `services/recap_event.py`'s own `first_event_id` contract, Story Integrity thresholds, and
    announcement identity are untouched - this is read-only forensic reporting only.

Safety pattern identical to every prior production-facing RECAP script this session: SET
TRANSACTION READ ONLY + SHOW transaction_read_only verification, SET LOCAL statement_timeout, one
transaction, rollback in finally, no writes, no network, no LLM, no Telegram, no worker.

Use: `docker compose run --rm --no-deps backend python scripts/_recap_r2_6_broader_shadow_candidate_selection.py`
NOT executed by the author of this script - no VPS/production DB access this session.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio  # noqa: E402
from collections import Counter  # noqa: E402

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from core.config import settings  # noqa: E402
from database.models.news_event import NewsEvent  # noqa: E402
from database.models.story import Story  # noqa: E402
from database.models.story_link import NewsEventStoryLink  # noqa: E402
from services.event_recap import (  # noqa: E402
    FACT_MULTI_SOURCE_CONFIRMED,
    EventRecapCandidate,
    VerifiedFactCandidate,
    _is_generic_entity_phrase,
    _synthesis_verified_facts,
    build_event_recap_candidate,
    render_event_recap_bundle_text,
)
from services.news_editorial_relevance import (  # noqa: E402
    ADJACENT,
    CORE,
    EditorialRelevanceDecision,
    classify_editorial_relevance,
)

OUTPUT_PATH = Path("/tmp/recap_r2_6_broader_shadow_candidate_selection.txt")
STATEMENT_TIMEOUT_MS = 30_000

# Bounded sample-selection strategy - same shape as scripts/_recap_r1_4_production_replay.py's own
# (SCAN_LIMIT/event-count floors/boilerplate+duplicate-title filtering), reused, never reinvented.
SCAN_LIMIT = 500
INSPECT_LIMIT = 60  # how many Stories to run full Story Integrity + candidate classification against
TARGET_SHORTLIST = 5
PRIMARY_EVENT_COUNT_FLOOR = 3
FALLBACK_EVENT_COUNT_FLOOR = 2
MIN_USABLE_AT_PRIMARY_FLOOR = 5

_BOILERPLATE_TITLE_MARKERS = ("content cycle test event", "test event", "test source", "test story")

EXCLUDED_STORY_IDS: frozenset[UUID] = frozenset({
    UUID("859ffea0-9b54-41cb-be25-13c061ca75ad"),  # Taiwan - proven frozen fail-closed case (item 5)
    UUID("60be3f72-28d3-4c5a-af65-f0550923fe94"),  # Sverdlovsk - CLOSED after R2.3/R2.4/R2.5 paid
                                                    # validation runs; must never be re-selected for
                                                    # broader-transfer testing (R2.6a spec item 5/H).
})

# The exact forbidden-term list Phase R2.5 established for the same purpose in
# services/event_recap.py::_INTERNAL_VOCABULARY_TERMS - reused verbatim here for the hygiene scan
# (never reimplemented independently, never expanded).
_FORBIDDEN_EVIDENCE_TERMS = (
    "SINGLE_SOURCE_ONLY", "MULTI_SOURCE_CONFIRMED", "[entity]", "[numeric]",
    "bundle", "evidence bundle", "candidate",
)
_ACCEPTABLE_RELEVANCE_TIERS = frozenset({CORE, ADJACENT})

# services/news_editorial_relevance.py's own literal reason string for its "no keyword evidence at
# all" fallback branch (that module's final `return`, ADJACENT tier reused as a neutral default,
# rank_adjustment=0) - confirmed by reading that file, not modified. A stricter diagnostic-only
# shortlist gate needs to tell this apart from a GENUINE adjacency keyword hit (same tier, but
# reason="adjacent tech-relevant subject signal ...", rank_adjustment=3). If this exact string ever
# changes in that module, `test_recap_r2_6_shortlist_policy.py::
# test_relevance_neutral_default_reason_string_matches_production` will fail loudly rather than
# silently letting the neutral-default leak back through.
_NEUTRAL_DEFAULT_RELEVANCE_REASON = "no editorial-relevance keyword evidence - neutral default"

# R2.6a item 6 - conservative, diagnostic-only NEWS_EVENT vs RESEARCH_ABSTRACT/PAPER-LIKE-CONTENT
# heuristic. No LLM, no embeddings, no giant blacklist. Calibrated against the two REAL production
# titles the R2.6a checkpoint reported as false positives in the prior shortlist:
#   "Diffusion models have recently shown strong potential for multivariate time-series anomaly
#    detection..."
#   "On-policy distillation (OPD) offers a promising way..."
# Deliberately narrow and specific - a generic word like "aims to" or "framework" alone is NOT used
# as a trigger, since real product headlines can plausibly contain such words too (false negatives
# are acceptable here; false positives that reject a genuine NINJA PULSE headline are not).
_RESEARCH_ABSTRACT_OPENER_RE = re.compile(
    r"^(this (study|paper|work|article)\b|we (propose|present|introduce|demonstrate)\b|"
    r"in this (paper|work|study)\b)",
    re.IGNORECASE,
)
_RESEARCH_ABSTRACT_PHRASE_MARKERS: tuple[str, ...] = (
    "remains challenging", "remains an open problem", "we demonstrate that", "we show that",
    "experimental results show", "state-of-the-art performance", "benchmark dataset",
    "novel framework", "have recently shown strong potential", "offers a promising way",
    "shows strong potential for", "propose a novel", "proposed method achieves",
)


def _is_research_abstract_like(title: str) -> bool:
    stripped = title.strip()
    lowered = stripped.lower()
    if _RESEARCH_ABSTRACT_OPENER_RE.search(lowered):
        return True
    marker_hits = sum(1 for marker in _RESEARCH_ABSTRACT_PHRASE_MARKERS if marker in lowered)
    if marker_hits >= 1:
        return True
    return bool(stripped.endswith("...") and len(stripped) > 100)


# R2.6a item 7 - diagnostic-only, additive to (never a duplicate of) services/news_editorial_
# relevance.py's own real, untouched `_PERIPHERAL_PHRASES` (confirmed by reading that module: it
# has no "billionaire"/"net worth"/"should you buy" style investment-advice/wealth-story phrases at
# all - a genuine gap for THIS shortlist's stricter purpose, not a duplicate of existing coverage).
#
# R2.6b item 6 addition (real production finding - a real Story, "The CEO of This Nvidia-Backed
# Artificial Intelligence (AI) Chip Company Just Bought $10 Million of His Own Stock.", passed the
# R2.6a version of this filter and was classified MINIMAL_EDGE despite being ordinary insider-
# stock-purchase-disclosure content, ubiquitous in finance blogs, not a NINJA PULSE event). None of
# the R2.6a markers matched this shape (they targeted "should-you-buy" ADVICE framing and
# billionaire/net-worth framing, not insider-purchase-DISCLOSURE framing) - a genuinely distinct
# finance-content shape, so new markers are added rather than reused. "own stock"/"bought shares"/
# "stock purchase"/"insider buying" are high-precision: real product/feature/launch headlines do
# not use this phrasing (verified offline against a real-shaped false-positive check - e.g. "Nvidia
# RTX 5090 GPU back in stock at major retailers" does not match "own stock", "in stock" alone is
# never a marker here precisely to avoid that false positive).
_FINANCE_ADVICE_MARKERS: tuple[str, ...] = (
    "should you buy", "is it a buy", "buy or sell", "stocks to buy", "top stocks",
    "billionaire", "net worth", "richest person", "richest man", "richest woman",
    "best stocks", "stock pick", "price target",
    "own stock", "bought shares", "buys shares", "stock purchase", "insider buying",
)


def _is_finance_advice_like(title: str) -> bool:
    lowered = title.lower()
    return any(marker in lowered for marker in _FINANCE_ADVICE_MARKERS)


# R2.6a spec item 15/H - the five Stories the (rejected) prior R2.6 shortlist selected, for the
# live "PRIOR R2.6a SHORTLIST DISPOSITION" report section. Purely narrative/reporting - this dict
# never affects selection or scoring; disposition is always evaluated live against whatever the
# current scan actually finds for these IDs (or reports them absent if the pool no longer contains
# them), never hardcoded as a verdict.
_PRIOR_R2_6_CANDIDATE_NOTES: dict[UUID, str] = {
    UUID("2a39731e-06ea-4caa-8b91-e6e2fc6d1641"): "Yakutia AI cluster - GOOD candidate, best real Story so far",
    UUID("60be3f72-28d3-4c5a-af65-f0550923fe94"): "Sverdlovsk - CLOSED, must never be re-selected",
    UUID("a98a5e34-5dfa-47e6-9688-e1ca6d22b67b"): "diffusion-model anomaly-detection abstract",
    UUID("d8a1bc1d-3654-41af-8345-efa827d37a5b"): "AI algorithms book preorder - weak minimal edge case",
    UUID("80e4b284-df69-4975-9ad3-a6f2d4d8d476"): "on-policy distillation (OPD) abstract",
    UUID("0d7e1ee3-b5ae-4b75-8498-77ce36e91385"): "Nvidia-backed AI chip CEO stock purchase - ordinary "
                                                  "finance/investment content, R2.6b finance-filter miss",
}


def _relevance_accepted(relevance: EditorialRelevanceDecision) -> bool:
    """Stricter than the old blanket `tier in {CORE, ADJACENT}` check (R2.6a root-cause fix) -
    ADJACENT is only accepted when it reflects a genuine keyword-based adjacency hit, never the
    tiering module's own "no keyword evidence, neutral default" fallback branch."""
    if relevance.tier == CORE:
        return True
    if relevance.tier == ADJACENT:
        return relevance.reason != _NEUTRAL_DEFAULT_RELEVANCE_REASON
    return False


class ReadOnlyGuardError(RuntimeError):
    """Raised if the read-only transaction guard cannot be verified - the script refuses to run
    any query in that case."""


async def _verify_read_only(conn: AsyncConnection) -> None:
    await conn.execute(text("SET TRANSACTION READ ONLY"))
    result = await conn.execute(text("SHOW transaction_read_only"))
    value = str(result.scalar()).strip().lower()
    if value != "on":
        raise ReadOnlyGuardError(f"transaction_read_only={value!r}, expected 'on' - refusing to run")
    await conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}'"))


def _is_boilerplate_title(title: str) -> bool:
    lowered = title.lower()
    return any(marker in lowered for marker in _BOILERPLATE_TITLE_MARKERS)


async def _scan_candidates(session: AsyncSession, event_count_floor: int) -> list[Story]:
    stmt = (
        select(Story)
        .where(Story.event_count >= event_count_floor)
        .order_by(Story.updated_at.desc())
        .limit(SCAN_LIMIT)
    )
    scanned = list((await session.execute(stmt)).scalars().all())
    seen_titles: set[str] = set()
    usable: list[Story] = []
    for story in scanned:
        if story.id in EXCLUDED_STORY_IDS:
            continue
        if _is_boilerplate_title(story.title):
            continue
        if story.title in seen_titles:
            continue
        seen_titles.add(story.title)
        usable.append(story)
    return usable


async def select_pool(session: AsyncSession) -> list[Story]:
    usable = await _scan_candidates(session, PRIMARY_EVENT_COUNT_FLOOR)
    if len(usable) < MIN_USABLE_AT_PRIMARY_FLOOR:
        fallback = await _scan_candidates(session, FALLBACK_EVENT_COUNT_FLOOR)
        seen_ids = {s.id for s in usable}
        usable = usable + [s for s in fallback if s.id not in seen_ids]
    return usable[:INSPECT_LIMIT]


def _projected_facts(candidate: EventRecapCandidate) -> list[VerifiedFactCandidate]:
    """The exact synthesis-facing projection `render_event_recap_bundle_text()` itself uses
    (`services.event_recap._synthesis_verified_facts()`, imported directly, never reimplemented) -
    the single source of truth this script uses everywhere it needs to distinguish "what the raw
    forensic candidate recorded" from "what the LLM would actually be shown" (spec R2.6b item 14)."""
    return _synthesis_verified_facts(candidate.verified_facts, candidate.announcements)


def _semantic_contamination_findings(candidate: EventRecapCandidate, projected: list[VerifiedFactCandidate]) -> list[str]:
    """R2.6b item 15 - detects STRUCTURAL semantic contamination a raw-vs-projected diff reveals:
    a numeric fact removed for being publisher-suffix-derived only, or an entity fact removed for
    being a generic pronoun/modifier/magnitude phrase (`_is_generic_entity_phrase()`, imported
    directly from services.event_recap, never reimplemented). Deliberately does NOT flag an
    ordinary single-source entity token removal (R2.4's own, already-accepted projection behavior)
    - spec item 15's own explicit "do NOT label all single-source facts as garbage," so only the
    TWO new R2.6b contamination classes are ever reported here."""
    projected_values = {fact.value for fact in projected}
    findings: list[str] = []
    for fact in candidate.verified_facts:
        if fact.value in projected_values:
            continue
        if fact.fact_type == "numeric":
            findings.append(f"publisher-derived-numeric:{fact.value}")
        elif fact.fact_type == "entity" and _is_generic_entity_phrase(fact.value):
            findings.append(f"generic-entity-phrase:{fact.value}")
    return findings


def _fact_bearing_synthesis_text(bundle_text: str) -> str:
    """R2.6c item 6 - extracts exactly the FACT-BEARING content of a rendered synthesis bundle: the
    VERIFIED FACTS section body, plus every announcement's own `numbers=`/`entities=` field values.
    Deliberately EXCLUDES the TIMELINE section's own headline-display labels, which legitimately
    echo each announcement's real, raw title text (proven necessary and correct by tests/
    test_event_recap.py's own R2.6b test-fix precedent - a raw headline ending " - RuNews24" is
    expected, harmless display text, not a factual claim about a verified number)."""
    if "VERIFIED FACTS" not in bundle_text:
        return ""
    after_facts = bundle_text.split("VERIFIED FACTS", 1)[1]
    facts_section, _, announcements_section = after_facts.partition("ANNOUNCEMENTS (detail):")
    field_values: list[str] = []
    for line in announcements_section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- #"):
            continue
        if "numbers=" in stripped:
            field_values.append(stripped.split("numbers=", 1)[1].split("|", 1)[0])
        if "entities=" in stripped:
            field_values.append(stripped.split("entities=", 1)[1].split("|", 1)[0])
    return facts_section + " " + " ".join(field_values)


def _synthesis_input_findings(bundle_text: str, raw_forensic_findings: list[str]) -> list[str]:
    """R2.6c item 6 - the FINAL, authoritative source of truth for paid-shadow eligibility. Two
    independent checks against the ACTUAL rendered `bundle_text` (never inferred from helper intent
    alone, per spec's own explicit instruction):
    1. the exact forbidden-vocabulary/independence-language scan Phase R2.5/R2.6a already proved
       necessary - these already check the real rendered output directly, unchanged here.
    2. for each RAW-forensic contamination finding (`_semantic_contamination_findings()` - what the
       R2 synthesis projection is SUPPOSED to have removed), actually re-scans the fact-bearing
       portion of the rendered bundle (`_fact_bearing_synthesis_text()`) to PROVE the contaminated
       value is genuinely absent - only a value found STILL PRESENT there becomes a hard synthesis-
       input finding (`still-present-in-rendered-synthesis:<finding>`). A raw finding whose value is
       proven absent from the actual rendering is safely projected away and never appears here -
       this is the R2.6c fix: raw contamination the projection already removed must not block
       shortlist eligibility."""
    findings = [term for term in _FORBIDDEN_EVIDENCE_TERMS if term in bundle_text]
    lowered = bundle_text.lower()
    if "independent" in lowered or "независим" in lowered:
        findings.append("independence-language")

    fact_text = _fact_bearing_synthesis_text(bundle_text)
    for finding in raw_forensic_findings:
        _, _, value = finding.partition(":")
        if value and value in fact_text:
            findings.append(f"still-present-in-rendered-synthesis:{finding}")
    return findings


def _evidence_shape_reason(candidate: EventRecapCandidate, projected: list[VerifiedFactCandidate]) -> str:
    """Deterministic, evidence-derived category (spec item 10's own explicit "use evidence, not
    arbitrary labels") - never an arbitrary human label. R2.6b: reads the SYNTHESIS-PROJECTED facts
    (spec item 10's own "truthful evidence shape" requirement - e.g. Yakutia's only numeric fact was
    publisher-suffix noise; after projection it correctly reads as having zero numeric facts, never
    "numeric-heavy")."""
    numeric_facts = [f for f in projected if f.fact_type == "numeric"]
    multi_source_entities = [
        f for f in projected if f.fact_type == "entity" and f.status == FACT_MULTI_SOURCE_CONFIRMED
    ]
    if candidate.announcement_count == 1:
        return "minimal (single announcement)"
    if numeric_facts:
        return f"numeric-heavy ({len(numeric_facts)} meaningful number(s))"
    if candidate.evidence_reference_count >= 3:
        return f"multi-source-reference ({candidate.evidence_reference_count} distinct evidence references)"
    if multi_source_entities:
        return f"entity-heavy ({len(multi_source_entities)} multi-source entit(y/ies))"
    if candidate.announcement_count >= 3:
        return f"timeline-rich ({candidate.announcement_count} announcements)"
    return "product/update (general)"


def _quality_preflight(
    candidate: EventRecapCandidate, projected: list[VerifiedFactCandidate], synthesis_input_findings: list[str],
    relevance: EditorialRelevanceDecision, *, is_research_abstract: bool, is_finance_advice: bool,
) -> tuple[str, dict[str, str]]:
    """Deterministic PASS/PARTIAL/FAIL classification across the 9 dimensions spec item 13 lists.
    A dimension is only ever a hard FAIL for genuinely disqualifying conditions (Story Integrity
    already gates separately/harder upstream, item 8 - a Story reaching this function has already
    passed it); everything else is PASS/PARTIAL informational. I_editorial_relevance (R2.6a) uses
    `_relevance_accepted()` - a genuine ADJACENT keyword hit passes, the tiering module's own
    "neutral default" fallback does not - and also FAILs on the research-abstract/finance-advice
    diagnostic-only detectors, since neither is a valid NINJA PULSE newsroom event regardless of
    what tier the production classifier happened to assign - this remains a completely independent
    gate from evidence cleanliness (R2.6c spec item 9 - Nvidia stays rejected even with clean
    synthesis evidence). D/E (R2.6b) read the SYNTHESIS-PROJECTED facts, not the raw forensic set -
    a Story whose only numeric/entity signal is projection-filtered noise correctly reads as
    PARTIAL, never a false PASS (spec item 10). C/H (R2.6c fix) key off `synthesis_input_findings`
    - the ACTUAL rendered synthesis-facing content - never the raw forensic findings; raw
    contamination the R2 projection already safely removed from the rendered evidence must not
    fail these dimensions (spec items 2/4 - Yakutia's raw "24" no longer fails C/H once proven
    absent from the actual rendered bundle)."""
    dims: dict[str, str] = {}
    dims["A_story_coherence"] = "PASS"  # Story Integrity already passed to reach here (item 8)
    dims["B_announcement_usefulness"] = "PASS" if candidate.announcement_count >= 2 else "PARTIAL"
    dims["C_evidence_cleanliness"] = "FAIL" if synthesis_input_findings else "PASS"
    numeric_facts = [f for f in projected if f.fact_type == "numeric"]
    dims["D_numeric_fact_quality"] = "PASS" if numeric_facts else "PARTIAL"
    multi_source_entities = [
        f for f in projected if f.fact_type == "entity" and f.status == FACT_MULTI_SOURCE_CONFIRMED
    ]
    dims["E_entity_quality"] = "PASS" if multi_source_entities else "PARTIAL"
    dims["F_source_reference_clarity"] = "PASS" if candidate.evidence_reference_count >= 2 else "PARTIAL"
    dims["G_timeline_usefulness"] = "PASS" if len(candidate.timeline) == candidate.announcement_count and candidate.timeline else "PARTIAL"
    dims["H_publisher_noise_exposure"] = "FAIL" if synthesis_input_findings else "PASS"
    dims["I_editorial_relevance"] = (
        "FAIL" if (is_research_abstract or is_finance_advice or not _relevance_accepted(relevance)) else "PASS"
    )

    if any(v == "FAIL" for v in dims.values()):
        overall = "FAIL"
    elif any(v == "PARTIAL" for v in dims.values()):
        overall = "PARTIAL"
    else:
        overall = "PASS"
    return overall, dims


async def _anchor_missing_forensic(session: AsyncSession, story: Story, confirmed_events: list[NewsEvent]) -> dict:
    """R2.6c item 11 - forensic-only visibility into WHY the anchor-missing fail-closed path fires
    so often (17/60 in the real R2.6b scan). READ ONLY: does not mutate anything, does not propose
    or apply a replacement anchor (spec's own explicit "No replacement logic yet" / "DO NOT mutate
    anything") - `plausible_replacement_anchor_id` is reported for human visibility only."""
    relevance = classify_editorial_relevance(story.title)
    is_research_abstract = _is_research_abstract_like(story.title)
    is_finance_advice = _is_finance_advice_like(story.title)

    declared_id = story.first_event_id
    declared_exists = False
    belongs_to_other_story_ids: list[UUID] = []
    if declared_id is not None:
        exists_stmt = select(NewsEvent.id).where(NewsEvent.id == declared_id)
        declared_exists = (await session.execute(exists_stmt)).scalar_one_or_none() is not None
        if declared_exists:
            links_stmt = select(NewsEventStoryLink.story_id).where(NewsEventStoryLink.news_event_id == declared_id)
            linked_story_ids = list((await session.execute(links_stmt)).scalars().all())
            belongs_to_other_story_ids = [sid for sid in linked_story_ids if sid != story.id]

    plausible_replacement_anchor_id = None
    if confirmed_events:
        earliest = min(confirmed_events, key=lambda e: e.published_at or e.collected_at)
        plausible_replacement_anchor_id = earliest.id

    return {
        "story_id": story.id, "title": story.title, "relevance": relevance,
        "is_research_abstract": is_research_abstract, "is_finance_advice": is_finance_advice,
        "confirmed_member_count": len(confirmed_events),
        "declared_first_event_id": declared_id, "declared_first_event_exists": declared_exists,
        "belongs_to_other_story_ids": belongs_to_other_story_ids,
        "plausible_replacement_anchor_id": plausible_replacement_anchor_id,
    }


def _tally_anchor_missing_category(aggregate: dict, forensic: dict) -> None:
    """R2.6c item 12 - quantifies whether anchor integrity is materially blocking real NINJA PULSE
    events or mostly garbage. The three relevance buckets (CORE/genuine-ADJACENT/neutral-default)
    are mutually exclusive; research-abstract-like/finance-like are independent, orthogonal flags
    (a Story can be both, e.g. a finance-advice piece that also opens with academic-abstract prose)."""
    relevance = forensic["relevance"]
    if relevance.tier == CORE:
        aggregate["anchor_missing_CORE"] += 1
    elif relevance.tier == ADJACENT and relevance.reason != _NEUTRAL_DEFAULT_RELEVANCE_REASON:
        aggregate["anchor_missing_genuine_adjacent"] += 1
    elif relevance.tier == ADJACENT:
        aggregate["anchor_missing_neutral_default"] += 1
    if forensic["is_research_abstract"]:
        aggregate["anchor_missing_research_abstract_like"] += 1
    if forensic["is_finance_advice"]:
        aggregate["anchor_missing_finance_like"] += 1


async def render_story(
    session: AsyncSession, story: Story, aggregate: dict, anchor_missing_forensics: list[dict],
) -> tuple[list[str], dict | None]:
    from services.recap_event import evaluate_recap_story_integrity, load_story_events

    lines = [f"Story {story.id}: {story.title!r}"]
    events = await load_story_events(session, story.id)
    anchor = next((e for e in events if e.id == story.first_event_id), None)
    if anchor is None:
        lines.append("  SKIPPED - declared first_event_id not among confirmed member events (fail-closed)")
        lines.append("")
        # R2.6b item 13 - counted separately from a genuine Story Integrity Gate FAIL below, so the
        # final report can quantify how many editorially-attractive Stories are lost specifically to
        # the anchor-integrity fail-closed path (never bypassed either way - both are hard rejects).
        aggregate["anchor_missing_fail"] += 1
        aggregate["integrity_fail"] += 1
        forensic = await _anchor_missing_forensic(session, story, events)
        anchor_missing_forensics.append(forensic)
        _tally_anchor_missing_category(aggregate, forensic)
        return lines, None

    integrity = evaluate_recap_story_integrity(anchor, events)
    if not integrity.eligible:
        lines.append(f"  Story Integrity: FAIL - {integrity.reasons}")
        lines.append("")
        aggregate["story_integrity_gate_fail"] += 1
        aggregate["integrity_fail"] += 1
        return lines, None
    aggregate["integrity_pass"] += 1
    lines.append("  Story Integrity: PASS")

    relevance = classify_editorial_relevance(story.title)
    is_research_abstract = _is_research_abstract_like(story.title)
    is_finance_advice = _is_finance_advice_like(story.title)
    relevance_accepted = _relevance_accepted(relevance)
    lines.append(
        f"  editorial_relevance_tier={relevance.tier} reason={relevance.reason!r} "
        f"relevance_accepted={relevance_accepted}"
    )
    lines.append(f"  is_research_abstract_like={is_research_abstract} is_finance_advice_like={is_finance_advice}")

    result = await build_event_recap_candidate(session, story, force_shadow=True)
    if result.rejected or result.candidate is None:
        lines.append(f"  SKIPPED post-integrity - {result.rejection_reasons}")
        lines.append("")
        return lines, None

    candidate = result.candidate
    original_ready = not candidate.readiness_overridden
    bundle_text = render_event_recap_bundle_text(candidate)
    projected = _projected_facts(candidate)
    # R2.6c: two DISTINCT quality surfaces (spec items 3/4) - raw_forensic_findings is informational
    # only (never blocks eligibility), synthesis_input_findings is the actual paid-shadow gate,
    # verified against the REAL rendered bundle_text, never inferred from projection intent alone.
    raw_forensic_findings = _semantic_contamination_findings(candidate, projected)
    synthesis_input_findings = _synthesis_input_findings(bundle_text, raw_forensic_findings)
    raw_forensic_quality = "DIAGNOSTIC_WARNING" if raw_forensic_findings else "CLEAN"
    synthesis_input_quality = "FAIL" if synthesis_input_findings else "PASS"
    quality_verdict, quality_dims = _quality_preflight(
        candidate, projected, synthesis_input_findings, relevance,
        is_research_abstract=is_research_abstract, is_finance_advice=is_finance_advice,
    )

    if is_research_abstract:
        editorial_event_class = "RESEARCH_ABSTRACT_REJECTED"
    elif is_finance_advice:
        editorial_event_class = "FINANCE_ADVICE_REJECTED"
    elif not relevance_accepted:
        editorial_event_class = "RELEVANCE_NEUTRAL_REJECTED"
    elif candidate.announcement_count == 1:
        editorial_event_class = "MINIMAL_EDGE"
    else:
        editorial_event_class = "NEWS_EVENT"

    shortlist_eligible = (
        quality_verdict != "FAIL"
        and relevance_accepted
        and not is_research_abstract
        and not is_finance_advice
    )

    numeric_facts = [f for f in candidate.verified_facts if f.fact_type == "numeric"]
    entity_facts = [f for f in candidate.verified_facts if f.fact_type == "entity"]
    image_count = sum(1 for m in candidate.media_candidates if m.kind == "image")
    video_count = sum(1 for m in candidate.media_candidates if m.kind == "video")

    lines += [
        f"  anchor_event_id={candidate.anchor_event_id}",
        f"  editorial_event_class={editorial_event_class} shortlist_eligible={shortlist_eligible}",
        f"  readiness_state={candidate.readiness_state} original_ready={original_ready} (readiness_overridden={candidate.readiness_overridden})",
        f"  announcement_count={candidate.announcement_count} readiness_source_count={candidate.readiness_source_count} "
        f"evidence_reference_count={candidate.evidence_reference_count} source_refs_count={len(candidate.source_refs)}",
        f"  timeline_count={len(candidate.timeline)}",
        f"  verified_facts: numeric={len(numeric_facts)} entity={len(entity_facts)} "
        f"(multi_source_entities={sum(1 for f in entity_facts if f.status == FACT_MULTI_SOURCE_CONFIRMED)})",
        f"  media_candidates: image={image_count} video={video_count}",
        f"  raw_forensic_findings={raw_forensic_findings or 'none'}  raw_forensic_quality={raw_forensic_quality}",
        f"  synthesis_input_findings={synthesis_input_findings or 'none'}  synthesis_input_quality={synthesis_input_quality}",
        f"  quality_preflight: {quality_verdict}  dims={quality_dims}",
        f"  evidence_shape_reason={_evidence_shape_reason(candidate, projected)!r}",
        "",
    ]

    return lines, {
        "story": story, "candidate": candidate, "relevance": relevance,
        "quality_verdict": quality_verdict, "quality_dims": quality_dims,
        "raw_forensic_findings": raw_forensic_findings, "raw_forensic_quality": raw_forensic_quality,
        "synthesis_input_findings": synthesis_input_findings, "synthesis_input_quality": synthesis_input_quality,
        "bundle_text": bundle_text, "projected": projected,
        "original_ready": original_ready, "is_research_abstract": is_research_abstract,
        "is_finance_advice": is_finance_advice, "relevance_accepted": relevance_accepted,
        "editorial_event_class": editorial_event_class, "shortlist_eligible": shortlist_eligible,
    }


def _select_shortlist(usable: list[dict]) -> list[dict]:
    """Diversity-aware shortlist (spec item 10), R2.6a-corrected: only `shortlist_eligible` Stories
    (Story Integrity PASS upstream, quality_preflight != FAIL, genuine relevance, not a research
    abstract, not finance-advice content) are ever considered; at most ONE MINIMAL_EDGE
    (single-announcement) Story is ever included (spec item 9), and the shortlist is capped at
    TARGET_SHORTLIST but never padded beyond how many Stories genuinely qualify - "quality over
    quota" (spec item 10), so this can legitimately return fewer than TARGET_SHORTLIST."""
    eligible = [u for u in usable if u["shortlist_eligible"]]
    eligible.sort(key=lambda u: (u["quality_verdict"] != "PASS", -u["candidate"].announcement_count))

    shortlist: list[dict] = []
    seen_shapes: set[str] = set()
    minimal_edge_used = False

    def _take(u: dict) -> None:
        nonlocal minimal_edge_used
        shortlist.append(u)
        seen_shapes.add(_evidence_shape_reason(u["candidate"], u["projected"]).split(" (")[0])
        if u["editorial_event_class"] == "MINIMAL_EDGE":
            minimal_edge_used = True

    for u in eligible:
        if u["editorial_event_class"] == "MINIMAL_EDGE" and minimal_edge_used:
            continue
        shape = _evidence_shape_reason(u["candidate"], u["projected"]).split(" (")[0]
        if shape in seen_shapes and len(shortlist) < TARGET_SHORTLIST:
            continue
        _take(u)
        if len(shortlist) >= TARGET_SHORTLIST:
            break
    if len(shortlist) < TARGET_SHORTLIST:
        for u in eligible:
            if u in shortlist or len(shortlist) >= TARGET_SHORTLIST:
                continue
            if u["editorial_event_class"] == "MINIMAL_EDGE" and minimal_edge_used:
                continue
            _take(u)
    return shortlist


async def main() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await _verify_read_only(conn)
            session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)

            pool = await select_pool(session)
            lines = [
                "NINJA PULSE RECAP Phase R2.6c - broader shadow candidate selection (READ ONLY)",
                f"Story pool inspected: {len(pool)} (bounded sample strategy, event-count floor "
                f"{PRIMARY_EVENT_COUNT_FLOOR}, fallback {FALLBACK_EVENT_COUNT_FLOOR})",
                "",
            ]

            aggregate: dict = {
                "integrity_pass": 0, "integrity_fail": 0,
                "anchor_missing_fail": 0, "story_integrity_gate_fail": 0,
                "anchor_missing_CORE": 0, "anchor_missing_genuine_adjacent": 0,
                "anchor_missing_neutral_default": 0, "anchor_missing_research_abstract_like": 0,
                "anchor_missing_finance_like": 0,
            }
            usable: list[dict] = []
            anchor_missing_forensics: list[dict] = []
            for story in pool:
                block, record = await render_story(session, story, aggregate, anchor_missing_forensics)
                lines += block
                if record is not None:
                    usable.append(record)

            shortlist = _select_shortlist(usable)

            lines += ["=" * 100, "SHORTLIST", "=" * 100]
            for i, u in enumerate(shortlist):
                story, candidate, projected = u["story"], u["candidate"], u["projected"]
                shortname = f"story{i+1}"
                raw_facts_repr = [(f.fact_type, f.value, f.status) for f in candidate.verified_facts]
                projected_facts_repr = [(f.fact_type, f.value, f.status) for f in projected]
                lines += [
                    f"[{shortname}] {story.id} - {story.title!r}",
                    f"  editorial_event_class={u['editorial_event_class']}  "
                    f"reason: {_evidence_shape_reason(candidate, projected)}  "
                    f"quality={u['quality_verdict']}  relevance={u['relevance'].tier}",
                    f"  Story Integrity=PASS  readiness_state={candidate.readiness_state} "
                    f"original_ready={u['original_ready']}",
                    f"  announcement_count={candidate.announcement_count} "
                    f"readiness_source_count={candidate.readiness_source_count} "
                    f"evidence_reference_count={candidate.evidence_reference_count} "
                    f"source_refs_count={len(candidate.source_refs)} timeline_count={len(candidate.timeline)}",
                    f"  raw_forensic_findings={u['raw_forensic_findings'] or 'none'} "
                    f"({u['raw_forensic_quality']})",
                    f"  synthesis_input_findings={u['synthesis_input_findings'] or 'none'} "
                    f"({u['synthesis_input_quality']})",
                    "  --- RAW verified_facts (forensic, unfiltered candidate.verified_facts) ---",
                    f"  {raw_facts_repr}",
                    "  --- PROJECTED verified_facts (synthesis-facing, _synthesis_verified_facts) ---",
                    f"  {projected_facts_repr}",
                    "  (raw vs projected proves projection never mutates the forensic candidate - "
                    "the raw list above is exactly candidate.verified_facts, untouched)",
                    "  --- FULL no-LLM synthesis evidence preview (render_event_recap_bundle_text) ---",
                    u["bundle_text"],
                    "  --- end evidence preview ---",
                    "  future single-attempt command (NOT executed):",
                    "    docker compose run --rm --no-deps \\",
                    "      -v \"$(pwd)/services:/app/services:ro\" -v \"$(pwd)/scripts:/app/scripts:ro\" "
                    "-v \"$(pwd)/prompts:/app/prompts:ro\" -v \"/tmp:/tmp\" \\",
                    "      backend python scripts/_recap_r2_event_shadow.py \\",
                    f"      --story-id {story.id} --force-shadow --with-llm --single-attempt \\",
                    f"      --output /tmp/recap_r2_6_{shortname}_llm.json "
                    f"--evidence-output /tmp/recap_r2_6_{shortname}_evidence.txt",
                    "",
                ]

            lines += ["=" * 100, "PRIOR SHORTLIST DISPOSITION (R2.6 + R2.6a candidates)", "=" * 100]
            usable_by_id = {u["story"].id: u for u in usable}
            shortlist_ids = {u["story"].id for u in shortlist}
            for prior_id, prior_note in _PRIOR_R2_6_CANDIDATE_NOTES.items():
                if prior_id in EXCLUDED_STORY_IDS:
                    disposition = "EXCLUDED (calibration/control Story, hard-excluded this checkpoint)"
                elif prior_id in shortlist_ids:
                    disposition = "RETAINED in new shortlist"
                elif prior_id in usable_by_id:
                    u = usable_by_id[prior_id]
                    disposition = (
                        f"REJECTED - editorial_event_class={u['editorial_event_class']} "
                        f"quality_preflight={u['quality_verdict']} shortlist_eligible={u['shortlist_eligible']}"
                    )
                else:
                    disposition = "not present in this scan's pool (integrity-failed, filtered pre-pool, or outside INSPECT_LIMIT)"
                lines.append(f"  {prior_id} ({prior_note}): {disposition}")
            lines.append("")

            lines += ["=" * 100, "ANCHOR_MISSING_EDITORIAL_FORENSIC", "=" * 100]
            for f in anchor_missing_forensics:
                lines += [
                    f"Story {f['story_id']}: {f['title']!r}",
                    f"  editorial_relevance_tier={f['relevance'].tier} reason={f['relevance'].reason!r}",
                    f"  is_research_abstract_like={f['is_research_abstract']} "
                    f"is_finance_advice_like={f['is_finance_advice']}",
                    f"  confirmed_member_count={f['confirmed_member_count']}",
                    f"  declared_first_event_id={f['declared_first_event_id']} "
                    f"exists_in_db={f['declared_first_event_exists']}",
                    f"  belongs_to_other_story_ids={f['belongs_to_other_story_ids'] or 'none/unknown'}",
                    f"  plausible_replacement_anchor_id={f['plausible_replacement_anchor_id']} "
                    "(forensic visibility only - NOT applied, no replacement logic)",
                    "",
                ]

            lines += [
                "=" * 100, "AGGREGATE", "=" * 100,
                f"pool_inspected={len(pool)}",
                f"integrity_pass={aggregate['integrity_pass']} integrity_fail={aggregate['integrity_fail']}",
                f"  of which anchor_missing_fail={aggregate['anchor_missing_fail']} "
                f"(declared first_event_id not among confirmed members - spec item 13's own "
                f"quantitative request) story_integrity_gate_fail={aggregate['story_integrity_gate_fail']}",
                f"  anchor_missing breakdown: CORE={aggregate['anchor_missing_CORE']} "
                f"genuine_adjacent={aggregate['anchor_missing_genuine_adjacent']} "
                f"neutral_default={aggregate['anchor_missing_neutral_default']} "
                f"research_abstract_like={aggregate['anchor_missing_research_abstract_like']} "
                f"finance_like={aggregate['anchor_missing_finance_like']}",
                f"structurally_usable={len(usable)}",
                f"quality_verdicts={dict(Counter(u['quality_verdict'] for u in usable))}",
                f"shortlist_size={len(shortlist)}",
            ]

            OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
            print(f"Wrote {OUTPUT_PATH} (pool={len(pool)}, shortlist={len(shortlist)})")
        finally:
            await trans.rollback()
            await conn.close()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
