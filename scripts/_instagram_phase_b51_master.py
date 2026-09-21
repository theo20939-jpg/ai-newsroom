"""Phase B.5.1: build real_archetype_master.png from the acceptance output (pixels first; minimal labels).

Each archetype row shows: ARCHETYPE, REAL MODEL yes/no, VALIDATION pass/fail, and under every slide its chosen visual family. An archetype whose real
output failed validation shows the failure and NO fixture in its place.

Usage: python scripts/_instagram_phase_b51_master.py <out_dir>"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.instagram_visual_profiles import ig_font  # noqa: E402

ORDER = ("ai_hack", "news_insight", "news_recap", "trend_generative")
SHORT = {"immersive_image_field": "IMMERSIVE", "hero_object_stage": "HERO OBJECT", "internet_culture_collage": "COLLAGE",
         "dark_type_number_statement": "DARK TYPE/NUMBER", "interface_cards": "INTERFACE CARDS", "light_utility_editorial": "LIGHT UTILITY"}
BG, FG, MUTED, OK, BAD = (16, 17, 21), (240, 241, 244), (150, 155, 166), (90, 210, 130), (240, 90, 90)


def main() -> None:
    out = Path(sys.argv[1])
    thumb_h, gap = 400, 10
    rows = []
    for name in ORDER:
        manifest_path = out / name / "render_manifest.json"
        if not manifest_path.exists():
            rows.append((name, None, []))
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        images = sorted((out / name).glob("slide_*.png"))
        rows.append((name, manifest, images))
    widest = 0
    prepared = []
    for name, manifest, images in rows:
        thumbs = []
        for img_path in images:
            im = Image.open(img_path).convert("RGB")
            thumbs.append(im.resize((round(im.width * thumb_h / im.height), thumb_h), Image.Resampling.LANCZOS))
        width = sum(t.width + gap for t in thumbs) + gap
        widest = max(widest, width)
        prepared.append((name, manifest, thumbs))
    W = max(widest, 1500) + 20
    H = 90 + sum(60 + (thumb_h + 62 if thumbs else 90) + 24 for _, _, thumbs in prepared)
    sheet = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(sheet)
    d.text((20, 18), "REAL CREATIVE DIRECTOR (prompt v9.1 + Visual DNA v2) - four real archetype posts through the accepted renderer", font=ig_font(32, "black"), fill=FG)
    y = 84
    for name, manifest, thumbs in prepared:
        real = bool(manifest and manifest.get("REAL_MODEL"))
        valid = manifest.get("VALIDATION") if manifest else "FAIL"
        if valid == "PASS" and manifest.get("art_validation_passed") is False:
            valid = "FAIL (art gate)"
        d.text((20, y), name.upper(), font=ig_font(28, "black"), fill=(255, 255, 0))
        src = str((manifest or {}).get("MODEL_SOURCE"))
        source = "REUSED FROM B.5.1.1" if "B.5.1.1" in src else ("REUSED FROM B.5.1.2" if "B.5.1.2 REAL OUTPUT" in src else "NEW B.5.1.2 CALL")
        d.text((320, y + 4), f"REAL MODEL - {source}" if real else "REAL MODEL: NO", font=ig_font(22, "semibold"), fill=OK if real else BAD)
        d.text((820, y + 4), f"VALIDATION: {valid}", font=ig_font(22, "semibold"), fill=OK if valid == "PASS" else BAD)
        warns = [w.split(":")[0] for w in ((manifest or {}).get("art_warnings") or [])]
        if warns:
            d.text((1150, y + 6), "WARNINGS: " + ", ".join(warns)[:60], font=ig_font(18, "medium"), fill=MUTED)
        y += 54
        if not thumbs:
            reason = (manifest or {}).get("contract_error") or (manifest or {}).get("outcome_reason") or (manifest or {}).get("error") or "no output"
            d.text((20, y + 20), f"No render - the real output failed validation: {str(reason)[:180]}", font=ig_font(22, "medium"), fill=BAD)
            y += 90 + 24
            continue
        families = [s["visual_family_chosen"] for s in manifest["slides"]]
        x = gap
        for i, t in enumerate(thumbs):
            sheet.paste(t, (x, y))
            family = families[i] if i < len(families) else None
            executed = manifest["slides"][i].get("visual_family_executed") if i < len(manifest["slides"]) else None
            label = SHORT.get(family or "", str(family))
            d.text((x, y + thumb_h + 4), f"SELECTED: {label}", font=ig_font(16, "semibold"), fill=FG)
            drawn = SHORT.get(executed or "", str(executed))
            d.text((x, y + thumb_h + 24), f"EXECUTED: {drawn}", font=ig_font(15, "medium"), fill=FG if executed == family else BAD)
            sl = manifest["slides"][i] if i < len(manifest["slides"]) else {}
            adapted = bool(sl.get("collage_geometry_adapted") or sl.get("calm_zone_adapted"))
            d.text((x, y + thumb_h + 42), f"ADAPTED: {'YES' if adapted else 'NO'}", font=ig_font(15, "medium"), fill=OK if adapted else MUTED)
            x += t.width + gap
        y += thumb_h + 62 + 24
    sheet.crop((0, 0, W, y + 10)).save(out / "real_archetype_master.png")
    print("master written")


if __name__ == "__main__":
    main()
