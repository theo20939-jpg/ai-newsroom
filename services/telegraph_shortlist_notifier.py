"""TELEGRAPH Checkpoint 2: Telegram send/edit for the shortlist review UI (part C of the phase
brief's own A/B/C/D split). Reuses `services/telegram_routing.py::send_to_editorial_destination()`
verbatim - the single existing, already-tested Telegram send boundary - never a new HTTP/Bot API
call site. Destination is hardcoded to `EditorialDestination.TELEGRAPH` only; this module never
references NEWS/MEME/INSTAGRAM/REELS (see tests/test_telegraph_shortlist_notifier.py's own
structural source-scan test).

`dry_run=True` by default on every function here, mirroring every other send wrapper in this
codebase (`send_to_editorial_destination()` itself, `send_editorial_card()`, `send_news_with_
image_preview()`) - calling this module with no explicit `dry_run=False` override never sends a
real Telegram message. No scheduler/worker/bot-command calls these functions yet (Checkpoint 2's
own explicit "no production activation" requirement) - this module is reachable only from bot/
handlers/telegraph_shortlist.py's own message-edit path and from whatever future, separately-
authorized caller eventually triggers a real shortlist send.
"""
from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot.keyboards.telegraph_shortlist import build_shortlist_keyboard
from bot.telegraph_shortlist_formatting import render_shortlist_message_text
from database.models.telegraph_shortlist import TelegraphTopicProposal
from schemas.editorial_route import EditorialDestination
from services.telegram_routing import RoutingOutcome, send_to_editorial_destination


async def send_telegraph_shortlist(
    bot: Bot, proposals: list[TelegraphTopicProposal], *, dry_run: bool = True,
) -> RoutingOutcome:
    """Sends the shortlist as ONE message to the TELEGRAPH editorial destination (a Telegram
    forum topic within the NINJA NEWSROOM supergroup - see services/telegram_routing.py's own
    module docstring; NOT telegra.ph publication, per the accepted forensic baseline). The
    caller (a future, separately-authorized batch-delivery step - not built this checkpoint) is
    responsible for persisting `RoutingOutcome.chat_id`/`message_id` onto the owning
    `TelegraphShortlistBatch` via `services.telegraph_shortlist_service.
    TelegraphShortlistService.record_telegram_delivery()` once `sent` is True."""
    text = render_shortlist_message_text(proposals)
    keyboard = build_shortlist_keyboard(proposals)
    return await send_to_editorial_destination(
        bot, EditorialDestination.TELEGRAPH, text, dry_run=dry_run, reply_markup=keyboard,
    )


async def update_telegraph_shortlist_message(
    bot: Bot, *, chat_id: int, message_id: int, proposals: list[TelegraphTopicProposal],
) -> bool:
    """Edits the ALREADY-SENT shortlist message in place after a decision - the phase brief's own
    explicit "prefer updating the existing shortlist message/keyboard... avoid chat spam" -
    never sends a new message. Returns `True` on success, `False` on a live `TelegramAPIError`
    (never raises - mirrors bot/handlers/meme_preview.py::_finalize_decision()'s own "log and
    swallow, the decision itself is already durably recorded regardless" discipline: a failed
    message edit must never be treated as a failed decision)."""
    text = render_shortlist_message_text(proposals)
    keyboard = build_shortlist_keyboard(proposals)
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=keyboard)
    except TelegramAPIError:
        return False
    return True
