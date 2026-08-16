"""TELEGRAPH Checkpoint 2: shortlist review callback handler. Thin orchestration only, mirroring
`bot/handlers/meme_preview.py`'s own "no query construction, no AI/workflow call, no mutation
logic of its own" discipline - every DB read/write goes through `services.
telegraph_shortlist_service.TelegraphShortlistService`.

State is re-queried fresh from the database on every single callback - never cached, never
trusted from an earlier render (mirrors bot/handlers/meme_preview.py's identical discipline).

Authorization - TWO independent checks, both required (security-correction revision):

1. Chat scoping (originally added by this checkpoint): this codebase has NO existing per-user
admin/editorial authorization mechanism anywhere (`bot/handlers/whereami.py`'s own docstring
confirms this explicitly: "no ADMIN_USER_ID/allowlist setting, no auth-filter precedent in any
other bot/handlers/*.py file" - `bot/handlers/meme_preview.py`/`bot/handlers/image_preview.py`
perform no authorization check of their own either). The one real, already-relied-upon security
boundary in this codebase is Telegram CHAT membership itself - only editorial staff are members
of the private NINJA NEWSROOM supergroup (`settings.newsroom_telegram_chat_id`). This handler
makes that existing, implicit boundary explicit and enforced.

2. Per-user approver allowlist (`settings.telegraph_approver_user_ids` - security-correction
addition): chat membership alone was found insufficient once APPROVED is intended to eventually
gate paid Deep Research/article generation - anyone in the editorial chat could tap a button, not
just a designated approver. `_is_authorized_approver()` checks `callback.from_user.id` against
this explicit, fail-closed allowlist (empty/unconfigured means NOBODY is authorized, never
"everyone in the chat" - see core/config.py's own comment on this field). This IS a new,
narrowly-scoped authorization system (unlike the chat check above) - deliberately the smallest
one possible (a config list, no middleware, no roles), because no existing reusable per-user
mechanism was found anywhere in this codebase (confirmed again during the security-correction
sweep: grepped for admin_user/owner_id/operator_id/allowlist/is_admin across the whole repo).

Both checks must pass before ANY database read/write happens for a given callback. Authorization
is never inferred from `from_user.first_name`/`username`/display name - only the numeric
`from_user.id`, matching the checkpoint's own "Do NOT infer authorization from Telegram
username/display name" requirement.
"""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from bot.keyboards.telegraph_shortlist import parse_callback_data
from core.config import settings
from database.models.telegraph_shortlist import TelegraphProposalStatus
from database.session import async_session_factory
from services.telegraph_shortlist_notifier import update_telegraph_shortlist_message
from services.telegraph_shortlist_service import TelegraphShortlistService

logger = logging.getLogger(__name__)

router = Router(name="telegraph_shortlist")

_ACTION_TO_STATUS: dict[str, TelegraphProposalStatus] = {
    "approve": TelegraphProposalStatus.APPROVED,
    "reject": TelegraphProposalStatus.REJECTED,
}
_ACTION_TO_ACK_RU: dict[str, str] = {"approve": "Одобрено.", "reject": "Отклонено."}


def _is_authorized_chat(message: Message) -> bool:
    """See module docstring for the full reasoning - chat-membership scoping is the one real
    authorization boundary this codebase already relies on, made explicit here. `False` whenever
    `newsroom_telegram_chat_id` is unconfigured (`None`) - an unconfigured destination authorizes
    nothing, never "any chat"."""
    if settings.newsroom_telegram_chat_id is None:
        return False
    return message.chat.id == settings.newsroom_telegram_chat_id


def _is_authorized_approver(callback: CallbackQuery) -> bool:
    """See module docstring §2 - fail closed. An empty/unconfigured
    `telegraph_approver_user_ids` authorizes NO ONE, never "everyone in the chat". Identity is
    the numeric Telegram user id only - never username/display name."""
    if not settings.telegraph_approver_user_ids:
        return False
    return callback.from_user.id in settings.telegraph_approver_user_ids


@router.callback_query(F.data.startswith("tgshort:"))
async def handle_telegraph_shortlist_callback(callback: CallbackQuery) -> None:
    parsed = parse_callback_data(callback.data or "")
    if parsed is None:
        await callback.answer()
        return
    action, proposal_id = parsed

    message = callback.message
    if message is None or isinstance(message, InaccessibleMessage):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return

    if not _is_authorized_chat(message):
        logger.warning(
            "telegraph_shortlist_unauthorized_chat",
            extra={"chat_id": message.chat.id, "proposal_id": str(proposal_id)},
        )
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    if not _is_authorized_approver(callback):
        logger.warning(
            "telegraph_shortlist_unauthorized_user",
            extra={"user_id": callback.from_user.id, "proposal_id": str(proposal_id)},
        )
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    async with async_session_factory() as session:
        service = TelegraphShortlistService(session)
        proposal = await service.get_proposal(proposal_id)
        if proposal is None:
            await callback.answer("Тема больше недоступна.", show_alert=True)
            return

        already_final = proposal.status != TelegraphProposalStatus.PENDING
        updated = await service.set_decision(
            proposal_id, _ACTION_TO_STATUS[action], decided_by_telegram_user_id=callback.from_user.id,
        )
        if updated is None:
            await callback.answer("Тема больше недоступна.", show_alert=True)
            return

        if already_final:
            # Idempotent/immutable-final policy (services.telegraph_shortlist_service.
            # TelegraphShortlistService.set_decision()'s own docstring) - no re-render, no
            # duplicate side effect, just an operator-friendly acknowledgement of the EXISTING
            # decision (which may differ from the tapped action, e.g. tapping reject on an
            # already-approved proposal).
            await callback.answer(f"Решение уже принято: {_ACTION_TO_ACK_RU.get(updated.status.value, updated.status.value)}")
            return

        proposals = await service.list_proposals_for_batch(updated.batch_id)
        assert message.bot is not None
        edited = await update_telegraph_shortlist_message(
            message.bot, chat_id=message.chat.id, message_id=message.message_id, proposals=proposals,
        )
        if not edited:
            logger.warning(
                "telegraph_shortlist_rerender_failed",
                extra={"chat_id": message.chat.id, "proposal_id": str(proposal_id)},
            )
        await callback.answer(_ACTION_TO_ACK_RU[action])
