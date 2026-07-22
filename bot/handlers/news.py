"""Handler for the /news command - the Phase 11 Editorial Inbox (docs/
phase11_telegram_editorial_inbox_architecture_contract.md §9).

Thin orchestration layer only: opens the DB session, calls the read-only query service, renders
each card, sends it. No query construction, no AI/workflow call, no mutation of any kind lives
here (Contract §9's own ownership rule - all query logic lives in
services/editorial_inbox_service.py).
"""
import logging

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message

from bot.formatting import CardTooLongError, render_editorial_card
from database.session import async_session_factory
from services.editorial_inbox_service import get_latest_editorial_cards

router = Router(name="news")

logger = logging.getLogger(__name__)

EMPTY_INBOX_TEXT = "No recent editorial drafts yet."
GENERIC_ERROR_TEXT = "Something went wrong — please try again."


@router.message(Command("news"))
async def handle_news(message: Message) -> None:
    """Reply to /news with up to 5 latest eligible editorial drafts, as separate HTML cards.

    Single session scope spans query + render + send (Contract §9), mirroring
    scripts/run_content_generation.py's own `async with session_factory() as session:` pattern -
    the only precedent this repository has for a bot handler that needs a database session, since
    the bot layer has no dependency injection of any kind (bot/loader.py::create_dispatcher()
    returns a bare Dispatcher()).
    """
    async with async_session_factory() as session:
        try:
            cards = await get_latest_editorial_cards(session, limit=5)
        except Exception:
            logger.exception("news_query_failed")
            await message.answer(GENERIC_ERROR_TEXT)
            return

        if not cards:
            await message.answer(EMPTY_INBOX_TEXT)
            return

        for card in cards:
            try:
                html = render_editorial_card(card)
            except CardTooLongError:
                logger.error("news_card_render_failed", extra={"draft_id": str(card.draft_id)})
                continue
            try:
                await message.answer(html, parse_mode=ParseMode.HTML)
            except TelegramAPIError:
                logger.exception("news_card_send_failed", extra={"draft_id": str(card.draft_id)})
                continue
