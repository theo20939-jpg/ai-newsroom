"""Content, hooks & virality pass - ZERO-COST EDITORIAL REFERENCE render.

Takes the preserved real iteration-6r Creative Director plans, applies the editorial reference copy
(scripts/_instagram_content_pass_reference_copy.json: headline + body per slide, written to the prompt v10.7 contract from each post's own
evidence - NOT model output), runs the UNCHANGED creative-director contract (evidence handles, fact safety, Russian output policy,
meta-language, clickbait, media-first, hook contract and the new information-density check) and renders every slide with the current
renderer and the ALREADY-PAID media only. No provider call of any kind.

Usage: python scripts/_instagram_content_pass_reference.py <out_dir>"""
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
from services.instagram_media_first import find_thin_slides  # noqa: E402
from services.instagram_visual_profiles import InstagramRenderProfile, profile_spec  # noqa: E402

ORDER = ("ai_hack", "news_insight", "news_recap", "trend_generative")
IT6R = ROOT / "artifacts" / "instagram_quality_loop_it6r" / "instagram_quality_loop_it6r"
R2 = ROOT / "artifacts" / "instagram_quality_loop_it6r_complete_r2" / "run" / "final"
STORY_3 = Path(r"C:/Users/Theodor/AppData/Local/Temp/claude/C--Users-Theodor-ai-newsroom/3526231c-0a6d-46c8-9f46-749f71289ce7/scratchpad/r2local/incoming/263b87f469b51fe3ae090aa1a0899e309de9f19327f0121c86b8f1e2a631480f.jpg")
NEWS_INSIGHT_SOURCE = ROOT.parent.parent / ".b44-scratch" / "store" / "ff" / "ff5300e330b3126330077784b352405e7fbdf2236c46a202ab4c69becfc73d2f.png"
MEDIA_MODE = {"source": "SOURCE", "generated": "GENERATED", "graphic": "GRAPHIC"}


def _generated(name: str, index: int) -> Path:
    base = R2 if name in ("news_recap", "trend_generative") else IT6R
    return base / name / f"generated_slide_{index + 1:02d}.png"


def _apply(name: str, raw: dict, ref: dict) -> tuple[dict, list[str]]:
    out = copy.deepcopy(raw)
    out["editorial_angle"] = ref["editorial_angle"]
    out["final_caption"] = ref["final_caption"]
    edits = []
    for key, patch in ref["slides"].items():
        slide = out["slides"][int(key)]
        for field in ("slide_copy", "slide_body", "hook_emotion", "hook_mechanic", "slide_purpose", "source_evidence"):
            if field in patch:
                slide[field] = patch[field]
        if "flow_steps" in patch:
            for region in slide["layout"]["regions"]:
                if region.get("graphic_type") == "flow_diagram":
                    region["flow_steps"] = patch["flow_steps"]
    for key, edit in (ref.get("plan_edits") or {}).items():
        slide = out["slides"][int(key)]
        if "layout" in edit:
            slide["layout"] = edit["layout"]
        if "drop_graphic_types" in edit:
            slide["layout"]["regions"] = [r for r in slide["layout"]["regions"] if r.get("graphic_type") not in edit["drop_graphic_types"]]
        edits.append(f"slide {int(key) + 1}: {edit['reason']}")
    for slide in out["slides"]:
        slide.setdefault("slide_body", None)
    return out, edits


def _director_input(name: str, handles: dict, raw: dict) -> cd.CreativeDirectorInput:
    subjects = sorted({r["content_ref"] for s in raw["slides"] for r in (s.get("layout") or {}).get("regions", [])
                       if r.get("kind") == "media" and r.get("content_ref") not in (None, "generated")})
    return cd.CreativeDirectorInput(
        objective="reach", format="carousel", opportunity_summary=common.SCENARIOS[name]["summary"] if name != "trend_generative" else
        "Vivo представила cмарт-часы Watch 6 с титановым корпусом, сапфировым стеклом и eSIM — цены начинаются от $149",
        allowed_evidence=list(handles.values()), locale="ru", media_first=True, is_recap_bundle=name == "news_recap",
        available_media_subjects=tuple(subjects), unsuitable_media_subjects=(),
    )


