"""Manual-only Phase B.4.3 REAL Creative Director shadow canary (text planning only).

One real carousel Creative Director call (prompt v6, real gateway, real BudgetGuard in `enforce`
mode) per archetype - at most FOUR real LLM calls in total, no retries. Everything after the model
returns is the real live-trigger path: `evaluate_and_submit_instagram_opportunity` -> v6 schema
validation -> package -> media executor -> renderer -> art validator -> editorial gate. The only
substitutions: the editorial-DECISION step is a deterministic fixture (so no second LLM call per
archetype), Telegram delivery is a recorder (zero publication), and persistence goes to a
throwaway Postgres session that is rolled back (shadow drafts never reach live history).
Zero image-provider calls. The automatic-generation flag is never touched.

Usage: python scripts/_instagram_phase_b43_real_cd_shadow.py <out_dir>"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import scripts._instagram_phase_b4_archetype_diagnostic as diag
import services.instagram_automatic_trigger as trigger
import services.instagram_creative_director as cd_module
from core.config import settings
from core.redis import get_redis_client
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from schemas.instagram_creative import InstagramEditorialDecision
from services.cost_tracker import compute_call_cost
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_recap_bundle import build_instagram_recap_bundle
from services.instagram_trend_radar import TrendSignal, TrendSignalProvenance, TrendSignalType
from services.pricing_catalog import ModelRegistryPricingCatalog
from services.weekly_recap_selection import select_weekly_recap_stories

_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_MAX_REAL_CALLS = 4
_HABR_EVIDENCE = [
    "Автор на Хабре описал переход от самых умных и дорогих моделей к более дешёвым.",
    "Главным критерием он выбрал стоимость выполненной задачи, а не максимальный intelligence index.",
]
_AI_HACK_EVIDENCE = [
    "Задача: длинный текст нужно быстро превратить в понятное решение.",
    "Шаг 1: вставить текст и попросить выделить только принятые решения, без описания проблемы.",
    "Шаг 2: попросить модель переформулировать вывод в чек-лист из трёх пунктов.",
    "Результат: вместо чтения длинного текста получается короткий чек-лист для проверки.",
]
_TREND_EVIDENCE = [
    "Локальная фикстура-референс: быстрая двухпанельная схема «ожидание vs реальность».",
    "Ритм: широкий план, затем резкий кадр-деталь; сама смена кадра несёт мысль, а не подпись.",
    "Ограничение оригинальности: нельзя копировать подпись и кадры референса, использовать только приём.",
]

_SCENARIOS = {
    "ai_hack": dict(
        summary="Практичный приём: как за две минуты превратить длинный текст в чек-лист решений",
        decision=dict(opportunity_type="EVERGREEN", angle_intent="HOW_TO", origin="EVERGREEN", purpose="VALUE",
                      topic="Промпт для разбора длинного текста", angle="Два шага вместо двадцати минут чтения"),
        evidence=_AI_HACK_EVIDENCE),
    "news_insight": dict(
        summary="Разработчик на Хабре перестал брать самую умную и дорогую ИИ-модель для каждой задачи",
        decision=dict(opportunity_type="NEWS", angle_intent="EXPLAINER", origin="NEWS", purpose="ENGAGEMENT",
                      topic="Выбор модели по стоимости результата", angle="Самая умная модель не всегда самая полезная"),
        evidence=_HABR_EVIDENCE),
    "news_recap": dict(
        summary="Главные истории недели в мире ИИ и технологий",
        decision=dict(opportunity_type="NEWS", angle_intent="EXPLAINER", origin="NEWS", purpose="REACH",
                      topic="Итоги недели", angle="Четыре истории недели, у каждой свой кадр"),
        evidence=[]),
    "trend_generative": dict(
        summary="Ожидание и реальность: мем-механика применительно к очередному ИИ-релизу",
        decision=dict(opportunity_type="NEWS_X_TREND", angle_intent="MEME", origin="TREND", purpose="REACH",
                      topic="Ожидание vs реальность в ИИ-релизах", angle="Резкий контраст обещаний и практики",
                      trend_rationale="Приём «ожидание vs реальность» уже знаком аудитории; берём только механику, не чужой материал."),
        evidence=_TREND_EVIDENCE),
}


def _decision(archetype: str) -> InstagramEditorialDecision:
    spec = _SCENARIOS[archetype]
    base = {
        "source_summary": spec["summary"], "why_now": "Есть конкретный повод обсудить это сейчас",
        "audience_value": "Понять главное и применить", "recommended_format": "carousel",
        "format_reason": "Последовательность кадров читается лучше одного изображения",
        "creative_direction": "Показать суть, объяснить, закрыть выводом",
        "product_connection": None, "trend_rationale": None, "trend_signal_type": None,
        "trend_signal_provenance": None, "supplementary_story_idea": None, "evidence_used": [],
    }
    base.update(spec["decision"])
    return InstagramEditorialDecision(**base)


def _worst_case_call_cost() -> Decimal:
    registry = build_model_registry()
    worst = Decimal(0)
    for model in registry.all_models():
        if model.provider_id != "openai" or not model.supports_structured_output:
            continue
        tier = next((t for t in model.pricing_tiers if t.condition == "standard"), None)
        if tier is None:
            continue
        worst = max(worst, Decimal(14000) / 1_000_000 * tier.input_price_per_million
                    + Decimal(8000) / 1_000_000 * tier.output_price_per_million)
    return worst


async def _budget_preflight() -> dict:
    redis = get_redis_client()
    ns = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw = await redis.get(f"phase7:cost_ledger:{ns}")
    spent = Decimal(str(raw)) if raw is not None else Decimal(0)
    worst_each = _worst_case_call_cost()
    budget = Decimal(str(settings.llm_daily_budget_usd))
    report = {
        "ledger_namespace": ns, "spent_today_usd": str(spent), "daily_budget_usd": str(budget),
        "budget_mode": settings.llm_budget_mode, "worst_case_per_call_usd": str(worst_each.quantize(Decimal("0.0001"))),
        "worst_case_four_calls_usd": str((worst_each * _MAX_REAL_CALLS).quantize(Decimal("0.0001"))),
        "safe": spent + worst_each * _MAX_REAL_CALLS <= budget,
    }
    return report


async def main() -> None:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    preflight = await _budget_preflight()
    (out_dir / "budget_preflight.json").write_text(json.dumps(preflight, indent=2), encoding="utf-8")
    print("BUDGET_PREFLIGHT", json.dumps(preflight))
    if not preflight["safe"]:
        print("SAFE_STOP: budget cannot accommodate four calls")
        return

    prompt_repo = FilePromptRepository(_PROMPTS)
    layer = assemble_ai_integration_layer(settings, prompt_repo)
    gateway = layer.gateway
    pricing = ModelRegistryPricingCatalog(build_model_registry())

    # Recap bundle: the EXISTING weekly selection + bundle builder, on a READ-ONLY production session.
    prod_engine = create_async_engine(
        settings.database_url, connect_args={"server_settings": {"default_transaction_read_only": "on"}},
    )
    recap_bundle = None
    recap_note = ""
    async with AsyncSession(prod_engine, expire_on_commit=False) as prod_session:
        selected, _rest = await select_weekly_recap_stories(prod_session)
        recap_note = f"weekly_selection_returned={len(selected)}"
        recap_bundle = await build_instagram_recap_bundle(prod_session, selected=selected)
    await prod_engine.dispose()

    shadow_engine = create_async_engine("postgresql+asyncpg://postgres:postgres@b43pg:5432/ai_newsroom_test")
    calls = {"count": 0}
    captured: dict = {}
    real_call = cd_module._call_creative_director

    async def counting_call(gw, repo, *, prompt_name, director_input, prompt_version):
        if calls["count"] >= _MAX_REAL_CALLS:
            raise RuntimeError("hard cap: no more than four real Creative Director calls")
        calls["count"] += 1
        captured["director_input"] = director_input
        output, call = await real_call(gw, repo, prompt_name=prompt_name, director_input=director_input, prompt_version=prompt_version)
        captured["model_output"], captured["call"] = output, call
        return output, call

    cd_module._call_creative_director = counting_call
    summary = []
    try:
        async with shadow_engine.connect() as connection:
            await connection.begin()
            async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
                for archetype in ("ai_hack", "news_insight", "news_recap", "trend_generative"):
                    summary.append(await _run_one(archetype, session, gateway, prompt_repo, pricing, out_dir, recap_bundle, captured))
            await connection.rollback()  # shadow drafts never persist
    finally:
        cd_module._call_creative_director = real_call
        await shadow_engine.dispose()

    post = await get_redis_client().get(f"phase7:cost_ledger:{preflight['ledger_namespace']}")
    result = {"real_calls": calls["count"], "recap_selection": recap_note, "ledger_after_usd": str(post), "runs": summary}
    (out_dir / "run_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("DONE", json.dumps({"real_calls": calls["count"], "ledger_before": preflight["spent_today_usd"], "ledger_after": str(post)}))


async def _run_one(archetype, session, gateway, prompt_repo, pricing, out_dir, recap_bundle, captured) -> dict:
    spec = _SCENARIOS[archetype]
    captured.clear()
    trend_signal = None
    source_image = None
    bundle = None
    evidence = list(spec["evidence"])
    if archetype == "news_recap":
        bundle = recap_bundle
        if bundle is None:
            return {"archetype": archetype, "status": "NO_BUNDLE", "reason": "existing recap selection returned <4 stories with usable data"}
        evidence = bundle.evidence
    elif archetype == "news_insight":
        source_image = diag._load_news_insight_raw(None)
    elif archetype == "ai_hack":
        source_image = diag._fixture((25, 25, 30), "AI_HACK fixture source")
    else:
        source_image = diag._fixture((30, 30, 35), "TREND fixture source")
        trend_signal = TrendSignal(
            signal_type=TrendSignalType.TOPIC_MOMENTUM, provenance=TrendSignalProvenance.MANUAL_EDITORIAL,
            topic=spec["decision"]["topic"], evidence=list(_TREND_EVIDENCE),
        )
    opportunity = ContentOpportunity(
        id=f"b43-{archetype}-{uuid4()}", source_type=OpportunitySourceType.NEWS, story_id=str(uuid4()),
        news_value=1.0, audience_relevance=0.5, product_mention_allowed=False, evidence=evidence, confidence=0.5,
    )
    decision = _decision(archetype)

    async def fixed_decision(gw, repo, *, decision_input):
        return decision, None

    async def fake_source(_s, _story):
        if source_image is None:
            return None, None, 0, 0
        return source_image, SimpleNamespace(id=uuid4(), candidate_id=f"b43-{archetype}"), 1, 1

    seen: dict = {}
    real_render, real_snapshot = trigger.render_instagram_carousel, trigger.build_package_snapshot
    delivery = AsyncMock(return_value=SimpleNamespace(sent=False, reason="b43_shadow_no_publication", delivery_id=None))

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
            gateway=gateway, prompt_repository=prompt_repo, phase_a_enabled=True, recap_bundle=bundle,
            trend_context=trend_signal.to_director_context() if trend_signal else "", trend_signal=trend_signal,
        )
    finally:
        trigger.render_instagram_carousel, trigger.build_package_snapshot = real_render, real_snapshot

    call = captured.get("call")
    model_output = captured.get("model_output") or {}
    cost = None
    if call is not None and call.model_used:
        try:
            cost = str(compute_call_cost(call, pricing))
        except Exception as exc:  # noqa: BLE001
            cost = f"unavailable:{type(exc).__name__}"
    package = seen.get("package")
    obs = package.media_plan.get("b4_observability") if package else None
    director_input = captured.get("director_input")
    record = {
        "archetype": archetype, "prompt_version": cd_module.CAROUSEL_PROMPT_VERSION, "outcome_reason": outcome.reason,
        "gate_decision": outcome.gate_decision,
        "model": getattr(call, "model_used", None), "cost_usd": cost,
        "input_tokens": getattr(getattr(call, "usage", None), "input_tokens", None),
        "output_tokens": getattr(getattr(call, "usage", None), "output_tokens", None),
        "model_emitted_content_archetype": model_output.get("content_archetype"),
        "derived_content_archetype": (obs or {}).get("content_archetype"),
        "fatigue_note_passed_to_model": getattr(director_input, "fatigue_note", None),
        "recap_subjects_offered": getattr(director_input, "recap_subjects", None),
        "plan_focal_point": (model_output.get("creative_execution_plan") or {}).get("focal_point"),
        "plan_media_strategy": (model_output.get("creative_execution_plan") or {}).get("media_strategy"),
        "slides_raw": [
            {k: s.get(k) for k in ("role", "composition", "media_position", "media_scale", "overlay_mode",
                                    "media_subject", "must_match_story", "media_need")}
            for s in model_output.get("slides", [])
        ],
        "b4_observability": obs,
        "provider_image_calls": 0, "publication_calls": 0,
    }
    target = out_dir / archetype
    target.mkdir(parents=True, exist_ok=True)
    (target / "cd_structured_output.json").write_text(json.dumps(model_output, ensure_ascii=False, indent=2), encoding="utf-8")
    images = []
    for i, r in enumerate(seen.get("renders", []), start=1):
        img = Image.open(io.BytesIO(r.image_bytes)).convert("RGB")
        img.save(target / f"slide_{i:02d}.png")
        images.append(img)
    if images:
        diag._build_contact_sheet(images).save(target / "contact_sheet.png")
    (target / "manifest.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return record


if __name__ == "__main__":
    asyncio.run(main())
