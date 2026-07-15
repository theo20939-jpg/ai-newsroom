"""Handler for the /status command."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="status")

PLACEHOLDER_TEXT = "This functionality will be implemented in the next development phases."


@router.message(Command("status"))
async def handle_status(message: Message) -> None:
    """Reply to /status with a placeholder message."""
    await message.answer(PLACEHOLDER_TEXT)
