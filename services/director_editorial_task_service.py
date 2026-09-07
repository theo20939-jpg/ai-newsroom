"""DIRECTOR-CONTROL-PLANE-1 §14/§15/§50: DirectorEditorialTask persistence. Plain module-level
async functions, mirroring services/event_recap_review_service.py's own established idempotent-
mutation shape."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.director_editorial_task import DirectorEditorialTask, DirectorTaskReason, DirectorTaskStatus

# Spec §50's own "duplicate Director idea does not endlessly recreate itself" requirement - a
# Director re-proposing the SAME topic within this window returns the existing open task instead
# of creating a second one. Deliberately generous (not a tight dedup window): a Director task is a
# low-frequency, high-intent proposal, never a per-cycle re-evaluation the way ingestion is.
_DUPLICATE_PROPOSAL_WINDOW = timedelta(days=14)

_OPEN_STATUSES = frozenset({
    DirectorTaskStatus.PROPOSED, DirectorTaskStatus.RESEARCH_REQUIRED, DirectorTaskStatus.RESEARCHED,
})


async def find_open_duplicate(
    session: AsyncSession, *, platform: str, proposed_topic: str, now: datetime | None = None,
) -> DirectorEditorialTask | None:
    now = now or datetime.now(timezone.utc)
    cutoff = now - _DUPLICATE_PROPOSAL_WINDOW
    stmt = select(DirectorEditorialTask).where(
        DirectorEditorialTask.platform == platform,
        DirectorEditorialTask.proposed_topic == proposed_topic,
        DirectorEditorialTask.status.in_(_OPEN_STATUSES),
        DirectorEditorialTask.created_at >= cutoff,
    )
    return (await session.execute(stmt)).scalars().first()


async def create_task(
    session: AsyncSession, *, platform: str, proposed_topic: str, why_now: str, reason: DirectorTaskReason,
    director: str, desired_format: str | None = None, requires_research: bool = True,
    campaign_id: UUID | None = None, directive_id: UUID | None = None,
    director_run_context_fingerprint: str | None = None, now: datetime | None = None,
) -> DirectorEditorialTask:
    """Spec §50: never creates a second open task for the same (platform, proposed_topic) pair
    within the dedup window - returns the existing one unchanged instead."""
    existing = await find_open_duplicate(session, platform=platform, proposed_topic=proposed_topic, now=now)
    if existing is not None:
        return existing

    task = DirectorEditorialTask(
        id=uuid.uuid4(), platform=platform, proposed_topic=proposed_topic, why_now=why_now, reason=reason,
        desired_format=desired_format, requires_research=requires_research,
        campaign_id=campaign_id, directive_id=directive_id, director=director,
        director_run_context_fingerprint=director_run_context_fingerprint,
        status=DirectorTaskStatus.RESEARCH_REQUIRED if requires_research else DirectorTaskStatus.PROPOSED,
    )
    session.add(task)
    return task


async def mark_researched(
    session: AsyncSession, task_id: UUID, *, research_event_id: UUID,
) -> DirectorEditorialTask | None:
    """Spec §15: the ONLY function allowed to set `research_event_id` - a task may not be
    converted into a ContentDraft before this has run. Idempotent: a second call is a no-op once
    already RESEARCHED/CONVERTED_TO_DRAFT."""
    task = await session.get(DirectorEditorialTask, task_id)
    if task is None:
        return None
    if task.status in (DirectorTaskStatus.RESEARCHED, DirectorTaskStatus.CONVERTED_TO_DRAFT):
        return task
    task.research_event_id = research_event_id
    task.status = DirectorTaskStatus.RESEARCHED
    return task


async def mark_converted(
    session: AsyncSession, task_id: UUID, *, content_draft_id: UUID,
) -> DirectorEditorialTask | None:
    """Spec §15's own hard gate: raises if the task never went through mark_researched() first -
    a fact-requiring Director idea can never become a ContentDraft without a real research_event_id
    on record, regardless of what a caller passes in here."""
    task = await session.get(DirectorEditorialTask, task_id)
    if task is None:
        return None
    if task.status == DirectorTaskStatus.CONVERTED_TO_DRAFT:
        return task
    if task.requires_research and task.research_event_id is None:
        raise ValueError(
            "DirectorEditorialTask requires research but has no research_event_id - "
            "mark_researched() must run before mark_converted()."
        )
    task.content_draft_id = content_draft_id
    task.status = DirectorTaskStatus.CONVERTED_TO_DRAFT
    return task


async def list_pending_tasks(session: AsyncSession, *, platform: str | None = None) -> list[DirectorEditorialTask]:
    stmt = select(DirectorEditorialTask).where(DirectorEditorialTask.status.in_(_OPEN_STATUSES))
    if platform is not None:
        stmt = stmt.where(DirectorEditorialTask.platform == platform)
    stmt = stmt.order_by(DirectorEditorialTask.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())
