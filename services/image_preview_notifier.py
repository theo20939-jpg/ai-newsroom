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
from aiogram.types import InputMediaPhoto, InputMediaVideo, MediaUnion
from sqlalchemy.ext.asyncio import AsyncSession

from bot.formatting import SAFE_LIMIT, CardTooLongError, render_editorial_card
from bot.image_preview_formatting import CAPTION_SAFE_LIMIT
from bot.image_preview_media import resolve_photo_input
from bot.keyboards.image_preview import build_image_preview_keyboard, build_source_only_keyboard
from database.models.news_event import NewsEvent
from schemas.content_draft import ContentDraftRead
from schemas.editorial_inbox import EditorialInboxCard
from schemas.video_candidate import NativeVideoHint, VideoPlatform
from services.image_persistence import (
    EditorialImageCandidate,
    get_editorial_image_candidates,
    record_telegram_file_id,
)

logger = logging.getLogger(__name__)

# Telegram's own hard constraint on bot.send_media_group() - between 2 and 10 items.
_MEDIA_GROUP_MAX_ITEMS = 10
_MEDIA_GROUP_MIN_ITEMS = 2


def _to_card(
    draft: ContentDraftRead, event: NewsEvent, *, quote_text: str | None = None, quote_speaker: str | None = None,
) -> EditorialInboxCard:
    """Byte-for-byte the same field mapping services/telegram_notifier.py's own `_to_card()`
    already uses - duplicated intentionally rather than imported, per this codebase's own
    established convention for small, single-purpose mappings (mirrors e.g.
    `worker/content_cycle.py::_extract_scoring_result()`'s own documented rationale for the same
    choice) - keeps `services/telegram_notifier.py` completely untouched.

    Phase 19 M5: `quote_text`/`quote_speaker` mirror `services.telegram_notifier._to_card()`'s
    own Phase 18.10 addition - both default to None, so every pre-M5 caller is unaffected. This
    closes the confirmed gap where the image-preview delivery path never rendered a quote at all,
    even when one existed."""
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
    quote_text: str | None = None, quote_speaker: str | None = None,
) -> CombinedCardOutcome:
    """The sole delivery function whenever the image-preview flow is active - always sends exactly
    one message (text-only if there is no eligible candidate at all, a photo otherwise), never two.

    `dry_run` mirrors `services.telegram_notifier.send_editorial_card()`'s own established
    contract exactly (Phase 15 M5.8 fact-safety suppression / the global `content_generation_
    dry_run` flag both flow through this same parameter) - renders and logs, never calls the
    Telegram API, when `True`. `quote_text`/`quote_speaker` (Phase 19 M5) both default to None -
    every pre-M5 caller is unaffected; the caller (worker/content_cycle.py) is responsible for
    the quote_telegram_rendering_mode gate."""
    card = _to_card(draft, event, quote_text=quote_text, quote_speaker=quote_speaker)
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


def _hosted_platform_link_line(hint: NativeVideoHint) -> str:
    """YouTube/Vimeo candidates are never downloaded/re-uploaded (per Phase 19 M10's own scope) -
    delivered as a plain link line appended to the caption instead."""
    label = "Video" if hint.platform == VideoPlatform.YOUTUBE else "Video (Vimeo)"
    return f"\n\n{label}: {hint.remote_url}"


@dataclass(frozen=True)
class RichMediaPlan:
    """What send_news_with_rich_media() would send - always computed, even in "shadow"/dry-run,
    so the same plan can be logged (shadow) or actually sent (enforce) from one code path."""

    media_group_items: list[MediaUnion]
    hosted_platform_link: str | None  # appended to the caption when a YouTube/Vimeo hint exists
    fallback_single_photo: EditorialImageCandidate | None  # used when < 2 total media items


