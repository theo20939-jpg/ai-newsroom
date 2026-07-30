"""Phase 16 M6: initial Telegram Editorial Preview send (docs/
phase16_m6_telegram_editorial_preview_report.md §7). Sends the top-ranked image candidate for a
ContentDraft with the interactive Previous/Next/Use/No-image keyboard - a second, independent,
additive notification alongside `services/telegram_notifier.py::send_editorial_card()`, which this
module never modifies, replaces, or imports from (Contract §3: the existing news-delivery card
stays byte-for-byte unchanged). `worker/content_cycle.py` owns the
`image_editorial_preview_enabled`/`image_candidate_persistence_mode` gating - this function itself
has no "off" branch of its own beyond "there are no candidates to show" (a normal, frequent, non-
error outcome).
"""
import logging
from dataclasses import dataclass
from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.image_preview_formatting import render_image_preview_caption
from bot.image_preview_media import resolve_photo_input
from bot.keyboards.image_preview import build_image_preview_keyboard
from services.image_persistence import get_editorial_image_candidates, record_telegram_file_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImagePreviewOutcome:
    """Mirrors services.telegram_notifier.NotificationOutcome's own "always returned, directly
    inspectable" convention. `attempted=False` means there was nothing to preview at all (zero
    eligible candidates) - not an error, not counted as a failed send."""

    attempted: bool
    sent: bool
    candidate_count: int


async def send_image_preview(
    bot: Bot, chat_id: int | None, session: AsyncSession, *, content_draft_id: UUID, draft_title: str | None,
) -> ImagePreviewOutcome:
    """No dry-run mode exists here (M6 has no publish/attach pipeline to preview a dry-run of -
    Contract's own explicit non-goal). `chat_id=None` is tolerated only when there is nothing to
    send (`candidates` empty); once a real candidate exists, `chat_id` is required, mirroring
    `services.telegram_notifier.send_editorial_card()`'s own fail-fast assertion for its live
    path."""
    candidates = await get_editorial_image_candidates(session, content_draft_id=content_draft_id)
    if not candidates:
        return ImagePreviewOutcome(attempted=False, sent=False, candidate_count=0)

    assert chat_id is not None, (
        "send_image_preview() called with no chat_id - settings.editorial_chat_id must be "
        "configured before image_editorial_preview_enabled may be set to True"
    )

    candidate = candidates[0]
    caption = render_image_preview_caption(candidate, draft_title=draft_title, index=0, total=len(candidates))
    keyboard = build_image_preview_keyboard(
        content_draft_id=content_draft_id, index=0, total=len(candidates), candidate=candidate,
    )
    photo_input = resolve_photo_input(candidate)

    try:
        if photo_input is not None:
            message = await bot.send_photo(chat_id, photo=photo_input, caption=caption, reply_markup=keyboard)
            if not candidate.telegram_file_id and message.photo:
                await record_telegram_file_id(session, candidate_row_id=candidate.id, file_id=message.photo[-1].file_id)
                await session.commit()
        else:
            await bot.send_message(chat_id, caption, reply_markup=keyboard)
    except TelegramAPIError:
        logger.exception("image_preview_send_failed", extra={"content_draft_id": str(content_draft_id)})
        return ImagePreviewOutcome(attempted=True, sent=False, candidate_count=len(candidates))

    return ImagePreviewOutcome(attempted=True, sent=True, candidate_count=len(candidates))
