"""TELEGRAPH Checkpoint 6: durable article-review creation + human-decision persistence.

Mirrors services/telegraph_shortlist_service.py's own A/D split exactly, for a later stage:

- A. creation - `create_article_review()` (this module)
- B. Telegram formatting - bot/telegraph_article_review_formatting.py
- C. Telegram send - services/telegraph_article_review_notifier.py
- D. callback decision mutation - `TelegraphArticleReviewService.set_decision()` (this module),
  called only from bot/handlers/telegraph_article_review.py

No LLM Gateway call, no web/article-fetch call, no Telegram call anywhere in this module.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.telegraph_article_review import TelegraphArticleReview, TelegraphArticleReviewStatus


async def get_review_for_article_task(
    session: AsyncSession, article_task_id: UUID,
) -> TelegraphArticleReview | None:
    stmt = select(TelegraphArticleReview).where(TelegraphArticleReview.article_task_id == article_task_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_article_review(
    session: AsyncSession, *, article_task_id: UUID, proposal_id: UUID,
) -> TelegraphArticleReview:
    """Creates exactly one review row per `article_task_id` (the model's own UNIQUE constraint
    is the real guarantee; this function additionally short-circuits to the existing row rather
    than letting a second call raise an IntegrityError, since "review already exists for this
    article" is an entirely ordinary, expected case - e.g. a caller re-invoking after a partial
    failure - never a bug to surface as a crash)."""
    existing = await get_review_for_article_task(session, article_task_id)
    if existing is not None:
        return existing

    review = TelegraphArticleReview(article_task_id=article_task_id, proposal_id=proposal_id)
    session.add(review)
    await session.commit()
    await session.refresh(review)
    return review


class TelegraphArticleReviewService:
    """Owns every read/write against `TelegraphArticleReview` past creation time - mirrors
    `TelegraphShortlistService`'s own identical shape/discipline."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_review(self, review_id: UUID) -> TelegraphArticleReview | None:
        return await self._session.get(TelegraphArticleReview, review_id)

    async def record_telegram_delivery(
        self, review_id: UUID, *, chat_id: int, message_id: int, thread_id: int | None,
    ) -> TelegraphArticleReview | None:
        review = await self._session.get(TelegraphArticleReview, review_id)
        if review is None:
            return None
        review.telegram_chat_id = chat_id
        review.telegram_message_id = message_id
        review.telegram_thread_id = thread_id
        await self._session.commit()
        await self._session.refresh(review)
        return review

    async def set_decision(
        self, review_id: UUID, decision: TelegraphArticleReviewStatus, *, decided_by_telegram_user_id: int,
    ) -> TelegraphArticleReview | None:
        """Approve / request-revision a review. Idempotent and immutable-once-final, byte-for-
        byte the same policy `TelegraphShortlistService.set_decision()` already established for
        the topic-approval stage (see that method's own docstring for the full reasoning) -
        deliberately kept identical across both review stages of this pipeline, not reinvented.

        Returns `None` only if `review_id` does not exist - never raises."""
        review = await self._session.get(TelegraphArticleReview, review_id)
        if review is None:
            return None
        if review.status != TelegraphArticleReviewStatus.PENDING:
            return review  # already final - immutable, no mutation
        review.status = decision
        review.decided_at = datetime.now(timezone.utc)
        review.decided_by_telegram_user_id = decided_by_telegram_user_id
        await self._session.commit()
        await self._session.refresh(review)
        return review
