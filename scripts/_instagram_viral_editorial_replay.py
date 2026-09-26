"""Zero-cost replay of the VIRAL EDITORIAL QUALITY rules (founder review 2026-09-26) on real saved outputs - no provider call, no image
regenerated.

B. the failed IShowSpeed canary: its planner read, its live Director output through the CURRENT Director validation (and the full list of
   viral copy / generated-person findings), and the CURRENT art gate on its real package re-rendered from its saved pictures;
C. the accepted DeepSeek and Hamster carousels (polished copy): planner read, Director validation, art gate - they must stay eligible;
D. an ordinary non-viral KAGE story (the accepted Adobe AI_HACK carousel): planner read and art gate unchanged, no viral rule applied.
Usage: python scripts/_instagram_viral_editorial_replay.py <out dir>
"""
from __future__ import annotations

import copy
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts/instagram_feed_product"
FAILED = ART / "fresh_viral_canary_20260926"


def _package(path: Path, **updates):
    from services.instagram_content_package import InstagramContentPackage
    from services.instagram_format_director import ContentFormat

    data = json.loads(path.read_text(encoding="utf-8"))
    data = {k: v for k, v in data.items() if k in {f.name for f in dataclasses.fields(InstagramContentPackage)}}
    data["content_format"] = ContentFormat(data["content_format"])
    return dataclasses.replace(InstagramContentPackage(**data), **updates)


def _read(title: str, source: str, summary: str = "") -> dict:
    from services.instagram_feed_product import FeedCandidate, kage_core, read_candidate

    read = read_candidate(FeedCandidate(id="x", title=title, summary=summary, source_name=source, source_type="RSS"))
    return {"format": read.format.value, "strong": read.strong, "reason": read.reason, "kage_core": kage_core(title)}


def _validate(raw: dict, director_input) -> str:
    import services.instagram_creative_director as cd

    try:
        cd._validate_carousel_output(copy.deepcopy(raw), None, director_input=director_input, archetype="trend_generative")
        return "PASS"
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {str(exc)[:900]}"


def _director_input(persisted: dict, **overrides):
    from services.instagram_creative_director import CreativeDirectorInput

    names = {f.name for f in dataclasses.fields(CreativeDirectorInput)}
    data = {k: v for k, v in persisted.items() if k in names}
    for key in ("available_media_subjects", "unsuitable_media_subjects"):
        data[key] = tuple(data.get(key) or ())
    return CreativeDirectorInput(**{**data, **overrides})


def _gate(pkg, pictures: dict, subject_assets: dict) -> dict:
    from services.instagram_art_validator import validate_instagram_art
    from services.instagram_creative_media import derive_image_identity
    from services.instagram_platform_renderer import render_instagram_carousel

    renders = render_instagram_carousel(pkg, slide_images=pictures, asset_identities={i: derive_image_identity(im) for i, im in pictures.items()},
                                        subject_assets=subject_assets,
                                        slide_subject_assets={i: {"generated": (im, derive_image_identity(im))} for i, im in pictures.items()})
    art = validate_instagram_art(pkg, renders)
    return {"art_passed": art.passed, "blocking": list(art.blocking_issues)}


def main() -> None:
    from services.instagram_creative_media import derive_image_identity
    from services.instagram_viral_format import generated_person_risks, viral_copy_findings

    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"provider_calls": 0, "images_regenerated": 0}

    # B. the failed IShowSpeed canary
    outcome = json.loads((FAILED / "outcome.json").read_text(encoding="utf-8"))
    persisted = json.loads((FAILED / "post/director_input.json").read_text(encoding="utf-8"))
    raw = json.loads((FAILED / "post/calls/03_director.json").read_text(encoding="utf-8"))["response"]["structured_output"]
    evidence = list(persisted["allowed_evidence"])
    pkg = _package(FAILED / "post/package.json")
    pictures = {int(p.stem.split("_")[1]): Image.open(p).convert("RGB") for p in sorted((FAILED / "post/generated").glob("asset_*.png"))}
    source = Image.open(next((FAILED / "_image_storage/images").rglob("*.jpg"))).convert("RGB")
    resolved = copy.deepcopy(raw["slides"])
    handle = {f"E{i}": e for i, e in enumerate(evidence, 1)}
    for slide in resolved:
        slide["source_evidence"] = handle.get(str(slide.get("source_evidence") or "").strip(), slide.get("source_evidence"))
    report["B_ishowspeed"] = {
        "story": outcome["title"], "planner_read_now": _read(outcome["title"], outcome["source"], json.dumps(outcome.get("planner_read"))),
        "director_validation_now": _validate(raw, _director_input(persisted)),
        "all_viral_copy_findings": viral_copy_findings(resolved, evidence, caption=raw.get("final_caption") or ""),
        "generated_person_risks": generated_person_risks(raw["slides"], evidence),
        "art_gate_now": _gate(pkg, pictures, {"source": (source, derive_image_identity(source))}),
    }

    # C. the accepted DeepSeek and Hamster carousels (polished copy) must stay eligible
    import scripts._instagram_viral_copy_polish as polish

    titles = {"deepseek": ("460 целей, ноль автономных взломов: как Telegram-бот на DeepSeek подставил хозяина", "Habr: Artificial Intelligence"),
              "hamster": ("Physicist Rigged His Pet Hamster's Wheel to Strava. It Runs Far Every Night", "Hacker News Front Page")}
    for name, cfg in polish.STORIES.items():
        polished = json.loads((ART / "viral_copy_polish_20260926" / name / "polished_director_output.json").read_text(encoding="utf-8"))
        director_input = polish._director_input(name, cfg)
        review_pkg = _package(ART / "viral_carousel_20260926" / name / "package.json")
        from services.instagram_generated_fallback import viral_generated_heroes

        slides, _ = viral_generated_heroes(copy.deepcopy(review_pkg.media_plan["slides"]))
        for slide, new in zip(slides, polished["slides"]):
            slide["text"], slide["body"] = new["slide_copy"], new["slide_body"]
        review_pkg = dataclasses.replace(review_pkg, caption=polished["final_caption"], media_plan={**review_pkg.media_plan, "slides": slides})
        pics = {int(p.stem.split("_")[1]) - 1: Image.open(p).convert("RGB")
                for p in sorted((ART / "viral_carousel_20260926" / name / "generated").glob("slide_*.png"))}
        report[f"C_{name}"] = {"planner_read_now": _read(*titles[name]), "director_validation_now": _validate(polished, director_input),
                               "art_gate_now": _gate(review_pkg, pics, {})}

    # D. an ordinary non-viral KAGE story is unaffected
    adobe = ART / "daily_media_cleanliness_20260926/preserved/carousel_adobe"
    adobe_pkg = _package(adobe / "package.json")
    adobe_source = next((ART / "last_three_blockers_20260926/daily/_image_storage/images").rglob("*.png"), None)
    decision = (adobe_pkg.director_evidence or {}).get("editorial_decision") or {}
    report["D_adobe_ai_hack"] = {
        "planner_read_now": _read("You can use 70+ Adobe tools without leaving ChatGPT now - here's how", "ZDNET"),
        "viral_rules_apply": bool(decision.get("viral_carousel_upgrade")),
        "art_gate_now": _gate(adobe_pkg, {}, {}),
        "adobe_source_checked": str(adobe_source is not None),
    }
    (out / "replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
