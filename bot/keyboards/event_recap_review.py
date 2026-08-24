"""NINJA PULSE RECAP Phase R2 integration, Phase C.1: inline keyboard + callback_data codec for
the EVENT_RECAP review UI. Mirrors bot/keyboards/telegraph_article_review.py's exact shape - pure,
no database access, no aiogram Bot call.

A distinct prefix ("evrecrev", never "tgartrev") - different decision namespace entirely.

Deliberate difference from telegraph_article_review.py's own build_article_review_keyboard():
that function is keyed on `TelegraphArticleReview.id` (a durable review row with its own
`.status`, letting the keyboard disappear once a final decision is recorded). No equivalent
review row exists for EVENT_RECAP (Phase C.1 does not add one - see this module's own package
docstring / services/event_recap_review_notifier.py). This keyboard is therefore keyed on
`EventRecapCandidate.story_id` instead (already-existing, stable, no new storage) and always
returns the same two-button row - there is no persisted status to hide it behind. The buttons are
wired to a real callback route (bot/handlers/event_recap_review.py) but that handler does not yet
persist any decision - see its own docstring for why, and for what a future phase would need to
add before these buttons can do more than acknowledge a click.
"""
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

_PREFIX = "evrecrev"
_ACTIONS = ("approve", "reject")


def encode_callback_data(action: str, story_id: UUID) -> str:
    """`evrecrev:<action>:<story_id>` - well within Telegram's 64-byte callback_data limit."""
    return f"{_PREFIX}:{action}:{story_id}"


def parse_callback_data(data: str) -> tuple[str, UUID] | None:
    """Returns `(action, story_id)`, or `None` if `data` is not a well-formed evrecrev callback -
    callback_data is user-controllable transport, never trusted blindly."""
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != _PREFIX:
        return None
    action, story_id_raw = parts[1], parts[2]
    if action not in _ACTIONS:
        return None
    try:
        story_id = UUID(story_id_raw)
    except ValueError:
        return None
    return action, story_id


def build_event_recap_review_keyboard(story_id: UUID) -> InlineKeyboardMarkup:
    """One row of [✅ Одобрить][❌ Отклонить]. Unlike build_article_review_keyboard(), never
    returns `None` for a "terminal state" - Phase C.1 has no persisted decision state to check
    (see module docstring). Neither button triggers publication - the handler these route to only
    acknowledges the click (bot/handlers/event_recap_review.py's own docstring)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить", callback_data=encode_callback_data("approve", story_id),
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить", callback_data=encode_callback_data("reject", story_id),
                ),
            ]
        ]
    )
