"""TELEGRAPH Checkpoint 6 (revised, TELEGRAPH EDITORIAL CHAT DELIVERY): Telegram send/edit for
the article-review UI (part C). Reuses services/telegram_routing.py::
send_to_editorial_destination() verbatim, once per message - the single existing Telegram send
boundary Checkpoint 2 already established, never a new HTTP/Bot API call site. Destination is
hardcoded to `EditorialDestination.TELEGRAPH` only (the internal editorial Telegram topic,
TELEGRAPH_TOPIC_ID - not an external publishing surface; no outbound publish-API call of any kind
is made anywhere in this codebase).

`send_article_review()` now sends the COMPLETE article as a short, ordered sequence of messages -
header, then N body chunks, then a sources+status footer with the review-control keyboard - never
a bounded preview. See bot/telegraph_article_review_formatting.py's own module docstring for the
full three-message design and why only the footer is ever re-rendered afterward.

Idempotency (TELEGRAPH EDITORIAL CHAT DELIVERY §6): `review.telegram_message_id` is the ONLY
delivery-completion signal this module trusts - set exclusively by the caller (scripts/
telegraph_pipeline_worker.py) via TelegraphArticleReviewService.record_telegram_delivery() once
`send_article_review()` reports the footer as sent. If it is already set, `send_article_review()`
short-circuits immediately (`sent=False, reason="already_delivered"`, zero Telegram calls) rather
than re-sending the whole sequence on a normal retry (e.g. the pipeline worker re-invoked for the
same proposal). Disclosed limitation: this is an all-or-nothing guard keyed on the FINAL message
only - a crash or API failure partway through (header sent, only some body chunks sent, footer
never reached) leaves `telegram_message_id` unset, so a subsequent retry resends the ENTIRE
sequence from scratch, visibly duplicating whatever the interrupted attempt already delivered.
Accepted for this phase (no large new subsystem, per the phase's own explicit constraint) - a
human editor can see and ignore the duplicate content; nothing is corrupted or lost.

`dry_run=True` by default, mirroring every other send wrapper in this codebase.
"""
from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot.keyboards.telegraph_article_review import build_article_review_keyboard
from bot.telegraph_article_review_formatting import (
    build_article_body_chunks,
    render_article_footer_text,
    render_article_review_header,
)
from database.models.telegraph_article_review import TelegraphArticleReview
from schemas.editorial import EditorialChannel
from schemas.editorial_route import EditorialDestination
from services.telegram_routing import RoutingOutcome, send_to_editorial_destination


async def send_article_review(
    bot: Bot, review: TelegraphArticleReview, article_result: dict, editorial_channel: EditorialChannel,
    *, dry_run: bool = True,
) -> RoutingOutcome:
    """Sends the COMPLETE article as an ordered message sequence (header, body chunks, sources+
    status footer with the review keyboard) to the TELEGRAPH editorial destination - never a
    preview, never truncated. Returns the FOOTER message's own `RoutingOutcome` (the "anchor" the
    caller persists via `TelegraphArticleReviewService.record_telegram_delivery()` once `sent` is
    True - exactly the same contract this function's single-message predecessor already
    established, just now anchored to the last message of several instead of the only one).

    Short-circuits to `sent=False, reason="already_delivered"` with zero Telegram calls if
    `review.telegram_message_id` is already set (see module docstring for the exact idempotency
    contract and its one disclosed limitation).

    On a real (non-dry-run) send failure at the header or any body chunk, returns that failed
    outcome immediately without attempting the remaining messages - never sends body content
    without its header, and never sends the footer (with its review keyboard) for an incomplete
    body. In `dry_run` mode every stage is still walked through (each `send_to_editorial_
    destination()` call itself returns `sent=False, reason="dry_run"` without ever calling the
    Telegram API), so a dry run still exercises and can log the full sequence."""
    if review.telegram_message_id is not None:
        return RoutingOutcome(
            destination=EditorialDestination.TELEGRAPH, chat_id=review.telegram_chat_id,
            topic_id=review.telegram_thread_id, sent=False, reason="already_delivered",
            message_id=review.telegram_message_id,
        )

    header_text = render_article_review_header(article_result, editorial_channel)
    header_outcome = await send_to_editorial_destination(
        bot, EditorialDestination.TELEGRAPH, header_text, dry_run=dry_run,
    )
    if not header_outcome.sent and not dry_run:
        return header_outcome

    for chunk_text in build_article_body_chunks(article_result):
        chunk_outcome = await send_to_editorial_destination(
            bot, EditorialDestination.TELEGRAPH, chunk_text, dry_run=dry_run,
        )
        if not chunk_outcome.sent and not dry_run:
            return chunk_outcome

    footer_text = render_article_footer_text(article_result, review)
    keyboard = build_article_review_keyboard(review)
    return await send_to_editorial_destination(
        bot, EditorialDestination.TELEGRAPH, footer_text, dry_run=dry_run, reply_markup=keyboard,
    )


async def update_article_review_message(
    bot: Bot, *, chat_id: int, message_id: int, review: TelegraphArticleReview, article_result: dict,
    editorial_channel: EditorialChannel,
) -> bool:
    """Edits the ALREADY-SENT footer message in place after a decision - the header and body
    chunks are never touched again (see bot/telegraph_article_review_formatting.py's own module
    docstring for why only the footer is ever kept current). Never sends a new message. Returns
    `True` on success, `False` on a live `TelegramAPIError` (never raises - the decision itself is
    already durably recorded regardless of whether the re-render succeeds).

    `editorial_channel` is accepted for call-site symmetry with `send_article_review()` and
    forward compatibility, even though the footer text itself (sources + status) does not depend
    on it - unused parameters are never silently dropped from a public function's signature in
    this codebase's own established convention."""
    text = render_article_footer_text(article_result, review)
    keyboard = build_article_review_keyboard(review)
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=keyboard)
    except TelegramAPIError:
        return False
    return True
