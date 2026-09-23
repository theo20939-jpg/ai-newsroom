"""v10.7 CREATIVE DIRECTOR PRODUCT VALIDATION (founder-authorized): can the Creative Director itself write KAGE content at the editorial
reference's level under prompt v10.7?

Exactly ONE real Creative Director call per archetype (4 total), through the unchanged trigger path, on the SAME four story/evidence
packages as the founder reference (the iteration-6r inputs: recap bundle and trend story pinned from the persisted evidence handles and
stored images; the rebuilt media note must equal the persisted one byte for byte before any call).
  - retries 0: the trigger's built-in contract retry is blocked (a second call for the same archetype raises before the provider);
    weak or contract-failing output is product evidence and is rendered for review as it is;
  - vision OFF: the persisted suitability verdicts are re-applied; the vision checker raises if touched;
  - image generation OFF: every generated slide of the new plan gets that archetype's ALREADY-PAID images in slide order (pairing by
    order, not by the new brief - disclosed); the image adapter raises if touched;
  - hard cap B51_CD_CAP_USD (default 1.10) enforced twice: the dry-run pass prices the four EXACT requests with the gateway's own cost
    estimator (worst case over every model the router may pick) before any provider call, and the diagnostic ledger's budget guard
    refuses any call that would exceed it.

Usage: python scripts/_instagram_v107_cd_validation.py <preserved it6r dir> <r2 final dir> <out dir> preflight|live
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts._instagram_phase_b51_acceptance as acc  # noqa: E402
import scripts._instagram_phase_b5_common as common  # noqa: E402
import scripts._instagram_quality_loop_it6r_complete as comp  # noqa: E402
import services.instagram_automatic_trigger as trigger  # noqa: E402
import services.instagram_creative_director as cd  # noqa: E402
import services.instagram_creative_media as media_mod  # noqa: E402
import services.instagram_source_suitability as suit_module  # noqa: E402
from core.config import settings  # noqa: E402
from integrations.llm_gateway.models.catalog import build_model_registry  # noqa: E402
from integrations.llm_gateway.providers.openai_image_adapter import GPT_IMAGE_2, OpenAIImageAdapter  # noqa: E402
from integrations.prompts.file_repository import FilePromptRepository  # noqa: E402
from services.cost_tracker import compute_call_cost  # noqa: E402
from services.pricing_catalog import ModelRegistryPricingCatalog  # noqa: E402

ORDER = ("ai_hack", "news_insight", "news_recap", "trend_generative")
NAMESPACE = os.environ.get("B51_DIAG_NAMESPACE", "instagram_v107_cd_validation")
CAP = Decimal(os.environ.get("B51_CD_CAP_USD", "1.10"))
CUMULATIVE_BEFORE = Decimal(os.environ.get("B51_CUMULATIVE_BEFORE_USD", "3.2907"))
EXPECT_PROMPT = os.environ.get("B51_EXPECT_PROMPT_VERSION", "10.7")
CUMULATIVE_CEILING = Decimal("5.00")


class SafeStop(RuntimeError):
    pass


class DryRunStop(RuntimeError):
    """Raised by the dry-run gateway after pricing the exact request: nothing ever reaches a provider."""


def _eligible_models():
    registry = build_model_registry()
    priced = []
    for model in registry.all_models():
        if model.provider_id != "openai" or not model.supports_structured_output:
            continue
        tier = next((t for t in model.pricing_tiers if t.condition == "standard"), None)
        if tier is not None:
            priced.append((tier.input_price_per_million + tier.output_price_per_million, model))
    cheapest = min(p for p, _ in priced)
    return registry, [m for p, m in priced if p <= cheapest * Decimal("3.0")]


def request_worst_case(request) -> dict[str, Decimal]:
    """The gateway's OWN estimator (the figure its budget guard checks) for this exact request, per model the router can pick."""
    from services.cost_estimator import CostEstimator

    registry, models = _eligible_models()
    estimator = CostEstimator(ModelRegistryPricingCatalog(registry))
    return {m.model_id: estimator.estimate(m, request).worst_case for m in models}


