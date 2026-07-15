"""Handler for the /digest command."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="digest")

PLACEHOLDER_TEXT = "This functionality will be implemented in the next development phases."


@router.message(Command("digest"))
async def handle_digest(message: Message) -> None:
    """Reply to /digest with a placeholder message."""
    await message.answer(PLACEHOLDER_TEXT)
