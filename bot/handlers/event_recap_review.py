"""NINJA PULSE RECAP Phase R2 integration, Phase C.1: EVENT_RECAP review callback handler -
DELIBERATELY A STUB. Registers a real callback route with the same two-factor authorization
bot/handlers/telegraph_article_review.py already established (newsroom chat scope + an approver
allowlist - reuses `settings.telegraph_approver_user_ids` rather than adding a new, separate
EVENT_RECAP-specific settings field, since no distinct approver population has been defined for
this feature yet; a future phase may split this out), but the approve/reject decision itself is
NEVER persisted anywhere and the message is NEVER edited - this handler only acknowledges the
click.

Why a stub, not a full decision handler: bot/handlers/telegraph_article_review.py's own APPROVE/
REVISE path writes to a real, durable `TelegraphArticleReview` row (services/
telegraph_article_review_service.py::TelegraphArticleReviewService.set_decision()) - a genuinely
new DB table Checkpoint 6 added specifically to hold that decision. Phase C.1's own explicit
constraints forbid adding any new DB model. Without a durable row to write a decision into, this
handler has nothing safe to persist a click as - fabricating an in-memory-only "decision" would be
worse than not recording one at all (silently misleading, not actually durable). The buttons
(bot/keyboards/event_recap_review.py) are therefore wired to a real, authorized callback route -
"prepared for a future review flow", exactly as this checkpoint's own brief asks - not a
functioning approve/reject flow yet. A future phase that adds an `EventRecapReview`-shaped table
(mirroring `TelegraphArticleReview`'s own precedent) would extend this handler to actually persist
a decision and re-render the message, the same way bot/handlers/telegraph_article_review.py does
today.

Never republishes, never sends anything anywhere else, never calls any external publishing API,
never triggers a new LLM call, never touches `EventRecapCandidate.publishable` - it isn't even
reachable from here (this handler never loads a candidate at all).
"""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from bot.keyboards.event_recap_review import parse_callback_data
from core.config import settings

logger = logging.getLogger(__name__)

router = Router(name="event_recap_review")

_ACTION_ACK_RU: dict[str, str] = {
    "approve": "Отмечено как «одобрено» (решение пока не сохраняется).",
    "reject": "Отмечено как «отклонено» (решение пока не сохраняется).",
}


def _is_authorized_chat(message: Message) -> bool:
    if settings.newsroom_telegram_chat_id is None:
        return False
    return message.chat.id == settings.newsroom_telegram_chat_id


def _is_authorized_approver(callback: CallbackQuery) -> bool:
    if not settings.telegraph_approver_user_ids:
        return False
    return callback.from_user.id in settings.telegraph_approver_user_ids


@router.callback_query(F.data.startswith("evrecrev:"))
async def handle_event_recap_review_callback(callback: CallbackQuery) -> None:
    parsed = parse_callback_data(callback.data or "")
    if parsed is None:
        await callback.answer()
        return
    action, story_id = parsed

    message = callback.message
    if message is None or isinstance(message, InaccessibleMessage):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return

    if not _is_authorized_chat(message):
        logger.warning(
            "event_recap_review_unauthorized_chat", extra={"chat_id": message.chat.id, "story_id": str(story_id)},
        )
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    if not _is_authorized_approver(callback):
        logger.warning(
            "event_recap_review_unauthorized_user",
            extra={"user_id": callback.from_user.id, "story_id": str(story_id)},
        )
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    # Deliberately no DB write, no message edit - see this module's own docstring for why. Only
    # a disclosed, structured log line plus a Telegram-side acknowledgment.
    logger.info(
        "event_recap_review_callback_acknowledged_not_persisted",
        extra={"action": action, "story_id": str(story_id), "user_id": callback.from_user.id},
    )
    await callback.answer(_ACTION_ACK_RU[action])
