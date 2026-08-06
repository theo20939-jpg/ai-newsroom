"""Phase 16 M6 + UX fix: combined Telegram news+image delivery (docs/
phase16_m6_telegram_editorial_preview_report.md §7, docs/phase16_ux_combined_preview_fix_report.md).

Live validation of the original M6 design (two independent messages - a text news card via
`services/telegram_notifier.py::send_editorial_card()`, plus a separate technical image-preview
message) surfaced a real UX defect: the operator saw two messages for one news item, the second
carrying candidate metadata (quality/relevance score) rather than the actual drafted news text, and
a further, separate "Image selected for this draft" message once a decision was made. This module
now sends exactly ONE message per draft whenever the image-preview flow is active: the *real* news
card content (title/body/hashtags - `bot/formatting.py::render_editorial_card()`, reused directly,
never duplicated) as the photo caption (or plain text, if no candidate has resolvable bytes/exists
at all), with the source shown only via an inline button - never as a URL in the body.

`worker/content_cycle.py` calls this function INSTEAD OF `send_editorial_card()` (not in addition
to it) whenever `image_editorial_preview_enabled` and `image_candidate_persistence_mode != "off"` -
the only two settings this module's own behavior is gated by; `send_editorial_card()` itself is
never modified, imported, or called from here, and remains the exact, byte-identical text-only path
for every other environment.
"""
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.formatting import SAFE_LIMIT, CardTooLongError, render_editorial_card
from bot.image_preview_formatting import CAPTION_SAFE_LIMIT
from bot.image_preview_media import resolve_photo_input
from bot.keyboards.image_preview import build_image_preview_keyboard, build_source_only_keyboard
from database.models.news_event import NewsEvent
from schemas.content_draft import ContentDraftRead
from schemas.editorial_inbox import EditorialInboxCard
from services.image_persistence import get_editorial_image_candidates, record_telegram_file_id

logger = logging.getLogger(__name__)


def _to_card(draft: ContentDraftRead, event: NewsEvent) -> EditorialInboxCard:
    """Byte-for-byte the same field mapping services/telegram_notifier.py's own `_to_card()`
    already uses - duplicated intentionally rather than imported, per this codebase's own
    established convention for small, single-purpose mappings (mirrors e.g.
    `worker/content_cycle.py::_extract_scoring_result()`'s own documented rationale for the same
    choice) - keeps `services/telegram_notifier.py` completely untouched."""
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
    )


@dataclass(frozen=True)
class CombinedCardOutcome:
    """Mirrors services.telegram_notifier.NotificationOutcome's own "always returned, directly
    inspectable" convention - this function is the sole delivery path whenever the image-preview
    flow is active, so its outcome must be just as inspectable as the text-only path it replaces."""

    chat_id: int | None
    sent: bool  # False in dry-run mode, or if the live send itself failed
    has_image: bool
    candidate_count: int
    # Phase 18.10 M3: captured from the real aiogram Message the live send returns - see
    # services.telegram_notifier.NotificationOutcome's own identical field for the full contract.
    message_id: int | None = None


async def send_news_with_image_preview(
    bot: Bot, chat_id: int | None, session: AsyncSession, *,
    draft: ContentDraftRead, event: NewsEvent, dry_run: bool, reply_to_message_id: int | None = None,
) -> CombinedCardOutcome:
    """The sole delivery function whenever the image-preview flow is active - always sends exactly
    one message (text-only if there is no eligible candidate at all, a photo otherwise), never two.

    `dry_run` mirrors `services.telegram_notifier.send_editorial_card()`'s own established
    contract exactly (Phase 15 M5.8 fact-safety suppression / the global `content_generation_
    dry_run` flag both flow through this same parameter) - renders and logs, never calls the
    Telegram API, when `True`."""
    card = _to_card(draft, event)
    candidates = await get_editorial_image_candidates(session, content_draft_id=draft.id)

    if not candidates:
        try:
            text = render_editorial_card(card, include_url=False)
        except CardTooLongError:
            logger.error("content_notification_render_failed", extra={"draft_id": str(draft.id)})
            return CombinedCardOutcome(chat_id=chat_id, sent=False, has_image=False, candidate_count=0)
        keyboard = build_source_only_keyboard(event.url)

        if dry_run:
            logger.info(
                "content_notification_dry_run",
                extra={"draft_id": str(draft.id), "chat_id": chat_id, "html": text, "has_image": False},
            )
            return CombinedCardOutcome(chat_id=chat_id, sent=False, has_image=False, candidate_count=0)

        assert chat_id is not None, (
            "send_news_with_image_preview() called with no chat_id - settings.editorial_chat_id "
            "must be configured before image_editorial_preview_enabled may be set to True"
        )
        try:
            message = await bot.send_message(
                chat_id, text, reply_markup=keyboard, reply_to_message_id=reply_to_message_id,
            )
        except TelegramAPIError:
            logger.exception("content_notification_failed", extra={"draft_id": str(draft.id)})
            return CombinedCardOutcome(chat_id=chat_id, sent=False, has_image=False, candidate_count=0)
        return CombinedCardOutcome(
            chat_id=chat_id, sent=True, has_image=False, candidate_count=0, message_id=message.message_id,
        )

    candidate = candidates[0]
    photo_input = resolve_photo_input(candidate)
    caption_limit = CAPTION_SAFE_LIMIT if photo_input is not None else SAFE_LIMIT
    try:
        caption = render_editorial_card(card, limit=caption_limit, include_url=False)
    except CardTooLongError:
        logger.error("content_notification_render_failed", extra={"draft_id": str(draft.id)})
        return CombinedCardOutcome(chat_id=chat_id, sent=False, has_image=False, candidate_count=len(candidates))

    keyboard = build_image_preview_keyboard(
        content_draft_id=draft.id, index=0, total=len(candidates), candidate=candidate,
    )

    if dry_run:
        logger.info(
            "content_notification_dry_run",
            extra={
                "draft_id": str(draft.id), "chat_id": chat_id, "html": caption,
                "has_image": photo_input is not None,
            },
        )
        return CombinedCardOutcome(
            chat_id=chat_id, sent=False, has_image=photo_input is not None, candidate_count=len(candidates),
        )

    assert chat_id is not None, (
        "send_news_with_image_preview() called with no chat_id - settings.editorial_chat_id "
        "must be configured before image_editorial_preview_enabled may be set to True"
    )
    try:
        if photo_input is not None:
            message = await bot.send_photo(
                chat_id, photo=photo_input, caption=caption, reply_markup=keyboard,
                reply_to_message_id=reply_to_message_id,
            )
            if not candidate.telegram_file_id and message.photo:
                await record_telegram_file_id(session, candidate_row_id=candidate.id, file_id=message.photo[-1].file_id)
                await session.commit()
        else:
            message = await bot.send_message(
                chat_id, caption, reply_markup=keyboard, reply_to_message_id=reply_to_message_id,
            )
    except TelegramAPIError:
        logger.exception("content_notification_failed", extra={"draft_id": str(draft.id)})
        return CombinedCardOutcome(
            chat_id=chat_id, sent=False, has_image=photo_input is not None, candidate_count=len(candidates),
        )

    return CombinedCardOutcome(
        chat_id=chat_id, sent=True, has_image=photo_input is not None, candidate_count=len(candidates),
        message_id=message.message_id,
    )
