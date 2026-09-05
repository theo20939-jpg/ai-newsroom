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
persisted `selected_media` pointer into an actual sendable photo (see `_resolve_selected_media_
photo_input()`'s own docstring - Phase H.3C extends this to be fully tier-agnostic, never a new
resolver, never a media reselection), and (2) call the EXISTING `services.event_recap_review_
service.record_telegram_delivery()` once the canonical text message actually sends - closing the
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.event_recap_review_formatting import render_event_recap_review_text
from bot.keyboards.event_recap_review import build_event_recap_review_keyboard
from database.models.editorial_task import EditorialTask
from database.models.event_recap_review import EventRecapReview
from database.models.news_event import NewsEvent
from database.models.news_event_article_acquisition import NewsEventArticleAcquisition
from integrations.storage.image_storage import StorageError
from schemas.editorial_route import EditorialDestination
from services.event_recap_review_service import record_telegram_delivery
from services.image_persistence import _get_storage, get_editorial_image_candidates
from services.media_finalizer import finalize_photo_input
from services.telegram_routing import RoutingOutcome, send_photo_to_editorial_destination, send_to_editorial_destination

logger = logging.getLogger(__name__)


async def _resolve_primary_source_url(session: AsyncSession, task_id: UUID) -> str | None:
    """Phase I.2.2L: the single deterministic source-verification URL for the review keyboard's
    "Источник" button - read-only, zero new network/LLM calls, reuses only already-persisted data.

    Priority (per this codebase's own existing provenance contracts, never a new one):
    1. The recap's own `anchor_event_id` - `services/event_recap_processor.py::
       _persist_source_snapshot()`'s own `event_recap_source_snapshot` step result, already
       written before synthesis ever runs. This is the SAME anchor the synthesis prompt itself
       calls the "ORIGIN announcement... the central event this recap is about" - the most
       semantically correct single URL for a reviewer verifying what the recap's own title/lead
       claim is centered on, not an arbitrary member event.
    2. For that anchor event, `NewsEventArticleAcquisition.canonical_url` if article acquisition
       has already resolved one (the same real-destination-URL mechanism `services.recap_event.
       count_unique_sources_with_canonical_urls()` already documents) - preferred over a raw
       aggregator-wrapper URL whenever it exists.
    3. Falling back to the anchor event's own stored `NewsEvent.url` (always populated - a
       required collector field) when no canonical URL has been resolved yet.

    Returns `None` only if the source snapshot step result is missing entirely or the anchor
    event itself cannot be found - `build_source_only_keyboard()`'s own established contract
    already treats `None` as "omit the button, never crash, never a placeholder URL". Fail-soft,
    never raises (mirrors `_resolve_selected_media_photo_input()`'s own identical discipline in
    this same file): any lookup failure falls back to a text-only-keyboard review rather than
    blocking review delivery."""
    try:
        task = await session.get(EditorialTask, task_id)
        if task is None:
            return None
        anchor_event_id: str | None = None
        for step_result in (task.workflow or {}).get("step_results", []):
            if step_result.get("step_name") == "event_recap_source_snapshot" and step_result.get("status") == "SUCCESS":
                anchor_event_id = (step_result.get("result") or {}).get("anchor_event_id")
                break
        if not anchor_event_id:
            return None

        canonical = await session.scalar(
            select(NewsEventArticleAcquisition.canonical_url).where(
                NewsEventArticleAcquisition.news_event_id == anchor_event_id
            )
        )
        if canonical:
            return canonical

        return await session.scalar(select(NewsEvent.url).where(NewsEvent.id == anchor_event_id))
    except Exception:  # noqa: BLE001 - fail-soft to a keyboard with no source button, never a crash
        logger.warning("event_recap_review_source_url_resolution_failed", exc_info=True)
        return None


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


def _extension_from_storage_key(storage_key: str) -> str:
    if "." in storage_key:
        return storage_key.rsplit(".", 1)[-1]
    return "jpg"  # every current tier that writes a bare storage_key (H.3C) writes JPEG


async def _resolve_selected_media_photo_input(
    session: AsyncSession, selected_media: dict | None,
) -> str | BufferedInputFile | None:
    """Phase H.2 (extended, Phase H.3C): read-only re-resolution of the persisted representative-
    media pointer (`services.event_recap.serialize_selected_media_plan()`'s own JSON shape) into
    whatever Telegram send input is available - tier-agnostic by design (module docstring's own
    "notifier must not care whether the visual came from story_pool/discovered/branded_fallback"
    rule): the ONLY thing this function branches on is which fields the persisted pointer actually
    carries, never `tier` itself.

    - `candidate_id` + `originating_event_id` both present (`tier="story_pool"`/`"discovered"`):
      the EXISTING H.2 path, unchanged - re-reads the ONE already-selected event's already-
      persisted candidate list via `get_editorial_image_candidates()`, then `bot.image_preview_
      media.resolve_photo_input()` (cached Telegram `file_id`, or freshly-read local bytes). Never
      a media reselection: H.1's ranking is not recomputed, no new Story query happens.
    - `storage_key` present with no `candidate_id`/`originating_event_id` (`tier=
      "branded_fallback"`, Phase H.3C - there is no `ImageCandidateRecord` row for a rendered
      card): reads the bytes directly through the SAME `integrations.storage.image_storage.
      ImageStorage` abstraction Tier 1/2B candidates already resolve through (`services.
      image_persistence._get_storage()`, reused unmodified) - no `ImageCandidateRecord` lookup, no
      network, never a second, parallel resolver.

    Fail-soft, never raises: returns `None` for every failure mode (no tier/representative,
    candidate/file no longer found, unresolvable storage/file_id, or any unexpected exception) -
    the caller always falls back to sending the text-only review."""
    if selected_media is None or selected_media.get("tier") == "none":
        return None
    representative = selected_media.get("representative")
    if not representative:
        return None
    try:
        candidate_id = representative.get("candidate_id")
        originating_event_id = representative.get("originating_event_id")
        if candidate_id and originating_event_id:
            event_id = UUID(originating_event_id)
            candidates = await get_editorial_image_candidates(session, news_event_id=event_id, limit=10)
            candidate = next((c for c in candidates if c.candidate_id == candidate_id), None)
            if candidate is None:
                logger.warning(
                    "event_recap_review_media_candidate_not_found",
                    extra={"event_id": str(event_id), "candidate_id": candidate_id},
                )
                return None
            # BufferedInputFile is intentionally not attempted here - Phase H.2 scope only ever
            # resends an ALREADY-STORED-or-file_id-cached candidate (mirrors this module's own
            # "never a new fetch" discipline); a fresh local-bytes read is exactly what resolve_
            # photo_input() already does when telegram_file_id is absent. MEDIA-PROD-1:
            # finalize_photo_input() (services/media_finalizer.py) wraps that same resolution with
            # the mandatory NNJ branding step - the single choke point every non-router delivery
            # path in this codebase now goes through.
            return finalize_photo_input(candidate)

        storage_key = representative.get("storage_key")
        if storage_key:
            try:
                data = _get_storage().read(storage_key)
            except StorageError:
                logger.warning(
                    "event_recap_review_branded_fallback_storage_read_failed",
                    extra={"storage_key": storage_key},
                )
                return None
            extension = _extension_from_storage_key(storage_key)
            return BufferedInputFile(data, filename=f"recap_fallback.{extension}")

        return None
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
    source_url = await _resolve_primary_source_url(session, review.recap_task_id)
    keyboard = build_event_recap_review_keyboard(review, source_url=source_url)
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
