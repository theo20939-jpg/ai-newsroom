"""DIRECTOR-CONTROL-PLANE-1 §5: real NINJA PULSE Telegram channel context - title/username/
description/pinned message/recent posts, via the SAME already-authenticated Telethon/MTProto
session services/telegram_performance_collection.py already established (its own module docstring:
the mechanism/auth already exist, only wiring + channel membership are missing -
AVAILABLE_WITH_EXISTING_MTPROTO in services/telegram_performance_memory.py's own capability
registry). Duplicates `_build_client()` rather than importing it (this codebase's own established
convention across every Telethon-touching module: telegram_source.py / telegram_performance_
collection.py both already duplicate the same few lines rather than cross-couple).

Passive/read-only, exactly like telegram_performance_collection.py - never a write/edit/delete/
send call. Returns `None` (never a fabricated/empty-but-successful context) whenever the surface
is not registered, the session is unauthorized, or the channel cannot be resolved - callers must
treat None as "context unavailable", not as "channel has no content."""
from __future__ import annotations

import logging

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest

from core.config import settings
from database.models.telegram_surface import TelegramSurface

logger = logging.getLogger(__name__)

_RECENT_POST_LIMIT = 10


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


async def fetch_owned_channel_context(surface: TelegramSurface) -> dict | None:
    """Real Telethon read of `surface.chat_id` (spec §5's own required field list: title/username/
    description/avatar identity/pinned message/recent posts/timestamps/media type/views/reactions/
    forwards). Never called automatically by any live worker path in this phase (matches services/
    telegram_performance_collection.py's own telegram_performance_collection_enabled gating
    precedent) - a future console/refresh command is the only intended real caller."""
    client = _build_client()
    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning("telegram_channel_context_session_not_authorized", extra={"chat_id": surface.chat_id})
            return None

        entity = await client.get_entity(surface.chat_id)
        full = await client(GetFullChannelRequest(channel=entity))
        full_chat = full.full_chat

        recent_posts = []
        async for message in client.iter_messages(surface.chat_id, limit=_RECENT_POST_LIMIT):
            if message.action is not None:
                continue
            recent_posts.append({
                "message_id": message.id,
                "date": message.date.isoformat() if message.date else None,
                "has_media": message.media is not None,
                "views": message.views,
                "forwards": message.forwards,
                "reactions_total": (
                    sum(r.count for r in message.reactions.results) if message.reactions is not None else None
                ),
            })

        return {
            "chat_id": surface.chat_id,
            "title": getattr(entity, "title", None),
            "username": getattr(entity, "username", None),
            "description": getattr(full_chat, "about", None) or None,
            "pinned_message_id": getattr(full_chat, "pinned_msg_id", None),
            "recent_posts": recent_posts,
        }
    finally:
        await client.disconnect()
