"""TELEGRAPH Checkpoint 6: inline keyboard + callback_data codec for the article-review UI.
Mirrors bot/keyboards/telegraph_shortlist.py's exact shape - pure, no database access, no
aiogram Bot call.

A distinct prefix ("tgartrev", never "tgshort") - the two callback namespaces are for genuinely
different decisions (topic approval vs. article approval) on genuinely different rows
(TelegraphTopicProposal vs. TelegraphArticleReview); reusing tgshort's prefix would risk a stale
button from one stage being misrouted to the other's handler.
"""
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.models.telegraph_article_review import TelegraphArticleReview, TelegraphArticleReviewStatus

_PREFIX = "tgartrev"
_ACTIONS = ("approve", "revise")


def encode_callback_data(action: str, review_id: UUID) -> str:
    """`tgartrev:<action>:<review_id>` - well within Telegram's 64-byte callback_data limit."""
    return f"{_PREFIX}:{action}:{review_id}"


def parse_callback_data(data: str) -> tuple[str, UUID] | None:
    """Returns `(action, review_id)`, or `None` if `data` is not a well-formed tgartrev
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


def build_article_review_keyboard(review: TelegraphArticleReview) -> InlineKeyboardMarkup | None:
    """One row of [✅ Одобрить][✏️ Доработать] while PENDING - `None` once a final decision has
    been made (mirrors build_shortlist_keyboard()'s own "terminal state, no keyboard" convention)."""
    if review.status != TelegraphArticleReviewStatus.PENDING:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить", callback_data=encode_callback_data("approve", review.id),
                ),
                InlineKeyboardButton(
                    text="✏️ Доработать", callback_data=encode_callback_data("revise", review.id),
                ),
            ]
        ]
    )
