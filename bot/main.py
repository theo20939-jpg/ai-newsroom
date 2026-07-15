"""Entry point for running the Telegram bot in polling mode (development).

Launch with:
    python -m bot.main
"""
import asyncio
import logging

from bot.handlers import router
from bot.loader import create_bot, create_dispatcher
from core.logging import setup_logging

logger = logging.getLogger(__name__)


async def on_startup() -> None:
    """Log that the bot has started."""
    logger.info("Bot started")


async def on_shutdown() -> None:
    """Log that the bot has stopped."""
    logger.info("Bot stopped")


async def main() -> None:
    """Create the bot, configure the dispatcher and run long-polling."""
    setup_logging()

    bot = create_bot()
    dp = create_dispatcher()

    dp.include_router(router)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