def build_rich_media_plan(
    image_candidates: list[EditorialImageCandidate], video_hint: NativeVideoHint | None, *, caption: str,
) -> RichMediaPlan:
    """Pure (aside from resolve_photo_input()'s local storage read - never a network call).
    Images first, direct-hosted video last (Phase 19 M12's own explicit ordering requirement).
    Bounded to Telegram's own 10-item media-group cap - one slot reserved for the video, if any.

    `InputMediaPhoto`/`InputMediaVideo` are frozen (Pydantic) - the caption (Telegram's real
    behavior: only the first item's caption is shown as the group's caption) must be passed at
    construction time, never assigned afterward, so photo/video URLs are resolved first and the
    actual `InputMedia*` objects are built last, in final order."""
    max_photos = _MEDIA_GROUP_MAX_ITEMS - (1 if video_hint is not None and video_hint.platform == VideoPlatform.DIRECT_HOSTED else 0)
    photo_inputs = []
    for candidate in image_candidates[:max_photos]:
        photo_input = resolve_photo_input(candidate)
        if photo_input is not None:
            photo_inputs.append(photo_input)

    direct_video_url: str | None = None
    hosted_platform_link: str | None = None
    if video_hint is not None:
        if video_hint.platform == VideoPlatform.DIRECT_HOSTED:
            direct_video_url = video_hint.remote_url
        elif video_hint.platform in (VideoPlatform.YOUTUBE, VideoPlatform.VIMEO):
            hosted_platform_link = _hosted_platform_link_line(video_hint)

    media_group_items: list[MediaUnion] = []
    is_first = True
    for photo_input in photo_inputs:
        media_group_items.append(InputMediaPhoto(media=photo_input, caption=caption if is_first else None))
        is_first = False
    if direct_video_url is not None:
        media_group_items.append(InputMediaVideo(media=direct_video_url, caption=caption if is_first else None))

    fallback_single_photo = image_candidates[0] if len(media_group_items) < _MEDIA_GROUP_MIN_ITEMS and image_candidates else None

    return RichMediaPlan(
        media_group_items=media_group_items, hosted_platform_link=hosted_platform_link,
        fallback_single_photo=fallback_single_photo,
    )


async def send_news_with_rich_media(
    bot: Bot, chat_id: int | None, session: AsyncSession, *,
    draft: ContentDraftRead, event: NewsEvent, dry_run: bool,
    image_candidates: list[EditorialImageCandidate], video_hint: NativeVideoHint | None = None,
    reply_to_message_id: int | None = None, quote_text: str | None = None, quote_speaker: str | None = None,
) -> CombinedCardOutcome:
    """Phase 19 M12: multi-photo/mixed-media delivery, built on the same architecture as
    send_news_with_image_preview() above (never a parallel notifier) - reuses bot/formatting.py's
    rendering and M5's quote-budget-aware caption limit exactly.

    Falls back to the existing single-photo path when fewer than 2 total media items are
    available (Telegram's send_media_group() requires 2-10 items) - the caller is responsible for
    only invoking this function when rich_media_mode != "off"; this function itself never checks
    the setting.

    KNOWN UX LIMITATION (documented, not solved, per the milestone's own explicit allowance):
    Telegram's Bot API does not support an inline keyboard on a media group at all
    (`reply_markup` is not a valid send_media_group() parameter) - unlike the single-photo path,
    a rich-media send carries no interactive keyboard. The source link is included in the caption
    text instead (never a second follow-up message - that would reintroduce the exact two-message
    UX defect the Phase 16 M6 fix eliminated)."""
    card = _to_card(draft, event, quote_text=quote_text, quote_speaker=quote_speaker)
    try:
        caption = render_editorial_card(card, limit=CAPTION_SAFE_LIMIT, include_url=False)
    except CardTooLongError:
        logger.error("rich_media_notification_render_failed", extra={"draft_id": str(draft.id)})
        return CombinedCardOutcome(chat_id=chat_id, sent=False, has_image=False, candidate_count=len(image_candidates))

    if video_hint is not None and video_hint.platform in (VideoPlatform.YOUTUBE, VideoPlatform.VIMEO):
        caption = caption + _hosted_platform_link_line(video_hint)

    plan = build_rich_media_plan(image_candidates, video_hint, caption=caption)

    if plan.fallback_single_photo is not None or not plan.media_group_items:
        return await send_news_with_image_preview(
            bot, chat_id, session, draft=draft, event=event, dry_run=dry_run,
            reply_to_message_id=reply_to_message_id, quote_text=quote_text, quote_speaker=quote_speaker,
        )

    if dry_run:
        logger.info(
            "rich_media_notification_dry_run",
            extra={
                "draft_id": str(draft.id), "chat_id": chat_id, "item_count": len(plan.media_group_items),
                "has_hosted_platform_link": plan.hosted_platform_link is not None,
            },
        )
        return CombinedCardOutcome(
            chat_id=chat_id, sent=False, has_image=True, candidate_count=len(image_candidates),
        )

    assert chat_id is not None, (
        "send_news_with_rich_media() called with no chat_id - settings.editorial_chat_id must be "
        "configured before rich_media_mode may be set to \"enforce\""
    )
    try:
        messages = await bot.send_media_group(
            chat_id, media=plan.media_group_items, reply_to_message_id=reply_to_message_id,
        )
    except TelegramAPIError:
        logger.exception("rich_media_notification_failed", extra={"draft_id": str(draft.id)})
        return CombinedCardOutcome(
            chat_id=chat_id, sent=False, has_image=True, candidate_count=len(image_candidates),
        )

    return CombinedCardOutcome(
        chat_id=chat_id, sent=True, has_image=True, candidate_count=len(image_candidates),
        message_id=messages[0].message_id if messages else None,
    )
