"""TELEGRAPH Checkpoint 7: dormant worker entry point for the full research -> article ->
Telegram-review pipeline, for exactly ONE explicitly-named, already-APPROVED proposal.

Launch with:
    python -m scripts.telegraph_pipeline_worker <proposal_id> [--live]

No scheduler, cron, or automatic-execution path - a human or an external process invokes this
manually, exactly mirroring scripts/run_content_generation.py's own established convention
("No scheduler, cron, or automatic-execution path - a human or an external process invokes this
manually"). Nothing in this codebase imports or calls this module - `settings.
telegraph_pipeline_enabled` exists (core/config.py, defaulted False) but is never read by any
automatic path; it is declared now, per this checkpoint's own explicit "prepare, do not enable"
scope, purely so a future scheduling milestone does not also need a settings migration.

Chains, in order, reusing every existing, already-reviewed checkpoint unmodified:
  1. services.telegraph_research_processor.process_approved_telegraph_proposal() - a no-op if
     the proposal is not APPROVED-and-unclaimed (idempotent to call on an already-researched
     proposal: the claim simply returns None and this step is skipped).
  2. services.telegraph_article_processor.generate_article_for_researched_proposal() - a no-op
     (returns "already_exists") if an article was already generated for this proposal's Story.
  3. services.telegraph_article_review_service.create_article_review() +
     services.telegraph_article_review_notifier.send_article_review() - creates the durable
     review row and sends (or, by default, DRY-RUNS) the Telegram preview message.

Real paid LLM calls and real Telegram sends require BOTH `--live` on the command line AND
`settings.telegraph_pipeline_enabled = True` in the environment - two independent, explicit
confirmations, mirroring this codebase's own established double-confirmation precedent for real
spend (e.g. scripts/phase17_m3_adaptive_length_comparison.py's own `--confirm-paid-calls` +
`--dry-run` defaulting on). Omitting `--live` (the default) runs everything in dry-run mode: the
capability registry is still real (so structured-output/schema issues surface), but the LLM
Gateway calls are never reached because... actually no dry-run short-circuit exists inside the
Capability layer itself - CALLING THIS SCRIPT WITHOUT `--live` STILL PERFORMS REAL, PAID LLM
CALLS for steps 1/2 if a real CapabilityRegistry is assembled. `--live` therefore gates ONLY the
Telegram send (`dry_run=not args.live` passed to send_article_review()) - it does NOT gate the
LLM calls. An operator who wants to rehearse this script with zero cost and zero Telegram
delivery must inject a FakeLLMGateway-backed CapabilityRegistry themselves (exactly as every test
in this checkpoint series already does) - this script's own production default always assembles
the REAL AI integration layer via assemble_ai_integration_layer(), matching scripts/
run_content_generation.py's own identical, disclosed production-default behavior. This is stated
explicitly, not left implicit, because it is the single most consequential fact about invoking
this script.

==================================================================================================
SCHEDULER DESIGN (not implemented - documented per this checkpoint's own explicit brief)
==================================================================================================

A future, separately-authorized milestone would need two independent polling loops, mirroring
this codebase's own established worker/analysis_cycle.py + worker/content_cycle.py two-loop
precedent (one loop per pipeline stage, never one monolithic loop):

1. SHORTLIST FORMATION loop (new, e.g. worker/telegraph_shortlist_cycle.py): every
   `settings.telegraph_shortlist_schedule_interval_seconds` (default 3600s), call
   services.telegraph_shortlist_service.create_telegraph_shortlist() and, if it produced a
   non-empty batch, services.telegraph_shortlist_notifier.send_telegraph_shortlist() with
   `dry_run=False`. This is the ONLY loop that would ever run automatically without a prior human
   action - everything downstream requires the human APPROVE decision Checkpoint 2 already gates.

2. PIPELINE ADVANCEMENT loop (new, e.g. worker/telegraph_pipeline_cycle.py): every
   `settings.telegraph_pipeline_poll_interval_seconds` (default 300s):
   a. Query APPROVED proposals with `consumed_at IS NULL` (services.telegraph_shortlist_service
      already exposes the exact WHERE-clause shape needed - no new query primitive required) -
      for each, call process_approved_telegraph_proposal().
   b. Query TELEGRAPH_RESEARCH tasks with status=COMPLETED whose proposal has no linked
      TELEGRAPH_ARTICLE task yet (services.telegraph_article_processor.find_article_task_id()
      already exposes the lookup this needs) - for each, call
      generate_article_for_researched_proposal().
   c. Query TELEGRAPH_ARTICLE tasks with status=COMPLETED that have no TelegraphArticleReview row
      yet (services.telegraph_article_review_service.get_review_for_article_task() already
      exposes this) - for each, call create_article_review() + send_article_review().

Both loops would need the SAME bounded-batch-size discipline every existing automatic path in
this codebase already enforces (news_analysis_batch_size, content_generation_batch_size,
content_generation_scan_limit) - never an unbounded scan per cycle. Neither loop auto-approves,
auto-revises, or auto-publishes anything - APPROVE/REJECT (Checkpoint 2) and APPROVE/REQUEST-
REVISION (Checkpoint 6) remain exclusively human decisions made via the existing Telegram
callback handlers; no code path this checkpoint (or the design above) describes ever sets either
of those statuses itself.

==================================================================================================
METRICS (log-event based - this codebase's own established observability convention, never a new
metrics stack/Prometheus/statsd dependency)
==================================================================================================

Every stage below logs a structured INFO event on completion (`extra={...}`) - the same
convention `services/collector.py`/`services/telegraph_shortlist_service.py` already use for
"the cycle outcome is always logged, even when nothing happened" auditability. A future metrics
pipeline would scrape these same log events (this codebase has no existing metrics-emission
mechanism beyond structured logging to build on or diverge from):
  - `telegraph_pipeline_worker_research_stage` (claimed: bool, task_id, run_status)
  - `telegraph_pipeline_worker_article_stage` (status, task_id, run_status)
  - `telegraph_pipeline_worker_review_stage` (review_id, sent: bool, dry_run: bool)
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
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from services.pricing_catalog import ModelRegistryPricingCatalog
from services.telegraph_article_processor import generate_article_for_researched_proposal
from services.telegraph_article_review_notifier import send_article_review
from services.telegraph_article_review_service import create_article_review
from services.telegraph_research_processor import process_approved_telegraph_proposal

logger = logging.getLogger(__name__)

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


async def run_telegraph_pipeline_for_proposal(proposal_id: UUID, *, live: bool) -> None:
    """Orchestrate one proposal through research -> article -> review-send. `live=False` (the
    default) still makes real, paid LLM calls (see module docstring) - it only controls whether
    the final Telegram send is a dry run."""
    prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
    ai_layer = assemble_ai_integration_layer(settings, prompt_repository)
    registry = ai_layer.capability_registry
    # AIIntegrationLayer does not expose pricing_catalog itself (only gateway/capability_
    # registry/cost_tracker - integrations/llm_gateway/boot.py's own dataclass) - rebuilt here
    # exactly as tests/test_cost_recording_integration.py's own established real-call-site
    # pattern already does, never a second, divergent pricing source (ModelRegistryPricingCatalog
    # wraps the same build_model_registry() catalog assemble_ai_integration_layer() itself uses).
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())

    async with async_session_factory() as session:
        research_outcome = await process_approved_telegraph_proposal(
            session, proposal_id, capability_registry=registry,
            cost_tracker=ai_layer.cost_tracker, pricing_catalog=pricing_catalog,
        )
        logger.info(
            "telegraph_pipeline_worker_research_stage",
            extra={
                "proposal_id": str(proposal_id), "claimed": research_outcome.claimed,
                "task_id": str(research_outcome.task_id) if research_outcome.task_id else None,
                "run_status": research_outcome.run_result.status if research_outcome.run_result else None,
            },
        )

        article_outcome = await generate_article_for_researched_proposal(
            session, proposal_id, capability_registry=registry,
            cost_tracker=ai_layer.cost_tracker, pricing_catalog=pricing_catalog,
        )
        logger.info(
            "telegraph_pipeline_worker_article_stage",
            extra={
                "proposal_id": str(proposal_id), "status": article_outcome.status,
                "task_id": str(article_outcome.task_id) if article_outcome.task_id else None,
                "run_status": article_outcome.run_result.status if article_outcome.run_result else None,
            },
        )

        if article_outcome.status != "generated" or article_outcome.task_id is None:
            logger.info(
                "telegraph_pipeline_worker_review_stage",
                extra={"proposal_id": str(proposal_id), "sent": False, "reason": "no_new_article"},
            )
            return

        review = await create_article_review(
            session, article_task_id=article_outcome.task_id, proposal_id=proposal_id,
        )

        from database.models.editorial_task import EditorialTask

        task = await session.get(EditorialTask, article_outcome.task_id)
        article_result = None
        if task is not None:
            for step_result in (task.workflow or {}).get("step_results", []):
                if step_result.get("step_name") == "generate_article" and step_result.get("status") == "SUCCESS":
                    article_result = step_result.get("result")
                    break

        if article_result is None:
            logger.warning(
                "telegraph_pipeline_worker_review_stage_missing_result",
                extra={"proposal_id": str(proposal_id), "review_id": str(review.id)},
            )
            return

        dry_run = not (live and settings.telegraph_pipeline_enabled)
        bot = create_bot()
        try:
            outcome = await send_article_review(bot, review, article_result, dry_run=dry_run)
        finally:
            await bot.session.close()
        logger.info(
            "telegraph_pipeline_worker_review_stage",
            extra={"proposal_id": str(proposal_id), "review_id": str(review.id), "sent": outcome.sent, "dry_run": dry_run},
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal_id", type=str)
    parser.add_argument(
        "--live", action="store_true",
        help=(
            "Allow a real Telegram send (still requires settings.telegraph_pipeline_enabled=True "
            "as a second, independent confirmation). Does NOT gate LLM calls - see module docstring."
        ),
    )
    return parser.parse_args()


async def main() -> None:
    setup_logging()
    args = _parse_args()
    await run_telegraph_pipeline_for_proposal(UUID(args.proposal_id), live=args.live)


if __name__ == "__main__":
    asyncio.run(main())
