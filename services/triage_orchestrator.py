"""Triage Orchestrator (Phase 9 M2 + M3): atomic NewsEvent ownership primitives, plus
the full find-work / claim / Triage / create_task() cycle that composes them.

Phase 9 Contract §2.3/§7 (all subsections). See scripts/validate_architecture.py's
triage-orchestrator-isolation rule for the mechanically-enforced dependency boundary:
no LLMGateway, no Capability layer, no provider SDK.

Both primitives (_claim_new_event, _acquire_recovery_ownership) are a single, atomic
conditional UPDATE plus an affected-row-count check - never a SELECT followed by a
separate UPDATE (Contract §7.2's explicit prohibition). They never commit or roll
back themselves - that is run_triage_cycle()'s responsibility, per the exact
transaction discipline documented on it below.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from database.models.news_event import EventStatus, NewsEvent
from database.models.news_source import NewsSource
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from database.session import async_session_factory
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services.cleaning import is_valid_title
from services.story_memory import (
    NEW_STORY,
    SEMANTIC_DUPLICATE,
    STORY_UPDATE,
    SUPPORTING_SOURCE,
    UNCERTAIN_MATCH,
    match_story,
)
from services.triage import decide_triage
from services.workflow_service import _find_active_task, create_task
from workflows.errors import DuplicateActiveTaskError

logger = logging.getLogger(__name__)

__all__ = [
    "_claim_new_event",
    "_select_recovery_candidates",
    "_acquire_recovery_ownership",
    "TriageCycleReport",
    "run_triage_cycle",
]


async def _claim_new_event(session: AsyncSession, event_id: UUID, *, now: datetime) -> bool:
    """Atomically claim one NEW NewsEvent -> PROCESSING (Contract §7.2 step 1).

    A single, atomic conditional UPDATE - `updated_at` is set explicitly to `now`
    (rather than relied upon implicitly via the column's own onupdate=func.now(),
    though the Contract confirms either is compliant) so a claim's exact timestamp
    is deterministic and test-controllable, not dependent on the database server's
    own wall clock.

    Returns True iff this call's own attempt affected the row (won the race - the
    event was still NEW). Returns False iff another instance already claimed it (or
    it was never NEW) - not an error; the caller MUST skip this event silently
    (Contract §18) and MUST NOT proceed to Triage or create_task() for it.

    The caller MUST commit immediately after a True result, before doing anything
    else for this event (Contract §7.5's "claim, already committed in step 1").
    """
    result = await session.execute(
        update(NewsEvent)
        .where(NewsEvent.id == event_id, NewsEvent.status == EventStatus.NEW)
        .values(status=EventStatus.PROCESSING, updated_at=now)
    )
    return result.rowcount == 1  # type: ignore[attr-defined]  # CursorResult at runtime for an UPDATE; Result[Any]'s stub doesn't expose it statically


async def _select_recovery_candidates(
    session: AsyncSession, *, now: datetime, staleness_threshold_seconds: int
) -> list[NewsEvent]:
    """Select PROCESSING NewsEvent rows eligible for stale-claim recovery (Contract
    §7.6's eligibility invariant - all three conditions required, evaluated in this
    exact precedence order):

        status == PROCESSING
        AND no EditorialTask already exists for it (any status - Phase 15 M1;
            was CREATED/RUNNING-only, see _find_active_task()'s own docstring
            for why that let a completed/failed sibling go unnoticed)
        AND (now - updated_at) > staleness_threshold_seconds

    `PROCESSING` + no-existing-task alone is NOT sufficient - a legitimately in-flight
    claim also transiently has no task yet; only once its age exceeds the
    threshold does it become a candidate. The existing-task check takes precedence over
    staleness and is evaluated first per candidate (an event with an existing task is
    never a candidate, regardless of how old `updated_at` is) - _find_active_task()
    is reused unmodified here (not reimplemented as a second, parallel query), exactly
    as the Contract requires; Phase 15 M1 fixed its one shared implementation, not this
    call site.

    Age is computed with strict inequality (`>`, not `>=`) - an event whose age
    exactly equals the threshold is treated as NOT yet stale (Contract §7.6 rule 3,
    the safe, non-recovery direction).
    """
    result = await session.execute(select(NewsEvent).where(NewsEvent.status == EventStatus.PROCESSING))
    threshold = timedelta(seconds=staleness_threshold_seconds)

    candidates: list[NewsEvent] = []
    for event in result.scalars().all():
        age = now - event.updated_at
        if age <= threshold:
            continue
        active_task = await _find_active_task(session, event.id, WorkflowType.NEWS_ANALYSIS)
        if active_task is not None:
            continue
        candidates.append(event)
    return candidates


async def _acquire_recovery_ownership(
    session: AsyncSession, event_id: UUID, observed_updated_at: datetime, *, now: datetime
) -> bool:
    """Atomically acquire recovery ownership of one stale PROCESSING NewsEvent
    (Contract §7.6's CAS mechanism), guarded by the exact `updated_at` value observed
    when the candidate was selected.

    A single, atomic conditional UPDATE: `status = 'PROCESSING' AND updated_at =
    observed_updated_at`, advancing `updated_at` to `now` on success. This guard
    condition is re-evaluated by the database atomically at execution time, so a
    successful acquisition IS the proof that status was still PROCESSING and
    updated_at had not moved since selection - the structural TOCTOU re-check the
    Contract describes, not a separate step.

    Returns True iff this call's own attempt affected the row (won). Returns False
    iff another instance already acquired ownership (or the row otherwise changed) -
    not an error; the caller MUST skip this event silently, exactly as for a lost
    NEW claim, and MUST NOT proceed to Triage or create_task() for it.

    The caller MUST commit immediately after a True result, before doing anything
    else for this event - identical discipline to _claim_new_event().
    """
    result = await session.execute(
        update(NewsEvent)
        .where(
            NewsEvent.id == event_id,
            NewsEvent.status == EventStatus.PROCESSING,
            NewsEvent.updated_at == observed_updated_at,
        )
        .values(updated_at=now)
    )
    return result.rowcount == 1  # type: ignore[attr-defined]  # CursorResult at runtime for an UPDATE; Result[Any]'s stub doesn't expose it statically


@dataclass
class TriageCycleReport:
    """Summary of a single Triage cycle, used for logging - mirrors
    services/collector.py's CollectionReport pattern."""

    events_claimed: int = 0
    events_recovered: int = 0
    tasks_created: int = 0
    claim_races_lost: int = 0
    duplicate_active_task_outcomes: int = 0
    events_rejected_invalid_title: int = 0
    other_failures: int = 0
    # Phase 18.10 M1/M2 (Story Memory, story_memory_mode != "off" only - all zero when "off").
    # `received_events` is a derived property, not a separate counter (see below).
    # `exact_duplicates` is intentionally NOT tracked here - it already exists, unchanged, as
    # services/collector.py::CollectionReport.duplicates_skipped (exact-hash dedup happens at
    # collection time, before an event ever reaches Triage) - cross-module composition, not
    # duplicated. `ignored_events` aliases events_rejected_invalid_title (also unchanged).
    story_new: int = 0
    story_updates: int = 0
    story_supporting_sources: int = 0
    story_semantic_duplicates: int = 0
    story_uncertain_matches: int = 0

    @property
    def received_events(self) -> int:
        return self.events_claimed + self.events_recovered


async def _apply_story_memory(session: AsyncSession, event: NewsEvent, report: TriageCycleReport) -> None:
    """Phase 18.10 M1/M2: match `event` against recent same-category stories
    (services/story_memory.py), persist the result as a NewsEventStoryLink row (never as columns
    on `event` itself - see database/models/news_event.py's own comment on why), and create/
    update the `stories` row as needed. Never raises for a well-formed event (mirrors
    decide_triage()'s own "MUST NOT raise for well-formed input" contract) - any failure here is
    a bug to fix, not a reason to fall back silently, so this deliberately does not have its own
    try/except; a real failure (including "table does not exist" if story_memory_mode is enabled
    before the Phase 18.10 migration has been applied) surfaces via `_run_phase_b()`'s own outer
    `except Exception` handler, exactly like a Triage or create_task() failure would - the event
    is left PROCESSING with no task, automatically eligible for recovery once the migration
    lands, never silently corrupted.

    Owns no commit of its own - all mutations here (the new/updated Story row, the new
    NewsEventStoryLink row) are committed atomically together with create_task()'s own
    EditorialTask insert, in the same transaction `_run_phase_b()` already manages."""
    signature, result = await match_story(session, title=event.title, category=event.category)

    if result.outcome == NEW_STORY:
        story = Story(
            id=uuid4(),
            title=event.title,
            category=event.category,
            entities=signature.entities,
            keywords=signature.keywords,
            topic_bucket=signature.topic_bucket,
            first_event_id=event.id,
            event_count=1,
        )
        session.add(story)
        story_id = story.id
        report.story_new += 1
    else:
        # STORY_UPDATE, SEMANTIC_DUPLICATE, or UNCERTAIN_MATCH - all three link the event to the
        # matched story for observability; only story_update/semantic_duplicate bump event_count
        # (an uncertain match is, definitionally, not confident enough to count as confirmed
        # continuation of that story's own event history).
        assert result.matched_story_id is not None  # guaranteed whenever outcome != NEW_STORY
        story_id = result.matched_story_id
        matched_story = await session.get(Story, result.matched_story_id)
        assert matched_story is not None  # match_story() only returns an id it just queried
        if result.outcome in (STORY_UPDATE, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE):
            matched_story.event_count += 1

        if result.outcome == STORY_UPDATE:
            report.story_updates += 1
        elif result.outcome == SUPPORTING_SOURCE:
            report.story_supporting_sources += 1
        elif result.outcome == SEMANTIC_DUPLICATE:
            report.story_semantic_duplicates += 1
        elif result.outcome == UNCERTAIN_MATCH:
            report.story_uncertain_matches += 1

    session.add(
        NewsEventStoryLink(
            news_event_id=event.id, story_id=story_id, match_type=result.outcome, match_score=result.confidence,
        )
    )

    logger.info(
        "phase18_10_story_memory_match",
        extra={
            "event_id": str(event.id),
            "outcome": result.outcome,
            "matched_story_id": str(story_id) if story_id else None,
            "confidence": result.confidence,
            "reason": result.similarity_reason,
        },
    )


async def _run_phase_b(session: AsyncSession, event_id: UUID, report: TriageCycleReport) -> None:
    """Phase B - post-claim processing (Contract §7.2 steps 2-3): load the event's
    NewsSource, run deterministic Triage, call the existing, unmodified create_task().

    Runs only after Phase A's commit has already succeeded (see run_triage_cycle()).
    Any exception here triggers `await session.rollback()` before returning -
    **binding invariant**: one event's post-claim failure MUST NOT leave the
    SQLAlchemy session in a failed-transaction state that breaks the processing of
    later events in the same batch. This rollback discards only this event's own
    (uncommitted) Phase B work; it cannot and does not undo Phase A's already-
    committed claim/ownership, which was finalized in its own, separate, prior
    transaction before this function was ever called. The residual state this
    produces on failure - PROCESSING, no active task - is the same, already-approved,
    staleness-gated recovery path this module already implements (§7.5, §7.6),
    not a new mechanism.
    """
    try:
        reference_now = datetime.now(timezone.utc)
        event = await session.get(NewsEvent, event_id)
        assert event is not None  # just claimed/recovered this exact event; it cannot have vanished

        # Phase 15 M1: cheap deterministic gate, before Triage/create_task() ever run - a
        # malformed title (raw HTML fragment, empty, bare URL) must not reach NEWS_ANALYSIS's
        # LLM calls just because it scored low; scoring is not a reliable filter for this
        # (Phase 15 M0: a malformed title scored 78 and was delivered). Defense-in-depth for
        # events collected before services.cleaning's own ingestion-time check existed.
        # Reuses the existing EventStatus.REJECTED lifecycle state - no new status, no new
        # table. decide_triage()'s own closed input contract is untouched: this check runs
        # before it and never becomes one of its inputs.
        if not is_valid_title(event.title):
            event.status = EventStatus.REJECTED
            await session.commit()
            report.events_rejected_invalid_title += 1
            logger.info(
                "phase15_event_rejected_invalid_title",
                extra={"event_id": str(event_id), "source_id": str(event.source_id)},
            )
            return

        # Phase 18.10 M1/M2: Story Memory, immediately after the title gate above - the same
        # "cheap deterministic check before any paid work" seam, since this too is fully
        # deterministic (no LLM call, services/story_memory.py's own module docstring). A no-op
        # when story_memory_mode == "off" (the default) - zero extra queries, byte-identical to
        # pre-18.10 behavior. In "shadow" (the only enabled mode this phase ships), the match
        # result is persisted for observability but NEVER suppresses create_task() below -
        # publication behavior is completely unchanged; "enforce"'s suppression path is not
        # implemented in this phase.
        if settings.story_memory_mode != "off":
            await _apply_story_memory(session, event, report)

        source = await session.get(NewsSource, event.source_id)
        reliability_score = source.reliability_score if source is not None else None

        triage_result = decide_triage(
            event.published_at, event.collected_at, reliability_score, reference_now
        )
        logger.info(
            "phase9_triage_decision",
            extra={
                "event_id": str(event_id),
                "source_id": str(event.source_id),
                "reference_now": reference_now.isoformat(),
                **triage_result.explanation,
            },
        )

        command = EditorialTaskCreate(
            event_id=event_id,
            workflow_type=WorkflowType.NEWS_ANALYSIS,
            priority=triage_result.priority,
        )
        await create_task(session, command)
        report.tasks_created += 1

    except DuplicateActiveTaskError:
        # Contract §7.5 point 2: not a failure - another instance already created the
        # active task for this event (a retry, or the narrow "stolen healthy worker"
        # case §7.6 discloses). The event's PROCESSING status is now genuinely
        # accurate; nothing further is required. Rolled back anyway, defensively and
        # uniformly with the branch below, even though no SQL statement actually
        # failed here (create_task()'s own _find_active_task() check is a plain
        # SELECT) - this avoids a fragile special case.
        report.duplicate_active_task_outcomes += 1
        logger.info("phase9_duplicate_active_task", extra={"event_id": str(event_id)})
        await session.rollback()

    except Exception:
        # Any other failure (source/event loading, Triage - which MUST NOT raise for
        # well-formed input, or create_task() itself): the event remains PROCESSING
        # with no active task, MUST be logged, and MUST NOT be treated as processed
        # (Contract §18). It is automatically eligible for recovery on a future pass,
        # once stale.
        report.other_failures += 1
        logger.exception("phase9_triage_phase_b_failed", extra={"event_id": str(event_id)})
        await session.rollback()


async def run_triage_cycle(
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
) -> TriageCycleReport:
    """Run one Triage pass over every eligible NewsEvent (Contract §2.3/§7).

    One shared AsyncSession for the whole batch (mirroring services/collector.py's
    single-session-per-cycle shape), but - unlike collector.py, which commits once per
    *source* (which may hold many items) - this function commits and rolls back once
    per *event*, because each event's ownership claim, not the batch as a whole, is
    the atomic unit of correctness this Contract defines.

    For each eligible event, exactly two phases:

    Phase A - ownership acquisition (commit-or-skip, never partial):
        Normal path: _claim_new_event(); on success, `await session.commit()`
        *immediately* - this is the durable fact Contract §7.5 calls "the claim,
        already committed in step 1." On failure (lost the race), skip silently -
        no exception, no log entry (Contract §18's "not an error" classification) -
        and do NOT proceed to Phase B.
        Recovery path: identical shape, via _acquire_recovery_ownership().
        A losing claimant, either path, MUST NOT run Triage or call create_task() -
        enforced structurally here: Phase B is only ever reached after a successful
        Phase A commit.

    Phase B - post-claim processing: see _run_phase_b()'s own docstring for its
    commit/rollback discipline.

    No distributed transaction, no cross-session coordination, and no change to
    session ownership is introduced anywhere in this discipline - every commit/
    rollback is a plain, single-session operation on the one AsyncSession this
    function owns for the whole batch; create_task()'s own internal commit is
    untouched and unmodified.
    """
    report = TriageCycleReport()
    threshold_seconds = settings.stale_processing_threshold_seconds

    async with session_factory() as session:
        now = datetime.now(timezone.utc)

        new_result = await session.execute(select(NewsEvent).where(NewsEvent.status == EventStatus.NEW))
        new_event_ids = [event.id for event in new_result.scalars().all()]

        recovery_candidates = await _select_recovery_candidates(
            session, now=now, staleness_threshold_seconds=threshold_seconds
        )
        recovery_targets = [(event.id, event.updated_at) for event in recovery_candidates]

        for event_id in new_event_ids:
            claim_now = datetime.now(timezone.utc)
            won = await _claim_new_event(session, event_id, now=claim_now)
            if not won:
                report.claim_races_lost += 1
                continue
            await session.commit()
            report.events_claimed += 1
            await _run_phase_b(session, event_id, report)

        for event_id, observed_updated_at in recovery_targets:
            recovery_now = datetime.now(timezone.utc)
            won = await _acquire_recovery_ownership(session, event_id, observed_updated_at, now=recovery_now)
            if not won:
                report.claim_races_lost += 1
                continue
            await session.commit()
            report.events_recovered += 1
            await _run_phase_b(session, event_id, report)

    logger.info(
        "phase9_triage_cycle_finished",
        extra={
            "events_claimed": report.events_claimed,
            "events_recovered": report.events_recovered,
            "tasks_created": report.tasks_created,
            "claim_races_lost": report.claim_races_lost,
            "duplicate_active_task_outcomes": report.duplicate_active_task_outcomes,
            "events_rejected_invalid_title": report.events_rejected_invalid_title,
            "other_failures": report.other_failures,
            "received_events": report.received_events,
            "story_new": report.story_new,
            "story_updates": report.story_updates,
            "story_supporting_sources": report.story_supporting_sources,
            "story_semantic_duplicates": report.story_semantic_duplicates,
            "story_uncertain_matches": report.story_uncertain_matches,
        },
    )
    return report
