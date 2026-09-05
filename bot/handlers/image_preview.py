"""Phase 16 M6 + UX fix: Telegram Editorial Preview callback handler (docs/
phase16_m6_telegram_editorial_preview_report.md §6/§8/§9, docs/phase16_ux_combined_preview_fix_
report.md). Thin orchestration only, mirroring bot/handlers/news.py's own "no query construction,
no AI/workflow call, no mutation logic of its own" discipline - every DB read/write and every byte
resolution goes through services/image_persistence.py; this module never imports
integrations.storage.image_storage directly.

Every state a callback needs (which draft, which candidate index) travels entirely inside
`callback_data` (bot/keyboards/image_preview.py); the candidate list itself is always re-queried
fresh from the database on every single callback - never cached, never trusted from an earlier
render, so a stale/expired/deleted candidate is always detected against current state, not
whatever was true when the button was first sent (docs §9).

UX fix: every rendered caption/text is now the *actual* news card content
(`bot/formatting.py::render_editorial_card()`, reused directly) - never candidate-specific
technical metadata, and never a separate "Image selected" confirmation message. Navigating
(Previous/Next) or deciding (Use image/No image) always edits the one message already on screen;
this handler never sends an additional new message of its own (the only exception, mirroring M6's
own established precedent, is the unavoidable delete+resend when Telegram itself has no API to
convert a photo message into a text message or back).
"""
import logging
from uuid import UUID

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InaccessibleMessage, InputMediaPhoto, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.formatting import CardTooLongError, render_editorial_card
from bot.image_preview_formatting import (
    CAPTION_SAFE_LIMIT,
    render_expired_candidate_alert_text,
    render_unavailable_candidate_alert_text,
)
from bot.keyboards.image_preview import build_image_preview_keyboard, build_source_only_keyboard, parse_callback_data
from bot.keyboards.meme_generate import append_meme_generate_button
from database.models.content_draft import ContentDraft
from database.models.editorial_task import EditorialTask
from database.models.news_event import NewsEvent
from database.session import async_session_factory
from schemas.editorial_inbox import EditorialInboxCard
from services.image_persistence import (
    EditorialImageCandidate,
    get_editorial_image_candidates,
    record_telegram_file_id,
    reject_all_candidates,
    set_editor_decision,
)
from services.media_finalizer import finalize_photo_input

logger = logging.getLogger(__name__)

router = Router(name="image_preview")

_SAFE_LIMIT = 4096  # bot/formatting.py::SAFE_LIMIT - duplicated as a plain int to avoid a second import name


def _to_card(draft: ContentDraft, event: NewsEvent) -> EditorialInboxCard:
    """Byte-for-byte the same mapping services/image_preview_notifier.py's own `_to_card()` uses
    (which itself mirrors services/telegram_notifier.py's) - duplicated per this codebase's own
    established small-mapping convention; this call site has raw ORM rows, not a `ContentDraftRead`."""
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


async def _load_card_and_event(
    session: AsyncSession, content_draft_id: UUID,
) -> tuple[EditorialInboxCard, NewsEvent] | None:
    draft = await session.get(ContentDraft, content_draft_id)
    if draft is None:
        return None
    task = await session.get(EditorialTask, draft.task_id)
    if task is None:
        return None
    event = await session.get(NewsEvent, task.event_id)
    if event is None:
        return None
    return _to_card(draft, event), event


async def _render_candidate(
    message: Message, *, card: EditorialInboxCard, event: NewsEvent,
    candidates: list[EditorialImageCandidate], index: int,
) -> None:
    """Renders one candidate at `index` into the given message - the caption/text is always the
    real news card (never candidate metadata); only the attached photo and the keyboard's
    Previous/Next position change between candidates. Swaps between a photo and a text-only
    message as needed - Telegram's `editMessageMedia`/`editMessageCaption` cannot convert a text
    message into a photo message or vice versa, so a type change is handled by deleting the old
    message and sending a fresh one (docs §9's own documented approach)."""
    candidate = candidates[index]
    photo_input = finalize_photo_input(candidate)
    caption_limit = CAPTION_SAFE_LIMIT if photo_input is not None else _SAFE_LIMIT
    try:
        caption = render_editorial_card(card, limit=caption_limit, include_url=False)
    except CardTooLongError:
        logger.error("image_preview_render_card_too_long", extra={"draft_id": str(card.draft_id)})
        return
    keyboard = build_image_preview_keyboard(
        content_draft_id=card.draft_id, index=index, total=len(candidates), candidate=candidate,
    )
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
        logger.exception("image_preview_render_failed", extra={"draft_id": str(card.draft_id)})
        return

    if not candidate.telegram_file_id and result is not None and result.photo:
        file_id = result.photo[-1].file_id
        async with async_session_factory() as session:
            await record_telegram_file_id(session, candidate_row_id=candidate.id, file_id=file_id)
            await session.commit()


