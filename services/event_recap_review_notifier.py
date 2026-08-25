"""NINJA PULSE RECAP Phase R2 integration, Phase D.0: Telegram send/edit for the EVENT_RECAP
review UI (part C of services/event_recap_review_service.py's own module docstring). Reuses
services/telegram_routing.py::send_to_editorial_destination() verbatim - the single existing
Telegram send boundary this codebase already established, never a new HTTP/Bot API call site.
Mirrors services/telegraph_article_review_notifier.py's own shape/discipline exactly.

Destination defaults to `EditorialDestination.TELEGRAPH` - the same internal editorial Telegram
topic TELEGRAPH article review already uses. No dedicated EVENT_RECAP destination exists yet
(schemas/editorial_route.py's own five-topic enum is deliberately kept small, no speculative
additions per that module's own docstring); the caller may pass a different `EditorialDestination`
explicitly if one is added later - this module makes no destination decision of its own beyond the
default. `schemas/editorial_route.py` and the routing mechanism itself are untouched by Phase D.0.

`dry_run=True` by default, mirroring every other send wrapper in this codebase. No scheduler/
worker/bot-command calls this module yet - reachable only from bot/handlers/event_recap_review.py's
own message-edit path and from whatever future, separately-authorized caller eventually triggers a
real recap-review send (mirrors services/telegraph_article_review_notifier.py's own identical
dormancy disclosure).

This module makes no publish decision of any kind: `EventRecapCandidate.publishable` is never
read or set here - it is not even imported (this module never imports `EventRecapCandidate` at
all, unlike Phase C.1's own version of this file). Sending or editing this preview message has no
bearing on and never mutates that field.

Phase H.2 (two-message media contract): `send_event_recap_review()` is no longer DB-free (Phase
D.0's own original discipline) - it now takes a read-only `AsyncSession` to (1) re-resolve the
Phase H.1-persisted `selected_media` pointer into an actual sendable photo via the EXISTING
`get_editorial_image_candidates()`/`bot.image_preview_media.resolve_photo_input()` read contracts
(never a new resolver, never a media reselection - see `_resolve_selected_media_photo_input()`'s
own docstring), and (2) call the EXISTING `services.event_recap_review_service.
record_telegram_delivery()` once the canonical text message actually sends - closing the
previously-disclosed gap where `EventRecapReview.telegram_*` stayed NULL forever (no prior caller
ever called that function). Deliberately TWO Telegram messages, never one:

    MESSAGE 1 (optional): the representative photo alone - no caption text, no keyboard. Sent via
    `services.telegram_routing.send_photo_to_editorial_destination()` (Phase 23.1H, already
    real/tested, unmodified). Never attempted if H.1's plan has no eligible representative, or if
    re-resolution fails for any reason (fail-soft - see `_resolve_selected_media_photo_input()`).

    MESSAGE 2 (always, if MESSAGE 1's failure/absence didn't already fail-soft first): the FULL,
    untruncated recap text (`render_event_recap_review_text()`, unchanged, still targeting
    Telegram's 4096-char text-message limit, never the much smaller 1024-char photo-caption limit)
    plus the approve/needs-revision keyboard. This is the ONLY message ever sent to (or edited
    inside) `update_event_recap_review_message()`, which is completely UNTOUCHED by this phase -
    it was already text-only, so its `edit_message_text()` contract needs no branch at all. When
    MESSAGE 1 was sent successfully, MESSAGE 2 is sent as a reply to it (`reply_to_message_id`,
    already supported by `send_to_editorial_destination()` since Phase 23.1Q) - a real, working
    "media above, full review + buttons below" thread, not a new orchestration mechanism.

A media send failure/absence NEVER blocks or shortens MESSAGE 2 - the canonical review's success
is judged by MESSAGE 2's own `RoutingOutcome.sent` alone, exactly matching `EventRecapReviewSendOutcome
.text_outcome`'s own field name. Delivery metadata (`record_telegram_delivery()`) is written using
MESSAGE 2's chat/message/topic ids ONLY, and only when MESSAGE 2 itself actually sent - never
MESSAGE 1's ids, and never on a dry run or a live text-send failure.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile
from sqlalchemy.ext.asyncio import AsyncSession

from bot.event_recap_review_formatting import render_event_recap_review_text
from bot.image_preview_media import resolve_photo_input
from bot.keyboards.event_recap_review import build_event_recap_review_keyboard
from database.models.event_recap_review import EventRecapReview
from schemas.editorial_route import EditorialDestination
from services.event_recap_review_service import record_telegram_delivery
from services.image_persistence import get_editorial_image_candidates
from services.telegram_routing import RoutingOutcome, send_photo_to_editorial_destination, send_to_editorial_destination

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventRecapReviewSendOutcome:
    """The two-message H.2 send result. `text_outcome` is the canonical review message - the ONLY
    one that determines overall delivery success and the ONLY one ever persisted via
    `record_telegram_delivery()`. `media_outcome` is `None` whenever no representative media was
    attempted at all (tier="none", no representative, or re-resolution failed before any send
    attempt) - distinct from a `RoutingOutcome(sent=False, ...)`, which means a send WAS attempted
    and did not succeed (dry run or a live Telegram failure)."""

    text_outcome: RoutingOutcome
    media_outcome: RoutingOutcome | None


async def _resolve_selected_media_photo_input(
    session: AsyncSession, selected_media: dict | None,
) -> str | BufferedInputFile | None:
    """Phase H.2: read-only re-resolution of the H.1-persisted representative-media pointer
    (`services.event_recap.serialize_selected_media_plan()`'s own JSON shape) into whatever
    `bot.image_preview_media.resolve_photo_input()` already knows how to send - a cached Telegram
    `file_id` string, or freshly-read local bytes. Never a media reselection: H.1's ranking is not
    recomputed, no new Story query happens, only the ONE already-selected event's already-persisted
    candidate list is re-read via the EXISTING, unmodified `get_editorial_image_candidates()` -
    the same read contract `bot/image_preview_media.py`'s own established callers already use.

    Fail-soft, never raises: returns `None` for every failure mode named in Phase H.2's own brief
    (no tier/representative, candidate no longer found/eligible, unresolvable storage/file_id, or
    any unexpected exception during the lookup itself) - the caller always falls back to sending
    the text-only review."""
    if selected_media is None or selected_media.get("tier") != "story_pool":
        return None
    representative = selected_media.get("representative")
    if not representative:
        return None
    try:
        event_id = UUID(representative["originating_event_id"])
        candidate_id = representative["candidate_id"]
        candidates = await get_editorial_image_candidates(session, news_event_id=event_id, limit=10)
        candidate = next((c for c in candidates if c.candidate_id == candidate_id), None)
        if candidate is None:
            logger.warning(
                "event_recap_review_media_candidate_not_found",
                extra={"event_id": str(event_id), "candidate_id": candidate_id},
            )
            return None
        photo_input = resolve_photo_input(candidate)
        # BufferedInputFile is intentionally not attempted here - Phase H.2 scope only ever
        # resends an ALREADY-STORED-or-file_id-cached candidate (mirrors this module's own "never
        # a new fetch" discipline); a fresh local-bytes read is exactly what resolve_photo_input()
        # already does when telegram_file_id is absent, so this is not a limitation introduced
        # here - str | BufferedInputFile is send_photo_to_editorial_destination()'s own accepted
        # input type either way.
        return photo_input
    except Exception:  # noqa: BLE001 - fail-soft to a text-only review, never a review-blocking crash
        logger.warning("event_recap_review_media_resolution_failed", exc_info=True)
        return None


async def send_event_recap_review(
    bot: Bot, session: AsyncSession, review: EventRecapReview, recap_result: dict, *,
    selected_media: dict | None = None,
    dry_run: bool = True, destination: EditorialDestination = EditorialDestination.TELEGRAPH,
) -> EventRecapReviewSendOutcome:
    """Sends the EVENT_RECAP review as one or two messages to `destination` (module docstring's
    own MESSAGE 1/MESSAGE 2 contract). Makes no decision about publication - `dry_run=True` (the
    safe default) never actually calls the Telegram API for either message. `selected_media` is
    the H.1-persisted `select_recap_media` step result's own `result` dict (`{"tier": ...,
    "representative": ...}`) - the caller reads it from `EditorialTask.workflow["step_results"]`
    exactly as it already reads `recap_result` from the `synthesize_recap` entry; `None` (the
    default) behaves exactly like `tier="none"` - a plain text-only review, byte-identical to
    every pre-H.2 caller."""
    photo_input = await _resolve_selected_media_photo_input(session, selected_media)

    media_outcome: RoutingOutcome | None = None
    reply_to_message_id: int | None = None
    if photo_input is not None:
        media_outcome = await send_photo_to_editorial_destination(
            bot, destination, photo_input, "", dry_run=dry_run,
        )
        if media_outcome.sent and media_outcome.message_id is not None:
            reply_to_message_id = media_outcome.message_id

    text = render_event_recap_review_text(review, recap_result)
    keyboard = build_event_recap_review_keyboard(review)
    text_outcome = await send_to_editorial_destination(
        bot, destination, text, dry_run=dry_run, reply_markup=keyboard,
        reply_to_message_id=reply_to_message_id,
    )

    if text_outcome.sent and text_outcome.message_id is not None and text_outcome.chat_id is not None:
        await record_telegram_delivery(
            session, review.id, chat_id=text_outcome.chat_id, message_id=text_outcome.message_id,
            thread_id=text_outcome.topic_id,
        )

    return EventRecapReviewSendOutcome(text_outcome=text_outcome, media_outcome=media_outcome)


async def update_event_recap_review_message(
    bot: Bot, *, chat_id: int, message_id: int, review: EventRecapReview, recap_result: dict,
) -> bool:
    """Edits the ALREADY-SENT canonical review message (MESSAGE 2, always a text message - module
    docstring) in place after a decision - never sends a new message, never touches MESSAGE 1 (the
    representative photo, if any - Phase H.2 deliberately never edits or resends it). Returns
    `True` on success, `False` on a live `TelegramAPIError` (never raises - the decision itself is
    already durably recorded regardless of whether the re-render succeeds). Mirrors
    services/telegraph_article_review_notifier.py::update_article_review_message()'s own identical
    contract exactly - completely unchanged by Phase H.2, since MESSAGE 2 was already text-only."""
    text = render_event_recap_review_text(review, recap_result)
    keyboard = build_event_recap_review_keyboard(review)
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=keyboard)
    except TelegramAPIError:
        return False
    return True
