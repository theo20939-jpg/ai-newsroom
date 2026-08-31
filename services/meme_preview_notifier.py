"""Phase 18 M8 (revised, MEME PRODUCTION PIPELINE): Telegram Meme Editorial Preview sender.
Mirrors `services/telegram_notifier.py::send_editorial_card()`'s exact dry-run-first contract:
`dry_run=True` renders and logs the exact payload that WOULD be sent - `bot.send_photo()`/
`bot.send_message()` is never called, no Telegram API contact of any kind.

MEME PRODUCTION PIPELINE fix: routes through `services.telegram_routing.resolve_route()` /
`EditorialDestination.MEME` - the SAME centralized destination-resolution this codebase already
uses for TELEGRAPH/NEWS/etc (`meme_topic_id` in `core/config.py`) - never a raw `chat_id` param
supplied by the caller. Prior to this phase, this function took `chat_id` directly and never
passed `message_thread_id` at all, so a real send would have landed in the configured chat's ROOT,
never inside the MEMES forum topic specifically - a real, disclosed gap this fix closes. Every
meme this function ever sends routes to `EditorialDestination.MEME` and nowhere else.

Simplification vs. Phase 16's `bot/image_preview_media.py` (disclosed, not an oversight): no
`telegram_file_id` caching - `MemeCandidate` has no such column (unlike `ImageCandidateRecord`).
Every send reads the rendered image bytes fresh from `ImageStorage`. Revisiting this to add
caching is a reasonable, contained future optimization once real send volume exists.
"""
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile

from bot.keyboards.meme_preview import build_meme_preview_keyboard
from bot.meme_preview_formatting import MemePreviewCaptionTooLongError, render_meme_preview_caption
from integrations.storage.image_storage import ImageStorage, StorageError
from schemas.editorial_route import EditorialDestination
from schemas.meme_preview import MemePreviewCard
from services.telegram_routing import resolve_route

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemePreviewOutcome:
    """Always returned, in both dry-run and live modes - mirrors
    `services.telegram_notifier.NotificationOutcome`'s own "always inspectable" convention.
    `reason` is `None` only when `sent` is `True` - mirrors `services.telegram_routing.
    RoutingOutcome`'s identical discipline (added this phase, additive - every pre-existing field
    is unchanged)."""

    chat_id: int | None
    rendered_caption: str
    has_image: bool
    sent: bool  # False in dry-run mode, or if the live send itself failed
    reason: str | None = None


def _resolve_photo_bytes(storage: ImageStorage, storage_key: str | None) -> bytes | None:
    if storage_key is None:
        return None
    try:
        if not storage.exists(storage_key):
            return None
        return storage.read(storage_key)
    except (StorageError, OSError):
        logger.warning("meme_preview_photo_read_failed", extra={"storage_key": storage_key})
        return None


async def send_meme_preview(
    bot: Bot, storage: ImageStorage, card: MemePreviewCard, *, dry_run: bool,
) -> MemePreviewOutcome:
    """`dry_run=True`: renders and returns the exact payload that WOULD be sent - no Telegram API
    contact. Logged at INFO for human inspection (`meme_preview_dry_run`).

    `dry_run=False` (live): resolves `EditorialDestination.MEME` and actually calls
    `bot.send_photo()`/`bot.send_message()` with `message_thread_id` set to the resolved MEME
    topic id. Never sends anywhere else - an unconfigured destination (`resolve_route()` returns
    `None`) is reported as `sent=False, reason="unconfigured_destination"`, never a fallback send
    to some other chat/topic. A `MemePreviewCaptionTooLongError` (rendering) or a
    `TelegramAPIError` (the live send itself) is caught here, logged, and returned as
    `MemePreviewOutcome(sent=False)` - never raised past this function."""
    try:
        caption = render_meme_preview_caption(card)
    except MemePreviewCaptionTooLongError:
        logger.error("meme_preview_render_failed", extra={"candidate_id": str(card.candidate_id)})
        return MemePreviewOutcome(chat_id=None, rendered_caption="", has_image=False, sent=False, reason="caption_too_long")

    photo_bytes = _resolve_photo_bytes(storage, card.image_storage_key)
    keyboard = build_meme_preview_keyboard(card.candidate_id, source_url=card.news_url)

    route = resolve_route(EditorialDestination.MEME)
    if route is None:
        logger.warning("meme_preview_unconfigured_destination", extra={"candidate_id": str(card.candidate_id)})
        return MemePreviewOutcome(
            chat_id=None, rendered_caption=caption, has_image=photo_bytes is not None, sent=False,
            reason="unconfigured_destination",
        )

    if dry_run:
        logger.info(
            "meme_preview_dry_run",
            extra={
                "candidate_id": str(card.candidate_id), "chat_id": route.chat_id, "topic_id": route.topic_id,
                "caption": caption, "has_image": photo_bytes is not None,
            },
        )
        return MemePreviewOutcome(
            chat_id=route.chat_id, rendered_caption=caption, has_image=photo_bytes is not None, sent=False,
            reason="dry_run",
        )

    try:
        if photo_bytes is not None:
            await bot.send_photo(
                route.chat_id, photo=BufferedInputFile(photo_bytes, filename="meme_preview.png"),
                caption=caption, reply_markup=keyboard, message_thread_id=route.topic_id,
            )
        else:
            await bot.send_message(route.chat_id, caption, reply_markup=keyboard, message_thread_id=route.topic_id)
    except TelegramAPIError:
        logger.exception("meme_preview_send_failed", extra={"candidate_id": str(card.candidate_id)})
        return MemePreviewOutcome(
            chat_id=route.chat_id, rendered_caption=caption, has_image=photo_bytes is not None, sent=False,
            reason="telegram_api_error",
        )

    return MemePreviewOutcome(
        chat_id=route.chat_id, rendered_caption=caption, has_image=photo_bytes is not None, sent=True,
    )
