"""TELEGRAPH LIVE PUBLISH: publication orchestration - the ONE place that decides whether an
APPROVED, COMPLETED `TelegraphArticleReview` is eligible to become a real telegra.ph page, and
persists the result.

Deliberately kept OUT of services/telegraph_article_review_service.py: that module's own
structural boundary test (tests/test_telegraph_article_review_service.py::
test_no_llm_gateway_or_telegram_call_in_service_source) explicitly forbids any "telegra.ph"
reference there, by design (its own module docstring: "No LLM Gateway call, no web/article-fetch
call, no Telegram call anywhere in this module"). This module needs exactly the one new external
side effect (a real outbound HTTPS call) that boundary correctly keeps separate - mirrors this
codebase's own established A/B/C/D per-concern split precedent (creation / formatting / Telegram
send / decision-mutation, each its own module) by giving publication its own fifth module rather
than blurring it into an existing one.

This module NEVER writes `TelegraphArticleReview.status` - that remains exclusively
services/telegraph_article_review_service.py's own field to mutate (the human APPROVE/NEEDS_
REVISION decision). It only ever READS `.status` (to gate publication) and writes the two new,
purely additive `published_url`/`published_at` columns.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.telegraph_article_review import TelegraphArticleReview, TelegraphArticleReviewStatus
from services.telegraph_publisher import TelegraphPublishError, build_telegraph_content_nodes, create_page

logger = logging.getLogger(__name__)

PublishStatus = Literal["published", "already_published", "not_approved", "article_not_ready", "failed"]


@dataclass(frozen=True)
class PublishOutcome:
    status: PublishStatus
    url: str | None
    error: str | None = None


def _extract_article_result(task: EditorialTask) -> dict[str, Any] | None:
    """Byte-for-byte the same extraction bot/handlers/telegraph_article_review.py::
    _extract_article_result() already implements - duplicated rather than imported (that
    function is a private, module-scoped helper there, matching this codebase's own established
    per-module-private-helper convention, exactly like the two modules' identical authorization
    helpers already do for a different concern)."""
    for step_result in (task.workflow or {}).get("step_results", []):
        if step_result.get("step_name") == "generate_article" and step_result.get("status") == "SUCCESS":
            result = step_result.get("result")
            return result if isinstance(result, dict) else None
    return None


async def publish_approved_telegraph_article(session: AsyncSession, review_id: UUID) -> PublishOutcome:
    """Idempotent: fetches `review_id` fresh from `session`, never trusts a caller-supplied row.
    Publishes AT MOST once per review - a `published_url` already present short-circuits to
    "already_published" with zero network calls, regardless of how many times (or from how many
    different callers - the bot callback, `scripts/publish_telegraph_review.py`, a future retry)
    this is invoked for the same review.

    Gating, in order (never publishes a NEEDS_REVISION or PENDING review; never regenerates
    research or the article):
      1. review must exist.
      2. already published => short-circuit success, no network call.
      3. review.status must be APPROVED.
      4. the linked EditorialTask must exist, be COMPLETED, and carry a real
         "generate_article" SUCCESS step result.

    On any Telegraph API failure, this function returns WITHOUT touching `review` at all - the
    row is left exactly as it was (APPROVED, `published_url` still `None`), so a later call (bot
    retry, operator CLI) can simply try again. Never raises `TelegraphPublishError` itself - every
    failure is reported through `PublishOutcome`, never an exception, so callers never need their
    own try/except around this entry point."""
    review = await session.get(TelegraphArticleReview, review_id)
    if review is None:
        return PublishOutcome(status="failed", url=None, error="review_not_found")

    if review.published_url:
        return PublishOutcome(status="already_published", url=review.published_url)

    if review.status != TelegraphArticleReviewStatus.APPROVED:
        return PublishOutcome(status="not_approved", url=None)

    task = await session.get(EditorialTask, review.article_task_id)
    if task is None or task.status != TaskStatus.COMPLETED:
        return PublishOutcome(status="article_not_ready", url=None, error="article_task_not_completed")

    article_result = _extract_article_result(task)
    if article_result is None:
        return PublishOutcome(status="article_not_ready", url=None, error="missing_article_result")

    headline = str(article_result.get("headline") or "Untitled")
    content_nodes = build_telegraph_content_nodes(article_result)

    try:
        page = await create_page(title=headline, content=content_nodes)
    except TelegraphPublishError as exc:
        logger.warning(
            "telegraph_publish_failed", extra={"review_id": str(review_id), "error": str(exc)},
        )
        return PublishOutcome(status="failed", url=None, error=str(exc))

    # Idempotency / concurrent-double-publish race: mirrors services/telegraph_shortlist_service.
    # py::claim_approved_telegraph_proposal()'s own established idiom exactly - a single atomic
    # conditional UPDATE (`WHERE ... AND published_url IS NULL`) followed by a `rowcount` check,
    # never a `SELECT ... FOR UPDATE` (not used anywhere in this codebase - that module's own
    # docstring explicitly rejects it) and never a new locking table/Redis/advisory-lock
    # mechanism. Postgres's own row-level locking on the UPDATE statement is what makes two
    # concurrent callers (a bot-callback retry racing an operator's manual `scripts.
    # publish_telegraph_review` invocation, or two rapid callback deliveries) racing this same
    # `review_id` safe: only one transaction's WHERE clause can still match once the other has
    # (atomically) set `published_url` - the second sees `rowcount == 0` and returns the WINNER's
    # already-persisted URL instead of overwriting it. The only remaining, disclosed edge case:
    # BOTH callers may have already independently called the real Telegraph API before reaching
    # this UPDATE (the network call itself is not inside this lock) - the loser's own
    # freshly-created page becomes an orphaned, unreferenced Telegraph page, never a data-
    # corruption risk (this row's `published_url` is always exactly the first writer's URL,
    # deterministically). Accepted for this manual/human-triggered phase - a real double-tap is
    # already near-impossible in practice since the Approve button itself disappears from the
    # Telegram message after the first tap lands (bot/keyboards/telegraph_article_review.py::
    # build_article_review_keyboard() returns no keyboard once `status != PENDING`).
    result = await session.execute(
        update(TelegraphArticleReview)
        .where(TelegraphArticleReview.id == review_id, TelegraphArticleReview.published_url.is_(None))
        .values(published_url=page.url, published_at=datetime.now(timezone.utc))
    )
    await session.commit()
    await session.refresh(review)

    if result.rowcount != 1:  # type: ignore[attr-defined]
        return PublishOutcome(status="already_published", url=review.published_url)

    logger.info("telegraph_publish_ok", extra={"review_id": str(review_id), "path": page.path})
    return PublishOutcome(status="published", url=review.published_url)
