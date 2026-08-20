"""NINJA PULSE RECAP Phase R2.9 - RECAP-only Origin Membership Projection.

Narrow RECAP boundary adapter, NOT a Story Memory rewrite. Reused evidence, reimplemented here
(never imported from `scripts/` - diagnostic scripts remain diagnostic; production code must not
depend on them): R2.7 (`scripts/_recap_r2_7_anchor_lifecycle_forensic.py`) proved, against real
production data, that `services/triage_orchestrator.py::_apply_story_memory()` (Phase 20 M11.1,
Story Identity Invariant) deliberately creates a brand-new Story for a `RELATED_STORY` outcome, or
a weak-entity-overlap `UNCERTAIN_MATCH` outcome, with `Story.first_event_id = event.id` - but
persists that SAME event's own `NewsEventStoryLink.match_type` unchanged from the classification
against the OLD, discarded candidate Story it was scored against and rejected. `services/
recap_event.py::_CONFIRMED_MEMBERSHIP_MATCH_TYPES` (written independently, for a different
question - "is this a confirmed continuation of the Story's own history") excludes both outcomes by
design, so the Story's own immutable origin event can be, and for a real, non-trivial class of
Stories always is, absent from its own confirmed membership from the moment of creation. R2.8
(`scripts/_recap_r2_8_origin_membership_semantics_shadow.py`) built and offline-validated a
fail-closed projection rule for this exact shape, including two real, named production examples
(reproduced as this module's own R2.9 test fixtures) proving that a NAIVE "substitute the earliest
confirmed member as anchor instead" repair is UNSAFE (a real Marvell/Google Story: the earliest-
confirmed-member anchor FAILS frozen Story Integrity, while the immutable origin anchor correctly
PASSES - all three events genuinely describe the same chip-development/warrant/share transaction).
This module is the production integration of that same proven rule - never a broader heuristic,
never a new anchor-selection algorithm.

CONTRACT (mirrors R2.8's own `classify_origin_projection()` exactly - same invariants, same reason
codes, reimplemented rather than imported):

    Story Memory storage semantics                (unchanged - this module writes nothing)
            v
    confirmed-member loader                        (services.recap_event.load_story_events() -
            v                                        unchanged, still the global membership truth)
    RECAP semantic adapter                          (THIS MODULE - read-only, RECAP-only)
            v
    effective origin-aware RECAP member set          (build_effective_recap_members())
            v
    frozen evaluate_recap_story_integrity()          (services.recap_event - byte-for-byte unchanged)
            v
    existing RECAP readiness/candidate logic          (services.event_recap - unchanged downstream)

`Story.first_event_id`, `NewsEventStoryLink.match_type`, `services.recap_event.
_CONFIRMED_MEMBERSHIP_MATCH_TYPES`, and `services/story_memory.py`/`services/triage_orchestrator.py`
classification semantics are NEVER read for any purpose other than this READ-ONLY eligibility
check, and are NEVER written to anywhere in this module. `resolve_recap_origin_projection()` is a
pure DB read (one `NewsEvent` lookup, one `NewsEventStoryLink` lookup by the origin event's own
id); `classify_origin_projection()` and `build_effective_recap_members()` are pure functions over
already-loaded plain objects. No `session.add()`/`.delete()`/`.merge()`, no `.commit()`/`.flush()`,
no write SQL anywhere in this module.

FAIL-CLOSED: `classify_origin_projection()` never infers history the schema cannot prove. Any
structural ambiguity (multiple current links for the origin event, a current link to a DIFFERENT
Story, no link at all, an unrecognized `match_type`) returns `eligible=False` with an explicit
reason code - never a guess, never a broader fallback."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import NewsEvent
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from services.recap_event import _CONFIRMED_MEMBERSHIP_MATCH_TYPES
from services.story_memory import RELATED_STORY, UNCERTAIN_MATCH

# Reason codes - plain strings, mirrors this codebase's own established closed-vocabulary
# convention (e.g. services/story_memory.py's own NEW_STORY/RELATED_STORY/...), and mirrors R2.8's
# own identically-named codes exactly (same proven eligibility rule, not a new one).
ORIGIN_EVENT_MISSING = "ORIGIN_EVENT_MISSING"
ORIGIN_LINK_MISSING = "ORIGIN_LINK_MISSING"
ORIGIN_LINK_WRONG_STORY = "ORIGIN_LINK_WRONG_STORY"
ORIGIN_LINK_AMBIGUOUS = "ORIGIN_LINK_AMBIGUOUS"
ORIGIN_MATCH_TYPE_UNEXPECTED = "ORIGIN_MATCH_TYPE_UNEXPECTED"
ORIGIN_PROJECTION_ELIGIBLE = "ORIGIN_PROJECTION_ELIGIBLE"
ORIGIN_PROJECTION_NOT_NEEDED = "ORIGIN_PROJECTION_NOT_NEEDED"


@dataclass(frozen=True)
class OriginProjectionDecision:
    """The fail-closed eligibility verdict for treating a Story's declared, non-confirmed
    `first_event_id` as an effective RECAP member. Never mutates anything - a pure function of
    already-loaded rows."""

    reason_code: str
    eligible: bool
    detail: str


def classify_origin_projection(
    story: Story,
    declared_event: NewsEvent | None,
    all_current_links_for_declared_event: list[NewsEventStoryLink],
) -> OriginProjectionDecision:
    """Pure, fail-closed. `all_current_links_for_declared_event` must be EVERY current
    `NewsEventStoryLink` row for `story.first_event_id` (not pre-filtered to `story.id`) - the
    wrong-story/ambiguous checks below need to see the full set to prove their verdicts, never
    assume them.

    Eligibility requires ALL of: the origin event exists; it has exactly one current link; that
    link points to THIS Story; that link's `match_type` is `RELATED_STORY` or `UNCERTAIN_MATCH`
    (the two, and only two, outcomes `services/triage_orchestrator.py::_apply_story_memory()` can
    persist on a newly-self-created Story's own founding link - proven in this module's own
    docstring); no conflicting current relationship to a different Story exists."""
    if declared_event is None:
        return OriginProjectionDecision(
            ORIGIN_EVENT_MISSING, False, f"NewsEvent {story.first_event_id} does not exist in news_events",
        )

    own_links = [link for link in all_current_links_for_declared_event if link.story_id == story.id]
    other_links = [link for link in all_current_links_for_declared_event if link.story_id != story.id]

    if other_links:
        return OriginProjectionDecision(
            ORIGIN_LINK_WRONG_STORY,
            False,
            f"declared event's current link points to a DIFFERENT story: "
            f"{[str(link.story_id) for link in other_links]}",
        )
    if not own_links:
        return OriginProjectionDecision(
            ORIGIN_LINK_MISSING, False, "declared event exists but has no NewsEventStoryLink row at all",
        )
    if len(own_links) > 1:
        # `news_event_id` is the PRIMARY KEY of `news_event_story_links` (database/models/
        # story_link.py's own explicit "at most one link per event... hard database constraint,
        # not an application-level convention") - PROVEN unreachable given the current schema.
        # Kept as defense-in-depth, never assumed away.
        return OriginProjectionDecision(
            ORIGIN_LINK_AMBIGUOUS, False, f"{len(own_links)} current link rows found for the declared event",
        )

    own_link = own_links[0]
    if own_link.match_type in _CONFIRMED_MEMBERSHIP_MATCH_TYPES:
        return OriginProjectionDecision(
            ORIGIN_PROJECTION_NOT_NEEDED,
            False,
            f"declared event's own link match_type={own_link.match_type!r} is already confirmed "
            "membership - no projection needed",
        )
    if own_link.match_type not in (RELATED_STORY, UNCERTAIN_MATCH):
        return OriginProjectionDecision(
            ORIGIN_MATCH_TYPE_UNEXPECTED,
            False,
            f"declared event's own link match_type={own_link.match_type!r} is neither confirmed "
            "membership nor RELATED_STORY/UNCERTAIN_MATCH - unknown taxonomy, refusing to guess",
        )
    return OriginProjectionDecision(
        ORIGIN_PROJECTION_ELIGIBLE,
        True,
        f"declared event's own link match_type={own_link.match_type!r}, points to this Story, exactly "
        "one current link, no conflicting other-Story relationship",
    )


async def resolve_recap_origin_projection(
    session: AsyncSession, story: Story,
) -> tuple[NewsEvent | None, OriginProjectionDecision]:
    """Read-only. Loads `story.first_event_id`'s own `NewsEvent` row and EVERY current
    `NewsEventStoryLink` row for that event id, then classifies projection eligibility via
    `classify_origin_projection()`. Two bounded, indexed reads - never an unbounded scan, never a
    write. Callers should invoke this ONLY when the origin is already known to be absent from
    confirmed membership (the common/majority case never reaches this function at all - see
    `services/event_recap.py::build_event_recap_candidate()`'s own call site)."""
    event_stmt = select(NewsEvent).where(NewsEvent.id == story.first_event_id)
    declared_event = (await session.execute(event_stmt)).scalar_one_or_none()

    links_stmt = select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == story.first_event_id)
    all_links = list((await session.execute(links_stmt)).scalars().all())

    decision = classify_origin_projection(story, declared_event, all_links)
    return declared_event, decision


