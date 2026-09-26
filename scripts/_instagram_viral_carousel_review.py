"""Offline founder review: VIRAL STORIES EXPAND INTO CAROUSELS (services.instagram_viral_format) - before any live run.

VIRAL (the only two persisted stories that ever became a Single - both from the frozen 5-11 Aug week):
  - DeepSeek / Habr '460 целей, ноль автономных взломов'   (Phase A: TREND product, MEME, single)
  - Hamster / Strava 'Physicist Rigged His Pet Hamster's Wheel' (Phase A: TREND product, MEME, single)
  Their PERSISTED Phase A decisions (no Phase A re-run) go through the new rule -> carousel; then the REAL pipeline pieces the trigger
  uses: source suitability (flat-card profile + vision), media note, the real Creative Director (carousel, media-first, the viral beat
  note), the no-photo -> generated promotion (viral, playful), the real media executor (gpt-image-2), the package builder, renderer and art gate.
STAYS SINGLE (a straightforward product update from the same week: OpenAI's free-tier model / limits change, which has a suitable real
  photo): a REAL Phase A decision as NEWS_INSIGHT -> the rule -> the real Director (single) -> its real photo -> render + art gate.

Isolation: no DB, no Telegram, no production config. LLM calls: pinned to gpt-5.6-luna, SDK retries off, refused before sending past
KAGE_VIRAL_LLM_CAP_USD (the e2e harness guard). Images: generation 'live' in THIS process only, an isolated capped ledger
(KAGE_VIRAL_IMAGE_CAP_USD), one attempt per image, dry-run quote first. Every picture is saved the moment it arrives.
Usage (OPENAI_API_KEY in the environment only): python scripts/_instagram_viral_carousel_review.py <out dir>
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import sys
from dataclasses import replace
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("KAGE_E2E_CAP_USD", os.environ.get("KAGE_VIRAL_LLM_CAP_USD", "0.60"))

import scripts._instagram_e2e_week as harness  # noqa: E402  (the provider guard + call capture; its module import touches no DB)

from PIL import Image, ImageDraw  # noqa: E402

import services.instagram_automatic_trigger as trigger  # noqa: E402
import services.instagram_creative_media as media_mod  # noqa: E402
from core.config import settings  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts/instagram_feed_product"
VIRAL = {
    "deepseek": {"run": ART / "daily_media_cleanliness_20260926/live/2026-08-05_2_meme_trend",
                 "image": ART / "last_three_blockers_20260926/daily/_image_storage/images/a5/a5b7675f1861cf31741262705fffda1abc1d31efcf413115287118c75f8fe2b6.png"},
    "hamster": {"run": ART / "e2e_week_2026-08-05_11/canary_run/2026-08-08_2_meme_trend",
                "image": ART / "e2e_week_2026-08-05_11/canary_run/_image_storage/images/e3/e32cd78c131719a12fdd8c38348ba541a2aa4411488030427a493569403fe92b.jpg"},
}
RECAP = ART / "daily_media_cleanliness_20260926/preserved/weekly_recap"
IMAGE_CAP = Decimal(os.environ.get("KAGE_VIRAL_IMAGE_CAP_USD", "1.30"))
IMAGE_NAMESPACE = "kage_viral_carousel_review_20260926"


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(harness._jsonable(payload), ensure_ascii=False, indent=1), encoding="utf-8")


def _director_input(persisted: dict, **overrides):
    from services.instagram_creative_director import CreativeDirectorInput

    names = {f.name for f in dataclasses.fields(CreativeDirectorInput)}
    data = {k: v for k, v in persisted.items() if k in names}
    for key in ("available_media_subjects", "unsuitable_media_subjects"):
        data[key] = tuple(data.get(key) or ())
    return CreativeDirectorInput(**{**data, **overrides})


async def _director(gateway, repo, director_input, fmt):
    from services.instagram_editorial_regeneration import build_default_regenerator
    from services.instagram_media_first import MediaFirstContractError

    regenerator = build_default_regenerator(gateway, repo)
    try:
        return await regenerator(director_input, fmt), None
    except MediaFirstContractError as exc:  # the trigger's own single bounded correction retry, nothing more
        retry = replace(director_input, contract_retry_note=f"Your previous attempt was rejected: {exc}. Fix exactly that and keep everything else.")
        return await regenerator(retry, fmt), str(exc)


def _image_guard():
    from redis.asyncio import Redis

    from services.budget_guard import RedisBudgetGuard
    from services.budgeted_image_execution import BudgetedImageExecutor

    diag = Redis.from_url("redis://localhost:6379/13", decode_responses=True)
    guard = RedisBudgetGuard(diag, settings.model_copy(update={"llm_budget_mode": "enforce", "llm_daily_budget_usd": float(IMAGE_CAP),
                                                               "redis_unavailable_policy": "fail_closed"}), ledger_namespace=IMAGE_NAMESPACE)
    media_mod.build_budgeted_image_executor = lambda: BudgetedImageExecutor(budget_guard=guard)
    return diag


async def _viral_story(name: str, cfg: dict, gateway, repo, out: Path) -> dict:
    from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
    from services.instagram_content_package import build_instagram_content_package
    from services.instagram_creative_media import derive_image_identity, execute_instagram_creative_media
    from services.instagram_format_director import ContentFormat, FormatDecision
    from services.instagram_generated_fallback import generated_plan_update, promote_no_photo_slides
    from services.instagram_platform_renderer import render_instagram_carousel
    from services.instagram_art_validator import validate_instagram_art
    from services.instagram_shadow_pipeline import ShadowPlanResult
    from services.instagram_viral_format import VIRAL_CAROUSEL_NOTE, viral_carousel_upgrade
    from services.kage_voice import load_kage_voice

    post = out / name
    harness.STATE["post"], harness.STATE["post_dir"] = name, post
    persisted = json.loads((cfg["run"] / "director_input.json").read_text(encoding="utf-8"))
    decision = json.loads(persisted["editorial_decision"])
    upgrade = viral_carousel_upgrade(decision, planned_product="TREND", executable_formats=["single", "carousel"])
    record = {"story": persisted["opportunity_summary"], "phase_a_recommended_format": decision["recommended_format"],
              "phase_a_angle_intent": decision.get("angle_intent"), "phase_a_format_reason": decision.get("format_reason"), "upgrade_signals": upgrade}
    if not upgrade:
        return {**record, "result": "stays single"}
    decision = {**decision, "recommended_format": "carousel", "viral_carousel_upgrade": upgrade, "phase_a_recommended_format": "single"}

    with Image.open(cfg["image"]) as decoded:
        source_image = decoded.convert("RGB")
    vision_unsuitable = await trigger._vision_unsuitable_subjects(gateway=gateway, prompt_repository=repo, source_image=source_image, recap_bundle=None)
    available, unsuitable = trigger._carousel_media_subjects(source_image=source_image, recap_bundle=None, vision_unsuitable=vision_unsuitable)
    record["source_suitability"] = {"available": list(available), "unsuitable": list(unsuitable)}
    director_input = _director_input(
        persisted, format="carousel", media_first=True, generated_media_available=True, fatigue_note="",
        editorial_decision=json.dumps(decision, ensure_ascii=False, sort_keys=True),
        visual_dna_context=trigger._visual_dna_context(), visual_dna_version=trigger._visual_dna_version(),
        media_note=trigger._carousel_media_note(source_image=source_image, recap_bundle=None, media_first=True, vision_unsuitable=vision_unsuitable),
        kage_voice_context=load_kage_voice().render_context(), available_media_subjects=available, unsuitable_media_subjects=unsuitable,
        planned_format="TREND", planned_archetype="trend_generative", viral_carousel_note=VIRAL_CAROUSEL_NOTE, contract_retry_note="",
    )
    outcome, retried = await _director(gateway, repo, director_input, ContentFormat.CAROUSEL)
    record["director_contract_retry"] = retried
    carousel = outcome.carousel
    _write(post / "director_carousel.json", carousel)
    suitable = set(available) - set(unsuitable)
    slides, promotions = promote_no_photo_slides(list(carousel.slides), suitable_subjects=suitable, recap=False, viral=True)
    if promotions:
        plan = carousel.creative_execution_plan
        carousel = carousel.model_copy(update={"slides": slides, **({"creative_execution_plan": plan.model_copy(update=generated_plan_update(viral=True))}
                                                                    if plan is not None else {})})
    record["promotions"] = promotions
    record["director_generated_slides"] = [i for i, s in enumerate(outcome.carousel.slides) if s.media_source == "generated"]
    outcome = replace(outcome, carousel=carousel)
    story_id = str(uuid4())
    slide_assets, _fallback, carousel, subject_assets = trigger._resolve_carousel_slide_assets(
        carousel, recap_bundle=None, source_image=source_image, source_ref="source-review")
    outcome = replace(outcome, carousel=carousel)
    creative_media = await execute_instagram_creative_media(
        slide_assets=slide_assets, creative=carousel, source_image=source_image, source_ref="source-review",
        opportunity_summary=persisted["opportunity_summary"], evidence=list(persisted["allowed_evidence"]), content_format="carousel",
        creative_id=f"viral-review-{story_id}", opportunity_id=story_id)
    for asset in creative_media.assets:
        if asset.image is not None and asset.media_mode.value == "GENERATED":
            (post / "generated").mkdir(parents=True, exist_ok=True)
            asset.image.save(post / "generated" / f"slide_{int(asset.asset_key) + 1:02d}.png")
    record["media"] = [{"slide": a.asset_key, "mode": a.media_mode.value, "status": a.status, "accounted_usd": a.accounted_cost_usd}
                       for a in creative_media.assets]
    if creative_media.status not in {"source_media", "generated_media", "typographic", "graphic", "media_plan_ready"}:
        return {**record, "result": f"media failed: {creative_media.status}"}
    opportunity = ContentOpportunity(id=story_id, source_type=OpportunitySourceType.NEWS, story_id=story_id, news_value=0.8,
                                     evidence=list(persisted["allowed_evidence"]), editorial_decision=decision)
    fmt_decision = FormatDecision(recommended_format=ContentFormat.CAROUSEL, alternatives=[ContentFormat.SINGLE, ContentFormat.REEL],
                                  why=decision.get("format_reason", ""), expected_role="education/reference", risk="low", confidence=0.8, warnings=[])
    shadow = ShadowPlanResult(campaign_name=None, campaign_phase=None, opportunity_description=persisted["opportunity_summary"],
                              primary_objective=persisted.get("objective", "shares"), audience_description="", recommended_format="carousel",
                              hook_family=None, creative_concept_summary=carousel.hook_slide.slide_copy, alternative_format=None,
                              alternative_objective=None, product_mention_allowed=False, evidence=list(persisted["allowed_evidence"]), confidence=0.8)
    pkg = build_instagram_content_package(opportunity=opportunity, format_decision=fmt_decision, shadow_plan=shadow, creative_outcome=outcome,
                                          source_image_ref=creative_media.media_ref)
    pkg = dataclasses.replace(pkg, media_plan={**pkg.media_plan, "media_execution": creative_media.execution_metadata(),
                                               "generated_no_photo_slides": promotions})
    renders = render_instagram_carousel(
        pkg, slide_images=creative_media.slide_images(), asset_identities=creative_media.slide_asset_identities(), subject_assets=subject_assets,
        slide_subject_assets={int(a.asset_key): {"generated": (a.image, a.asset_identity or derive_image_identity(a.image))}
                              for a in creative_media.assets if a.media_mode.value == "GENERATED" and a.image is not None and a.asset_key.isdigit()})
    for i, r in enumerate(renders, 1):
        (post / "slides").mkdir(parents=True, exist_ok=True)
        (post / "slides" / f"slide_{i:02d}.png").write_bytes(r.image_bytes)
    art = validate_instagram_art(pkg, renders)
    _write(post / "package.json", pkg)
    record.update(result="carousel", slides=len(renders), art_passed=art.passed, art_blocking=list(art.blocking_issues),
                  copy=[{"role": s.role, "copy": s.slide_copy, "body": s.slide_body} for s in carousel.slides], caption=pkg.caption)
    return record


def _finish_from_disk(name: str, cfg: dict, out: Path) -> dict:
    """A viral story whose Director plan, generated pictures and package are already saved (a later step failed): the same render and
    art gate, re-run from disk - never a second Director or image call."""
    from services.instagram_art_validator import validate_instagram_art
    from services.instagram_content_package import InstagramContentPackage
    from services.instagram_creative_media import derive_image_identity
    from services.instagram_format_director import ContentFormat
    from services.instagram_platform_renderer import render_instagram_carousel

    post = out / name
    data = json.loads((post / "package.json").read_text(encoding="utf-8"))
    data = {k: v for k, v in data.items() if k in {f.name for f in dataclasses.fields(InstagramContentPackage)}}
    data["content_format"] = ContentFormat(data["content_format"])
    pkg = InstagramContentPackage(**data)
    pictures = {int(p.stem.split("_")[1]) - 1: Image.open(p).convert("RGB") for p in sorted((post / "generated").glob("slide_*.png"))}
    from services.instagram_generated_fallback import viral_generated_heroes

    # the trigger's current step for a viral story: every generated picture is its slide's full-bleed hero (the saved package predates it)
    hero_slides, heroes = viral_generated_heroes(list(pkg.media_plan["slides"]))
    pkg = dataclasses.replace(pkg, media_plan={**pkg.media_plan, "slides": hero_slides,
                                               "generated_no_photo_slides": [*(pkg.media_plan.get("generated_no_photo_slides") or []),
                                                                             *({"slide": i, "treatment": "viral_hero"} for i in heroes)]})
    with Image.open(cfg["image"]) as decoded:
        source = decoded.convert("RGB")
    renders = render_instagram_carousel(
        pkg, slide_images=pictures, asset_identities={i: derive_image_identity(im) for i, im in pictures.items()},
        subject_assets={"source": (source, derive_image_identity(source))},
        slide_subject_assets={i: {"generated": (im, derive_image_identity(im))} for i, im in pictures.items()})
    for i, r in enumerate(renders, 1):
        (post / "slides" / f"slide_{i:02d}.png").write_bytes(r.image_bytes)
    art = validate_instagram_art(pkg, renders)
    persisted = json.loads((cfg["run"] / "director_input.json").read_text(encoding="utf-8"))
    decision = json.loads(persisted["editorial_decision"])
    carousel = json.loads((post / "director_carousel.json").read_text(encoding="utf-8"))
    return {"story": persisted["opportunity_summary"], "phase_a_recommended_format": decision["recommended_format"],
            "phase_a_angle_intent": decision.get("angle_intent"), "phase_a_format_reason": decision.get("format_reason"),
            "upgrade_signals": pkg.media_plan.get("editorial_decision") and json.loads(pkg.media_plan["editorial_decision"]).get("viral_carousel_upgrade")
            if isinstance(pkg.media_plan.get("editorial_decision"), str) else None,
            "result": "carousel", "slides": len(renders), "generated_pictures": len(pictures), "art_passed": art.passed,
            "art_blocking": list(art.blocking_issues), "generated_no_photo_slides": pkg.media_plan.get("generated_no_photo_slides"),
            "director_media_sources": [s.get("media_source") for s in carousel["slides"]],
            "copy": [{"role": s["role"], "copy": s["slide_copy"], "body": s.get("slide_body")} for s in carousel["slides"]], "caption": pkg.caption}


async def _stays_single(gateway, repo, out: Path) -> dict:
    """A straightforward product update through a REAL Phase A decision (NEWS_INSIGHT) -> the rule -> the real single Director."""
    from services.instagram_art_validator import validate_instagram_art
    from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
    from services.instagram_content_package import build_instagram_content_package
    from services.instagram_creative_director import InstagramEditorialDecisionInput, generate_editorial_decision
    from services.instagram_creative_media import execute_instagram_creative_media
    from services.instagram_director_context import load_instagram_director_context
    from services.instagram_format_director import ContentFormat, FormatDecision
    from services.instagram_platform_renderer import render_instagram_feed_image
    from services.instagram_shadow_pipeline import ShadowPlanResult
    from services.instagram_viral_format import viral_carousel_upgrade

    key = os.environ.get("KAGE_VIRAL_SINGLE_STORY", "story_5")
    post = out / f"stays_single_{key}"
    harness.STATE["post"], harness.STATE["post_dir"] = post.name, post
    recap = json.loads((RECAP / "director_input.json").read_text(encoding="utf-8"))
    evidence = [e for e, k in recap["evidence_story_keys"].items() if k == key]
    title = next(s for s in json.loads((RECAP / "bundle.json").read_text(encoding="utf-8"))["stories"] if s["key"] == key)["title"]
    suitable_photo = next(v for v in json.loads((RECAP / "vision_verdicts.json").read_text(encoding="utf-8")) if v["subject_key"] == key)["suitable"]
    decision, _call = await generate_editorial_decision(gateway, repo, decision_input=InstagramEditorialDecisionInput(
        source_type="NEWS", source_summary=title, allowed_evidence=evidence, brand_context=load_instagram_director_context(),
        executable_formats=["single", "carousel"], planned_format="NEWS_INSIGHT"))
    decision_payload = decision.model_dump()
    upgrade = viral_carousel_upgrade(decision_payload, planned_product="NEWS_INSIGHT", executable_formats=["single", "carousel"])
    record = {"story": title, "phase_a_recommended_format": decision.recommended_format, "phase_a_angle_intent": decision.angle_intent,
              "phase_a_opportunity_type": decision.opportunity_type, "phase_a_format_reason": decision.format_reason, "upgrade_signals": upgrade}
    if decision.recommended_format != "single":
        return {**record, "result": f"Phase A chose {decision.recommended_format} - not a Single to keep; the rule never downgrades"}
    if upgrade:
        return {**record, "result": "UPGRADED - the rule was not selective"}
    with Image.open(BytesIO((RECAP / f"story_media/{key}.img").read_bytes())) as decoded:
        photo = decoded.convert("RGB")
    from services.instagram_creative_director import CreativeDirectorInput

    selection = ({"suitable": True, "selected": "source", "checks": [{"subject_key": "source", "size": list(photo.size), "basis": "recorded recap vision verdict"}]}
                 if suitable_photo else {"suitable": False, "selected": None, "checks": [{"subject_key": "source", "image_kind": "recorded recap vision verdict: unsuitable"}]})
    director_input = CreativeDirectorInput(
        objective="saves", format="single", opportunity_summary=title, allowed_evidence=evidence, external_news_entities_allowed=True,
        locale="ru", editorial_decision=json.dumps(decision_payload, ensure_ascii=False, sort_keys=True), planned_format="NEWS_INSIGHT",
        planned_archetype="news_insight", media_note=trigger._daily_media_note(selection), generated_media_available=True)
    outcome, _retried = await _director(gateway, repo, director_input, ContentFormat.SINGLE)
    single = outcome.single
    if not suitable_photo:  # the trigger's own boundary: no suitable photo -> a generated picture, never the unsuitable one
        single, _changed = trigger._demote_source_plan(single, generation=True)
        outcome = replace(outcome, single=single)
        photo = None
    story_id = str(uuid4())
    media = await execute_instagram_creative_media(creative=single, source_image=photo, source_ref=f"{key}-photo" if photo else None, opportunity_summary=title,
                                                   evidence=evidence, content_format="single", creative_id=f"viral-review-single-{story_id}",
                                                   opportunity_id=story_id)
    opportunity = ContentOpportunity(id=story_id, source_type=OpportunitySourceType.NEWS, story_id=story_id, news_value=0.7, evidence=evidence,
                                     editorial_decision=decision_payload)
    fmt = FormatDecision(recommended_format=ContentFormat.SINGLE, alternatives=[ContentFormat.CAROUSEL], why=decision.format_reason,
                         expected_role="hero/breaking/statement", risk="low", confidence=0.7, warnings=[])
    shadow = ShadowPlanResult(campaign_name=None, campaign_phase=None, opportunity_description=title, primary_objective="saves",
                              audience_description="", recommended_format="single", hook_family=None, creative_concept_summary=single.creative_angle,
                              alternative_format=None, alternative_objective=None, product_mention_allowed=False, evidence=evidence, confidence=0.7)
    pkg = build_instagram_content_package(opportunity=opportunity, format_decision=fmt, shadow_plan=shadow, creative_outcome=outcome,
                                          source_image_ref=media.media_ref)
    pkg = dataclasses.replace(pkg, media_plan={**pkg.media_plan, "media_execution": media.execution_metadata(), "source_media_suitability": selection})
    render = render_instagram_feed_image(pkg, source_image=media.image)
    if media.image is not None and media.media_strategy == "generated_media":
        (post / "generated").mkdir(parents=True, exist_ok=True)
        media.image.save(post / "generated" / "single.png")
    (post / "slides").mkdir(parents=True, exist_ok=True)
    (post / "slides" / "slide_01.png").write_bytes(render.image_bytes)
    art = validate_instagram_art(pkg, [render])
    _write(post / "package.json", pkg)
    return {**record, "result": "stays single", "media_strategy": media.media_strategy, "treatment": render.evidence.source_image_treatment,
            "art_passed": art.passed, "art_blocking": list(art.blocking_issues), "on_image_copy": single.on_image_copy}


def _before_single(name: str, cfg: dict, out: Path) -> Path:
    """The old Single: its accepted render when one was captured, else the persisted package re-rendered offline (zero cost)."""
    slide = cfg["run"] / "slides" / "slide_01.png"
    if slide.exists():
        return slide
    from services.instagram_content_package import InstagramContentPackage
    from services.instagram_format_director import ContentFormat
    from services.instagram_platform_renderer import render_instagram_feed_image

    data = json.loads((cfg["run"] / "package.json").read_text(encoding="utf-8"))
    data = {k: v for k, v in data.items() if k in {f.name for f in dataclasses.fields(InstagramContentPackage)}}
    data["content_format"] = ContentFormat(data["content_format"])
    with Image.open(cfg["image"]) as decoded:
        render = render_instagram_feed_image(InstagramContentPackage(**data), source_image=decoded.convert("RGB"))
    path = out / name / "before_single_rerendered.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render.image_bytes)
    return path


def _sheet(out: Path, rows: list[tuple[str, list[Path]]]) -> None:
    th, label = 330, 34
    width = max(sum(round(Image.open(p).width * th / Image.open(p).height) + 10 for p in files) for _, files in rows if files) + 24
    sheet = Image.new("RGB", (width, sum(th + label + 18 for _ in rows) + 12), (246, 246, 246))
    draw, y = ImageDraw.Draw(sheet), 12
    for title, files in rows:
        draw.text((12, y + 10), title, fill=(160, 30, 30) if title.startswith("BEFORE") else (20, 20, 20))
        x = 12
        for path in files:
            im = Image.open(path).convert("RGB")
            w = round(im.width * th / im.height)
            sheet.paste(im.resize((w, th)), (x, y + label))
            x += w + 10
        y += th + label + 18
    sheet.save(out / "viral_carousel_contact_sheet.png")


async def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    from redis.asyncio import Redis

    import integrations.llm_gateway.boot as boot
    from integrations.llm_gateway.boot import assemble_ai_integration_layer
    from integrations.llm_gateway.models.catalog import build_model_registry
    from integrations.prompts.file_repository import FilePromptRepository
    from services.budget_guard import RedisBudgetGuard
    from services.cost_estimator import CostEstimator
    from services.cost_tracker import RedisCostTracker
    from services.pricing_catalog import ModelRegistryPricingCatalog

    namespace = os.environ.get("KAGE_VIRAL_LLM_NAMESPACE", "kage_viral_carousel_llm_20260926")
    diag = Redis.from_url(harness.DIAG_REDIS_URL, decode_responses=True)
    if await diag.get(f"phase7:cost_ledger:{namespace}"):
        raise SystemExit("the LLM ledger already holds spend for this review - it never runs twice")
    registry = build_model_registry()
    models = {m.model_id: m for m in registry.all_models()}
    pricing = ModelRegistryPricingCatalog(registry)
    diag_settings = settings.model_copy(update={"llm_budget_mode": "enforce", "llm_daily_budget_usd": float(harness.CAP),
                                                "enabled_providers": ["openai"], "redis_unavailable_policy": "fail_closed"})
    boot.RedisBudgetGuard = lambda redis, st: RedisBudgetGuard(redis, st, ledger_namespace=namespace)
    repo = FilePromptRepository(ROOT / "prompts")
    layer = assemble_ai_integration_layer(diag_settings, repo, redis_client=diag)
    harness._install_provider_guard(pricing, CostEstimator(pricing), models, RedisCostTracker(diag, pricing, ledger_namespace=namespace))
    image_diag = _image_guard()
    settings.instagram_image_generation_mode = "live"  # in-process only; the capped image ledger bounds every picture
    import services.instagram_source_suitability as suit

    verdicts: list = []
    suit.set_verdict_sink(verdicts)
    report: dict = {"llm_cap_usd": str(harness.CAP), "image_cap_usd": str(IMAGE_CAP)}
    previous = json.loads((out / "report.json").read_text(encoding="utf-8")) if (out / "report.json").exists() else {}
    for name, cfg in VIRAL.items():
        try:
            if (out / name / "package.json").exists() and (out / name / "generated").exists():
                report[name] = _finish_from_disk(name, cfg, out)  # already paid for: re-render + gate only
                report[name]["reused_from_run"] = True
                continue
            report[name] = await _viral_story(name, cfg, layer.gateway, repo, out)
        except Exception as exc:  # noqa: BLE001 - recorded, never retried
            report[name] = {"result": f"error: {type(exc).__name__}: {str(exc)[:400]}"}
        print(name, report[name].get("result"), report[name].get("art_passed"), flush=True)
    try:
        report["stays_single"] = await _stays_single(layer.gateway, repo, out)
    except Exception as exc:  # noqa: BLE001
        report["stays_single"] = {"result": f"error: {type(exc).__name__}: {str(exc)[:400]}"}
    print("stays_single", report["stays_single"].get("result"), flush=True)
    report["vision_verdicts"] = verdicts
    report["previous_runs"] = [previous] if previous else []
    report["llm_calls"] = harness.STATE["calls"]
    report["llm_spent_usd"] = str(harness.STATE["spent"])
    report["image_ledger_usd"] = await image_diag.get(f"phase7:cost_ledger:{IMAGE_NAMESPACE}")
    _write(out / "report.json", report)
    rows = []
    for name, cfg in VIRAL.items():
        rows.append((f"BEFORE - {name}: old Single ({report[name].get('phase_a_angle_intent')} / Phase A single)", [_before_single(name, cfg, out)]))
        rows.append((f"AFTER - {name}: viral Carousel ({report[name].get('result')}, art gate {report[name].get('art_passed')})",
                     sorted((out / name / "slides").glob("slide_*.png"))))
    single_key = os.environ.get("KAGE_VIRAL_SINGLE_STORY", "story_5")
    rows.append((f"STAYS SINGLE - one-beat news ({report['stays_single'].get('phase_a_angle_intent')}): {report['stays_single'].get('result')}",
                 sorted((out / f"stays_single_{single_key}" / "slides").glob("slide_*.png"))))
    _sheet(out, [r for r in rows if r[1]])
    print(json.dumps({"llm_spent_usd": report["llm_spent_usd"], "image_ledger_usd": report["image_ledger_usd"],
                      "calls": [(c["post"], c["kind"], c.get("status"), c.get("cost_usd")) for c in harness.STATE["calls"]]}, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
