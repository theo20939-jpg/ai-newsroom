"""One-shot controlled KAGE NEWS delivery for the saved message-2865 fixture.

The command is deliberately narrow: one exact event, one scratch database, one accepted visual,
and at most one real Telegram ``send_photo``.  It skips natural selection while reusing the
normal content-generation, factual-gate, formatter, routing, receipt, lineage, and publication
truth implementations.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5, NAMESPACE_URL

from aiogram.types import BufferedInputFile
from PIL import Image
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.loader import create_bot
from core.config import settings
from core.logging import setup_logging
from database.models.ai_execution import AIExecution
from database.models.content_draft import ContentDraft
from database.models.content_draft_story_link import ContentDraftStoryLink
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, EventStatus, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from database.models.story_telegram_delivery import StoryTelegramDelivery
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from schemas.editorial_route import EditorialDestination
from schemas.content_draft import ContentDraftRead
from bot.keyboards.image_preview import build_editorial_send_keyboard
from scripts._canary_delivery_cap import HardDeliveryCap, wrap_bot_with_hard_cap
from scripts.run_content_generation import ContentGenerationOutcome, run_content_generation_for_event
from services.editorial_treatment import STANDARD
from services.kage_delivery_truth import authorize_failed_transport_retry, event_publication_state
from services.kage_editorial_usefulness import evaluate_editorial_usefulness
from services.kage_publication_worker_gate import WorkerGateResult, evaluate_worker_publication_gate
from services.kage_telegram_canary_envelope import (
    IMAGE_VISUAL_STAGES,
    TelegramCanaryEnvelope,
    telegram_canary_envelope,
    validate_request_envelope_contracts,
)
from services.kage_content_lineage_audit import reconstruct_lineage
from services.news_telegram_presentation import (
    build_ninja_pulse_footer_html,
    render_v81_news_card_html,
)
from services.pricing_catalog import ModelRegistryPricingCatalog
from services.telegram_routing import RouteTarget, resolve_route
from worker.content_cycle import AcceptedVisualArtifact, run_content_cycle

EVENT_ID = UUID("db748bb0-b41b-4a21-9679-7bd3262a749c")
STORY_ID = UUID("12ded5ee-0f8c-54f7-9e62-b6169114198b")
TASK_ID = UUID("7c3586aa-76a3-41c2-ba51-44a8c124a73b")
DRAFT_ID = UUID("48b5d317-bb43-4c7b-8e6c-16b5569bd445")
EXPECTED_ROUTE = RouteTarget(chat_id=-1004297182444, topic_id=2)
EXPECTED_VISUAL_SHA256 = "d9bbbfb914b79b9c994865d3bb27bc75b5ea03223a51c45899a89166fd0d4e8c"
EXPECTED_VISUAL_SIZE = (1536, 1024)
SCRATCH_DATABASE = "ai_newsroom_kage_controlled_2865"
FORBIDDEN_BODY = "OpenAI приостановила его."
EXPECTED_HEADLINE = "OpenAI приостановила обучение последних моделей"
EXPECTED_BODY = "По данным NBC News, агенты OpenAI неожиданным образом выполняли поиск на сайтах правительства США."
PROMPTS_ROOT = Path(__file__).resolve().parents[1] / "prompts"
FIXTURE_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "kage_lineage_msg2865.json"
VISUAL_PATH = (
    Path(__file__).resolve().parents[1]
    / "artifacts" / "kage_openai_2865_scene_grammar_20260929" / "message_2865_kage_final.jpg"
)


def _configure() -> None:
    if settings.postgres_db != SCRATCH_DATABASE:
        raise RuntimeError(f"refusing controlled send outside scratch database {SCRATCH_DATABASE}")
    if settings.content_generation_enabled:
        raise RuntimeError("refusing controlled send while autonomous content generation is enabled")
    if settings.enabled_providers != ["openai"]:
        raise RuntimeError(f"refusing non-OpenAI provider configuration: {settings.enabled_providers}")
    settings.copywriting_prompt_version = "11.10"
    settings.editorial_delivery_mode = "router"
    settings.unified_editorial_pipeline_enabled = False
    settings.content_generation_dry_run = False
    settings.content_generation_batch_size = 1
    settings.content_generation_scan_limit = 1
    settings.newsroom_telegram_chat_id = EXPECTED_ROUTE.chat_id
    settings.news_topic_id = EXPECTED_ROUTE.topic_id
    settings.instagram_automatic_generation_enabled = False
    settings.instagram_product_lane_enabled = False
    settings.meme_opportunity_mode = "off"
    settings.telegram_story_reply_mode = "off"
    settings.telegram_editorial_gate_enabled = False
    settings.telegram_channel_director_shadow_enabled = False
    settings.story_memory_mode = "shadow"
    settings.article_acquisition_mode = "off"
    settings.image_intelligence_mode = "off"
    settings.image_candidate_persistence_mode = "off"
    settings.editorial_recomposition_mode = "off"
    settings.rich_media_mode = "off"
    settings.video_discovery_mode = "off"
    settings.kage_news_visual_fallback_mode = "live"


def _load_fixture() -> dict[str, Any]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    if UUID(fixture["event_id"]) != EVENT_ID:
        raise RuntimeError("saved fixture event id mismatch")
    return fixture


def _load_visual() -> AcceptedVisualArtifact:
    raw = VISUAL_PATH.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    with Image.open(VISUAL_PATH) as image:
        size = image.size
    if digest != EXPECTED_VISUAL_SHA256 or size != EXPECTED_VISUAL_SIZE:
        raise RuntimeError(f"accepted visual mismatch sha={digest} size={size}")
    return AcceptedVisualArtifact(
        image_bytes=raw,
        filename="message_2865_kage_final.jpg",
        sha256=digest,
        width=size[0],
        height=size[1],
        compliance_decision="COMPLIANT",
    )


def _step(name: str, result: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "step_name": name,
        "status": "SUCCESS",
        "attempt": 1,
        "started_at": now,
        "finished_at": now,
        "error": None,
        "result": result,
    }


async def seed_saved_story(factory: async_sessionmaker[AsyncSession], fixture: dict[str, Any]) -> dict[str, str]:
    """Import only immutable saved evidence needed by the current pipeline into scratch storage."""
    async with factory() as session:
        existing = await session.get(NewsEvent, EVENT_ID)
        if existing is not None:
            analysis = await session.scalar(
                select(EditorialTask).where(
                    EditorialTask.event_id == EVENT_ID,
                    EditorialTask.workflow["workflow_name"].as_string() == "NEWS_ANALYSIS",
                )
            )
            story_link = await session.get(NewsEventStoryLink, EVENT_ID)
            if analysis is None or story_link is None:
                raise RuntimeError("partial controlled fixture already exists")
            return {
                "event_id": str(EVENT_ID),
                "story_id": str(story_link.story_id),
                "analysis_task_id": str(analysis.id),
            }

        source_id = uuid5(NAMESPACE_URL, "kage-controlled-2865-source")
        story_id = uuid5(NAMESPACE_URL, "kage-controlled-2865-story")
        analysis_task_id = uuid5(NAMESPACE_URL, "kage-controlled-2865-analysis")
        saved_source_url = fixture["saved_image_candidates"][0]["source_url"]
        facts = fixture["research"]["facts"]
        source = NewsSource(
            id=source_id,
            name="NBC News (saved #2865 fixture)",
            type=SourceType.RSS,
            url=saved_source_url,
            reliability_score=0.9,
            active=True,
        )
        event = NewsEvent(
            id=EVENT_ID,
            source_id=source_id,
            title=fixture["source_headline"],
            summary="\n".join(facts),
            content="\n".join(facts),
            url=saved_source_url,
            category=EventCategory.AI,
            published_at=datetime.now(timezone.utc),
            hash="kage-controlled-2865",
            status=EventStatus.ANALYZED,
        )
        session.add(source)
        await session.flush()
        session.add(event)
        await session.flush()
        story = Story(
            id=story_id,
            title=fixture["source_headline"],
            category=EventCategory.AI,
            entities=["OpenAI"],
            keywords=["AI agents", "model training"],
            topic_bucket="ai",
            first_event_id=EVENT_ID,
            event_count=1,
        )
        session.add(story)
        await session.flush()
        session.add(NewsEventStoryLink(
            news_event_id=EVENT_ID,
            story_id=story_id,
            match_type="new_story",
            match_score=1.0,
        ))
        analysis = EditorialTask(
            id=analysis_task_id,
            event_id=EVENT_ID,
            priority=TaskPriority.B,
            status=TaskStatus.COMPLETED,
            retry_count=0,
            workflow={
                "workflow_name": "NEWS_ANALYSIS",
                "workflow_version": 1,
                "current_step": None,
                "completed_steps": ["research", "intelligence"],
                "iteration_count": 1,
                "step_results": [
                    _step("research", fixture["research"]),
                    _step("intelligence", fixture["intelligence"]),
                ],
                "failure": None,
            },
        )
        session.add(analysis)
        await session.commit()
        return {
            "event_id": str(EVENT_ID),
            "story_id": str(story_id),
            "analysis_task_id": str(analysis_task_id),
        }


def _copy_body(copy: dict[str, Any]) -> str:
    body = str(copy.get("main_body") or "")
    ending = copy.get("ending")
    return "\n\n".join((body, ending.strip())) if isinstance(ending, str) and ending.strip() else body


async def _load_delivery_retry_state(
    factory: async_sessionmaker[AsyncSession], visual: AcceptedVisualArtifact,
) -> tuple[ContentGenerationOutcome, WorkerGateResult, dict[str, Any]]:
    """Rehydrate the persisted result without constructing any provider dependency."""
    async with factory() as session:
        task = await session.get(EditorialTask, TASK_ID)
        draft = await session.get(ContentDraft, DRAFT_ID)
        link = await session.get(ContentDraftStoryLink, DRAFT_ID)
        event = await session.get(NewsEvent, EVENT_ID)
        lineage = await reconstruct_lineage(session, TASK_ID)
        receipt_count = await session.scalar(
            select(func.count()).select_from(StoryTelegramDelivery).where(
                StoryTelegramDelivery.content_draft_id == DRAFT_ID,
            )
        )
        publication = await event_publication_state(session, EVENT_ID)
        ai_execution_count = await session.scalar(select(func.count()).select_from(AIExecution))
    if task is None or task.event_id != EVENT_ID:
        raise RuntimeError("controlled retry task/event mismatch")
    if draft is None or draft.task_id != TASK_ID or draft.id != DRAFT_ID:
        raise RuntimeError("controlled retry draft/task mismatch")
    if link is None or link.story_id != STORY_ID or link.source_event_id != EVENT_ID:
        raise RuntimeError("controlled retry story relation mismatch")
    if event is None:
        raise RuntimeError("controlled retry event missing")
    if draft.title != EXPECTED_HEADLINE or draft.body != EXPECTED_BODY:
        raise RuntimeError("persisted controlled copy changed")
    if receipt_count != 0 or publication["already_delivered"]:
        raise RuntimeError("successful delivery already exists; retry refused")
    terminal = (task.workflow or {}).get("publication_outcome")
    if not isinstance(terminal, dict) or terminal.get("status") != "VISUAL_HOLD" \
            or terminal.get("reason") != "media_send_failed":
        raise RuntimeError("controlled retry requires the persisted media_send_failed VISUAL_HOLD")
    if lineage is None:
        raise RuntimeError("controlled retry lineage missing")
    step_results = {
        row.get("step_name"): row.get("result")
        for row in (task.workflow or {}).get("step_results", [])
        if isinstance(row, dict) and row.get("status") == "SUCCESS" and isinstance(row.get("result"), dict)
    }
    required_steps = {"research", "intelligence", "copywriting", "quality"}
    if not required_steps.issubset(step_results):
        raise RuntimeError("persisted controlled stage outputs incomplete")
    copy = step_results["copywriting"]
    if copy.get("title") != EXPECTED_HEADLINE or _copy_body(copy) != EXPECTED_BODY:
        raise RuntimeError("persisted structured copy changed")
    factual_audit = lineage.get("publication_factual_gate")
    structured = factual_audit.get("structured_result") if isinstance(factual_audit, dict) else None
    if not isinstance(structured, dict) or structured.get("FACTUAL_SAFETY") != "PASS" \
            or structured.get("HEADLINE_SAFETY") != "PASS" \
            or structured.get("BODY_SAFETY") != "PASS" \
            or structured.get("UNSUPPORTED_CLAIMS") != []:
        raise RuntimeError("persisted factual gate is not an exact zero-claim PASS")
    caption = render_v81_news_card_html(
        copy, treatment=STANDARD, include_ninja_pulse_footer=True,
    )
    footer = build_ninja_pulse_footer_html()
    keyboard = build_editorial_send_keyboard(event.url, event.id, label="🔗 Источник")
    buttons = _buttons(keyboard)
    if not caption.endswith(footer) or len(caption.encode("utf-16-le")) // 2 > 1024:
        raise RuntimeError("persisted controlled caption failed footer/length preflight")
    if not any(button["text"] == "🔗 Источник" and button["url"] for button in buttons):
        raise RuntimeError("persisted controlled source button missing")
    if visual.sha256 != EXPECTED_VISUAL_SHA256:
        raise RuntimeError("accepted controlled visual changed")
    quality = step_results["quality"]
    fact_safety = quality.get("fact_safety") if isinstance(quality, dict) else None
    outcome = ContentGenerationOutcome(
        task_id=TASK_ID,
        workflow_status="COMPLETED",
        content_draft=ContentDraftRead.model_validate(draft, from_attributes=True),
        fact_safety_status=fact_safety.get("status") if isinstance(fact_safety, dict) else None,
        copywriting_output=copy,
        research_output=step_results["research"],
        intelligence_output=step_results["intelligence"],
        quality_output=quality,
    )
    gate = WorkerGateResult(
        publication_block=False,
        technical_block=False,
        factual_block=False,
        guard_block=False,
        record={
            "final_publication_block": False,
            "unsupported_claim_count": 0,
            "reused_persisted_gate": True,
        },
        audit_payload=factual_audit,
    )
    return outcome, gate, {
        "task_id": str(TASK_ID),
        "draft_id": str(DRAFT_ID),
        "story_id": str(STORY_ID),
        "event_id": str(EVENT_ID),
        "headline": draft.title,
        "body": draft.body,
        "draft_status": draft.status,
        "caption": caption,
        "caption_utf16_units": len(caption.encode("utf-16-le")) // 2,
        "buttons": buttons,
        "receipt_count": receipt_count,
        "publication_state": publication,
        "previous_publication_outcome": terminal,
        "ai_execution_count": ai_execution_count,
    }


def _buttons(markup: Any) -> list[dict[str, str | None]]:
    return [
        {"text": button.text, "url": button.url}
        for row in (getattr(markup, "inline_keyboard", None) or [])
        for button in row
    ]


def _instrument_bot(bot: Any, visual: AcceptedVisualArtifact) -> tuple[HardDeliveryCap, list[dict[str, Any]]]:
    sends: list[dict[str, Any]] = []
    original_photo = bot.send_photo

    async def reject_message(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("controlled KAGE delivery forbids send_message")

    async def guarded_photo(*args: Any, **kwargs: Any) -> Any:
        bound = inspect.signature(original_photo).bind_partial(*args, **kwargs)
        chat_id = bound.arguments.get("chat_id")
        topic_id = bound.arguments.get("message_thread_id")
        caption = str(bound.arguments.get("caption") or "")
        photo = bound.arguments.get("photo")
        buttons = _buttons(bound.arguments.get("reply_markup"))
        footer = build_ninja_pulse_footer_html()
        if (chat_id, topic_id) != (EXPECTED_ROUTE.chat_id, EXPECTED_ROUTE.topic_id):
            raise RuntimeError("controlled destination mismatch at send boundary")
        if not isinstance(photo, BufferedInputFile):
            raise RuntimeError("controlled send did not resolve accepted visual bytes")
        if hashlib.sha256(photo.data).hexdigest() != visual.sha256:
            raise RuntimeError("controlled visual changed before send")
        if len(caption.encode("utf-16-le")) // 2 > 1024:
            raise RuntimeError("controlled caption exceeds Telegram photo limit")
        if not caption.endswith(footer):
            raise RuntimeError("KAGE footer missing at send boundary")
        if not any(button["text"] == "🔗 Источник" and button["url"] for button in buttons):
            raise RuntimeError("source button missing at send boundary")
        try:
            response = await original_photo(*args, **kwargs)
        except Exception as exc:
            sends.append({"method": "send_photo", "status": "failed", "error": type(exc).__name__})
            raise
        sends.append({
            "method": "send_photo",
            "status": "accepted",
            "chat_id": chat_id,
            "topic_id": topic_id,
            "message_id": response.message_id,
            "telegram_chat_id": response.chat.id,
            "caption": caption,
            "buttons": buttons,
            "photo_sha256": visual.sha256,
        })
        return response

    bot.send_message = reject_message
    bot.send_photo = guarded_photo
    cap = HardDeliveryCap(max_deliveries=1)
    wrap_bot_with_hard_cap(bot, cap)
    return cap, sends


async def _persisted_result(
    factory: async_sessionmaker[AsyncSession], *, task_id: UUID, draft_id: UUID,
) -> dict[str, Any]:
    async with factory() as session:
        task = await session.get(EditorialTask, task_id)
        draft = await session.get(ContentDraft, draft_id)
        link = await session.get(ContentDraftStoryLink, draft_id)
        receipt = await session.scalar(
            select(StoryTelegramDelivery)
            .where(StoryTelegramDelivery.content_draft_id == draft_id)
            .order_by(StoryTelegramDelivery.created_at.desc())
            .limit(1)
        )
        lineage = await reconstruct_lineage(session, task_id)
        publication = await event_publication_state(session, EVENT_ID)
    return {
        "task_id": str(task_id),
        "draft_id": str(draft_id),
        "draft_status": draft.status if draft else None,
        "story_id": str(link.story_id) if link else None,
        "source_event_id": str(link.source_event_id) if link else None,
        "publication_outcome": (task.workflow or {}).get("publication_outcome") if task else None,
        "delivery_receipt": {
            "id": str(receipt.id),
            "status": receipt.delivery_status.value,
            "chat_id": receipt.telegram_chat_id,
            "message_id": receipt.telegram_message_id,
        } if receipt else None,
        "lineage": lineage,
        "event_publication_state": publication,
    }


async def run_once() -> dict[str, Any]:
    _configure()
    validate_request_envelope_contracts()
    fixture = _load_fixture()
    visual = _load_visual()
    route = resolve_route(EditorialDestination.NEWS)
    if route != EXPECTED_ROUTE:
        raise RuntimeError(f"NEWS route mismatch: {route!r}")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    bot = None
    try:
        if not await redis.ping() or await redis.dbsize() != 0:
            raise RuntimeError("controlled Redis must be reachable and empty")
        fixture_identity = await seed_saved_story(factory, fixture)
        async with factory() as session:
            before = await event_publication_state(session, EVENT_ID)
        if before["already_delivered"] or before["in_flight_task_ids"]:
            return {
                "status": "DUPLICATE_BLOCKED",
                "block_point": "event_publication_state_before_provider_setup",
                "fixture": fixture_identity,
                "publication_state": before,
                "provider_calls": 0,
                "telegram_sends": 0,
                "image_generation_calls": 0,
                "natural_selection_calls": 0,
            }

        prompts = FilePromptRepository(PROMPTS_ROOT)
        ai = assemble_ai_integration_layer(settings, prompts, redis_client=redis)
        pricing = ModelRegistryPricingCatalog(build_model_registry())
        envelope = TelegramCanaryEnvelope()
        with telegram_canary_envelope(envelope):
            outcome = await run_content_generation_for_event(
                EVENT_ID,
                capability_registry=ai.capability_registry,
                session_factory=factory,
                cost_tracker=ai.cost_tracker,
                pricing_catalog=pricing,
            )
            if outcome.content_draft is None or not outcome.copywriting_output:
                raise RuntimeError("current editorial pipeline produced no draft")
            copy = outcome.copywriting_output
            body = _copy_body(copy)
            if not str(copy.get("title") or "").strip() or not body.strip():
                raise RuntimeError("current editorial draft is missing headline/body")
            if FORBIDDEN_BODY in body:
                raise RuntimeError("current editorial draft reproduced forbidden historical body")
            usefulness = evaluate_editorial_usefulness(
                title=str(copy.get("title") or ""),
                body=body,
                research=outcome.research_output or {},
                intelligence=outcome.intelligence_output or {},
                source_headline=fixture["source_headline"],
            )
            if not usefulness["passed"]:
                raise RuntimeError(f"editorial usefulness failed: {usefulness.get('reason')}")
            gate = await evaluate_worker_publication_gate(
                gateway=ai.gateway,
                prompt_repository=prompts,
                draft=copy,
                research=outcome.research_output,
                intelligence=outcome.intelligence_output,
                source_headline=fixture["source_headline"],
                event_id=EVENT_ID,
                draft_id=outcome.content_draft.id,
                task_id=outcome.task_id,
                cost_tracker=ai.cost_tracker,
                pricing_catalog=pricing,
                quality_result=outcome.quality_output,
            )
            if gate.publication_block or gate.record.get("unsupported_claim_count") != 0:
                raise RuntimeError(f"publication factual gate blocked: {gate.record}")

            print(json.dumps({
                "event": "KAGE_CONTROLLED_PRE_SEND_ACCEPTANCE_PASS",
                "event_id": str(EVENT_ID),
                "story_id": fixture_identity["story_id"],
                "task_id": str(outcome.task_id),
                "draft_id": str(outcome.content_draft.id),
                "headline_present": True,
                "body_present": True,
                "editorial_usefulness": "PASS",
                "factual_gate": "PASS",
                "unsupported_claims": 0,
                "duplicate_state": "CLEAR",
                "visual_sha256": visual.sha256,
                "visual_dimensions": [visual.width, visual.height],
                "visual_compliance": visual.compliance_decision,
                "new_image_generation_calls": 0,
                "route": {"chat_id": route.chat_id, "topic_id": route.topic_id},
                "natural_selection_calls": 0,
                "enabled_providers": settings.enabled_providers,
            }, ensure_ascii=False), flush=True)

            bot = create_bot()
            delivery_cap, sends = _instrument_bot(bot, visual)
            cycle = await run_content_cycle(
                ai.capability_registry,
                bot,
                session_factory=factory,
                cost_tracker=ai.cost_tracker,
                pricing_catalog=pricing,
                event_ids_override=[EVENT_ID],
                precomputed_outcomes={EVENT_ID: outcome},
                accepted_visuals={EVENT_ID: visual},
                precomputed_publication_gates={outcome.task_id: gate},
                gate_gateway=None,
                gate_prompt_repository=None,
            )

        if delivery_cap.attempted != 1 or len(sends) != 1 or sends[0].get("status") != "accepted":
            raise RuntimeError(f"controlled send was not exactly one confirmed send_photo: {sends}")
        if cycle.notified != 1:
            raise RuntimeError("normal content cycle did not confirm one notification")
        if any(row.get("stage") in IMAGE_VISUAL_STAGES for row in envelope.dispatch_records):
            raise RuntimeError("image provider was called despite accepted visual reuse")

        persisted = await _persisted_result(
            factory, task_id=outcome.task_id, draft_id=outcome.content_draft.id,
        )
        actual_cost = sum(
            (Decimal(str(row["actual_cost_usd"])) for row in envelope.dispatch_records
             if row.get("actual_cost_usd") is not None),
            Decimal("0"),
        )
        return {
            "status": "DELIVERED",
            "fixture": fixture_identity,
            "event_id": str(EVENT_ID),
            "task_id": str(outcome.task_id),
            "draft_id": str(outcome.content_draft.id),
            "headline": copy.get("title"),
            "body": body,
            "usefulness": usefulness,
            "factual_gate": gate.record,
            "visual": {
                "path": str(VISUAL_PATH),
                "sha256": visual.sha256,
                "width": visual.width,
                "height": visual.height,
                "compliance": visual.compliance_decision,
            },
            "route": {"chat_id": route.chat_id, "topic_id": route.topic_id},
            "send": sends[0],
            "provider_dispatches": envelope.dispatch_records,
            "provider_calls": len(envelope.dispatch_records),
            "provider_cost_usd": str(actual_cost),
            "image_generation_calls": 0,
            "natural_selection_calls": 0,
            "persisted": persisted,
        }
    finally:
        if bot is not None:
            await bot.session.close()
        await redis.aclose()
        await engine.dispose()


async def run_delivery_only_retry() -> dict[str, Any]:
    """Retry only the persisted transport payload; never construct or call a provider."""
    _configure()
    validate_request_envelope_contracts()
    visual = _load_visual()
    route = resolve_route(EditorialDestination.NEWS)
    if route != EXPECTED_ROUTE:
        raise RuntimeError(f"NEWS route mismatch: {route!r}")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    bot = None
    try:
        async with factory() as session:
            publication_before = await event_publication_state(session, EVENT_ID)
            ai_count_before = await session.scalar(select(func.count()).select_from(AIExecution))
        if publication_before["already_delivered"]:
            return {
                "status": "DUPLICATE_BLOCKED",
                "block_point": "event_publication_state_before_retry_authorization",
                "event_id": str(EVENT_ID),
                "publication_state": publication_before,
                "provider_calls": 0,
                "telegram_api_send_attempts": 0,
                "confirmed_telegram_deliveries": 0,
                "image_generation_calls": 0,
            }
        outcome, gate, preflight = await _load_delivery_retry_state(factory, visual)
        async with factory() as session:
            authorization = await authorize_failed_transport_retry(
                session,
                task_id=TASK_ID,
                draft_id=DRAFT_ID,
                authorized_by="founder_manual_topic_inspection",
            )
            await session.commit()

        envelope = TelegramCanaryEnvelope()
        bot = create_bot()
        delivery_cap, sends = _instrument_bot(bot, visual)
        with telegram_canary_envelope(envelope):
            cycle = await run_content_cycle(
                None,  # provider registry deliberately absent in delivery-only mode
                bot,
                session_factory=factory,
                event_ids_override=[EVENT_ID],
                precomputed_outcomes={EVENT_ID: outcome},
                accepted_visuals={EVENT_ID: visual},
                precomputed_publication_gates={TASK_ID: gate},
                gate_gateway=None,
                gate_prompt_repository=None,
            )
        if delivery_cap.attempted != 1 or len(sends) != 1 or sends[0].get("status") != "accepted":
            raise RuntimeError(f"delivery-only retry was not one confirmed send_photo: {sends}")
        if cycle.notified != 1:
            raise RuntimeError("normal content cycle did not confirm one retry notification")
        if envelope.dispatch_records:
            raise RuntimeError("provider dispatch occurred during delivery-only retry")
        persisted = await _persisted_result(factory, task_id=TASK_ID, draft_id=DRAFT_ID)
        async with factory() as session:
            ai_count_after = await session.scalar(select(func.count()).select_from(AIExecution))
        if ai_count_after != ai_count_before:
            raise RuntimeError("AI execution count changed during delivery-only retry")
        return {
            "status": "DELIVERED",
            "mode": "delivery_only_retry",
            "event_id": str(EVENT_ID),
            "story_id": str(STORY_ID),
            "task_id": str(TASK_ID),
            "draft_id": str(DRAFT_ID),
            "preflight": preflight,
            "retry_authorization": authorization,
            "visual": {
                "path": str(VISUAL_PATH),
                "sha256": visual.sha256,
                "width": visual.width,
                "height": visual.height,
                "compliance": visual.compliance_decision,
            },
            "route": {"chat_id": route.chat_id, "topic_id": route.topic_id},
            "send": sends[0],
            "provider_dispatches": [],
            "provider_calls": 0,
            "provider_cost_usd": "0",
            "image_generation_calls": 0,
            "natural_selection_calls": 0,
            "telegram_api_send_attempts": 1,
            "confirmed_telegram_deliveries": 1,
            "persisted": persisted,
        }
    finally:
        if bot is not None:
            await bot.session.close()
        await engine.dispose()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event-id", required=True, type=UUID)
    parser.add_argument("--confirm-live-send", action="store_true")
    parser.add_argument("--delivery-only-retry", action="store_true")
    parser.add_argument("--confirm-founder-no-message", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.event_id != EVENT_ID:
        raise SystemExit(f"refusing unsupported event id: {args.event_id}")
    if not args.confirm_live_send:
        raise SystemExit("refusing live execution without --confirm-live-send")
    if args.delivery_only_retry:
        if not args.confirm_founder_no_message:
            raise SystemExit("delivery-only retry requires --confirm-founder-no-message")
        result = await run_delivery_only_retry()
    else:
        result = await run_once()
    rendered = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.report is not None:
        if args.report.exists():
            raise SystemExit(f"refusing to overwrite report: {args.report}")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered, flush=True)


if __name__ == "__main__":
    setup_logging()
    asyncio.run(main())
