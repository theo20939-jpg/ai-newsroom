"""Phase I.2: Telegram send/edit for the Final Post Preview + publication-review UI. Reuses
services/telegram_routing.py::send_photo_to_editorial_destination()/send_to_editorial_destination()
verbatim - the single existing Telegram send boundary this codebase already established, never a
new HTTP/Bot API call site. Mirrors services/event_recap_review_notifier.py's own two-message
shape/discipline exactly, adapted for a PUBLIC-LIKE preview instead of an internal review card.

Destination defaults to `EditorialDestination.TELEGRAPH` - mirrors services/event_recap_review_
notifier.py's own identical reasoning: no dedicated Final Post Review destination exists yet
(schemas/editorial_route.py's own five-topic enum is deliberately kept small), and this preview is
INTERNAL - it must never route to the public NEWS destination (Phase I.2's own explicit Part T
"never accidentally route to the public channel" invariant). `dry_run=True` by default, mirroring
every other send wrapper in this codebase.

TWO Telegram messages, never one (Phase I.2's own explicit critical product rule):

    MESSAGE 1 (the public-like preview): the representative photo (resolved from `final_post_
    source.selected_media_plan` - tier-agnostic, reusing services/event_recap_review_notifier.py's
    own H.2/H.3C resolution semantics, duplicated here rather than imported per this codebase's own
    established small-helper-duplication convention) with the caption
    `bot.final_post_review_formatting.render_final_post_preview_caption()` produces (the exact,
    untruncated future public post - reuses services.news_telegram_presentation.
    render_v81_news_card_html() verbatim), and reply_markup limited to a single source url= button
    (`bot.keyboards.image_preview.build_source_only_keyboard()`) - NEVER the ✅/✏️ decision keyboard.
    Media is REQUIRED at this gate (services/final_post_review_eligibility.py already enforced this
    before this module is ever reached) - there is no text-only fallback path here, unlike the
    ordinary NEWS delivery notifiers.

    MESSAGE 2 (the control message): a short, internal-only text
    (`bot.final_post_review_formatting.render_final_post_review_control_text()`) sent as a reply to
    MESSAGE 1, carrying the real ✅ К публикации / ✏️ На доработку keyboard
    (`bot.keyboards.final_post_review.build_final_post_review_keyboard()`). This is the ONLY message
    this module ever records as `FinalPostReview.telegram_*` (via
    `services.final_post_review_service.record_telegram_delivery()`) - MESSAGE 1's own message id is
    never persisted anywhere.

NO SILENT TRUNCATION (Phase I.2's own Part G): if the rendered MESSAGE 1 caption exceeds Telegram's
photo-caption limit, this module sends NOTHING and returns `"presentation_too_long"` - it never
shrinks/truncates the body itself (unlike bot/formatting.py::render_editorial_card()'s own
different, NEWS-editorial-card-specific shrink-loop contract, which is deliberately not reused
here for exactly this reason).

SEND FAILURE SEMANTICS (Phase I.2's own Part U): a media-resolution failure sends nothing at all
(no fallback text-only send - media is required at this gate). A live MESSAGE 1 failure never
attempts MESSAGE 2 (an editor cannot approve an unseen final post). A live MESSAGE 1 success
followed by a MESSAGE 2 failure is reported as `"control_send_failed"` - never silently treated as
an actionable, deliverable review, and never auto-retried.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from bot.final_post_review_formatting import (
    CAPTION_SAFE_LIMIT,
    render_final_post_preview_caption,
    render_final_post_review_control_text,
    telegram_utf16_length,
)
from bot.keyboards.final_post_review import build_final_post_review_keyboard
from bot.keyboards.image_preview import build_editorial_send_keyboard
from database.models.final_post_review import FinalPostReview
from integrations.storage.image_storage import StorageError
from schemas.editorial_route import EditorialDestination
from services.final_post_review_service import record_telegram_delivery
from services.image_persistence import _get_storage, get_editorial_image_candidates
from services.media_finalizer import finalize_photo_input
from services.nnj_master_news_overlay import apply_master_news_branding
from services.telegram_routing import send_photo_to_editorial_destination, send_to_editorial_destination

logger = logging.getLogger(__name__)

FinalPostPreviewSendStatus = Literal[
    "media_resolution_failed", "presentation_too_long", "dry_run",
    "preview_send_failed", "control_send_failed", "sent",
]


@dataclass(frozen=True)
class FinalPostPreviewSendOutcome:
    status: FinalPostPreviewSendStatus
    preview_message_id: int | None = None
    control_message_id: int | None = None


def _extension_from_storage_key(storage_key: str) -> str:
    """Byte-for-byte the same helper services/event_recap_review_notifier.py::
    _extension_from_storage_key() already established - duplicated, not imported (private,
    module-scoped helper)."""
    if "." in storage_key:
        return storage_key.rsplit(".", 1)[-1]
    return "jpg"


async def resolve_final_post_photo_input(session: AsyncSession, selected_media: dict[str, Any] | None):
    """PRESENTATION RECOVERY (2026-09-02) WYSIWYG requirement: deliberately made importable
    (no longer a `_`-prefixed module-private helper) so `services/final_post_publication.py`'s real
    publish step can call this SAME function - one shared media-resolution implementation for both
    the Final Post Review preview and real publication, never two independent ones (plan review
    correction 2's explicit "do not create two independent RECAP presentation implementations for
    preview vs. publish" requirement overrides this codebase's general small-helper-duplication
    convention for this one function specifically).

    Tier-agnostic by construction: branches only on which fields the persisted pointer carries
    (`candidate_id`+`originating_event_id` vs. `storage_key` alone), never on `tier` itself. Both
    branches now converge on the same canonical branding: the `candidate_id` branch already went
    through `finalize_photo_input()` (MEDIA-PROD-1, applies `apply_master_news_branding()` when
    `presentation_director_mode=="enforce"` and `pulse_brand_enabled`); the `storage_key` branch
    (RECAP Tier 3's own unbranded `build_recap_fallback_background()` output - see services/
    event_recap_processor.py) now applies the exact same branding call directly, under the exact
    same gate, so an editor's preview always shows the real branding real publication would send.
    Fail-soft, never raises: returns `None` for every failure mode; a branding failure falls back
    to the original unbranded bytes rather than blocking the preview (mirrors `finalize_photo_
    input()`'s own identical fail-open contract)."""
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
                    "final_post_review_media_candidate_not_found",
                    extra={"event_id": str(event_id), "candidate_id": candidate_id},
                )
                return None
            # PRODUCTION-SOURCE-RECONCILIATION-1: services/media_finalizer.py (MEDIA-PROD-1) is the
            # real, canonical, single choke point for this exact resolve+brand contract - recovered
            # from the accepted production source (feature/prod-content-recap-release @ 250da40) and
            # ported into this tree. A prior local fix (R2.10-FINALIZATION-2) inlined the same
            # resolve/brand/fail-soft logic directly here because media_finalizer.py did not yet
            # exist in this branch's own history; that duplication is removed now that the real
            # shared helper is present, so this branch converges on the identical single
            # implementation the storage_key branch below and every other real caller
            # (bot/handlers/image_preview.py, services/image_preview_notifier.py, services/
            # event_recap_review_notifier.py) now also use.
            return finalize_photo_input(candidate)

        storage_key = representative.get("storage_key")
        if storage_key:
            try:
                data = _get_storage().read(storage_key)
            except StorageError:
                logger.warning(
                    "final_post_review_branded_fallback_storage_read_failed",
                    extra={"storage_key": storage_key},
                )
                return None
            if settings.presentation_director_mode == "enforce" and settings.pulse_brand_enabled:
                try:
                    data, _decision = apply_master_news_branding(data)
                except Exception:  # noqa: BLE001 - branding is best-effort, never blocks the preview
                    logger.exception("final_post_review_branded_fallback_branding_failed", extra={"storage_key": storage_key})
            extension = _extension_from_storage_key(storage_key)
            return BufferedInputFile(data, filename=f"final_post_preview.{extension}")

        return None
    except Exception:  # noqa: BLE001 - fail-soft: caller treats None as media_resolution_failed
        logger.warning("final_post_review_media_resolution_failed", exc_info=True)
        return None


