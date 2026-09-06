"""Aggregates all command routers into a single root router."""
from aiogram import Router

from bot.handlers.business_context import router as business_context_router
from bot.handlers.digest import router as digest_router
from bot.handlers.director_console import router as director_console_router
from bot.handlers.event_recap_review import router as event_recap_review_router
from bot.handlers.final_post_review import router as final_post_review_router
from bot.handlers.image_preview import router as image_preview_router
from bot.handlers.launch import router as launch_router
from bot.handlers.meme_generate import router as meme_generate_router
from bot.handlers.meme_preview import router as meme_preview_router
from bot.handlers.news import router as news_router
from bot.handlers.settings import router as settings_router
from bot.handlers.start import router as start_router
from bot.handlers.status import router as status_router
from bot.handlers.telegram_surface import router as telegram_surface_router
from bot.handlers.telegraph_article_review import router as telegraph_article_review_router
from bot.handlers.telegraph_shortlist import router as telegraph_shortlist_router
from bot.handlers.visual_design import router as visual_design_router
from bot.handlers.whereami import router as whereami_router

router = Router(name="root")
router.include_router(start_router)
router.include_router(news_router)
router.include_router(digest_router)
router.include_router(status_router)
router.include_router(settings_router)
router.include_router(image_preview_router)
# MEME PRODUCTION PIPELINE (overnight phase): the manual "😂 Сгенерировать мем" NEWS-button
# callback - real trigger, gated by settings.meme_manual_approver_user_ids (fail-closed, empty by
# default) and settings.meme_telegram_preview_mode (delivery is dry-run unless "enforce").
router.include_router(meme_generate_router)
# Phase 18 M8 (MEME PRODUCTION PIPELINE): the "memeprev:" approve/reject/regen preview callback -
# reachable once bot/handlers/meme_generate.py above (or a future automatic cycle) actually sends
# a preview message via services/meme_preview_notifier.py::send_meme_preview().
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
# NINJA Social Intelligence Foundation, Part II: General-topic Business Context Command Center.
# Gated by its own two-factor chat+topic check on every message/callback (bot/handlers/
# business_context.py's own module docstring) - a no-op everywhere `newsroom_telegram_chat_id`/
# `business_context_topic_id` do not match. Fail-closed via `business_context_role_map` (empty by
# default - nobody has any role until explicitly configured).
router.include_router(business_context_router)
# SOCIAL-INTELLIGENCE-INTEGRATION-1: NINJA Director Console (/directors /plan /opportunities
# /calendar /performance) - same General-topic gate, additionally off by default via
# settings.director_console_enabled (bot/handlers/director_console.py's own module docstring).
router.include_router(director_console_router)
# SOCIAL-INTELLIGENCE-OPS-1: /surface Telegram Surface configuration - same General-topic gate,
# read available broadly, mutation FOUNDER-only (bot/handlers/telegram_surface.py's own module
# docstring).
router.include_router(telegram_surface_router)
# VISUAL-DESIGN-AUTONOMY-1: /design Visual System status + freeze/unfreeze/rollback - same
# General-topic gate, read available broadly, mutation FOUNDER-only via confirm/cancel keyboard
# (bot/handlers/visual_design.py's own module docstring).
router.include_router(visual_design_router)
# SOCIAL-INTELLIGENCE-PRELAUNCH-1: /launch cold-start social launch strategy (Telegram VPN->PULSE
# transition, Instagram empty-account cold start) - same General-topic gate, read available
# broadly, mutation FOUNDER-only, additionally off by default via
# settings.social_launch_context_enabled (bot/handlers/launch.py's own module docstring).
router.include_router(launch_router)

__all__ = ["router"]
