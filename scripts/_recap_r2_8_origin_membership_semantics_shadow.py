"""NINJA PULSE RECAP Phase R2.8 - Story Origin/Membership Semantics Shadow (READ ONLY).

CANONICAL R2.8 diagnostic as of this checkpoint - supersedes
`scripts/_recap_r2_8_anchor_repair_shadow_scaffold.py` (kept, but marked deprecated in its own
docstring, pointing back here - see that file's own header for why it is retained rather than
deleted: no other code references it, and its transcript remains useful forensic history of the
pre-R2.7 design that this checkpoint's own production evidence disproved).

======================================================================================
WHY THIS FILE EXISTS (R2.7 recap, treated as FROZEN production evidence this checkpoint)
======================================================================================
R2.7 (`scripts/_recap_r2_7_anchor_lifecycle_forensic.py`) proved, against a real (unmodified)
production database, that 106/300 recently-updated Stories have a declared `first_event_id` that
is absent from `services.recap_event.load_story_events()`'s own confirmed-membership definition -
ALWAYS because that event's own `NewsEventStoryLink.match_type` is `RELATED_STORY` (91/106) or
`UNCERTAIN_MATCH` (15/106), the two outcomes `services.triage_orchestrator._apply_story_memory()`
(Phase 20 M11.1, Story Identity Invariant) deliberately uses to justify creating a BRAND NEW Story
for that same event. R2.7 also proved, via its own hypothetical-anchor simulation, that blindly
substituting "the earliest CURRENT confirmed member" as a repair anchor is UNSAFE for 2/16 testable
cases (a broad "large language model..." research cluster, and an unrelated Russian-domains/web-
standards/fastest-star cluster) - both fail the REAL, frozen `evaluate_recap_story_integrity()`
when tested this way. This checkpoint does not revive that rejected repair rule.

======================================================================================
WHAT THIS FILE DOES
======================================================================================
For every anchor-missing Story (identical population `scripts._recap_r2_7_anchor_lifecycle_
forensic._scan_anchor_missing_stories()` finds - imported, not duplicated), computes four SHADOW
Story Integrity / RECAP-candidate semantic models, side by side, using only the REAL, frozen,
unmodified `services.recap_event.evaluate_recap_story_integrity()` and the REAL, frozen
`services.event_recap.build_event_recap_candidate()` (for CURRENT only - the other three models use
`_shadow_build_candidate()` below, a pure, LOCAL, read-only re-derivation over an EXPLICIT event
list, never a mutated Story/DB row - see its own docstring for exactly why `build_event_recap_
candidate()` itself cannot be reused unmodified for those three: it always re-derives membership by
querying `NewsEventStoryLink` directly via `load_story_events(session, story.id)`, so there is no
way to hand it a hypothetical "origin is also a member" event list without either mutating the real
link rows (forbidden) or writing this same local re-derivation):

    CURRENT              - real production semantics, unmodified. Always fails today for exactly
                            this population (module docstring's own contract in
                            services/event_recap.py::build_event_recap_candidate()).
    ORIGIN_ANCHOR_ONLY_A1 - anchor=origin event; members=CURRENT CONFIRMED MEMBERS ONLY (unchanged).
                            Integrity-only variant (undefined RECAP-candidate shadow - see below).
    ORIGIN_ANCHOR_ONLY_A2 - anchor=origin event; members=[origin] + current confirmed members.
                            Same Integrity result as A1 (proven below - both feed
                            `evaluate_recap_story_integrity()`, which ALWAYS internally computes
                            `others = [e for e in member_events if e.id != anchor_event.id]`, so a
                            redundant anchor-in-members duplicate is unconditionally filtered out
                            before any comparison happens); DIFFERS from A1 only in whether a
                            well-defined RECAP-candidate shadow exists (A2's event list legitimately
                            contains its own anchor, so `cluster_announcements()`/
                            `count_unique_sources()` can run on it; A1's cannot, without an anchor
                            event that both `build_event_recap_candidate()` and this shadow's own
                            `_shadow_build_candidate()` require by construction).
    ORIGIN_IS_OWN_MEMBER  - same (anchor, members) shape as A2, but ONLY computed when the strict,
                            fail-closed origin-projection invariants below all hold. Never a
                            production decision - see `OriginProjectionDecision` and Part H's own
                            reason codes.

Also reports, per anchor-missing Story: `Story.event_count` (declared) vs the ACTUAL current link
count for the declared event vs the actual confirmed-member count (Part F/event_count forensic -
documented, never fixed here).

======================================================================================
FAIL-CLOSED ORIGIN-PROJECTION ELIGIBILITY (Part H)
======================================================================================
`classify_origin_projection()` below NEVER infers history the schema cannot prove (mirrors R2.7's
own "PROVEN/STRONGLY INFERRED/UNKNOWN" discipline). Reason codes:

    ORIGIN_EVENT_MISSING       - declared first_event_id's NewsEvent row does not exist.
    ORIGIN_LINK_MISSING        - the event exists but has NO NewsEventStoryLink row at all.
    ORIGIN_LINK_WRONG_STORY    - the event's one current link points to a DIFFERENT Story (proves a
                                  real, current conflicting relationship - never overridden).
    ORIGIN_LINK_AMBIGUOUS      - more than one current link row exists for the event. PROVEN
                                  unreachable given the current schema (`news_event_id` is the
                                  PRIMARY KEY of `news_event_story_links` -
                                  database/models/story_link.py's own explicit "at most one link per
                                  event... hard database constraint," not an application convention)
                                  - kept anyway, defense-in-depth, never assumed away.
    ORIGIN_MATCH_TYPE_UNEXPECTED - the event's own link exists, points to THIS Story, but its
                                  match_type is neither a confirmed-membership type nor RELATED_STORY/
                                  UNCERTAIN_MATCH (would indicate a taxonomy this checkpoint does not
                                  know about - fail closed, never guess).
    ORIGIN_PROJECTION_NOT_NEEDED - the event's own link IS already a confirmed-membership type -
                                  this Story was not actually anchor-missing in the first place (can
                                  only happen if the caller's own scan population is stale/wrong;
                                  reported for completeness, never expected in practice given this
                                  script always re-derives from the SAME scan).
    ORIGIN_PROJECTION_ELIGIBLE - all invariants hold: event exists; exactly one current link;
                                  that link points to THIS Story; match_type is RELATED_STORY or
                                  UNCERTAIN_MATCH; no conflicting current other-Story relationship.

`ORIGIN_ANCHOR_ONLY_A1`/`A2` are computed whenever the origin event itself exists in the DB
(regardless of eligibility - they never change the confirmed-membership SET, only the anchor used
for a read-only Integrity comparison, so the strict invariants above are Part H's own explicit
extra requirement for `ORIGIN_IS_OWN_MEMBER` specifically, not for these two exploratory variants).
`ORIGIN_IS_OWN_MEMBER` is computed ONLY when `classify_origin_projection()` returns
ORIGIN_PROJECTION_ELIGIBLE.

======================================================================================
SAFETY (identical read-only pattern to every prior R2 diagnostic this session)
======================================================================================
SET TRANSACTION READ ONLY + SHOW transaction_read_only verification, SET LOCAL statement_timeout,
one transaction, rollback in `finally`, no writes, no network beyond the DB read, no LLM, no
Telegram, no worker. Every "model" here is a pure computation over already-loaded plain NewsEvent/
Story objects (or, for `ORIGIN_ANCHOR_ONLY`/`ORIGIN_IS_OWN_MEMBER`/`ORIGIN_PROJECTION`, a plain
Python-side comparison of already-loaded link rows) - no `session.add()`, no `session.delete()`, no
`.execute()` of anything but SELECT, no `commit()`/`flush()` anywhere in this module (see
`tests/test_recap_r2_8_origin_membership_semantics_shadow.py`'s own write-safety-audit test, which
asserts this via source inspection, never by trusting this docstring alone).

Does NOT modify `services/recap_event.py`, `services/story_memory.py`, `services/fact_safety.py`,
`services/event_recap.py`, or `services/triage_orchestrator.py` - all READ-ONLY references this
checkpoint, as every prior R2 checkpoint's own docstring already states for those five modules.

Designed for a FUTURE, separately-authorized production mount (same transaction discipline as
R2.6/R2.7 already establish) - NOT executed against production this session; no VPS/production DB
access exists this session at all.

Use (future, once authorized): `docker compose run --rm --no-deps backend python
scripts/_recap_r2_8_origin_membership_semantics_shadow.py`
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from core.config import settings  # noqa: E402
from database.models.news_event import NewsEvent  # noqa: E402
from database.models.story import Story  # noqa: E402
from database.models.story_link import NewsEventStoryLink  # noqa: E402
from scripts._recap_r2_7_anchor_lifecycle_forensic import (  # noqa: E402
    earliest_confirmed_member,
    _scan_anchor_missing_stories,
)
from services.event_recap import _evidence_reference_identity, build_event_recap_candidate  # noqa: E402
from services.recap_event import (  # noqa: E402
    StoryIntegrityResult,
    _CONFIRMED_MEMBERSHIP_MATCH_TYPES,
    cluster_announcements,
    count_unique_sources,
    evaluate_recap_readiness,
    evaluate_recap_story_integrity,
    load_canonical_urls_for_events,
)
from services.story_memory import RELATED_STORY, UNCERTAIN_MATCH  # noqa: E402

OUTPUT_PATH = Path("/tmp/recap_r2_8_origin_membership_semantics_shadow.txt")
STATEMENT_TIMEOUT_MS = 30_000

# --- Part H reason codes (plain strings - mirrors this codebase's own established closed-
# vocabulary convention, e.g. services/story_memory.py's own NEW_STORY/RELATED_STORY/... - never a
# Python Enum class here) ---
ORIGIN_EVENT_MISSING = "ORIGIN_EVENT_MISSING"
ORIGIN_LINK_MISSING = "ORIGIN_LINK_MISSING"
ORIGIN_LINK_WRONG_STORY = "ORIGIN_LINK_WRONG_STORY"
ORIGIN_LINK_AMBIGUOUS = "ORIGIN_LINK_AMBIGUOUS"
ORIGIN_MATCH_TYPE_UNEXPECTED = "ORIGIN_MATCH_TYPE_UNEXPECTED"
ORIGIN_PROJECTION_ELIGIBLE = "ORIGIN_PROJECTION_ELIGIBLE"
ORIGIN_PROJECTION_NOT_NEEDED = "ORIGIN_PROJECTION_NOT_NEEDED"

# --- Part L classification codes ---
ZERO_CONFIRMED_ORIGIN_ONLY = "ZERO_CONFIRMED_ORIGIN_ONLY"
ORIGIN_PLUS_COHERENT_MEMBERS = "ORIGIN_PLUS_COHERENT_MEMBERS"
ORIGIN_PLUS_INCOHERENT_MEMBERS = "ORIGIN_PLUS_INCOHERENT_MEMBERS"
UNSAFE_ORIGIN_PROJECTION = "UNSAFE_ORIGIN_PROJECTION"
UNEXPECTED_STATE = "UNEXPECTED_STATE"


@dataclass(frozen=True)
class OriginProjectionDecision:
    """Part H - the fail-closed eligibility verdict for treating a Story's declared, non-confirmed
    `first_event_id` as its own member for `ORIGIN_IS_OWN_MEMBER` purposes. Never mutates anything;
    a pure function of already-loaded rows."""

    reason_code: str
    eligible: bool
    detail: str


def classify_origin_projection(
    story: Story,
    declared_event: NewsEvent | None,
    all_current_links_for_declared_event: list[NewsEventStoryLink],
) -> OriginProjectionDecision:
    """Part H. `all_current_links_for_declared_event` must be EVERY current `NewsEventStoryLink`
    row for `story.first_event_id` (not pre-filtered to `story.id`) - the wrong-story/ambiguous
    checks below need to see the full set to prove their verdicts, never assume them."""
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
        # PROVEN unreachable given news_event_id being the links table's PRIMARY KEY (see this
        # module's own docstring) - kept as defense-in-depth, never assumed away.
        return OriginProjectionDecision(
            ORIGIN_LINK_AMBIGUOUS, False, f"{len(own_links)} current link rows found for the declared event",
        )

    own_link = own_links[0]
    if own_link.match_type in _CONFIRMED_MEMBERSHIP_MATCH_TYPES:
        return OriginProjectionDecision(
            ORIGIN_PROJECTION_NOT_NEEDED,
            False,
            f"declared event's own link match_type={own_link.match_type!r} is already confirmed membership",
        )
    if own_link.match_type not in (RELATED_STORY, UNCERTAIN_MATCH):
        return OriginProjectionDecision(
            ORIGIN_MATCH_TYPE_UNEXPECTED,
            False,
            f"declared event's own link match_type={own_link.match_type!r} is neither confirmed nor "
            f"RELATED_STORY/UNCERTAIN_MATCH - unknown taxonomy, refusing to guess",
        )
    return OriginProjectionDecision(
        ORIGIN_PROJECTION_ELIGIBLE,
        True,
        f"declared event's own link match_type={own_link.match_type!r}, points to this Story, exactly one "
        "current link, no conflicting other-Story relationship",
    )


def evaluate_origin_anchor_only(
    origin_event: NewsEvent, confirmed_members: list[NewsEvent],
) -> tuple[StoryIntegrityResult, StoryIntegrityResult]:
    """Part G - ORIGIN_ANCHOR_ONLY A1/A2. Both call the REAL, frozen, unmodified
    `evaluate_recap_story_integrity()` - A1 with `confirmed_members` verbatim, A2 with
    `[origin_event] + confirmed_members`. PROVEN to always return byte-identical
    `StoryIntegrityResult`s (never asserted blindly - `evaluate_recap_story_integrity()`'s own
    algorithm unconditionally computes `others = [e for e in member_events if e.id !=
    anchor_event.id]` before doing anything else, so a redundant anchor-in-members duplicate is
    filtered out identically either way; `tests/test_recap_r2_8_origin_membership_semantics_shadow.
    py` asserts this equality directly, every fixture, rather than trusting this docstring). Kept
    as two separate calls (not one, deduplicated) because the checkpoint's own instruction ("Do NOT
    silently choose between them") requires both to be visible in the report even though they
    coincide at THIS layer - they diverge at the RECAP-candidate-shadow layer (`shadow_build_
    candidate()` below), where A1 has no well-defined member-event list to build a candidate from
    at all (its origin event is not part of `confirmed_members`) and A2 does."""
    a1 = evaluate_recap_story_integrity(origin_event, confirmed_members)
    a2 = evaluate_recap_story_integrity(origin_event, [origin_event, *confirmed_members])
    return a1, a2


@dataclass(frozen=True)
class RecapCandidateShadow:
    """Part N - structural-only shadow result. Never includes announcement text, verified-fact
    values, media, or anything LLM-adjacent - deliberately narrower than the real
    `EventRecapCandidate` (spec's own "report only deterministic structural differences").
    `publishable` is always False here (this dataclass has no field for it at all - never even
    representable as True, mirroring services/event_recap.py's own module-level "R2 never sets
    publishable=True" invariant one level more strictly)."""

    rejected: bool
    rejection_reasons: list[str]
    anchor_event_id: UUID | None
    member_count: int
    announcement_count: int | None
    unique_source_count: int | None
    evidence_reference_count: int | None
    story_integrity_eligible: bool | None
    story_integrity_reasons: list[str]
    readiness_state: str | None
    readiness_ready: bool | None
    force_shadow: bool = True


async def shadow_build_candidate(
    session: AsyncSession, anchor: NewsEvent, members: list[NewsEvent], *, now: datetime,
) -> RecapCandidateShadow:
    """Part N. A LOCAL, pure(ish) re-derivation of `services.event_recap.build_event_recap_
    candidate()`'s own deterministic pipeline (Story Integrity -> readiness; announcement
    clustering/source counting/evidence-reference counting only as far as needed for the
    structural fields Part N asks for) over an EXPLICIT `(anchor, members)` pair, never a Story
    row or `load_story_events(session, story.id)` query - see this module's own top docstring for
    exactly why the real `build_event_recap_candidate()` cannot be reused unmodified for the
    origin-projected models. Every function called here (`evaluate_recap_story_integrity`,
    `cluster_announcements`, `count_unique_sources`, `evaluate_recap_readiness`, `load_canonical_
    urls_for_events`, `_evidence_reference_identity`) is the REAL, frozen, unmodified
    `services/recap_event.py`/`services/event_recap.py` function - reused, never reimplemented.
    `force_shadow` is always True here (mirrors `build_event_recap_candidate(..., force_shadow=
    True)` - this is exploratory-only, never a readiness/publishable decision); `publishable` is
    not even a field on `RecapCandidateShadow` (see its own docstring)."""
    if anchor.id not in {e.id for e in members}:
        return RecapCandidateShadow(
            rejected=True,
            rejection_reasons=["anchor not present in the given member-event list - no well-defined candidate"],
            anchor_event_id=anchor.id, member_count=len(members), announcement_count=None,
            unique_source_count=None, evidence_reference_count=None, story_integrity_eligible=None,
            story_integrity_reasons=[], readiness_state=None, readiness_ready=None,
        )

    integrity = evaluate_recap_story_integrity(anchor, members)
    if not integrity.eligible:
        return RecapCandidateShadow(
            rejected=True, rejection_reasons=list(integrity.reasons),
            anchor_event_id=anchor.id, member_count=len(members), announcement_count=None,
            unique_source_count=None, evidence_reference_count=None,
            story_integrity_eligible=False, story_integrity_reasons=list(integrity.reasons),
            readiness_state=None, readiness_ready=None,
        )

    clusters = cluster_announcements(members)
    unique_sources = count_unique_sources(members)
    last_event_at = max((e.published_at or e.collected_at for e in members), default=now)
    readiness = evaluate_recap_readiness(
        event_count=len(members), announcement_count=len(clusters), unique_source_count=unique_sources,
        last_event_at=last_event_at, now=now, research_complete=False, unresolved_conflict_count=0,
        story_integrity_eligible=integrity.eligible, story_integrity_reasons=integrity.reasons,
    )
    canonical_urls = await load_canonical_urls_for_events(session, [e.id for e in members])
    evidence_reference_count = len(
        {_evidence_reference_identity(e, canonical_urls.get(e.id)) for e in members}
    )

    return RecapCandidateShadow(
        rejected=False, rejection_reasons=[],
        anchor_event_id=anchor.id, member_count=len(members), announcement_count=len(clusters),
        unique_source_count=unique_sources, evidence_reference_count=evidence_reference_count,
        story_integrity_eligible=integrity.eligible, story_integrity_reasons=list(integrity.reasons),
        readiness_state=readiness.state, readiness_ready=readiness.ready,
    )


def classify_semantic_shape(
    confirmed_members: list[NewsEvent],
    projection: OriginProjectionDecision,
    origin_is_own_member_integrity: StoryIntegrityResult | None,
) -> str:
    """Part L classification. Never a substitute for the raw per-model results reported alongside
    it - purely a compact summary label."""
    if not projection.eligible:
        if projection.reason_code == ORIGIN_PROJECTION_NOT_NEEDED:
            return UNEXPECTED_STATE
        return UNSAFE_ORIGIN_PROJECTION
    if not confirmed_members:
        return ZERO_CONFIRMED_ORIGIN_ONLY
    if origin_is_own_member_integrity is None:
        return UNEXPECTED_STATE
    return ORIGIN_PLUS_COHERENT_MEMBERS if origin_is_own_member_integrity.eligible else ORIGIN_PLUS_INCOHERENT_MEMBERS


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


async def _all_current_links_for_event(session: AsyncSession, event_id: UUID) -> list[NewsEventStoryLink]:
    stmt = select(NewsEventStoryLink).where(NewsEventStoryLink.news_event_id == event_id)
    return list((await session.execute(stmt)).scalars().all())


async def _process_story(
    session: AsyncSession, story: Story, confirmed_members: list[NewsEvent], *, now: datetime,
) -> dict:
    """One anchor-missing Story -> the full R2.8 comparison bundle. Read-only; never mutates
    `story`, `confirmed_members`, or any DB row."""
    event_stmt = select(NewsEvent).where(NewsEvent.id == story.first_event_id)
    declared_event = (await session.execute(event_stmt)).scalar_one_or_none()
    all_links = await _all_current_links_for_event(session, story.first_event_id)

    projection = classify_origin_projection(story, declared_event, all_links)

    current_result = await build_event_recap_candidate(session, story, force_shadow=True, now=now)

    result: dict = {
        "story": story,
        "declared_event": declared_event,
        "confirmed_member_count": len(confirmed_members),
        "declared_event_count": story.event_count,
        "actual_link_count_for_declared_event": len(all_links),
        "projection": projection,
        "current_rejected": current_result.rejected,
        "current_rejection_reasons": current_result.rejection_reasons,
        "origin_anchor_only_a1": None,
        "origin_anchor_only_a2": None,
        "origin_anchor_only_a2_candidate": None,
        "origin_is_own_member_integrity": None,
        "origin_is_own_member_candidate": None,
    }

    if declared_event is not None:
        a1, a2 = evaluate_origin_anchor_only(declared_event, confirmed_members)
        result["origin_anchor_only_a1"] = a1
        result["origin_anchor_only_a2"] = a2
        result["origin_anchor_only_a2_candidate"] = await shadow_build_candidate(
            session, declared_event, [declared_event, *confirmed_members], now=now,
        )

        if projection.eligible:
            members = [declared_event, *confirmed_members]
            result["origin_is_own_member_integrity"] = evaluate_recap_story_integrity(declared_event, members)
            result["origin_is_own_member_candidate"] = await shadow_build_candidate(
                session, declared_event, members, now=now,
            )

    result["classification"] = classify_semantic_shape(
        confirmed_members, projection, result["origin_is_own_member_integrity"],
    )
    return result


def _fmt_integrity(label: str, integrity: StoryIntegrityResult | None) -> list[str]:
    if integrity is None:
        return [f"  {label}: N/A"]
    ratio = integrity.metrics.get("anchor_coherent_ratio")
    return [
        f"  {label}: eligible={integrity.eligible} anchor_coherent_ratio={ratio} reasons={integrity.reasons}",
    ]


def _fmt_candidate(label: str, candidate: RecapCandidateShadow | None) -> list[str]:
    if candidate is None:
        return [f"  {label}: N/A"]
    if candidate.rejected:
        return [f"  {label}: rejected=True reasons={candidate.rejection_reasons}"]
    return [
        f"  {label}: rejected=False anchor={candidate.anchor_event_id} member_count={candidate.member_count} "
        f"announcement_count={candidate.announcement_count} unique_source_count={candidate.unique_source_count} "
        f"evidence_reference_count={candidate.evidence_reference_count} "
        f"readiness_state={candidate.readiness_state} readiness_ready={candidate.readiness_ready} "
        f"force_shadow={candidate.force_shadow} publishable=False",
    ]


async def main() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    now = datetime.now(timezone.utc)
    try:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            await _verify_read_only(conn)
            session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)

            stories_scanned, missing = await _scan_anchor_missing_stories(session)
            lines = [
                "NINJA PULSE RECAP Phase R2.8 - Story Origin/Membership Semantics Shadow (READ ONLY)",
                f"Stories scanned: {stories_scanned}  Anchor-missing found: {len(missing)}",
                "",
            ]

            agg: dict = {
                "root_related_story_count": 0, "root_uncertain_match_count": 0,
                "unexpected_root_match_type_count": 0,
                "zero_confirmed_count": 0, "one_plus_confirmed_count": 0,
                "origin_projection_eligible_count": 0, "origin_projection_ineligible_count": 0,
                "CURRENT_PASS": 0, "CURRENT_FAIL": 0,
                "ORIGIN_ANCHOR_ONLY_A1_PASS": 0, "ORIGIN_ANCHOR_ONLY_A1_FAIL": 0,
                "ORIGIN_ANCHOR_ONLY_A2_PASS": 0, "ORIGIN_ANCHOR_ONLY_A2_FAIL": 0,
                "ORIGIN_IS_OWN_MEMBER_PASS": 0, "ORIGIN_IS_OWN_MEMBER_FAIL": 0,
                "projection_recovers_zero_confirmed_count": 0,
                "projection_preserves_incoherent_fail_count": 0,
                "unexpected_semantic_divergence_count": 0,
                "INCOHERENT_CURRENT_STORIES_THAT_BECOME_FALSE_PASS": 0,
                ZERO_CONFIRMED_ORIGIN_ONLY: 0, ORIGIN_PLUS_COHERENT_MEMBERS: 0,
                ORIGIN_PLUS_INCOHERENT_MEMBERS: 0, UNSAFE_ORIGIN_PROJECTION: 0, UNEXPECTED_STATE: 0,
            }

            for story, confirmed in missing:
                bundle = await _process_story(session, story, confirmed, now=now)
                projection: OriginProjectionDecision = bundle["projection"]
                declared_event = bundle["declared_event"]

                if declared_event is not None:
                    own_link_types = [
                        link.match_type
                        for link in await _all_current_links_for_event(session, story.first_event_id)
                        if link.story_id == story.id
                    ]
                    if own_link_types == [RELATED_STORY]:
                        agg["root_related_story_count"] += 1
                    elif own_link_types == [UNCERTAIN_MATCH]:
                        agg["root_uncertain_match_count"] += 1
                    elif own_link_types and own_link_types[0] not in _CONFIRMED_MEMBERSHIP_MATCH_TYPES:
                        agg["unexpected_root_match_type_count"] += 1

                if bundle["confirmed_member_count"] == 0:
                    agg["zero_confirmed_count"] += 1
                else:
                    agg["one_plus_confirmed_count"] += 1

                if projection.eligible:
                    agg["origin_projection_eligible_count"] += 1
                else:
                    agg["origin_projection_ineligible_count"] += 1

                agg["CURRENT_FAIL" if bundle["current_rejected"] else "CURRENT_PASS"] += 1

                a1 = bundle["origin_anchor_only_a1"]
                a2 = bundle["origin_anchor_only_a2"]
                if a1 is not None:
                    agg["ORIGIN_ANCHOR_ONLY_A1_PASS" if a1.eligible else "ORIGIN_ANCHOR_ONLY_A1_FAIL"] += 1
                if a2 is not None:
                    agg["ORIGIN_ANCHOR_ONLY_A2_PASS" if a2.eligible else "ORIGIN_ANCHOR_ONLY_A2_FAIL"] += 1
                    if a1 is not None and a1.eligible != a2.eligible:
                        agg["unexpected_semantic_divergence_count"] += 1

                oim = bundle["origin_is_own_member_integrity"]
                if oim is not None:
                    agg["ORIGIN_IS_OWN_MEMBER_PASS" if oim.eligible else "ORIGIN_IS_OWN_MEMBER_FAIL"] += 1
                    if bundle["confirmed_member_count"] == 0 and oim.eligible:
                        agg["projection_recovers_zero_confirmed_count"] += 1
                    if bundle["confirmed_member_count"] > 0 and not oim.eligible:
                        agg["projection_preserves_incoherent_fail_count"] += 1
                    # Safety metric (target 0 - Part M): a story where the origin-projected model
                    # reports PASS while the SAME frozen evaluator, given the SAME confirmed
                    # members but the (proven-unsafe, R2.7) earliest-confirmed-member anchor
                    # instead, would report FAIL - i.e. origin projection alone is what flips the
                    # verdict for a group R2.7's own hypothesis already flags as incoherent.
                    if oim.eligible and confirmed:
                        alt_anchor = earliest_confirmed_member(confirmed)
                        alt_integrity = evaluate_recap_story_integrity(alt_anchor, confirmed)
                        if not alt_integrity.eligible:
                            agg["INCOHERENT_CURRENT_STORIES_THAT_BECOME_FALSE_PASS"] += 1

                agg[bundle["classification"]] += 1

                lines += [
                    f"Story {story.id}: {story.title!r}",
                    f"  declared_first_event_id={story.first_event_id} "
                    f"declared_event_count={bundle['declared_event_count']} "
                    f"actual_link_count_for_declared_event={bundle['actual_link_count_for_declared_event']} "
                    f"confirmed_member_count={bundle['confirmed_member_count']}",
                    f"  origin_projection: reason_code={projection.reason_code} eligible={projection.eligible} "
                    f"detail={projection.detail}",
                    f"  CURRENT: rejected={bundle['current_rejected']} reasons={bundle['current_rejection_reasons']}",
                ]
                lines += _fmt_integrity("ORIGIN_ANCHOR_ONLY_A1 (integrity)", a1)
                lines += _fmt_integrity("ORIGIN_ANCHOR_ONLY_A2 (integrity)", a2)
                lines += _fmt_candidate("ORIGIN_ANCHOR_ONLY_A2 (candidate shadow)", bundle["origin_anchor_only_a2_candidate"])
                lines += _fmt_integrity("ORIGIN_IS_OWN_MEMBER (integrity)", oim)
                lines += _fmt_candidate("ORIGIN_IS_OWN_MEMBER (candidate shadow)", bundle["origin_is_own_member_candidate"])
                lines += [f"  classification={bundle['classification']}", ""]

            lines += ["=" * 100, "AGGREGATE METRICS", "=" * 100, f"stories_scanned={stories_scanned}",
                      f"anchor_missing_total={len(missing)}"]
            lines += [f"{k}={v}" for k, v in agg.items()]

            OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
            print(f"Wrote {OUTPUT_PATH} (missing_anchor_total={len(missing)})")
        finally:
            await trans.rollback()
            await conn.close()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