def first_usable_source_url(source_refs: list[Any]) -> str | None:
    """A "usable" source_ref, for keyboard purposes, is one shaped like an actual clickable URL -
    `final_post_source.source_refs` may in principle contain a bare domain or a non-URL sentinel
    (services.event_recap._evidence_reference_identity()'s own documented fallback shapes, though
    `AnnouncementSummary.source_refs` itself is built from real article URLs in the common case).
    Returns `None` (never raises) if none qualify - build_source_only_keyboard() already degrades
    gracefully to "no keyboard" in that case."""
    for ref in source_refs:
        if isinstance(ref, str) and ref.startswith(("http://", "https://")):
            return ref
    return None


async def send_final_post_preview(
    bot: Bot,
    session: AsyncSession,
    review: FinalPostReview,
    *,
    title: str,
    body: str,
    final_post_source: dict[str, Any],
    authoring_prompt_version: str,
    fact_safety_status: str,
    dry_run: bool = True,
    destination: EditorialDestination = EditorialDestination.TELEGRAPH,
) -> FinalPostPreviewSendOutcome:
    """Sends the two-message Final Post Preview (module docstring's own full contract). Makes no
    publication decision of any kind - `dry_run=True` (the safe default) never actually calls the
    Telegram API for either message, mirroring services/event_recap_review_notifier.py::
    send_event_recap_review()'s own identical `dry_run` contract; both messages are still rendered
    and their `RoutingOutcome.reason == "dry_run"` is surfaced as this function's own `"dry_run"`
    status, never confused with a real send failure."""
    media_plan = final_post_source.get("selected_media_plan")
    photo_input = await resolve_final_post_photo_input(session, media_plan)
    if photo_input is None:
        logger.warning("final_post_preview_media_resolution_failed", extra={"review_id": str(review.id)})
        return FinalPostPreviewSendOutcome(status="media_resolution_failed")

    caption = render_final_post_preview_caption(title, body)
    caption_length = telegram_utf16_length(caption)
    if caption_length > CAPTION_SAFE_LIMIT:
        logger.warning(
            "final_post_preview_presentation_too_long",
            extra={"review_id": str(review.id), "length": caption_length, "limit": CAPTION_SAFE_LIMIT},
        )
        return FinalPostPreviewSendOutcome(status="presentation_too_long")

    source_refs = final_post_source.get("source_refs") or []
    source_url = first_usable_source_url(source_refs)
    # PRESENTATION RECOVERY (2026-09-02) WYSIWYG requirement: the canonical NEWS-family keyboard
    # (source + meme, never a subscribe/CTA button) - the same builder and the same identity
    # (final_post_source["anchor_event_id"], always present per services/final_post_processor.py's
    # own bundle contract) real publication (services/final_post_publication.py) uses, so an
    # editor's preview shows the exact keyboard that would actually be sent.
    anchor_event_id = UUID(final_post_source["anchor_event_id"])
    preview_keyboard = build_editorial_send_keyboard(source_url, anchor_event_id)

    preview_outcome = await send_photo_to_editorial_destination(
        bot, destination, photo_input, caption, dry_run=dry_run, reply_markup=preview_keyboard,
    )
    if not preview_outcome.sent and preview_outcome.reason != "dry_run":
        logger.warning(
            "final_post_preview_send_failed",
            extra={"review_id": str(review.id), "reason": preview_outcome.reason},
        )
        return FinalPostPreviewSendOutcome(status="preview_send_failed")

    control_text = render_final_post_review_control_text(
        review, authoring_prompt_version=authoring_prompt_version, fact_safety_status=fact_safety_status,
        source_event_recap_review_id=final_post_source.get("source_event_recap_review_id"),
    )
    control_keyboard = build_final_post_review_keyboard(review)
    control_outcome = await send_to_editorial_destination(
        bot, destination, control_text, dry_run=dry_run, reply_markup=control_keyboard,
        reply_to_message_id=preview_outcome.message_id,
    )

    if control_outcome.reason == "dry_run":
        return FinalPostPreviewSendOutcome(status="dry_run")
    if not control_outcome.sent:
        logger.warning(
            "final_post_review_control_send_failed",
            extra={"review_id": str(review.id), "reason": control_outcome.reason},
        )
        return FinalPostPreviewSendOutcome(status="control_send_failed", preview_message_id=preview_outcome.message_id)

    if control_outcome.chat_id is not None and control_outcome.message_id is not None:
        await record_telegram_delivery(
            session, review.id, chat_id=control_outcome.chat_id, message_id=control_outcome.message_id,
            thread_id=control_outcome.topic_id,
        )

    return FinalPostPreviewSendOutcome(
        status="sent", preview_message_id=preview_outcome.message_id, control_message_id=control_outcome.message_id,
    )


async def update_final_post_review_message(
    bot: Bot, *, chat_id: int, message_id: int, review: FinalPostReview,
) -> bool:
    """Edits the ALREADY-SENT MESSAGE 2 (control message) in place after a decision - never sends a
    new message, never touches MESSAGE 1 (the public-like preview - Phase I.2's own explicit "Do
    not edit public-like preview. Do not create new message." Part Q instruction). Returns `True` on
    success, `False` on a live `TelegramAPIError` (never raises). Mirrors services/event_recap_
    review_notifier.py::update_event_recap_review_message()'s own identical contract exactly."""
    text = render_final_post_review_control_text(review)
    keyboard = build_final_post_review_keyboard(review)
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=keyboard)
    except TelegramAPIError:
        return False
    return True
