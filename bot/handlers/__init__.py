"""Aggregates all command routers into a single root router."""
from aiogram import Router

from bot.handlers.digest import router as digest_router
from bot.handlers.event_recap_review import router as event_recap_review_router
from bot.handlers.final_post_review import router as final_post_review_router
from bot.handlers.image_preview import router as image_preview_router
from bot.handlers.meme_preview import router as meme_preview_router
from bot.handlers.news import router as news_router
from bot.handlers.settings import router as settings_router
from bot.handlers.start import router as start_router
from bot.handlers.status import router as status_router
from bot.handlers.telegraph_article_review import router as telegraph_article_review_router
from bot.handlers.telegraph_shortlist import router as telegraph_shortlist_router
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
# TELEGRAPH Checkpoint 2: inert until something actually creates+sends a shortlist batch - no
# scheduler/worker/bot-command calls services/telegraph_shortlist_service.py::
# create_telegraph_shortlist() or services/telegraph_shortlist_notifier.py yet.
router.include_router(telegraph_shortlist_router)
# TELEGRAPH Checkpoint 6: inert until something actually creates+sends an article review - no
# scheduler/worker/bot-command calls services/telegraph_article_review_service.py::
# create_article_review() or services/telegraph_article_review_notifier.py yet.
router.include_router(telegraph_article_review_router)
# NINJA PULSE RECAP Phase R2 integration, Phase D.0: inert until something actually sends an
# EVENT_RECAP review preview - no scheduler/worker/bot-command calls services/
# event_recap_review_notifier.py yet (services/event_recap_processor.py::generate_recap_for_story()
# deliberately never calls it - processor != notification). Its own callback handler now fully
# persists approve/needs_revision decisions onto EventRecapReview (Phase D.0), but is only ever
# reached once some future, separately-authorized caller actually sends a review message with a
# real "eventrecap:" callback button - bot/handlers/event_recap_review.py's own docstring.
router.include_router(event_recap_review_router)
# Phase I.2: inert until something actually sends a Final Post Preview - no scheduler/worker/
# bot-command calls services/final_post_review_service.py::create_final_post_review() or
# services/final_post_review_notifier.py yet (only the manually-invoked, never-auto-run
# scripts/final_post_review_worker.py CLI). Its own callback handler fully persists approve/
# needs_revision decisions onto FinalPostReview, but is only ever reached once some future,
# separately-authorized caller actually sends a review message with a real "finalpost:" callback
# button - bot/handlers/final_post_review.py's own docstring.
router.include_router(final_post_review_router)
# Phase 23.0: temporary diagnostic command (bot/handlers/whereami.py's own docstring has the full
# safety scope) - reports chat_id/is_forum/message_thread_id only, no other effect.
router.include_router(whereami_router)

__all__ = ["router"]
