"""Forward-only terminal publication outcomes on the existing generation task.

The task id is the attempt id.  ``workflow.publication_outcome`` is written once;
the existing story_telegram_deliveries row remains the send receipt for linked
stories.  Historical tasks are deliberately left untouched/UNKNOWN.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.models.editorial_task import EditorialTask
from database.models.content_draft import ContentDraft
from database.models.news_event import NewsEvent
from database.models.story_telegram_delivery import DeliveryStatus, StoryTelegramDelivery
from services.kage_content_lineage_audit import update_attempt_audit

TerminalStatus = Literal[
    "DELIVERED", "BLOCKED_FACTUAL_GATE", "BLOCKED_LOCAL_GUARD", "BLOCKED_BOTH",
    "GATE_TECHNICAL_BLOCK", "GENERATION_FAILED", "DELIVERY_FAILED", "VISUAL_HOLD",
    "DUPLICATE_SUPERSEDED", "ROUTING_HOLD", "PRE_SEND_FAILURE", "DRY_RUN",
    "DELIVERY_UNCONFIRMED", "OTHER_TERMINAL_FAILURE", "BLOCKED_EDITORIAL_USEFULNESS",
]


async def mark_publication_started(
    session: AsyncSession, *, task_id: UUID, draft_id: UUID,
) -> dict:
    """Record the pre-send intent before entering the post-generation path.

    A stale IN_FLIGHT result after a crash is intentionally not called a delivery;
    it requires reconciliation and prevents an unobserved automatic second send.
    """
    task = await session.get(EditorialTask, task_id, with_for_update=True)
    if task is None:
        raise ValueError(f"generation task missing: {task_id}")
    workflow = dict(task.workflow or {})
    if workflow.get("publication_outcome") is not None:
        raise ValueError(f"publication attempt already observed for task {task_id}")
    started = {
        "status": "IN_FLIGHT", "task_id": str(task_id),
        "event_id": str(task.event_id), "draft_id": str(draft_id),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    task.workflow = {**workflow, "publication_outcome": started}
    return started


async def record_terminal_outcome(
    session: AsyncSession, *, task_id: UUID, status: TerminalStatus,
    draft_id: UUID | None = None, story_id: UUID | None = None,
    chat_id: int | None = None, topic_id: int | None = None,
    message_id: int | None = None, error_class: str | None = None,
    reason: str | None = None, send_attempted_at: datetime | None = None,
) -> dict:
    """Persist exactly one immutable terminal result for one generation attempt.

    Caller commits this transaction. A repeated identical result is idempotent;
    a contradictory result fails loudly. No title, provider text, or secret is stored.
    """
    if status == "DELIVERED" and (message_id is None or chat_id is None):
        raise ValueError("DELIVERED requires a Telegram chat and message id")
    if status != "DELIVERED" and message_id is not None:
        raise ValueError("a non-delivered outcome cannot contain a message id")
    task = await session.get(EditorialTask, task_id, with_for_update=True)
    if task is None:
        raise ValueError(f"generation task missing: {task_id}")
    workflow = dict(task.workflow or {})
    candidate = {
        "status": status,
        "task_id": str(task_id),
        "event_id": str(task.event_id),
        "draft_id": str(draft_id) if draft_id else None,
        "story_id": str(story_id) if story_id else None,
        "chat_id": chat_id,
        "topic_id": topic_id,
        "message_id": message_id,
        "error_class": error_class,
        "reason": reason,
        "send_attempted_at": send_attempted_at.isoformat() if send_attempted_at else None,
    }
    existing = workflow.get("publication_outcome")
    if isinstance(existing, dict) and existing.get("status") == "IN_FLIGHT":
        candidate["started_at"] = existing.get("started_at")
    elif existing is not None:
        if {key: existing.get(key) for key in candidate} != candidate:
            raise ValueError(f"conflicting terminal outcome for task {task_id}")
        return existing
    candidate["observed_at"] = datetime.now(timezone.utc).isoformat()
    task.workflow = {**workflow, "publication_outcome": candidate}
    await update_attempt_audit(
        session, task_id=task_id, section="publication_outcome", value=candidate,
    )
    return candidate


async def event_publication_state(session: AsyncSession, event_id: UUID) -> dict:
    """Read-only: has THIS event already produced a successful Telegram publication?

    Resolved through the durable path the delivery code actually writes: generation task
    (``event_id``) -> draft (``task_id``) -> ``story_telegram_deliveries.content_draft_id``,
    plus the task's own ``workflow.publication_outcome``. ``story_telegram_deliveries.
    source_event_id`` is deliberately not used: ``record_delivery()`` never populates it.
    A failed/blocked attempt alone is not a delivery; IN_FLIGHT is reported separately.
    """
    rows = (await session.execute(
        select(EditorialTask.id, EditorialTask.workflow,
               StoryTelegramDelivery.id, StoryTelegramDelivery.delivery_status,
               StoryTelegramDelivery.telegram_message_id)
        .outerjoin(ContentDraft, ContentDraft.task_id == EditorialTask.id)
        .outerjoin(StoryTelegramDelivery,
                   StoryTelegramDelivery.content_draft_id == ContentDraft.id)
        .where(EditorialTask.event_id == event_id)
    )).all()
    delivered_tasks: set[str] = set()
    in_flight_tasks: set[str] = set()
    receipt_ids: set[str] = set()
    for task_id, workflow, receipt_id, delivery_status, message_id in rows:
        if not isinstance(workflow, dict) or workflow.get("workflow_name") != "CONTENT_GENERATION":
            continue
        outcome = workflow.get("publication_outcome")
        status = outcome.get("status") if isinstance(outcome, dict) else None
        if delivery_status == DeliveryStatus.SENT and message_id is not None:
            receipt_ids.add(str(receipt_id))
            delivered_tasks.add(str(task_id))
        if status == "DELIVERED":
            delivered_tasks.add(str(task_id))
        elif status == "IN_FLIGHT":
            in_flight_tasks.add(str(task_id))
    return {
        "event_id": str(event_id),
        "already_delivered": bool(delivered_tasks),
        "delivered_task_ids": sorted(delivered_tasks),
        "sent_receipt_ids": sorted(receipt_ids),
        "in_flight_task_ids": sorted(in_flight_tasks - delivered_tasks),
    }


async def count_terminal_outcomes(
    session: AsyncSession, *, window_start: datetime, window_end: datetime,
) -> dict[str, int]:
    """Read-only audit for generation attempts whose source events are in [start,end).

    A historical persisted sent receipt still proves delivery, and a FAILED
    generation task proves generation failure. All other historical gaps remain
    UNKNOWN; this helper writes nothing and never guesses from a draft alone.
    """
    rows = (await session.execute(
        select(EditorialTask.id, EditorialTask.status, EditorialTask.workflow,
               StoryTelegramDelivery.delivery_status,
               StoryTelegramDelivery.telegram_message_id)
        .join(NewsEvent, NewsEvent.id == EditorialTask.event_id)
        .outerjoin(ContentDraft, ContentDraft.task_id == EditorialTask.id)
        .outerjoin(StoryTelegramDelivery,
                   StoryTelegramDelivery.content_draft_id == ContentDraft.id)
        .where(NewsEvent.collected_at >= window_start,
               NewsEvent.collected_at < window_end)
    )).all()
    counts: Counter[str] = Counter()
    by_task: dict[UUID, str] = {}
    for task_id, task_status, workflow, delivery_status, message_id in rows:
        if not isinstance(workflow, dict) or workflow.get("workflow_name") != "CONTENT_GENERATION":
            continue
        outcome = workflow.get("publication_outcome")
        status = outcome.get("status") if isinstance(outcome, dict) else None
        if not isinstance(status, str):
            if delivery_status == DeliveryStatus.SENT and message_id is not None:
                status = "DELIVERED"
            elif getattr(task_status, "value", task_status) == "FAILED":
                status = "GENERATION_FAILED"
            else:
                status = "UNKNOWN"
        prior = by_task.get(task_id)
        if prior is None or (prior == "UNKNOWN" and status != "UNKNOWN"):
            by_task[task_id] = status
    counts.update(by_task.values())
    counts["TOTAL_ATTEMPTS"] = sum(value for key, value in counts.items() if key != "TOTAL_ATTEMPTS")
    for status in ("DELIVERED", "BLOCKED_FACTUAL_GATE", "BLOCKED_LOCAL_GUARD", "BLOCKED_EDITORIAL_USEFULNESS",
                   "BLOCKED_BOTH", "GATE_TECHNICAL_BLOCK", "GENERATION_FAILED",
                   "DELIVERY_FAILED", "DELIVERY_UNCONFIRMED", "VISUAL_HOLD", "OTHER_TERMINAL_FAILURE",
                   "IN_FLIGHT", "UNKNOWN"):
        counts.setdefault(status, 0)
    counts["OTHER"] = sum(counts[key] for key in (
        "DUPLICATE_SUPERSEDED", "ROUTING_HOLD", "PRE_SEND_FAILURE", "DRY_RUN",
        "DELIVERY_UNCONFIRMED", "OTHER_TERMINAL_FAILURE",
    ))
    return dict(counts)
