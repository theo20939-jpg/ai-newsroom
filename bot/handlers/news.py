"""Handler for the /news command."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="news")

PLACEHOLDER_TEXT = "This functionality will be implemented in the next development phases."


@router.message(Command("news"))
async def handle_news(message: Message) -> None:
    """Reply to /news with a placeholder message."""
    await message.answer(PLACEHOLDER_TEXT)
