"""NINJA PULSE RECAP Phase R2 integration, Phase D.0: durable EVENT_RECAP review creation +
human-decision persistence. Mirrors services/telegraph_article_review_service.py's own A/D split
exactly, for a structurally identical later stage of a different workflow:

- A. creation - `create_event_recap_review()` (this module)
- B. Telegram formatting - bot/event_recap_review_formatting.py
- C. Telegram send - services/event_recap_review_notifier.py
- D. callback decision mutation - `set_decision()` (this module), called only from
  bot/handlers/event_recap_review.py

No LLM Gateway call, no Story/candidate rebuilding, no Telegram call anywhere in this module -
this is pure persistence, exactly mirroring its Telegraph sibling's own "MUST NOT" list.

Deliberately plain, module-level functions (not a class wrapping the session) - this phase's own
requested shape; unlike `TelegraphArticleReviewService`, there is no need for a shared
constructor-injected session across several calls, since every one of this module's callers
already holds its own `AsyncSession` and passes it explicitly to each function.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.event_recap_review import EventRecapReview, EventRecapReviewStatus


async def get_event_recap_review_for_task(
    session: AsyncSession, recap_task_id: UUID,
) -> EventRecapReview | None:
    stmt = select(EventRecapReview).where(EventRecapReview.recap_task_id == recap_task_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_event_recap_review(
    session: AsyncSession, *, recap_task_id: UUID,
) -> EventRecapReview:
    """Creates exactly one review row per `recap_task_id` (the model's own UNIQUE constraint is
    the real guarantee; this function additionally short-circuits to the existing row rather than
    letting a second call raise an IntegrityError, since "review already exists for this recap
    task" is an entirely ordinary, expected case - never a bug to surface as a crash). Mirrors
    services/telegraph_article_review_service.py::create_article_review()'s own identical
    idempotency discipline."""
    existing = await get_event_recap_review_for_task(session, recap_task_id)
    if existing is not None:
        return existing

    review = EventRecapReview(recap_task_id=recap_task_id)
    session.add(review)
    await session.commit()
    await session.refresh(review)
    return review


async def get_event_recap_review(session: AsyncSession, review_id: UUID) -> EventRecapReview | None:
    return await session.get(EventRecapReview, review_id)


async def record_telegram_delivery(
    session: AsyncSession, review_id: UUID, *, chat_id: int, message_id: int, thread_id: int | None,
) -> EventRecapReview | None:
    review = await session.get(EventRecapReview, review_id)
    if review is None:
        return None
    review.telegram_chat_id = chat_id
    review.telegram_message_id = message_id
    review.telegram_thread_id = thread_id
    await session.commit()
    await session.refresh(review)
    return review


async def set_decision(
    session: AsyncSession, review_id: UUID, status: EventRecapReviewStatus, *, decided_by_user_id: int,
) -> EventRecapReview | None:
    """Approve / request-revision a review. Idempotent and immutable-once-final, byte-for-byte the
    same policy `TelegraphArticleReviewService.set_decision()` already established (see that
    method's own docstring for the full reasoning) - deliberately kept identical, not reinvented.

    Returns `None` only if `review_id` does not exist - never raises."""
    review = await session.get(EventRecapReview, review_id)
    if review is None:
        return None
    if review.status != EventRecapReviewStatus.PENDING:
        return review  # already final - immutable, no mutation
    review.status = status
    review.decided_at = datetime.now(timezone.utc)
    review.decided_by_telegram_user_id = decided_by_user_id
    await session.commit()
    await session.refresh(review)
    return review
