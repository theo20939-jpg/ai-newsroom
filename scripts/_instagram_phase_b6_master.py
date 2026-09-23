"""Phase B.6: build real_archetype_master.png from the acceptance output. Pixels first: per archetype the real hook line, then every rendered slide with a
two-line label (media source, chosen -> executed family). A failed archetype shows its reason and NO fixture. Real-model output only.

Usage: python scripts/_instagram_phase_b6_master.py <out_dir>"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.instagram_visual_profiles import ig_font  # noqa: E402

ORDER = ("ai_hack", "news_insight", "news_recap", "trend_generative")
SHORT = {"immersive_image_field": "IMMERSIVE", "hero_object_stage": "HERO", "internet_culture_collage": "COLLAGE", "dark_type_number_statement": "DARK TYPE",
         "interface_cards": "INTERFACE", "light_utility_editorial": "LIGHT TYPE", "legacy_role_fallback": "FALLBACK"}
BG, FG, MUTED, OK, BAD, GOLD = (16, 17, 21), (240, 241, 244), (150, 155, 166), (90, 210, 130), (240, 90, 90), (255, 220, 60)


def _wrap(draw, text: str, font, width: int) -> list[str]:
    lines, current = [], ""
    for word in str(text).split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    return lines + ([current] if current else [])


def main() -> None:
    out = Path(sys.argv[1])
    thumb_h, gap = 420, 10
    prepared = []
    widest = 0
    for name in ORDER:
        path = out / name / "render_manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        images = sorted((out / name).glob("slide_*.png")) if manifest else []
        thumbs = []
        for img in images:
            im = Image.open(img).convert("RGB")
            thumbs.append(im.resize((round(im.width * thumb_h / im.height), thumb_h), Image.Resampling.LANCZOS))
        widest = max(widest, sum(t.width + gap for t in thumbs) + gap)
        prepared.append((name, manifest, thumbs))
    W = max(widest, 1700) + 20
    row_h = 118 + thumb_h + 58 + 26
    H = 90 + sum(row_h if thumbs else 190 for _, _, thumbs in prepared)
    sheet = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(sheet)
    d.text((20, 18), "KAGE INSTAGRAM - real Creative Director + generated media + Visual DNA v2 (" + (sys.argv[2] if len(sys.argv) > 2 else "") + ")", font=ig_font(32, "black"), fill=FG)
    y = 84
    for name, manifest, thumbs in prepared:
        valid = manifest.get("VALIDATION") if manifest else "FAIL"
        if valid == "PASS" and manifest.get("art_validation_passed") is False:
            valid = "FAIL (art gate)"
        d.text((20, y), name.upper(), font=ig_font(28, "black"), fill=GOLD)
        d.text((330, y + 4), (("REAL PLAN: " + manifest["MODEL_SOURCE"]) if manifest.get("MODEL_SOURCE", "").startswith("REPLAYED") else "REAL MODEL: YES - FRESH CALL") if manifest and manifest.get("REAL_MODEL") else "REAL MODEL: NO", font=ig_font(22, "semibold"), fill=OK)
        d.text((820, y + 4), f"VALIDATION: {valid}", font=ig_font(22, "semibold"), fill=OK if valid == "PASS" else BAD)
        counts = (manifest or {}).get("media_source_counts") or {}
        if counts:
            d.text((1130, y + 6), f"SOURCE {counts.get('source', 0)}  GENERATED {counts.get('generated', 0)}  GRAPHIC {counts.get('graphic', 0)}  TEXT-ONLY {len((manifest or {}).get('text_only_slides') or [])}",
                   font=ig_font(18, "medium"), fill=MUTED)
        y += 48
        hook = (manifest or {}).get("hook_text")
        if hook:
            font = ig_font(24, "black")
            emotion = str((manifest or {}).get("hook_emotion") or "?").upper().replace("_", " ")
            for line in _wrap(d, f"HOOK [{emotion}]: {hook}", font, W - 60)[:2]:
                d.text((20, y), line, font=font, fill=FG)
                y += 30
        y = max(y, y) + 6
        if not thumbs:
            reason = (manifest or {}).get("contract_error") or (manifest or {}).get("validation_error") or (manifest or {}).get("outcome_reason") or "no output"
            d.text((20, y + 20), f"No render - the real output failed: {str(reason)[:170]}", font=ig_font(22, "medium"), fill=BAD)
            y += 190 - 84
            continue
        x = gap
        media_slides = (manifest or {}).get("media_slides") or []
        for i, t in enumerate(thumbs):
            sheet.paste(t, (x, y))
            slide = manifest["slides"][i] if i < len(manifest["slides"]) else {}
            ms = media_slides[i] if i < len(media_slides) else {}
            source = {"SOURCE": "S", "GENERATED": "GEN", "GRAPHIC": "GFX"}.get(str(ms.get("media_source") or "?").upper(), "?")
            d.text((x, y + thumb_h + 4), source, font=ig_font(17, "black"), fill=GOLD if source == "GEN" else FG)
            chosen, executed = slide.get("visual_family_chosen"), slide.get("visual_family_executed")
            d.text((x, y + thumb_h + 26), f"{SHORT.get(chosen or '', chosen)} > {SHORT.get(executed or '', executed)}", font=ig_font(15, "medium"), fill=FG if chosen == executed else BAD)
            x += t.width + gap
        y += thumb_h + 58 + 26
    sheet.crop((0, 0, W, y + 10)).save(out / "real_archetype_master.png")
    print("master written")


if __name__ == "__main__":
    main()