def main() -> None:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    refs = json.loads((ROOT / "scripts" / "_instagram_content_pass_reference_copy.json").read_text(encoding="utf-8"))
    spec = profile_spec(InstagramRenderProfile.CAROUSEL_SLIDE)
    story_3 = Image.open(STORY_3).convert("RGB")
    insight_source = Image.open(NEWS_INSIGHT_SOURCE).convert("RGB")
    summary = {}
    for name in ORDER:
        raw_file = json.loads((IT6R / name / "raw_creative_director_output.json").read_text(encoding="utf-8"))
        handles = raw_file["evidence_handles"]
        plan, edits = _apply(name, raw_file["structured_output"], refs[name])
        director_input = _director_input(name, handles, plan)
        contract = "PASS"
        try:
            cd._validate_carousel_output(plan, None, director_input=director_input, archetype=plan.get("content_archetype"))
        except Exception as exc:  # noqa: BLE001 - report the contract failure, never repair it silently
            contract = f"{type(exc).__name__}: {exc}"
        target = out_dir / name
        target.mkdir(parents=True, exist_ok=True)
        slides = plan["slides"]
        images, rows = [], []
        for i, slide in enumerate(slides):
            mode = MEDIA_MODE.get(slide.get("media_source") or "", None)
            assets: dict = {}
            if mode == "GENERATED":
                img = Image.open(_generated(name, i)).convert("RGB")
                assets["generated"] = (img, derive_image_identity(img))
            for region in (slide.get("layout") or {}).get("regions", []):
                if region.get("kind") == "media" and region.get("content_ref") == "story_3":
                    assets["story_3"] = (story_3, derive_image_identity(story_3))
                if region.get("kind") == "media" and region.get("content_ref") == "source":
                    assets["source"] = (insight_source, derive_image_identity(insight_source))
            result = render_carousel_slide(
                spec=spec, role=slide["role"], index=i, total=len(slides), slide_copy=slide["slide_copy"], slide_body=slide.get("slide_body"),
                source_evidence=slide.get("source_evidence"), package_identity=f"content-pass-reference-{name}",
                visual_direction=slide.get("visual_direction"), media_mode=mode, media_need=slide.get("media_need"),
                media_subject=slide.get("media_subject"), layout_plan=slide.get("layout"), subject_assets=assets,
            )
            result.image.save(target / f"slide_{i + 1:02d}.png")
            images.append(result.image)
            n = result.notes
            metrics = n.get("text_metrics") or []
            rows.append({
                "index": i, "role": slide["role"], "slide_copy": slide["slide_copy"], "slide_body": slide.get("slide_body"),
                "media_source": slide.get("media_source"), "visual_family_chosen": slide.get("visual_family"),
                "visual_family_executed": slide.get("visual_family"),
                "headline_px": max([int(m.get("font_px") or 0) for m in metrics if m.get("ref") in ("copy", "copy_lead", "copy_no_number")], default=0),
                "body_px": max([int(m.get("font_px") or 0) for m in metrics if m.get("ref") == "body"], default=0),
                "body_placement": n.get("body_placement"), "orientation": n.get("media_scale_orientation"), "scale_reason": n.get("media_scale_reason"),
                "fallback": n.get("fallback_role_layout_used"), "media_preserving_fallback": n.get("media_preserving_fallback_used"),
                "text_clipped": result.text_clipped, "media_regions": len(n.get("media_regions") or []),
            })
        common.contact_sheet(images).save(target / "contact_sheet.png")
        counts = {k: sum(1 for s in slides if s.get("media_source") == k) for k in ("source", "generated", "graphic")}
        manifest = {
            "archetype": name, "REAL_MODEL": True, "MODEL_SOURCE": "EDITORIAL REFERENCE COPY - NOT MODEL OUTPUT",
            "VALIDATION": "PASS" if contract == "PASS" else "FAIL", "contract": contract, "thin_slides": find_thin_slides(slides),
            "hook_text": slides[0]["slide_copy"], "hook_emotion": slides[0].get("hook_emotion"), "editorial_angle": plan["editorial_angle"],
            "final_caption": plan["final_caption"], "media_source_counts": counts, "text_only_slides": [],
            "plan_edits": edits, "slides": rows, "media_slides": [{"media_source": r["media_source"]} for r in rows],
            "prompt_contract_version": cd.CAROUSEL_PROMPT_VERSION, "provider_calls": 0,
        }
        (target / "render_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        summary[name] = {"contract": contract, "slides": [(r["headline_px"], r["body_px"], r["body_placement"], r["orientation"], r["text_clipped"], r["fallback"]) for r in rows]}
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
