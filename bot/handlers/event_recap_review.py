"""NINJA PULSE RECAP Phase R2 integration, Phase D.0: EVENT_RECAP review callback handler. Thin
orchestration only, mirroring bot/handlers/telegraph_article_review.py's own "no query
construction, no AI/workflow call, no mutation logic of its own" discipline exactly - every DB
read/write goes through services.event_recap_review_service.

State is re-queried fresh from the database on every single callback - never cached, never
trusted from an earlier render (same discipline as every other TELEGRAPH/meme/recap callback
handler in this codebase).

Authorization: byte-for-byte the same TWO-factor check bot/handlers/telegraph_article_review.py
already established (newsroom chat scope + settings.telegraph_approver_user_ids fail-closed
allowlist) - deliberately duplicated here rather than imported (both `_is_authorized_chat`/
`_is_authorized_approver` are private, module-scoped helpers there, matching this codebase's own
established per-module-private-helper convention), reused as-is since no distinct EVENT_RECAP
approver population has been defined for this feature yet - never a second, divergent
authorization system.

Phase D.0 change from Phase C.1: this handler was a deliberate stub (authorization only,
`callback.answer()`, no persistence at all - Phase C.1 had no durable review row to write a
decision into). Phase D.0 adds `EventRecapReview` (database/models/event_recap_review.py), so this
handler now actually persists the decision via `services.event_recap_review_service.set_decision()`
and re-renders the already-sent Telegram message in place, exactly mirroring
bot/handlers/telegraph_article_review.py's own APPROVE/REVISE path.

APPROVE/NEEDS_REVISION here ONLY sets `EventRecapReview.status` - never republishes, never creates
a ContentDraft, never sends the recap anywhere else, never calls any external publishing API,
never triggers a new LLM call or workflow re-run, never touches
`EventRecapCandidate.publishable` (not even reachable from here - this handler never loads a
candidate at all, only the recap's own persisted result dict from `EditorialTask.workflow`). This
phase does not build what happens after a decision (a future phase's job) - see this module's own
structural source-scan tests (tests/test_event_recap_review_handler.py) for the enforced boundary.
"""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from bot.keyboards.event_recap_review import parse_callback_data
from core.config import settings
from database.models.editorial_task import EditorialTask
from database.models.event_recap_review import EventRecapReviewStatus
from database.session import async_session_factory
from services.event_recap_review_notifier import update_event_recap_review_message
from services.event_recap_review_service import get_event_recap_review, set_decision

logger = logging.getLogger(__name__)

router = Router(name="event_recap_review")

_ACTION_TO_STATUS: dict[str, EventRecapReviewStatus] = {
    "approve": EventRecapReviewStatus.APPROVED,
    "needs_revision": EventRecapReviewStatus.NEEDS_REVISION,
}
_ACTION_TO_ACK_RU: dict[str, str] = {
    "approve": "Recap одобрен.", "needs_revision": "Отправлено на доработку.",
}


def _is_authorized_chat(message: Message) -> bool:
    if settings.newsroom_telegram_chat_id is None:
        return False
    return message.chat.id == settings.newsroom_telegram_chat_id


def _is_authorized_approver(callback: CallbackQuery) -> bool:
    if not settings.telegraph_approver_user_ids:
        return False
    return callback.from_user.id in settings.telegraph_approver_user_ids


def _extract_recap_result(task: EditorialTask) -> dict | None:
    for step_result in (task.workflow or {}).get("step_results", []):
        if step_result.get("step_name") == "synthesize_recap" and step_result.get("status") == "SUCCESS":
            result = step_result.get("result")
            return result if isinstance(result, dict) else None
    return None


@router.callback_query(F.data.startswith("eventrecap:"))
async def handle_event_recap_review_callback(callback: CallbackQuery) -> None:
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
            "event_recap_review_unauthorized_chat",
            extra={"chat_id": message.chat.id, "review_id": str(review_id)},
        )
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    if not _is_authorized_approver(callback):
        logger.warning(
            "event_recap_review_unauthorized_user",
            extra={"user_id": callback.from_user.id, "review_id": str(review_id)},
        )
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    async with async_session_factory() as session:
        review = await get_event_recap_review(session, review_id)
        if review is None:
            await callback.answer("Recap больше недоступен.", show_alert=True)
            return

        already_final = review.status != EventRecapReviewStatus.PENDING
        updated = await set_decision(
            session, review_id, _ACTION_TO_STATUS[action], decided_by_user_id=callback.from_user.id,
        )
        if updated is None:
            await callback.answer("Recap больше недоступен.", show_alert=True)
            return

        if already_final:
            already_ack = "Recap одобрен." if updated.status == EventRecapReviewStatus.APPROVED else "Отправлено на доработку."
            await callback.answer(f"Решение уже принято: {already_ack}")
            return

        task = await session.get(EditorialTask, updated.recap_task_id)
        recap_result = _extract_recap_result(task) if task is not None else None
        if recap_result is None:
            logger.warning(
                "event_recap_review_missing_recap_result",
                extra={"review_id": str(review_id), "recap_task_id": str(updated.recap_task_id)},
            )
            await callback.answer(_ACTION_TO_ACK_RU[action])
            return

        assert message.bot is not None
        edited = await update_event_recap_review_message(
            message.bot, chat_id=message.chat.id, message_id=message.message_id,
            review=updated, recap_result=recap_result,
        )
        if not edited:
            logger.warning(
                "event_recap_review_rerender_failed",
                extra={"chat_id": message.chat.id, "review_id": str(review_id)},
            )
        await callback.answer(_ACTION_TO_ACK_RU[action])
