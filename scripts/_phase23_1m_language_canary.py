"""Phase 23.1M Part K - the bounded LIVE LANGUAGE canary, run only after the golden replay showed a
clear naturalness improvement (docs/phase23_1m_russian_editorial_naturalness_report.md).

Reuses scripts/_phase23_1l_final_local_acceptance_canary.py's own structure verbatim (settings
applied IN-PROCESS ONLY, hard preflight route assertion, the true per-message hard delivery cap
from scripts/_canary_delivery_cap.py, provenance logging, the Part N duplicate tripwire) - every
runtime protection from Phase 23.1L carries over unchanged. The only differences this phase:
copywriting_prompt_version="8.3" (the new, frozen-after-this-phase Russian-naturalness version;
v8.2 stays untouched), and tighter bounds (max 30 analyzed, max 3 deliveries HARD LIMIT, max
$0.50). story_memory_mode is NOT touched - stays exactly whatever the real .env has ("off"),
preserving the current approved state per the phase brief's explicit instruction.
"""
import asyncio
import json
import logging
import re
import time
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

from sqlalchemy import func, select

from bot.loader import create_bot
from core.config import settings
from core.logging import setup_logging
from database.models.ai_execution import AIExecution
from database.models.content_draft import ContentDraft
from database.models.editorial_task import EditorialTask
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.models.story_link import NewsEventStoryLink
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from schemas.editorial_route import EditorialDestination
from scripts._canary_delivery_cap import HardDeliveryCap, wrap_bot_with_hard_cap
from services.editorial_treatment import EditorialTreatmentDecision
from services.image_persistence import get_editorial_image_candidates
from services.news_telegram_presentation import is_v8_family_output, render_v81_news_card_html
from services.pricing_catalog import ModelRegistryPricingCatalog
from services.telegram_routing import RouteTarget, resolve_route
from worker import content_cycle
from worker.analysis_cycle import run_analysis_cycle
from worker.content_cycle import run_content_cycle

logger = logging.getLogger(__name__)
_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_REAL_CHAT_ID = -1004297182444
_REAL_NEWS_TOPIC_ID = 2
_TARGET_MESSAGES_MIN = 1
_TARGET_MESSAGES_MAX = 3
_MAX_ROUNDS = 10
_MAX_COST_USD = 0.50
_MAX_RUNTIME_SECONDS = 4 * 60 * 60
_MAX_ANALYZED = 30

_recorded_sends: list[dict[str, object]] = []
_treatment_decisions: list[dict[str, object]] = []
_seen_titles: list[tuple[str, str]] = []  # (event_id, normalized_title) - Part N tripwire
_duplicate_stop_triggered: dict[str, object] | None = None

_WORD_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9]+")


def _normalize_title(title: str) -> set[str]:
    return set(_WORD_RE.findall(title.lower()))


def _check_duplicate_tripwire(event_id: str, title: str) -> dict[str, object] | None:
    """Part N: a simple, transparent, canary-only observational check - NOT Story Memory, NOT a
    general matcher. Jaccard word overlap >=0.75 against anything already processed this run is
    treated as "obviously identical". Deliberately conservative (high threshold) so it only ever
    fires on genuinely blatant duplicates, never a false-positive block on merely-related news."""
    new_words = _normalize_title(title)
    for seen_event_id, seen_title_normalized_str in _seen_titles:
        seen_words = set(seen_title_normalized_str.split("\x1f"))
        if not new_words or not seen_words:
            continue
        overlap = len(new_words & seen_words) / len(new_words | seen_words)
        if overlap >= 0.75:
            return {"other_event_id": seen_event_id, "overlap": overlap}
    _seen_titles.append((event_id, "\x1f".join(new_words)))
    return None


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
    global _duplicate_stop_triggered
    decision = await _real_classify_event_for_router_treatment(session, event_id)
    async with async_session_factory() as record_session:
        event = await record_session.get(NewsEvent, event_id)
        source = await record_session.get(NewsSource, event.source_id) if event else None
        story_link = await record_session.get(NewsEventStoryLink, event_id)

    provenance = {
        "event_id": str(event_id),
        "source_id": str(event.source_id) if event else None,
        "source_name": source.name if source else None,
        "source_type": source.type.value if source and source.type else None,
        "source_url": event.url if event else None,
        "collected_at": str(event.collected_at) if event else None,
        "published_at": str(event.published_at) if event else None,
    }
    print(f"=== PROVENANCE {event_id} === {json.dumps(provenance, ensure_ascii=False, default=str)}")

    dup = None
    if event is not None and decision.treatment != "SKIP" and _duplicate_stop_triggered is None:
        dup = _check_duplicate_tripwire(str(event_id), event.title)
        if dup is not None:
            _duplicate_stop_triggered = {
                "new_event_id": str(event_id), "new_title": event.title,
                "other_event_id": dup["other_event_id"], "overlap": dup["overlap"],
                "story_memory_classification": (
                    {"story_id": str(story_link.story_id), "match_type": story_link.match_type}
                    if story_link is not None else "none computed (story_memory_mode=off this run)"
                ),
            }
            print(f"=== DUPLICATE TRIPWIRE FIRED - STOPPING BEFORE SECOND SEND === {json.dumps(_duplicate_stop_triggered, ensure_ascii=False, default=str)}")

    _treatment_decisions.append({
        "event_id": str(event_id), "title": event.title if event else None,
        "treatment": decision.treatment, "human_review_required": decision.human_review_required,
        "reason": decision.reason, "provenance": provenance,
        "duplicate_tripwire": dup,
    })
    return decision


