"""Phase B.5R.1: asset manifest + per-family fidelity sheets + the master acceptance sheet (images first, text last).

Usage: python scripts/_instagram_phase_b5r1_artifacts.py <out_dir>   (run after _instagram_phase_b5r1_render.py)"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import _instagram_phase_b5r1_assets as assets  # noqa: E402
from scripts import _instagram_phase_b5r1_families as fam  # noqa: E402
from services.instagram_reference_segmentation import crop_sample, reference_samples  # noqa: E402
from services.instagram_visual_dna import REFERENCE_BOARD_PATH  # noqa: E402
from services.instagram_visual_dna_v2 import load_visual_dna_v2  # noqa: E402
from services.instagram_visual_profiles import ig_font  # noqa: E402

FAMILIES = [
    (assets.IMM, "IMMERSIVE IMAGE FIELD", "immersive_image_field_fidelity.png"),
    (assets.HERO, "HERO OBJECT STAGE", "hero_object_stage_fidelity.png"),
    (assets.COL, "INTERNET-CULTURE COLLAGE", "culture_collage_fidelity.png"),
]
TEXT = {
    assets.IMM: (
        "Full-frame dark scene or portrait owns the frame; a large condensed headline sits in a naturally quiet dark zone; the subject is off-centre.",
        "Real stored images placed full-bleed (crop/scale only). The text zone is chosen by measured luminance, contrast and busyness of the actual pixels; images with no usable zone are refused. No overlay, blur, dimming or gradient.",
        "Text only where the image is already calm, so bright or busy images are not eligible. The reference's neon illustrated art is richer; our stored scenes are plainer. No scene-coloured accents on type.",
    ),
    assets.HERO: (
        "One recognisable object is the hero: large, often cropped or bleeding off an edge, on a generous solid ground; type is small or heavy but never competes.",
        "Real product photos on uniform grounds. The ground colour is sampled from the asset's own border so the object reads as isolated; a 'stage' arrangement lets the object bleed off the frame.",
        "Isolation relies on uniform backgrounds (no general cut-out service; only one real transparent asset exists). No reflection or glow staging. A bright, non-uniform photo failed the readability check and was dropped.",
    ),
    assets.COL: (
        "Uneven fragments (reaction, meme, screenshot, paper), stickers and doodles, tight overlaps and small tilts, dark or light, with an obvious reading order despite the mess.",
        "Real reaction, comic, UI and chart fragments with explicit layer order, overlaps, bleed, tilts, paper mats, vector scribble/badge marks and an enforced primary > secondary > tertiary size hierarchy. Deterministic.",
        "No torn-paper edges, no real sticker or emoji art (marks are generated vector strokes). Fragments are cleaner than the reference's hand-made mess.",
    ),
}


def _wrap(draw, text, font, width):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def _paste_row(sheet: Image.Image, images: list[Image.Image], y: int, height: int, x0: int = 24, gap: int = 14) -> int:
    x = x0
    for im in images:
        r = im.resize((max(1, round(im.width * height / im.height)), height), Image.Resampling.LANCZOS)
        sheet.paste(r, (x, y))
        x += r.width + gap
    return x


def member_thumbs(dna, family_id: str) -> list[Image.Image]:
    board = Image.open(REFERENCE_BOARD_PATH).convert("RGB")
    by_id = {s.sample_id: s for s in reference_samples()}
    fam_def = next(f for f in dna.families if f.family_id == family_id)
    return [crop_sample(board, by_id[m], scale=2.0) for m in fam_def.member_samples]


def recon_images(out: Path, family_id: str) -> list[tuple[str, Image.Image]]:
    files = sorted((out / "renderer_examples").glob(f"{family_id}_*.png"))
    return [(f.stem.rsplit("_", 1)[1], Image.open(f).convert("RGB")) for f in files]


def family_sheet(dna, out: Path, family_id: str, title: str, name: str) -> None:
    refs = member_thumbs(dna, family_id)
    recons = recon_images(out, family_id)
    ref_h, rec_h = 330, 620
    ref_w = sum(round(r.width * ref_h / r.height) + 14 for r in refs)
    rec_w = sum(round(r.width * rec_h / r.height) + 14 for _, r in recons)
    W = max(ref_w, rec_w) + 48
    sheet = Image.new("RGB", (W, 90 + ref_h + 60 + rec_h + 300), (16, 17, 21))
    d = ImageDraw.Draw(sheet)
    d.text((24, 16), f"{title} - reference members vs our real-media reconstructions", font=ig_font(34, "black"), fill=(240, 241, 244))
    d.text((24, 66), "REFERENCE MEMBERS (small analysis thumbnails)", font=ig_font(20, "semibold"), fill=(255, 255, 0))
    _paste_row(sheet, refs, 96, ref_h)
    y = 96 + ref_h + 14
    d.text((24, y), "OUR RECONSTRUCTIONS (existing real media, neutral copy - renderer fixtures, not posts)  " + "   ".join(f"[{l}]" for l, _ in recons), font=ig_font(20, "semibold"), fill=(255, 255, 0))
    _paste_row(sheet, [im for _, im in recons], y + 34, rec_h)
    y = y + 34 + rec_h + 20
    font_l, font_b = ig_font(18, "black"), ig_font(17, "medium")
    for label, text in zip(("REFERENCE MECHANICS", "OUR IMPLEMENTATION", "KNOWN GAP"), TEXT[family_id]):
        d.text((24, y), label, font=font_l, fill=(255, 255, 0))
        y += 24
        for line in _wrap(d, text, font_b, W - 60):
            d.text((24, y), line, font=font_b, fill=(214, 216, 222))
            y += 22
        y += 10
    sheet.crop((0, 0, W, y + 10)).save(out / name)


def master_sheet(dna, out: Path) -> None:
    col_w, cell_h = 600, 750
    sheet = Image.new("RGB", (3 * (col_w + 20) + 20, 100 + 4 * (cell_h + 40) + 20), (16, 17, 21))
    d = ImageDraw.Draw(sheet)
    d.text((20, 18), "FAMILY FIDELITY - reference members vs our real-media reconstructions (renderer fixtures, neutral copy, existing media)", font=ig_font(30, "black"), fill=(240, 241, 244))
    row_labels = ["REFERENCE FAMILY MEMBERS", "OUR RECONSTRUCTION A", "OUR RECONSTRUCTION B", "OUR RECONSTRUCTION C"]
    for c, (family_id, title, _name) in enumerate(FAMILIES):
        x = 20 + c * (col_w + 20)
        d.text((x, 62), title, font=ig_font(26, "black"), fill=(255, 255, 0))
        thumbs = member_thumbs(dna, family_id)
        cell = Image.new("RGB", (col_w, cell_h), (28, 29, 34))
        cols = 3
        tw = (col_w - 8 * (cols + 1)) // cols
        th = (cell_h - 8 * 4) // 3
        for i, t in enumerate(thumbs[:9]):
            t = t.copy()
            t.thumbnail((tw, th), Image.Resampling.LANCZOS)
            cell.paste(t, (8 + (i % cols) * (tw + 8), 8 + (i // cols) * (th + 8)))
        y = 100
        sheet.paste(cell, (x, y))
        d.text((x + 6, y + cell_h + 4), row_labels[0], font=ig_font(18, "semibold"), fill=(214, 216, 222))
        recons = dict(recon_images(out, family_id))
        for r, label in enumerate(("A", "B", "C"), start=1):
            im = recons[label].resize((col_w, round(recons[label].height * col_w / recons[label].width)), Image.Resampling.LANCZOS)
            im = im.crop((0, 0, col_w, cell_h)) if im.height > cell_h else im
            yy = 100 + r * (cell_h + 40)
            sheet.paste(im, (x, yy))
            d.text((x + 6, yy + cell_h + 4), row_labels[r], font=ig_font(18, "semibold"), fill=(214, 216, 222))
    sheet.save(out / "family_fidelity_master.png")


def asset_manifest(out: Path) -> dict:
    manifest = json.loads((out / "reconstruction_manifest.json").read_text(encoding="utf-8"))
    used: dict[str, list[str]] = {}
    for rec in manifest["reconstructions"]:
        if rec.get("accepted"):
            for aid in rec["diagnostics"]["ASSETS"]:
                used.setdefault(aid, []).append(f"{rec['family']}/{rec['label']}")
    rows = []
    for aid, where in used.items():
        a = assets.BY_ID[aid]
        img = assets.resolve(aid)
        alpha = bool(img is not None and img.mode == "RGBA" and img.getchannel("A").getextrema()[0] < 250)
        rows.append({
            "ASSET ID": aid, "SOURCE TYPE": a.source_type, "SOURCE PATH / STORAGE KEY": a.key,
            "DIMENSIONS": f"{img.width}x{img.height}" if img else None, "ALPHA AVAILABLE": "YES" if alpha else "NO",
            "SUBJECT": a.subject, "SUITABLE FAMILIES": list(a.families), "WHY SUITABLE": a.why, "USED IN": where,
        })
    probe = []
    for a in assets.ASSETS:
        if assets.IMM in a.families or a.asset_id == "repo_yellow_kiosk":
            if assets.resolve(a.asset_id) is None:
                continue
            per_crop, best = {}, None
            for fx in (0.1, 0.3, 0.5, 0.7, 0.9):
                sel = fam.immersive_eligibility(a.asset_id, fx, 0.5)
                per_crop[str(fx)] = sel.selected.name if sel.selected is not None else "NONE"
                if sel.selected is not None and best is None:
                    best = {"focus_x": fx, "zone": sel.selected.name, "why": sel.why}
            probe.append({"asset": a.asset_id, "immersive_eligible": best is not None, "zone_by_crop_focus_x": per_crop, "first_eligible_crop": best,
                          "crops_without_any_usable_zone": sum(1 for v in per_crop.values() if v == "NONE"),
                          "verdict": ("eligible at " + str(sum(1 for v in per_crop.values() if v != "NONE")) + " of 5 tested crops") if best else
                          "NOT SUITABLE FOR IMMERSIVE IMAGE FIELD (no calm, high-contrast text zone at any tested crop)"})
    doc = {
        "note": "Existing real media only (git-tracked repository fixtures and existing stored Newsroom images). No generation, no provider, no web fetch, no reference-board imagery. Several stored Newsroom images are illustrations produced earlier by the newsroom pipeline; provenance is reported as 'stored newsroom image'.",
        "PLACEHOLDER SUBJECT ASSETS": 0, "assets_used": rows, "immersive_eligibility_probe": probe,
    }
    (out / "asset_manifest.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


def main() -> None:
    out = Path(sys.argv[1])
    dna = load_visual_dna_v2()
    assert dna is not None
    doc = asset_manifest(out)
    for family_id, title, name in FAMILIES:
        family_sheet(dna, out, family_id, title, name)
    master_sheet(dna, out)
    print("assets used:", len(doc["assets_used"]), "| probe:", [(p["asset"], p["immersive_eligible"]) for p in doc["immersive_eligibility_probe"]])


if __name__ == "__main__":
    main()
