"""Phase B.5.1.3: compact BEFORE (B.5.1.2 legacy fallback) / AFTER (adapted collage) comparison of the three previously rejected collage slides.

Usage: python scripts/_instagram_phase_b513_before_after.py <before_dir> <after_dir>"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.instagram_visual_profiles import ig_font  # noqa: E402

BG, FG, MUTED = (16, 17, 21), (240, 241, 244), (150, 155, 166)


def main() -> None:
    before, after = Path(sys.argv[1]), Path(sys.argv[2])
    cases = []
    for name in ("news_recap", "trend_generative"):
        manifest = json.loads((after / name / "render_manifest.json").read_text(encoding="utf-8"))
        for slide in manifest["slides"]:
            if slide.get("collage_geometry_adapted"):
                cases.append((name, slide["index"]))
    th, gap = 560, 16
    tiles = []
    for name, idx in cases:
        old = Image.open(before / name / f"slide_{idx + 1:02d}.png").convert("RGB")
        new = Image.open(after / name / f"slide_{idx + 1:02d}.png").convert("RGB")
        tiles.append((name, idx, old.resize((round(old.width * th / old.height), th)), new.resize((round(new.width * th / new.height), th))))
    width = sum(o.width + n.width + gap * 3 for _, _, o, n in tiles) + gap
    sheet = Image.new("RGB", (width, th + 130), BG)
    d = ImageDraw.Draw(sheet)
    d.text((gap, 12), "COLLAGE EXECUTION - BEFORE (legacy fallback)  ->  AFTER (adapted collage)", font=ig_font(28, "black"), fill=FG)
    x = gap
    for name, idx, old, new in tiles:
        d.text((x, 64), f"{name.upper()} slide {idx + 1}", font=ig_font(20, "semibold"), fill=(255, 255, 0))
        sheet.paste(old, (x, 100))
        d.text((x, 100 + th + 4), "BEFORE", font=ig_font(16, "semibold"), fill=MUTED)
        sheet.paste(new, (x + old.width + gap, 100))
        d.text((x + old.width + gap, 100 + th + 4), "AFTER", font=ig_font(16, "semibold"), fill=FG)
        x += old.width + new.width + gap * 3
    sheet.save(after / "collage_before_after.png")
    print("written", len(cases), "comparisons")


if __name__ == "__main__":
    main()