async def main() -> None:
    global _duplicate_stop_triggered
    setup_logging()
    run_start = time.monotonic()

    settings.editorial_delivery_mode = "router"
    settings.copywriting_prompt_version = "8.3"  # FROZEN after this phase, never modified again
    settings.fact_safety_mode = "shadow"
    # story_memory_mode: NOT set - stays exactly whatever the real .env has ("off").
    settings.newsroom_telegram_chat_id = _REAL_CHAT_ID
    settings.news_topic_id = _REAL_NEWS_TOPIC_ID
    settings.content_generation_dry_run = False

    print("=== CANARY SETTINGS (in-process only) ===")
    for key in ("editorial_delivery_mode", "copywriting_prompt_version", "fact_safety_mode",
                "story_memory_mode", "content_generation_dry_run", "content_generation_min_score"):
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

    cap = HardDeliveryCap(max_deliveries=_TARGET_MESSAGES_MAX)
    wrap_bot_with_hard_cap(bot, cap)
    print(f"=== HARD DELIVERY CAP ARMED: max_deliveries={cap.max_deliveries} ===")
    print()

    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())

    async with async_session_factory() as session:
        baseline_cost = (await session.execute(select(func.coalesce(func.sum(AIExecution.cost), 0)))).scalar_one()

    total_notified = 0
    total_analyzed = 0
    all_delivered_event_ids: list[str] = []
    stop_reason = "max_rounds_reached"

    with patch.object(content_cycle, "_classify_event_for_router_treatment", _instrumented_classify):
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

            if cap.remaining <= 0:
                stop_reason = "hard_delivery_cap_exhausted"
                print(f"=== HARD DELIVERY CAP EXHAUSTED ({cap.attempted}/{cap.max_deliveries}) - stopping ===")
                break

            if total_notified >= _TARGET_MESSAGES_MAX:
                stop_reason = "target_reached"
                print(f"=== TARGET REACHED ({total_notified}/{_TARGET_MESSAGES_MAX}) - stopping, not chasing volume ===")
                break

            if total_analyzed >= _MAX_ANALYZED:
                stop_reason = "max_analyzed_reached"
                print(f"=== MAX ANALYZED REACHED ({total_analyzed}/{_MAX_ANALYZED}) - stopping ===")
                break

            if _duplicate_stop_triggered is not None:
                stop_reason = "duplicate_tripwire"
                print("=== DUPLICATE TRIPWIRE ALREADY FIRED LAST ROUND - stopping, not sending the second one ===")
                break

            print(f"=== ROUND {round_num}: analysis cycle ===")
            analysis_result = await run_analysis_cycle(
                ai_layer.capability_registry, cost_tracker=ai_layer.cost_tracker, pricing_catalog=pricing_catalog,
            )
            print(analysis_result)
            total_analyzed += analysis_result.eligible_found

            print(f"=== ROUND {round_num}: content cycle (LIVE, router mode, V8.3, capped at {cap.remaining} remaining) ===")
            content_result = await run_content_cycle(
                ai_layer.capability_registry, bot, cost_tracker=ai_layer.cost_tracker, pricing_catalog=pricing_catalog,
            )
            print(content_result)
            print()

            total_notified += content_result.notified
            all_delivered_event_ids.extend(str(eid) for eid in content_result.event_ids)

            if analysis_result.eligible_found == 0 and content_result.eligible_found == 0:
                stop_reason = "nothing_eligible"
                print("=== NOTHING LEFT ELIGIBLE THIS ROUND - stopping early, not manufacturing more work ===")
                break

    async with async_session_factory() as session:
        final_cost = (await session.execute(select(func.coalesce(func.sum(AIExecution.cost), 0)))).scalar_one()
    cost_delta = final_cost - baseline_cost
    print(f"=== STOP REASON: {stop_reason} ===")
    print(f"=== COST: baseline={baseline_cost} final={final_cost} delta={cost_delta} ===")
    print(f"=== TOTAL ANALYZED: {total_analyzed}  TOTAL NOTIFIED: {total_notified}  CAP ATTEMPTED: {cap.attempted}/{cap.max_deliveries} ===")
    assert total_notified <= _TARGET_MESSAGES_MAX, f"HARD CAP VIOLATION: {total_notified} > {_TARGET_MESSAGES_MAX}"
    assert cap.attempted <= _TARGET_MESSAGES_MAX, f"HARD CAP VIOLATION: {cap.attempted} attempts > {_TARGET_MESSAGES_MAX}"

    records: list[dict[str, object]] = []
    async with async_session_factory() as session:
        tasks = (
            await session.execute(
                select(EditorialTask).where(EditorialTask.event_id.in_(all_delivered_event_ids))
            )
        ).scalars().all()
        content_tasks = [t for t in tasks if (t.workflow or {}).get("workflow_name") == "CONTENT_GENERATION"]
        for seq, task in enumerate(content_tasks, start=1):
            draft = (
                await session.execute(select(ContentDraft).where(ContentDraft.task_id == task.id))
            ).scalar_one_or_none()
            if draft is None:
                continue
            event = await session.get(NewsEvent, task.event_id)
            source = await session.get(NewsSource, event.source_id) if event else None
            steps = {s.get("step_name"): s.get("result") for s in (task.workflow or {}).get("step_results", [])}
            copywriting_output = steps.get("copywriting")

            matching_decision = next(
                (d for d in _treatment_decisions if d["event_id"] == str(task.event_id)), None,
            )
            treatment = matching_decision["treatment"] if matching_decision else None

            v8_family = bool(copywriting_output) and is_v8_family_output(copywriting_output)
            rendered_html = (
                render_v81_news_card_html(copywriting_output, treatment=treatment or "STANDARD")
                if copywriting_output and v8_family else None
            )
            main_body = copywriting_output.get("main_body") if copywriting_output else None
            ending = copywriting_output.get("ending") if copywriting_output else None

            story_link = await session.get(NewsEventStoryLink, task.event_id)

            event_cost = (
                await session.execute(
                    select(func.coalesce(func.sum(AIExecution.cost), 0)).where(AIExecution.event_id == task.event_id)
                )
            ).scalar_one()

            matching_send = next(
                (s for s in _recorded_sends if isinstance(s.get("text"), str) and copywriting_output
                 and copywriting_output.get("title") and str(copywriting_output["title"])[:15] in s["text"]), None,
            )
            image_domain = None
            if matching_send and matching_send.get("method") == "send_photo":
                image_candidates = await get_editorial_image_candidates(session, content_draft_id=draft.id)
                if image_candidates and image_candidates[0].source_url:
                    image_domain = urlparse(image_candidates[0].source_url).netloc or None

            v82_check = {
                "exactly_one_main_paragraph": bool(main_body) and "\n\n" not in (main_body or ""),
                "no_expandable_details": "expandable_details" not in (copywriting_output or {}),
                "ninja_pulse_absent": rendered_html is not None and "NINJA PULSE" not in rendered_html,
                "no_raw_source_url_in_body": bool(event and event.url and main_body and event.url not in main_body),
            }

            records.append({
                "sequential_delivery_number": seq,
                "event_id": str(task.event_id),
                "content_draft_id": str(draft.id),
                "source_id": str(event.source_id) if event else None,
                "source_name": source.name if source else None,
                "source_url": event.url if event else None,
                "original_title": event.title if event else None,
                "news_category": event.category.value if event and event.category else None,
                "scoring": steps.get("scoring"),
                "intelligence": steps.get("intelligence"),
                "treatment": treatment,
                "treatment_reason": matching_decision["reason"] if matching_decision else None,
                "story_id": str(story_link.story_id) if story_link else None,
                "story_match_type": story_link.match_type if story_link else None,
                "headline": copywriting_output.get("title") if copywriting_output else None,
                "final_telegram_body": rendered_html,
                "character_count": len(rendered_html) if rendered_html else None,
                "main_body_paragraph_count": (main_body.count("\n\n") + 1) if main_body else None,
                "ending_present": bool(ending),
                "image_attached": matching_send.get("method") == "send_photo" if matching_send else None,
                "image_domain": image_domain,
                "source_button_present": matching_send.get("has_button") if matching_send else None,
                "fact_safety": steps.get("quality"),
                "chat_id": matching_send.get("chat_id") if matching_send else None,
                "message_thread_id": matching_send.get("message_thread_id") if matching_send else None,
                "message_id": matching_send.get("message_id") if matching_send else None,
                "incremental_cost_usd": str(event_cost),
                "v82_acceptance_check": v82_check,
            })

    with open("scripts/_phase23_1m_language_canary_records.json", "w", encoding="utf-8") as f:
        json.dump({
            "stop_reason": stop_reason,
            "total_analyzed": total_analyzed,
            "total_notified": total_notified,
            "cap_attempted": cap.attempted,
            "cap_max": cap.max_deliveries,
            "cost_delta_usd": str(cost_delta),
            "runtime_seconds": time.monotonic() - run_start,
            "duplicate_tripwire": _duplicate_stop_triggered,
            "recorded_sends": [
                {**s, "text_len": len(s["text"]) if isinstance(s.get("text"), str) else None}
                for s in _recorded_sends
            ],
            "treatment_decisions": _treatment_decisions,
            "records": records,
        }, f, indent=2, ensure_ascii=False, default=str)
    print("=== WROTE scripts/_phase23_1m_language_canary_records.json ===")

    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
