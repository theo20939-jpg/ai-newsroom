"""Phase B.5R.1: render the real-media family reconstructions and record fidelity diagnostics (no score).

Usage: python scripts/_instagram_phase_b5r1_render.py <out_dir>"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schemas.instagram_creative import InstagramSlideLayout  # noqa: E402
from scripts import _instagram_phase_b5r1_assets as assets  # noqa: E402
from scripts import _instagram_phase_b5r1_families as fam  # noqa: E402
from services.instagram_declarative_layout import DeclaredRenderRejected, render_declared_slide  # noqa: E402
from services.instagram_layout_signature import layout_characteristics, layout_signature  # noqa: E402
from services.instagram_layout_validation import validate_layout  # noqa: E402


def render_plan(plan: dict[str, Any]):
    images = {}
    for aid in plan["assets"]:
        img = assets.resolve(aid)
        if img is None:
            raise FileNotFoundError(f"real media not present locally: {aid}")
        images[aid] = (img, f"{assets.BY_ID[aid].source_type}:{assets.BY_ID[aid].key}")
    layout = InstagramSlideLayout.model_validate(plan["layout"])
    validated = validate_layout(layout, slide_copy=plan["copy"], resolvable_subjects=set(images))
    if not validated.accepted or validated.layout is None:
        return validated, None, (validated.rejection_codes[0] if validated.rejection_codes else "rejected")
    try:
        result = render_declared_slide(spec=fam.SPEC, layout=validated.layout, slide_copy=plan["copy"], index=0, total=5,
                                       subject_assets=images, progress_hidden=validated.progress_hidden)
    except DeclaredRenderRejected as exc:
        return validated, None, exc.code
    return validated, result, None


def diagnostics(plan: dict[str, Any], validated, result) -> dict[str, Any]:
    n = result.notes
    metrics = n["text_metrics"]
    biggest = max(metrics, key=lambda m: m["font_px"]) if metrics else None
    smallest = min(metrics, key=lambda m: m["font_px"]) if metrics else None
    chars = layout_characteristics(plan["layout"])
    media_cov, text_cov, obj_cov = n["media_canvas_coverage"], n["text_canvas_coverage"], n["object_canvas_coverage"]
    weight = "media" if media_cov >= 2 * max(text_cov, 0.001) else "type" if text_cov >= 2 * max(media_cov, 0.001) else "mixed"
    return {
        "FAMILY": plan["family"], "LABEL": plan["label"], "NAME": plan["name"], "ASSETS": plan["assets"],
        "SURFACE": plan["layout"]["background"], "PALETTE": plan["layout"]["palette"], "ARRANGEMENT": plan["layout"]["arrangement"],
        "MEDIA_REGION_COUNT": len(n["media_regions"]), "MEDIA_CANVAS_COVERAGE": media_cov, "OBJECT_CANVAS_COVERAGE": obj_cov, "OBJECT_BBOX_CANVAS_COVERAGE": n["object_bbox_canvas_coverage"],
        "TEXT_CANVAS_COVERAGE": text_cov, "OBJECT_TO_TEXT_VISUAL_WEIGHT": round(n["object_bbox_canvas_coverage"] / max(text_cov, 0.001), 2),
        "PRIMARY_VISUAL_WEIGHT": weight, "HEADLINE_ZONE": chars["headline_zone"],
        "HEADLINE_TOKEN": biggest["token"] if biggest else None, "HEADLINE_HEIGHT_OVER_CANVAS_HEIGHT": biggest["block_h_frac"] if biggest else None,
        "HEADLINE_FONT_PX": biggest["font_px"] if biggest else None,
        "SUPPORTING_TYPE_TOKEN": smallest["token"] if smallest else None, "SUPPORTING_FONT_PX": smallest["font_px"] if smallest else None,
        "TYPE_SCALE_RATIO": round(biggest["font_px"] / smallest["font_px"], 2) if biggest and smallest else None,
        "DENSITY": plan["layout"]["density"], "NEGATIVE_SPACE": n["negative_space"], "LAYER_COUNT": n["layer_count"],
        "ROTATION_COUNT": n["rotation_count"], "LOGO_POSITION": n["logo_position"], "OVERLAY_OPS": 0,
        "SOURCE_PIXELS_ALTERED": (None if n["source_media_pixels_unaltered"] is None else not n["source_media_pixels_unaltered"]),
        "TEXT_CLIPPED": result.text_clipped, "LAYOUT_ADAPTATIONS": [i.code for i in validated.issues if i.severity == "adapted"],
        "GEOMETRY_SIGNATURE": layout_signature(plan["layout"]),
    }


def immersive_manifest_entry(plan: dict[str, Any], result) -> dict[str, Any]:
    sel = plan["selection"]
    chosen = sel.selected
    return {
        "TEXT_ZONE_SELECTED": chosen.name, "WHY": sel.why,
        "LOCAL_LUMA": {"mean": round(chosen.mean, 1), "p10": chosen.p10, "p90": chosen.p90},
        "LOCAL_VARIANCE": {"luma_std": round(chosen.std, 1), "edge_energy": round(chosen.edge_energy, 2)},
        "CONTRAST": {"light_text_vs_brightest_decile": round(chosen.contrast_light_text, 1), "dark_text_vs_darkest_decile": round(chosen.contrast_dark_text, 1)},
        "TEXT_COLOR": chosen.text_colour, "RENDER_TIME_ZONE_CHECKS": result.notes["text_zone_reports"],
        "ALL_CANDIDATE_ZONES": [r.as_dict() for r in sel.reports],
    }


def main() -> None:
    out = Path(sys.argv[1])
    (out / "renderer_examples").mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"note": "RENDERER FIXTURES over neutral copy and existing real media - not Instagram posts, not Creative Director output.", "reconstructions": []}
    for plan in fam.all_plans():
        validated, result, render_code = render_plan(plan)
        entry: dict[str, Any] = {"family": plan["family"], "label": plan["label"], "name": plan["name"]}
        if result is None:
            entry["accepted"] = False
            entry["rejections"] = validated.rejection_codes or [render_code]
            manifest["reconstructions"].append(entry)
            print("REJECTED", plan["name"], entry["rejections"])
            continue
        path = out / "renderer_examples" / f"{plan['family']}_{plan['label']}.png"
        result.image.save(path)
        entry.update(accepted=True, file=str(path.name), diagnostics=diagnostics(plan, validated, result))
        if plan.get("selection") is not None:
            entry["quiet_zone"] = immersive_manifest_entry(plan, result)
        manifest["reconstructions"].append(entry)
        print("OK", plan["name"], entry["diagnostics"]["MEDIA_CANVAS_COVERAGE"], entry["diagnostics"]["HEADLINE_TOKEN"], entry["diagnostics"]["TYPE_SCALE_RATIO"])
    (out / "reconstruction_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
