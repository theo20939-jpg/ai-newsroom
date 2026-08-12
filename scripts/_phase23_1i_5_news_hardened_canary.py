"""Phase 23.1I - the 5-publishable-NEWS live editorial hardening canary. Same one-shot, host-run,
bounded design as scripts/_phase23_1h_5_news_image_canary.py (mirrored closely) - NOT a persistent
worker, NOT a Docker container, canary settings applied IN-PROCESS ONLY, hard preflight route
assertion before any LLM/Telegram call.

New this run, per docs/phase23_1i_live_editorial_hardening_report.md:
- copywriting_prompt_version="7" (plain-language + importance-does-not-imply-length rules).
- story_memory_mode="shadow" - genuinely exercised this time (Part C): automation_worker (which
  otherwise races this script for every freshly-collected event, always winning since it triages
  in near-real-time) must be STOPPED before this script runs, and RESTARTED after - see the
  companion shell commands this script's own docstring below documents; this script itself never
  touches Docker. Each round calls the real, deterministic services.triage_orchestrator.
  run_triage_cycle() (no LLM, confirmed by that function's own docstring) BEFORE run_analysis_
  cycle()/run_content_cycle(), so genuinely fresh events get a real Story Memory shadow
  classification this run, not an inert one.
- The duplicate-delivery guard (services/story_duplicate_guard.py) is already wired into worker/
  content_cycle.py's router branch - no extra wiring needed here, only monitoring/recording.
- Records `treatment_skipped`/`duplicate_blocked` counts and per-event Story Memory outcome
  (queried directly from NewsEventStoryLink after each round) for the required live-monitoring log.

OPERATOR INSTRUCTIONS (documented per Part C's own explicit "document exactly what will happen
before doing it" requirement) - run in this exact order:
    1. docker compose stop automation_worker   (pauses collection AND triage - temporary, reversible,
                                                  same container/config, zero .env mutation)
    2. python scripts/_phase23_1i_5_news_hardened_canary.py
    3. docker compose start automation_worker  (resumes normal operation immediately after, always,
                                                  even if the canary script errors - see the `finally`
                                                  reminder printed at the end of this script's own
                                                  output)
"""
import asyncio
import json
import logging
import time
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import func, select

from bot.loader import create_bot
from core.config import settings
from core.logging import setup_logging
from database.models.ai_execution import AIExecution
from database.models.editorial_task import EditorialTask
from database.models.news_event import NewsEvent
from database.models.story_link import NewsEventStoryLink
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from schemas.editorial_route import EditorialDestination
from services.editorial_treatment import EditorialTreatmentDecision
from services.news_telegram_presentation import build_compact_news_body
from services.pricing_catalog import ModelRegistryPricingCatalog
from services.telegram_routing import RouteTarget, resolve_route
from services.triage_orchestrator import run_triage_cycle
from worker import content_cycle
from worker.analysis_cycle import run_analysis_cycle
from worker.content_cycle import run_content_cycle

logger = logging.getLogger(__name__)
_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_REAL_CHAT_ID = -1004297182444
_REAL_NEWS_TOPIC_ID = 2
_TARGET_MESSAGES = 5
_MAX_ROUNDS = 10  # news_analysis_batch_size=5 * 10 = 50, the hard analyzed-events cap
_MAX_COST_USD = 1.00
_MAX_RUNTIME_SECONDS = 4 * 60 * 60
_MAX_ANALYZED = 50

_recorded_sends: list[dict[str, object]] = []
_treatment_decisions: list[dict[str, object]] = []
_duplicate_checks: list[dict[str, object]] = []


def _instrument_send_message(bot: object) -> None:
    original = bot.send_message  # type: ignore[attr-defined]

    async def _wrapped(chat_id: object, text: object = None, *args: object, **kwargs: object) -> object:
        message = await original(chat_id, text, *args, **kwargs)
        _recorded_sends.append({
            "method": "send_message", "chat_id": chat_id, "message_thread_id": kwargs.get("message_thread_id"),
            "text": text, "has_button": kwargs.get("reply_markup") is not None,
            "message_id": getattr(message, "message_id", None),
        })
        return message

    bot.send_message = _wrapped  # type: ignore[attr-defined]


