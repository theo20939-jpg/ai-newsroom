"""Phase 20 M6: deterministic Delta Engine - answers "does this new event add reader-worthy
information to an existing Story?", separately from whether it IS the same story (that's
services/story_memory.py's job).

Deliberately deterministic-first, no LLM call (Tier 1/2 only this phase - an optional Tier 3 LLM
adjudication for MEDIUM-confidence ambiguous cases is designed in docs/phase20_story_memory_
calibration_dataset.md's own companion report but NOT implemented here, per the phase's own cost/
model guardrail). Reuses services/fact_safety.py::extract_claims() for number/date detection
(never a second, competing parser) and services/story_memory.py::extract_story_signature() for
keyword-level delta - never invents a third extraction mechanism.

Split into a pure calculator (`classify_delta`, no I/O, fully unit-testable) and one thin async
orchestration function (`compute_story_delta`, the only DB-touching entry point) - mirrors
services/story_memory.py's own established split exactly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import EventCategory, NewsEvent
from database.models.story_link import NewsEventStoryLink
from services.fact_safety import extract_claims
from services.story_memory import extract_story_signature
from services.text_normalization import normalize_loose, symmetric_token_overlap

# --- outcomes ------------------------------------------------------------------------------

NO_NEW_FACTS = "no_new_facts"
CONFIRMATION_ONLY = "confirmation_only"
MINOR_DELTA = "minor_delta"
MATERIAL_UPDATE = "material_update"
UNCERTAIN_DELTA = "uncertain_delta"

# Claim types treated as "reader-worthy new fact" signals when genuinely new (never present in
# any prior title for this story) - a release date, a price, a benchmark percentage, a named
# quantity. "entity"/"quote" are deliberately excluded here: a new entity alone is often just a
# different source's own phrasing (a spokesperson's name, a publication credit), not a material
# development, and quotes are Copywriting's own concern (services/quote_lookup.py), not a delta
# signal - conflating them would over-trigger MATERIAL_UPDATE on wording alone, exactly the
# "different wording is not a new fact" mistake this engine exists to avoid.
# Disclosed limitation, inherited from fact_safety.py's own date pattern (not something this
# engine can or should fix - the plan's own guardrail says reuse the existing extractor, not build
# a second one): a bare "March 15" without a year does not match `_DATE_EXTRACT_PATTERN`, so it
# will not register as a `date` material claim - it still surfaces via the keyword-delta fallback
# below (MINOR_DELTA at worst, never silently NO_NEW_FACTS), so it is degraded, not lost.
_MATERIAL_CLAIM_TYPES: tuple[str, ...] = ("date", "money", "percentage", "metric_quantity")

# Reasoned starting points (same "reasoned default, refine from replay" convention as services/
# story_memory.py's own thresholds) - Phase 20 M11's historical replay is what should calibrate
# these, not a guess made before real data exists.
_NO_NEW_FACTS_TITLE_OVERLAP = 0.85
_CONFIRMATION_ONLY_TITLE_OVERLAP = 0.55
_MINOR_DELTA_MAX_NEW_KEYWORDS = 4


@dataclass(frozen=True)
class DeltaResult:
    classification: str  # NO_NEW_FACTS | CONFIRMATION_ONLY | MINOR_DELTA | MATERIAL_UPDATE | UNCERTAIN_DELTA
    new_material_claims: list[str] = field(default_factory=list)
    new_keywords: list[str] = field(default_factory=list)
    max_title_overlap_vs_prior: float = 0.0
    reason: str = ""


def _normalize_claim(claim: str) -> str:
    return normalize_loose(claim)


def classify_delta(new_title: str, prior_titles: list[str]) -> DeltaResult:
    """Pure. `prior_titles` is every other real title already linked to this Story (order does
    not matter - all are pooled together, never compared pairwise). Empty `prior_titles` is a
    caller error (a story with no prior events isn't a delta question at all - services/
    story_memory.py's NEW_STORY/RELATED_STORY outcomes never reach this function), but this
    function stays defensive rather than raising: returns UNCERTAIN_DELTA."""
    if not prior_titles:
        return DeltaResult(UNCERTAIN_DELTA, reason="no prior titles supplied - nothing to compare against")

    new_claims = extract_claims(new_title)
    new_material_claims = [
        claim for claim_type in _MATERIAL_CLAIM_TYPES for claim in new_claims.get(claim_type, [])
    ]

    prior_material_pool: set[str] = set()
    max_title_overlap = 0.0
    for prior_title in prior_titles:
        prior_claims = extract_claims(prior_title)
        for claim_type in _MATERIAL_CLAIM_TYPES:
            prior_material_pool.update(_normalize_claim(c) for c in prior_claims.get(claim_type, []))
        max_title_overlap = max(max_title_overlap, symmetric_token_overlap(new_title, prior_title))

    return _classify_from_signals(
        new_title=new_title, prior_titles=prior_titles, new_material_claims=new_material_claims,
        prior_material_pool=prior_material_pool, max_title_overlap=max_title_overlap,
    )


def _classify_from_signals(
    *, new_title: str, prior_titles: list[str], new_material_claims: list[str],
    prior_material_pool: set[str], max_title_overlap: float,
) -> DeltaResult:
    genuinely_new_claims = [c for c in new_material_claims if _normalize_claim(c) not in prior_material_pool]

    # Keyword-level delta, computed without a category (this function only ever sees titles, and
    # extract_story_signature's own category parameter is documented as unused by the signature
    # itself - see services/story_memory.py's own docstring) - a real EventCategory is never
    # available here, so a placeholder is required only to satisfy the function's type signature.
    new_keywords_set = set(extract_story_signature(new_title, EventCategory.UNKNOWN).keywords)
    prior_keywords_set: set[str] = set()
    for prior_title in prior_titles:
        prior_keywords_set |= set(extract_story_signature(prior_title, EventCategory.UNKNOWN).keywords)
    new_keywords = sorted(new_keywords_set - prior_keywords_set)

    if genuinely_new_claims:
        reason = f"genuinely new material claim(s) not present in any prior title: {genuinely_new_claims}"
        return DeltaResult(
            MATERIAL_UPDATE, new_material_claims=genuinely_new_claims, new_keywords=new_keywords,
            max_title_overlap_vs_prior=max_title_overlap, reason=reason,
        )

    if max_title_overlap >= _NO_NEW_FACTS_TITLE_OVERLAP and not new_keywords:
        reason = f"near-identical title (overlap={max_title_overlap:.2f}) and no new keywords or claims"
        return DeltaResult(NO_NEW_FACTS, max_title_overlap_vs_prior=max_title_overlap, reason=reason)

    # Phase 20 Checkpoint 4 fix: high title_overlap alone is NOT sufficient for CONFIRMATION_ONLY.
    # A real M11.3 replay suppression-packet case exposed this - two template-driven guide
    # headlines ("X romance walkthrough: All the best gifts for the Y in Fields of Mistria")
    # scored title_overlap=0.75 despite naming a genuinely different subject (new distinctive
    # keywords: "juniper"/"arrogant"/"witch"). CONFIRMATION_ONLY now additionally requires no new
    # distinctive keywords - if there ARE any (bounded to a small number), that is real signal a
    # template match alone would hide, so it falls through to MINOR_DELTA/UNCERTAIN_DELTA below
    # instead of being confidently waved through as "just a rewording."
    if max_title_overlap >= _CONFIRMATION_ONLY_TITLE_OVERLAP and not new_keywords:
        reason = (
            f"substantially similar title (overlap={max_title_overlap:.2f}), no new material claims, "
            f"no new distinctive keywords - a rewording, not new substance"
        )
        return DeltaResult(
            CONFIRMATION_ONLY, max_title_overlap_vs_prior=max_title_overlap, reason=reason,
        )

    if new_keywords and len(new_keywords) <= _MINOR_DELTA_MAX_NEW_KEYWORDS:
        reason = f"a small number of new distinctive keywords, no material claim ({new_keywords})"
        return DeltaResult(
            MINOR_DELTA, new_keywords=new_keywords, max_title_overlap_vs_prior=max_title_overlap, reason=reason,
        )

    reason = (
        f"neither a confident rewording (overlap={max_title_overlap:.2f}) nor a clear material "
        f"claim nor a small bounded keyword delta ({len(new_keywords)} new keywords) - ambiguous"
    )
    return DeltaResult(UNCERTAIN_DELTA, new_keywords=new_keywords, max_title_overlap_vs_prior=max_title_overlap, reason=reason)


def gate_delta_by_identity(delta: DeltaResult, *, has_distinctive_shared_entity: bool) -> DeltaResult:
    """Pure. Phase 20 Checkpoint 6 - "identity before delta": a claim about WHAT CHANGED is only
    meaningful once WHETHER THIS IS THE SAME STORY is itself reasonably established. Real
    Checkpoint 6 evidence (docs/phase20_checkpoint6_human_calibration_report.md) found four
    confirmed false-match cases where a real new date/amount/year (a genuine `MATERIAL_UPDATE` by
    `classify_delta()`'s own title/claim-only logic) was being attached to a Story that was
    actually a different real-world event - the new fact was real, but it was a new fact about
    the WRONG story. In every one of those cases, `services/story_memory.py::match_story()`'s own
    winning candidate shared no distinctive entity with the new event (only a single generic word
    - a politician's surname, a company name, a template artifact) - `has_distinctive_shared_entity`
    is exactly that same signal, already computed by `match_story()` for its own dispatch.

    `MATERIAL_UPDATE` is the only classification gated - it is the one that asserts new
    information about a *specific* existing story. `NO_NEW_FACTS`/`CONFIRMATION_ONLY` already
    imply high title similarity (a near-rewording), which is itself strong same-story evidence
    independent of entities, and are additionally gated by `compute_would_suppress()`'s own
    requirement that `match_type` be `SEMANTIC_DUPLICATE`/`SUPPORTING_SOURCE` (both now
    entity-gated too, or near-identical-titled, at the `services/story_memory.py` layer) - so
    downgrading them again here would be redundant, not additionally protective."""
    if delta.classification == MATERIAL_UPDATE and not has_distinctive_shared_entity:
        return DeltaResult(
            UNCERTAIN_DELTA, new_keywords=delta.new_keywords, max_title_overlap_vs_prior=delta.max_title_overlap_vs_prior,
            reason=(
                f"{delta.reason} - DOWNGRADED from material_update: the matched Story shares no "
                f"distinctive entity with this event (identity-before-delta gate), so the new "
                f"claim(s) {delta.new_material_claims} cannot be trusted as an update to THIS "
                f"specific story rather than a coincidental match"
            ),
        )
    return delta


async def compute_story_delta(session: AsyncSession, *, new_title: str, story_id: UUID, exclude_event_id: UUID | None = None) -> DeltaResult:
    """The only DB-touching entry point. Fetches every other real NewsEvent title already linked
    to this Story (one bounded query, mirrors services/story_context.py::build_story_timeline()'s
    own "3 bounded queries, never N+1" discipline) and delegates to the pure `classify_delta()`.
    `exclude_event_id` lets the caller exclude the event currently being classified if it has
    already been linked (defensive - normally the caller classifies delta BEFORE linking)."""
    stmt = (
        select(NewsEvent.title)
        .join(NewsEventStoryLink, NewsEventStoryLink.news_event_id == NewsEvent.id)
        .where(NewsEventStoryLink.story_id == story_id)
    )
    if exclude_event_id is not None:
        stmt = stmt.where(NewsEvent.id != exclude_event_id)
    prior_titles = list((await session.execute(stmt)).scalars().all())
    return classify_delta(new_title, prior_titles)
