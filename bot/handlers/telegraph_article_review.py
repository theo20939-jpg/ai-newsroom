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

APPROVE/REVISE here ONLY sets `TelegraphArticleReview.status` - never republishes, never sends
the article anywhere else, never calls any external publishing API, never triggers a new LLM
call. This checkpoint does not build what happens after a decision (a future checkpoint's job) -
see this module's own structural source-scan tests
(tests/test_telegraph_article_review_handler.py) for the enforced boundary.
"""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from bot.keyboards.telegraph_article_review import parse_callback_data
from core.config import settings
from database.models.editorial_task import EditorialTask
from database.models.telegraph_article_review import TelegraphArticleReviewStatus
from database.session import async_session_factory
from services.telegraph_article_review_notifier import update_article_review_message
from services.telegraph_article_review_service import TelegraphArticleReviewService

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

        assert message.bot is not None
        edited = await update_article_review_message(
            message.bot, chat_id=message.chat.id, message_id=message.message_id,
            review=updated, article_result=article_result,
        )
        if not edited:
            logger.warning(
                "telegraph_article_review_rerender_failed",
                extra={"chat_id": message.chat.id, "review_id": str(review_id)},
            )
        await callback.answer(_ACTION_TO_ACK_RU[action])
