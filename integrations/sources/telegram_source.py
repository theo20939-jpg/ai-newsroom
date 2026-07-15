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

logger = logging.getLogger(__name__)

MESSAGE_FETCH_LIMIT = 50


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
        """Convert one Telethon message into a RawNewsItem, or None to skip it."""
        if message.action is not None:
            return None  # service message (join/leave/pin/...), not news content

        return RawNewsItem(
            external_id=str(message.id),
            text=message.text or None,
            url=f"https://t.me/{channel}/{message.id}",
            published_at=message.date,
        )
