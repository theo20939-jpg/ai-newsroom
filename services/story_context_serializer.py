"""Phase 19 overnight A/B/C validation seam: deterministic serialization of a Story Timeline
(services/story_context.py::build_story_timeline()'s output) into the bounded text block
CopywritingCapability's v6 prompt reads via BusinessContext.prior_coverage_context.

Pure, deterministic, no LLM call. Returns None (never an empty-but-present string) when there is
no real prior coverage to report - the caller must never fabricate a memory scenario. Uncertainty
in the underlying Story Memory match is carried through explicitly, never silently upgraded to a
stated fact (mirrors services/editorial_planning_safety.py's own "disclosed, narrow
approximation" convention).
"""
from __future__ import annotations

from uuid import UUID

from services.story_context import StoryTimelineEntry
from services.story_delta_engine import DeltaResult

_MAX_TIMELINE_ENTRIES = 6
_MAX_FACT_ITEMS = 5
_MAX_DELTA_ITEMS = 8

_UNCERTAIN_MATCH_TYPES = {"uncertain_match"}


def serialize_prior_coverage(
    timeline: list[StoryTimelineEntry], *, current_event_id: UUID, match_type: str | None, match_score: float | None,
) -> str | None:
    """`timeline` is the FULL story timeline (may include the current event itself, since
    build_story_timeline() has no reason to exclude it - the caller is expected to have already
    linked the current event into the story before calling this). Entries at or after the current
    event are excluded here so "prior coverage" never includes the update being written right
    now. Returns None if nothing prior remains, or if the match itself is not yet a real story
    link (match_type is None - no NewsEventStoryLink exists for this event)."""
    if match_type is None or not timeline:
        return None

    return _serialize(timeline, current_event_id=current_event_id, match_type=match_type, match_score=match_score)


def _serialize(
    timeline: list[StoryTimelineEntry], *, current_event_id: UUID, match_type: str, match_score: float | None,
) -> str | None:
    current = next((e for e in timeline if e.event_id == current_event_id), None)
    if current is None:
        # The current event isn't itself in the timeline yet (e.g. the caller computed the
        # timeline from an existing story before linking this event in) - every other entry is
        # prior by definition.
        prior = list(timeline)
    else:
        anchor = current.published_at or current.collected_at
        prior = [
            e for e in timeline
            if e.event_id != current_event_id and (e.published_at or e.collected_at) <= anchor
        ]

    if not prior:
        return None

    uncertain = match_type in _UNCERTAIN_MATCH_TYPES
    prior = prior[-_MAX_TIMELINE_ENTRIES:]  # most recent N, chronological order preserved

    already_published: list[str] = []
    for entry in prior:
        already_published.extend(entry.confirmed_existing_facts)
        already_published.extend(entry.introduced_new_facts)
    # de-duplicate while preserving order, bounded
    seen: set[str] = set()
    deduped: list[str] = []
    for fact in already_published:
        if fact not in seen:
            seen.add(fact)
            deduped.append(fact)
    deduped = deduped[:_MAX_FACT_ITEMS]

    lines = [
        f"story_match_type: {match_type}" + (" (UNCERTAIN - do not treat as confirmed)" if uncertain else ""),
        f"story_match_score: {match_score if match_score is not None else 'unknown'}",
        f"prior_coverage_count: {len(prior)}",
        "prior_coverage_timeline:",
    ]
    for entry in prior:
        when = (entry.published_at or entry.collected_at).date().isoformat()
        published_marker = "PUBLISHED TO TELEGRAM" if entry.already_published else "not yet published"
        lines.append(
            f"  - {when} [{entry.source or 'unknown source'}] delta={entry.delta} ({published_marker})"
        )
    lines.append("already_published_keywords_topics (do not repeat as new; may reference briefly for continuity):")
    lines.append("  - " + ", ".join(deduped) if deduped else "  - (none identified)")
    if uncertain:
        lines.append(
            "NOTE: this story link is UNCERTAIN - treat all of the above as possibly-related "
            "background only, never as confirmed prior coverage."
        )
    return "\n".join(lines)


def serialize_delta_engine_context(*, delta_result: DeltaResult, confidence_band: str, would_suppress: bool) -> str:
    """Phase 20 M9: renders the V2 Delta Engine's (services/story_delta_engine.py) own
    classification of what is genuinely new about the event currently being drafted, as an
    additional bounded text block a caller may concatenate onto `serialize_prior_coverage()`'s
    output. Deliberately a separate function, not a change to `serialize_prior_coverage()` itself
    - keeps the already-tested Phase 19 seam untouched, and keeps this new function independently
    testable (mirrors this module's own "add, don't rewrite" convention already visible in
    `_serialize()`'s docstring). Tests/replay only this milestone - no caller exists yet in the
    live `capabilities/copywriting_capability.py` / `worker/content_cycle.py` path, matching Phase
    20's shadow-neutrality requirement exactly.

    Always returns a non-empty string (unlike `serialize_prior_coverage()`, which may return
    `None`) - a delta classification always exists once a same-story match exists; there is no
    "nothing to report" case for this function the way there is for prior coverage."""
    lines = [
        f"delta_classification: {delta_result.classification}",
        f"delta_reason: {delta_result.reason}",
        f"confidence_band: {confidence_band}",
        f"would_suppress_as_duplicate (shadow recommendation only, NOT enforced - has zero effect "
        f"on whether this article is written or published): {would_suppress}",
    ]
    if delta_result.new_material_claims:
        lines.append("new_material_claims: " + ", ".join(delta_result.new_material_claims[:_MAX_DELTA_ITEMS]))
    if delta_result.new_keywords:
        lines.append("new_keywords: " + ", ".join(delta_result.new_keywords[:_MAX_DELTA_ITEMS]))
    return "\n".join(lines)