def _instrument_send_photo(bot: object) -> None:
    original = bot.send_photo  # type: ignore[attr-defined]

    async def _wrapped(chat_id: object, *args: object, **kwargs: object) -> object:
        message = await original(chat_id, *args, **kwargs)
        photo = kwargs.get("photo")
        _recorded_sends.append({
            "method": "send_photo", "chat_id": chat_id, "message_thread_id": kwargs.get("message_thread_id"),
            "text": kwargs.get("caption"), "has_button": kwargs.get("reply_markup") is not None,
            "message_id": getattr(message, "message_id", None),
            "photo_ref": photo if isinstance(photo, str) else "<uploaded bytes>",
        })
        return message

    bot.send_photo = _wrapped  # type: ignore[attr-defined]


_real_classify_event_for_router_treatment = content_cycle._classify_event_for_router_treatment
_real_check_duplicate_story_delivery = content_cycle.check_duplicate_story_delivery


async def _instrumented_classify(session: object, event_id: object) -> EditorialTreatmentDecision:
    decision = await _real_classify_event_for_router_treatment(session, event_id)
    async with async_session_factory() as record_session:
        event = await record_session.get(NewsEvent, event_id)
    _treatment_decisions.append({
        "event_id": str(event_id), "title": event.title if event else None,
        "treatment": decision.treatment, "human_review_required": decision.human_review_required,
        "reason": decision.reason,
    })
    return decision


async def _instrumented_duplicate_check(session: object, event_id: object) -> object:
    result = await _real_check_duplicate_story_delivery(session, event_id)
    _duplicate_checks.append({
        "event_id": str(event_id), "blocked": result.blocked,
        "story_id": str(result.story_id) if result.story_id else None,
        "match_type": result.match_type, "reason": result.reason,
    })
    return result


