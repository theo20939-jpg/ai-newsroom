"""Manual-only Phase B.4.4 shadow canary through the REAL live trigger
(`services.instagram_automatic_trigger.evaluate_and_submit_instagram_opportunity`).

Modes (argv[2]):
  fake  - ZERO cost: an offline fake transport returns deterministic v7-shaped plans
          (scripts/_instagram_phase_b44_common.py::fake_plan). No provider call of any kind.
  real  - at most FOUR real carousel Creative Director calls (prompt v7, real gateway, BudgetGuard in
          enforce mode, own cumulative budget cap). One call per archetype, no retries. Text planning
          only: zero image-provider calls.

Both modes: the editorial-DECISION step is a deterministic fixture (no extra LLM call), Telegram
delivery is a recorder (zero publication), and persistence goes to a throwaway Postgres session that
is rolled back. The automatic-generation flag is never touched.

Usage: python scripts/_instagram_phase_b44_shadow.py <out_dir> <fake|real>"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import scripts._instagram_phase_b44_common as common
import services.instagram_automatic_trigger as trigger
import services.instagram_creative_director as cd_module
from core.config import settings
from database.models.image_candidate_record import ImageCandidateRecord, ImageStorageStatus
from database.models.story import Story
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from services.cost_tracker import compute_call_cost
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_recap_bundle import build_instagram_recap_bundle
from services.instagram_trend_radar import TrendSignal, TrendSignalProvenance, TrendSignalType
from services.pricing_catalog import ModelRegistryPricingCatalog
from services.weekly_recap_selection import (
    _build_candidate,
    select_weekly_recap_stories,
    select_weekly_recap_stories_from_candidates,
)

_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_MAX_REAL_CALLS = 4
_ARCHETYPES = ("ai_hack", "news_insight", "news_recap", "trend_generative")


def _worst_case_call_cost() -> Decimal:
    worst = Decimal(0)
    for model in build_model_registry().all_models():
        if model.provider_id != "openai" or not model.supports_structured_output:
            continue
        tier = next((t for t in model.pricing_tiers if t.condition == "standard"), None)
        if tier is not None:
            worst = max(worst, Decimal(8000) / 1_000_000 * tier.input_price_per_million
                        + Decimal(6000) / 1_000_000 * tier.output_price_per_million)
    return worst


async def _budget_preflight() -> dict:
    from core.redis import get_redis_client

    ns = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw = await get_redis_client().get(f"phase7:cost_ledger:{ns}")
    spent = Decimal(str(raw)) if raw is not None else Decimal(0)
    worst_each = _worst_case_call_cost()
    budget = Decimal(str(settings.llm_daily_budget_usd))
    return {
        "ledger_namespace": ns, "spent_today_usd": str(spent), "daily_budget_usd": str(budget),
        "budget_mode": settings.llm_budget_mode, "worst_case_per_call_usd": str(worst_each.quantize(Decimal("0.0001"))),
        "worst_case_four_calls_usd": str((worst_each * _MAX_REAL_CALLS).quantize(Decimal("0.0001"))),
        "safe": spent + worst_each * _MAX_REAL_CALLS <= budget,
    }


async def _recap_bundles() -> tuple[object | None, object | None, str]:
    """(editorial-order bundle, media-pool bundle, note) from a READ-ONLY production session, using
    the EXISTING weekly selection pipeline. The media pool feeds the SAME pipeline only stories with
    unexpired stored media (canary-level pool choice, disclosed - never a product ranking rule)."""
    engine = create_async_engine(
        settings.database_url, connect_args={"server_settings": {"default_transaction_read_only": "on"}},
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        selected, _ = await select_weekly_recap_stories(session)
        plain = await build_instagram_recap_bundle(session, selected=selected)
        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.weekly_recap_window_days)
        media_events = select(ImageCandidateRecord.news_event_id).where(
            ImageCandidateRecord.eligible_for_editorial.is_(True),
            ImageCandidateRecord.storage_status == ImageStorageStatus.STORED,
            ImageCandidateRecord.storage_key.is_not(None),
        )
        stories = list((await session.execute(
            select(Story).where(Story.updated_at >= cutoff, Story.first_event_id.in_(media_events))
        )).scalars().all())
        built = [c for c in [await _build_candidate(session, st) for st in stories] if c is not None]
        pool_selected, _ = select_weekly_recap_stories_from_candidates(built)
        pooled = await build_instagram_recap_bundle(session, selected=pool_selected)
    await engine.dispose()
    note = (f"editorial_selection={len(selected)} stories (with_media_in_bundle="
            f"{sum(1 for s in (plain.stories if plain else []) if s.image_bytes)}); "
            f"media_pool={len(built)} selected={len(pool_selected)}")
    return plain, pooled, note


async def main() -> None:
    out_dir = Path(sys.argv[1])
    mode = sys.argv[2] if len(sys.argv) > 2 else "fake"
    out_dir.mkdir(parents=True, exist_ok=True)
    real = mode == "real"

    preflight = None
    pricing = ModelRegistryPricingCatalog(build_model_registry())
    gateway_factory = None
    if real:
        from integrations.llm_gateway.boot import assemble_ai_integration_layer

        preflight = await _budget_preflight()
        (out_dir / "budget_preflight.json").write_text(json.dumps(preflight, indent=2), encoding="utf-8")
        print("BUDGET_PREFLIGHT", json.dumps(preflight))
        if not preflight["safe"]:
            print("SAFE_STOP: budget cannot accommodate four calls")
            return
        layer = assemble_ai_integration_layer(settings, FilePromptRepository(_PROMPTS))
        gateway_factory = lambda archetype, plan: layer.gateway  # noqa: E731

    plain_bundle, pool_bundle, recap_note = await _recap_bundles()
    if os.environ.get("B44_PREP"):
        print("PREP", recap_note, json.dumps([
            {"key": s.key, "title": s.title[:60], "has_image": s.image_bytes is not None}
            for s in (pool_bundle.stories if pool_bundle else [])], ensure_ascii=False))
        return
    if not real:
        gateway_factory = lambda archetype, plan: common.RoutingFakeGateway(  # noqa: E731
            common.editorial_decision(archetype).model_dump(), plan)

    calls = {"count": 0, "actual": Decimal(0)}
    ledger_spent = Decimal(preflight["spent_today_usd"]) if preflight else Decimal(0)
    worst_each = Decimal(preflight["worst_case_per_call_usd"]) if preflight else Decimal(0)
    daily_budget = Decimal(preflight["daily_budget_usd"]) if preflight else Decimal(0)
    captured: dict = {}
    real_call = cd_module._call_creative_director

    async def counting_call(gw, repo, *, prompt_name, director_input, prompt_version):
        if real:
            if calls["count"] >= _MAX_REAL_CALLS:
                raise RuntimeError("hard cap: no more than four real Creative Director calls")
            if ledger_spent + calls["actual"] + worst_each > daily_budget:
                raise RuntimeError("SAFE_STOP: projected spend would exceed the daily budget")
            calls["count"] += 1
        captured["director_input"] = director_input
        output, call = await real_call(gw, repo, prompt_name=prompt_name, director_input=director_input, prompt_version=prompt_version)
        captured["model_output"], captured["call"] = output, call
        if real:
            try:
                calls["actual"] += compute_call_cost(call, pricing)
            except Exception:  # noqa: BLE001
                calls["actual"] += worst_each
            (out_dir / f"raw_cd_call_{calls['count']}.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        return output, call

    cd_module._call_creative_director = counting_call
    prompt_repo = FilePromptRepository(_PROMPTS)
    summary = []
    shadow_engine = create_async_engine(f"postgresql+asyncpg://postgres:postgres@{os.environ.get('B44_SHADOW_DB_HOST', 'b44pg')}:5432/ai_newsroom_test")
    try:
        async with shadow_engine.connect() as connection:
            await connection.begin()
            async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
                runs = list(_ARCHETYPES) + ([] if real else ["news_recap_editorial_order"])
                for name in runs:
                    archetype = "news_recap" if name.startswith("news_recap") else name
                    bundle = None
                    if archetype == "news_recap":
                        bundle = plain_bundle if name == "news_recap_editorial_order" else pool_bundle
                    try:
                        summary.append(await _run_one(name, archetype, session, gateway_factory, prompt_repo, pricing, out_dir, bundle, captured, real))
                    except Exception as exc:  # noqa: BLE001 - record and continue; never retry a paid call
                        summary.append({"archetype": name, "status": "EXCEPTION", "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
            await connection.rollback()
    finally:
        cd_module._call_creative_director = real_call
        await shadow_engine.dispose()

    result = {"mode": mode, "real_calls": calls["count"], "actual_cost_usd": str(calls["actual"]), "recap_selection": recap_note, "runs": summary}
    (out_dir / "run_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("DONE", json.dumps({"mode": mode, "real_calls": calls["count"], "cost": str(calls["actual"])}))


async def _run_one(name, archetype, session, gateway_factory, prompt_repo, pricing, out_dir, recap_bundle, captured, real) -> dict:
    spec = common.SCENARIOS[archetype]
    captured.clear()
    trend_signal = None
    source_image = None
    evidence = list(spec["evidence"])
    if archetype == "news_recap":
        if recap_bundle is None:
            return {"archetype": name, "status": "NO_BUNDLE"}
        evidence = recap_bundle.evidence
    elif archetype == "news_insight":
        source_image = _load_b2_raw()
    elif archetype == "ai_hack":
        source_image = None  # no screenshot asset exists: plans must use graphic/typographic compositions
    else:
        source_image = _load_stored("images/ca/ca3f5f3f973f51f55baac90fcdeedea115707d1a398d40acdbe5da3f9484aa11.png")
        trend_signal = TrendSignal(
            signal_type=TrendSignalType.TOPIC_MOMENTUM, provenance=TrendSignalProvenance.MANUAL_EDITORIAL,
            topic=spec["decision"]["topic"], evidence=list(common.TREND_EVIDENCE),
        )
    opportunity = ContentOpportunity(
        id=f"b44-{name}-{uuid4()}", source_type=OpportunitySourceType.NEWS, story_id=str(uuid4()),
        news_value=1.0, audience_relevance=0.5, product_mention_allowed=False, evidence=evidence, confidence=0.5,
    )
    decision = common.editorial_decision(archetype)
    plan = None if real else common.fake_plan(archetype, recap_bundle)
    gateway = gateway_factory(archetype, plan)

    async def fixed_decision(gw, repo, *, decision_input):
        return decision, None

    async def fake_source(_s, _story):
        if source_image is None:
            return None, None, 0, 0
        return source_image, SimpleNamespace(id=uuid4(), candidate_id=f"b44-{name}"), 1, 1

    seen: dict = {}
    real_render, real_snapshot = trigger.render_instagram_carousel, trigger.build_package_snapshot
    delivery = AsyncMock(return_value=SimpleNamespace(sent=False, reason="b44_shadow_no_publication", delivery_id=None))

    def spy_render(pkg, **kw):
        seen["renders"] = real_render(pkg, **kw)
        return seen["renders"]

    def spy_snapshot(**kw):
        seen["package"] = kw["package"]
        return real_snapshot(**kw)

    trigger.generate_editorial_decision = fixed_decision
    trigger.render_instagram_carousel, trigger.build_package_snapshot = spy_render, spy_snapshot
    trigger._resolve_single_source_image, trigger.deliver_instagram_package = fake_source, delivery
    try:
        outcome = await trigger.evaluate_and_submit_instagram_opportunity(
            session, AsyncMock(), opportunity=opportunity, opportunity_summary=spec["summary"],
            gateway=gateway, prompt_repository=prompt_repo, phase_a_enabled=True,
            recap_bundle=recap_bundle if archetype == "news_recap" else None,
            trend_context=trend_signal.to_director_context() if trend_signal else "", trend_signal=trend_signal,
        )
    finally:
        trigger.render_instagram_carousel, trigger.build_package_snapshot = real_render, real_snapshot

    call = captured.get("call")
    model_output = captured.get("model_output") or {}
    cost = None
    if real and call is not None and call.model_used:
        try:
            cost = str(compute_call_cost(call, pricing))
        except Exception as exc:  # noqa: BLE001
            cost = f"unavailable:{type(exc).__name__}"
    package = seen.get("package")
    obs = package.media_plan.get("b4_observability") if package else None
    di = captured.get("director_input")
    target = out_dir / name
    target.mkdir(parents=True, exist_ok=True)
    images = []
    for i, r in enumerate(seen.get("renders", []), start=1):
        img = Image.open(io.BytesIO(r.image_bytes)).convert("RGB")
        img.save(target / f"slide_{i:02d}.png")
        images.append(img)
    if images:
        common.contact_sheet(images).save(target / "contact_sheet.png")
    identities = [s.get("resolved_asset_identity") for s in (obs or {}).get("slides", []) if s.get("resolved_asset_identity")]
    record = {
        "archetype": name, "mode": "real" if real else "fake", "prompt_version": cd_module.CAROUSEL_PROMPT_VERSION,
        "outcome_reason": outcome.reason, "gate_decision": outcome.gate_decision,
        "model": getattr(call, "model_used", None), "cost_usd": cost,
        "input_tokens": getattr(getattr(call, "usage", None), "input_tokens", None),
        "output_tokens": getattr(getattr(call, "usage", None), "output_tokens", None),
        "model_emitted_content_archetype": model_output.get("content_archetype"),
        "derived_content_archetype": (obs or {}).get("content_archetype"),
        "fatigue_note_passed_to_model": getattr(di, "fatigue_note", None),
        "media_note_passed_to_model": getattr(di, "media_note", None),
        "plan_media_strategy": (model_output.get("creative_execution_plan") or {}).get("media_strategy"),
        "slides_raw": [
            {k: sl.get(k) for k in ("role", "composition", "media_position", "media_scale", "media_subject", "must_match_story", "slide_copy")}
            for sl in model_output.get("slides", [])
        ],
        "overlay_requests_in_plan": sum(1 for sl in model_output.get("slides", []) if "overlay_mode" in sl and sl["overlay_mode"]),
        "overlay_executions": (obs or {}).get("overlay_operations_executed_total"),
        "dark_slides": common.dark_slide_count(images), "slide_total": len(images),
        "headline_overflow_slides": sum(1 for r in seen.get("renders", []) if r.evidence.text_clipped),
        "shared_asset_identity_repeats": len(identities) - len(set(identities)),
        "graphic_fallback_slides": sum(1 for s in (obs or {}).get("slides", []) if s.get("graphic_fallback_used")),
        "b4_observability": obs, "provider_image_calls": 0, "publication_calls": 0,
    }
    (target / "cd_structured_output.json").write_text(json.dumps(model_output or plan or {}, ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "manifest.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return record


def _load_stored(key: str) -> Image.Image:
    from integrations.storage.image_storage import LocalImageStorage

    return Image.open(io.BytesIO(LocalImageStorage(settings.image_storage_root).read(key))).convert("RGB")


def _load_b2_raw() -> Image.Image:
    return _load_stored("images/ff/ff5300e330b3126330077784b352405e7fbdf2236c46a202ab4c69becfc73d2f.png")


if __name__ == "__main__":
    asyncio.run(main())
