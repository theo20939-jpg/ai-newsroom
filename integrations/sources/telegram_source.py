"""Telegram Client API (Telethon) adapter for the Source Collector.

Uses the Telegram Client API via Telethon and a pre-generated StringSession.
This is completely separate from the Telegram Bot API used by bot/
(aiogram, TELEGRAM_BOT_TOKEN) - different credentials, different client,
no shared imports between the two.
"""
import logging

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message

from core.config import settings
from database.models.news_source import NewsSource
from integrations.sources.base import SourceAdapter, SourceFetchContext
from schemas.raw_news_item import RawNewsItem
from services.image_intelligence import extract_telegram_native_media

logger = logging.getLogger(__name__)

MESSAGE_FETCH_LIMIT = 50


def _reactions_count(message: Message) -> int | None:
    """Deterministic aggregate: sum of every reaction type's count (Phase 15 M3.3) - no
    sentiment/taxonomy, just a total. `None` when the message carries no `reactions` object at
    all (reactions disabled, or Telethon simply has nothing for this message) - a message with
    reactions enabled but zero cast reactions has `reactions.results == []`, which correctly
    sums to `0`, not `None`."""
    if message.reactions is None:
        return None
    return sum(result.count for result in message.reactions.results)


class TelegramSourceAdapter(SourceAdapter):
    """Fetches recent messages from a Telegram channel via Telethon."""

    async def fetch(self, source: NewsSource, context: SourceFetchContext) -> list[RawNewsItem]:
        """Fetch up to MESSAGE_FETCH_LIMIT recent messages from source.url."""
        client = self._build_client()
        channel = source.url.lstrip("@") if source.url else source.url

        items: list[RawNewsItem] = []
        async with client:
            async for message in client.iter_messages(channel, limit=MESSAGE_FETCH_LIMIT):
                item = self._to_raw_item(message, channel)
                if item is not None:
                    items.append(item)

        logger.info("Fetched %d messages from %s", len(items), source.url)
        return items

    @staticmethod
    def _build_client() -> TelegramClient:
        """Build a Telethon client from the configured StringSession."""
        if settings.telegram_api_id is None or settings.telegram_api_hash is None:
            raise RuntimeError("TELEGRAM_API_ID / TELEGRAM_API_HASH are not configured")
        if settings.telegram_session_string is None:
            raise RuntimeError("TELEGRAM_SESSION_STRING is not configured")

        return TelegramClient(
            StringSession(settings.telegram_session_string.get_secret_value()),
            settings.telegram_api_id,
            settings.telegram_api_hash.get_secret_value(),
        )

    @staticmethod
    def _to_raw_item(message: Message, channel: str) -> RawNewsItem | None:
        """Convert one Telethon message into a RawNewsItem, or None to skip it.

        Phase 15 M3: views/forwards/replies/reactions are read directly from the `Message`
        object already fetched above by `iter_messages()` - no additional Telethon/Telegram API
        call is made to obtain them. Each is left `None` (not 0) when Telethon itself has no
        value for it (private/limited channels, older messages, reactions/comments disabled,
        or a message type that doesn't carry the field at all) - see `_reactions_count()`.
        """
        if message.action is not None:
            return None  # service message (join/leave/pin/...), not news content

        return RawNewsItem(
            external_id=str(message.id),
            text=message.text or None,
            url=f"https://t.me/{channel}/{message.id}",
            published_at=message.date,
            views_count=message.views,
            forwards_count=message.forwards,
            replies_count=message.replies.replies if message.replies is not None else None,
            reactions_count=_reactions_count(message),
            # Phase 16 M1: native photo/document metadata only - never downloaded here (docs/
            # phase16_m1_native_media_ingestion_report.md). Extraction failure must never break
            # collection of the message's text, so this is never allowed to raise past this point.
            native_media_hints=extract_telegram_native_media(message),
        )
