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

from database.models.event_recap_review import EventRecapReview, EventRecapReviewStatus

_PREFIX = "eventrecap"
_ACTIONS = ("approve", "needs_revision")


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


def build_event_recap_review_keyboard(review: EventRecapReview) -> InlineKeyboardMarkup | None:
    """One row of [✅ Одобрить][✏️ На доработку] while PENDING - `None` once a final decision has
    been made (mirrors build_article_review_keyboard()'s own "terminal state, no keyboard"
    convention). Neither button triggers publication - the handler these route to only persists a
    decision (bot/handlers/event_recap_review.py's own docstring)."""
    if review.status != EventRecapReviewStatus.PENDING:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить", callback_data=encode_callback_data("approve", review.id),
                ),
                InlineKeyboardButton(
                    text="✏️ На доработку", callback_data=encode_callback_data("needs_revision", review.id),
                ),
            ]
        ]
    )
