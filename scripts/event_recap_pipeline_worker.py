"""NINJA PULSE RECAP Phase R2 integration, Phase E.0: dormant manual entry point for the full
Story -> EVENT_RECAP synthesis -> Telegram-review pipeline, for exactly ONE explicitly-named Story.

Launch with:
    python -m scripts.event_recap_pipeline_worker <story_id> [--live]

No scheduler, cron, or automatic-execution path - a human or an external process invokes this
manually, exactly mirroring scripts/telegraph_pipeline_worker.py's own established convention
("No scheduler, cron, or automatic-execution path - a human or an external process invokes this
manually"). Nothing in this codebase imports or calls this module - `settings.
event_recap_pipeline_enabled` exists (core/config.py, defaulted False) but is never read by any
automatic path; it is declared purely so a future scheduling milestone does not also need a
settings migration, exactly like `telegraph_pipeline_enabled`'s own identical role.

Chains, in order, reusing every existing, already-reviewed Phase A-D.0 component unmodified:
  1. services.event_recap_processor.generate_recap_for_story() - a no-op (returns "already_exists")
     if an EVENT_RECAP task was already created for this Story's anchor event; "story_not_found" if
     `story_id` does not exist. Neither case reaches the steps below.
  2. services.event_recap_review_service.create_event_recap_review() - creates the durable review
     row (idempotent per recap task, exactly like create_article_review()).
  3. services.event_recap_review_notifier.send_event_recap_review() - sends (or, by default,
     DRY-RUNS) the Telegram preview message.

Real paid LLM calls and real Telegram sends require BOTH `--live` on the command line AND
`settings.event_recap_pipeline_enabled = True` in the environment - two independent, explicit
confirmations, mirroring scripts/telegraph_pipeline_worker.py's own established double-
confirmation precedent for real spend.

Omitting `--live` (the default) does NOT prevent a real, paid LLM call: this script's own
production default always assembles the REAL AI integration layer via
assemble_ai_integration_layer() (matching scripts/telegraph_pipeline_worker.py's own identical,
disclosed production-default behavior) - CALLING THIS SCRIPT WITH A REAL story_id ALWAYS PERFORMS
A REAL, PAID LLM CALL if `generate_recap_for_story()` actually reaches synthesis. `--live` gates
ONLY the Telegram send (`dry_run=not (live and settings.event_recap_pipeline_enabled)` passed to
send_event_recap_review()) - it does NOT gate the LLM call. An operator who wants to rehearse this
script with zero cost must inject a FakeLLMGateway-backed CapabilityRegistry themselves (exactly
as every Phase A-D.0 test already does) - this is stated explicitly, not left implicit, because it
is the single most consequential fact about invoking this script (byte-for-byte the same warning
scripts/telegraph_pipeline_worker.py's own docstring already carries for its own pipeline).

Telegram delivery ids (`EventRecapReview.telegram_chat_id`/`telegram_message_id`/
`telegram_thread_id`) are deliberately NOT recorded by this script - `services.
event_recap_review_service.record_telegram_delivery()` exists but is never called here, mirroring
scripts/telegraph_pipeline_worker.py's own identical, already-accepted behavior (that script never
calls TelegraphArticleReviewService.record_telegram_delivery() either). This is a disclosed,
inherited gap, not a Phase E.0 regression: bot/handlers/event_recap_review.py's own approve/
needs_revision callback re-derives `chat_id`/`message_id` from the live Telegram callback object
itself, never from these columns, so the edit-in-place decision flow is unaffected either way.

This script never creates a ContentDraft, never publishes anything, never touches
`EventRecapCandidate.publishable` (services/event_recap.py) - that field is not even reachable
from here, this script only ever sees the recap's own persisted result dict
(`recap_title`/`recap_summary`/`key_takeaways`/`uncertainty_notes`), never a live
`EventRecapCandidate`.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from uuid import UUID

from bot.loader import create_bot
from core.config import settings
from core.logging import setup_logging
from database.models.editorial_task import EditorialTask
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from services.event_recap_processor import generate_recap_for_story
from services.event_recap_review_notifier import send_event_recap_review
from services.event_recap_review_service import create_event_recap_review
from services.pricing_catalog import ModelRegistryPricingCatalog

logger = logging.getLogger(__name__)

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


async def run_event_recap_pipeline_for_story(story_id: UUID, *, live: bool) -> None:
    """Orchestrate one Story through synthesis -> review-creation -> review-send. `live=False`
    (the default) still makes a real, paid LLM call if synthesis is actually reached (see module
    docstring) - it only controls whether the final Telegram send is a dry run."""
    prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
    ai_layer = assemble_ai_integration_layer(settings, prompt_repository)
    registry = ai_layer.capability_registry
    # AIIntegrationLayer does not expose pricing_catalog itself (only gateway/capability_
    # registry/cost_tracker - integrations/llm_gateway/boot.py's own dataclass) - rebuilt here
    # exactly as scripts/telegraph_pipeline_worker.py's own established real-call-site pattern
    # already does, never a second, divergent pricing source.
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())

    async with async_session_factory() as session:
        outcome = await generate_recap_for_story(
            session, story_id, capability_registry=registry,
            cost_tracker=ai_layer.cost_tracker, pricing_catalog=pricing_catalog,
        )
        logger.info(
            "event_recap_pipeline_worker_synthesis_stage",
            extra={
                "story_id": str(story_id), "status": outcome.status,
                "task_id": str(outcome.task_id) if outcome.task_id else None,
                "run_status": outcome.run_result.status if outcome.run_result else None,
            },
        )

        if outcome.status != "generated" or outcome.task_id is None:
            logger.info(
                "event_recap_pipeline_worker_review_stage",
                extra={"story_id": str(story_id), "sent": False, "reason": outcome.status},
            )
            return

        task = await session.get(EditorialTask, outcome.task_id)
        recap_result = None
        if task is not None:
            for step_result in (task.workflow or {}).get("step_results", []):
                if step_result.get("step_name") == "synthesize_recap" and step_result.get("status") == "SUCCESS":
                    recap_result = step_result.get("result")
                    break

        if recap_result is None:
            logger.warning(
                "event_recap_pipeline_worker_review_stage_missing_result",
                extra={"story_id": str(story_id), "task_id": str(outcome.task_id)},
            )
            return

        review = await create_event_recap_review(session, recap_task_id=outcome.task_id)

        dry_run = not (live and settings.event_recap_pipeline_enabled)
        bot = create_bot()
        try:
            routing_outcome = await send_event_recap_review(bot, review, recap_result, dry_run=dry_run)
        finally:
            await bot.session.close()
        logger.info(
            "event_recap_pipeline_worker_review_stage",
            extra={
                "story_id": str(story_id), "review_id": str(review.id), "sent": routing_outcome.sent,
                "dry_run": dry_run,
            },
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("story_id", type=str)
    parser.add_argument(
        "--live", action="store_true",
        help=(
            "Allow a real Telegram send (still requires settings.event_recap_pipeline_enabled=True "
            "as a second, independent confirmation). Does NOT gate the LLM call - see module docstring."
        ),
    )
    return parser.parse_args()


async def main() -> None:
    setup_logging()
    args = _parse_args()
    await run_event_recap_pipeline_for_story(UUID(args.story_id), live=args.live)


if __name__ == "__main__":
    asyncio.run(main())