def build_effective_recap_members(
    origin_event: NewsEvent, confirmed_members: list[NewsEvent],
) -> list[NewsEvent]:
    """Pure. `[origin_event] + confirmed_members`, deduplicated by event id (property: idempotent -
    calling this again on its own output is a no-op), re-sorted using the EXACT same chronological
    key `services.recap_event.load_story_events()` already orders by (`published_at`, falling back
    to `collected_at` - the same coalesce this codebase already uses in `services/event_recap.py`'s
    own `last_event_at` computation and in `scripts/_recap_r2_7_anchor_lifecycle_forensic.py`'s own
    `earliest_confirmed_member()`, never a new convention). Required, not cosmetic: `services.
    recap_event.cluster_announcements()`'s own docstring assumes its input is ALREADY sorted
    chronologically - simply prepending `origin_event` would silently violate that invariant
    whenever the origin is not actually the earliest event by that key, so this always re-sorts the
    full combined set rather than assuming origin sorts first. Deterministic regardless of input
    ordering (`confirmed_members` in any order, or containing accidental duplicates, produces the
    same output) - `sorted()` over the deduplicated `dict` values, tie-broken by `event.id` for a
    total order even when two events share an identical timestamp."""
    by_id: dict[UUID, NewsEvent] = {}
    for event in (origin_event, *confirmed_members):
        by_id.setdefault(event.id, event)
    return sorted(by_id.values(), key=lambda e: (e.published_at or e.collected_at, e.id))
