"""Aggregates all command routers into a single root router."""
from aiogram import Router

from bot.handlers.digest import router as digest_router
from bot.handlers.news import router as news_router
from bot.handlers.settings import router as settings_router
from bot.handlers.start import router as start_router
from bot.handlers.status import router as status_router

router = Router(name="root")
router.include_router(start_router)
router.include_router(news_router)
router.include_router(digest_router)
router.include_router(status_router)
router.include_router(settings_router)

__all__ = ["router"]
