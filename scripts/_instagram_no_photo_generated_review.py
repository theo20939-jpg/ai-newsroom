"""Offline before/after for the founder rule NO SUITABLE PHOTO => GENERATED IMAGE, on the already accepted persisted packages:
the live Single (DeepSeek/Habr), the final live Reel (gym/vc.ru), the accepted Adobe Carousel and the accepted Weekly Recap.

No Creative Director call, no Phase A, no vision: the persisted Director plans are reused as-is. The CURRENT deterministic promotion
(services.instagram_generated_fallback) decides which slides get a generated image; the real media executor
(services.instagram_creative_media._execute_generated_asset -> gpt-image-2 through the budgeted image executor) generates them; the CURRENT
renderer and art gate produce and judge the 'after'. The 'before' is the accepted persisted render, untouched.

Safety: generation runs in THIS process only (settings.instagram_image_generation_mode set in-process, never in any config file); the
budget guard is an isolated diagnostic ledger (redis db 13, its own namespace, enforce mode) whose cap is KAGE_NOPHOTO_CAP_USD; pass 1 is
a DRY RUN (quotes + prompts, zero spend) and the live pass runs only when every quote fits the cap. One attempt per image, no retry.
Usage (OPENAI_API_KEY in the environment only): python scripts/_instagram_no_photo_generated_review.py <out dir> [--live]
"""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
import os
import sys
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw  # noqa: E402

import services.instagram_creative_media as media_mod  # noqa: E402
from core.config import settings  # noqa: E402
from services.instagram_art_validator import validate_instagram_art  # noqa: E402
from services.instagram_content_package import InstagramContentPackage  # noqa: E402
from services.instagram_creative_media import derive_image_identity  # noqa: E402
from services.instagram_format_director import ContentFormat  # noqa: E402
from services.instagram_generated_fallback import generated_plan_update, promote_no_photo_slides  # noqa: E402
from services.instagram_platform_renderer import render_instagram_carousel, render_instagram_feed_image, render_instagram_reel_cover  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REVIEW = ROOT / "artifacts/instagram_feed_product/daily_media_cleanliness_20260926"
POSTS = {
    "SINGLE": REVIEW / "live/2026-08-05_2_meme_trend",
    "REEL": REVIEW / "live_reel_final/2026-08-10_2_meme_trend",
    "CAROUSEL": REVIEW / "preserved/carousel_adobe",
    "WEEKLY RECAP": REVIEW / "preserved/weekly_recap",
}
CAP = Decimal(os.environ.get("KAGE_NOPHOTO_CAP_USD", "1.00"))
NAMESPACE = "kage_no_photo_generated_20260926"


def _package(run: Path) -> InstagramContentPackage:
    data = json.loads((run / "package.json").read_text(encoding="utf-8"))
    data = {k: v for k, v in data.items() if k in {f.name for f in dataclasses.fields(InstagramContentPackage)}}
    data["content_format"] = ContentFormat(data["content_format"])
    return InstagramContentPackage(**data)


def _story_media(run: Path) -> dict:
    out = {}
    for path in sorted((run / "story_media").glob("*.img")) if (run / "story_media").exists() else []:
        image = Image.open(BytesIO(path.read_bytes()))
        image.load()
        out[path.stem] = (image.convert("RGB"), derive_image_identity(image))
    return out


def _saved(out: Path, job: dict) -> Path:
    return out / "generated" / (job["name"].lower().replace(" ", "_") + ".png")


