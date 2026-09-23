"""Product polish - ZERO-COST before/after of the real v10.9 first-pass outputs.

Each archetype's real v10.9 Creative Director output goes through: the unchanged acceptance contract (now clearing hook-only planning
fields on non-hook slides), the exact-subject media rule (services/instagram_exact_subject_media.py) with the REAL stored images and the
recorded vision verdicts, and the final Russian line edit (scripts/_instagram_product_polish_copy.json, editor edits, disclosed). It is
rendered with the current renderer and ONLY existing media (paid generated images reused by order, real source photos). No provider call.

Usage: python scripts/_instagram_product_polish.py <out_dir>"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts._instagram_phase_b5_common as common  # noqa: E402
import services.instagram_creative_director as cd  # noqa: E402
from services.instagram_carousel_layouts import render_carousel_slide  # noqa: E402
from services.instagram_creative_media import derive_image_identity  # noqa: E402
from services.instagram_editorial_critic import critique  # noqa: E402
from services.instagram_exact_subject_media import exact_subject_keys, prefer_exact_subject_slides  # noqa: E402
from services.instagram_visual_profiles import InstagramRenderProfile, profile_spec  # noqa: E402

ORDER = ("ai_hack", "news_insight", "news_recap", "trend_generative")
V109 = ROOT / "artifacts" / "instagram_v109_cd_validation" / "run" / "final"
FIXTURES = ROOT / "tests" / "fixtures" / "instagram_v107_validation"
IT6R = ROOT / "artifacts" / "instagram_quality_loop_it6r" / "instagram_quality_loop_it6r"
R2 = ROOT / "artifacts" / "instagram_quality_loop_it6r_complete_r2" / "run" / "final"
STORE = Path(r"C:/Users/Theodor/AppData/Local/Temp/claude/C--Users-Theodor-ai-newsroom/3526231c-0a6d-46c8-9f46-749f71289ce7/scratchpad/r2local/store/images")
STORY_IMAGES = {"story_1": "22/22f125ebedcd0a5d806b1aaec67429141fff9f20ada044d52cf24b9e0109c85c.jpg",
                "story_2": "d2/d2fb55dc06f679a10937b51bbf2a08e3360cdccd0314d37a7b9a14116f7a66dd.jpg",
                "story_3": "26/263b87f469b51fe3ae090aa1a0899e309de9f19327f0121c86b8f1e2a631480f.jpg",
                "story_4": "28/2840d4eea9709eb81ae98bb10af8dc0ff2ef8c2ddafa944fca9ad1d0c03018ad.jpg",
                "story_6": "87/875a6e7f22d73619001c8cc3e68a70b5ef36546b4cbea0fbf3e8702c12af3486.jpg"}
INSIGHT_SOURCE = ROOT.parent.parent / ".b44-scratch" / "store" / "ff" / "ff5300e330b3126330077784b352405e7fbdf2236c46a202ab4c69becfc73d2f.png"
VISION_UNSUITABLE = {"news_recap": {"story_1", "story_2", "story_6"}}  # the recorded vision verdicts of the real run (no vision call here)
# The generated pools come from the earlier it6r paid run, not from v10.9, so reuse "in order" ties no image to a card. RECAP is assigned by what
# each picture shows (editor choice, disclosed). it6r pool 05 is a GENERATED watch: never shown - a generated stand-in must not pose as the real product.
GENERATED_BY_CARD = {"news_recap": {0: "01", 1: "02", 2: "03", 5: "06", 6: "07"}}


def _pool(name: str) -> list[Path]:
    base = R2 if name in ("news_recap", "trend_generative") else IT6R
    return sorted((base / name).glob("generated_slide_*.png"))


def _sources(name: str) -> dict[str, Image.Image]:
    if name == "news_recap":
        return {k: Image.open(STORE / f).convert("RGB") for k, f in STORY_IMAGES.items()}
    if name == "trend_generative":
        return {"source": Image.open(STORE / STORY_IMAGES["story_4"]).convert("RGB")}
    if name == "news_insight":
        return {"source": Image.open(INSIGHT_SOURCE).convert("RGB")}
    return {}


def _edit(plan: dict, edits: dict) -> tuple[dict, list[str]]:
    out = copy.deepcopy(plan)
    log, keep = [], []
    for i, slide in enumerate(out["slides"]):
        patch = edits.get(str(i), {})
        if patch.get("drop"):
            log.append(f"card {i + 1} dropped: {patch['why']}")
            continue
        for field in ("slide_copy", "slide_body"):
            if field in patch:
                slide[field] = patch[field]
        if "flow_steps" in patch:
            for region in slide["layout"]["regions"]:
                if region.get("graphic_type") == "flow_diagram":
                    region["flow_steps"] = patch["flow_steps"]
        if patch:
            log.append(f"card {i + 1}: {patch['why']}")
        keep.append(slide)
    out["slides"] = keep
    if keep[-1]["role"] not in ("result", "takeaway", "cta", "closing"):
        keep[-1]["role"] = "takeaway"
    return out, log


def main() -> None:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    edits = json.loads((ROOT / "scripts" / "_instagram_product_polish_copy.json").read_text(encoding="utf-8"))
    spec = profile_spec(InstagramRenderProfile.CAROUSEL_SLIDE)
    summary = {}
    for name in ORDER:
        raw = json.loads((V109 / name / "raw_creative_director_output.json").read_text(encoding="utf-8"))["structured_output"]
        evidence = list(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["evidence_handles"].values())
        sources = _sources(name)
        exact = exact_subject_keys(list(sources.items()), exclude=VISION_UNSUITABLE.get(name, set()))
        swapped, media_notes = prefer_exact_subject_slides(raw["slides"], exact)
        plan, edit_log = _edit({**raw, "slides": swapped}, edits[name]["slides"])
        unsuitable = tuple(sorted(VISION_UNSUITABLE.get(name, set()) | ({"story_5"} if name == "news_recap" else set())))
        available = tuple(sorted(set(sources) | ({"story_5"} if name == "news_recap" else set())))
        director_input = cd.CreativeDirectorInput(objective="reach", format="carousel", opportunity_summary="s", allowed_evidence=evidence, locale="ru",
                                                  media_first=True, is_recap_bundle=name == "news_recap", available_media_subjects=available,
                                                  unsuitable_media_subjects=unsuitable)
        try:
            cd._validate_carousel_output(plan, None, director_input=director_input, archetype=name)
            contract = "PASS"
        except Exception as exc:  # noqa: BLE001 - reported, never repaired
            contract = f"{type(exc).__name__}: {str(exc)[:300]}"
        findings = critique(plan["slides"], evidence, archetype=name, caption=plan.get("final_caption") or "")
        target = out_dir / name
        target.mkdir(parents=True, exist_ok=True)
        pool, used, images, rows = _pool(name), 0, [], []
        for i, slide in enumerate(plan["slides"]):
            mode = {"source": "SOURCE", "generated": "GENERATED", "graphic": "GRAPHIC"}.get(slide.get("media_source") or "")
            assets, gen_file = {}, None
            if mode == "GENERATED" and pool:
                chosen = GENERATED_BY_CARD.get(name, {}).get(i)
                path = next(p for p in pool if p.stem.endswith(chosen)) if chosen else pool[used % len(pool)]
                img, gen_file = Image.open(path).convert("RGB"), path.name
                used += 1
                assets["generated"] = (img, derive_image_identity(img))
            for region in (slide.get("layout") or {}).get("regions") or []:
                ref = region.get("content_ref")
                if region.get("kind") in ("media", "surface") and ref in sources:
                    assets[ref] = (sources[ref], derive_image_identity(sources[ref]))
            result = render_carousel_slide(spec=spec, role=slide["role"], index=i, total=len(plan["slides"]), slide_copy=slide["slide_copy"],
                                           slide_body=slide.get("slide_body"), source_evidence=None, package_identity=f"polish-{name}",
                                           visual_direction=slide.get("visual_direction"), media_mode=mode, media_subject=slide.get("media_subject"),
                                           layout_plan=slide.get("layout"), subject_assets=assets)
            result.image.save(target / f"slide_{i + 1:02d}.png")
            images.append(result.image)
            m = result.notes.get("text_metrics") or []
            rows.append({"index": i, "role": slide["role"], "slide_copy": slide["slide_copy"], "slide_body": slide.get("slide_body"),
                         "media_source": slide.get("media_source"), "media": [x.get("subject") for x in result.notes.get("media_regions") or []], "generated_file": gen_file,
                         "visual_family_chosen": slide.get("visual_family"), "visual_family_executed": slide.get("visual_family"),
                         "headline_px": max([x["font_px"] for x in m if x["ref"] in ("copy", "copy_lead", "copy_no_number")], default=0),
                         "body_px": max([x["font_px"] for x in m if x["ref"] == "body"], default=0), "clipped": result.text_clipped,
                         "fallback": bool(result.notes.get("fallback_role_layout_used") or result.notes.get("media_preserving_fallback_used"))})
        common.contact_sheet(images).save(target / "contact_sheet.png")
        manifest = {"archetype": name, "REAL_MODEL": True, "MODEL_SOURCE": "EDITORIAL LINE EDIT OF THE REAL v10.9 OUTPUT",
                    "VALIDATION": "PASS" if contract == "PASS" else "FAIL", "contract": contract,
                    "critic_blocking": [f.render() for f in findings if f.severity == "blocking"],
                    "critic_advisory": [f.render() for f in findings if f.severity != "blocking"],
                    "exact_subject_media": media_notes, "edits": edit_log, "hook_text": plan["slides"][0]["slide_copy"],
                    "hook_emotion": plan["slides"][0].get("hook_emotion"), "text_only_slides": [],
                    "media_source_counts": {k: sum(1 for s in plan["slides"] if s.get("media_source") == k) for k in ("source", "generated", "graphic")},
                    "slides": rows, "media_slides": [{"media_source": r["media_source"]} for r in rows], "provider_calls": 0}
        (target / "render_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        summary[name] = {"contract": contract[:90], "critic_blocking": len(manifest["critic_blocking"]), "exact_media": media_notes,
                         "px": [(r["headline_px"], r["body_px"]) for r in rows], "clipped": sum(r["clipped"] for r in rows),
                         "fallbacks": sum(r["fallback"] for r in rows)}
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
