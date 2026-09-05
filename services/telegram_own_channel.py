"""NINJA Social Intelligence Foundation, Telegram Directors Phase 2 §4: explicit own-channel
identity. Forensic finding (this phase's own research pass): there is no separate outward-facing
"channel" in this codebase today - real publication (services/final_post_publication.py) targets
`settings.newsroom_telegram_chat_id`, the same internal NINJA NEWSROOM supergroup used for
editorial review. `nnjvpn` (https://t.me/nnjvpn) is only a hardcoded CTA footer link string in
captions (services/news_telegram_presentation.py) - never a configured chat_id anywhere, so it is
NOT NNJ's identity for capability/collection purposes.

This module exists so every other Phase 2 module asks exactly ONE place "is this our own channel"
rather than each re-deriving it (and risking drift with services/collector.py's per-Source
external-channel identifiers, which live in the sources table, never in settings)."""
from __future__ import annotations

from core.config import settings


def owned_chat_id() -> int | None:
    """Real publication destination today. `telegram_owned_channel_id` is an explicit override for
    a future distinct outward channel; absent that, this is `newsroom_telegram_chat_id` - never a
    guess, never a fallback to `editorial_chat_id` (a different, older notification-only chat)."""
    if settings.telegram_owned_channel_id is not None:
        return settings.telegram_owned_channel_id
    return settings.newsroom_telegram_chat_id


def owned_username() -> str | None:
    return settings.telegram_owned_channel_username


def is_own_channel(chat_id: int | None, username: str | None = None) -> bool:
    """Never confuses an externally-monitored source channel (configured per-row in the sources
    table via services/collector.py, not here) with NNJ's own published destination."""
    if chat_id is not None and owned_chat_id() is not None and chat_id == owned_chat_id():
        return True
    configured_username = owned_username()
    if username is not None and configured_username is not None:
        return username.lstrip("@").lower() == configured_username.lstrip("@").lower()
    return False
