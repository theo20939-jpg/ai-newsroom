"""Phase 22 - Telegram Editorial Routing Foundation.

A safe routing layer connecting an `EditorialDestination` (schemas/editorial_route.py) to a
concrete Telegram send target (chat id + optional forum-topic `message_thread_id`) inside the
single NINJA NEWSROOM supergroup, and a thin send wrapper mirroring services/telegram_notifier.py
::send_editorial_card()'s own established dry-run/error-handling shape.

Deliberately NOT wired into any live/automated path this phase (worker/content_cycle.py,
capabilities/executor.py) - this is a standalone capability, exercised only by tests, exactly
matching this codebase's own established "build the capability, wire it in as a separate,
explicitly-authorized later step" precedent (e.g. services/story_delta_engine.py in Phase 20).
`EditorialDestination` is supplied explicitly by the caller, never derived from `ContentDraft` or
any other signal - no automatic decision-making of any kind lives here (docs/
phase22_telegram_editorial_routing_report.md §3).

Routing configuration is entirely settings-driven (core/config.py's `newsroom_telegram_chat_id`/
`*_topic_id` fields) - `_DESTINATION_TOPIC_SETTING` below maps each `EditorialDestination` to the
*name* of its settings attribute, not a topic id value itself, so no topic id is ever hardcoded in
this module or in any caller.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, LinkPreviewOptions, MediaUnion

from core.config import settings
from schemas.editorial_route import EditorialDestination, parse_editorial_destination

logger = logging.getLogger(__name__)

# NEWS Output Stability Fix (Case G, docs/news_output_stability_forensic_report.md §8): Telegram's
# own default behavior is to scan a text message for the first URL and expand it into a large
# preview card - confirmed, real, live observation: the NINJA PULSE footer's own
# <a href="https://t.me/nnjvpn"> link is the only link in the message body for the majority of
# text-only NEWS sends (the source URL itself is never embedded in the text, only as the separate
# inline button), so Telegram expanded THAT link into the NINJA VPN channel's own preview card on
# every text-only post. Applied only to send_to_editorial_destination()'s one bot.send_message()
# call - confirmed by direct code/API inspection that bot.send_photo()/bot.send_media_group() are
# never affected by this at all: Telegram's platform itself never generates link previews for
# photo/media-group captions, regardless of any parameter (aiogram's own InputMediaPhoto/
# InputMediaVideo types expose no link-preview field at all, consistent with this). The NINJA
# PULSE link itself remains fully clickable - only the large expanded preview card is suppressed.
_DISABLED_LINK_PREVIEW = LinkPreviewOptions(is_disabled=True)

# Maps each destination to the *name* of its `core.config.Settings` topic-id attribute - adding a
# new destination later means adding one enum member (schemas/editorial_route.py) plus one entry
# here plus one new settings field, never an `if destination == ...` chain in a handler.
_DESTINATION_TOPIC_SETTING: dict[EditorialDestination, str] = {
    EditorialDestination.NEWS: "news_topic_id",
    EditorialDestination.MEME: "meme_topic_id",
    EditorialDestination.TELEGRAPH: "telegraph_topic_id",
    EditorialDestination.INSTAGRAM: "instagram_topic_id",
    EditorialDestination.REELS: "reels_topic_id",
}


@dataclass(frozen=True)
class RouteTarget:
    """A resolved Telegram send target. `topic_id` is `None` for a destination whose topic id is
    not (yet) configured - that is a valid, safe target (send to the chat's own root), not an
    error; see `resolve_route()`'s own docstring for the one case that *is* an error (no chat id
    configured at all)."""

    chat_id: int
    topic_id: int | None


def resolve_route(destination: EditorialDestination) -> RouteTarget | None:
    """Pure, deterministic, zero I/O. Returns `None` only when `settings.newsroom_telegram_
    chat_id` itself is not configured - with no chat id there is no safe target of any kind, for
    any destination. A destination whose own `*_topic_id` is unset still resolves successfully,
    to `RouteTarget(chat_id=..., topic_id=None)` - sending without a `message_thread_id` (i.e. to
    the chat's root) is a legitimate, deliberate outcome, not a misconfiguration (docs/
    phase22_telegram_editorial_routing_report.md §6's own "normal chat delivery" case)."""
    if settings.newsroom_telegram_chat_id is None:
        return None
    topic_id = getattr(settings, _DESTINATION_TOPIC_SETTING[destination])
    return RouteTarget(chat_id=settings.newsroom_telegram_chat_id, topic_id=topic_id)


@dataclass(frozen=True)
class RoutingOutcome:
    """Mirrors services/telegram_notifier.py::NotificationOutcome's own directly-inspectable-
    result shape. `reason` is `None` only when `sent` is `True`; every failure path (dry-run
    included) sets it to a specific, stable string so tests and logs can distinguish "chose not to
    send" (dry-run) from "could not resolve a target" (unknown/unconfigured destination) from "the
    live send itself failed" (`telegram_api_error`)."""

    destination: EditorialDestination | None
    chat_id: int | None
    topic_id: int | None
    sent: bool
    reason: str | None = None
    message_id: int | None = None


async def send_to_editorial_destination(
    bot: Bot,
    destination: EditorialDestination | str,
    text: str,
    *,
    dry_run: bool = True,
    parse_mode: ParseMode = ParseMode.HTML,
    reply_markup: InlineKeyboardMarkup | None = None,
    reply_to_message_id: int | None = None,
) -> RoutingOutcome:
    """The one send boundary this phase adds. Safe by construction for every failure mode named
    in the phase brief's own required test cases:

    - An unrecognized destination string (`parse_editorial_destination()` returns `None`, e.g. a
      typo or a not-yet-supported value) never reaches `bot.send_message()` - logged
      (`telegram_routing_unknown_destination`) and returned as `sent=False,
      reason="unknown_destination"`.
    - A recognized destination with no chat id configured at all (`resolve_route()` returns
      `None`) is the same safe-failure shape - logged (`telegram_routing_unconfigured_
      destination`) and returned as `sent=False, reason="unconfigured_destination"`.
    - `dry_run=True` (the default - mirrors `send_editorial_card`'s own safe default) never calls
      `bot.send_message()` regardless of whether the route resolved - `sent=False,
      reason="dry_run"`, with the resolved `chat_id`/`topic_id` still populated so a caller/test
      can inspect exactly what WOULD have been sent and to where.
    - A resolved route's `topic_id` is always passed through as `message_thread_id` (aiogram's own
      `Bot.send_message()` signature already defaults this parameter to `None` - passing `None`
      explicitly is functionally identical to omitting it entirely: no thread). A destination
      routed to a plain chat (or a forum whose specific topic id is not yet configured) is
      therefore sent with `message_thread_id=None` - never a real topic id - which is exactly the
      "send without thread ID" behavior the phase brief's own §6 requires; this phase's own
      regression tests assert the *value* is `None` for this case, and a real positive topic id
      for the forum-topic case, directly on the recorded call.
    - A live `TelegramAPIError` is caught, logged (`telegram_routing_send_failed`), and returned
      as `sent=False, reason="telegram_api_error"` - never raised past this function, mirroring
      `send_editorial_card`'s own established per-call error-handling discipline.

    `reply_markup` (Phase 23.1E, additive, default `None` - every existing caller/test that never
    passes it is completely unaffected): passed straight through to `bot.send_message()` - this
    function does not build, validate, or interpret the keyboard itself (`bot/keyboards/
    image_preview.py::build_source_only_keyboard()` is the caller's responsibility, docs/
    phase23_1e_telegram_news_compact_profile_report.md §10) - it is simply threaded to the one
    real Telegram API call this module makes, exactly like `chat_id`/`message_thread_id` already
    are.

    `reply_to_message_id` (Phase 23.1Q, additive, default `None` - every existing caller/test
    that never passes it is completely unaffected): the caller's own already-resolved reply
    target (worker/content_cycle.py's own services/story_telegram_delivery.py::
    determine_reply_target() decision, computed identically for every delivery mode - this
    module makes no reply-routing decision of its own, it only threads an already-decided int
    straight through to the one real Telegram API call, exactly like `reply_markup` already is).
    Still the installed aiogram version's own direct `reply_to_message_id` parameter (confirmed
    present on `Bot.send_message`/`Bot.send_photo` - not the newer `reply_parameters` object,
    which this codebase has no other use for yet).

    `link_preview_options` (NEWS Output Stability Fix, Case G, unconditional - never a caller-
    supplied parameter, since every real NEWS text send has the identical problem and no caller
    has ever wanted a large preview card on a NEWS post): always `_DISABLED_LINK_PREVIEW` on this
    function's own `bot.send_message()` call - see that constant's own module-level comment for
    the real evidence. `send_photo_to_editorial_destination()`/`send_media_group_to_editorial_
    destination()` below are deliberately NOT touched - Telegram never generates a link preview
    for a photo/media-group caption in the first place, so there is nothing to disable there.
    """
    resolved_destination = (
        destination if isinstance(destination, EditorialDestination) else parse_editorial_destination(destination)
    )
    if resolved_destination is None:
        logger.warning("telegram_routing_unknown_destination", extra={"destination": str(destination)})
        return RoutingOutcome(destination=None, chat_id=None, topic_id=None, sent=False, reason="unknown_destination")

    route = resolve_route(resolved_destination)
    if route is None:
        logger.warning(
            "telegram_routing_unconfigured_destination", extra={"destination": resolved_destination.value}
        )
        return RoutingOutcome(
            destination=resolved_destination, chat_id=None, topic_id=None, sent=False,
            reason="unconfigured_destination",
        )

    if dry_run:
        logger.info(
            "telegram_routing_dry_run",
            extra={
                "destination": resolved_destination.value, "chat_id": route.chat_id, "topic_id": route.topic_id,
                "reply_to_message_id": reply_to_message_id,
            },
        )
        return RoutingOutcome(
            destination=resolved_destination, chat_id=route.chat_id, topic_id=route.topic_id, sent=False,
            reason="dry_run",
        )

    try:
        message = await bot.send_message(
            route.chat_id, text, parse_mode=parse_mode, message_thread_id=route.topic_id,
            reply_markup=reply_markup, reply_to_message_id=reply_to_message_id,
            link_preview_options=_DISABLED_LINK_PREVIEW,
        )
    except TelegramAPIError:
        logger.exception(
            "telegram_routing_send_failed",
            extra={"destination": resolved_destination.value, "chat_id": route.chat_id, "topic_id": route.topic_id},
        )
        return RoutingOutcome(
            destination=resolved_destination, chat_id=route.chat_id, topic_id=route.topic_id, sent=False,
            reason="telegram_api_error",
        )

    return RoutingOutcome(
        destination=resolved_destination, chat_id=route.chat_id, topic_id=route.topic_id, sent=True,
        message_id=message.message_id,
    )


async def send_photo_to_editorial_destination(
    bot: Bot,
    destination: EditorialDestination | str,
    photo: str | BufferedInputFile,
    caption: str,
    *,
    dry_run: bool = True,
    parse_mode: ParseMode = ParseMode.HTML,
    reply_markup: InlineKeyboardMarkup | None = None,
    reply_to_message_id: int | None = None,
) -> RoutingOutcome:
    """Phase 23.1H media integration (docs/phase23_1h_text_image_canary_report.md) - the minimal
    sibling this phase adds to reuse the router's own resolved-target/dry-run/error-handling shape
    for a photo send, without touching `send_to_editorial_destination()` above at all (every
    existing caller/destination - MEME/TELEGRAPH/INSTAGRAM/REELS, every text-only NEWS send -
    stays byte-identical, since none of them call this new function).

    `photo` is whatever `bot/image_preview_media.py::resolve_photo_input()` already resolved (a
    cached Telegram `file_id` string, or a freshly-read `BufferedInputFile`) - this function does
    no image discovery/ranking/validation of its own, it only sends what the caller already
    decided is safe to attach (Phase 23.1G's `EditorialTreatmentDecision` gates whether a post is
    sent at all; the caller's own caption-length check, per docs/
    phase23_1h_text_image_canary_report.md §"caption limit safety", gates whether it is sent as a
    photo vs. falling back to `send_to_editorial_destination()`'s plain-text path instead).

    Mirrors `send_to_editorial_destination()`'s exact contract: `dry_run=True` (default) never
    calls the Telegram API; an unresolvable/unconfigured destination fails the same safe way;
    `route.topic_id` is always passed as `message_thread_id`; a live `TelegramAPIError` is caught
    and returned, never raised. `reply_to_message_id` (Phase 23.1Q, additive, default `None`):
    identical contract to `send_to_editorial_destination()`'s own new parameter above - see its
    docstring."""
    resolved_destination = (
        destination if isinstance(destination, EditorialDestination) else parse_editorial_destination(destination)
    )
    if resolved_destination is None:
        logger.warning("telegram_routing_unknown_destination", extra={"destination": str(destination)})
        return RoutingOutcome(destination=None, chat_id=None, topic_id=None, sent=False, reason="unknown_destination")

    route = resolve_route(resolved_destination)
    if route is None:
        logger.warning(
            "telegram_routing_unconfigured_destination", extra={"destination": resolved_destination.value}
        )
        return RoutingOutcome(
            destination=resolved_destination, chat_id=None, topic_id=None, sent=False,
            reason="unconfigured_destination",
        )

    if dry_run:
        logger.info(
            "telegram_routing_photo_dry_run",
            extra={
                "destination": resolved_destination.value, "chat_id": route.chat_id, "topic_id": route.topic_id,
                "reply_to_message_id": reply_to_message_id,
            },
        )
        return RoutingOutcome(
            destination=resolved_destination, chat_id=route.chat_id, topic_id=route.topic_id, sent=False,
            reason="dry_run",
        )

    try:
        message = await bot.send_photo(
            route.chat_id, photo=photo, caption=caption, parse_mode=parse_mode,
            message_thread_id=route.topic_id, reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
        )
    except TelegramAPIError:
        logger.exception(
            "telegram_routing_photo_send_failed",
            extra={"destination": resolved_destination.value, "chat_id": route.chat_id, "topic_id": route.topic_id},
        )
        return RoutingOutcome(
            destination=resolved_destination, chat_id=route.chat_id, topic_id=route.topic_id, sent=False,
            reason="telegram_api_error",
        )

    return RoutingOutcome(
        destination=resolved_destination, chat_id=route.chat_id, topic_id=route.topic_id, sent=True,
        message_id=message.message_id,
    )


async def send_media_group_to_editorial_destination(
    bot: Bot,
    destination: EditorialDestination | str,
    media: list[MediaUnion],
    *,
    dry_run: bool = True,
    reply_to_message_id: int | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> RoutingOutcome:
    """Phase 23.1Q media wiring (Media Roadmap Recovery §10 step 1): the router-mode analogue of
    `send_to_editorial_destination()`/`send_photo_to_editorial_destination()` above, for
    `bot.send_media_group()` - mirrors their exact contract (dry-run/unknown/unconfigured-
    destination safe-failure shapes, `TelegramAPIError` caught and returned, never raised,
    `route.topic_id` always passed as `message_thread_id`). `media` is whatever
    `services/image_preview_notifier.py::build_rich_media_plan()` (Phase 19 M12, reused verbatim,
    not reimplemented here) already built - this function does no media-group composition,
    caption budgeting, or per-item resolution of its own, exactly like `send_photo_to_editorial_
    destination()` does no image discovery/ranking of its own.

    `reply_markup` (Phase 23.1Q, media-quality corrective phase - replaces an earlier, rejected
    in-caption-link approach): `bot.send_media_group()` itself has no `reply_markup` parameter at
    all - a real Telegram Bot API limitation, confirmed directly against the installed aiogram
    version, not a design choice. Once the group is sent, the keyboard is attached to the FIRST
    message via `bot.edit_message_reply_markup()` - a real, native aiogram/Telegram method for
    exactly this situation, not a new mechanism. This keeps the send at exactly one user-visible
    message (never a second, follow-up message - Phase 16 M6's own fix already established why
    that regresses the UX) and produces the same real `[🔗 Источник]` inline button every other
    NEWS delivery path already uses, instead of a visible caption text link. A failure to attach
    the keyboard is logged (`telegram_routing_media_group_keyboard_edit_failed`) and never retried
    or treated as a delivery failure - the post itself already sent successfully; the caller must
    never re-send/duplicate the post merely because the keyboard-edit step failed.

    `message_id` on the returned `RoutingOutcome` is the FIRST message of the group (mirrors
    `send_news_with_rich_media()`'s own `messages[0].message_id` convention) - the single id
    `services/story_telegram_delivery.py::record_delivery()` expects to persist as this draft's
    root/reply delivery record."""
    resolved_destination = (
        destination if isinstance(destination, EditorialDestination) else parse_editorial_destination(destination)
    )
    if resolved_destination is None:
        logger.warning("telegram_routing_unknown_destination", extra={"destination": str(destination)})
        return RoutingOutcome(destination=None, chat_id=None, topic_id=None, sent=False, reason="unknown_destination")

    route = resolve_route(resolved_destination)
    if route is None:
        logger.warning(
            "telegram_routing_unconfigured_destination", extra={"destination": resolved_destination.value}
        )
        return RoutingOutcome(
            destination=resolved_destination, chat_id=None, topic_id=None, sent=False,
            reason="unconfigured_destination",
        )

    if dry_run:
        logger.info(
            "telegram_routing_media_group_dry_run",
            extra={
                "destination": resolved_destination.value, "chat_id": route.chat_id, "topic_id": route.topic_id,
                "item_count": len(media), "reply_to_message_id": reply_to_message_id,
                "has_button": reply_markup is not None,
            },
        )
        return RoutingOutcome(
            destination=resolved_destination, chat_id=route.chat_id, topic_id=route.topic_id, sent=False,
            reason="dry_run",
        )

    try:
        messages = await bot.send_media_group(
            route.chat_id, media=media, message_thread_id=route.topic_id,
            reply_to_message_id=reply_to_message_id,
        )
    except TelegramAPIError:
        logger.exception(
            "telegram_routing_media_group_send_failed",
            extra={"destination": resolved_destination.value, "chat_id": route.chat_id, "topic_id": route.topic_id},
        )
        return RoutingOutcome(
            destination=resolved_destination, chat_id=route.chat_id, topic_id=route.topic_id, sent=False,
            reason="telegram_api_error",
        )

    first_message_id = messages[0].message_id if messages else None
    if reply_markup is not None and first_message_id is not None:
        try:
            await bot.edit_message_reply_markup(
                chat_id=route.chat_id, message_id=first_message_id, reply_markup=reply_markup,
            )
        except TelegramAPIError:
            # The post itself already sent successfully - never re-send/duplicate it merely
            # because attaching the button afterward failed. Logged, not raised, not retried.
            logger.exception(
                "telegram_routing_media_group_keyboard_edit_failed",
                extra={
                    "destination": resolved_destination.value, "chat_id": route.chat_id,
                    "message_id": first_message_id,
                },
            )

    return RoutingOutcome(
        destination=resolved_destination, chat_id=route.chat_id, topic_id=route.topic_id, sent=True,
        message_id=first_message_id,
    )
