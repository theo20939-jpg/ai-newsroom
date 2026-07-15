"""Handler for the /settings command."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="settings")

PLACEHOLDER_TEXT = "This functionality will be implemented in the next development phases."


@router.message(Command("settings"))
async def handle_settings(message: Message) -> None:
    """Reply to /settings with a placeholder message."""
    await message.answer(PLACEHOLDER_TEXT)
