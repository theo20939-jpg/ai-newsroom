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

from core.config import settings
from database.models.news_event import NewsEvent
from database.models.story_link import NewsEventStoryLink
from services.story_confidence import compute_confidence_band
from services.story_delta_engine import compute_story_delta
from services.story_memory import SEMANTIC_DUPLICATE, SUPPORTING_SOURCE, is_story_update_match
from services.story_suppression import compute_would_suppress
from services.story_telegram_delivery import FAIL_CLOSED_ROUTE_TO_REVIEW, determine_reply_target, get_root_delivery

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


# ---------------------------------------------------------------------------------------------
# NEWS Stability Acceptance follow-up (docs/post_acceptance_followup_checkpoint.md §B): the real
# acceptance canary found 2 genuine story_update candidates that correctly failed closed (no
# resolvable root Telegram message) - but only AFTER Research + Copywriting had already run and
# been paid for, since worker/content_cycle.py's own fail-closed check happens after
# run_content_generation_for_event() returns. Both pieces of information the late check needs
# (NewsEventStoryLink.match_type and the story's root delivery) are already fully determined at
# TRIAGE time (services/triage_orchestrator.py::_apply_story_memory()), long before Scoring,
# Intelligence, Research, or Copywriting ever run for the event - so the SAME check can run here,
# reusing the exact same NewsEventStoryLink + get_root_delivery() + determine_reply_target() this
# module and services/story_telegram_delivery.py already use, never a second, divergent rule.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class UpdateFailClosedCheck:
    """`would_fail_closed=True` means: worker/content_cycle.py's own real reply-routing check
    would, later, inevitably reach FAIL_CLOSED_ROUTE_TO_REVIEW and drop this draft entirely
    (never sent, per the existing, unchanged, non-negotiable product policy) - so the caller can
    skip the paid run_content_generation_for_event() call for this event now instead of paying for
    it first. `reason` is always populated, matching DuplicateDeliveryCheck's own convention."""

    would_fail_closed: bool
    story_id: UUID | None
    match_type: str | None
    reason: str


async def check_update_would_fail_closed(session: AsyncSession, event_id: UUID) -> UpdateFailClosedCheck:
    """Read-only pre-generation gate. A no-op (would_fail_closed=False) whenever:

    - `telegram_story_reply_mode != "enforce"` - "off"/"shadow" never fail-closed-DROP a draft
      (shadow still generates and sends as a standalone post, purely to observe/log the would-be
      rate - see services/story_telegram_delivery.py's own module docstring); short-circuiting
      here for those modes would silently change that observability behavior, not just save cost.
    - no `NewsEventStoryLink` exists (`story_memory_mode == "off"`, today's real default).
    - the match type is not update-equivalent (`is_story_update_match()`).
    - a resolvable root already exists.

    Does NOT wait or retry for a root that might resolve moments later - an intentional design
    choice, not an oversight: the root's own resolution is entirely driven by a SEPARATE event's
    own asynchronous processing timeline, never by whether THIS event's Research/Copywriting runs
    or not, so moving this exact same point-in-time check earlier (from after generation to
    before it) does not meaningfully change how much wall-clock time the other event's root had to
    resolve - see docs/post_acceptance_followup_checkpoint.md §B for the full reasoning. The final,
    real send-time check in worker/content_cycle.py is left completely unchanged and remains the
    authoritative decision - this function only ever prevents wasted spend on a case that check
    would have dropped anyway, it never makes a delivery decision of its own."""
    if settings.telegram_story_reply_mode != "enforce":
        return UpdateFailClosedCheck(
            False, None, None, "telegram_story_reply_mode is not enforce - never fail-closed-drops here",
        )
    link = await session.get(NewsEventStoryLink, event_id)
    if link is None:
        return UpdateFailClosedCheck(
            False, None, None, "no NewsEventStoryLink - Story Memory did not run for this event",
        )
    if not is_story_update_match(link.match_type):
        return UpdateFailClosedCheck(
            False, link.story_id, link.match_type,
            f"match_type ({link.match_type}) is not update-equivalent - proceeds normally",
        )
    root_delivery = await get_root_delivery(session, link.story_id)
    root_message_id = root_delivery.telegram_message_id if root_delivery is not None else None
    decision = determine_reply_target(is_story_update=True, root_message_id=root_message_id)
    if decision.action == FAIL_CLOSED_ROUTE_TO_REVIEW:
        return UpdateFailClosedCheck(
            True, link.story_id, link.match_type,
            f"Story {link.story_id} has no resolvable root Telegram message - would fail closed",
        )
    return UpdateFailClosedCheck(
        False, link.story_id, link.match_type, f"Story {link.story_id} has a resolvable root - proceeds normally",
    )
