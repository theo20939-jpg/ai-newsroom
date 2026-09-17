"""Manual-only Phase B.2 RAW-vs-FINAL GPT Image diagnostic.

Default execution is preflight-only. A real provider call additionally requires
INSTAGRAM_PHASE_B2_DISPATCH=1. Normal autonomous Instagram generation stays OFF.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os

from aiogram.types import BufferedInputFile

from bot.loader import create_bot
from core.config import settings
from core.redis import get_redis_client
from database.session import async_session_factory
from integrations.llm_gateway.image_protocol import ImageGenerationOperation, ImageGenerationRequest
from integrations.llm_gateway.providers.openai_image_adapter import GPT_IMAGE_2
from integrations.storage.image_storage import LocalImageStorage
from schemas.editorial_route import EditorialDestination
from schemas.instagram_creative import InstagramCreativeExecutionPlan, InstagramSingleCreative
from services.cost_tracker import global_ledger_key
from services.image_pricing import ImageExecutionProfile, ImagePricingCatalog
from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeDirectorInput, CreativeGenerationOutcome
from services.instagram_creative_media import (
    compile_instagram_generation_prompt,
    execute_instagram_creative_media,
)
from services.instagram_editorial_delivery_state import (
    InstagramEditorialDeliveryService,
    compute_package_identity,
)
from services.instagram_editorial_gate import InstagramGateDecision, evaluate_instagram_editorial_gate
from services.instagram_editorial_package_snapshot import build_package_snapshot
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import render_instagram_feed_image
from services.instagram_shadow_pipeline import ShadowPlanResult
from services.instagram_telegram_delivery import instagram_topic_configured
from services.telegram_routing import send_photo_to_editorial_destination, send_to_editorial_destination


_STORY_ID = "5d82a32b-8afe-4c08-8c3b-75d1f56769b7"
_OPPORTUNITY_ID = f"phase-b2-diagnostic-B4-{_STORY_ID}"
_CREATIVE_ID = "phase-b2-diagnostic-b4-20260918-v1"
_DELIVERY_IDENTITY = compute_package_identity(
    source_key=f"instagram-phase-b2-diagnostic:{_STORY_ID}:v1",
    content_format=ContentFormat.SINGLE.value,
)
_SOURCE_URL = "https://habr.com/ru/articles/1083368/"
_EVIDENCE = [
    "Автор на Хабре описал переход от самых умных и дорогих моделей к более дешёвым.",
    "Главным критерием он выбрал стоимость выполненной задачи, а не максимальный intelligence index.",
]
_SUMMARY = "Почему разработчик выбрал полезность модели вместо максимального рейтинга"


def _creative() -> InstagramSingleCreative:
    return InstagramSingleCreative(
        creative_angle="Максимум интеллекта модели не всегда даёт лучший результат на задачу.",
        visual_concept=(
            "Концептуальная материальная сцена о выборе: сложный тяжёлый механизм противопоставлен "
            "точному лёгкому инструменту, который действительно завершает задачу."
        ),
        on_image_copy="Самая умная модель ≠ самая полезная",
        caption_direction="Разговорно пересказать практический критерий выбора модели.",
        final_caption=(
            "Автор на Хабре пишет, что перестал выбирать самые умные ИИ-модели для каждой задачи. "
            "Вместо рейтинга интеллекта он смотрит на стоимость готового результата.\n\n"
            "Иногда хорошо поставленная задача и более лёгкая модель выигрывают у режима "
            "«включить максимум»."
        ),
        source_subject="выбор ИИ-модели по полезности",
        evidence_used=_EVIDENCE,
        creative_execution_plan=InstagramCreativeExecutionPlan(
            main_idea=(
                "Показать разницу между максимальной вычислительной мощью и практической "
                "полезностью через один ясный материальный визуальный конфликт."
            ),
            focal_point="Лёгкий точный инструмент, который завершает задачу, на фоне громоздкой системы",
            media_strategy="generated_media",
            media_rationale=(
                "Концептуальная метафора уместнее документальной фотографии и не изображает "
                "несуществующий реальный продукт."
            ),
            composition_direction=(
                "Асимметричная портретная сцена: массивная сложная система занимает левую и "
                "нижнюю часть, небольшой точный инструмент становится ясным центром действия; "
                "справа сверху оставить спокойное отрицательное пространство под заголовок."
            ),
            branding_treatment="Логотип не генерировать; текущий знак добавляет compositor.",
            visual_treatment=(
                "Premium editorial still life, tactile industrial materials, subtle surrealism, "
                "warm natural light, intelligent culture-magazine art direction."
            ),
            avoid_recent_treatment=(
                "Без роботов, неона, чёрной карточки, интерфейсов, мозгов из микросхем и sci-fi клише."
            ),
        ),
    )


async def _current_spend() -> Decimal:
    namespace = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw = await get_redis_client().get(global_ledger_key(namespace))
    return Decimal(str(raw)) if raw is not None else Decimal("0")


def _quote(creative: InstagramSingleCreative):
    plan = creative.creative_execution_plan.model_dump()
    prompt = compile_instagram_generation_prompt(
        plan=plan,
        opportunity_summary=_SUMMARY,
        evidence=_EVIDENCE,
        content_format="single",
    )
    request = ImageGenerationRequest(
        prompt=prompt,
        operation=ImageGenerationOperation.TEXT_TO_IMAGE,
        preferred_provider="openai",
        preferred_model=GPT_IMAGE_2,
        target_aspect_ratio="2:3",
        target_width=1024,
        target_height=1536,
    )
    profile = ImageExecutionProfile(
        provider="openai",
        model=GPT_IMAGE_2,
        quality="medium",
        size="1024x1536",
        operation=ImageGenerationOperation.TEXT_TO_IMAGE,
    )
    return prompt, ImagePricingCatalog().quote(profile, request)


async def _already_delivered() -> bool:
    async with async_session_factory() as session:
        existing = await InstagramEditorialDeliveryService().find_current(
            session, package_identity=_DELIVERY_IDENTITY,
        )
        return existing is not None


def _build_package(creative: InstagramSingleCreative, media_result):
    opportunity = ContentOpportunity(
        id=_OPPORTUNITY_ID,
        source_type=OpportunitySourceType.NEWS,
        story_id=_STORY_ID,
        news_value=0.8,
        audience_relevance=0.9,
        evidence=_EVIDENCE,
        confidence=0.95,
        editorial_decision={
            "opportunity_type": "CULTURE",
            "angle": _SUMMARY,
            "angle_intent": "REACTION",
            "audience_value": "Получить практичную рамку выбора модели.",
            "recommended_format": "single",
            "format_reason": "Одна концептуальная метафора сильнее последовательности слайдов.",
            "purpose": "VALUE",
            "origin": "NEWS",
            "topic": _SUMMARY,
            "why_now": "Диагностический повтор подтверждённой B4-возможности.",
            "creative_direction": "Concept-led generated editorial still life.",
        },
    )
    decision = FormatDecision(
        recommended_format=ContentFormat.SINGLE,
        why="Одна концептуальная метафора.",
        expected_role="culture",
        confidence=0.95,
    )
    shadow = ShadowPlanResult(
        campaign_name=None,
        campaign_phase=None,
        opportunity_description=_SUMMARY,
        primary_objective="value",
        audience_description="Разработчики и пользователи ИИ.",
        recommended_format="single",
        hook_family=None,
        creative_concept_summary=creative.creative_execution_plan.main_idea,
        alternative_format=None,
        alternative_objective=None,
        product_mention_allowed=False,
        evidence=_EVIDENCE,
        confidence=0.95,
    )
    package = build_instagram_content_package(
        opportunity=opportunity,
        format_decision=decision,
        shadow_plan=shadow,
        creative_outcome=CreativeGenerationOutcome(single=creative),
        account_key="ninja_pulse",
        source_image_ref=media_result.media_ref,
    )
    package = replace(package, media_plan={
        **package.media_plan,
        "media_execution": media_result.execution_metadata(),
    })
    director_input = CreativeDirectorInput(
        objective="value",
        format="single",
        opportunity_summary=_SUMMARY,
        allowed_evidence=_EVIDENCE,
        audience_summary="Разработчики и пользователи ИИ.",
        locale="ru",
        external_news_entities_allowed=True,
        editorial_decision=json.dumps(opportunity.editorial_decision, ensure_ascii=False),
    )
    return package, opportunity, decision, shadow, director_input


async def main() -> None:
    if settings.instagram_image_generation_mode != "off":
        raise RuntimeError("normal Instagram generation must remain OFF for this diagnostic")
    if not instagram_topic_configured():
        raise RuntimeError("Instagram Telegram topic is not configured")

    creative = _creative()
    prompt, quote = _quote(creative)
    spend = await _current_spend()
    daily_budget = Decimal(str(settings.llm_daily_budget_usd))
    execution_id = f"instagram:{_CREATIVE_ID}:visual:primary:v2"
    report = {
        "status": "PREFLIGHT",
        "provider": "openai",
        "model": GPT_IMAGE_2,
        "size": "1024x1536",
        "quality": "medium",
        "max_attempts": 1,
        "planned_paid_canaries": 1,
        "expected_cost_usd": str(quote.expected_cost_usd),
        "reserved_maximum_cost_usd": str(quote.worst_case_cost_usd),
        "daily_budget_usd": str(daily_budget),
        "current_spend_usd": str(spend),
        "available_budget_usd": str(max(Decimal("0"), daily_budget - spend)),
        "execution_id": execution_id,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "prompt": prompt,
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))

    if quote.worst_case_cost_usd > Decimal("0.10"):
        print(json.dumps({"status": "BLOCKED_THEORETICAL_SPEND"}))
        return
    if spend + quote.worst_case_cost_usd > daily_budget:
        print(json.dumps({"status": "PAID_DIAGNOSTIC_BLOCKED_BY_BUDGET"}))
        return
    if os.getenv("INSTAGRAM_PHASE_B2_DISPATCH") != "1":
        print(json.dumps({"status": "PREFLIGHT_ONLY_NO_PROVIDER_CALL"}))
        return
    if await _already_delivered():
        print(json.dumps({"status": "DUPLICATE_DELIVERY_BLOCKED_NO_PROVIDER_CALL"}))
        return

    media_result = await execute_instagram_creative_media(
        creative=creative,
        source_image=None,
        source_ref=None,
        opportunity_summary=_SUMMARY,
        evidence=_EVIDENCE,
        content_format="single",
        creative_id=_CREATIVE_ID,
        opportunity_id=_OPPORTUNITY_ID,
        mode="live",
    )
    if media_result.status != "generated_media" or len(media_result.assets) != 1:
        raise RuntimeError(f"diagnostic generation failed closed: {media_result.status}")
    asset = media_result.assets[0]
    if asset.raw_image_bytes is None or asset.generated_asset_ref is None:
        raise RuntimeError("provider result lacks durable raw generated asset")

    package, opportunity, decision, shadow, director_input = _build_package(creative, media_result)
    final_render = render_instagram_feed_image(package, source_image=asset.image)
    art = validate_instagram_art(package, [final_render])
    gate = evaluate_instagram_editorial_gate(package, art)
    if gate.decision is not InstagramGateDecision.READY_FOR_EDITOR:
        raise RuntimeError(f"final diagnostic composite failed QA: {art.blocking_issues}")

    final_digest = hashlib.sha256(final_render.image_bytes).hexdigest()
    final_stored = LocalImageStorage(settings.image_storage_root).store_validated_image(
        final_render.image_bytes,
        sha256=final_digest,
        image_format="JPEG",
        max_bytes=settings.instagram_generated_image_max_bytes,
    )
    snapshot = build_package_snapshot(
        package=package,
        opportunity=opportunity,
        format_decision=decision,
        shadow_plan=shadow,
        director_input=director_input,
        previous_creative=creative,
        source_url=_SOURCE_URL,
    )
    snapshot["phase_b2_diagnostic"] = {
        "raw_model_output_ref": asset.generated_asset_ref,
        "final_composite_ref": f"generated:{final_stored.storage_key}",
        "execution_id": asset.generation_execution_id,
        "provider_request_id": asset.provider_request_id,
        "provider": asset.provider,
        "model": asset.model,
        "size": asset.size,
        "quality": asset.quality,
        "prompt": asset.prompt,
        "prompt_sha256": asset.prompt_sha256,
        "reserved_cost_usd": asset.reserved_cost_usd,
        "accounted_cost_usd": asset.accounted_cost_usd,
    }

    bot = create_bot()
    try:
        async with async_session_factory() as session:
            service = InstagramEditorialDeliveryService()
            delivery, created = await service.get_or_create_first_version(
                session,
                package_identity=_DELIVERY_IDENTITY,
                source_story_id=_STORY_ID,
                content_format="single",
                package_snapshot=snapshot,
            )
            if not created:
                raise RuntimeError("diagnostic delivery identity already exists; refusing resend")
            raw_outcome = await send_photo_to_editorial_destination(
                bot,
                EditorialDestination.INSTAGRAM,
                BufferedInputFile(asset.raw_image_bytes, filename="phase_b2_generated_raw.png"),
                "🧪 <b>GENERATED RAW — DO NOT PUBLISH</b>",
                dry_run=False,
            )
            if not raw_outcome.sent or raw_outcome.message_id is None:
                raise RuntimeError(f"raw diagnostic Telegram send failed: {raw_outcome.reason}")
            final_outcome = await send_photo_to_editorial_destination(
                bot,
                EditorialDestination.INSTAGRAM,
                BufferedInputFile(final_render.image_bytes, filename="phase_b2_final_composite.jpg"),
                "✅ <b>FINAL COMPOSITE — CANDIDATE</b>",
                dry_run=False,
                reply_to_message_id=raw_outcome.message_id,
            )
            if not final_outcome.sent or final_outcome.message_id is None:
                raise RuntimeError(f"final diagnostic Telegram send failed: {final_outcome.reason}")
            control = await send_to_editorial_destination(
                bot,
                EditorialDestination.INSTAGRAM,
                (
                    "<b>INSTAGRAM PHASE B.2 · RAW vs FINAL</b>\n\n"
                    f"Execution: <code>{asset.generation_execution_id}</code>\n"
                    f"Provider/model: {asset.provider} / {asset.model}\n"
                    f"Accounted cost: ${asset.accounted_cost_usd}\n\n"
                    "Сначала оцените RAW как работу модели/промпта. Затем отдельно оцените FINAL compositor."
                ),
                dry_run=False,
                reply_to_message_id=final_outcome.message_id,
            )
            await service.mark_delivered(
                session,
                delivery,
                chat_id=final_outcome.chat_id or settings.newsroom_telegram_chat_id,
                topic_id=settings.instagram_topic_id,
                media_message_ids=[raw_outcome.message_id, final_outcome.message_id],
                control_message_id=control.message_id,
            )
            await session.commit()
        print(json.dumps({
            "status": "DELIVERED",
            "raw_message_id": raw_outcome.message_id,
            "final_message_id": final_outcome.message_id,
            "control_message_id": control.message_id,
            "raw_asset_ref": asset.generated_asset_ref,
            "final_asset_ref": f"generated:{final_stored.storage_key}",
            "execution_id": asset.generation_execution_id,
            "provider_request_id": asset.provider_request_id,
            "accounted_cost_usd": asset.accounted_cost_usd,
        }, ensure_ascii=False, sort_keys=True))
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
