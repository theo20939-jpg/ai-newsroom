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
     (returns "already_exists", with the existing task's own id) if an article was already
     generated for this proposal's Story - never a second paid generation call.
  3. services.telegraph_article_review_service.create_article_review() +
     services.telegraph_article_review_notifier.send_article_review() - creates the durable
     review row and sends (or, by default, DRY-RUNS) the COMPLETE article as a header/body-chunks/
     footer message sequence into TELEGRAPH_TOPIC_ID (TELEGRAPH EDITORIAL CHAT DELIVERY - the
     editor is the final publisher, manually, from this full delivery; no external publishing API
     is ever called). On a real, successful send, this function now persists the footer message's
     chat_id/message_id/topic_id onto the review row (TelegraphArticleReviewService.
     record_telegram_delivery()) - the delivery-completion signal send_article_review()'s own
     idempotency guard checks before ever re-sending on a later retry for the same proposal.

  RETRY/RECOVERY FIX: stage 2 returning "already_exists" (a prior run already generated the
  article, e.g. because that run's own Telegram send was skipped/failed/never attempted) is NOT a
  stop condition for stage 3 - `_USABLE_ARTICLE_STATUSES` treats "generated" and "already_exists"
  identically: both resolve the article task, load its result, resolve-or-create the review
  (idempotent, never a duplicate row), and attempt the send. `send_article_review()`'s own
  `review.telegram_message_id is not None` guard is what actually prevents a resend of an
  already-delivered review on yet another retry - this worker never re-checks that condition
  itself, it only ever needs to reach stage 3 reliably.

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

from aiogram import Bot

from bot.loader import create_bot
from capabilities.registry import CapabilityRegistry
from core.config import settings
from core.logging import setup_logging
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from services.cost_tracker import CostTracker
from services.pricing_catalog import ModelRegistryPricingCatalog, PricingCatalog
from services.telegraph_article_processor import generate_article_for_researched_proposal
from services.telegraph_article_review_notifier import send_article_review
from services.telegraph_article_review_service import TelegraphArticleReviewService, create_article_review
from services.telegraph_research_processor import process_approved_telegraph_proposal

logger = logging.getLogger(__name__)

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

# RETRY/RECOVERY FIX: an article task in either of these two ArticleGenerationStatus values has a
# real, usable EditorialTask - "generated" (a brand new task this exact call just ran) and
# "already_exists" (a prior call already created and ran one for this Story, per services.
# telegraph_article_processor's own exactly-once-per-Story guard) are equally valid starting
# points for review resolution/send. Only "not_researched"/"research_not_complete" (no research
# evidence yet) are genuine stop conditions.
_USABLE_ARTICLE_STATUSES = frozenset({"generated", "already_exists"})


def _extract_generate_article_result(workflow: dict | None) -> dict | None:
    """The one, unchanged source of truth for a completed article's structured output - byte-for-
    byte the same `step_results` scan this worker has always used (TELEGRAPH EDITORIAL CHAT
    DELIVERY's own "Preserve this source of truth" requirement), factored out only so the fresh-
    generation path and the already-exists recovery path share exactly one implementation rather
    than two copies that could drift. Returns `None` when no successful `generate_article` step
    exists yet (task still running, or failed before/at that step) - the caller's own signal to
    fail closed rather than inventing or recomputing anything."""
    for step_result in (workflow or {}).get("step_results", []):
        if step_result.get("step_name") == "generate_article" and step_result.get("status") == "SUCCESS":
            return step_result.get("result")
    return None


async def run_telegraph_pipeline_for_proposal(
    proposal_id: UUID,
    *,
    live: bool,
    capability_registry: CapabilityRegistry | None = None,
    cost_tracker: CostTracker | None = None,
    pricing_catalog: PricingCatalog | None = None,
    bot: Bot | None = None,
) -> None:
    """Orchestrate one proposal through research -> article -> review-send. `live=False` (the
    default) still makes real, paid LLM calls (see module docstring) - it only controls whether
    the final Telegram send is a dry run.

    `capability_registry`/`cost_tracker`/`pricing_catalog`/`bot` all default to `None`, in which
    case the real production layer is assembled/constructed exactly as before (this function's own
    real-call-site behavior is completely unchanged when a caller omits every one of them, which
    the CLI entry point below always does). Injectable ONLY for tests - mirrors this codebase's
    own established "optional param, real default, test-only injection" convention (e.g.
    services/meme_generation_orchestrator.py::trigger_meme_generation()'s own `image_gateway`
    parameter) - never a second, divergent code path, just the same real assembly logic moved
    behind an `if ... is None` guard so tests can supply fakes for the retry/recovery scenarios
    this fix is about, without ever constructing a real LLM Gateway or a real Telegram session."""
    if capability_registry is None:
        prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
        ai_layer = assemble_ai_integration_layer(settings, prompt_repository)
        capability_registry = ai_layer.capability_registry
        cost_tracker = ai_layer.cost_tracker
        # AIIntegrationLayer does not expose pricing_catalog itself (only gateway/capability_
        # registry/cost_tracker - integrations/llm_gateway/boot.py's own dataclass) - rebuilt here
        # exactly as tests/test_cost_recording_integration.py's own established real-call-site
        # pattern already does, never a second, divergent pricing source (ModelRegistryPricingCatalog
        # wraps the same build_model_registry() catalog assemble_ai_integration_layer() itself uses).
        pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())
    registry = capability_registry

    async with async_session_factory() as session:
        research_outcome = await process_approved_telegraph_proposal(
            session, proposal_id, capability_registry=registry,
            cost_tracker=cost_tracker, pricing_catalog=pricing_catalog,
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
            cost_tracker=cost_tracker, pricing_catalog=pricing_catalog,
        )
        logger.info(
            "telegraph_pipeline_worker_article_stage",
            extra={
                "proposal_id": str(proposal_id), "status": article_outcome.status,
                "task_id": str(article_outcome.task_id) if article_outcome.task_id else None,
                "run_status": article_outcome.run_result.status if article_outcome.run_result else None,
            },
        )

        if article_outcome.status not in _USABLE_ARTICLE_STATUSES or article_outcome.task_id is None:
            # CASE E: no usable completed article exists (no research yet, research incomplete, or
            # an "already_exists" lookup that somehow found no task) - fail closed, invent/
            # recompute nothing.
            logger.info(
                "telegraph_pipeline_worker_review_stage",
                extra={
                    "proposal_id": str(proposal_id), "sent": False,
                    "reason": f"no_usable_article_task:{article_outcome.status}",
                },
            )
            return

        from database.models.editorial_task import EditorialTask

        task = await session.get(EditorialTask, article_outcome.task_id)
        article_result = _extract_generate_article_result(task.workflow if task is not None else None)

        if article_result is None:
            # CASE E: the resolved article task exists but has no successful generate_article
            # result yet (still running, or failed) - fail closed before ever creating a review
            # row for a result that doesn't exist.
            logger.warning(
                "telegraph_pipeline_worker_review_stage_missing_result",
                extra={
                    "proposal_id": str(proposal_id), "article_task_id": str(article_outcome.task_id),
                    "article_status": article_outcome.status,
                },
            )
            return

        # CASES A/B/D converge here: create_article_review() is itself idempotent (services.
        # telegraph_article_review_service's own docstring - "short-circuits to the existing row
        # rather than letting a second call raise an IntegrityError") - it resolves the existing
        # review (CASE B) or creates exactly one (CASE A/D), never a duplicate; the model's own
        # UNIQUE(article_task_id) constraint is the hard backstop.
        review = await create_article_review(
            session, article_task_id=article_outcome.task_id, proposal_id=proposal_id,
        )

        # Editorial channel split: fetched from the proposal itself - classified once at
        # shortlist-creation time (services/editorial_channel_classifier.py), never re-classified.
        from database.models.telegraph_shortlist import TelegraphTopicProposal

        proposal = await session.get(TelegraphTopicProposal, proposal_id)
        assert proposal is not None  # already resolved successfully by every prior stage above

        dry_run = not (live and settings.telegraph_pipeline_enabled)
        owns_bot = bot is None
        send_bot = bot or create_bot()
        try:
            outcome = await send_article_review(
                send_bot, review, article_result, proposal.editorial_channel, dry_run=dry_run,
            )
        finally:
            if owns_bot:
                await send_bot.session.close()

        # TELEGRAPH EDITORIAL CHAT DELIVERY §6: persist the delivery anchor (the footer message's
        # own chat_id/message_id/topic_id, per send_article_review()'s own contract) the moment a
        # real send succeeds - this is the ONLY thing that makes send_article_review()'s own
        # `already_delivered` idempotency guard effective on a later retry for this same proposal.
        # Previously never wired at all (a pre-existing Checkpoint 6/7 gap, not introduced here).
        if outcome.sent and outcome.message_id is not None and outcome.chat_id is not None:
            review_service = TelegraphArticleReviewService(session)
            await review_service.record_telegram_delivery(
                review.id, chat_id=outcome.chat_id, message_id=outcome.message_id, thread_id=outcome.topic_id,
            )

        logger.info(
            "telegraph_pipeline_worker_review_stage",
            extra={
                "proposal_id": str(proposal_id), "review_id": str(review.id), "sent": outcome.sent,
                "reason": outcome.reason, "dry_run": dry_run,
            },
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
