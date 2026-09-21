"""Phase B.5R.3: render the hero-object and collage reconstructions and record per-reconstruction diagnostics (no score).

Usage: python scripts/_instagram_phase_b5r3_render.py <out_dir>"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import _instagram_phase_b5r1_render as r1  # noqa: E402
from scripts import _instagram_phase_b5r3_families as fam  # noqa: E402


def diagnostics(plan: dict[str, Any], validated, result) -> dict[str, Any]:
    d = r1.diagnostics(plan, validated, result)
    n = result.notes
    metrics = n["text_metrics"]
    headline = max(metrics, key=lambda m: m["font_px"]) if metrics else None
    support = min(metrics, key=lambda m: m["font_px"]) if metrics else None
    d.update({
        "OBJECT_BOUNDING_BOXES": n["object_bounding_boxes"],
        "OBJECT_EDGE_BLEED": bool(n["object_edge_bleed"]), "OBJECT_EDGE_BLEED_SIDES": n["object_edge_bleed"],
        "HEADLINE_CANVAS_COVERAGE": round(headline["block_h_frac"] * headline["block_w_frac"], 4) if headline else None,
        "OBJECT_TO_TYPE_VISUAL_WEIGHT": round(n["object_bbox_canvas_coverage"] / max(headline["block_h_frac"] * headline["block_w_frac"], 0.001), 2) if headline else None,
        "SUPPORTING_TOKEN": support["token"] if support else None,
        "TEXT_BLOCK_WIDTH": headline["block_w_frac"] if headline else None,
        "FRAGMENT_FRAMES": [r.get("frame") for r in plan["layout"]["regions"] if r["kind"] == "media"],
        "DEVICES": sorted({r["graphic_type"] for r in plan["layout"]["regions"] if r["kind"] == "graphic"}),
    })
    return d


def main() -> None:
    out = Path(sys.argv[1])
    (out / "renderer_examples").mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"note": "RENDERER FIXTURES over neutral copy and existing real media - not Instagram posts, not Creative Director output.", "reconstructions": []}
    for plan in fam.hero_plans() + fam.collage_plans():
        validated, result, code = r1.render_plan(plan)
        entry: dict[str, Any] = {"family": plan["family"], "label": plan["label"], "name": plan["name"]}
        if result is None:
            entry.update(accepted=False, rejections=validated.rejection_codes or [code])
            manifest["reconstructions"].append(entry)
            print("REJECTED", plan["name"], entry["rejections"])
            continue
        path = out / "renderer_examples" / f"{plan['family']}_{plan['label']}.png"
        result.image.save(path)
        entry.update(accepted=True, file=path.name, diagnostics=diagnostics(plan, validated, result))
        manifest["reconstructions"].append(entry)
        dg = entry["diagnostics"]
        print("OK", plan["family"][:4], plan["label"], "obj", dg["OBJECT_BBOX_CANVAS_COVERAGE"], "media", dg["MEDIA_CANVAS_COVERAGE"], "neg", dg["NEGATIVE_SPACE"], "hl", dg["HEADLINE_TOKEN"], dg["TYPE_SCALE_RATIO"], "clip", dg["TEXT_CLIPPED"])
    (out / "reconstruction_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
