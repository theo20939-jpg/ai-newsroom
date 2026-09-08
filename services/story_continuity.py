"""STORY-CONTINUITY-P0 (2026-09): the single deterministic continuity classification.

`classify_continuity()` collapses Story Memory's six retrieval-only `match_type` values plus the
Delta Engine's five classifications into ONE actionable, non-overlapping outcome per event:

    NEW_STORY                 - a genuinely different real-world development.
    DUPLICATE_NO_DELTA        - confidently the same Story, adds no meaningful new fact.
    MATERIAL_UPDATE_CANDIDATE - confidently the same Story, adds a real new fact (P1 will decide
                                how to present it; in P0 it still flows down the existing NEWS
                                path, never dropped).
    AMBIGUOUS                 - not enough evidence to assert same-Story identity confidently.
                                Never merges unrelated Stories, never suppresses a distinct
                                development - diagnostics retained, optional future review.

Pure, deterministic, no I/O, no LLM. The result is structured evidence only - never chain-of-
thought. `suppression_eligible` is a DIAGNOSTIC flag: nothing in P0 reads it to drop a send
(services/story_duplicate_guard.py::check_duplicate_story_delivery() unconditionally returns
blocked=False, unchanged by this phase). Real duplicate suppression is a separately-authorized
rollout step.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from services.story_confidence import HIGH, MEDIUM, compute_confidence_band
from services.story_delta_engine import (
    DELTA_MATERIAL,
    DELTA_MINOR,
    DELTA_NONE,
    DeltaResult,
    coarse_delta_class,
)
from services.story_memory import (
    NEW_STORY,
    RELATED_STORY,
    SEMANTIC_DUPLICATE,
    STORY_UPDATE,
    SUPPORTING_SOURCE,
    UNCERTAIN_MATCH,
    MatchResult,
)

# --- outcomes ---------------------------------------------------------------------------------
CONTINUITY_NEW_STORY = "NEW_STORY"
CONTINUITY_DUPLICATE_NO_DELTA = "DUPLICATE_NO_DELTA"
CONTINUITY_MATERIAL_UPDATE_CANDIDATE = "MATERIAL_UPDATE_CANDIDATE"
CONTINUITY_AMBIGUOUS = "AMBIGUOUS"

ALL_CONTINUITY_OUTCOMES: tuple[str, ...] = (
    CONTINUITY_NEW_STORY,
    CONTINUITY_DUPLICATE_NO_DELTA,
    CONTINUITY_MATERIAL_UPDATE_CANDIDATE,
    CONTINUITY_AMBIGUOUS,
)

# Story Memory match_type values that assert a CONFIDENT same-Story relationship.
_CONFIDENT_SAME_STORY_MATCH_TYPES = frozenset({SEMANTIC_DUPLICATE, SUPPORTING_SOURCE, STORY_UPDATE})


@dataclass(frozen=True)
class ContinuityResult:
    """The one structured continuity result. `reason_codes` are concise, machine-readable, and
    stable; `match_components` carries the per-tier entity-overlap evidence for P1 / observability
    / audit. Nothing here is free-text reasoning."""

    outcome: str
    matched_story_id: UUID | None
    match_score: float
    confidence_band: str  # story_confidence band for the match ("high"/"medium"/"low")
    delta_class: str | None  # NO_DELTA | MINOR_DELTA | MATERIAL_DELTA, or None (NEW_STORY)
    suppression_eligible: bool  # DIAGNOSTIC ONLY - P0 never acts on it
    reason_codes: tuple[str, ...] = ()
    match_components: dict[str, float] = field(default_factory=dict)
    new_signals: tuple[str, ...] = ()       # new factual signals this event adds to the Story
    repeated_signals: tuple[str, ...] = ()  # signals already carried by the Story's prior titles


def _components(match_result: MatchResult) -> dict[str, float]:
    return {
        "match_score": round(float(match_result.confidence), 4),
        "entity_overlap": round(float(match_result.entity_overlap), 4),
        "distinctive_overlap": round(float(match_result.distinctive_overlap), 4),
        "supporting_overlap": round(float(match_result.supporting_overlap), 4),
        "generic_overlap": round(float(match_result.generic_overlap), 4),
    }


def classify_continuity(
    *,
    match_result: MatchResult,
    delta_result: DeltaResult | None,
    creates_own_story: bool,
) -> ContinuityResult:
    """Pure. `match_result` is services/story_memory.py::match_story()'s result;
    `delta_result` is services/story_delta_engine.py::compute_story_delta()'s result (None when
    the event creates its own Story, so there are no prior titles to diff against);
    `creates_own_story` mirrors triage_orchestrator's own dispatch bool exactly."""
    components = _components(match_result)
    outcome_mt = match_result.outcome
    band = (
        compute_confidence_band(match_result.confidence)
        if outcome_mt in (SEMANTIC_DUPLICATE, SUPPORTING_SOURCE, STORY_UPDATE, UNCERTAIN_MATCH)
        else "low"
    )
    new_signals: tuple[str, ...] = ()
    repeated_signals: tuple[str, ...] = ()
    delta_class: str | None = None
    if delta_result is not None:
        delta_class = coarse_delta_class(delta_result)
        new_signals = tuple(delta_result.new_material_claims) + tuple(delta_result.new_keywords)

    # 1. NEW_STORY / RELATED_STORY / a story-creating uncertain match -> a distinct development.
    if creates_own_story or outcome_mt in (NEW_STORY, RELATED_STORY):
        new_story_codes: tuple[str, ...] = (
            ("new_story",) if outcome_mt == NEW_STORY
            else ("related_story_not_merged",) if outcome_mt == RELATED_STORY
            else ("uncertain_match_low_entity_own_story",)
        )
        return ContinuityResult(
            outcome=CONTINUITY_NEW_STORY, matched_story_id=None,
            match_score=round(float(match_result.confidence), 4), confidence_band=band,
            delta_class=None, suppression_eligible=False, reason_codes=new_story_codes,
            match_components=components,
        )

    matched_id = match_result.matched_story_id

    # 2. A confident same-Story match (SEMANTIC_DUPLICATE / SUPPORTING_SOURCE / STORY_UPDATE),
    #    but only if a genuinely distinctive shared entity backs it - organization/generic-only
    #    overlap is never confident identity (Section 7).
    if outcome_mt in _CONFIDENT_SAME_STORY_MATCH_TYPES and match_result.has_distinctive_shared_entity:
        if outcome_mt == STORY_UPDATE:
            # Story Memory already judged the title materially different; honour that as an
            # update candidate. delta_class refines the evidence but never demotes it to a
            # duplicate.
            eff_delta = delta_class or DELTA_MATERIAL
            return ContinuityResult(
                outcome=CONTINUITY_MATERIAL_UPDATE_CANDIDATE, matched_story_id=matched_id,
                match_score=round(float(match_result.confidence), 4), confidence_band=band,
                delta_class=eff_delta, suppression_eligible=False,
                reason_codes=("same_story", "story_update", f"delta_{eff_delta.lower()}"),
                match_components=components, new_signals=new_signals, repeated_signals=repeated_signals,
            )
        # SEMANTIC_DUPLICATE / SUPPORTING_SOURCE - the delta decides.
        if delta_class == DELTA_NONE:
            return ContinuityResult(
                outcome=CONTINUITY_DUPLICATE_NO_DELTA, matched_story_id=matched_id,
                match_score=round(float(match_result.confidence), 4), confidence_band=band,
                delta_class=DELTA_NONE, suppression_eligible=True,
                reason_codes=("same_story", outcome_mt, "no_new_facts"),
                match_components=components, new_signals=(), repeated_signals=repeated_signals,
            )
        if delta_class == DELTA_MATERIAL:
            return ContinuityResult(
                outcome=CONTINUITY_MATERIAL_UPDATE_CANDIDATE, matched_story_id=matched_id,
                match_score=round(float(match_result.confidence), 4), confidence_band=band,
                delta_class=DELTA_MATERIAL, suppression_eligible=False,
                reason_codes=("same_story", outcome_mt, "material_delta"),
                match_components=components, new_signals=new_signals, repeated_signals=repeated_signals,
            )
        # DELTA_MINOR (or delta not computable): SAFE semantics (Section 11) - treat as an update
        # candidate, NOT suppression-eligible, so a potentially important small fact is never
        # silently dropped. P1 may still choose to present it as a light UPDATE or fold it in.
        return ContinuityResult(
            outcome=CONTINUITY_MATERIAL_UPDATE_CANDIDATE, matched_story_id=matched_id,
            match_score=round(float(match_result.confidence), 4), confidence_band=band,
            delta_class=DELTA_MINOR, suppression_eligible=False,
            reason_codes=("same_story", outcome_mt, "minor_delta", "not_suppressed_conservative"),
            match_components=components, new_signals=new_signals, repeated_signals=repeated_signals,
        )

    # 3. Everything else - a confident score without a distinctive entity, or an UNCERTAIN_MATCH
    #    that attached for observability. AMBIGUOUS: no merge, no suppression, evidence retained.
    codes: tuple[str, ...]
    if outcome_mt in _CONFIDENT_SAME_STORY_MATCH_TYPES:
        codes = (outcome_mt, "no_distinctive_shared_entity", "identity_not_confident")
    elif match_result.company_only_match:
        codes = ("uncertain_match", "company_only_overlap", "identity_not_confident")
    else:
        codes = ("uncertain_match", "identity_not_confident")
    return ContinuityResult(
        outcome=CONTINUITY_AMBIGUOUS, matched_story_id=matched_id,
        match_score=round(float(match_result.confidence), 4),
        confidence_band=band if band in (HIGH, MEDIUM) else "low",
        delta_class=delta_class, suppression_eligible=False, reason_codes=codes,
        match_components=components, new_signals=new_signals, repeated_signals=repeated_signals,
    )
