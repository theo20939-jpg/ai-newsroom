"""Phase B.5R.2: founder review sheets (pixels first, minimal text) + the immersive preservation proof.

  hero_object_stage_fidelity.png, culture_collage_fidelity.png, family_fidelity_master.png
  immersive_preservation.json   (B.5R.2 renderer output vs the accepted B.5R.1 immersive PNGs, byte for byte)

Usage: python scripts/_instagram_phase_b5r2_artifacts.py <out_dir> <b5r1_artifacts_dir>   (after _instagram_phase_b5r2_render.py)"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import _instagram_phase_b5r1_artifacts as a1  # noqa: E402
from scripts import _instagram_phase_b5r1_render as r1  # noqa: E402
from scripts import _instagram_phase_b5r2_families as fam  # noqa: E402
from services.instagram_visual_dna_v2 import load_visual_dna_v2  # noqa: E402
from services.instagram_visual_profiles import ig_font  # noqa: E402

TEXT = {
    fam.HERO: (
        "Objects are staged by their own measured extent (31-61% of the canvas, one full-frame) and cropped by canvas edges; two dark grounds, four light; six different arrangements "
        "(bottom-right bleed, full-frame, near full-height, bottom-left crop, lower object + giant numeral, cropped by the left edge); type is tiny, set in a calm zone, or a giant numeral.",
        "Only a handful of real objects sit on a uniform ground and there are no true cut-outs, so light grounds are cleaner than the reference's dark cinematic product shots. "
        "No glow, reflection or light integration on the object.",
    ),
    fam.COL: (
        "Torn paper edges, a die-cut outline on a real transparent cut-out, sticker bursts, highlighter, coloured type, marker circles/arrows that link fragments, layered overlaps and edge "
        "bleed; a clear primary > secondary > tertiary hierarchy; two dark, one light, one media-heavy.",
        "Torn edges are a generated jagged outline (more regular than real paper); no emoji or hand-drawn sticker art; the fragments lean on UI and screenshot material; no tape or paper texture.",
    ),
}
TITLES = {fam.HERO: ("HERO OBJECT STAGE", "hero_object_stage_fidelity.png"), fam.COL: ("INTERNET-CULTURE COLLAGE", "culture_collage_fidelity.png")}


def family_sheet(dna, out: Path, family_id: str) -> None:
    title, name = TITLES[family_id]
    refs = a1.member_thumbs(dna, family_id)
    recons = a1.recon_images(out, family_id)
    ref_h, rec_h = 300, 640
    ref_w = sum(round(r.width * ref_h / r.height) + 14 for r in refs)
    rec_w = sum(round(r.width * rec_h / r.height) + 14 for _, r in recons)
    W = max(ref_w, rec_w) + 48
    sheet = Image.new("RGB", (W, 90 + ref_h + 60 + rec_h + 240), (16, 17, 21))
    d = ImageDraw.Draw(sheet)
    d.text((24, 16), f"{title} - reference members vs our real-media reconstructions (B.5R.2)", font=ig_font(34, "black"), fill=(240, 241, 244))
    d.text((24, 64), "REFERENCE MEMBERS (analysis thumbnails)", font=ig_font(20, "semibold"), fill=(255, 255, 0))
    a1._paste_row(sheet, refs, 94, ref_h)
    y = 94 + ref_h + 14
    d.text((24, y), "OUR RECONSTRUCTIONS  " + "   ".join(f"[{label}]" for label, _ in recons) + "   (existing real media, neutral copy - renderer fixtures, not posts)", font=ig_font(20, "semibold"), fill=(255, 255, 0))
    a1._paste_row(sheet, [im for _, im in recons], y + 34, rec_h)
    y = y + 34 + rec_h + 20
    font_l, font_b = ig_font(18, "black"), ig_font(17, "medium")
    for label, text in zip(("WHAT NOW MATCHES", "WHAT STILL DOES NOT"), TEXT[family_id]):
        d.text((24, y), label, font=font_l, fill=(255, 255, 0))
        y += 24
        for line in a1._wrap(d, text, font_b, W - 60):
            d.text((24, y), line, font=font_b, fill=(214, 216, 222))
            y += 22
        y += 10
    sheet.crop((0, 0, W, y + 10)).save(out / name)


def master_sheet(dna, out: Path, b5r1_dir: Path) -> None:
    imm_dir = out / "renderer_examples_immersive_from_b5r1"
    imm_dir.mkdir(exist_ok=True)
    for f in (b5r1_dir / "renderer_examples").glob("immersive_image_field_*.png"):
        shutil.copyfile(f, imm_dir / f.name)
    col_w, cell_h = 560, 700
    sheet = Image.new("RGB", (3 * (col_w + 20) + 20, 100 + 5 * (cell_h + 36) + 20), (16, 17, 21))
    d = ImageDraw.Draw(sheet)
    d.text((20, 18), "FAMILY FIDELITY (B.5R.2) - reference members vs our real-media reconstructions (renderer fixtures, neutral copy, existing media)", font=ig_font(28, "black"), fill=(240, 241, 244))
    labels = ["REFERENCE FAMILY MEMBERS", "OUR A", "OUR B", "OUR C", "OUR D"]
    families = [(fam.IMM, "IMMERSIVE IMAGE FIELD (unchanged, preserved)", imm_dir), (fam.HERO, "HERO OBJECT STAGE", out / "renderer_examples"), (fam.COL, "INTERNET-CULTURE COLLAGE", out / "renderer_examples")]
    for c, (family_id, title, folder) in enumerate(families):
        x = 20 + c * (col_w + 20)
        d.text((x, 62), title, font=ig_font(24, "black"), fill=(255, 255, 0))
        thumbs = a1.member_thumbs(dna, family_id)
        cell = Image.new("RGB", (col_w, cell_h), (28, 29, 34))
        cols = 3
        tw = (col_w - 8 * (cols + 1)) // cols
        th = (cell_h - 8 * 4) // 3
        for i, t in enumerate(thumbs[:9]):
            t = t.copy()
            t.thumbnail((tw, th), Image.Resampling.LANCZOS)
            cell.paste(t, (8 + (i % cols) * (tw + 8), 8 + (i // cols) * (th + 8)))
        sheet.paste(cell, (x, 100))
        d.text((x + 6, 100 + cell_h + 4), labels[0], font=ig_font(17, "semibold"), fill=(214, 216, 222))
        for r, letter in enumerate("ABCD", start=1):
            f = folder / f"{family_id}_{letter}.png"
            im = Image.open(f).convert("RGB")
            im = im.resize((col_w, round(im.height * col_w / im.width)), Image.Resampling.LANCZOS)
            im = im.crop((0, 0, col_w, cell_h)) if im.height > cell_h else im
            yy = 100 + r * (cell_h + 36)
            sheet.paste(im, (x, yy))
            d.text((x + 6, yy + cell_h + 4), labels[r], font=ig_font(17, "semibold"), fill=(214, 216, 222))
    sheet.save(out / "family_fidelity_master.png")


def immersive_preservation(out: Path, b5r1_dir: Path) -> dict:
    """Re-render the accepted immersive plans with the B.5R.2 renderer and compare bytes with the accepted B.5R.1 PNGs."""
    rows = []
    for plan in fam.immersive_plans():
        validated, result, code = r1.render_plan(plan)
        ref = b5r1_dir / "renderer_examples" / f"immersive_image_field_{plan['label']}.png"
        identical = bool(result is not None and ref.exists() and Image.open(ref).convert("RGB").tobytes() == result.image.convert("RGB").tobytes())
        rows.append({"label": plan["label"], "identical_to_b5r1": identical, "code": code, "sha256": hashlib.sha256(result.image.tobytes()).hexdigest() if result else None})
    doc = {"immersive_changed": not all(r["identical_to_b5r1"] for r in rows), "reconstructions": rows}
    (out / "immersive_preservation.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def main() -> None:
    out, b5r1_dir = Path(sys.argv[1]), Path(sys.argv[2])
    dna = load_visual_dna_v2()
    assert dna is not None
    for family_id in (fam.HERO, fam.COL):
        family_sheet(dna, out, family_id)
    master_sheet(dna, out, b5r1_dir)
    doc = immersive_preservation(out, b5r1_dir)
    print("immersive changed:", doc["immersive_changed"], [(r["label"], r["identical_to_b5r1"]) for r in doc["reconstructions"]])


if __name__ == "__main__":
    main()
