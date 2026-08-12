"""Phase 23.1Q - narrow live validation canary for exactly two changes: V8.5 quote rendering and
router-mode Telegram UPDATE reply-threading (docs/session conversation, authorized live canary
following the Phase 23.1Q pre-canary checkpoint).

Reuses scripts/_phase23_1p_2h_canary.py's own proven structure verbatim (settings applied
IN-PROCESS ONLY, hard preflight route assertion, the true per-message hard delivery cap from
scripts/_canary_delivery_cap.py, real production-cadence multi-stage scheduling, same runtime/
cost/delivery caps) - every runtime protection from that canary carries over unchanged. Three
differences only:

1. `settings.telegram_story_reply_mode = "enforce"` (IN-PROCESS ONLY, restored on exit) - so a
   confirmed story_update draft with a resolvable root actually sends as a real Telegram reply
   this time, instead of always as a standalone post (Phase 23.1P deliberately left this at "off").
2. `settings.quote_telegram_rendering_mode = "enforce"` (IN-PROCESS ONLY, restored on exit) - so a
   verified quote actually reaches the delivered card, instead of only being looked-up-and-logged.
3. Two OBSERVATION-ONLY instrumentation wrappers (no production code touched): one around
   worker.content_cycle.render_v81_news_card_html to record, per draft, whether a quote was
   available/rendered/dedup-suppressed/budget-suppressed (re-deriving the exact same pure checks
   the real function already uses - services.news_telegram_presentation._is_distinct(),
   services.quote_budget.fits_within_budget()/select_quote_or_omit() - never a second, divergent
   rule); one extending the existing bot.send_message/send_photo instrumentation to also record
   reply_to_message_id. Neither wrapper changes real behavior - both call the real underlying
   function/method unchanged and only observe its inputs/outputs.

`story_memory_mode = "shadow"` is reused unchanged from Phase 23.1P's own precedent (not a new
decision this phase) - a strict prerequisite for telegram_story_reply_mode=enforce to have
anything to act on at all (no ContentDraftStoryLink is ever created while story_memory_mode ==
"off"), not a change to Story Memory's own matching/scoring/thresholds.
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
_MAX_RUNTIME_SECONDS = 2 * 60 * 60

_TICK_SECONDS = 30

_recorded_sends: list[dict[str, object]] = []
_stage_log: list[dict[str, object]] = []
_errors_log: list[dict[str, object]] = []
_quote_observations: list[dict[str, object]] = []


def _instrument_send_message(bot: object) -> None:
    original = bot.send_message  # type: ignore[attr-defined]

    async def _wrapped(chat_id: object, text: object = None, *args: object, **kwargs: object) -> object:
        message = await original(chat_id, text, *args, **kwargs)
        _recorded_sends.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "method": "send_message", "chat_id": chat_id, "message_thread_id": kwargs.get("message_thread_id"),
            "text": text, "has_button": kwargs.get("reply_markup") is not None,
            "reply_to_message_id": kwargs.get("reply_to_message_id"),
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
            "ts": datetime.now(timezone.utc).isoformat(),
            "method": "send_photo", "chat_id": chat_id, "message_thread_id": kwargs.get("message_thread_id"),
            "text": kwargs.get("caption"), "has_button": kwargs.get("reply_markup") is not None,
            "reply_to_message_id": kwargs.get("reply_to_message_id"),
            "message_id": getattr(message, "message_id", None),
            "photo_ref": photo if isinstance(photo, str) else "<uploaded bytes>",
        })
        return message

    bot.send_photo = _wrapped  # type: ignore[attr-defined]


def _instrument_quote_rendering() -> None:
    """OBSERVATION ONLY - calls the real, unmodified render_v81_news_card_html() and records
    whether/why a quote did or did not appear, by re-deriving the exact same pure checks the real
    function already uses internally (never a second, divergent rule - see this module's own
    docstring)."""
    import worker.content_cycle as content_cycle_module
    from services.news_telegram_presentation import (
        _OPTIONAL_REDUNDANCY_THRESHOLD,
        _is_distinct,
        build_v81_news_body,
    )
    from services.quote_budget import fits_within_budget, select_quote_or_omit

    original_render = content_cycle_module.render_v81_news_card_html

    def _wrapped(copywriting_output: dict, *, treatment: str = "standard",
                 include_ninja_pulse_footer: bool = False, quote_text: str | None = None,
                 quote_speaker: str | None = None) -> str:
        html = original_render(
            copywriting_output, treatment=treatment, include_ninja_pulse_footer=include_ninja_pulse_footer,
            quote_text=quote_text, quote_speaker=quote_speaker,
        )
        rendered_in_html = "<blockquote>" in html
        dedup_suppressed = False
        budget_suppressed = False
        if quote_text and not rendered_in_html:
            body = build_v81_news_body(copywriting_output, treatment=treatment)
            distinct = _is_distinct(quote_text, [body] if body else [], threshold=_OPTIONAL_REDUNDANCY_THRESHOLD)
            if not distinct:
                dedup_suppressed = True
            else:
                # Re-derive the exact same budget check render_v81_news_card_html() itself uses.
                non_quote_len = len(html.encode("utf-16-le")) // 2
                candidate_quote_block_len = len((quote_text + (quote_speaker or "")).encode("utf-16-le")) // 2
                fits = fits_within_budget(
                    non_quote_blocks_length=non_quote_len, quote_block_length=candidate_quote_block_len, limit=4096,
                )
                selected, _ = select_quote_or_omit(quote_text, quote_speaker, fits=fits)
                if selected is None:
                    budget_suppressed = True
        _quote_observations.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "quote_available": quote_text is not None,
            "quote_text": quote_text, "quote_speaker": quote_speaker,
            "rendered_in_html": rendered_in_html,
            "dedup_suppressed": dedup_suppressed, "budget_suppressed": budget_suppressed,
            "html_utf16_length": len(html.encode("utf-16-le")) // 2,
        })
        return html

    content_cycle_module.render_v81_news_card_html = _wrapped  # type: ignore[assignment]


def _dump_state(path: str, *, extra: dict[str, object]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            **extra, "recorded_sends": _recorded_sends, "stage_log": _stage_log,
            "errors_log": _errors_log, "quote_observations": _quote_observations,
        }, f, indent=2, ensure_ascii=False, default=str)


async def main() -> None:
    setup_logging()
    run_start_wall = datetime.now(timezone.utc)
    run_start_mono = time.monotonic()

    original_story_memory_mode = settings.story_memory_mode
    original_telegram_story_reply_mode = settings.telegram_story_reply_mode
    original_quote_telegram_rendering_mode = settings.quote_telegram_rendering_mode
    settings.editorial_delivery_mode = "router"
    # NEWS Output Stability Fix (Case F): v8.6 is now the accepted candidate, never actually
    # exercised by a real delivery before this activation - see docs/news_output_stability_
    # forensic_report.md §7/§13 item 2.
    settings.copywriting_prompt_version = "8.6"
    settings.content_generation_dry_run = False
    settings.story_memory_mode = "shadow"  # IN-PROCESS ONLY - prerequisite for reply-threading to have any data; restored below
    settings.telegram_story_reply_mode = "enforce"  # IN-PROCESS ONLY - the feature under validation; restored below
    settings.quote_telegram_rendering_mode = "enforce"  # IN-PROCESS ONLY - the feature under validation; restored below
    settings.newsroom_telegram_chat_id = _REAL_CHAT_ID
    settings.news_topic_id = _REAL_NEWS_TOPIC_ID

    print("=== CANARY_START (UTC) ===", run_start_wall.isoformat())
    print("=== CANARY SETTINGS (in-process only) ===")
    for key in ("editorial_delivery_mode", "copywriting_prompt_version", "fact_safety_mode",
                "story_memory_mode", "telegram_story_reply_mode", "quote_telegram_rendering_mode",
                "article_acquisition_mode", "content_generation_dry_run", "content_generation_min_score",
                "news_collection_interval_seconds", "news_analysis_poll_interval_seconds",
                "content_generation_poll_interval_seconds"):
        print(f"{key} = {getattr(settings, key)}")
    print(f"original story_memory_mode (will be restored on exit) = {original_story_memory_mode!r}")
    print(f"original telegram_story_reply_mode (will be restored on exit) = {original_telegram_story_reply_mode!r}")
    print(f"original quote_telegram_rendering_mode (will be restored on exit) = {original_quote_telegram_rendering_mode!r}")
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
        _instrument_quote_rendering()

        cap = HardDeliveryCap(max_deliveries=_MAX_DELIVERIES_HARD_CAP)
        wrap_bot_with_hard_cap(bot, cap)
        print(f"=== HARD DELIVERY CAP ARMED: max_deliveries={cap.max_deliveries} ===")
        print(f"=== MAX ANALYZED CAP: {_MAX_ANALYZED} ===")
        print(f"=== COST CAP: ${_MAX_COST_USD:.2f} ===")
        print(f"=== RUNTIME CAP: {_MAX_RUNTIME_SECONDS}s (2 hours) - the primary boundary ===")
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
                print(f"=== 2-HOUR RUNTIME REACHED ({elapsed:.0f}s) - stopping ===")
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
                "scripts/_phase23_1q_2h_canary_state.json",
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
        print(f"=== QUOTE OBSERVATIONS: {len(_quote_observations)} ===")
        assert cap.attempted <= _MAX_DELIVERIES_HARD_CAP, f"HARD CAP VIOLATION: {cap.attempted} attempts > {_MAX_DELIVERIES_HARD_CAP}"
        assert all(s["chat_id"] == _REAL_CHAT_ID and s["message_thread_id"] == _REAL_NEWS_TOPIC_ID for s in _recorded_sends), (
            "DESTINATION VIOLATION: a send targeted somewhere other than the approved NEWS destination"
        )

        _dump_state(
            "scripts/_phase23_1q_2h_canary_state.json",
            extra={
                "canary_start_utc": run_start_wall.isoformat(), "canary_end_utc": run_end_wall.isoformat(),
                "tick_num": tick_num, "elapsed_s": time.monotonic() - run_start_mono,
                "cost_delta_usd": str(cost_delta), "cap_attempted": cap.attempted, "cap_max": cap.max_deliveries,
                "total_analyzed": total_analyzed, "max_analyzed": _MAX_ANALYZED, "stop_reason": stop_reason,
            },
        )
        print("=== WROTE scripts/_phase23_1q_2h_canary_state.json ===")

        await bot.session.close()
    finally:
        settings.story_memory_mode = original_story_memory_mode
        settings.telegram_story_reply_mode = original_telegram_story_reply_mode
        settings.quote_telegram_rendering_mode = original_quote_telegram_rendering_mode
        print(f"=== story_memory_mode restored to {original_story_memory_mode!r} (in-process only, never touched .env) ===")
        print(f"=== telegram_story_reply_mode restored to {original_telegram_story_reply_mode!r} (in-process only, never touched .env) ===")
        print(f"=== quote_telegram_rendering_mode restored to {original_quote_telegram_rendering_mode!r} (in-process only, never touched .env) ===")


if __name__ == "__main__":
    asyncio.run(main())
