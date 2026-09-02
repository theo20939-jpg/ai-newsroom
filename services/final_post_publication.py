"""PRESENTATION RECOVERY (2026-09-02), Phase I.3: the ONE real-Telegram-publish step for an
APPROVED_FOR_PUBLICATION `FinalPostReview` row - the piece services/final_post_review_service.py's
own module docstring explicitly named as "a later, separate phase" and never built until now.

Never a second, independent RECAP presentation implementation: media resolution reuses
`services.final_post_review_notifier.resolve_final_post_photo_input()` verbatim (the exact same
function the Final Post Review preview already calls - WYSIWYG by construction, not by
coincidence), the caption reuses `bot.final_post_review_formatting.render_final_post_preview_caption()`
verbatim (which itself now includes the canonical NINJA PULSE footer), and the keyboard reuses
`bot.keyboards.image_preview.build_editorial_send_keyboard()` - the same canonical builder every
other NEWS-family send in this codebase converges on.

Routes to `EditorialDestination.NEWS` - the same real topic every other production presentation
type (NEWS/BREAKING/DATA/QUOTE) already sends to via worker/content_cycle.py. This is establishing
missing routing (no prior RECAP production route existed - the review-stage preview sends to
EditorialDestination.TELEGRAPH instead, an internal review destination), never a change to any
existing route.

Gated by `settings.final_post_publication_enabled` (additive, default `False`) - does NOT alter
`event_recap_pipeline_enabled`'s or `final_post_review_enabled`'s own semantics, which continue to
gate only their own review-stage sends. Never enabled by this phase; `dry_run` mirrors every other
send wrapper's own established two-factor confirmation (`live` AND the settings flag).

Never approves/rejects anything, never re-decides the human's own status. Re-checks eligibility
fresh (never trusts a stale row across time - mirrors this codebase's own established "re-query
fresh, never assume a snapshot is still valid" discipline). Records only
`published_at`/`published_telegram_message_id`/`published_telegram_chat_id` on success - `status`/
`decided_*` stay exclusively owned by services/final_post_review_service.py::set_decision().
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from bot.final_post_review_formatting import CAPTION_SAFE_LIMIT, render_final_post_preview_caption, telegram_utf16_length
from bot.keyboards.image_preview import build_editorial_send_keyboard
from core.config import settings
from database.models.content_draft import ContentDraft
from database.models.final_post_review import FinalPostReview, FinalPostReviewStatus
from schemas.editorial_route import EditorialDestination
from services.final_post_review_eligibility import check_final_post_preview_eligibility
from services.final_post_review_notifier import first_usable_source_url, resolve_final_post_photo_input
from services.telegram_routing import send_photo_to_editorial_destination

logger = logging.getLogger(__name__)

PublicationStatus = Literal[
    "not_approved", "already_published", "not_eligible", "media_resolution_failed",
    "presentation_too_long", "dry_run", "send_failed", "published",
]


@dataclass(frozen=True)
class PublicationOutcome:
    status: PublicationStatus
    telegram_message_id: int | None = None
    telegram_chat_id: int | None = None


async def publish_approved_final_post(
    session: AsyncSession, bot: Bot, review_id: UUID, *, live: bool,
) -> PublicationOutcome:
    """The one entry point. `live=False` (every call site's safe default posture, mirroring every
    other worker in this pipeline) never actually calls the Telegram API - `dry_run=not (live and
    settings.final_post_publication_enabled)` is computed the same two-factor way every sibling
    stage already does it."""
    review = await session.get(FinalPostReview, review_id)
    if review is None:
        return PublicationOutcome(status="not_approved")
    if review.status != FinalPostReviewStatus.APPROVED_FOR_PUBLICATION:
        return PublicationOutcome(status="not_approved")
    if review.published_at is not None:
        # Idempotent: a second call against an already-published row is a no-op, never a duplicate
        # send - mirrors services/final_post_review_service.py::set_decision()'s own "immutable-
        # once-final" discipline, applied here to the publish step itself.
        return PublicationOutcome(
            status="already_published", telegram_message_id=review.published_telegram_message_id,
            telegram_chat_id=review.published_telegram_chat_id,
        )

    eligibility = await check_final_post_preview_eligibility(session, review.content_draft_id)
    if not eligibility.eligible or eligibility.final_post_source is None:
        logger.info(
            "final_post_publication_not_eligible",
            extra={"review_id": str(review_id), "reason": eligibility.reason},
        )
        return PublicationOutcome(status="not_eligible")

    draft = await session.get(ContentDraft, review.content_draft_id)
    assert draft is not None  # eligibility just confirmed this row exists

    final_post_source = eligibility.final_post_source
    media_plan = final_post_source.get("selected_media_plan")
    photo_input = await resolve_final_post_photo_input(session, media_plan)
    if photo_input is None:
        logger.warning("final_post_publication_media_resolution_failed", extra={"review_id": str(review_id)})
        return PublicationOutcome(status="media_resolution_failed")

    caption = render_final_post_preview_caption(draft.title or "", draft.body or "")
    if telegram_utf16_length(caption) > CAPTION_SAFE_LIMIT:
        logger.warning("final_post_publication_presentation_too_long", extra={"review_id": str(review_id)})
        return PublicationOutcome(status="presentation_too_long")

    source_refs = final_post_source.get("source_refs") or []
    source_url = first_usable_source_url(source_refs)
    anchor_event_id = UUID(final_post_source["anchor_event_id"])
    keyboard = build_editorial_send_keyboard(source_url, anchor_event_id)

    dry_run = not (live and settings.final_post_publication_enabled)
    outcome = await send_photo_to_editorial_destination(
        bot, EditorialDestination.NEWS, photo_input, caption, dry_run=dry_run, reply_markup=keyboard,
    )
    if outcome.reason == "dry_run":
        return PublicationOutcome(status="dry_run")
    if not outcome.sent or outcome.chat_id is None or outcome.message_id is None:
        logger.warning(
            "final_post_publication_send_failed", extra={"review_id": str(review_id), "reason": outcome.reason},
        )
        return PublicationOutcome(status="send_failed")

    review.published_at = datetime.now(timezone.utc)
    review.published_telegram_message_id = outcome.message_id
    review.published_telegram_chat_id = outcome.chat_id
    await session.commit()

    return PublicationOutcome(
        status="published", telegram_message_id=outcome.message_id, telegram_chat_id=outcome.chat_id,
    )