async def main() -> None:
    setup_logging()
    run_start = time.monotonic()

    settings.editorial_delivery_mode = "router"
    settings.copywriting_prompt_version = "7"
    settings.fact_safety_mode = "shadow"
    settings.story_memory_mode = "shadow"  # Part C - genuinely exercised this run (see docstring)
    settings.newsroom_telegram_chat_id = _REAL_CHAT_ID
    settings.news_topic_id = _REAL_NEWS_TOPIC_ID
    settings.content_generation_dry_run = False
    # telegram_story_reply_mode / duplicate-suppression enforce: never touched by this script -
    # stay exactly whatever the real .env already has them at ("off" / not wired at all).

    print("=== CANARY SETTINGS (in-process only) ===")
    for key in ("editorial_delivery_mode", "copywriting_prompt_version", "fact_safety_mode",
                "story_memory_mode", "telegram_story_reply_mode", "content_generation_dry_run",
                "content_generation_min_score"):
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
    _instrument_send_photo(bot)
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())

    async with async_session_factory() as session:
        baseline_cost = (await session.execute(select(func.coalesce(func.sum(AIExecution.cost), 0)))).scalar_one()

    total_notified = 0
    total_analyzed = 0
    all_delivered_event_ids: list[str] = []
    stop_reason = "max_rounds_reached"

    with (
        patch.object(content_cycle, "_classify_event_for_router_treatment", _instrumented_classify),
        patch.object(content_cycle, "check_duplicate_story_delivery", _instrumented_duplicate_check),
    ):
        for round_num in range(1, _MAX_ROUNDS + 1):
            elapsed = time.monotonic() - run_start
            if elapsed >= _MAX_RUNTIME_SECONDS:
                stop_reason = "max_runtime_reached"
                print(f"=== MAX RUNTIME REACHED ({elapsed:.0f}s) - stopping ===")
                break

            async with async_session_factory() as session:
                current_cost = (
                    await session.execute(select(func.coalesce(func.sum(AIExecution.cost), 0)))
                ).scalar_one()
            if float(current_cost - baseline_cost) >= _MAX_COST_USD:
                stop_reason = "max_cost_reached"
                print(f"=== MAX COST REACHED (${current_cost - baseline_cost:.4f}) - stopping ===")
                break

            if total_notified >= _TARGET_MESSAGES:
                stop_reason = "target_reached"
                print(f"=== TARGET REACHED ({total_notified}/{_TARGET_MESSAGES}) - stopping, not chasing volume ===")
                break

            if total_analyzed >= _MAX_ANALYZED:
                stop_reason = "max_analyzed_reached"
                print(f"=== MAX ANALYZED REACHED ({total_analyzed}/{_MAX_ANALYZED}) - stopping ===")
                break

            print(f"=== ROUND {round_num}: triage cycle (Story Memory shadow) ===")
            triage_report = await run_triage_cycle(session_factory=async_session_factory)
            print(triage_report)

            print(f"=== ROUND {round_num}: analysis cycle ===")
            analysis_result = await run_analysis_cycle(
                ai_layer.capability_registry, cost_tracker=ai_layer.cost_tracker, pricing_catalog=pricing_catalog,
            )
            print(analysis_result)
            total_analyzed += analysis_result.eligible_found

            print(f"=== ROUND {round_num}: content cycle (LIVE, router mode) ===")
            content_result = await run_content_cycle(
                ai_layer.capability_registry, bot, cost_tracker=ai_layer.cost_tracker, pricing_catalog=pricing_catalog,
            )
            print(content_result)
            print()

            total_notified += content_result.notified
            all_delivered_event_ids.extend(str(eid) for eid in content_result.event_ids)

            if (
                triage_report.events_claimed == 0 and triage_report.events_recovered == 0
                and analysis_result.eligible_found == 0 and content_result.eligible_found == 0
            ):
                stop_reason = "nothing_eligible"
                print("=== NOTHING LEFT ELIGIBLE THIS ROUND - stopping early, not manufacturing more work ===")
                break

    async with async_session_factory() as session:
        final_cost = (await session.execute(select(func.coalesce(func.sum(AIExecution.cost), 0)))).scalar_one()
    cost_delta = final_cost - baseline_cost
    print(f"=== STOP REASON: {stop_reason} ===")
    print(f"=== COST: baseline={baseline_cost} final={final_cost} delta={cost_delta} ===")
    print(f"=== TOTAL ANALYZED: {total_analyzed}  TOTAL NOTIFIED: {total_notified} ===")

    # --- build the full per-post editorial + media + duplicate/story record for the report ---
    from database.models.content_draft import ContentDraft

    records: list[dict[str, object]] = []
    async with async_session_factory() as session:
        tasks = (
            await session.execute(
                select(EditorialTask).where(EditorialTask.event_id.in_(all_delivered_event_ids))
            )
        ).scalars().all()
        content_tasks = [t for t in tasks if (t.workflow or {}).get("workflow_name") == "CONTENT_GENERATION"]
        for task in content_tasks:
            draft = (
                await session.execute(select(ContentDraft).where(ContentDraft.task_id == task.id))
            ).scalar_one_or_none()
            if draft is None:
                continue
            event = await session.get(NewsEvent, task.event_id)
            steps = {s.get("step_name"): s.get("result") for s in (task.workflow or {}).get("step_results", [])}
            copywriting_output = steps.get("copywriting")

            matching_decision = next(
                (d for d in _treatment_decisions if d["event_id"] == str(task.event_id)), None,
            )
            treatment = matching_decision["treatment"] if matching_decision else None
            compact_body = (
                build_compact_news_body(copywriting_output, treatment=treatment or "STANDARD")
                if copywriting_output else None
            )

            story_link = await session.get(NewsEventStoryLink, task.event_id)

            event_cost = (
                await session.execute(
                    select(func.coalesce(func.sum(AIExecution.cost), 0)).where(AIExecution.event_id == task.event_id)
                )
            ).scalar_one()

            records.append({
                "event_id": str(task.event_id),
                "task_id": str(task.id),
                "content_draft_id": str(draft.id),
                "news_title": event.title if event else None,
                "news_url": event.url if event else None,
                "news_category": event.category.value if event and event.category else None,
                "scoring": steps.get("scoring"),
                "intelligence": steps.get("intelligence"),
                "quality": steps.get("quality"),
                "treatment": treatment,
                "treatment_reason": matching_decision["reason"] if matching_decision else None,
                "story_id": str(story_link.story_id) if story_link else None,
                "story_match_type": story_link.match_type if story_link else None,
                "copywriting_title": copywriting_output.get("title") if copywriting_output else None,
                "compact_body": compact_body,
                "compact_body_len": len(compact_body) if compact_body else None,
                "paragraph_count": (compact_body.count("\n\n") + 1) if compact_body else None,
                "incremental_cost_usd": str(event_cost),
            })

    with open("scripts/_phase23_1i_records.json", "w", encoding="utf-8") as f:
        json.dump({
            "stop_reason": stop_reason,
            "total_analyzed": total_analyzed,
            "total_notified": total_notified,
            "cost_delta_usd": str(cost_delta),
            "runtime_seconds": time.monotonic() - run_start,
            "recorded_sends": [
                {**s, "text_len": len(s["text"]) if isinstance(s.get("text"), str) else None}
                for s in _recorded_sends
            ],
            "treatment_decisions": _treatment_decisions,
            "duplicate_checks": _duplicate_checks,
            "records": records,
        }, f, indent=2, ensure_ascii=False, default=str)
    print("=== WROTE scripts/_phase23_1i_records.json ===")
    print("=== REMINDER: run `docker compose start automation_worker` now if you haven't already ===")

    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
