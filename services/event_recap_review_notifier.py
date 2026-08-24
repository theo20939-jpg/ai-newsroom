"""NINJA PULSE RECAP Phase R2 integration, Phase C.1: Telegram send for the EVENT_RECAP review UI.
Reuses services/telegram_routing.py::send_to_editorial_destination() verbatim - the single
existing Telegram send boundary this codebase already established, never a new HTTP/Bot API call
site. Mirrors services/telegraph_article_review_notifier.py's own shape/discipline exactly.

Destination defaults to `EditorialDestination.TELEGRAPH` - the same internal editorial Telegram
topic TELEGRAPH article review already uses. No dedicated EVENT_RECAP destination exists yet
(schemas/editorial_route.py's own five-topic enum is deliberately kept small, no speculative
additions per that module's own docstring); the caller may pass a different `EditorialDestination`
explicitly if one is added later - this module makes no destination decision of its own beyond the
default.

`dry_run=True` by default, mirroring every other send wrapper in this codebase. No scheduler/
worker/bot-command calls this function yet - `services/event_recap_processor.py::
generate_recap_for_story()` deliberately does NOT call it (processor != notification, exactly
mirroring the TELEGRAPH pipeline's own established separation - see that processor's own module
docstring). Reachable only from a future, separately-authorized caller (a manual script, or
bot/handlers/event_recap_review.py's own future decision-persistence work).

This module makes no publish decision of any kind: `EventRecapCandidate.publishable` is never
read or set here - it is not even imported for that purpose, only as the type this function's
`candidate` parameter carries. Sending this preview message has no bearing on and never mutates
that field.
"""
from __future__ import annotations

from aiogram import Bot

from bot.event_recap_review_formatting import render_event_recap_review_text
from bot.keyboards.event_recap_review import build_event_recap_review_keyboard
from schemas.editorial_route import EditorialDestination
from services.event_recap import EventRecapCandidate
from services.telegram_routing import RoutingOutcome, send_to_editorial_destination


async def send_event_recap_review(
    bot: Bot, candidate: EventRecapCandidate, *,
    dry_run: bool = True, destination: EditorialDestination = EditorialDestination.TELEGRAPH,
) -> RoutingOutcome:
    """Sends the EVENT_RECAP review preview as ONE message to `destination`. Makes no decision
    about publication - `dry_run=True` (the safe default) never actually calls the Telegram API
    (send_to_editorial_destination()'s own established contract); the caller decides when (if
    ever) to pass `dry_run=False`. The caller is responsible for persisting
    `RoutingOutcome.chat_id`/`message_id` anywhere it needs them - this module stays DB-free,
    matching services/telegraph_article_review_notifier.py's own established convention (there is
    no durable EVENT_RECAP review row to persist them onto yet - see this module's own package
    docstring)."""
    text = render_event_recap_review_text(candidate)
    keyboard = build_event_recap_review_keyboard(candidate.story_id)
    return await send_to_editorial_destination(
        bot, destination, text, dry_run=dry_run, reply_markup=keyboard,
    )
