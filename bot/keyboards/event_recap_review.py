"""NINJA PULSE RECAP Phase R2 integration, Phase D.0: inline keyboard + callback_data codec for
the EVENT_RECAP review UI. Mirrors bot/keyboards/telegraph_article_review.py's exact shape - pure,
no database access, no aiogram Bot call.

A distinct prefix ("eventrecap", never "tgartrev") - different decision namespace entirely.

Phase D.0 change from Phase C.1: now keyed on the durable `EventRecapReview.id` (Phase D.0 added
that table) instead of `EventRecapCandidate.story_id` - exactly like
build_article_review_keyboard() is keyed on `TelegraphArticleReview.id`. The keyboard now
disappears (`None`) once a final decision has been recorded, matching that same precedent, since
there is now a real persisted status to check.
"""
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.image_preview import build_source_only_keyboard
from database.models.event_recap_review import EventRecapReview, EventRecapReviewStatus

_PREFIX = "eventrecap"
_ACTIONS = ("approve", "needs_revision")

# Phase I.2.2L: the existing newsroom source-button label (worker/content_cycle.py's own
# `_NEWS_SOURCE_BUTTON_LABEL`, documented there as "the label this codebase's Telegram NEWS
# presentation uses for the inline source button") - reused byte-for-byte, never a new wording.
# Deliberately NOT `bot.keyboards.image_preview.NINJA_PULSE_SOURCE_LABEL` ("Источник ↗") - that is
# the public NINJA PULSE Visual System's own distinct label/CTA pairing, out of scope here (this
# internal review UX never adds the subscribe CTA - see build_event_recap_review_keyboard()'s own
# docstring).
_SOURCE_BUTTON_LABEL = "🔗 Источник"


def encode_callback_data(action: str, review_id: UUID) -> str:
    """`eventrecap:<action>:<review_id>` - well within Telegram's 64-byte callback_data limit."""
    return f"{_PREFIX}:{action}:{review_id}"


def parse_callback_data(data: str) -> tuple[str, UUID] | None:
    """Returns `(action, review_id)`, or `None` if `data` is not a well-formed eventrecap
    callback - callback_data is user-controllable transport, never trusted blindly."""
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != _PREFIX:
        return None
    action, review_id_raw = parts[1], parts[2]
    if action not in _ACTIONS:
        return None
    try:
        review_id = UUID(review_id_raw)
    except ValueError:
        return None
    return action, review_id


def build_event_recap_review_keyboard(
    review: EventRecapReview, *, source_url: str | None = None,
) -> InlineKeyboardMarkup | None:
    """Row 1: [✅ Одобрить][✏️ На доработку] while PENDING - `None` once a final decision has been
    made (mirrors build_article_review_keyboard()'s own "terminal state, no keyboard" convention).
    Neither button triggers publication - the handler these route to only persists a decision
    (bot/handlers/event_recap_review.py's own docstring).

    Row 2 (Phase I.2.2L, additive, optional): a single [🔗 Источник] URL button so the editor can
    verify the source before deciding - reuses `build_source_only_keyboard()` (bot/keyboards/
    image_preview.py), the same existing, already-tested component the NEWS presentation profile
    already uses for its own identical-label source button (worker/content_cycle.py), never a
    parallel implementation. `source_url=None` (the caller found no deterministic source URL to
    offer - see `services/event_recap_review_notifier.py::_resolve_primary_source_url()`'s own
    fallback-to-None contract) omits this row entirely, exactly like `build_source_only_keyboard()`
    itself already does - never a placeholder/dead button, never a crash. This never adds the
    NINJA PULSE subscribe CTA - that is a public-channel-only element (`build_source_and_cta_
    keyboard()`), deliberately not part of this internal review UX."""
    if review.status != EventRecapReviewStatus.PENDING:
        return None
    rows = [
        [
            InlineKeyboardButton(
                text="✅ Одобрить", callback_data=encode_callback_data("approve", review.id),
            ),
            InlineKeyboardButton(
                text="✏️ На доработку", callback_data=encode_callback_data("needs_revision", review.id),
            ),
        ]
    ]
    source_keyboard = build_source_only_keyboard(source_url, label=_SOURCE_BUTTON_LABEL)
    if source_keyboard is not None:
        rows.extend(source_keyboard.inline_keyboard)
    return InlineKeyboardMarkup(inline_keyboard=rows)
