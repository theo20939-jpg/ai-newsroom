"""Editorial judgment reset - ZERO-COST regression replay of the frozen v10.7 paid validation.

For each archetype: the exact paid Creative Director output (tests/fixtures/instagram_v107_validation) is run through the editorial critic
and re-rendered with the current renderer and the same already-paid media; the founder reference copy for the same story is run through
the same critic as the false-positive check. No provider call of any kind.

Usage: python scripts/_instagram_editorial_regression.py <out_dir>"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts._instagram_phase_b5_common as common  # noqa: E402
from services.instagram_carousel_layouts import render_carousel_slide  # noqa: E402
from services.instagram_creative_media import derive_image_identity  # noqa: E402
from services.instagram_editorial_critic import critique  # noqa: E402
from services.instagram_visual_profiles import InstagramRenderProfile, profile_spec  # noqa: E402

ORDER = ("ai_hack", "news_insight", "news_recap", "trend_generative")
FIXTURES = ROOT / "tests" / "fixtures" / "instagram_v107_validation"
IT6R = ROOT / "artifacts" / "instagram_quality_loop_it6r" / "instagram_quality_loop_it6r"
R2 = ROOT / "artifacts" / "instagram_quality_loop_it6r_complete_r2" / "run" / "final"
STORE = ROOT.parent.parent / ".b44-scratch" / "store"
STORY_3 = Path(r"C:/Users/Theodor/AppData/Local/Temp/claude/C--Users-Theodor-ai-newsroom/3526231c-0a6d-46c8-9f46-749f71289ce7/scratchpad/r2local/incoming/263b87f469b51fe3ae090aa1a0899e309de9f19327f0121c86b8f1e2a631480f.jpg")
INSIGHT_SOURCE = STORE / "ff" / "ff5300e330b3126330077784b352405e7fbdf2236c46a202ab4c69becfc73d2f.png"


def _pool(name: str) -> list[Path]:
    base = R2 if name in ("news_recap", "trend_generative") else IT6R
    return sorted((base / name).glob("generated_slide_*.png"))


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    spec = profile_spec(InstagramRenderProfile.CAROUSEL_SLIDE)
    sources = {"story_3": Image.open(STORY_3).convert("RGB"), "source": Image.open(INSIGHT_SOURCE).convert("RGB")}
    report = {}
    for name in ORDER:
        data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
        evidence = list(data["evidence_handles"].values())
        paid = data["paid_output"]
        ref_slides = [{**s, "layout": {"regions": [{"flow_steps": s["flow_steps"]}]} if s.get("flow_steps") else None} for s in data["reference"]["slides"]]
        paid_findings = critique(paid["slides"], evidence, archetype=name, caption=paid.get("final_caption") or "")
        ref_findings = critique(ref_slides, evidence, archetype=name, caption=data["reference"]["final_caption"])
        target = out / name
        target.mkdir(parents=True, exist_ok=True)
        pool, used, images, metrics = _pool(name), 0, [], []
        for i, slide in enumerate(paid["slides"]):
            mode = {"source": "SOURCE", "generated": "GENERATED", "graphic": "GRAPHIC"}.get(slide.get("media_source") or "")
            assets = {}
            if mode == "GENERATED" and pool:
                img = Image.open(pool[used % len(pool)]).convert("RGB")
                used += 1
                assets["generated"] = (img, derive_image_identity(img))
            for region in (slide.get("layout") or {}).get("regions", []):
                ref = region.get("content_ref")
                if region.get("kind") == "media" and ref in sources:
                    assets[ref] = (sources[ref], derive_image_identity(sources[ref]))
            result = render_carousel_slide(spec=spec, role=slide["role"], index=i, total=len(paid["slides"]), slide_copy=slide["slide_copy"],
                                           slide_body=slide.get("slide_body"), source_evidence=None, package_identity=f"regression-{name}",
                                           visual_direction=slide.get("visual_direction"), media_mode=mode, layout_plan=slide.get("layout"),
                                           subject_assets=assets)
            result.image.save(target / f"slide_{i + 1:02d}.png")
            images.append(result.image)
            m = result.notes.get("text_metrics") or []
            metrics.append({"headline_px": max([x["font_px"] for x in m if x["ref"] in ("copy", "copy_lead", "copy_no_number")], default=0),
                            "body_px": max([x["font_px"] for x in m if x["ref"] == "body"], default=0), "clipped": result.text_clipped,
                            "fallback": bool(result.notes.get("fallback_role_layout_used") or result.notes.get("media_preserving_fallback_used"))})
        common.contact_sheet(images).save(target / "contact_sheet.png")
        report[name] = {
            "paid_blocking": [f.render() for f in paid_findings if f.severity == "blocking"],
            "paid_advisory": [f.render() for f in paid_findings if f.severity != "blocking"],
            "reference_blocking": [f.render() for f in ref_findings if f.severity == "blocking"],
            "reference_advisory": [f.render() for f in ref_findings if f.severity != "blocking"],
            "render": metrics,
        }
    (out / "editorial_regression.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, r in report.items():
        print(name, "paid blocking", len(r["paid_blocking"]), "| reference blocking", len(r["reference_blocking"]),
              "| render", [(m["headline_px"], m["body_px"]) for m in r["render"]], "clipped", sum(m["clipped"] for m in r["render"]))


if __name__ == "__main__":
    main()
