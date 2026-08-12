"""Handler for the temporary /whereami diagnostic command (Phase 23.0 - Local Telegram
Diagnostics + Live Canary Preparation).

Purpose: safely discover the real Telegram `chat_id` and per-topic `message_thread_id` for the
NINJA NEWSROOM supergroup's five topics, by manually invoking `/whereami` inside each one (docs/
phase23_0_telegram_diagnostics_report.md). Reuses the exact `Router`/`Command`/`message.answer()`
shape every other handler in this package already uses (bot/handlers/status.py) - no new
dispatcher, no parallel bot application, no bypass of the existing aiogram Dispatcher.

Safety (phase brief §2): never logs or echoes the bot token, any credential, or any user personal
data (name/username/phone are never read - `message.from_user` is never touched); never dumps the
raw Update/Message object; reads exactly four fields - `chat.id`, `chat.type`, `chat.is_forum`,
`message.message_thread_id` (plus `message.is_topic_message`, logged only, not echoed in the
reply, matching the brief's own example reply format exactly). No DB query, no other Telegram
call, no state mutation - the single `message.answer()` call is this handler's only outbound
effect.

Not gated behind an admin-authorization check: no such mechanism exists anywhere in this codebase
to reuse (no `ADMIN_USER_ID`/allowlist setting, no auth-filter precedent in any other bot/handlers/
*.py file) - building one now would be a scope-exceeding architecture change for a temporary
diagnostic command, explicitly out of scope this phase. Safe regardless: the fields this command
echoes are ordinary Telegram routing metadata already visible to any member of the chat through
Telegram's own client UI (e.g. long-pressing a topic), not privileged information - see the phase
report's own §7 for the full reasoning.

Temporary by design - intended for removal (or gating) once the real IDs are collected and Phase
22's routing settings are configured; not wired into any production decision path.
"""
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

logger = logging.getLogger(__name__)

router = Router(name="whereami")


@router.message(Command("whereami"))
async def handle_whereami(message: Message) -> None:
    """Reply with the incoming message's `chat_id`/`is_forum`/`message_thread_id` - see module
    docstring for the exact safety scope."""
    chat = message.chat
    is_forum = bool(chat.is_forum)
    thread_id = message.message_thread_id

    logger.info(
        "telegram_route_debug",
        extra={
            "chat_id": chat.id,
            "chat_type": chat.type,
            "is_forum": is_forum,
            "message_thread_id": thread_id,
            "is_topic_message": bool(message.is_topic_message),
        },
    )

    lines = [
        "TELEGRAM ROUTE DEBUG",
        "",
        f"chat_id: {chat.id}",
        f"is_forum: {'true' if is_forum else 'false'}",
        f"message_thread_id: {thread_id if thread_id is not None else 'none'}",
    ]
    await message.answer("\n".join(lines))
