"""Manual-only Phase B.5.1 REAL Creative Director acceptance run through the REAL live trigger
(`services.instagram_automatic_trigger.evaluate_and_submit_instagram_opportunity`): prompt v9 + Visual DNA v2 + the accepted declarative
layout system + the accepted family renderer.

Modes (argv[2]):
  real     - at most FOUR real carousel Creative Director calls (one per archetype, zero retries), real gateway, BudgetGuard in enforce mode,
             own cumulative cap, budget preflight with SAFE STOP. Text planning only: zero image-provider calls. There is NO fixture path in
             this mode: a failing archetype is recorded as FAIL and nothing is rendered in its place.
  fixture  - ZERO cost wiring check with a hand-authored v9-shaped plan (a DIAGNOSTIC FIXTURE, never model output). Refuses any output folder that
             is not explicitly marked FIXTURE_NOT_MODEL, so it can never be mistaken for the acceptance set.

Both modes: the editorial-DECISION step is deterministic (no extra LLM call), delivery is a recorder (zero publication), persistence goes to a
throwaway Postgres session that is rolled back, the automatic-generation flag is never touched.

Usage: python scripts/_instagram_phase_b51_acceptance.py <out_dir> <real|fixture>"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import scripts._instagram_phase_b5_common as common
import scripts._instagram_phase_b5_shadow as b5
import services.instagram_automatic_trigger as trigger
import services.instagram_creative_director as cd_module
from core.config import settings
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from schemas.instagram_creative import TERMINAL_ROLES, VISUAL_FAMILIES, InstagramCarouselCreative
from services.cost_tracker import compute_call_cost
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_layout_signature import infer_family
from services.instagram_meta_language_guard import find_meta_language
from services.instagram_trend_radar import TrendSignal, TrendSignalProvenance, TrendSignalType
from services.pricing_catalog import ModelRegistryPricingCatalog

_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_MAX_REAL_CALLS = 4
_ARCHETYPES = ("ai_hack", "news_insight", "news_recap", "trend_generative")
_EST_INPUT_TOKENS, _EST_OUTPUT_TOKENS = 16000, 9000


class FixtureSubstitutionError(RuntimeError):
    """Raised when fixture output would be written where real acceptance output belongs."""


def assert_no_fixture_substitution(mode: str, out_dir: Path) -> None:
    """The acceptance set (mode=real) can never contain fixture output, and fixture output can never land in an acceptance folder."""
    if mode == "fixture" and "FIXTURE_NOT_MODEL" not in out_dir.name:
        raise FixtureSubstitutionError(f"fixture mode must write to a folder marked FIXTURE_NOT_MODEL, got {out_dir.name!r}")
    if mode == "real" and "FIXTURE" in out_dir.name.upper():
        raise FixtureSubstitutionError("real acceptance output must not live in a fixture folder")
    if mode not in ("real", "fixture"):
        raise FixtureSubstitutionError(f"unknown mode {mode!r}")


def routed_worst_case_call_cost() -> Decimal:
    """Worst case for ONE Creative Director call on the models the router can actually pick: LOWEST_COST with the 3.0x cost ceiling
    (integrations/llm_gateway/routing/criteria.py) admits only models whose combined standard price is within 3x of the cheapest OpenAI
    structured model - never a more expensive model."""
    priced = []
    for model in build_model_registry().all_models():
        if model.provider_id != "openai" or not model.supports_structured_output:
            continue
        tier = next((t for t in model.pricing_tiers if t.condition == "standard"), None)
        if tier is not None:
            priced.append((tier.input_price_per_million + tier.output_price_per_million, tier))
    cheapest = min(p for p, _ in priced)
    eligible = [t for p, t in priced if p <= cheapest * Decimal("3.0")]
    return max(Decimal(_EST_INPUT_TOKENS) / 1_000_000 * t.input_price_per_million + Decimal(_EST_OUTPUT_TOKENS) / 1_000_000 * t.output_price_per_million for t in eligible)


async def _budget_preflight() -> dict:
    from core.redis import get_redis_client

    ns = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw = await get_redis_client().get(f"phase7:cost_ledger:{ns}")
    spent = Decimal(str(raw)) if raw is not None else Decimal(0)
    worst_each = routed_worst_case_call_cost()
    budget = Decimal(str(settings.llm_daily_budget_usd))
    return {
        "ledger_namespace": ns, "spent_today_usd": str(spent), "daily_budget_usd": str(budget), "budget_mode": settings.llm_budget_mode,
        "worst_case_per_call_usd": str(worst_each.quantize(Decimal("0.0001"))),
        "worst_case_four_calls_usd": str((worst_each * _MAX_REAL_CALLS).quantize(Decimal("0.0001"))),
        "assumed_tokens_per_call": {"input": _EST_INPUT_TOKENS, "output": _EST_OUTPUT_TOKENS},
        "safe": spent + worst_each * _MAX_REAL_CALLS <= budget,
    }


def _v9_fixture_plan(archetype: str, recap_bundle) -> dict:
    """DIAGNOSTIC FIXTURE ONLY: the B.5 hand-authored declarative plan adapted to the v9 contract (bounded roles, a family per slide)."""
    plan = common.fake_plan(archetype, recap_bundle)
    remap = {"impact": "evidence", "beat": "context", "explanation": "step", "data": "evidence", "problem": "context"}
    slides = []
    for i, slide in enumerate(plan["slides"]):
        role = remap.get(slide["role"], slide["role"])
        if role.startswith("story"):
            role = "story"
        if i == len(plan["slides"]) - 1 and role not in TERMINAL_ROLES:
            role = "takeaway"
        layout = slide.get("layout")
        slides.append({**slide, "role": role, "visual_family": infer_family(layout) if isinstance(layout, dict) else "light_utility_editorial",
                       "visual_family_reason": "fixture"})
    return {**plan, "slides": slides}


async def _trend_inputs(pool_bundle):
    """A REAL story (with its real facts and stored image) from the production read-only recap pool, marked as a manual-editorial trend
    signal. Nothing in it is instruction text."""
    for story in (pool_bundle.stories if pool_bundle else []):
        if story.image_bytes and len(story.evidence) >= 2 and any("а" <= ch.lower() <= "я" for ch in story.title):
            return story
    return None


async def main() -> None:
    out_dir = Path(sys.argv[1])
    mode = sys.argv[2] if len(sys.argv) > 2 else "fixture"
    assert_no_fixture_substitution(mode, out_dir)
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
            print("SAFE_STOP: budget cannot accommodate four calls; no provider call was made")
            return
        layer = assemble_ai_integration_layer(settings, FilePromptRepository(_PROMPTS))
        gateway_factory = lambda archetype, plan: layer.gateway  # noqa: E731

    plain_bundle, pool_bundle, recap_note = await b5._recap_bundles()
    trend_story = await _trend_inputs(pool_bundle)
    if os.environ.get("B51_PREP"):
        print("PREP", recap_note, "| trend_story:", (trend_story.title[:80], len(trend_story.evidence)) if trend_story else None)
        return
    if not real:
        gateway_factory = lambda archetype, plan: common.RoutingFakeGateway(  # noqa: E731
            _decision_for(archetype, trend_story).model_dump(), plan)

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
            captured["real_call_number"] = calls["count"]
        captured["director_input"] = director_input
        captured["user_text"] = cd_module._build_user_text(director_input)
        output, call = await real_call(gw, repo, prompt_name=prompt_name, director_input=director_input, prompt_version=prompt_version)
        captured["model_output"], captured["call"] = output, call
        if real:
            try:
                calls["actual"] += compute_call_cost(call, pricing)
            except Exception:  # noqa: BLE001
                calls["actual"] += worst_each
        return output, call

    cd_module._call_creative_director = counting_call
    prompt_repo = FilePromptRepository(_PROMPTS)
    summary = []
    shadow_engine = create_async_engine(f"postgresql+asyncpg://postgres:postgres@{os.environ.get('B5_SHADOW_DB_HOST', 'b5pg')}:5432/ai_newsroom_test")
    try:
        async with shadow_engine.connect() as connection:
            await connection.begin()
            async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
                for name in _ARCHETYPES:
                    bundle = pool_bundle if name == "news_recap" else None
                    try:
                        summary.append(await _run_one(name, session, gateway_factory, prompt_repo, pricing, out_dir, bundle, trend_story, captured, real))
                    except Exception as exc:  # noqa: BLE001 - record; NEVER retry a paid call and NEVER substitute a fixture
                        summary.append({"archetype": name, "REAL_MODEL": real, "VALIDATION": "FAIL", "status": "EXCEPTION",
                                        "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
            await connection.rollback()
    finally:
        cd_module._call_creative_director = real_call
        await shadow_engine.dispose()

    result = {"mode": mode, "REAL_MODEL": real, "real_calls": calls["count"], "actual_cost_usd": str(calls["actual"]), "fixture_substitutions": 0,
              "recap_selection": recap_note, "runs": summary}
    (out_dir / "run_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("DONE", json.dumps({"mode": mode, "real_calls": calls["count"], "cost": str(calls["actual"])}))


def _decision_for(name: str, trend_story):
    decision = common.editorial_decision(name)
    if name == "trend_generative" and trend_story is not None:
        data = decision.model_dump()
        data.update(source_summary=trend_story.title, topic=trend_story.title,
                    angle="Резкий контраст между ожиданием и реальностью, показанный визуально",
                    trend_rationale="Тема обсуждается прямо сейчас; берём визуальный приём, а не чужой материал.")
        return type(decision)(**data)
    return decision


async def _run_one(name, session, gateway_factory, prompt_repo, pricing, out_dir, recap_bundle, trend_story, captured, real) -> dict:
    spec = common.SCENARIOS[name]
    captured.clear()
    trend_signal = None
    source_image = None
    evidence = list(spec["evidence"])
    summary = spec["summary"]
    if name == "news_recap":
        if recap_bundle is None:
            return {"archetype": name, "REAL_MODEL": real, "VALIDATION": "FAIL", "status": "NO_BUNDLE"}
        evidence = recap_bundle.evidence
    elif name == "news_insight":
        source_image = b5._load_b2_raw()
    elif name == "ai_hack":
        source_image = None  # no real UI/screenshot asset exists for this how-to: the plan must use the media-free families
    else:
        if trend_story is None:
            return {"archetype": name, "REAL_MODEL": real, "VALIDATION": "FAIL", "status": "NO_REAL_TREND_STORY"}
        evidence = list(trend_story.evidence)
        summary = trend_story.title
        with Image.open(io.BytesIO(trend_story.image_bytes)) as decoded:
            source_image = decoded.convert("RGB")
        trend_signal = TrendSignal(signal_type=TrendSignalType.TOPIC_MOMENTUM, provenance=TrendSignalProvenance.MANUAL_EDITORIAL,
                                   topic=trend_story.title, evidence=list(trend_story.evidence[:3]))
    opportunity = ContentOpportunity(id=f"b51-{name}-{uuid4()}", source_type=OpportunitySourceType.NEWS, story_id=str(uuid4()),
                                     news_value=1.0, audience_relevance=0.5, product_mention_allowed=False, evidence=evidence, confidence=0.5)
    decision = _decision_for(name, trend_story)
    plan = None if real else _v9_fixture_plan(name, recap_bundle)
    gateway = gateway_factory(name, plan)

    async def fixed_decision(gw, repo, *, decision_input):
        return decision, None

    async def fake_source(_s, _story):
        if source_image is None:
            return None, None, 0, 0
        return source_image, SimpleNamespace(id=uuid4(), candidate_id=f"b51-{name}"), 1, 1

    seen: dict = {}
    real_render, real_snapshot = trigger.render_instagram_carousel, trigger.build_package_snapshot
    delivery = AsyncMock(return_value=SimpleNamespace(sent=False, reason="b51_shadow_no_publication", delivery_id=None))

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
            session, AsyncMock(), opportunity=opportunity, opportunity_summary=summary, gateway=gateway, prompt_repository=prompt_repo,
            phase_a_enabled=True, recap_bundle=recap_bundle if name == "news_recap" else None,
            trend_context=trend_signal.to_director_context() if trend_signal else "", trend_signal=trend_signal,
        )
    finally:
        trigger.render_instagram_carousel, trigger.build_package_snapshot = real_render, real_snapshot

    return _record(name, real, outcome, captured, seen, out_dir, pricing, evidence)


def _record(name, real, outcome, captured, seen, out_dir, pricing, evidence) -> dict:
    call = captured.get("call")
    model_output = captured.get("model_output") or {}
    package = seen.get("package")
    obs = package.media_plan.get("b4_observability") if package else None
    di = captured.get("director_input")
    target = out_dir / name
    target.mkdir(parents=True, exist_ok=True)
    cost = None
    if real and call is not None and call.model_used:
        try:
            cost = str(compute_call_cost(call, pricing))
        except Exception as exc:  # noqa: BLE001
            cost = f"unavailable:{type(exc).__name__}"

    images = []
    for i, r in enumerate(seen.get("renders", []), start=1):
        img = Image.open(io.BytesIO(r.image_bytes)).convert("RGB")
        img.save(target / f"slide_{i:02d}.png")
        images.append(img)
    if images:
        common.contact_sheet(images).save(target / "contact_sheet.png")

    validation = "PASS" if outcome.reason == "submitted" and images else "FAIL"
    contract_error = None
    if validation == "FAIL" and model_output:
        try:
            InstagramCarouselCreative.model_validate(model_output)
        except Exception as exc:  # noqa: BLE001 - record WHY the real output failed; never repair or retry it
            contract_error = f"{type(exc).__name__}: {str(exc)[:400]}"
    slides_raw = model_output.get("slides") or []
    obs_slides = (obs or {}).get("slides") or []
    roles = [s.get("role") for s in slides_raw]
    meta_hits = find_meta_language(
        {**{f"slide_{i}": s.get("slide_copy", "") for i, s in enumerate(slides_raw)}, "final_caption": model_output.get("final_caption") or "",
         "final_cta": model_output.get("final_cta") or ""},
        allowed_context=list(evidence),
    )
    per_slide = []
    for i, s in enumerate(slides_raw):
        o = obs_slides[i] if i < len(obs_slides) else {}
        per_slide.append({
            "index": i, "role": s.get("role"), "visual_family_chosen": s.get("visual_family"), "visual_family_reason": s.get("visual_family_reason"),
            "visual_family_executed": o.get("visual_family_executed"), "family_matches": o.get("visual_family_matches"),
            "media_subject": s.get("media_subject"), "media_function": s.get("media_function"), "must_match_story": s.get("must_match_story"),
            "background": (s.get("layout") or {}).get("background"), "arrangement": (s.get("layout") or {}).get("arrangement"),
            "layout_plan_applied": o.get("layout_plan_applied"), "layout_plan_rejected": o.get("layout_plan_rejected"),
            "layout_adaptations": o.get("layout_adaptations"), "actual_media": [{"subject": m["subject"], "identity": m["identity"]} for m in (o.get("media_regions") or [])],
            "unresolved_media": o.get("unresolved_media_regions"), "slide_copy": s.get("slide_copy"),
        })
    record = {
        "archetype": name, "REAL_MODEL": real, "VALIDATION": validation, "outcome_reason": outcome.reason, "gate_decision": outcome.gate_decision,
        "contract_error": contract_error, "prompt_version": cd_module.CAROUSEL_PROMPT_VERSION,
        "model": getattr(call, "model_used", None), "cost_usd": cost,
        "input_tokens": getattr(getattr(call, "usage", None), "input_tokens", None), "output_tokens": getattr(getattr(call, "usage", None), "output_tokens", None),
        "visual_dna_present_in_input": bool(getattr(di, "visual_dna_context", "")), "visual_dna_version": getattr(di, "visual_dna_version", None),
        "media_note_passed_to_model": getattr(di, "media_note", None), "fatigue_note_passed_to_model": getattr(di, "fatigue_note", None),
        "model_emitted_content_archetype": model_output.get("content_archetype"),
        "archetype_correction_required": (obs or {}).get("archetype_correction_required"),
        "roles": roles, "terminal_role": roles[-1] if roles else None, "terminal_role_valid": bool(roles) and roles[-1] in TERMINAL_ROLES,
        "families_chosen": [p["visual_family_chosen"] for p in per_slide], "families_valid": all(p["visual_family_chosen"] in VISUAL_FAMILIES for p in per_slide),
        "family_diversity": len({p["visual_family_chosen"] for p in per_slide}),
        "backgrounds": [p["background"] for p in per_slide], "light_slides": sum(1 for p in per_slide if p["background"] in ("paper", "soft")),
        "meta_language_hits": [h.__dict__ for h in meta_hits], "meta_language_leak": bool(meta_hits),
        "slides": per_slide, "visual_rhythm": model_output.get("visual_rhythm"),
        "declarative_slides": sum(1 for s in obs_slides if s.get("layout_plan_applied")),
        "legacy_role_fallback_slides": sum(1 for s in obs_slides if s.get("role_fallback_used")),
        "overlay_executions": (obs or {}).get("overlay_operations_executed_total"),
        "headline_overflow_slides": sum(1 for r in seen.get("renders", []) if r.evidence.text_clipped),
        "art_validation_passed": (obs or {}).get("art_validation_passed"), "art_blocking_issues": (obs or {}).get("art_blocking_issues"),
        "provider_image_calls": 0, "publication_calls": 0, "fixture_substitution": False,
    }
    (target / "creative_director_output.json").write_text(json.dumps(model_output, ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "render_manifest.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return record


if __name__ == "__main__":
    asyncio.run(main())
