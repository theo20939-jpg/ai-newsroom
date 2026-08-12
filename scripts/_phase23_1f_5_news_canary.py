"""Phase 23.1F - the 5-NEWS editorial quality canary. Same one-shot, host-run, bounded design as
scripts/_phase23_1d_local_live_canary.py (see that phase's own report for the full safety
rationale) - NOT a persistent worker, NOT a Docker container, canary settings applied IN-PROCESS
ONLY, hard preflight route assertion before any LLM/Telegram call.

New this run: loops bounded (analysis cycle, content cycle) rounds - capped at
_MAX_ROUNDS, safety-bounded, never open-ended - because a single round was observed in Phase
23.1D to deliver only 1/5 analyzed events (most did not clear content_generation_min_score), so
reaching ~5 real deliveries requires draining more than one batch of fresh eligible events. Stops
early the moment cumulative `notified` reaches the target, or the moment a round finds nothing
left to do (both analysis and content eligibility are 0) - never chases volume beyond what is
genuinely, freshly eligible.

For each successfully delivered post, captures the full per-post editorial record the phase brief
requires (title, source, scoring, intelligence, fact safety, final rendered text, character count,
button presence) directly from the persisted EditorialTask.workflow JSON - written to a JSON file
for the report to read verbatim, not re-typed by hand.
"""
import asyncio
import json
import logging
from pathlib import Path

from sqlalchemy import func, select

from bot.loader import create_bot
from core.config import settings
from core.logging import setup_logging
from database.models.ai_execution import AIExecution
from database.models.editorial_task import EditorialTask
from database.models.news_event import NewsEvent
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from schemas.editorial_route import EditorialDestination
from services.news_telegram_presentation import build_compact_news_body
from services.pricing_catalog import ModelRegistryPricingCatalog
from services.telegram_routing import RouteTarget, resolve_route
from worker.analysis_cycle import run_analysis_cycle
from worker.content_cycle import run_content_cycle

logger = logging.getLogger(__name__)
_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_REAL_CHAT_ID = -1004297182444
_REAL_NEWS_TOPIC_ID = 2
_TARGET_MESSAGES = 5
_MAX_ROUNDS = 8

_recorded_sends: list[dict[str, object]] = []


def _instrument_send_message(bot: object) -> None:
    original = bot.send_message  # type: ignore[attr-defined]

    async def _wrapped(chat_id: object, text: object = None, *args: object, **kwargs: object) -> object:
        _recorded_sends.append({"chat_id": chat_id, "message_thread_id": kwargs.get("message_thread_id"),
                                 "text": text, "has_button": kwargs.get("reply_markup") is not None})
        return await original(chat_id, text, *args, **kwargs)

    bot.send_message = _wrapped  # type: ignore[attr-defined]


