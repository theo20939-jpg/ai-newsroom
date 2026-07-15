"""Handler for the /start command."""
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router(name="start")

PLACEHOLDER_TEXT = "This functionality will be implemented in the next development phases."


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """Reply to /start with a placeholder message."""
    await message.answer(PLACEHOLDER_TEXT)
