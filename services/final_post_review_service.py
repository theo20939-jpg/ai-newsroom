"""Phase I.2: durable `FinalPostReview` creation + human-decision persistence. Mirrors
services/event_recap_review_service.py's own A/D split exactly, for a structurally identical later
stage of a different workflow:

- A. creation - `create_final_post_review()` (this module)
- B. Telegram formatting - bot/final_post_review_formatting.py
- C. Telegram send - services/final_post_review_notifier.py
- D. callback decision mutation - `set_decision()` (this module), called only from
  bot/handlers/final_post_review.py

No LLM Gateway call, no Story/ContentDraft rebuilding, no Telegram call anywhere in this module -
this is pure persistence, exactly mirroring its EventRecapReview sibling's own "MUST NOT" list.

No publication side effect of any kind - `set_decision()` only ever changes `FinalPostReview.
status`. Deciding `APPROVED_FOR_PUBLICATION` here never sends anything, never creates a
ContentDraft, never calls any publishing API - Phase I.3 (a later, separate phase) is the only
future consumer of that status value.

Deliberately plain, module-level functions (not a class wrapping the session) - mirrors
services/event_recap_review_service.py's own identical reasoning: every caller already holds its
own `AsyncSession` and passes it explicitly to each function.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.final_post_review import FinalPostReview, FinalPostReviewStatus


async def get_final_post_review_for_draft(
    session: AsyncSession, content_draft_id: UUID,
) -> FinalPostReview | None:
    stmt = select(FinalPostReview).where(FinalPostReview.content_draft_id == content_draft_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_final_post_review(
    session: AsyncSession, *, content_draft_id: UUID,
) -> FinalPostReview:
    """Creates exactly one review row per `content_draft_id` (the model's own UNIQUE constraint is
    the real guarantee; this function additionally short-circuits to the existing row rather than
    letting a second call raise an IntegrityError - "review already exists for this draft" is an
    entirely ordinary, expected case, never a bug to surface as a crash). Mirrors
    services/event_recap_review_service.py::create_event_recap_review()'s own identical idempotency
    discipline (Phase I.2's own Part N/"one ContentDraft -> max one FinalPostReview")."""
    existing = await get_final_post_review_for_draft(session, content_draft_id)
    if existing is not None:
        return existing

    review = FinalPostReview(content_draft_id=content_draft_id)
    session.add(review)
    await session.commit()
    await session.refresh(review)
    return review


async def get_final_post_review(session: AsyncSession, review_id: UUID) -> FinalPostReview | None:
    return await session.get(FinalPostReview, review_id)


async def record_telegram_delivery(
    session: AsyncSession, review_id: UUID, *, chat_id: int, message_id: int, thread_id: int | None,
) -> FinalPostReview | None:
    """Records MESSAGE 2's (the control message, never MESSAGE 1's preview) own chat/message/thread
    ids - mirrors services/event_recap_review_service.py::record_telegram_delivery() exactly."""
    review = await session.get(FinalPostReview, review_id)
    if review is None:
        return None
    review.telegram_chat_id = chat_id
    review.telegram_message_id = message_id
    review.telegram_thread_id = thread_id
    await session.commit()
    await session.refresh(review)
    return review


async def set_decision(
    session: AsyncSession, review_id: UUID, status: FinalPostReviewStatus, *, decided_by_user_id: int,
) -> FinalPostReview | None:
    """Approve-for-publication / request-revision a review. Idempotent and immutable-once-final,
    byte-for-byte the same policy services/event_recap_review_service.py::set_decision() already
    established (see that function's own docstring for the full reasoning) - deliberately kept
    identical, not reinvented. No publication side effect of any kind (this module's own docstring).

    Returns `None` only if `review_id` does not exist - never raises."""
    review = await session.get(FinalPostReview, review_id)
    if review is None:
        return None
    if review.status != FinalPostReviewStatus.PENDING:
        return review  # already final - immutable, no mutation
    review.status = status
    review.decided_at = datetime.now(timezone.utc)
    review.decided_by_telegram_user_id = decided_by_user_id
    await session.commit()
    await session.refresh(review)
    return review