async def _generate(jobs: list[dict], mode: str, out: Path | None = None) -> list[dict]:
    """One `_execute_generated_asset` per job through an isolated, capped ledger. Live pictures are written to disk the moment they
    arrive (a later render error never costs a second paid call - re-render with --reuse)."""
    from redis.asyncio import Redis

    from services.budget_guard import RedisBudgetGuard
    from services.budgeted_image_execution import BudgetedImageExecutor

    diag = Redis.from_url("redis://localhost:6379/13", decode_responses=True)
    guard = RedisBudgetGuard(diag, settings.model_copy(update={"llm_budget_mode": "enforce", "llm_daily_budget_usd": float(CAP),
                                                            "redis_unavailable_policy": "fail_closed"}),
                             ledger_namespace=NAMESPACE)
    real = media_mod.build_budgeted_image_executor
    media_mod.build_budgeted_image_executor = lambda: BudgetedImageExecutor(budget_guard=guard)
    try:
        results = []
        for job in jobs:
            asset = await media_mod._execute_generated_asset(
                asset_key=job["asset_key"], slide=job["slide"], plan=job["plan"], opportunity_summary=job["summary"],
                evidence=job["evidence"], content_format=job["format"], creative_id=job["creative_id"],
                opportunity_id=job["opportunity_id"], effective_mode=mode)
            if out is not None and asset.image is not None:
                _saved(out, job).parent.mkdir(parents=True, exist_ok=True)
                asset.image.save(_saved(out, job))
            results.append({"job": job["name"], "status": asset.status, "reserved_usd": asset.reserved_cost_usd,
                            "accounted_usd": asset.accounted_cost_usd, "provider_request_id": asset.provider_request_id,
                            "prompt": asset.prompt, "asset_ref": asset.asset_ref, "image": asset.image})
        ledger = await diag.get(f"phase7:cost_ledger:{NAMESPACE}")
    finally:
        media_mod.build_budgeted_image_executor = real
        await diag.aclose()
    return results + [{"job": "_ledger", "ledger": ledger.decode() if isinstance(ledger, bytes) else ledger}]


def _jobs() -> tuple[list[dict], dict]:
    """Every picture the CURRENT rule asks for, from the persisted plans."""
    jobs, context = [], {}
    for name, run in POSTS.items():
        pkg = _package(run)
        director = json.loads((run / "director_input.json").read_text(encoding="utf-8"))
        evidence, keys = list(director.get("allowed_evidence") or []), dict(director.get("evidence_story_keys") or {})
        plan = dict(pkg.media_plan.get("creative_execution_plan") or {})
        creative_id = f"nophoto-review-{uuid4()}"
        if name in ("SINGLE", "REEL"):
            copy_text = pkg.on_image_copy or pkg.media_plan.get("hook")
            plan = {**plan, "media_strategy": "generated_media", **generated_plan_update(copy_text)}  # exactly the trigger's switch
            jobs.append({"name": name, "post": name, "asset_key": "primary", "slide": None, "plan": plan,
                         "summary": director["opportunity_summary"],
                         "evidence": evidence, "format": pkg.content_format.value, "creative_id": creative_id, "opportunity_id": str(pkg.opportunity_id)})
            context[name] = {"package": pkg, "plan": plan}
            continue
        recap = pkg.media_plan.get("content_archetype") == "news_recap"
        available = set(director.get("available_media_subjects") or [])
        suitable = available - set(director.get("unsuitable_media_subjects") or [])
        slides, notes = promote_no_photo_slides(copy.deepcopy(pkg.media_plan["slides"]), suitable_subjects=suitable, recap=recap)
        if notes:
            plan = {**plan, **generated_plan_update()}  # exactly the trigger's carousel-wide switch
        context[name] = {"package": pkg, "slides": slides, "notes": notes, "suitable": sorted(suitable), "recap": recap}
        for note in notes:
            if note["treatment"] != "generated":
                continue
            slide = slides[note["slide"]]
            jobs.append({"name": f"{name} slide {note['slide'] + 1}", "post": name, "slide_index": note["slide"], "asset_key": str(note["slide"]),
                         "slide": {**slide, "slide_copy": slide["text"]}, "plan": plan, "summary": director["opportunity_summary"],
                         "evidence": media_mod._evidence_for_slide(evidence, {**slide, "slide_copy": slide["text"]}, keys),
                         "format": "carousel", "creative_id": creative_id, "opportunity_id": str(pkg.opportunity_id)})
    return jobs, context


