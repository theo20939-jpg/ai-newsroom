"""Phase 23.1O - the FINAL LOCAL NEWS ACCEPTANCE CANARY before Phase 23.2 VPS deployment
(docs/phase23_1o_final_2h_combined_news_canary_report.md).

Unlike every prior canary (fixed N-message target, single round-loop), this observes the accepted
NEWS pipeline naturally for a fixed WALL-CLOCK duration (2 hours) with NO message-count target -
only a true, per-message emergency hard cap (Phase 23.1L's own proven `HardDeliveryCap`, reused
verbatim, never redesigned) as a runaway circuit breaker, plus a cost cap, both checked at the
real send/cost boundary, never per-round.

Three real, already-production-configured cadences (worker/main.py::news_collection_interval_
seconds, worker/analysis_main.py::news_analysis_poll_interval_seconds, worker/content_main.py::
content_generation_poll_interval_seconds - this environment's own real .env/config values, not
invented) are ticked independently inside one process via a single fine-grained scheduler loop,
so COLLECTION -> TRIAGE -> ANALYSIS -> CONTENT GENERATION -> EDITORIAL TREATMENT -> PRESENTATION ->
IMAGE SELECTION -> TELEGRAM NEWS all run at their real configured pace, letting genuinely new
incoming stories enter and move through during the window - never a one-shot pool-drain.

Settings are overridden IN-PROCESS ONLY (never .env) exactly like every prior canary:
editorial_delivery_mode="router", copywriting_prompt_version="8.5" (already the accepted frozen
version - never a new version), newsroom_telegram_chat_id/news_topic_id hardcoded to the one
approved NEWS destination. fact_safety_mode and story_memory_mode are read, logged, and left
completely untouched (whatever the real .env already has), per the phase brief's explicit
"do not enable enforce modes" / "use the accepted configuration only" instruction.

This script owns only what must be live-correct under time pressure: safety (hard cap, cost cap,
destination proof, natural real-interval pacing) and capturing every real Telegram send. The rich
observational analysis (every candidate, skip reasons, duplicate/image/fact-safety inspection) is
deliberately done afterward by a separate, read-only, DB-querying script
(scripts/_phase23_1o_post_run_analysis.py) against the real, already-persisted data this run
writes - safer than trying to instrument everything live.
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

_MAX_DELIVERIES_HARD_CAP = 20  # emergency circuit breaker only, NEVER a publication target
_MAX_COST_USD = 2.00
_MAX_RUNTIME_SECONDS = 2 * 60 * 60  # the primary boundary

_TICK_SECONDS = 30  # scheduler resolution only - real per-stage cadence is the settings below

_recorded_sends: list[dict[str, object]] = []
_stage_log: list[dict[str, object]] = []  # every collection/analysis/content cycle result, timestamped
_errors_log: list[dict[str, object]] = []


def _instrument_send_message(bot: object) -> None:
    original = bot.send_message  # type: ignore[attr-defined]

    async def _wrapped(chat_id: object, text: object = None, *args: object, **kwargs: object) -> object:
        message = await original(chat_id, text, *args, **kwargs)
        _recorded_sends.append({
            "ts": datetime.now(timezone.utc).isoformat(),
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
            "ts": datetime.now(timezone.utc).isoformat(),
            "method": "send_photo", "chat_id": chat_id, "message_thread_id": kwargs.get("message_thread_id"),
            "text": kwargs.get("caption"), "has_button": kwargs.get("reply_markup") is not None,
            "message_id": getattr(message, "message_id", None),
            "photo_ref": photo if isinstance(photo, str) else "<uploaded bytes>",
        })
        return message

    bot.send_photo = _wrapped  # type: ignore[attr-defined]


def _dump_state(path: str, *, extra: dict[str, object]) -> None:
    """Written after every stage - so partial results survive if this process is ever
    interrupted before the full 2 hours complete."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump({**extra, "recorded_sends": _recorded_sends, "stage_log": _stage_log,
                    "errors_log": _errors_log}, f, indent=2, ensure_ascii=False, default=str)


