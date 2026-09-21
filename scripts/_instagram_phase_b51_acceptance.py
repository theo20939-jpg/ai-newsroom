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
import hashlib
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
REUSABLE_ARCHETYPES = ("ai_hack", "news_insight")  # B.5.1.2: these two archetypes may replay their saved B.5.1.1 REAL model output (zero provider calls)
_ARCHETYPES = ("ai_hack", "news_insight", "news_recap", "trend_generative")
_EST_INPUT_TOKENS, _EST_OUTPUT_TOKENS = 16000, 9000
DIAG_NAMESPACE = "instagram_b512_real_cd_acceptance"
DIAG_HARD_CAP_USD = Decimal("0.75")


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


def gateway_worst_case_by_model() -> dict[str, Decimal]:
    """The gateway's OWN worst-case estimate (services.cost_estimator.CostEstimator - the exact figure BudgetGuard checks) for the real v9
    Creative Director request, per model the router can pick, with a deliberately large representative input."""
    from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, Message
    from services.cost_estimator import CostEstimator

    repo = FilePromptRepository(_PROMPTS)
    prompt = repo.resolve(cd_module.CAROUSEL_PROMPT_NAME, cd_module._CAROUSEL_PROMPT_VERSION)
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    director_input = cd_module.CreativeDirectorInput(
        objective="saves", format="carousel", opportunity_summary="s" * 300, allowed_evidence=["x" * 300] * 12, locale="ru", fatigue_note="f" * 1500)
    request = GenerateRequest(
        messages=[Message(role="system", content=[ContentPart(type="text", text=system_text)]),
                  Message(role="user", content=[ContentPart(type="text", text=cd_module._build_user_text(director_input, evidence_handles=True))])],
        response_mode="json_schema", response_schema=prompt.output_schema, max_tokens=cd_module._CREATIVE_DIRECTOR_MAX_TOKENS)
    registry = build_model_registry()
    estimator = CostEstimator(ModelRegistryPricingCatalog(registry))
    priced = []
    for model in registry.all_models():
        if model.provider_id != "openai" or not model.supports_structured_output:
            continue
        tier = next((t for t in model.pricing_tiers if t.condition == "standard"), None)
        if tier is not None:
            priced.append((tier.input_price_per_million + tier.output_price_per_million, model))
    cheapest = min(p for p, _ in priced)
    return {m.model_id: estimator.estimate(m, request).worst_case for p, m in priced if p <= cheapest * Decimal("3.0")}


async def _production_ledger() -> Decimal:
    """READ-ONLY view of the production ledger key (never written by this run)."""
    from redis.asyncio import Redis

    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        ns = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        raw = await client.get(f"phase7:cost_ledger:{ns}")
        return Decimal(str(raw)) if raw is not None else Decimal(0)
    finally:
        await client.aclose()


def _diag_redis():
    """Isolated diagnostic ledger store: a dedicated Redis that is NOT the production one. Refuses to run otherwise."""
    from redis.asyncio import Redis

    url = os.environ.get("B51_DIAG_REDIS_URL", "")
    if not url or url == settings.redis_url:
        raise RuntimeError("SAFE_STOP: B51_DIAG_REDIS_URL must point to a dedicated diagnostic Redis distinct from production")
    return Redis.from_url(url, decode_responses=True)


async def _budget_preflight(diag, n_real: int = _MAX_REAL_CALLS) -> dict:
    prod_before = await _production_ledger()
    raw = await diag.get(f"phase7:cost_ledger:{DIAG_NAMESPACE}")
    diag_spent = Decimal(str(raw)) if raw is not None else Decimal(0)
    by_model = gateway_worst_case_by_model()
    worst_each = min(by_model.values())  # the router's LOWEST_COST pick; costlier candidates are fallback only
    return {
        "request_max_tokens": cd_module._CREATIVE_DIRECTOR_MAX_TOKENS, "gateway_worst_case_by_candidate_usd": {k: str(v) for k, v in by_model.items()},
        "diagnostic_namespace": DIAG_NAMESPACE, "diagnostic_hard_cap_usd": str(DIAG_HARD_CAP_USD), "diagnostic_spent_before_usd": str(diag_spent),
        "production_ledger_before_usd": str(prod_before), "production_daily_limit_usd": str(settings.llm_daily_budget_usd),
        "instagram_automatic_generation_enabled": bool(getattr(settings, "instagram_automatic_generation_enabled", False)),
        "worst_case_per_call_usd": str(worst_each.quantize(Decimal("0.0001"))),
        "real_calls_planned": n_real, "worst_case_planned_calls_usd": str((worst_each * n_real).quantize(Decimal("0.0001"))),
        "assumed_tokens_per_call": {"input": _EST_INPUT_TOKENS, "output": _EST_OUTPUT_TOKENS},
        "safe": diag_spent + worst_each * n_real <= DIAG_HARD_CAP_USD and all(v <= DIAG_HARD_CAP_USD - diag_spent for v in by_model.values()),
    }


