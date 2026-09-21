"""Phase B.5R: render the family reconstruction (2 compositions per visual family, neutral synthetic content)
through the REAL declarative validator + safe renderer. Zero provider calls.

Usage: python scripts/_instagram_phase_b5r_render.py <out_dir>"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schemas.instagram_creative import InstagramSlideLayout  # noqa: E402
from scripts import _instagram_phase_b5r_families as fam  # noqa: E402
from services.instagram_declarative_layout import render_declared_slide  # noqa: E402
from services.instagram_layout_signature import layout_characteristics, layout_signature  # noqa: E402
from services.instagram_layout_validation import validate_layout  # noqa: E402
from services.instagram_visual_profiles import INSTAGRAM_RENDER_PROFILES, InstagramRenderProfile, ig_font  # noqa: E402

SPEC = INSTAGRAM_RENDER_PROFILES[InstagramRenderProfile.CAROUSEL_SLIDE]


def render_composition(comp: dict[str, Any], images: dict[str, Image.Image]):
    """(validated, result|None). Nothing is drawn if the plan is rejected."""
    layout = InstagramSlideLayout.model_validate(comp["layout"])
    subject_assets = {k: (v, f"synthetic:{k}") for k, v in images.items()}
    validated = validate_layout(layout, slide_copy=comp["copy"], resolvable_subjects=set(subject_assets))
    if not validated.accepted or validated.layout is None:
        return validated, None
    result = render_declared_slide(
        spec=SPEC, layout=validated.layout, slide_copy=comp["copy"], index=0, total=5,
        subject_assets=subject_assets, progress_hidden=validated.progress_hidden,
    )
    return validated, result


def render_all() -> dict[str, list[dict[str, Any]]]:
    images = fam.assets()
    out: dict[str, list[dict[str, Any]]] = {}
    for family_id, comps in fam.FAMILY_COMPOSITIONS.items():
        rows = []
        for comp in comps:
            validated, result = render_composition(comp, images)
            rows.append({"comp": comp, "validated": validated, "result": result})
        out[family_id] = rows
    return out


def _sheet(items: list[tuple[str, Image.Image]], *, cols: int, title: str, cell_w: int = 460) -> Image.Image:
    cells = [(label, im.resize((cell_w, round(im.height * cell_w / im.width)))) for label, im in items]
    cell_h = max(im.height for _, im in cells)
    rows = (len(cells) + cols - 1) // cols
    W, H = cols * (cell_w + 24) + 24, rows * (cell_h + 60) + 70
    sheet = Image.new("RGB", (W, H), (128, 128, 128))
    d = ImageDraw.Draw(sheet)
    d.text((24, 16), title, font=ig_font(30, "black"), fill=(255, 255, 255))
    for i, (label, im) in enumerate(cells):
        x, y = 24 + (i % cols) * (cell_w + 24), 70 + (i // cols) * (cell_h + 60)
        d.text((x, y), label, font=ig_font(20, "semibold"), fill=(255, 255, 0))
        sheet.paste(im, (x, y + 32))
    return sheet


def main() -> None:
    out_dir = Path(sys.argv[1])
    (out_dir / "renderer_examples").mkdir(parents=True, exist_ok=True)
    results = render_all()
    manifest: dict[str, Any] = {"note": "RENDERER FIXTURES over neutral synthetic content - not Instagram posts, not model output.", "families": {}}
    all_items: list[tuple[str, Image.Image]] = []
    for family_id, rows in results.items():
        entries = []
        for n, row in enumerate(rows, start=1):
            comp, validated, result = row["comp"], row["validated"], row["result"]
            if result is None:
                entries.append({"name": comp["name"], "accepted": False, "rejections": validated.rejection_codes})
                continue
            path = out_dir / "renderer_examples" / f"{family_id}_{n:02d}.png"
            result.image.save(path)
            all_items.append((f"{family_id} #{n}", result.image))
            entries.append({
                "name": comp["name"], "file": path.name, "accepted": True, "signature": layout_signature(comp["layout"]),
                "characteristics": layout_characteristics(comp["layout"]),
                "overlay_operations_executed": 0, "source_media_pixels_unaltered": result.notes["source_media_pixels_unaltered"],
                "media_regions_tilted": result.notes["media_regions_tilted"], "text_clipped": result.text_clipped,
                "adaptations": [i.code for i in validated.issues if i.severity == "adapted"],
            })
        manifest["families"][family_id] = entries
    (out_dir / "reconstruction_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _sheet(all_items, cols=4, title="Reference family reconstruction - renderer fixtures over neutral synthetic content (not posts)").save(out_dir / "reference_family_reconstruction.png")
    print("rendered", len(all_items), "of", sum(len(v) for v in results.values()))


if __name__ == "__main__":
    main()
