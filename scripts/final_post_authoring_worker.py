"""Phase I.1 (Approved EVENT_RECAP -> Final Post Authoring Core): dormant manual entry point for
the Approved EventRecapReview -> Final Post authoring core, for exactly ONE explicitly-named
review.

Launch with:
    python -m scripts.final_post_authoring_worker <event_recap_review_id>

No scheduler, cron, or automatic-execution path - a human or an external process invokes this
manually, mirroring scripts/event_recap_pipeline_worker.py's own established convention exactly.
Nothing in this codebase imports or calls this module.

Takes a `review_id` (never a `story_id`) - the exact human-approved artifact this authoring run
must be provenanced to (services/final_post_processor.py's own Correction #1 discipline).

CALLING THIS SCRIPT WITH A REAL, APPROVED review_id ALWAYS PERFORMS A REAL, PAID LLM CALL if
`generate_final_post_for_review()` actually reaches authoring (mirrors scripts/
event_recap_pipeline_worker.py's own identical, disclosed production-default behavior - this
script's own production default always assembles the REAL AI integration layer via
assemble_ai_integration_layer()). An operator who wants to rehearse this script with zero cost must
inject a FakeLLMGateway-backed CapabilityRegistry themselves (exactly as every Phase I.1 test
already does) - this is stated explicitly, not left implicit, for the same reason scripts/
event_recap_pipeline_worker.py's own docstring states it explicitly.

This script never sends Telegram, never publishes anything, never creates a FinalPostReview (no
such thing exists yet - Phase I.2). It only ever prints/logs the resulting
`FinalPostGenerationOutcome` - a human reads the created `ContentDraft` directly from the database
until Phase I.2's own Telegram Final Post Preview exists.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from uuid import UUID

from core.config import settings
from core.logging import setup_logging
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from services.final_post_processor import generate_final_post_for_review
from services.pricing_catalog import ModelRegistryPricingCatalog

logger = logging.getLogger(__name__)

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


async def run_final_post_authoring_for_review(review_id: UUID) -> None:
    """Orchestrate one APPROVED EventRecapReview through the Final Post authoring core. Always
    makes a real, paid LLM call if authoring is actually reached (see module docstring)."""
    prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
    ai_layer = assemble_ai_integration_layer(settings, prompt_repository)
    registry = ai_layer.capability_registry
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())

    async with async_session_factory() as session:
        outcome = await generate_final_post_for_review(
            session, review_id, capability_registry=registry,
            cost_tracker=ai_layer.cost_tracker, pricing_catalog=pricing_catalog,
        )
        logger.info(
            "final_post_authoring_worker_outcome",
            extra={
                "review_id": str(review_id), "status": outcome.status,
                "task_id": str(outcome.task_id) if outcome.task_id else None,
                "run_status": outcome.run_result.status if outcome.run_result else None,
                "content_draft_id": str(outcome.content_draft.id) if outcome.content_draft else None,
                "fact_safety_status": outcome.fact_safety_status,
            },
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_id", type=str, help="The EventRecapReview id to author a Final Post from.")
    return parser.parse_args()


async def main() -> None:
    setup_logging()
    args = _parse_args()
    await run_final_post_authoring_for_review(UUID(args.review_id))


if __name__ == "__main__":
    asyncio.run(main())
