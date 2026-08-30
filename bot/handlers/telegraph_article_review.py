"""TELEGRAPH Checkpoint 6: article-review callback handler. Thin orchestration only, mirroring
bot/handlers/telegraph_shortlist.py's own "no query construction, no AI/workflow call, no
mutation logic of its own" discipline exactly - every DB read/write goes through
services.telegraph_article_review_service.TelegraphArticleReviewService.

State is re-queried fresh from the database on every single callback - never cached, never
trusted from an earlier render (same discipline as every other TELEGRAPH/meme callback handler
in this codebase).

Authorization: byte-for-byte the same TWO-factor check bot/handlers/telegraph_shortlist.py
already established (newsroom chat scope + settings.telegraph_approver_user_ids fail-closed
allowlist) - deliberately duplicated here rather than imported (both `_is_authorized_chat`/
`_is_authorized_approver` are private, module-scoped helpers there, matching this codebase's own
established per-module-private-helper convention), never a second, divergent authorization
system. See that module's own docstring for the full reasoning behind this being the strongest
EXISTING mechanism, not a new one.

REVISE here ONLY sets `TelegraphArticleReview.status` - never publishes, never sends the article
anywhere else, never triggers a new LLM call.

TELEGRAPH LIVE PUBLISH: APPROVE additionally invokes
`services.telegraph_publish_orchestrator.publish_approved_telegraph_article()` - the one new,
narrow next-stage side effect this handler triggers - immediately after the decision is durably
recorded, on the SAME transition (never on an already-final review re-tap). This handler still
never constructs a Telegraph publish-API request itself (no `access_token`, no Node-format
content, no direct outbound Telegraph HTTP call site anywhere in this file - see this module's own
structural source-scan tests, tests/test_telegraph_article_review_handler.py, for the enforced
boundary);
every Telegraph-specific detail lives in services/telegraph_publisher.py, reached only through
that one orchestrator entry point. A publish failure never rolls back the APPROVED decision and
never raises - the operator sees an explicit alert instead, and the review stays retryable via
`scripts/publish_telegraph_review.py`.
"""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from bot.keyboards.telegraph_article_review import parse_callback_data
from core.config import settings
from database.models.editorial_task import EditorialTask
from database.models.telegraph_article_review import TelegraphArticleReviewStatus
from database.models.telegraph_shortlist import TelegraphTopicProposal
from database.session import async_session_factory
from services.telegraph_article_review_notifier import update_article_review_message
from services.telegraph_article_review_service import TelegraphArticleReviewService
from services.telegraph_publish_orchestrator import publish_approved_telegraph_article

logger = logging.getLogger(__name__)

router = Router(name="telegraph_article_review")

_ACTION_TO_STATUS: dict[str, TelegraphArticleReviewStatus] = {
    "approve": TelegraphArticleReviewStatus.APPROVED,
    "revise": TelegraphArticleReviewStatus.NEEDS_REVISION,
}
_ACTION_TO_ACK_RU: dict[str, str] = {"approve": "Статья одобрена.", "revise": "Отправлено на доработку."}


def _is_authorized_chat(message: Message) -> bool:
    if settings.newsroom_telegram_chat_id is None:
        return False
    return message.chat.id == settings.newsroom_telegram_chat_id


def _is_authorized_approver(callback: CallbackQuery) -> bool:
    if not settings.telegraph_approver_user_ids:
        return False
    return callback.from_user.id in settings.telegraph_approver_user_ids


def _extract_article_result(task: EditorialTask) -> dict | None:
    for step_result in (task.workflow or {}).get("step_results", []):
        if step_result.get("step_name") == "generate_article" and step_result.get("status") == "SUCCESS":
            result = step_result.get("result")
            return result if isinstance(result, dict) else None
    return None


@router.callback_query(F.data.startswith("tgartrev:"))
async def handle_article_review_callback(callback: CallbackQuery) -> None:
    parsed = parse_callback_data(callback.data or "")
    if parsed is None:
        await callback.answer()
        return
    action, review_id = parsed

    message = callback.message
    if message is None or isinstance(message, InaccessibleMessage):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return

    if not _is_authorized_chat(message):
        logger.warning(
            "telegraph_article_review_unauthorized_chat",
            extra={"chat_id": message.chat.id, "review_id": str(review_id)},
        )
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    if not _is_authorized_approver(callback):
        logger.warning(
            "telegraph_article_review_unauthorized_user",
            extra={"user_id": callback.from_user.id, "review_id": str(review_id)},
        )
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    async with async_session_factory() as session:
        service = TelegraphArticleReviewService(session)
        review = await service.get_review(review_id)
        if review is None:
            await callback.answer("Статья больше недоступна.", show_alert=True)
            return

        already_final = review.status != TelegraphArticleReviewStatus.PENDING
        updated = await service.set_decision(
            review_id, _ACTION_TO_STATUS[action], decided_by_telegram_user_id=callback.from_user.id,
        )
        if updated is None:
            await callback.answer("Статья больше недоступна.", show_alert=True)
            return

        if already_final:
            await callback.answer(
                f"Решение уже принято: {_ACTION_TO_ACK_RU.get('approve' if updated.status == TelegraphArticleReviewStatus.APPROVED else 'revise', updated.status.value)}"
            )
            return

        task = await session.get(EditorialTask, updated.article_task_id)
        article_result = _extract_article_result(task) if task is not None else None
        if article_result is None:
            logger.warning(
                "telegraph_article_review_missing_article_result",
                extra={"review_id": str(review_id), "article_task_id": str(updated.article_task_id)},
            )
            await callback.answer(_ACTION_TO_ACK_RU[action])
            return

        # Editorial channel split: fetched here (never cached, never re-classified) from the
        # originating proposal - the formatting/notifier layer stays DB-free by design.
        proposal = await session.get(TelegraphTopicProposal, updated.proposal_id)
        if proposal is None:
            logger.warning(
                "telegraph_article_review_missing_proposal",
                extra={"review_id": str(review_id), "proposal_id": str(updated.proposal_id)},
            )
            await callback.answer(_ACTION_TO_ACK_RU[action])
            return

        publish_ok = True
        if action == "approve":
            publish_outcome = await publish_approved_telegraph_article(session, review_id)
            publish_ok = publish_outcome.status in ("published", "already_published")
            if not publish_ok:
                logger.warning(
                    "telegraph_article_review_publish_failed",
                    extra={
                        "review_id": str(review_id), "publish_status": publish_outcome.status,
                        "error": publish_outcome.error,
                    },
                )

        assert message.bot is not None
        edited = await update_article_review_message(
            message.bot, chat_id=message.chat.id, message_id=message.message_id,
            review=updated, article_result=article_result, editorial_channel=proposal.editorial_channel,
        )
        if not edited:
            logger.warning(
                "telegraph_article_review_rerender_failed",
                extra={"chat_id": message.chat.id, "review_id": str(review_id)},
            )

        if action == "approve" and not publish_ok:
            await callback.answer("Статья одобрена, но публикация не удалась.", show_alert=True)
        else:
            await callback.answer(_ACTION_TO_ACK_RU[action])
