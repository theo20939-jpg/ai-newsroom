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

This module stays DB-free (mirrors its Telegraph sibling's own established convention): it takes
an already-built `EventRecapReview` row and the recap's own persisted result dict as plain
parameters - it never queries or creates a review itself. `services/event_recap_processor.py::
generate_recap_for_story()` still does NOT call this module (processor != notification, exactly
mirroring the TELEGRAPH pipeline's own established separation - see that processor's own module
docstring, unchanged by this phase).

This module makes no publish decision of any kind: `EventRecapCandidate.publishable` is never
read or set here - it is not even imported (this module never imports `EventRecapCandidate` at
all, unlike Phase C.1's own version of this file). Sending or editing this preview message has no
bearing on and never mutates that field.
"""
from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot.event_recap_review_formatting import render_event_recap_review_text
from bot.keyboards.event_recap_review import build_event_recap_review_keyboard
from database.models.event_recap_review import EventRecapReview
from schemas.editorial_route import EditorialDestination
from services.telegram_routing import RoutingOutcome, send_to_editorial_destination


async def send_event_recap_review(
    bot: Bot, review: EventRecapReview, recap_result: dict, *,
    dry_run: bool = True, destination: EditorialDestination = EditorialDestination.TELEGRAPH,
) -> RoutingOutcome:
    """Sends the EVENT_RECAP review preview as ONE message to `destination`. Makes no decision
    about publication - `dry_run=True` (the safe default) never actually calls the Telegram API
    (send_to_editorial_destination()'s own established contract); the caller decides when (if
    ever) to pass `dry_run=False`. The caller is responsible for persisting
    `RoutingOutcome.chat_id`/`message_id`/`topic_id` onto the owning `EventRecapReview` via
    `services.event_recap_review_service.record_telegram_delivery()` once `sent` is True."""
    text = render_event_recap_review_text(review, recap_result)
    keyboard = build_event_recap_review_keyboard(review)
    return await send_to_editorial_destination(
        bot, destination, text, dry_run=dry_run, reply_markup=keyboard,
    )


async def update_event_recap_review_message(
    bot: Bot, *, chat_id: int, message_id: int, review: EventRecapReview, recap_result: dict,
) -> bool:
    """Edits the ALREADY-SENT review message in place after a decision - never sends a new
    message. Returns `True` on success, `False` on a live `TelegramAPIError` (never raises - the
    decision itself is already durably recorded regardless of whether the re-render succeeds).
    Mirrors services/telegraph_article_review_notifier.py::update_article_review_message()'s own
    identical contract exactly."""
    text = render_event_recap_review_text(review, recap_result)
    keyboard = build_event_recap_review_keyboard(review)
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=keyboard)
    except TelegramAPIError:
        return False
    return True
