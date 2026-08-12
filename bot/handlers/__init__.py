"""Aggregates all command routers into a single root router."""
from aiogram import Router

from bot.handlers.digest import router as digest_router
from bot.handlers.image_preview import router as image_preview_router
from bot.handlers.meme_preview import router as meme_preview_router
from bot.handlers.news import router as news_router
from bot.handlers.settings import router as settings_router
from bot.handlers.start import router as start_router
from bot.handlers.status import router as status_router
from bot.handlers.whereami import router as whereami_router

router = Router(name="root")
router.include_router(start_router)
router.include_router(news_router)
router.include_router(digest_router)
router.include_router(status_router)
router.include_router(settings_router)
router.include_router(image_preview_router)
# Phase 18 M8: inert until something actually sends a "memeprev:" message - no production code
# path calls services/meme_preview_notifier.py yet (meme_telegram_preview_mode defaults "off").
router.include_router(meme_preview_router)
# Phase 23.0: temporary diagnostic command (bot/handlers/whereami.py's own docstring has the full
# safety scope) - reports chat_id/is_forum/message_thread_id only, no other effect.
router.include_router(whereami_router)

__all__ = ["router"]
