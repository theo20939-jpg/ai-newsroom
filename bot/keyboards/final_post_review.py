"""Phase I.2: inline keyboard + callback_data codec for MESSAGE 2, the Final Post publication
review control message. Mirrors bot/keyboards/event_recap_review.py's exact shape - pure, no
database access, no aiogram Bot call.

A distinct prefix ("finalpost", never "eventrecap") - a different decision namespace entirely, so
bot/handlers/event_recap_review.py's own `F.data.startswith("eventrecap:")` filter can never match
a Final Post Review callback and vice versa (Phase I.2's own explicit "handlers must not cross"
instruction).

MESSAGE 1 (the public-like preview) uses `bot/keyboards/image_preview.py::build_source_only_
keyboard()` directly - a general-purpose, already-existing "one source url= button" builder, reused
verbatim, never a second implementation of the same one-button shape.
"""
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.models.final_post_review import FinalPostReview, FinalPostReviewStatus

_PREFIX = "finalpost"
_ACTIONS = ("approve", "needs_revision")


def encode_callback_data(action: str, review_id: UUID) -> str:
    """`finalpost:<action>:<review_id>` - well within Telegram's 64-byte callback_data limit."""
    return f"{_PREFIX}:{action}:{review_id}"


def parse_callback_data(data: str) -> tuple[str, UUID] | None:
    """Returns `(action, review_id)`, or `None` if `data` is not a well-formed finalpost callback -
    callback_data is user-controllable transport, never trusted blindly."""
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


def build_final_post_review_keyboard(review: FinalPostReview) -> InlineKeyboardMarkup | None:
    """One row of [✅ К публикации][✏️ На доработку] while PENDING - `None` once a final decision
    has been made (mirrors build_event_recap_review_keyboard()'s own "terminal state, no keyboard"
    convention). Neither button triggers publication - "К публикации" is a decision only (Phase
    I.2's own explicit Part R "no publication in callback" invariant); the handler this routes to
    only persists a decision (bot/handlers/final_post_review.py's own docstring)."""
    if review.status != FinalPostReviewStatus.PENDING:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ К публикации", callback_data=encode_callback_data("approve", review.id),
                ),
                InlineKeyboardButton(
                    text="✏️ На доработку", callback_data=encode_callback_data("needs_revision", review.id),
                ),
            ]
        ]
    )
