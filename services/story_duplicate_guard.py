"""Phase 23.1I Part B: a narrow, delivery-level invariant - a Story that already has a delivered
root NEWS post should not immediately receive a second standalone post from a source that adds no
material information (docs/phase23_1i_live_editorial_hardening_report.md).

Root cause this responds to: two real, live Phase 23.1H posts about the same underlying Armenia
datacenter story were both delivered as standalone NEWS posts. Investigation (report §1-3) found
`story_memory_mode=off` throughout - Story Memory never ran for either event, so there was no
persisted relationship to consult in the first place. This module does NOT fix that (Part C, live-
shadow wiring, is the actual fix for that gap) - it exists so that, once Story Memory DOES run,
delivery actually respects what it found.

Deliberately narrow, reusing only real, already-persisted Phase 20 state - no new table, no new
migration, no invented "material update" signal:
- `NewsEventStoryLink.match_type`/`match_score` (already real, already persisted whenever
  `story_memory_mode != "off"` was active at triage time) - `SEMANTIC_DUPLICATE`/`SUPPORTING_
  SOURCE` are Story Memory's own existing, already-calibrated definition of "corroborates or
  rehashes the same core event without adding new substance" (services/story_memory.py's own
  module-level outcome docstrings). `STORY_UPDATE` is Story Memory's own existing definition of "a
  materially different title, a real new development" - already the closest real signal to
  "material update" this codebase has computed and persisted; NOT blocked here.
- `services/story_telegram_delivery.py::get_root_delivery()` (already real, already tested,
  already the exact "has this Story had a successful root delivery" query) - reused verbatim, not
  reimplemented.

Phase 23.1P (docs/phase23_1p_story_memory_quotes_gate_report.md): now ALSO consults the Story
Memory V2 layer (services/story_delta_engine.py + story_confidence.py + story_suppression.py,
Phase 20 M6/M7) - re-derived on the fly at delivery time from already-persisted state (this
event's own title, the matched Story's other already-linked event titles, and the already-
persisted `match_type`/`match_score`), never from the V2 shadow columns themselves (that
migration, `3c22be05f4e5_add_story_memory_v2_shadow_columns.py`, is still never applied to any
real database - this module does not depend on it existing). `compute_would_suppress()` is
strictly MORE conservative than the old `match_type in {SEMANTIC_DUPLICATE, SUPPORTING_SOURCE}`
check alone (real, evidenced example: two syndicated-wire articles scoring a 0.843 near-identical-
title SEMANTIC_DUPLICATE match under V1 alone, but whose actual claims differ by one genuinely new
number - V1-only would have wrongly blocked the second article; the V2-aware check does not,
Phase 23.1P forensics table) - it can only ever suppress a STRICT SUBSET of what the old check
would have, never a superset, so this is additive precision, not a new suppression class.

`UNCERTAIN_MATCH` and `RELATED_STORY` are never blocked - mirrors Story Memory's own established
"false suppression is worse than a duplicate" design philosophy (docs/phase20_final_technical_
report.md), unchanged here, not reinterpreted.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import NewsEvent
from database.models.story_link import NewsEventStoryLink
from services.story_confidence import compute_confidence_band
from services.story_delta_engine import compute_story_delta, gate_delta_by_identity
from services.story_memory import SEMANTIC_DUPLICATE, SUPPORTING_SOURCE
from services.story_suppression import compute_would_suppress
from services.story_telegram_delivery import get_root_delivery

# Match types Story Memory itself already defines as "no material new information" - see this
# module's own docstring for why STORY_UPDATE/UNCERTAIN_MATCH/RELATED_STORY/NEW_STORY are
# deliberately excluded from this set. Still the cheap pre-filter before the V2 recompute below -
# no need to touch the delta engine at all for a match_type that can never suppress regardless.
_NO_MATERIAL_UPDATE_MATCH_TYPES = frozenset({SEMANTIC_DUPLICATE, SUPPORTING_SOURCE})


@dataclass(frozen=True)
class DuplicateDeliveryCheck:
    """`blocked=True` means: do not send a standalone NEWS post for this event. `reason` is always
    populated (blocked or not) for audit logging - mirrors `services.editorial_treatment.
    EditorialTreatmentDecision`'s own "always explain the decision" convention."""

    blocked: bool
    story_id: UUID | None
    match_type: str | None
    reason: str
    delta_classification: str | None = None
    would_suppress: bool | None = None


def should_block_duplicate_delivery(match_type: str | None, has_prior_root_delivery: bool) -> bool:
    """Pure, V1-only convenience check - still exported/used as the cheap pre-filter in
    `check_duplicate_story_delivery()` below (see its own docstring for why the real block
    decision there is V2-aware, strictly narrower than this). `match_type=None` (no
    NewsEventStoryLink at all - Story Memory did not run for this event) never blocks - there is
    nothing to consult, so delivery proceeds exactly as it always has (no regression when
    story_memory_mode is "off", today's real default)."""
    if match_type is None or not has_prior_root_delivery:
        return False
    return match_type in _NO_MATERIAL_UPDATE_MATCH_TYPES


async def check_duplicate_story_delivery(session: AsyncSession, event_id: UUID) -> DuplicateDeliveryCheck:
    """The one orchestration entry point `worker/content_cycle.py`'s router branch calls. Read-only
    - never creates, mutates, or deletes any row."""
    link = await session.get(NewsEventStoryLink, event_id)
    if link is None:
        return DuplicateDeliveryCheck(
            blocked=False, story_id=None, match_type=None,
            reason="no NewsEventStoryLink - Story Memory did not run for this event",
        )

    root_delivery = await get_root_delivery(session, link.story_id)
    v1_candidate = should_block_duplicate_delivery(link.match_type, root_delivery is not None)
    if not v1_candidate:
        if root_delivery is not None:
            reason = f"Story {link.story_id} already has a delivered root post, but match_type ({link.match_type}) is not a no-material-update type - allowed"
        else:
            reason = f"Story {link.story_id} has no prior delivered root post - allowed"
        return DuplicateDeliveryCheck(blocked=False, story_id=link.story_id, match_type=link.match_type, reason=reason)

    # V1 alone would block - Phase 23.1P: confirm with the delta-aware V2 layer before actually
    # blocking, re-derived on the fly (see module docstring - no dependency on the V2 migration).
    event = await session.get(NewsEvent, event_id)
    delta_classification: str | None = None
    would_suppress = True  # conservative fallback if the event row is somehow missing
    if event is not None:
        try:
            delta = await compute_story_delta(session, new_title=event.title, story_id=link.story_id, exclude_event_id=event_id)
            confidence_band = compute_confidence_band(link.match_score)
            would_suppress = compute_would_suppress(
                match_type=link.match_type, confidence_band=confidence_band, delta_classification=delta.classification,
            )
            delta_classification = delta.classification
        except Exception:
            pass  # conservative fallback (would_suppress=True) - matches the pre-23.1P V1-only behavior

    if would_suppress:
        reason = (
            f"Story {link.story_id} already has a delivered root post; this event's match_type "
            f"({link.match_type}) + delta_classification ({delta_classification}) confirm no "
            f"material new information (Story Memory V2)"
        )
    else:
        reason = (
            f"Story {link.story_id} already has a delivered root post and match_type "
            f"({link.match_type}) alone would suppress, but delta_classification "
            f"({delta_classification}) shows genuinely new information - allowed (Story Memory V2)"
        )
    return DuplicateDeliveryCheck(
        blocked=would_suppress, story_id=link.story_id, match_type=link.match_type, reason=reason,
        delta_classification=delta_classification, would_suppress=would_suppress,
    )
