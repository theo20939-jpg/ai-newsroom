"""Phase I.2: Final Post publication-review callback handler. Thin orchestration only, mirroring
bot/handlers/event_recap_review.py's own "no query construction, no AI/workflow call, no mutation
logic of its own" discipline exactly - every DB read/write goes through
services.final_post_review_service.

State is re-queried fresh from the database on every single callback - never cached, never trusted
from an earlier render (same discipline as every other TELEGRAPH/EVENT_RECAP/meme callback handler
in this codebase).

Authorization: byte-for-byte the same TWO-factor check bot/handlers/event_recap_review.py already
established (newsroom chat scope + settings.telegraph_approver_user_ids fail-closed allowlist) -
deliberately duplicated here rather than imported (both `_is_authorized_chat`/`_is_authorized_
approver` are private, module-scoped helpers there, matching this codebase's own established
per-module-private-helper convention), reused as-is since no distinct Final Post approver
population has been defined for this feature yet - never a second, divergent authorization system.

CRITICAL (Phase I.2's own explicit Part R "NO PUBLICATION IN CALLBACK" invariant): this handler
imports NOTHING from services/telegram_notifier.py, services/image_preview_notifier.py, or any
other public-delivery module. APPROVE here ONLY sets `FinalPostReview.status =
APPROVED_FOR_PUBLICATION` - never republishes, never sends the post anywhere else, never calls any
external publishing API, never triggers a new LLM call or workflow re-run. This phase does not
build what happens after a decision (Phase I.3's job) - see tests/test_final_post_review_handler.py
for the enforced structural boundary (mirrors tests/test_event_recap_review_handler.py's own
identical source-scan discipline).
"""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from bot.keyboards.final_post_review import parse_callback_data
from core.config import settings
from database.models.final_post_review import FinalPostReviewStatus
from database.session import async_session_factory
from services.final_post_review_notifier import update_final_post_review_message
from services.final_post_review_service import get_final_post_review, set_decision

logger = logging.getLogger(__name__)

router = Router(name="final_post_review")

_ACTION_TO_STATUS: dict[str, FinalPostReviewStatus] = {
    "approve": FinalPostReviewStatus.APPROVED_FOR_PUBLICATION,
    "needs_revision": FinalPostReviewStatus.NEEDS_REVISION,
}
_ACTION_TO_ACK_RU: dict[str, str] = {
    "approve": "Одобрено к публикации.", "needs_revision": "Отправлено на доработку.",
}


def _is_authorized_chat(message: Message) -> bool:
    if settings.newsroom_telegram_chat_id is None:
        return False
    return message.chat.id == settings.newsroom_telegram_chat_id


def _is_authorized_approver(callback: CallbackQuery) -> bool:
    if not settings.telegraph_approver_user_ids:
        return False
    return callback.from_user.id in settings.telegraph_approver_user_ids


@router.callback_query(F.data.startswith("finalpost:"))
async def handle_final_post_review_callback(callback: CallbackQuery) -> None:
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
            "final_post_review_unauthorized_chat",
            extra={"chat_id": message.chat.id, "review_id": str(review_id)},
        )
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    if not _is_authorized_approver(callback):
        logger.warning(
            "final_post_review_unauthorized_user",
            extra={"user_id": callback.from_user.id, "review_id": str(review_id)},
        )
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    async with async_session_factory() as session:
        review = await get_final_post_review(session, review_id)
        if review is None:
            await callback.answer("Ревью больше недоступно.", show_alert=True)
            return

        already_final = review.status != FinalPostReviewStatus.PENDING
        updated = await set_decision(
            session, review_id, _ACTION_TO_STATUS[action], decided_by_user_id=callback.from_user.id,
        )
        if updated is None:
            await callback.answer("Ревью больше недоступно.", show_alert=True)
            return

        if already_final:
            already_ack = (
                "Одобрено к публикации." if updated.status == FinalPostReviewStatus.APPROVED_FOR_PUBLICATION
                else "Отправлено на доработку."
            )
            await callback.answer(f"Решение уже принято: {already_ack}")
            return

        assert message.bot is not None
        edited = await update_final_post_review_message(
            message.bot, chat_id=message.chat.id, message_id=message.message_id, review=updated,
        )
        if not edited:
            logger.warning(
                "final_post_review_rerender_failed",
                extra={"chat_id": message.chat.id, "review_id": str(review_id)},
            )
        await callback.answer(_ACTION_TO_ACK_RU[action])
