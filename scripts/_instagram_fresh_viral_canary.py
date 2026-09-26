"""KAGE INSTAGRAM - FRESH VIRAL CAROUSEL LIVE VOICE PROOF: exactly ONE fresh real story through the REAL current pipeline.

The event (read-only copied from production into the scratch DB) goes through exactly the per-post path of scripts/_instagram_e2e_week.py:
treatment -> the daily evidence package (live acquisition + media discovery) -> evaluate_and_submit_instagram_candidate with the feed
planner's own slot (read_candidate -> MEME_TREND). NOTHING is forced: Phase A chooses among the executable formats (single / carousel), the
viral rule applies only if Phase A says single, the Director runs with the committed viral voice note and its one bounded correction retry,
no manual edit. Image generation is LIVE in this process only (the accepted no-photo => generated rule), through an isolated capped ledger.
No Telegram (the delivery row is recorded, the presentation saved), no production write, no publication.
Usage (OPENAI_API_KEY in the environment only): python scripts/_instagram_fresh_viral_canary.py <event id> <out dir>
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("KAGE_E2E_CAP_USD", os.environ.get("KAGE_FRESH_LLM_CAP_USD", "0.35"))

import scripts._instagram_e2e_week as harness  # noqa: E402  (scratch DB env, provider guard, render/delivery capture)

from core.config import settings  # noqa: E402

IMAGE_CAP = Decimal(os.environ.get("KAGE_FRESH_IMAGE_CAP_USD", "0.55"))
LLM_NAMESPACE = os.environ.get("KAGE_FRESH_LLM_NAMESPACE", "kage_fresh_viral_llm_20260926")
IMAGE_NAMESPACE = os.environ.get("KAGE_FRESH_IMAGE_NAMESPACE", "kage_fresh_viral_images_20260926")


async def main() -> None:
    event_id, out = UUID(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    settings.article_acquisition_mode = "shadow"
    settings.image_intelligence_mode = "shadow"
    settings.image_candidate_persistence_mode = "finalists"
    settings.image_storage_root = str(out / "_image_storage")
    settings.instagram_image_generation_mode = "live"  # in-process only: the accepted no-photo => generated rule, capped below
    assert harness.SCRATCH_DB in settings.database_url

    from redis.asyncio import Redis
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import integrations.llm_gateway.boot as boot
    import services.instagram_creative_media as media_mod
    import worker.content_cycle as cc
    from database.models.editorial_task import EditorialTask, TaskStatus
    from database.models.news_event import NewsEvent
    from database.models.news_source import NewsSource
    from integrations.llm_gateway.boot import assemble_ai_integration_layer
    from integrations.llm_gateway.models.catalog import build_model_registry
    from integrations.prompts.file_repository import FilePromptRepository
    from schemas.workflow import WorkflowType
    from services.budget_guard import RedisBudgetGuard
    from services.budgeted_image_execution import BudgetedImageExecutor
    from services.cost_estimator import CostEstimator
    from services.cost_tracker import RedisCostTracker
    from services.instagram_automatic_trigger import evaluate_and_submit_instagram_candidate
    from services.instagram_evidence_package import BLOCKING, build_daily_evidence_package
    from services.instagram_feed_product import FeedCandidate, FeedFormat, read_candidate
    from services.pricing_catalog import ModelRegistryPricingCatalog

    diag = Redis.from_url(harness.DIAG_REDIS_URL, decode_responses=True)
    for namespace in (LLM_NAMESPACE, IMAGE_NAMESPACE):
        if await diag.get(f"phase7:cost_ledger:{namespace}"):
            raise SystemExit(f"ledger {namespace} already holds spend - this canary never runs twice")
    registry = build_model_registry()
    models = {m.model_id: m for m in registry.all_models()}
    pricing = ModelRegistryPricingCatalog(registry)
    diag_settings = settings.model_copy(update={"llm_budget_mode": "enforce", "llm_daily_budget_usd": float(harness.CAP),
                                                "enabled_providers": ["openai"], "redis_unavailable_policy": "fail_closed"})
    boot.RedisBudgetGuard = lambda redis, st: RedisBudgetGuard(redis, st, ledger_namespace=LLM_NAMESPACE)
    repo = FilePromptRepository(harness.ROOT / "prompts")
    layer = assemble_ai_integration_layer(diag_settings, repo, redis_client=diag)
    harness._install_provider_guard(pricing, CostEstimator(pricing), models, RedisCostTracker(diag, pricing, ledger_namespace=LLM_NAMESPACE))
    suit = harness._install_capture()
    image_guard = RedisBudgetGuard(diag, settings.model_copy(update={"llm_budget_mode": "enforce", "llm_daily_budget_usd": float(IMAGE_CAP),
                                                                     "redis_unavailable_policy": "fail_closed"}), ledger_namespace=IMAGE_NAMESPACE)
    media_mod.build_budgeted_image_executor = lambda: BudgetedImageExecutor(budget_guard=image_guard)
    generated: list = []
    real_generate = media_mod._execute_generated_asset

    async def record_generation(**kw):  # observation only: every generated picture is saved the moment it arrives
        asset = await real_generate(**kw)
        generated.append({"asset_key": kw.get("asset_key"), "status": asset.status, "accounted_usd": asset.accounted_cost_usd,
                          "reserved_usd": asset.reserved_cost_usd, "provider_request_id": asset.provider_request_id, "prompt": asset.prompt})
        if asset.image is not None:
            (out / "post" / "generated").mkdir(parents=True, exist_ok=True)
            asset.image.save(out / "post" / "generated" / f"asset_{kw.get('asset_key')}.png")
        return asset

    media_mod._execute_generated_asset = record_generation

    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    harness.STATE["post"], harness.STATE["post_dir"] = "post", out / "post"
    verdicts: list = []
    suit.set_verdict_sink(verdicts)
    row: dict = {"event_id": str(event_id)}
    async with factory() as session:
        event = await session.get(NewsEvent, event_id)
        source = await session.get(NewsSource, event.source_id)
        read = read_candidate(FeedCandidate(id=str(event.id), title=event.title or "", summary=(event.summary or event.content or "")[:600],
                                            source_name=source.name or "", source_type=getattr(source.type, "value", str(source.type or "")),
                                            category=getattr(event.category, "value", str(event.category or ""))))
        row.update(title=event.title, source=source.name, url=event.url, published_at=str(event.published_at), ingested_at=str(event.created_at),
                   planner_read={"format": read.format.value, "strong": read.strong, "kinds": list(read.kinds), "reason": read.reason})
        if read.format is not FeedFormat.MEME_TREND:
            raise SystemExit(f"the planner no longer reads this story as MEME_TREND: {read.format.value}")
        treatment = await cc._classify_event_for_router_treatment(session, event_id)
        row["treatment"] = {"treatment": treatment.treatment, "reason": treatment.reason}
        package = await build_daily_evidence_package(
            post_id=str(event_id), fmt="meme_trend", title=event.title or "", url=event.url,
            source_type=getattr(getattr(source, "type", None), "value", "RSS"), source_name=source.name, stored_body=event.content or event.summary,
            event=event, event_id=event_id, session=session, acquisition_enabled=True, media_mode="shadow")
        await session.commit()
        harness._write(out / "post" / "evidence_package.json", package)
        row.update(evidence=package.quality, evidence_why=package.why, source_media=package.media.status)
        if package.quality == BLOCKING:
            row.update(reason="evidence_blocking")
        else:
            na_task = await session.scalar(select(EditorialTask).where(
                EditorialTask.event_id == event_id, EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
                EditorialTask.status == TaskStatus.COMPLETED).limit(1))
            facts = package.director_evidence() + [f[:800] for f in cc._extract_research_facts(na_task.workflow if na_task else None) if f]
            outcome = await evaluate_and_submit_instagram_candidate(
                session, AsyncMock(), event_id=str(event_id), event_title=event.title or "", treatment=treatment, research_facts=facts,
                gateway=layer.gateway, prompt_repository=repo, source_url=event.url, phase_a_enabled=True, feed_format=FeedFormat.MEME_TREND)
            await session.commit()
            row.update(reason=outcome.reason, gate=outcome.gate_decision, delivery=outcome.delivery_reason, chosen_format=outcome.chosen_format)
    row.update(vision_verdicts=verdicts, generated=generated, llm_calls=harness.STATE["calls"], llm_spent_usd=str(harness.STATE["spent"]),
               llm_ledger_usd=await diag.get(f"phase7:cost_ledger:{LLM_NAMESPACE}"),
               image_ledger_usd=await diag.get(f"phase7:cost_ledger:{IMAGE_NAMESPACE}"))
    harness._write(out / "outcome.json", row)
    print(json.dumps({k: row.get(k) for k in ("title", "reason", "gate", "chosen_format", "evidence", "source_media", "llm_spent_usd",
                                              "image_ledger_usd")}, ensure_ascii=False, indent=1, default=str))
    await engine.dispose()
    await diag.aclose()


if __name__ == "__main__":
    asyncio.run(main())
