"""Phase B.5R: founder-review artifacts built from Visual DNA v2 + the reconstruction renders (no provider call).

  reference_map.png            original board + every detected sample and its assigned family
  family_cards/<family>.png    one card per visual family
  b5_vs_reference_diagnosis.png  reference family/surface mix vs the B.5 real outputs' mix

Usage: python scripts/_instagram_phase_b5r_artifacts.py <out_dir> <b5_artifacts_dir>"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.instagram_layout_signature import layout_characteristics, structure_profile  # noqa: E402
from services.instagram_reference_segmentation import crop_sample, reference_samples  # noqa: E402
from services.instagram_visual_dna import REFERENCE_BOARD_PATH  # noqa: E402
from services.instagram_visual_dna_v2 import family_mix, load_visual_dna_v2, surface_mix  # noqa: E402
from services.instagram_visual_profiles import ig_font  # noqa: E402

_COLOURS = [(226, 60, 70), (0, 190, 220), (150, 100, 255), (190, 220, 20), (250, 150, 30), (120, 150, 190)]
_BG, _FG, _MUTED = (18, 19, 23), (240, 241, 244), (150, 155, 166)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def _colour_map(dna) -> dict[str, tuple[int, int, int]]:
    return {f.family_id: _COLOURS[i % len(_COLOURS)] for i, f in enumerate(dna.families)}


def reference_map(dna, out: Path) -> None:
    colours = _colour_map(dna)
    membership: dict[str, list[str]] = {}
    for f in dna.families:
        for m in f.member_samples:
            membership.setdefault(m, []).append(f.family_id)
    names = {f.family_id: f.name for f in dna.families}
    board = Image.open(REFERENCE_BOARD_PATH).convert("RGB")
    scale = 1.25
    big = board.resize((round(board.width * scale), round(board.height * scale)), Image.Resampling.LANCZOS)
    d = ImageDraw.Draw(big)
    for s in reference_samples():
        fams = membership.get(s.sample_id, [])
        box = tuple(round(v * scale) for v in s.box)
        for k, fid in enumerate(fams):
            inset = k * 4
            d.rectangle([box[0] + inset, box[1] + inset, box[2] - inset, box[3] - inset], outline=colours[fid], width=4)
        d.rectangle([box[0], box[1], box[0] + 58, box[1] + 26], fill=(0, 0, 0))
        d.text((box[0] + 5, box[1] + 3), s.sample_id, font=ig_font(20, "black"), fill=(255, 255, 0))
    cols, cell_w, cell_h = 5, 372, 400
    W = max(big.width, cols * cell_w + 40)
    legend_h = 40 + 30 * len(dna.families)
    H = big.height + 90 + 4 * cell_h + legend_h + 40
    sheet = Image.new("RGB", (W, H), _BG)
    sd = ImageDraw.Draw(sheet)
    sd.text((20, 14), "REFERENCE MAP - the founder board, its 20 detected samples, and the visual family each was grouped into", font=ig_font(28, "black"), fill=_FG)
    sheet.paste(big, (0, 60))
    y0 = 60 + big.height + 24
    sd.text((20, y0), "Each detected sample and its family (a second colour ring = the sample also fits that family). Reference crops are internal evidence only.", font=ig_font(20, "medium"), fill=_MUTED)
    y0 += 40
    for i, s in enumerate(reference_samples()):
        x, y = 20 + (i % cols) * cell_w, y0 + (i // cols) * cell_h
        crop = crop_sample(board, s, scale=1.0)
        crop = crop.resize((round(crop.width * 1.55), round(crop.height * 1.55)), Image.Resampling.LANCZOS)
        crop.thumbnail((cell_w - 20, cell_h - 90))
        sheet.paste(crop, (x, y + 30))
        fams = membership.get(s.sample_id, [])
        for k, fid in enumerate(fams):
            sd.rectangle([x - 4 - k * 4, y + 26 - k * 4, x + crop.width + 4 + k * 4, y + 34 + crop.height + k * 4], outline=colours[fid], width=3)
        sd.text((x, y), s.sample_id, font=ig_font(22, "black"), fill=(255, 255, 0))
        ty = y + crop.height + 40
        for fid in fams:
            sd.rectangle([x, ty + 3, x + 14, ty + 17], fill=colours[fid])
            sd.text((x + 20, ty), names[fid], font=ig_font(17, "medium"), fill=_FG)
            ty += 22
    ly = y0 + 4 * cell_h + 10
    sd.text((20, ly), "FAMILIES (sample membership)", font=ig_font(24, "black"), fill=_FG)
    ly += 34
    mix = family_mix(dna)
    for f in dna.families:
        sd.rectangle([20, ly + 3, 40, ly + 21], fill=colours[f.family_id])
        sd.text((52, ly), f"{f.name}: {mix[f.family_id]['count']} of {mix[f.family_id]['of']} - {', '.join(f.member_samples)}", font=ig_font(20, "medium"), fill=_FG)
        ly += 30
    sheet.save(out)


def _kv(draw, x, y, width, label, text, font_l, font_b) -> int:
    draw.text((x, y), label, font=font_l, fill=(255, 255, 0))
    y += 26
    for line in _wrap(draw, text, font_b, width):
        draw.text((x, y), line, font=font_b, fill=_FG)
        y += 23
    return y + 10


def family_cards(dna, out_dir: Path, renders_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    colours = _colour_map(dna)
    board = Image.open(REFERENCE_BOARD_PATH).convert("RGB")
    by_id = {s.sample_id: s for s in dna.samples}
    ref_by_id = {s.sample_id: s for s in reference_samples()}
    fl, fb = ig_font(20, "black"), ig_font(19, "medium")
    for fmly in dna.families:
        W, H = 2000, 1500
        card = Image.new("RGB", (W, H), _BG)
        d = ImageDraw.Draw(card)
        d.rectangle([0, 0, W, 12], fill=colours[fmly.family_id])
        d.text((30, 30), fmly.name, font=ig_font(46, "black"), fill=_FG)
        d.text((30, 90), f"family_id: {fmly.family_id}  |  {len(fmly.member_samples)} of {len(dna.samples)} reference samples: {', '.join(fmly.member_samples)}", font=ig_font(22, "medium"), fill=_MUTED)
        x = 30
        for sid in fmly.member_samples:  # internal evidence thumbnails
            crop = crop_sample(board, ref_by_id[sid], scale=1.0)
            crop.thumbnail((250, 290))
            card.paste(crop, (x, 140))
            d.text((x, 434), sid, font=ig_font(20, "black"), fill=(255, 255, 0))
            x += crop.width + 14
        members = [by_id[m] for m in fmly.member_samples]
        surf = Counter(m.surface_tone for m in members)
        heads = Counter(m.headline_scale for m in members)
        col1, col2 = 30, 1030
        y = 480
        summary = [
            ("VISUAL INTENT", fmly.visual_intent),
            ("SURFACE", f"allowed: {', '.join(fmly.allowed_surfaces)}; observed in members: {', '.join(f'{k} x{v}' for k, v in surf.items())}; dark surface allowed: {fmly.dark_surface_allowed}; image overlay allowed: False"),
            ("TYPOGRAPHY", f"headline scale {fmly.headline_scale_min}-{fmly.headline_scale_max} (observed {', '.join(f'{k} x{v}' for k, v in heads.items())}); type is the main visual object in {sum(m.type_is_main_visual_object for m in members)} of {len(members)} members; block widths: {', '.join(sorted({m.text_block_width for m in members}))}"),
            ("MEDIA", f"{fmly.media_regions_min}-{fmly.media_regions_max} regions, dominance {fmly.media_dominance_min}-{fmly.media_dominance_max}. " + "; ".join(fmly.allowed_media_behaviors)),
            ("DENSITY", f"{fmly.density_min}-{fmly.density_max}; lead: {fmly.preferred_visual_weight}"),
        ]
        for label, text in summary:
            y = _kv(d, col1, y, 950, label, text, fl, fb)
        y2 = 480
        for label, text in (
            ("SPATIAL BEHAVIOR", "; ".join(fmly.spatial_tendencies)), ("GRAPHIC DEVICES", "; ".join(fmly.graphic_devices) or "none"),
            ("NEGATIVE SPACE", fmly.negative_space_behavior), ("ACCENT", fmly.accent_behavior), ("WHAT MAKES IT DISTINCT", fmly.what_makes_it_distinct),
            ("ANTI-PATTERNS", "; ".join(fmly.anti_patterns)), ("WHEN NOT TO USE", fmly.when_not_to_use),
        ):
            y2 = _kv(d, col2, y2, 950, label, text, fl, fb)
        py = max(y, y2) + 10
        d.text((30, py), "RENDERER RECONSTRUCTION - two different compositions of this family (neutral synthetic content, fixtures)", font=fl, fill=colours[fmly.family_id])
        px = 30
        for n in (1, 2):
            path = renders_dir / f"{fmly.family_id}_{n:02d}.png"
            if path.exists():
                im = Image.open(path).convert("RGB")
                im.thumbnail((480, H - py - 60))
                card.paste(im, (px, py + 32))
                px += im.width + 24
        card.crop((0, 0, W, min(H, py + 32 + 600))).save(out_dir / f"{fmly.family_id}.png")


def _classify_b5_slide(layout: dict) -> str:
    p = structure_profile(layout)
    if "poll_cards" in p["devices"]:
        return "interface_cards"
    if p["media_count"] in ("2", "3") or p["tilted_media"] == "yes":
        return "culture_collage"
    if p["surface"] == "dark" and p["media_coverage"] == "high":
        return "immersive_image_field"
    if p["surface"] == "dark":
        return "dark_type_number_statement"
    if p["media_count"] == "1" and p["media_coverage"] in ("mid", "high"):
        return "hero_object_stage"
    return "light_utility_editorial"


def diagnosis(dna, out: Path, b5_dir: Path) -> dict:
    colours = _colour_map(dna)
    names = {f.family_id: f.name for f in dna.families}
    layouts: list[tuple[str, dict]] = []
    for archetype in ("news_insight", "trend_generative"):
        raw = json.loads((b5_dir / archetype / "cd_structured_output.json").read_text(encoding="utf-8"))
        for i, slide in enumerate(raw.get("slides") or []):
            if isinstance(slide.get("layout"), dict):
                layouts.append((f"{archetype[:5]} {i + 1}", slide["layout"]))
    b5_fam = Counter(_classify_b5_slide(l) for _, l in layouts)
    b5_surface = Counter(structure_profile(l)["surface"] for _, l in layouts)
    ref_fam = {fid: m["count"] for fid, m in family_mix(dna).items()}
    ref_surface = surface_mix(dna)
    ref_dark, ref_light = ref_surface["dark_solid"] + ref_surface["dark_image_field"], ref_surface["light"] + ref_surface["mixed"]
    W, H = 2400, 1900
    sheet = Image.new("RGB", (W, H), _BG)
    d = ImageDraw.Draw(sheet)
    d.text((30, 20), "B.5 vs REFERENCE - why B.5 over-converged (family coverage, not a similarity score)", font=ig_font(38, "black"), fill=_FG)

    def bars(x: int, y: int, title: str, rows: list[tuple[str, int, tuple[int, int, int]]], total: int, width: int = 900) -> int:
        d.text((x, y), title, font=ig_font(26, "black"), fill=_FG)
        y += 44
        for label, n, colour in rows:
            d.text((x, y), label, font=ig_font(20, "medium"), fill=_FG)
            bx = x + 380
            d.rectangle([bx, y + 2, bx + width - 380, y + 26], outline=(70, 74, 84))
            if n:
                d.rectangle([bx, y + 2, bx + round((width - 380) * n / max(1, total)), y + 26], fill=colour)
            d.text((bx + width - 370, y), f"{n} of {total}", font=ig_font(20, "semibold"), fill=_FG)
            y += 38
        return y + 14

    left_rows = [("SURFACE: dark (solid + image field)", ref_dark, (60, 60, 70)), ("SURFACE: light or mixed", ref_light, (235, 236, 240))]
    left_rows += [(names[fid], n, colours[fid]) for fid, n in ref_fam.items()]
    ly = bars(30, 100, f"REFERENCE FAMILY MIX  ({len(dna.samples)} samples; a sample may fit two families)", left_rows, len(dna.samples))
    right_rows = [("SURFACE: dark", b5_surface["dark"], (60, 60, 70)), ("SURFACE: light", b5_surface["light"], (235, 236, 240))]
    right_rows += [(names[fid], b5_fam.get(fid, 0), colours[fid]) for fid in ref_fam]
    ry = bars(1250, 100, f"B.5 OUTPUT FAMILY MIX  ({len(layouts)} real slides: news_insight + trend_generative)", right_rows, len(layouts), width=1000)
    y = max(ly, ry) + 10
    d.text((30, y), "B.5 slides are classified into the nearest family by measurable structure only (surface, media count and coverage, devices); dark and interface/collage devices could not be produced at all.", font=ig_font(18, "medium"), fill=_MUTED)
    y += 46
    d.text((30, y), "REFERENCE samples (the dark majority)", font=ig_font(24, "black"), fill=_FG)
    board = Image.open(REFERENCE_BOARD_PATH).convert("RGB")
    x = 30
    picks = ["S01", "S02", "S05", "S08", "S10", "S12", "S13", "S18"]
    ref_by_id = {s.sample_id: s for s in reference_samples()}
    for sid in picks:
        c = crop_sample(board, ref_by_id[sid], scale=1.0)
        c.thumbnail((270, 320))
        sheet.paste(c, (x, y + 36))
        d.text((x, y + 36 + c.height + 4), sid, font=ig_font(18, "black"), fill=(255, 255, 0))
        x += c.width + 16
    y += 36 + 350
    d.text((30, y), "B.5 real slides (news_insight and trend_generative, light canvas, one rectangular media region)", font=ig_font(24, "black"), fill=_FG)
    x = 30
    for archetype in ("news_insight", "trend_generative"):
        for n in range(1, 6):
            p = b5_dir / archetype / f"slide_{n:02d}.png"
            if p.exists():
                c = Image.open(p).convert("RGB")
                c.thumbnail((270, 340))
                sheet.paste(c, (x, y + 36))
                x += c.width + 14
    sheet.crop((0, 0, W, min(H, y + 36 + 360))).save(out)
    return {"b5_family_counts": dict(b5_fam), "b5_surface": dict(b5_surface), "ref_family_counts": ref_fam, "ref_surface": {k: v for k, v in ref_surface.items()}}


def main() -> None:
    out_dir, b5_dir = Path(sys.argv[1]), Path(sys.argv[2])
    dna = load_visual_dna_v2()
    assert dna is not None
    reference_map(dna, out_dir / "reference_map.png")
    family_cards(dna, out_dir / "family_cards", out_dir / "renderer_examples")
    facts = diagnosis(dna, out_dir / "b5_vs_reference_diagnosis.png", b5_dir)
    (out_dir / "coverage_facts.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")
    print(json.dumps(facts))


if __name__ == "__main__":
    main()
