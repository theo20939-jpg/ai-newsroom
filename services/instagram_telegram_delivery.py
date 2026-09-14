"""INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-1 §4/§17/§18/§19: the one orchestration entrypoint that
sends an already-built, already-QA'd Instagram package into the Telegram "instagram" editorial
topic. Reuses `services/telegram_routing.py`'s existing send functions unmodified - this module
adds exactly one thing on top: a STRICT, Instagram-specific fail-closed guard that
`resolve_route()`'s own generic (and correct, for every OTHER destination) "unconfigured topic ->
send to chat root" behavior does not apply here, because §4's hard invariant
(`INSTAGRAM_PACKAGE_WRONG_TOPIC=false`) forbids that fallback specifically for Instagram content.

No Instagram Graph API call exists anywhere in this module or anything it calls (§18) - generation
and delivery never touch `services/instagram_publish_adapter.py`, `services/instagram_account_
reader.py`, or any HTTP client pointed at `graph.instagram.com`. `settings.instagram_topic_id`
being `None` (today's real production state) makes every function here a safe no-op, never a crash
and never a send to the wrong place (§19 MEDIA_HOSTING_FALSE_BLOCKS_TELEGRAM_EDITORIAL=false is a
DIFFERENT gate - deliberately not checked here at all, since this module never reads
`instagram_media_hosting.py` or `instagram_account_reader.py`, so their state cannot block it)."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import BufferedInputFile, InputMediaPhoto

from core.config import settings
from database.models.instagram_editorial_delivery import InstagramEditorialDelivery, InstagramEditorialDeliveryState
from schemas.editorial_route import EditorialDestination
from services.instagram_editorial_delivery_state import InstagramEditorialDeliveryService
from services.instagram_editorial_gate import InstagramGateDecision
from services.instagram_telegram_package_presenter import InstagramTelegramPresentation
from bot.keyboards.instagram_editorial_review import build_review_keyboard
from services.telegram_routing import (
    send_media_group_to_editorial_destination,
    send_photo_to_editorial_destination,
    send_to_editorial_destination,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InstagramTelegramDeliveryOutcome:
    sent: bool
    reason: str | None = None
    delivery_id: str | None = None
    version: int | None = None


def instagram_topic_configured() -> bool:
    """The one place `INSTAGRAM_TOPIC_FOUND`/`INSTAGRAM_TOPIC_THREAD_ID_CONFIGURED` is actually
    determined - a plain settings read, no I/O."""
    return settings.newsroom_telegram_chat_id is not None and settings.instagram_topic_id is not None


async def deliver_instagram_package(
    bot: Bot, session, *, presentation: InstagramTelegramPresentation, gate_decision: InstagramGateDecision,
    package_identity: str, source_story_id: str | None, content_format: str, package_snapshot: dict,
    source_url: str | None = None, hold_or_block_reason: str | None = None,
) -> InstagramTelegramDeliveryOutcome:
    """§21 duplicate prevention + §4 strict-topic fail-closed, in that order:

    1. Never sends anything unless `instagram_topic_configured()` is `True` - a missing topic id
       is reported as `reason="topic_not_configured"`, never a send to the chat root (§4's hard
       invariant) and never a crash.
    2. A HOLD/BLOCK gate decision is recorded but not delivered as if ready (§17) - a concise
       notice is sent instead, with no editor action keyboard.
    3. A READY package only ever creates ONE delivery row per `package_identity` version - a
       worker cycle re-considering an already-delivered identity is a safe no-op
       (`reason="duplicate_skipped"`), never a re-send.
    """
    service = InstagramEditorialDeliveryService()

    if gate_decision is not InstagramGateDecision.READY_FOR_EDITOR:
        delivery, created = await service.get_or_create_first_version(
            session, package_identity=package_identity, source_story_id=source_story_id,
            content_format=content_format, package_snapshot=package_snapshot,
        )
        if not created:
            return InstagramTelegramDeliveryOutcome(sent=False, reason="duplicate_skipped", delivery_id=str(delivery.id), version=delivery.version)
        state = InstagramEditorialDeliveryState.HOLD if gate_decision is InstagramGateDecision.HOLD else InstagramEditorialDeliveryState.BLOCK
        await service.mark_hold_or_block(session, delivery, state=state)
        if not instagram_topic_configured():
            return InstagramTelegramDeliveryOutcome(sent=False, reason="topic_not_configured", delivery_id=str(delivery.id), version=delivery.version)
        label = "HOLD" if state is InstagramEditorialDeliveryState.HOLD else "BLOCK"
        text = (
            f"⚠️ <b>INSTAGRAM · {label}</b>\n\n"
            f"Формат: {content_format}\n"
            f"Причина: {hold_or_block_reason or 'не прошла проверка контроля качества'}"
        )
        await send_to_editorial_destination(bot, EditorialDestination.INSTAGRAM, text, dry_run=False)
        return InstagramTelegramDeliveryOutcome(sent=False, reason=f"delivered_as_{label.lower()}_notice", delivery_id=str(delivery.id), version=delivery.version)

    delivery, created = await service.get_or_create_first_version(
        session, package_identity=package_identity, source_story_id=source_story_id,
        content_format=content_format, package_snapshot=package_snapshot,
    )
    if not created:
        return InstagramTelegramDeliveryOutcome(sent=False, reason="duplicate_skipped", delivery_id=str(delivery.id), version=delivery.version)

    return await _send_and_mark_delivered(bot, session, delivery=delivery, presentation=presentation, source_url=source_url)


async def deliver_new_version(
    bot: Bot, session, *, delivery: InstagramEditorialDelivery, presentation: InstagramTelegramPresentation,
    source_url: str | None = None,
) -> InstagramTelegramDeliveryOutcome:
    """The regeneration-result delivery path - `delivery` is already the NEW version row (created
    by `InstagramEditorialDeliveryService.create_new_version()`), so no duplicate-prevention lookup
    is needed here (the caller already made that decision by creating this exact row)."""
    return await _send_and_mark_delivered(bot, session, delivery=delivery, presentation=presentation, source_url=source_url)


async def deliver_text_only_new_version(
    bot: Bot, session, *, delivery: InstagramEditorialDelivery, previous: InstagramEditorialDelivery,
    control_text: str, overflow_text: str | None, source_url: str | None = None,
) -> InstagramTelegramDeliveryOutcome:
    """§10 "📝 Текст": no new media is ever sent - the previous version's already-delivered
    Telegram photo/media-group message(s) are reused as-is (carried forward from `previous`), and
    only a fresh control/caption message (with a fresh keyboard for the NEW version) is sent,
    replying to that same media. This is the concrete mechanism behind "keep approved media
    unchanged" - there is no code path here that could re-send or substitute the image even if it
    wanted to, since no render bytes are passed to this function at all."""
    if not instagram_topic_configured():
        return InstagramTelegramDeliveryOutcome(sent=False, reason="topic_not_configured", delivery_id=str(delivery.id), version=delivery.version)

    reply_target = previous.media_message_ids[0] if previous.media_message_ids else previous.control_message_id
    keyboard = build_review_keyboard(delivery.id, delivery.version, source_url=source_url)
    control_outcome = await send_to_editorial_destination(
        bot, EditorialDestination.INSTAGRAM, control_text, dry_run=False,
        reply_markup=keyboard, reply_to_message_id=reply_target,
    )
    if not control_outcome.sent:
        logger.warning("instagram_telegram_delivery_text_only_control_failed", extra={"delivery_id": str(delivery.id), "reason": control_outcome.reason})
        return InstagramTelegramDeliveryOutcome(sent=False, reason=control_outcome.reason, delivery_id=str(delivery.id), version=delivery.version)

    if overflow_text:
        await send_to_editorial_destination(
            bot, EditorialDestination.INSTAGRAM, overflow_text, dry_run=False, reply_to_message_id=control_outcome.message_id,
        )

    await InstagramEditorialDeliveryService().mark_delivered(
        session, delivery, chat_id=control_outcome.chat_id or settings.newsroom_telegram_chat_id,
        topic_id=settings.instagram_topic_id, media_message_ids=previous.media_message_ids or [],
        control_message_id=control_outcome.message_id,
    )
    return InstagramTelegramDeliveryOutcome(sent=True, delivery_id=str(delivery.id), version=delivery.version)


async def _send_and_mark_delivered(
    bot: Bot, session, *, delivery: InstagramEditorialDelivery, presentation: InstagramTelegramPresentation,
    source_url: str | None,
) -> InstagramTelegramDeliveryOutcome:
    if not instagram_topic_configured():
        # §4 hard invariant: never fall back to the chat root for Instagram content. The delivery
        # row stays PENDING - a later retry (once the topic id is configured) can still complete
        # it; nothing here treats "not configured" as a permanent failure.
        return InstagramTelegramDeliveryOutcome(sent=False, reason="topic_not_configured", delivery_id=str(delivery.id), version=delivery.version)

    media_message_ids: list[int] = []
    if presentation.kind == "carousel":
        media_items = [
            InputMediaPhoto(media=BufferedInputFile(item, filename=f"slide_{i}.jpg"))
            for i, item in enumerate(presentation.media)
        ]
        outcome = await send_media_group_to_editorial_destination(bot, EditorialDestination.INSTAGRAM, media_items, dry_run=False)
        if not outcome.sent:
            logger.warning("instagram_telegram_delivery_media_group_failed", extra={"delivery_id": str(delivery.id), "reason": outcome.reason})
            return InstagramTelegramDeliveryOutcome(sent=False, reason=outcome.reason, delivery_id=str(delivery.id), version=delivery.version)
        if outcome.message_id is not None:
            media_message_ids = [outcome.message_id]  # first-of-group id only - aiogram/Telegram do not return every id via this call shape
        reply_target = outcome.message_id
    else:
        photo_bytes = presentation.media[0]
        outcome = await send_photo_to_editorial_destination(
            bot, EditorialDestination.INSTAGRAM, BufferedInputFile(photo_bytes, filename="media.jpg"), "", dry_run=False,
        )
        if not outcome.sent:
            logger.warning("instagram_telegram_delivery_photo_failed", extra={"delivery_id": str(delivery.id), "reason": outcome.reason})
            return InstagramTelegramDeliveryOutcome(sent=False, reason=outcome.reason, delivery_id=str(delivery.id), version=delivery.version)
        media_message_ids = [outcome.message_id] if outcome.message_id is not None else []
        reply_target = outcome.message_id

    keyboard = build_review_keyboard(delivery.id, delivery.version, source_url=source_url)
    control_outcome = await send_to_editorial_destination(
        bot, EditorialDestination.INSTAGRAM, presentation.control_text, dry_run=False,
        reply_markup=keyboard, reply_to_message_id=reply_target,
    )
    if not control_outcome.sent:
        logger.warning("instagram_telegram_delivery_control_message_failed", extra={"delivery_id": str(delivery.id), "reason": control_outcome.reason})
        # The media itself already sent - never re-send it merely because the control message
        # failed. The delivery row is still marked delivered with whatever media ids we have; a
        # missing control message is a real, disclosed defect for a human to notice, not silently
        # swallowed, but it must not trigger a duplicate media resend on the next cycle.

    if presentation.overflow_text:
        await send_to_editorial_destination(
            bot, EditorialDestination.INSTAGRAM, presentation.overflow_text, dry_run=False,
            reply_to_message_id=control_outcome.message_id or reply_target,
        )

    await InstagramEditorialDeliveryService().mark_delivered(
        session, delivery, chat_id=control_outcome.chat_id or settings.newsroom_telegram_chat_id,
        topic_id=settings.instagram_topic_id, media_message_ids=media_message_ids,
        control_message_id=control_outcome.message_id,
    )
    return InstagramTelegramDeliveryOutcome(sent=True, delivery_id=str(delivery.id), version=delivery.version)
