"""Bot and Dispatcher factories, configured from application settings.

Instances are created on demand (at application startup), not at import
time, so this module can always be imported safely regardless of whether
TELEGRAM_BOT_TOKEN is configured.
"""
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from core.config import settings


def create_bot() -> Bot:
    """Create a Bot instance from configuration.

    Fails fast with a clear error if TELEGRAM_BOT_TOKEN is missing.
    """
    if settings.telegram_bot_token is None:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    return Bot(
        token=settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    """Create a Dispatcher instance."""
    return Dispatcher()