class DryGateway:
    def __init__(self, sink: dict, name: str) -> None:
        self.sink, self.name = sink, name

    async def generate(self, request):
        self.sink[self.name] = request_worst_case(request)
        raise DryRunStop("dry run: request priced, never sent")


def _pool(it6r: Path, r2: Path, name: str) -> list[tuple[bytes, str]]:
    base = r2 if name in ("news_recap", "trend_generative") else it6r
    return [(p.read_bytes(), p.name) for p in sorted((base / name).glob("generated_slide_*.png"))]


async def _run(src: Path, r2: Path, out: Path, *, live: bool) -> dict:
    bundle, trend_story, missing = comp._pinned_inputs(src)
    saved = {name: comp._saved(src, name) for name in ORDER}
    pools = {name: _pool(src, r2, name) for name in ORDER}
    state: dict = {"calls": {}, "worst": {}, "notes_checked": {}, "attached": {}, "actual": Decimal(0), "provider_image_calls": 0}
    current: dict = {}
    pricing = ModelRegistryPricingCatalog(build_model_registry())

    async def saved_vision(**_kw):
        return saved[current["name"]]["unsuitable"]

    async def no_vision(*_a, **_kw):
        raise SafeStop("a vision call was attempted - vision is OFF in this validation")

    real_note, real_subjects = trigger._carousel_media_note, trigger._carousel_media_subjects

    def note_with_preserved(**kw):
        note = real_note(**kw)
        return comp.restore_preserved_note_lines(note, saved["news_recap"]["media_note"], list(missing)) if kw.get("recap_bundle") is not None and missing else note

    def subjects_with_preserved(**kw):
        available, unsuitable = real_subjects(**kw)
        recap = kw.get("recap_bundle")
        if recap is None or not missing:
            return available, unsuitable
        order = [s.key for s in recap.stories]
        return (tuple(k for k in order if k in set(available) | set(missing)), tuple(k for k in order if k in set(unsuitable) | set(missing)))

    captured_holder: dict = {}
    real_call = cd._call_creative_director
    diag = acc._diag_redis() if live else None
    diag_tracker = None

    async def one_call(gw, repo, *, prompt_name, director_input, prompt_version):
        name = current["name"]
        if director_input.media_note != saved[name]["media_note"]:
            raise SafeStop(f"{name}: rebuilt media note differs from the persisted one - the story inputs are not the reference inputs")
        if list(director_input.allowed_evidence) != list(saved[name]["raw"]["evidence_handles"].values()):
            raise SafeStop(f"{name}: rebuilt evidence differs from the persisted evidence")
        state["notes_checked"][name] = True
        if state["calls"].get(name):
            raise SafeStop(f"{name}: a second Creative Director call (the contract retry) is blocked - retries are 0")
        state["calls"][name] = 1
        if live:
            worst = max(request_worst_case(_request_of(director_input, repo, prompt_name, prompt_version)).values())
            if state["actual"] + worst > CAP:
                raise SafeStop(f"{name}: spent {state['actual']} + worst {worst} would exceed the cap {CAP}")
        cap = captured_holder["c"]
        cap["director_input"] = director_input
        cap["user_text"] = cd._build_user_text(director_input, evidence_handles=True)
        output, call = await real_call(gw, repo, prompt_name=prompt_name, director_input=director_input, prompt_version=prompt_version)
        cap["model_output"], cap["call"] = output, call
        if live:
            cost = compute_call_cost(call, pricing)
            state["actual"] += cost
            await diag_tracker.record(uuid4(), "instagram_creative_director", call)
        return output, call

    async def attach_paid_image(**kw):
        """Image generation is OFF: the slide gets its archetype's next already-paid image (by order), never a provider call."""
        name, key = current["name"], kw["asset_key"]
        used = state["attached"].setdefault(name, [])
        raw, label = pools[name][len(used) % len(pools[name])]
        used.append({"slide": int(key), "reused_image": label, "cycled": len(used) >= len(pools[name])})
        image = media_mod._decode_publishable_image(raw)
        ref = f"generated:reused:{label}"
        return media_mod.InstagramMediaExecutionAsset(
            asset_key=key, media_mode=media_mod.InstagramMediaMode.GENERATED, status="generated_media", image=image, asset_ref=ref,
            generated_asset_ref=ref, provider="openai", model=GPT_IMAGE_2, prompt=None, size="1024x1536", quality="medium", raw_image_bytes=None,
            source_treatment="existing_paid_image_reused_generation_off", final_compositor_treatment="exact_russian_typography_canonical_logo_safe_zones")

    async def no_image(self, request):
        state["provider_image_calls"] += 1
        raise SafeStop("an image provider call was attempted - image generation is OFF in this validation")

    def raw_sink(event: str, payload: dict) -> None:
        target = out / current["name"]
        target.mkdir(parents=True, exist_ok=True)
        path = target / "raw_creative_director_output.json"
        if event == "raw_output":
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        elif path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            data["validation_error"] = payload
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    if live:
        import integrations.llm_gateway.boot as boot
        from integrations.llm_gateway.boot import assemble_ai_integration_layer
        from services.budget_guard import RedisBudgetGuard
        from services.cost_tracker import RedisCostTracker

        diag_settings = settings.model_copy(update={"llm_budget_mode": "enforce", "llm_daily_budget_usd": float(CAP)})
        boot.RedisBudgetGuard = lambda redis, st: RedisBudgetGuard(redis, st, ledger_namespace=NAMESPACE)
        layer = assemble_ai_integration_layer(diag_settings, FilePromptRepository(acc._PROMPTS), redis_client=diag)
        diag_tracker = RedisCostTracker(diag, pricing, ledger_namespace=NAMESPACE)
        gateway_factory = lambda name, plan: layer.gateway  # noqa: E731
    else:
        gateway_factory = lambda name, plan: DryGateway(state["worst"], name)  # noqa: E731

    patches = [
        (trigger, "_vision_unsuitable_subjects", saved_vision), (trigger, "_carousel_media_note", note_with_preserved),
        (trigger, "_carousel_media_subjects", subjects_with_preserved), (suit_module, "check_primary_suitability", no_vision),
        (suit_module, "_call_vision", no_vision), (cd, "_call_creative_director", one_call),
        (media_mod, "_execute_generated_asset", attach_paid_image), (OpenAIImageAdapter, "generate_image", no_image),
    ]
    originals = [(obj, attr, getattr(obj, attr)) for obj, attr, _ in patches]
    for obj, attr, value in patches:
        setattr(obj, attr, value)
    cd.set_raw_output_sink(raw_sink)
    prompt_repo = FilePromptRepository(acc._PROMPTS)
    records = []
    engine = create_async_engine(f"postgresql+asyncpg://postgres:postgres@{os.environ.get('B5_SHADOW_DB_HOST', 'igpq_pg')}:5432/ai_newsroom_test")
    try:
        async with engine.connect() as connection:
            await connection.begin()
            async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
                for name in ORDER:
                    current["name"] = name
                    captured: dict = {}
                    captured_holder["c"] = captured
                    try:
                        rec = await acc._run_one(name, session, gateway_factory, prompt_repo, pricing, out, bundle if name == "news_recap" else None,
                                                 trend_story, captured, True, None)
                    except Exception as exc:  # noqa: BLE001 - record; never retry
                        rec = {"archetype": name, "VALIDATION": "FAIL", "status": "EXCEPTION", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
                    rec["MODEL_SOURCE"] = "NEW v10.7 REAL CALL" if live else "DRY RUN"
                    rec["reused_paid_images"] = state["attached"].get(name, [])
                    rec["vision_calls"] = 0
                    records.append(rec)
            await connection.rollback()
        ledger = await diag.get(f"phase7:cost_ledger:{NAMESPACE}") if live else None
    finally:
        for obj, attr, value in originals:
            setattr(obj, attr, value)
        cd.set_raw_output_sink(None)
        await engine.dispose()
        if diag is not None:
            await diag.aclose()
    return {"records": records, "calls": state["calls"], "worst": state["worst"], "notes_checked": state["notes_checked"],
            "actual": state["actual"], "ledger": ledger, "provider_image_calls": state["provider_image_calls"], "missing_sources": missing}


def _request_of(director_input, repo, prompt_name, prompt_version):
    """The exact GenerateRequest _call_creative_director sends (same construction), for pricing before the call."""
    from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, Message

    prompt = repo.resolve(prompt_name, prompt_version)
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    return GenerateRequest(
        messages=[Message(role="system", content=[ContentPart(type="text", text=system_text)]),
                  Message(role="user", content=[ContentPart(type="text", text=cd._build_user_text(director_input, evidence_handles=True))])],
        response_mode="json_schema", response_schema=prompt.output_schema, max_tokens=cd._CREATIVE_DIRECTOR_MAX_TOKENS)


def _render_raw_for_review(out: Path, name: str, src: Path, r2: Path, rec: dict) -> None:
    """A plan the contract rejected is still product evidence: render it as written (clearly labelled), with the same reused media."""
    from services.instagram_carousel_layouts import render_carousel_slide
    from services.instagram_creative_media import derive_image_identity
    from services.instagram_visual_profiles import InstagramRenderProfile, profile_spec

    raw_path = out / name / "raw_creative_director_output.json"
    if not raw_path.exists():
        return
    plan = json.loads(raw_path.read_text(encoding="utf-8")).get("structured_output") or {}
    slides = plan.get("slides") or []
    pool = _pool(src, r2, name)
    spec = profile_spec(InstagramRenderProfile.CAROUSEL_SLIDE)
    sources = {}
    for key, (_e, _c, storage_key) in comp.PINNED.items():
        path = comp.STORE_ROOT / storage_key
        if path.exists():
            with Image.open(path) as decoded:
                sources[key] = decoded.convert("RGB")
    if name == "news_insight":
        import scripts._instagram_phase_b5_shadow as b5

        sources["source"] = b5._load_b2_raw()
    images, used = [], 0
    for i, slide in enumerate(slides):
        mode = {"source": "SOURCE", "generated": "GENERATED", "graphic": "GRAPHIC"}.get(slide.get("media_source") or "")
        assets = {}
        if mode == "GENERATED" and pool:
            with Image.open(io.BytesIO(pool[used % len(pool)][0])) as decoded:
                img = decoded.convert("RGB")
            used += 1
            assets["generated"] = (img, derive_image_identity(img))
        for region in (slide.get("layout") or {}).get("regions") or []:
            # the plan's own real source images (a recap story's photo, the insight's source), exactly as the live path resolves them
            ref = region.get("content_ref")
            if region.get("kind") == "media" and ref in sources and ref not in assets:
                assets[ref] = (sources[ref], derive_image_identity(sources[ref]))
        result = render_carousel_slide(spec=spec, role=slide.get("role", ""), index=i, total=len(slides), slide_copy=slide.get("slide_copy", ""),
                                       slide_body=slide.get("slide_body"), source_evidence=None, package_identity=f"review-{name}",
                                       visual_direction=slide.get("visual_direction"), media_mode=mode, layout_plan=slide.get("layout"),
                                       subject_assets=assets)
        result.image.save(out / name / f"slide_{i + 1:02d}.png")
        images.append(result.image)
    if images:
        common.contact_sheet(images).save(out / name / "contact_sheet.png")
    rec["rendered_for_review_despite_contract_failure"] = True


async def main() -> None:
    src, r2, out, mode = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
    if mode not in ("preflight", "live"):
        raise SystemExit("mode must be preflight or live")
    out.mkdir(parents=True, exist_ok=True)
    dry = await _run(src, r2, out / "_dry_run", live=False)
    per_call = {name: max(v.values()) for name, v in dry["worst"].items()}
    total = sum(per_call.values(), Decimal(0))
    preflight = {
        "requests_priced": sorted(dry["worst"]), "worst_by_model": {k: {m: str(x) for m, x in v.items()} for k, v in dry["worst"].items()},
        "worst_per_call_usd": {k: str(v) for k, v in per_call.items()}, "worst_total_usd": str(total), "cap_usd": str(CAP),
        "cumulative_before_usd": str(CUMULATIVE_BEFORE), "cumulative_worst_usd": str(CUMULATIVE_BEFORE + total),
        "media_notes_verified": dry["notes_checked"], "missing_source_exceptions": sorted(dry["missing_sources"]),
        "prompt_version": cd.CAROUSEL_PROMPT_VERSION, "dry_run_provider_image_calls": dry["provider_image_calls"],
    }
    preflight["safe"] = (len(per_call) == 4 and len(dry["notes_checked"]) == 4 and total <= CAP and CUMULATIVE_BEFORE + total < CUMULATIVE_CEILING
                         and cd.CAROUSEL_PROMPT_VERSION == EXPECT_PROMPT and dry["provider_image_calls"] == 0)
    (out / "validation_preflight.json").write_text(json.dumps(preflight, indent=2, ensure_ascii=False), encoding="utf-8")
    print("PREFLIGHT", json.dumps({k: v for k, v in preflight.items() if k != "worst_by_model"}, ensure_ascii=False))
    if mode == "preflight":
        return
    if not preflight["safe"]:
        print("SAFE_STOP: preflight failed; no provider call was made")
        return
    if settings.openai_api_key is None:
        print("SAFE_STOP: no provider credential in this process")
        return
    final = out / "final"
    live = await _run(src, r2, final, live=True)
    for rec in live["records"]:
        if rec.get("VALIDATION") != "PASS":
            _render_raw_for_review(final, rec["archetype"], src, r2, rec)
    # first pass vs critic: the deterministic editor over EVERY raw first-pass output (zero cost), including plans rejected earlier for
    # another reason - what the Creative Director did by itself stays separate from what the critic caught afterwards
    from services.instagram_editorial_critic import critique

    critic_report = {}
    for rec in live["records"]:
        name = rec["archetype"]
        raw_path = final / name / "raw_creative_director_output.json"
        if not raw_path.exists():
            continue
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        plan = raw.get("structured_output") or {}
        findings = critique(plan.get("slides") or [], list(comp._saved(src, name)["raw"]["evidence_handles"].values()), archetype=name,
                            caption=plan.get("final_caption") or "")
        critic_report[name] = {"first_pass_contract": rec.get("VALIDATION"), "acceptance_error": raw.get("validation_error"),
                               "critic_result": "REJECT" if any(f.severity == "blocking" for f in findings) else "PASS",
                               "blocking": [f.render() for f in findings if f.severity == "blocking"],
                               "advisory": [f.render() for f in findings if f.severity != "blocking"]}
    (final / "critic_report.json").write_text(json.dumps(critic_report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"creative_director_calls": sum(live["calls"].values()), "retries": 0, "image_calls": live["provider_image_calls"], "vision_calls": 0,
               "cost_usd": str(live["actual"]), "diagnostic_ledger_usd": live["ledger"], "cap_usd": str(CAP),
               "cumulative_usd": str(CUMULATIVE_BEFORE + Decimal(str(live["ledger"] or live["actual"]))), "runs": live["records"]}
    (final / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("DONE", json.dumps({k: v for k, v in summary.items() if k != "runs"}))
    for rec in live["records"]:
        print("ARCHETYPE", rec["archetype"], rec.get("VALIDATION"), rec.get("outcome_reason"), rec.get("model"), rec.get("cost_usd"), rec.get("error"))


if __name__ == "__main__":
    asyncio.run(main())