class _ReplayGateway:
    """Returns a SAVED real model output verbatim (B.5.1.1). No provider call, no cost, no edits."""

    def __init__(self, output: dict) -> None:
        self.output = output

    async def generate(self, request):
        from integrations.llm_gateway.protocol import GenerateResponse
        from schemas.capability import CapabilityUsage

        return GenerateResponse(text=None, structured_output=self.output, finish_reason="stop", model_used=None, usage=CapabilityUsage())


def _load_replays(argv: list[str]) -> dict[str, dict]:
    """argv tail: `--replay-from <dir>` (a B.5.1.1 acceptance folder). Only REUSABLE_ARCHETYPES can be replayed; the file is loaded byte-for-byte."""
    if "--replay-from" not in argv:
        return {}
    base = Path(argv[argv.index("--replay-from") + 1])
    replays: dict[str, dict] = {}
    for name in REUSABLE_ARCHETYPES:
        path = base / name / "creative_director_output.json"
        if path.exists():
            replays[name] = {"output": json.loads(path.read_text(encoding="utf-8")), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "path": str(path)}
    return replays


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
    replays = _load_replays(sys.argv[3:]) if real else {}
    max_real = _MAX_REAL_CALLS - len(replays)

    preflight = None
    pricing = ModelRegistryPricingCatalog(build_model_registry())
    gateway_factory = None
    if real:
        from integrations.llm_gateway.boot import assemble_ai_integration_layer

        diag = _diag_redis()
        preflight = await _budget_preflight(diag, max_real)
        (out_dir / "budget_preflight.json").write_text(json.dumps(preflight, indent=2), encoding="utf-8")
        print("BUDGET_PREFLIGHT", json.dumps(preflight))
        if not preflight["safe"]:
            print("SAFE_STOP: budget cannot accommodate four calls; no provider call was made")
            return
        import integrations.llm_gateway.boot as boot
        from services.budget_guard import RedisBudgetGuard
        from services.cost_tracker import RedisCostTracker

        diag_settings = settings.model_copy(update={"llm_budget_mode": "enforce", "llm_daily_budget_usd": float(DIAG_HARD_CAP_USD)})
        boot.RedisBudgetGuard = lambda redis, st: RedisBudgetGuard(redis, st, ledger_namespace=DIAG_NAMESPACE)
        layer = assemble_ai_integration_layer(diag_settings, FilePromptRepository(_PROMPTS), redis_client=diag)
        diag_tracker = RedisCostTracker(diag, pricing, ledger_namespace=DIAG_NAMESPACE)
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
    ledger_spent = Decimal(preflight["diagnostic_spent_before_usd"]) if preflight else Decimal(0)
    worst_each = Decimal(preflight["worst_case_per_call_usd"]) if preflight else Decimal(0)
    daily_budget = DIAG_HARD_CAP_USD if preflight else Decimal(0)
    captured: dict = {}
    real_call = cd_module._call_creative_director

    async def counting_call(gw, repo, *, prompt_name, director_input, prompt_version):
        counted = real and not captured.get("replay")
        if counted:
            if calls["count"] >= max_real:
                raise RuntimeError(f"hard cap: no more than {max_real} real Creative Director calls in this run")
            if ledger_spent + calls["actual"] + worst_each > daily_budget:
                raise RuntimeError("SAFE_STOP: projected spend would exceed the daily budget")
            calls["count"] += 1
            captured["real_call_number"] = calls["count"]
        captured["director_input"] = director_input
        captured["user_text"] = cd_module._build_user_text(director_input, evidence_handles=cd_module._uses_evidence_handles(prompt_name, prompt_version))
        output, call = await real_call(gw, repo, prompt_name=prompt_name, director_input=director_input, prompt_version=prompt_version)
        captured["model_output"], captured["call"] = output, call
        if counted:
            try:
                calls["actual"] += compute_call_cost(call, pricing)
            except Exception:  # noqa: BLE001
                calls["actual"] += worst_each
            await diag_tracker.record(uuid4(), "instagram_creative_director", call)
        return output, call

    cd_module._call_creative_director = counting_call

    def raw_sink(event: str, payload: dict) -> None:
        target = captured.get("target_dir")
        if target is None:
            return
        target.mkdir(parents=True, exist_ok=True)
        path = target / "raw_creative_director_output.json"
        if event == "raw_output":  # written BEFORE any semantic validation can raise
            path.write_text(json.dumps({**payload, "model_source": captured.get("model_source")}, ensure_ascii=False, indent=2), encoding="utf-8")
        elif path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            saved["validation_error"] = payload
            path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")

    cd_module.set_raw_output_sink(raw_sink)
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
                        summary.append(await _run_one(name, session, gateway_factory, prompt_repo, pricing, out_dir, bundle, trend_story, captured, real, replays.get(name)))
                    except Exception as exc:  # noqa: BLE001 - record; NEVER retry a paid call and NEVER substitute a fixture
                        summary.append({"archetype": name, "REAL_MODEL": real, "VALIDATION": "FAIL", "status": "EXCEPTION",
                                        "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
            await connection.rollback()
    finally:
        cd_module._call_creative_director = real_call
        cd_module.set_raw_output_sink(None)
        await shadow_engine.dispose()

    accounting = {}
    if real:
        raw = await diag.get(f"phase7:cost_ledger:{DIAG_NAMESPACE}")
        accounting = {"diagnostic_namespace": DIAG_NAMESPACE, "diagnostic_hard_cap_usd": str(DIAG_HARD_CAP_USD),
                      "diagnostic_ledger_after_usd": str(raw), "production_ledger_before_usd": preflight["production_ledger_before_usd"],
                      "production_ledger_after_usd": str(await _production_ledger())}
        await diag.aclose()
    result = {"mode": mode, "REAL_MODEL": real, "real_calls": calls["count"], "actual_cost_usd": str(calls["actual"]), "fixture_substitutions": 0,
              "budget_accounting": accounting, "recap_selection": recap_note, "runs": summary}
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


async def _run_one(name, session, gateway_factory, prompt_repo, pricing, out_dir, recap_bundle, trend_story, captured, real, replay=None) -> dict:
    spec = common.SCENARIOS[name]
    captured.clear()
    captured["replay"] = replay is not None
    captured["target_dir"] = out_dir / name
    captured["model_source"] = "REUSED B.5.1.1 REAL OUTPUT" if replay is not None else ("NEW B.5.1.2 REAL CALL" if real else "FIXTURE_NOT_MODEL")
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
    gateway = _ReplayGateway(replay["output"]) if replay is not None else gateway_factory(name, plan)

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

    return _record(name, real, outcome, captured, seen, out_dir, pricing, evidence, replay)


def _record(name, real, outcome, captured, seen, out_dir, pricing, evidence, replay=None) -> dict:
    call = captured.get("call")
    model_output = captured.get("model_output") or {}
    package = seen.get("package")
    obs = package.media_plan.get("b4_observability") if package else None
    di = captured.get("director_input")
    target = out_dir / name
    target.mkdir(parents=True, exist_ok=True)
    cost = None
    if real and replay is None and call is not None and call.model_used:
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
            "layout_adaptations": o.get("layout_adaptations"),
            "calm_zone_adapted": o.get("calm_zone_adapted"), "calm_zone_requested": o.get("calm_zone_requested"), "calm_zone_executed": o.get("calm_zone_executed"),
            "composition_adapted_for_text_fit": o.get("composition_adapted_for_text_fit"), "actual_media": [{"subject": m["subject"], "identity": m["identity"]} for m in (o.get("media_regions") or [])],
            "unresolved_media": o.get("unresolved_media_regions"), "slide_copy": s.get("slide_copy"),
        })
    record = {
        "archetype": name, "REAL_MODEL": real, "MODEL_SOURCE": captured.get("model_source"),
        "REPLAY_OF_B511_OUTPUT_SHA256": (replay or {}).get("sha256"),
        "EVIDENCE_HANDLE_VALIDATION": "FAIL" if "UngroundedEvidenceError" in str(outcome.reason) else ("PASS" if model_output else "NOT_REACHED"),
        "VALIDATION": validation, "outcome_reason": outcome.reason, "gate_decision": outcome.gate_decision,
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
        "art_validation_passed": (obs or {}).get("art_validation_passed"), "art_blocking_issues": (obs or {}).get("art_blocking_issues"), "art_warnings": (obs or {}).get("art_warnings"),
        "layout_diversity_warning": any("layout_diversity" in w for w in ((obs or {}).get("art_warnings") or [])),
        "provider_image_calls": 0, "publication_calls": 0, "fixture_substitution": False,
    }
    raw_path = target / "raw_creative_director_output.json"
    record["validation_error"] = json.loads(raw_path.read_text(encoding="utf-8")).get("validation_error") if raw_path.exists() else None
    (target / "creative_director_output.json").write_text(json.dumps(model_output, ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "render_manifest.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return record


if __name__ == "__main__":
    asyncio.run(main())
