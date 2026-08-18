"""NINJA PULSE Visual System v1 - Cyrillic font preflight (spec item 6).

Deployment tooling only - meant to be run inside the VPS content_worker image (or any target
environment) BEFORE enabling `presentation_director_mode`/`pulse_brand_enabled` there, to confirm
the brand renderer's Cyrillic text rendering will actually work on that machine.

Guarantees:
  - ZERO network calls, ZERO LLM calls, ZERO Telegram calls - pure local font/Pillow inspection.
  - Reuses the EXACT SAME font-resolution logic `services/brand_renderer.py` uses in production
    (`_resolve_font_path()` - imported, never reimplemented/duplicated), so a PASS here means the
    real renderer will find the same font in the real deployment.
  - Never copies, uploads, or prints the contents of any font file - only its filesystem path and
    rendering metrics.
  - Never installs a font, never writes outside a single throwaway temp/output image file, never
    mutates any system font configuration.
  - Exits 0 on success, non-zero (1) on any failure - suitable for a CI/deploy gate
    (`python scripts/preflight_cyrillic_font.py || exit 1`).

Run: python scripts/preflight_cyrillic_font.py [--out PATH]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from services.brand_renderer import _FONT_CANDIDATE_PATHS, _resolve_font_path  # noqa: E402

REPRESENTATIVE_STRING = "NINJA PULSE — Технологии, искусственный интеллект, данные"

# The Cyrillic-bearing subset of the representative string - what actually gets glyph-checked
# (spaces, em-dash, comma, and Latin "NINJA PULSE" are not useful signal for "does this font have
# Cyrillic glyphs", the one thing this preflight exists to catch).
_CYRILLIC_CHARS = sorted({ch for ch in REPRESENTATIVE_STRING if "А" <= ch <= "я" or ch in "ЁёІіЇїЎў"})


def _check_glyph_coverage(font: ImageFont.FreeTypeFont) -> list[str]:
    """Returns the list of Cyrillic characters the font fails to render as a real glyph (a
    degenerate/zero-area bounding box is PIL/FreeType's own signal for a missing/.notdef glyph) -
    empty list means full coverage."""
    missing: list[str] = []
    for ch in _CYRILLIC_CHARS:
        bbox = font.getbbox(ch)
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        if width <= 0 or height <= 0:
            missing.append(ch)
    return missing


def _render_verification_image(font: ImageFont.FreeTypeFont, out_path: Path) -> bool:
    """Renders the representative string to a tiny local image and confirms it is not blank (a
    font that "loads" but silently emits empty/notdef glyphs for every character would otherwise
    pass a naive "did ImageFont.truetype() raise" check) - the second, independent verification
    layer alongside `_check_glyph_coverage()`'s per-glyph bbox check."""
    canvas = Image.new("RGB", (900, 80), (0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((10, 20), REPRESENTATIVE_STRING, font=font, fill=(255, 255, 255))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG")

    _min_luminance, max_luminance = canvas.convert("L").getextrema()
    return max_luminance > 0


def run(out_path: Path) -> int:
    print("NINJA PULSE Cyrillic font preflight - zero network, zero LLM, zero Telegram.")
    print(f"Representative string: {REPRESENTATIVE_STRING!r}")
    print(f"Font candidate search order (from services/brand_renderer.py, unmodified): {list(_FONT_CANDIDATE_PATHS)}")

    font_path = _resolve_font_path()
    if font_path is None:
        print("FAIL: no Cyrillic-capable font found on this machine (falls back to Pillow's own "
              "ASCII-only default font - services/brand_renderer.py's own documented degraded path).")
        return 1
    print(f"Resolved font path: {font_path}")

    try:
        font = ImageFont.truetype(font_path, 32)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: font file could not be loaded by Pillow ({exc!r}).")
        return 1

    missing = _check_glyph_coverage(font)
    if missing:
        print(f"FAIL: {len(missing)}/{len(_CYRILLIC_CHARS)} Cyrillic characters have no real glyph in this font: {missing}")
        return 1
    print(f"PASS: all {len(_CYRILLIC_CHARS)} Cyrillic characters in the representative string have real glyphs.")

    rendered_ok = _render_verification_image(font, out_path)
    if not rendered_ok:
        print(f"FAIL: rendered verification image at {out_path} is entirely blank.")
        return 1
    print(f"PASS: rendered a non-blank verification image at {out_path} (visually inspect if in doubt).")

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path,
        default=Path(tempfile.gettempdir()) / "ninja_pulse_cyrillic_preflight.png",
        help="Where to write the tiny local verification image (default: a system temp file).",
    )
    args = parser.parse_args()
    sys.exit(run(args.out))
