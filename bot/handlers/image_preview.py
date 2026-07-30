"""Phase 16 M6: Telegram Editorial Preview callback handler (docs/
phase16_m6_telegram_editorial_preview_report.md §6/§8/§9). Thin orchestration only, mirroring
bot/handlers/news.py's own "no query construction, no AI/workflow call, no mutation logic of its
own" discipline - every DB read/write and every byte resolution goes through
services/image_persistence.py; this module never imports SQLAlchemy models or
integrations.storage.image_storage directly.

Every state a callback needs (which draft, which candidate index) travels entirely inside
`callback_data` (bot/keyboards/image_preview.py); the candidate list itself is always re-queried
fresh from the database on every single callback - never cached, never trusted from an earlier
render, so a stale/expired/deleted candidate is always detected against current state, not
whatever was true when the button was first sent (docs §9).
"""
import logging
from uuid import UUID

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InaccessibleMessage, InputMediaPhoto, Message

from bot.image_preview_formatting import (
    render_decision_confirmation_text,
    render_expired_candidate_alert_text,
    render_image_preview_caption,
    render_unavailable_candidate_alert_text,
)
from bot.image_preview_media import resolve_photo_input
from bot.keyboards.image_preview import build_image_preview_keyboard, parse_callback_data
from database.models.content_draft import ContentDraft
from database.session import async_session_factory
from services.image_persistence import (
    EditorialImageCandidate,
    get_editorial_image_candidates,
    record_telegram_file_id,
    reject_all_candidates,
    set_editor_decision,
)

logger = logging.getLogger(__name__)

router = Router(name="image_preview")


async def _render_candidate(
    message: Message, *, content_draft_id: UUID, draft_title: str | None,
    candidates: list[EditorialImageCandidate], index: int,
) -> None:
    """Renders one candidate at `index` into the given message, swapping between a photo and a
    text-only message as needed - Telegram's `editMessageMedia`/`editMessageCaption` cannot
    convert a text message into a photo message or vice versa, so a type change is handled by
    deleting the old message and sending a fresh one (docs §9's own documented approach)."""
    candidate = candidates[index]
    caption = render_image_preview_caption(candidate, draft_title=draft_title, index=index, total=len(candidates))
    keyboard = build_image_preview_keyboard(
        content_draft_id=content_draft_id, index=index, total=len(candidates), candidate=candidate,
    )
    photo_input = resolve_photo_input(candidate)
    has_photo = bool(message.photo)
    bot = message.bot
    assert bot is not None

    result: Message | None = None
    try:
        if photo_input is not None and has_photo:
            edited = await bot.edit_message_media(
                chat_id=message.chat.id, message_id=message.message_id,
                media=InputMediaPhoto(media=photo_input, caption=caption),
                reply_markup=keyboard,
            )
            result = edited if isinstance(edited, Message) else None
        elif photo_input is not None and not has_photo:
            await bot.delete_message(message.chat.id, message.message_id)
            result = await bot.send_photo(message.chat.id, photo=photo_input, caption=caption, reply_markup=keyboard)
        elif photo_input is None and has_photo:
            await bot.delete_message(message.chat.id, message.message_id)
            result = await bot.send_message(message.chat.id, caption, reply_markup=keyboard)
        else:
            await bot.edit_message_text(
                chat_id=message.chat.id, message_id=message.message_id, text=caption, reply_markup=keyboard,
            )
    except TelegramAPIError:
        logger.exception("image_preview_render_failed", extra={"content_draft_id": str(content_draft_id)})
        return

    if not candidate.telegram_file_id and result is not None and result.photo:
        file_id = result.photo[-1].file_id
        async with async_session_factory() as session:
            await record_telegram_file_id(session, candidate_row_id=candidate.id, file_id=file_id)
            await session.commit()


async def _finalize_decision(message: Message, *, selected: bool, candidate: EditorialImageCandidate | None) -> None:
    """Replaces the interactive caption/text with a confirmation and removes the keyboard,
    ending the interactive flow for that message (docs §8)."""
    text = render_decision_confirmation_text(selected=selected, candidate=candidate)
    bot = message.bot
    assert bot is not None
    try:
        if message.photo:
            await bot.edit_message_caption(
                chat_id=message.chat.id, message_id=message.message_id, caption=text, reply_markup=None,
            )
        else:
            await bot.edit_message_text(
                chat_id=message.chat.id, message_id=message.message_id, text=text, reply_markup=None,
            )
    except TelegramAPIError:
        logger.exception("image_preview_finalize_failed")


@router.callback_query(F.data.startswith("imgprev:"))
async def handle_image_preview_callback(callback: CallbackQuery) -> None:
    parsed = parse_callback_data(callback.data or "")
    if parsed is None:
        await callback.answer()
        return
    action, content_draft_id, index = parsed

    message = callback.message
    if message is None or isinstance(message, InaccessibleMessage):
        await callback.answer(render_unavailable_candidate_alert_text(), show_alert=True)
        return

    async with async_session_factory() as session:
        try:
            candidates = await get_editorial_image_candidates(session, content_draft_id=content_draft_id)
            draft = await session.get(ContentDraft, content_draft_id)
        except Exception:
            logger.exception("image_preview_query_failed", extra={"content_draft_id": str(content_draft_id)})
            await callback.answer("Something went wrong.", show_alert=True)
            return

        if not candidates:
            await callback.answer(render_unavailable_candidate_alert_text(), show_alert=True)
            return

        safe_index = min(index, len(candidates) - 1)
        draft_title = draft.title if draft is not None else None

        if action in ("prev", "next"):
            if candidates[safe_index].is_expired:
                await callback.answer(render_expired_candidate_alert_text(), show_alert=True)
                return
            await _render_candidate(
                message, content_draft_id=content_draft_id, draft_title=draft_title,
                candidates=candidates, index=safe_index,
            )
            await callback.answer()
            return

        if action == "use":
            target = candidates[safe_index]
            if target.is_expired:
                await callback.answer(render_expired_candidate_alert_text(), show_alert=True)
                return
            ok = await set_editor_decision(session, content_draft_id=content_draft_id, candidate_row_id=target.id)
            if not ok:
                await callback.answer(render_unavailable_candidate_alert_text(), show_alert=True)
                return
            await session.commit()
            await _finalize_decision(message, selected=True, candidate=target)
            await callback.answer("Image selected.")
            return

        # action == "none"
        await reject_all_candidates(session, content_draft_id=content_draft_id)
        await session.commit()
        await _finalize_decision(message, selected=False, candidate=None)
        await callback.answer("No image will be used.")
