"""NINJA Social Intelligence Foundation, Telegram Directors Phase 2 §6: passive-only first-party
performance collection. Gated by `settings.telegram_performance_collection_enabled` (default
False) - every entry point below checks the flag and no-ops when disabled, so this module changes
nothing about production behavior until explicitly turned on.

PASSIVE ONLY (spec §6's own hard constraint): every Telegram call this module makes is a pure read
- `client.get_messages(...)` (Telethon) and `bot.get_chat_member_count(...)` (aiogram Bot API).
Never `send_message`/`edit_message`/`delete_message`/`send_reaction`/any write call, to our own
channel or anyone else's. This mirrors integrations/sources/telegram_source.py's own
`connect()` + `is_user_authorized()` + `disconnect()` pattern (never `client.start()` - see that
module's own docstring for the real interactive-login-hang incident this avoids) rather than
importing that module's private helpers directly (this codebase's established convention: small
adapter-local helpers are duplicated, not cross-coupled, across independent collection paths)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message

from core.config import settings
from database.models.telegram_channel_memory import TelegramChannelMemory
from database.models.telegram_post_performance import SnapshotWindow, TelegramPostPerformanceSnapshot
from services.telegram_own_channel import owned_chat_id

logger = logging.getLogger(__name__)

CAPABILITY_VERSION = "telegram-directors-phase2-2026-09"
COLLECTOR_NAME = "telegram_performance_collection"

# Nominal schedule points (spec §5) - only windows this module actually schedules collection for.
_WINDOW_SECONDS: dict[SnapshotWindow, int] = {
    SnapshotWindow.M5: 5 * 60,
    SnapshotWindow.M30: 30 * 60,
    SnapshotWindow.H1: 60 * 60,
    SnapshotWindow.H3: 3 * 60 * 60,
    SnapshotWindow.H6: 6 * 60 * 60,
    SnapshotWindow.H24: 24 * 60 * 60,
    SnapshotWindow.H72: 72 * 60 * 60,
}


def _build_client() -> TelegramClient:
    if settings.telegram_api_id is None or settings.telegram_api_hash is None:
        raise RuntimeError("TELEGRAM_API_ID / TELEGRAM_API_HASH are not configured")
    if settings.telegram_session_string is None:
        raise RuntimeError("TELEGRAM_SESSION_STRING is not configured")
    return TelegramClient(
        StringSession(settings.telegram_session_string.get_secret_value()),
        settings.telegram_api_id,
        settings.telegram_api_hash.get_secret_value(),
    )


def _reactions_count(message: Message) -> int | None:
    if message.reactions is None:
        return None
    return sum(result.count for result in message.reactions.results)


async def fetch_engagement_metrics(
    telegram_message_id: int, *, chat_id: int | None = None,
) -> dict[str, int | None] | None:
    """Read-only: `client.get_messages(chat, ids=...)` - never sends/edits/deletes. Returns None
    when the message cannot be read at all (deleted, no access); returns a dict with per-metric
    `None` (never a guessed 0) for any field Telethon itself has no value for."""
    target_chat = chat_id if chat_id is not None else owned_chat_id()
    if target_chat is None:
        logger.warning("No owned chat_id configured - cannot collect engagement metrics")
        return None

    client = _build_client()
    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning("Telegram session not authorized - skipping performance collection")
            return None
        message = await client.get_messages(target_chat, ids=telegram_message_id)
    finally:
        await client.disconnect()

    if message is None:
        return None
    return {
        "views": message.views,
        "forwards": message.forwards,
        "reactions_total": _reactions_count(message),
        "comments_total": message.replies.replies if message.replies is not None else None,
    }


async def fetch_subscriber_count(bot: Bot) -> int | None:
    """aiogram Bot API - genuinely AVAILABLE today (services/telegram_performance_memory.py's own
    capability registry), never called anywhere else in this codebase before this phase."""
    chat_id = owned_chat_id()
    if chat_id is None:
        return None
    try:
        return await bot.get_chat_member_count(chat_id)
    except Exception:
        logger.warning("Failed to read subscriber count for owned channel", exc_info=True)
        return None


def _nearest_due_window(age_seconds: int, already_captured: set[SnapshotWindow]) -> SnapshotWindow | None:
    """The largest schedule window whose nominal point has already elapsed and has not yet been
    captured - never re-captures a window already collected, never captures a window not yet due."""
    due = [w for w, secs in _WINDOW_SECONDS.items() if secs <= age_seconds and w not in already_captured]
    if not due:
        return None
    return max(due, key=lambda w: _WINDOW_SECONDS[w])


async def collect_snapshot_for_post(
    session: AsyncSession, *, channel_memory: TelegramChannelMemory, bot: Bot | None = None,
    now: datetime | None = None,
) -> TelegramPostPerformanceSnapshot | None:
    """Passive-only, flag-gated. Never guesses a 0 for a metric it could not read - each column is
    either the real value or NULL."""
    if not settings.telegram_performance_collection_enabled:
        return None
    if channel_memory.post_id is None:
        return None

    now = now or datetime.now(timezone.utc)
    age_seconds = int((now - channel_memory.published_at).total_seconds())

    existing = list((await session.execute(
        select(TelegramPostPerformanceSnapshot.window).where(
            TelegramPostPerformanceSnapshot.channel_memory_id == channel_memory.id
        )
    )).scalars().all())
    window = _nearest_due_window(age_seconds, set(existing))
    if window is None:
        return None

    try:
        telegram_message_id = int(channel_memory.post_id)
    except ValueError:
        return None

    metrics = await fetch_engagement_metrics(telegram_message_id)
    subscriber_count = await fetch_subscriber_count(bot) if bot is not None else None

    snapshot = TelegramPostPerformanceSnapshot(
        id=uuid.uuid4(),
        channel_memory_id=channel_memory.id,
        telegram_message_id=telegram_message_id,
        window=window,
        captured_at=now,
        age_seconds=age_seconds,
        views=(metrics or {}).get("views"),
        forwards=(metrics or {}).get("forwards"),
        reactions_total=(metrics or {}).get("reactions_total"),
        comments_total=(metrics or {}).get("comments_total"),
        subscriber_count=subscriber_count,
        subscriber_delta=None,
        capability_version=CAPABILITY_VERSION,
        collector=COLLECTOR_NAME,
        raw_metadata={"metrics_read": metrics is not None},
    )
    session.add(snapshot)
    return snapshot