async def _finalize_decision(
    message: Message, *, card: EditorialInboxCard, event: NewsEvent, keep_photo: bool,
) -> None:
    """Terminal state for the message once a decision has been made (docs §8, UX fix) - always
    shows the real news content (never a technical "Image selected"/"No image" confirmation
    string) with only the Source button (plus, MEME-PROD-1, the manual meme-generate button)
    remaining, ending the interactive Previous/Next/Use/No-image flow. `keep_photo`
    is `False` for "No image" (the message must become text-only - Telegram cannot edit a photo
    message into a text-only one, so this is a delete+resend, the same technique `_render_candidate`
    already uses for a type change) and `True` for "Use image" (the already-attached photo and its
    caption are correct as-is; only the keyboard needs to shrink to just the Source button)."""
    # MEME PRODUCTION PIPELINE (MEME-PROD-1): this IS the message's terminal, settled state
    # (docstring above) - the same "every NEWS message that ends up with a Source keyboard also
    # gets the manual meme button" rule services/image_preview_notifier.py's own text-only fallback
    # and worker/content_cycle.py's primary send path both already apply. Never added to the
    # earlier, still-interactive Previous/Next/Use/No-image keyboard - only here, once settled.
    keyboard = append_meme_generate_button(build_source_only_keyboard(event.url), event.id)
    bot = message.bot
    assert bot is not None
    has_photo = bool(message.photo)

    try:
        if keep_photo and has_photo:
            text = render_editorial_card(card, limit=CAPTION_SAFE_LIMIT, include_url=False)
            await bot.edit_message_caption(
                chat_id=message.chat.id, message_id=message.message_id, caption=text, reply_markup=keyboard,
            )
        elif not keep_photo and has_photo:
            text = render_editorial_card(card, include_url=False)
            await bot.delete_message(message.chat.id, message.message_id)
            await bot.send_message(message.chat.id, text, reply_markup=keyboard)
        else:
            text = render_editorial_card(card, include_url=False)
            await bot.edit_message_text(
                chat_id=message.chat.id, message_id=message.message_id, text=text, reply_markup=keyboard,
            )
    except CardTooLongError:
        logger.error("image_preview_finalize_card_too_long", extra={"draft_id": str(card.draft_id)})
    except TelegramAPIError:
        logger.exception("image_preview_finalize_failed", extra={"draft_id": str(card.draft_id)})


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
            loaded = await _load_card_and_event(session, content_draft_id)
        except Exception:
            logger.exception("image_preview_query_failed", extra={"content_draft_id": str(content_draft_id)})
            await callback.answer("Something went wrong.", show_alert=True)
            return

        if not candidates or loaded is None:
            await callback.answer(render_unavailable_candidate_alert_text(), show_alert=True)
            return
        card, event = loaded

        safe_index = min(index, len(candidates) - 1)

        if action in ("prev", "next"):
            if candidates[safe_index].is_expired:
                await callback.answer(render_expired_candidate_alert_text(), show_alert=True)
                return
            await _render_candidate(message, card=card, event=event, candidates=candidates, index=safe_index)
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
            await _finalize_decision(message, card=card, event=event, keep_photo=True)
            await callback.answer("Image selected.")
            return

        # action == "none"
        await reject_all_candidates(session, content_draft_id=content_draft_id)
        await session.commit()
        await _finalize_decision(message, card=card, event=event, keep_photo=False)
        await callback.answer("No image will be used.")