def _render_after(context: dict, generated: dict[str, list[dict]], out: Path) -> dict:
    report = {}
    for name, ctx in context.items():
        pkg: InstagramContentPackage = ctx["package"]
        folder = out / name.lower().replace(" ", "_")
        folder.mkdir(parents=True, exist_ok=True)
        results = generated.get(name, [])
        if name in ("SINGLE", "REEL"):
            item = results[0]
            if item["image"] is None:
                report[name] = {"status": item["status"], "rendered": False}
                continue
            media_plan = {**pkg.media_plan, "creative_execution_plan": ctx["plan"],
                          "media_execution": {"strategy": "generated_media", "status": "generated_media",
                                              "assets": [{"asset_key": "primary", "media_mode": "GENERATED", "status": "generated_media",
                                                          "asset_ref": item["asset_ref"], "generated_asset_ref": item["asset_ref"]}]}}
            after_pkg = dataclasses.replace(pkg, source_image_ref=item["asset_ref"], media_candidate_id=None, media_plan=media_plan)
            render = (render_instagram_feed_image if name == "SINGLE" else render_instagram_reel_cover)(after_pkg, source_image=item["image"])
            renders = [render]
        else:
            slide_assets = {r["slide_index"]: {"generated": (r["image"], derive_image_identity(r["image"]))} for r in results if r["image"] is not None}
            failed = [r["job"] for r in results if r["image"] is None]
            slides = ctx["slides"]
            execution = [{"asset_key": str(i), "media_mode": "GENERATED" if s.get("media_source") == "generated" else "SOURCE",
                          "status": "generated_media" if i in slide_assets else "source_media"} for i, s in enumerate(slides)]
            after_pkg = dataclasses.replace(pkg, media_plan={**pkg.media_plan, "slides": slides,
                                                             "media_execution": {**(pkg.media_plan.get("media_execution") or {}), "assets": execution},
                                                             "generated_no_photo_slides": ctx["notes"]})
            renders = render_instagram_carousel(after_pkg, subject_assets=_story_media(POSTS[name]), slide_subject_assets=slide_assets)
            report.setdefault(name, {})["generation_failed"] = failed
        for i, r in enumerate(renders, 1):
            (folder / f"slide_{i:02d}.png").write_bytes(r.image_bytes)
        art = validate_instagram_art(after_pkg, renders)
        report.setdefault(name, {}).update({
            "rendered": True, "slides": len(renders), "art_passed": art.passed, "art_blocking": list(art.blocking_issues),
            "per_slide": [{"variant": r.evidence.notes.get("layout_variant"), "editorial_variant": r.evidence.notes.get("editorial_variant"),
                           "treatment": r.evidence.source_image_treatment} for r in renders]})
    return report


def _text_only_adobe(out: Path) -> dict:
    """Generation unavailable (priority 3): the same Adobe plan under the CURRENT rule, no promotion - no fact cards may survive."""
    pkg = _package(POSTS["CAROUSEL"])
    renders = render_instagram_carousel(pkg, subject_assets={})
    folder = out / "carousel_generation_unavailable"
    folder.mkdir(parents=True, exist_ok=True)
    for i, r in enumerate(renders, 1):
        (folder / f"slide_{i:02d}.png").write_bytes(r.image_bytes)
    art = validate_instagram_art(pkg, renders)
    return {"variants": [r.evidence.notes.get("editorial_variant") or "plan" for r in renders], "art_passed": art.passed,
            "art_blocking": list(art.blocking_issues)}


