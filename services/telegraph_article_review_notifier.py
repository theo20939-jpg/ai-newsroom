"""TELEGRAPH Checkpoint 6: Telegram send/edit for the article-review UI (part C). Reuses
services/telegram_routing.py::send_to_editorial_destination() verbatim - the single existing
Telegram send boundary Checkpoint 2 already established, never a new HTTP/Bot API call site.
Destination is hardcoded to `EditorialDestination.TELEGRAPH` only (the same internal editorial
Telegram topic Checkpoint 2 uses - NOT telegra.ph publication, per the accepted forensic
baseline this whole pipeline has followed since Checkpoint 1/2).

`dry_run=True` by default, mirroring every other send wrapper in this codebase. No scheduler/
worker/bot-command calls these functions yet - reachable only from bot/handlers/
telegraph_article_review.py's own message-edit path and from whatever future, separately-
authorized caller eventually triggers a real article-review send.
"""
from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot.keyboards.telegraph_article_review import build_article_review_keyboard
from bot.telegraph_article_review_formatting import render_article_review_text
from database.models.telegraph_article_review import TelegraphArticleReview
from schemas.editorial_route import EditorialDestination
from services.telegram_routing import RoutingOutcome, send_to_editorial_destination


async def send_article_review(
    bot: Bot, review: TelegraphArticleReview, article_result: dict, *, dry_run: bool = True,
) -> RoutingOutcome:
    """Sends the article-review preview as ONE message to the TELEGRAPH editorial destination.
    The caller is responsible for persisting `RoutingOutcome.chat_id`/`message_id` onto the
    owning `TelegraphArticleReview` via `TelegraphArticleReviewService.record_telegram_delivery()`
    once `sent` is True."""
    text = render_article_review_text(review, article_result)
    keyboard = build_article_review_keyboard(review)
    return await send_to_editorial_destination(
        bot, EditorialDestination.TELEGRAPH, text, dry_run=dry_run, reply_markup=keyboard,
    )


async def update_article_review_message(
    bot: Bot, *, chat_id: int, message_id: int, review: TelegraphArticleReview, article_result: dict,
) -> bool:
    """Edits the ALREADY-SENT review message in place after a decision - never sends a new
    message. Returns `True` on success, `False` on a live `TelegramAPIError` (never raises - the
    decision itself is already durably recorded regardless of whether the re-render succeeds)."""
    text = render_article_review_text(review, article_result)
    keyboard = build_article_review_keyboard(review)
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=keyboard)
    except TelegramAPIError:
        return False
    return True