async def main() -> None:
    setup_logging()
    run_start_wall = datetime.now(timezone.utc)
    run_start_mono = time.monotonic()

    settings.editorial_delivery_mode = "router"
    # NEWS Output Stability Fix (Case F): the accepted candidate is now v8.6 - v8.5's own live
    # traffic (this session's own forensic report) showed the uncertainty-filler pattern v8.6
    # exists specifically to fix; v8.6 was never actually exercised by any real delivery before
    # this activation. This is the current production candidate this script's own docstring
    # already describes itself as - not historical replay tooling pinned to a specific version.
    settings.copywriting_prompt_version = "8.6"
    settings.newsroom_telegram_chat_id = _REAL_CHAT_ID
    settings.news_topic_id = _REAL_NEWS_TOPIC_ID
    settings.content_generation_dry_run = False
    # fact_safety_mode / story_memory_mode: NOT set here - left exactly as the real .env has them.

    print("=== CANARY_START (UTC) ===", run_start_wall.isoformat())
    print("=== CANARY SETTINGS (in-process only) ===")
    for key in ("editorial_delivery_mode", "copywriting_prompt_version", "fact_safety_mode",
                "story_memory_mode", "content_generation_dry_run", "content_generation_min_score",
                "news_collection_interval_seconds", "news_analysis_poll_interval_seconds",
                "content_generation_poll_interval_seconds", "news_analysis_freshness_cutoff_hours",
                "content_generation_freshness_cutoff_hours", "news_analysis_batch_size",
                "content_generation_batch_size", "content_generation_scan_limit"):
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

    cap = HardDeliveryCap(max_deliveries=_MAX_DELIVERIES_HARD_CAP)
    wrap_bot_with_hard_cap(bot, cap)
    print(f"=== HARD DELIVERY CAP ARMED (emergency circuit breaker, not a target): max_deliveries={cap.max_deliveries} ===")
    print(f"=== COST CAP: ${_MAX_COST_USD:.2f} ===")
    print(f"=== RUNTIME CAP: {_MAX_RUNTIME_SECONDS}s (2 hours) - the primary boundary ===")
    print()

    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())

    async with async_session_factory() as session:
        baseline_cost = (await session.execute(select(func.coalesce(func.sum(AIExecution.cost), 0)))).scalar_one()

    stop_reason = "runtime_reached"
    last_collection_mono = -1e18  # force an immediate first run of every stage
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
            except Exception as exc:  # matches worker/main.py's own "log and continue" contract
                logger.exception("canary_automation_cycle_failed")
                _errors_log.append({"ts": datetime.now(timezone.utc).isoformat(), "stage": "automation_cycle", "error": repr(exc)})
            last_collection_mono = now_mono

        if now_mono - last_analysis_mono >= settings.news_analysis_poll_interval_seconds:
            try:
                print(f"=== TICK {tick_num} ({elapsed:.0f}s elapsed): ANALYSIS ===")
                analysis_result = await run_analysis_cycle(
                    ai_layer.capability_registry, cost_tracker=ai_layer.cost_tracker, pricing_catalog=pricing_catalog,
                )
                print(analysis_result)
                _stage_log.append({
                    "ts": datetime.now(timezone.utc).isoformat(), "stage": "analysis_cycle",
                    "elapsed_s": elapsed, "result": vars(analysis_result),
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
            "scripts/_phase23_1o_2h_canary_state.json",
            extra={
                "canary_start_utc": run_start_wall.isoformat(), "tick_num": tick_num, "elapsed_s": elapsed,
                "cost_delta_usd": str(cost_delta), "cap_attempted": cap.attempted, "cap_max": cap.max_deliveries,
                "stop_reason": None,
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
    assert cap.attempted <= _MAX_DELIVERIES_HARD_CAP, f"HARD CAP VIOLATION: {cap.attempted} attempts > {_MAX_DELIVERIES_HARD_CAP}"
    assert all(s["chat_id"] == _REAL_CHAT_ID and s["message_thread_id"] == _REAL_NEWS_TOPIC_ID for s in _recorded_sends), (
        "DESTINATION VIOLATION: a send targeted somewhere other than the approved NEWS destination"
    )

    _dump_state(
        "scripts/_phase23_1o_2h_canary_state.json",
        extra={
            "canary_start_utc": run_start_wall.isoformat(), "canary_end_utc": run_end_wall.isoformat(),
            "tick_num": tick_num, "elapsed_s": time.monotonic() - run_start_mono,
            "cost_delta_usd": str(cost_delta), "cap_attempted": cap.attempted, "cap_max": cap.max_deliveries,
            "stop_reason": stop_reason,
        },
    )
    print("=== WROTE scripts/_phase23_1o_2h_canary_state.json ===")

    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