def _sheet(out: Path) -> None:
    rows = []
    for name, run in POSTS.items():
        after_dir = out / name.lower().replace(" ", "_")
        rows.append((f"{name} - BEFORE (accepted no-photo fallback)", sorted((run / "slides").glob("slide_*.png"))))
        rows.append((f"{name} - AFTER (no photo => generated image)", sorted(after_dir.glob("slide_*.png"))))
    rows.append(("CAROUSEL - generation unavailable (text-led fallback, no cards)", sorted((out / "carousel_generation_unavailable").glob("slide_*.png"))))
    th, label = 300, 30
    width = max(sum(round(Image.open(p).width * th / Image.open(p).height) + 10 for p in files) for _, files in rows if files) + 20
    sheet = Image.new("RGB", (width, sum(th + label + 16 for _ in rows) + 10), (246, 246, 246))
    draw, y = ImageDraw.Draw(sheet), 10
    for title, files in rows:
        draw.text((12, y + 8), title, fill=(160, 30, 30) if "BEFORE" in title else (20, 20, 20))
        x = 12
        for path in files:
            im = Image.open(path).convert("RGB")
            w = round(im.width * th / im.height)
            sheet.paste(im.resize((w, th)), (x, y + label))
            x += w + 10
        y += th + label + 16
    sheet.save(out / "before_after_contact_sheet.png")


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    live = "--live" in sys.argv
    jobs, context = _jobs()
    settings.instagram_image_generation_mode = "dry_run"  # in-process only
    dry = asyncio.run(_generate(jobs, "dry_run"))
    worst = sum(Decimal(str(d["reserved_usd"] or 0)) for d in dry if d["job"] != "_ledger")
    plan = {"images": len(jobs), "jobs": [j["name"] for j in jobs], "dry_statuses": [d["status"] for d in dry if d["job"] != "_ledger"],
            "worst_case_usd": str(worst), "cap_usd": str(CAP),
            "promotions": {k: v.get("notes") for k, v in context.items() if "notes" in v}}
    (out / "prompts.json").write_text(json.dumps([{"job": d["job"], "prompt": d["prompt"]} for d in dry if d["job"] != "_ledger"],
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=1))
    report = {"plan": plan, "text_only_adobe": _text_only_adobe(out)}
    if live:
        if worst > CAP:
            raise SystemExit(f"worst case {worst} exceeds the cap {CAP} - nothing sent")
        settings.instagram_image_generation_mode = "live"  # in-process only
        regen = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--regen=")), None)
        if regen:  # regenerate ONLY these jobs (a fixed prompt); every other picture is the one already paid for
            fresh = {r["job"]: r for r in asyncio.run(_generate([j for j in jobs if j["name"] in regen], "live", out))}
            results = [fresh.get(j["name"]) or {"job": j["name"], "status": "reused", "reserved_usd": None, "accounted_usd": None,
                                                 "provider_request_id": None, "prompt": None, "asset_ref": f"generated:reused/{_saved(out, j).name}",
                                                 "image": Image.open(_saved(out, j)).convert("RGB") if _saved(out, j).exists() else None}
                       for j in jobs]
            results.append(fresh.get("_ledger") or {"job": "_ledger", "ledger": None})
        elif "--reuse" in sys.argv:  # re-render from the pictures already paid for - no provider call
            results = [{"job": j["name"], "status": "reused", "reserved_usd": None, "accounted_usd": None, "provider_request_id": None,
                        "prompt": None, "asset_ref": f"generated:reused/{_saved(out, j).name}",
                        "image": Image.open(_saved(out, j)).convert("RGB") if _saved(out, j).exists() else None} for j in jobs]
            results.append({"job": "_ledger", "ledger": None})
        else:
            results = asyncio.run(_generate(jobs, "live", out))
        ledger = next(r["ledger"] for r in results if r["job"] == "_ledger")
        by_post: dict[str, list[dict]] = {}
        for job, r in zip(jobs, [r for r in results if r["job"] != "_ledger"]):
            by_post.setdefault(job["post"], []).append({**r, "slide_index": job.get("slide_index")})
        report["generation"] = [{k: v for k, v in r.items() if k not in ("image", "prompt")} for r in results if r["job"] != "_ledger"]
        report["ledger_usd"] = ledger
        report["after"] = _render_after(context, by_post, out)
        _sheet(out)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "plan"}, ensure_ascii=False, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main()
