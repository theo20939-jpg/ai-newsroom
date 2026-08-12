"""Phase 23.1Q - Media Roadmap Recovery, video shadow activation. Bounded, discovery-only video
canary: `video_discovery_mode="shadow"` (IN-PROCESS ONLY, restored on exit), everything else
byte-identical to scripts/_phase23_1q_2h_canary.py's own already-authorized configuration (Media
Wiring Checkpoint 1's own text/quote/footer/reply-threading/multi-image behavior, unchanged, not
re-reviewed here). No change to media ranking, no change to Telegram sending, no video delivery -
video_discovery_mode="shadow" only causes services/article_acquisition.py::get_or_acquire()'s
already-existing M10 persistence hook to write discovered NativeVideoHint/VideoValidation results
into `content_draft_media_items` (now that migration f2654fa00185 is applied) for post-run,
read-only analysis. Nothing reads that table for delivery purposes anywhere in this run.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from bot.loader import create_bot
from core.config import settings
from core.logging import setup_logging
from database.models.ai_execution import AIExecution
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from schemas.editorial_route import EditorialDestination
from scripts._canary_delivery_cap import HardDeliveryCap, wrap_bot_with_hard_cap
from services.pricing_catalog import ModelRegistryPricingCatalog
from services.telegram_routing import RouteTarget, resolve_route
from worker.analysis_cycle import run_analysis_cycle
from worker.content_cycle import run_content_cycle
from worker.cycle import run_automation_cycle

logger = logging.getLogger(__name__)
_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_REAL_CHAT_ID = -1004297182444
_REAL_NEWS_TOPIC_ID = 2

_MAX_DELIVERIES_HARD_CAP = 20
_MAX_ANALYZED = 100
_MAX_COST_USD = 2.00
# Video URL Classification Checkpoint validation run: bounded ~45 minutes - a short, focused
# re-validation of the classify_video_url() fix's real-world effect, not another
# publication-volume test. 30-60 minutes was explicitly authorized as sufficient if the sample is
# meaningful.
_MAX_RUNTIME_SECONDS = 45 * 60

_TICK_SECONDS = 30

_recorded_sends: list[dict[str, object]] = []
_stage_log: list[dict[str, object]] = []
_errors_log: list[dict[str, object]] = []


def _instrument_send_message(bot: object) -> None:
    original = bot.send_message  # type: ignore[attr-defined]

    async def _wrapped(chat_id: object, text: object = None, *args: object, **kwargs: object) -> object:
        message = await original(chat_id, text, *args, **kwargs)
        _recorded_sends.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "method": "send_message", "chat_id": chat_id, "message_thread_id": kwargs.get("message_thread_id"),
            "reply_to_message_id": kwargs.get("reply_to_message_id"),
            "message_id": getattr(message, "message_id", None),
        })
        return message

    bot.send_message = _wrapped  # type: ignore[attr-defined]


def _instrument_send_photo(bot: object) -> None:
    original = bot.send_photo  # type: ignore[attr-defined]

    async def _wrapped(chat_id: object, *args: object, **kwargs: object) -> object:
        message = await original(chat_id, *args, **kwargs)
        _recorded_sends.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "method": "send_photo", "chat_id": chat_id, "message_thread_id": kwargs.get("message_thread_id"),
            "reply_to_message_id": kwargs.get("reply_to_message_id"),
            "message_id": getattr(message, "message_id", None),
        })
        return message

    bot.send_photo = _wrapped  # type: ignore[attr-defined]


def _instrument_send_media_group(bot: object) -> None:
    """Observation only - Step 1's already-authorized multi-image wiring will naturally run
    during this canary too (it is unconditional in content_cycle.py now, not gated by any new
    setting this canary touches) - recorded here purely so the video-shadow checkpoint can report
    "how many stories also had usable images" honestly, never to change its behavior."""
    original = bot.send_media_group  # type: ignore[attr-defined]

    async def _wrapped(chat_id: object, *args: object, **kwargs: object) -> object:
        messages = await original(chat_id, *args, **kwargs)
        media = kwargs.get("media") or []
        _recorded_sends.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "method": "send_media_group", "chat_id": chat_id, "message_thread_id": kwargs.get("message_thread_id"),
            "reply_to_message_id": kwargs.get("reply_to_message_id"), "item_count": len(media),
            "message_id": getattr(messages[0], "message_id", None) if messages else None,
        })
        return messages

    bot.send_media_group = _wrapped  # type: ignore[attr-defined]


def _dump_state(path: str, *, extra: dict[str, object]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            **extra, "recorded_sends": _recorded_sends, "stage_log": _stage_log, "errors_log": _errors_log,
        }, f, indent=2, ensure_ascii=False, default=str)


async def main() -> None:
    setup_logging()
    run_start_wall = datetime.now(timezone.utc)
    run_start_mono = time.monotonic()

    original_story_memory_mode = settings.story_memory_mode
    original_telegram_story_reply_mode = settings.telegram_story_reply_mode
    original_quote_telegram_rendering_mode = settings.quote_telegram_rendering_mode
    original_video_discovery_mode = settings.video_discovery_mode
    settings.editorial_delivery_mode = "router"
    # NEWS Output Stability Fix (Case F): v8.6 is now the accepted candidate for the NEXT
    # validation - v8.5 was never actually exercised by a real delivery before this activation,
    # and this session's own forensic report found the uncertainty-filler pattern v8.6 exists to
    # fix in 31% of real deliveries, all generated under v8.5 (docs/news_output_stability_
    # forensic_report.md §7/§13 item 2). Superseded comment ("not re-reviewing v8.6 live here")
    # applied to the PRIOR, narrower video-classification validation phase, not this one.
    settings.copywriting_prompt_version = "8.6"
    settings.content_generation_dry_run = False
    settings.story_memory_mode = "shadow"
    settings.telegram_story_reply_mode = "enforce"
    settings.quote_telegram_rendering_mode = "enforce"
    settings.video_discovery_mode = "shadow"  # IN-PROCESS ONLY - the one new thing this canary adds; restored below
    settings.newsroom_telegram_chat_id = _REAL_CHAT_ID
    settings.news_topic_id = _REAL_NEWS_TOPIC_ID

    print("=== CANARY_START (UTC) ===", run_start_wall.isoformat())
    print("=== CANARY SETTINGS (in-process only) ===")
    for key in ("editorial_delivery_mode", "copywriting_prompt_version", "fact_safety_mode",
                "story_memory_mode", "telegram_story_reply_mode", "quote_telegram_rendering_mode",
                "video_discovery_mode", "article_acquisition_mode", "rich_media_mode",
                "content_generation_dry_run", "content_generation_min_score",
                "news_collection_interval_seconds", "news_analysis_poll_interval_seconds",
                "content_generation_poll_interval_seconds"):
        print(f"{key} = {getattr(settings, key)}")
    print(f"original video_discovery_mode (will be restored on exit) = {original_video_discovery_mode!r}")
    print("=== rich_media_mode stays 'off' (unchanged) - no video delivery wiring exists yet, this run is discovery-only ===")
    print()

    route = resolve_route(EditorialDestination.NEWS)
    print(f"=== RESOLVED NEWS ROUTE: {route} ===")
    assert route == RouteTarget(chat_id=_REAL_CHAT_ID, topic_id=_REAL_NEWS_TOPIC_ID), (
        f"REFUSING TO PROCEED - resolved route {route} does not match the real canary target"
    )
    print()

    try:
        prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
        ai_layer = assemble_ai_integration_layer(settings, prompt_repository)
        bot = create_bot()
        _instrument_send_message(bot)
        _instrument_send_photo(bot)
        _instrument_send_media_group(bot)

        cap = HardDeliveryCap(max_deliveries=_MAX_DELIVERIES_HARD_CAP)
        wrap_bot_with_hard_cap(bot, cap)
        print(f"=== HARD DELIVERY CAP ARMED: max_deliveries={cap.max_deliveries} ===")
        print(f"=== MAX ANALYZED CAP: {_MAX_ANALYZED} ===")
        print(f"=== COST CAP: ${_MAX_COST_USD:.2f} ===")
        print(f"=== RUNTIME CAP: {_MAX_RUNTIME_SECONDS}s (~45 minutes) - the primary boundary ===")
        print()

        pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())

        async with async_session_factory() as session:
            baseline_cost = (await session.execute(select(func.coalesce(func.sum(AIExecution.cost), 0)))).scalar_one()

        stop_reason = "runtime_reached"
        total_analyzed = 0
        last_collection_mono = -1e18
        last_analysis_mono = -1e18
        last_content_mono = -1e18
        tick_num = 0

        while True:
            tick_num += 1
            elapsed = time.monotonic() - run_start_mono
            if elapsed >= _MAX_RUNTIME_SECONDS:
                stop_reason = "runtime_reached"
                print(f"=== RUNTIME CAP REACHED ({elapsed:.0f}s) - stopping ===")
                break

            async with async_session_factory() as session:
                current_cost = (await session.execute(select(func.coalesce(func.sum(AIExecution.cost), 0)))).scalar_one()
            cost_delta = float(current_cost - baseline_cost)
            if cost_delta >= _MAX_COST_USD:
                stop_reason = "cost_cap_reached"
                print(f"=== COST CAP REACHED (${cost_delta:.4f}) - stopping paid processing ===")
                break

            if cap.remaining <= 0:
                stop_reason = "hard_delivery_cap_exhausted"
                print(f"=== HARD DELIVERY CAP EXHAUSTED ({cap.attempted}/{cap.max_deliveries}) - stopping Telegram delivery ===")
                break

            if total_analyzed >= _MAX_ANALYZED:
                stop_reason = "max_analyzed_reached"
                print(f"=== MAX ANALYZED REACHED ({total_analyzed}/{_MAX_ANALYZED}) - stopping ===")
                break

            now_mono = time.monotonic()

            if now_mono - last_collection_mono >= settings.news_collection_interval_seconds:
                try:
                    print(f"=== TICK {tick_num} ({elapsed:.0f}s elapsed): COLLECTION + TRIAGE ===")
                    result = await run_automation_cycle()
                    print(result)
                    _stage_log.append({
                        "ts": datetime.now(timezone.utc).isoformat(), "stage": "automation_cycle",
                        "elapsed_s": elapsed, "collection": vars(result.collection), "triage": vars(result.triage),
                    })
                except Exception as exc:
                    logger.exception("canary_automation_cycle_failed")
                    _errors_log.append({"ts": datetime.now(timezone.utc).isoformat(), "stage": "automation_cycle", "error": repr(exc)})
                last_collection_mono = now_mono

            if now_mono - last_analysis_mono >= settings.news_analysis_poll_interval_seconds:
                if total_analyzed >= _MAX_ANALYZED:
                    print("=== SKIPPING ANALYSIS CYCLE - max analyzed cap already reached ===")
                else:
                    try:
                        print(f"=== TICK {tick_num} ({elapsed:.0f}s elapsed): ANALYSIS (analyzed so far={total_analyzed}) ===")
                        analysis_result = await run_analysis_cycle(
                            ai_layer.capability_registry, cost_tracker=ai_layer.cost_tracker, pricing_catalog=pricing_catalog,
                        )
                        print(analysis_result)
                        total_analyzed += analysis_result.eligible_found
                        _stage_log.append({
                            "ts": datetime.now(timezone.utc).isoformat(), "stage": "analysis_cycle",
                            "elapsed_s": elapsed, "result": vars(analysis_result), "total_analyzed": total_analyzed,
                        })
                    except Exception as exc:
                        logger.exception("canary_analysis_cycle_failed")
                        _errors_log.append({"ts": datetime.now(timezone.utc).isoformat(), "stage": "analysis_cycle", "error": repr(exc)})
                last_analysis_mono = now_mono

            if now_mono - last_content_mono >= settings.content_generation_poll_interval_seconds:
                if cap.remaining <= 0:
                    print("=== SKIPPING CONTENT CYCLE - hard delivery cap already exhausted ===")
                else:
                    try:
                        print(f"=== TICK {tick_num} ({elapsed:.0f}s elapsed): CONTENT GENERATION (cap remaining={cap.remaining}) ===")
                        content_result = await run_content_cycle(
                            ai_layer.capability_registry, bot, cost_tracker=ai_layer.cost_tracker, pricing_catalog=pricing_catalog,
                        )
                        print(content_result)
                        _stage_log.append({
                            "ts": datetime.now(timezone.utc).isoformat(), "stage": "content_cycle",
                            "elapsed_s": elapsed, "result": vars(content_result),
                        })
                    except Exception as exc:
                        logger.exception("canary_content_cycle_failed")
                        _errors_log.append({"ts": datetime.now(timezone.utc).isoformat(), "stage": "content_cycle", "error": repr(exc)})
                last_content_mono = now_mono

            _dump_state(
                "scripts/_phase23_1q_video_shadow_canary_state.json",
                extra={
                    "canary_start_utc": run_start_wall.isoformat(), "tick_num": tick_num, "elapsed_s": elapsed,
                    "cost_delta_usd": str(cost_delta), "cap_attempted": cap.attempted, "cap_max": cap.max_deliveries,
                    "total_analyzed": total_analyzed, "max_analyzed": _MAX_ANALYZED, "stop_reason": None,
                },
            )
            await asyncio.sleep(_TICK_SECONDS)

        run_end_wall = datetime.now(timezone.utc)
        async with async_session_factory() as session:
            final_cost = (await session.execute(select(func.coalesce(func.sum(AIExecution.cost), 0)))).scalar_one()
        cost_delta = float(final_cost - baseline_cost)

        print(f"=== CANARY_END (UTC) === {run_end_wall.isoformat()}")
        print(f"=== STOP REASON: {stop_reason} ===")
        print(f"=== FINAL COST: baseline={baseline_cost} final={final_cost} delta=${cost_delta:.4f} ===")
        print(f"=== TELEGRAM SENDS: {len(_recorded_sends)}  CAP ATTEMPTED: {cap.attempted}/{cap.max_deliveries} ===")
        print(f"=== TOTAL ANALYZED: {total_analyzed}/{_MAX_ANALYZED} ===")
        assert cap.attempted <= _MAX_DELIVERIES_HARD_CAP, f"HARD CAP VIOLATION: {cap.attempted} attempts > {_MAX_DELIVERIES_HARD_CAP}"
        assert all(s["chat_id"] == _REAL_CHAT_ID and s["message_thread_id"] == _REAL_NEWS_TOPIC_ID for s in _recorded_sends), (
            "DESTINATION VIOLATION: a send targeted somewhere other than the approved NEWS destination"
        )

        _dump_state(
            "scripts/_phase23_1q_video_shadow_canary_state.json",
            extra={
                "canary_start_utc": run_start_wall.isoformat(), "canary_end_utc": run_end_wall.isoformat(),
                "tick_num": tick_num, "elapsed_s": time.monotonic() - run_start_mono,
                "cost_delta_usd": str(cost_delta), "cap_attempted": cap.attempted, "cap_max": cap.max_deliveries,
                "total_analyzed": total_analyzed, "max_analyzed": _MAX_ANALYZED, "stop_reason": stop_reason,
            },
        )
        print("=== WROTE scripts/_phase23_1q_video_shadow_canary_state.json ===")

        await bot.session.close()
    finally:
        settings.story_memory_mode = original_story_memory_mode
        settings.telegram_story_reply_mode = original_telegram_story_reply_mode
        settings.quote_telegram_rendering_mode = original_quote_telegram_rendering_mode
        settings.video_discovery_mode = original_video_discovery_mode
        print(f"=== video_discovery_mode restored to {original_video_discovery_mode!r} (in-process only, never touched .env) ===")
        print(f"=== story_memory_mode restored to {original_story_memory_mode!r} (in-process only, never touched .env) ===")
        print(f"=== telegram_story_reply_mode restored to {original_telegram_story_reply_mode!r} (in-process only, never touched .env) ===")
        print(f"=== quote_telegram_rendering_mode restored to {original_quote_telegram_rendering_mode!r} (in-process only, never touched .env) ===")


if __name__ == "__main__":
    asyncio.run(main())
