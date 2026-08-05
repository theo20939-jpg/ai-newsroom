"""Phase 18 M8: Telegram Meme Editorial Preview sender (docs/
phase18_m8_telegram_editorial_preview_report.md). Mirrors `services/telegram_notifier.py::
send_editorial_card()`'s exact dry-run-first contract: `dry_run=True` renders and logs the exact
payload that WOULD be sent - `bot.send_photo()`/`bot.send_message()` is never called, no
Telegram API contact of any kind. This is the explicit human-verification step required before
`meme_telegram_preview_mode` may ever be set to anything beyond `"off"`/`"dry_run"` - there is no
`"live"` value for that setting to select yet (module docstring of `services/
meme_image_generation.py` established the same pattern for image generation; this module repeats
it for the send path).

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
from schemas.meme_preview import MemePreviewCard

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemePreviewOutcome:
    """Always returned, in both dry-run and live modes - mirrors
    `services.telegram_notifier.NotificationOutcome`'s own "always inspectable" convention."""

    chat_id: int | None
    rendered_caption: str
    has_image: bool
    sent: bool  # False in dry-run mode, or if the live send itself failed


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
    bot: Bot, chat_id: int | None, storage: ImageStorage, card: MemePreviewCard, *, dry_run: bool,
) -> MemePreviewOutcome:
    """`dry_run=True`: renders and returns the exact payload that WOULD be sent - no Telegram API
    contact. Logged at INFO for human inspection (`meme_preview_dry_run`).

    `dry_run=False` (live): actually calls `bot.send_photo()`/`bot.send_message()`. A
    `MemePreviewCaptionTooLongError` (rendering) or a `TelegramAPIError` (the live send itself) is
    caught here, logged, and returned as `MemePreviewOutcome(sent=False)` - never raised past this
    function, mirroring `services.telegram_notifier.send_editorial_card()`'s own established
    per-card error handling exactly."""
    try:
        caption = render_meme_preview_caption(card)
    except MemePreviewCaptionTooLongError:
        logger.error("meme_preview_render_failed", extra={"candidate_id": str(card.candidate_id)})
        return MemePreviewOutcome(chat_id=chat_id, rendered_caption="", has_image=False, sent=False)

    photo_bytes = _resolve_photo_bytes(storage, card.image_storage_key)
    keyboard = build_meme_preview_keyboard(card.candidate_id, source_url=card.news_url)

    if dry_run:
        logger.info(
            "meme_preview_dry_run",
            extra={
                "candidate_id": str(card.candidate_id), "chat_id": chat_id, "caption": caption,
                "has_image": photo_bytes is not None,
            },
        )
        return MemePreviewOutcome(
            chat_id=chat_id, rendered_caption=caption, has_image=photo_bytes is not None, sent=False,
        )

    assert chat_id is not None, (
        "send_meme_preview(dry_run=False) called with no chat_id - a real editorial chat id must "
        "be configured before meme_telegram_preview_mode may ever select a live-sending value"
    )
    try:
        if photo_bytes is not None:
            await bot.send_photo(
                chat_id, photo=BufferedInputFile(photo_bytes, filename="meme_preview.png"),
                caption=caption, reply_markup=keyboard,
            )
        else:
            await bot.send_message(chat_id, caption, reply_markup=keyboard)
    except TelegramAPIError:
        logger.exception("meme_preview_send_failed", extra={"candidate_id": str(card.candidate_id)})
        return MemePreviewOutcome(
            chat_id=chat_id, rendered_caption=caption, has_image=photo_bytes is not None, sent=False,
        )

    return MemePreviewOutcome(
        chat_id=chat_id, rendered_caption=caption, has_image=photo_bytes is not None, sent=True,
    )