async def main() -> None:
    setup_logging()

    settings.editorial_delivery_mode = "router"
    settings.copywriting_prompt_version = "6"
    settings.story_memory_mode = "shadow"
    settings.newsroom_telegram_chat_id = _REAL_CHAT_ID
    settings.news_topic_id = _REAL_NEWS_TOPIC_ID
    settings.content_generation_dry_run = False

    print("=== CANARY SETTINGS (in-process only) ===")
    for key in ("editorial_delivery_mode", "copywriting_prompt_version", "story_memory_mode",
                "fact_safety_mode", "content_generation_dry_run"):
        print(f"{key} = {getattr(settings, key)}")
    print()

    route = resolve_route(EditorialDestination.NEWS)
    print(f"=== RESOLVED NEWS ROUTE: {route} ===")
    assert route == RouteTarget(chat_id=_REAL_CHAT_ID, topic_id=_REAL_NEWS_TOPIC_ID), (
        f"REFUSING TO PROCEED - resolved route {route} does not match the real canary target"
    )
    print()

    prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
    ai_layer = assemble_ai_integration_layer(settings, prompt_repository)
    bot = create_bot()
    _instrument_send_message(bot)
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())

    async with async_session_factory() as session:
        baseline_cost = (await session.execute(select(func.coalesce(func.sum(AIExecution.cost), 0)))).scalar_one()

    all_delivered_event_ids: list[str] = []
    total_notified = 0

    for round_num in range(1, _MAX_ROUNDS + 1):
        if total_notified >= _TARGET_MESSAGES:
            print(f"=== TARGET REACHED ({total_notified}/{_TARGET_MESSAGES}) - stopping, not chasing volume ===")
            break

        print(f"=== ROUND {round_num}: analysis cycle ===")
        analysis_result = await run_analysis_cycle(
            ai_layer.capability_registry, cost_tracker=ai_layer.cost_tracker, pricing_catalog=pricing_catalog,
        )
        print(analysis_result)

        print(f"=== ROUND {round_num}: content cycle (LIVE) ===")
        content_result = await run_content_cycle(
            ai_layer.capability_registry, bot, cost_tracker=ai_layer.cost_tracker, pricing_catalog=pricing_catalog,
        )
        print(content_result)
        print()

        total_notified += content_result.notified
        all_delivered_event_ids.extend(str(eid) for eid in content_result.event_ids)

        if analysis_result.eligible_found == 0 and content_result.eligible_found == 0:
            print("=== NOTHING LEFT ELIGIBLE THIS ROUND - stopping early, not manufacturing more work ===")
            break

    async with async_session_factory() as session:
        final_cost = (await session.execute(select(func.coalesce(func.sum(AIExecution.cost), 0)))).scalar_one()
    print(f"=== COST: baseline={baseline_cost} final={final_cost} delta={final_cost - baseline_cost} ===")
    print(f"=== TOTAL NOTIFIED: {total_notified} ===")

    # --- build the full per-post editorial record for the report ---
    # Only tasks with a persisted ContentDraft - the real proof persistence (and, given
    # content_generation_dry_run=False plus no active suppression mechanism this run, delivery
    # too) succeeded - `content_result.event_ids` above lists every ELIGIBLE event attempted,
    # including any that failed, so this filter is required, not redundant.
    from database.models.content_draft import ContentDraft

    records: list[dict[str, object]] = []
    async with async_session_factory() as session:
        tasks = (
            await session.execute(
                select(EditorialTask).where(EditorialTask.event_id.in_(all_delivered_event_ids))
            )
        ).scalars().all()
        content_tasks = [
            t for t in tasks
            if (t.workflow or {}).get("workflow_name") == "CONTENT_GENERATION"
        ]
        for task in content_tasks:
            has_draft = (
                await session.execute(select(ContentDraft.id).where(ContentDraft.task_id == task.id))
            ).scalar_one_or_none()
            if has_draft is None:
                continue
            event = await session.get(NewsEvent, task.event_id)
            steps = {s.get("step_name"): s.get("result") for s in (task.workflow or {}).get("step_results", [])}
            copywriting_output = steps.get("copywriting")
            compact_body = build_compact_news_body(copywriting_output) if copywriting_output else None
            records.append({
                "event_id": str(task.event_id),
                "task_id": str(task.id),
                "news_title": event.title if event else None,
                "news_url": event.url if event else None,
                "news_category": event.category.value if event and event.category else None,
                "scoring": steps.get("scoring"),
                "intelligence": steps.get("intelligence"),
                "quality": steps.get("quality"),
                "copywriting_title": copywriting_output.get("title") if copywriting_output else None,
                "compact_body": compact_body,
                "compact_body_len": len(compact_body) if compact_body else None,
            })

    with open("scripts/_phase23_1f_records.json", "w", encoding="utf-8") as f:
        json.dump({
            "total_notified": total_notified,
            "recorded_sends": [
                {**s, "text_len": len(s["text"]) if isinstance(s.get("text"), str) else None}
                for s in _recorded_sends
            ],
            "records": records,
            "cost_delta": final_cost - baseline_cost,
        }, f, indent=2, ensure_ascii=False, default=str)
    print("=== WROTE scripts/_phase23_1f_records.json ===")

    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
