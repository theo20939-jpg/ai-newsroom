"""Phase 14 minimal Telegram push-notification sender (docs/
phase14_autonomous_newsroom_implementation_plan.md §5).

Reuses, unmodified: bot/formatting.py::render_editorial_card() for HTML rendering,
schemas/editorial_inbox.py::EditorialInboxCard as the transport-neutral view model - the exact
same shape services/editorial_inbox_service.py's own _to_card() already builds for /news. No new
formatting system, no new card shape.

MUST NOT: retry a failed send, track "notified" state anywhere (no duplicate-notification
protection exists for this MVP - a failed send is logged and the caller moves on; the durable
fallback for a lost push notification is the existing, unmodified /news command, which reads
ContentDraft directly and unconditionally on notification history).
"""
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from bot.formatting import CardTooLongError, render_editorial_card
from database.models.news_event import NewsEvent
from schemas.content_draft import ContentDraftRead
from schemas.editorial_inbox import EditorialInboxCard

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationOutcome:
    """Always returned, in both dry-run and live modes - makes the exact outgoing payload
    directly inspectable by the caller/tests, not merely logged (mirrors scripts/run_content_
    generation.py's own ContentGenerationOutcome directly-inspectable-result convention)."""

    chat_id: int | None  # None only possible in dry-run mode (not yet configured)
    rendered_html: str
    sent: bool  # False in dry-run mode, or if the live send itself failed
    # Phase 18.10 M3: captured from the real aiogram Message the live send returns - previously
    # discarded entirely. None whenever `sent` is False (dry-run or a failed send) - never
    # fabricated. The caller (worker/content_cycle.py) is responsible for treating "sent" as
    # provisional until this value is durably persisted (services/story_telegram_delivery.py's
    # own "not successful unless telegram_message_id is persisted" contract).
    message_id: int | None = None


def to_editorial_card(
    draft: ContentDraftRead, event: NewsEvent, *, quote_text: str | None = None, quote_speaker: str | None = None,
) -> EditorialInboxCard:
    """Byte-for-byte the same field mapping services/editorial_inbox_service.py::_to_card()
    already uses for /news - not a new card shape (Phase 18.10 M5 adds the optional quote_text/
    quote_speaker pair, both defaulting to None - every pre-18.10 caller unaffected).

    Public (Phase 23.1A, renamed from `_to_card`): reused directly by `worker/content_cycle.py`'s
    router-mode delivery branch (docs/phase23_1a_canary_delivery_adapter_report.md) so the two
    delivery paths render an identical card from an identical mapping - never a second,
    duplicated field-mapping function. No other module imported the private name (confirmed
    before renaming), so this is a pure export, not a behavior change."""
    return EditorialInboxCard(
        draft_id=draft.id,
        draft_title=draft.title,
        draft_body=draft.body,
        hashtags=draft.hashtags,  # type: ignore[arg-type]
        draft_created_at=draft.created_at,
        news_title=event.title,
        news_category=event.category.value,
        news_url=event.url,
        news_published_at=event.published_at,
        quote_text=quote_text,
        quote_speaker=quote_speaker,
    )


async def send_editorial_card(
    bot: Bot, chat_id: int | None, draft: ContentDraftRead, event: NewsEvent, *,
    dry_run: bool, reply_to_message_id: int | None = None,
    quote_text: str | None = None, quote_speaker: str | None = None,
) -> NotificationOutcome:
    """dry_run=True: renders and returns the exact payload that WOULD be sent - bot.send_message()
    is never called, no Telegram API contact of any kind. Logged at INFO for human inspection
    (content_notification_dry_run) - this is the "explicit human verification" step docs/
    phase14_autonomous_newsroom_implementation_plan.md §5/§8 requires before ever switching to
    live sending.

    dry_run=False (live): actually calls bot.send_message(). A CardTooLongError (rendering) or a
    TelegramAPIError (the live send itself) is caught here, logged, and returned as
    NotificationOutcome(sent=False) - never raised past this function, mirroring bot/handlers/
    news.py's own established per-card error handling exactly, so one bad card/send never aborts
    the caller's own batch loop (worker/content_cycle.py).

    chat_id=None is tolerated in dry_run mode (part of what dry-run exists to surface - a human
    inspecting a dry-run payload can see editorial_chat_id is not configured yet, before it needs
    to be). In live mode (dry_run=False), chat_id=None is a configuration error, not a silent
    no-op - fails loud via the assertion below, mirroring bot/loader.py::create_bot()'s own
    fail-fast convention for missing required Telegram configuration."""
    card = to_editorial_card(draft, event, quote_text=quote_text, quote_speaker=quote_speaker)
    try:
        html = render_editorial_card(card)  # bot/formatting.py - unmodified
    except CardTooLongError:
        logger.error("content_notification_render_failed", extra={"draft_id": str(draft.id)})
        return NotificationOutcome(chat_id=chat_id, rendered_html="", sent=False)

    if dry_run:
        logger.info(
            "content_notification_dry_run",
            extra={"draft_id": str(draft.id), "chat_id": chat_id, "html": html},
        )
        return NotificationOutcome(chat_id=chat_id, rendered_html=html, sent=False)

    assert chat_id is not None, (
        "send_editorial_card(dry_run=False) called with no chat_id - settings.editorial_chat_id "
        "must be configured before content_generation_dry_run may be set to False"
    )
    try:
        message = await bot.send_message(
            chat_id, html, parse_mode=ParseMode.HTML, reply_to_message_id=reply_to_message_id,
        )
    except TelegramAPIError:
        logger.exception("content_notification_failed", extra={"draft_id": str(draft.id)})
        return NotificationOutcome(chat_id=chat_id, rendered_html=html, sent=False)

    return NotificationOutcome(chat_id=chat_id, rendered_html=html, sent=True, message_id=message.message_id)
