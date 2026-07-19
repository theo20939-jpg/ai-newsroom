"""Triage Orchestrator: atomic NewsEvent ownership primitives (Phase 9 M2).

Phase 9 Contract §2.3/§7.2/§7.5/§7.6. This module currently implements only the
persistence/concurrency primitives - the atomic NEW claim and the stale-PROCESSING
recovery-ownership CAS - never Triage itself, never create_task(), never a script
entry point (those are M3). See scripts/validate_architecture.py's
triage-orchestrator-isolation rule for the mechanically-enforced dependency boundary:
no LLMGateway, no Capability layer, no provider SDK.

Both primitives are a single, atomic conditional UPDATE plus an affected-row-count
check - never a SELECT followed by a separate UPDATE (Contract §7.2's explicit
prohibition). Commits are the caller's responsibility: the Contract's own
"claim, already committed in step 1" premise (§7.5, §7.6) requires the caller to
commit immediately after a True result, before any further work for that event -
this module never commits or rolls back itself, mirroring
services/workflow_service.py's own _find_active_task() session-lifecycle
convention exactly.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import EventStatus, NewsEvent
from schemas.workflow import WorkflowType
from services.workflow_service import _find_active_task

__all__ = ["_claim_new_event", "_select_recovery_candidates", "_acquire_recovery_ownership"]


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
        AND no active (CREATED/RUNNING) EditorialTask exists for it
        AND (now - updated_at) > staleness_threshold_seconds

    `PROCESSING` + no-active-task alone is NOT sufficient - a legitimately in-flight
    claim also transiently has no active task; only once its age exceeds the
    threshold does it become a candidate. The active-task check takes precedence over
    staleness and is evaluated first per candidate (an event with an active task is
    never a candidate, regardless of how old `updated_at` is) - _find_active_task()
    is reused unmodified, never reimplemented, exactly as the Contract requires.

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
