"""Derive the Instagram KAGE symbol production assets from the founder reference - deterministic, no model, no redraw.

Source: references/kage/kage_symhol.png (founder-approved K symbol, RGBA, light faceted planes for DARK surfaces). The reference file is
only read, never modified.

  kage_symbol_on_dark.png   the exact supplied pixels, cropped to the symbol's alpha bounding box (+2px transparent pad).
  kage_symbol_on_light.png  the same alpha mask and the same pixels with each RGB channel inverted (v -> 255 - v): identical geometry and
                            facet boundaries, dark planes for a light surface (founder decision 1, option A - the brandboard shows the K
                            dark on light). Alpha is copied unchanged.

Usage: python scripts/_kage_brand_assets.py <path/to/kage_symhol.png> [out_dir]"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
ALPHA_FLOOR = 8  # alpha below this is resampling haze, not symbol (measured: nothing above it lies outside the K)
PAD = 2


def derive(source: Path) -> tuple[Image.Image, Image.Image]:
    symbol = Image.open(source).convert("RGBA")
    alpha = symbol.getchannel("A")
    box = alpha.point(lambda v: 255 if v >= ALPHA_FLOOR else 0).getbbox()
    if box is None:
        raise ValueError("the reference symbol has no visible pixels")
    box = (max(0, box[0] - PAD), max(0, box[1] - PAD), min(symbol.width, box[2] + PAD), min(symbol.height, box[3] + PAD))
    on_dark = symbol.crop(box)
    r, g, b, a = on_dark.split()
    on_light = Image.merge("RGBA", (ImageChops.invert(r), ImageChops.invert(g), ImageChops.invert(b), a))
    return on_dark, on_light


def main() -> None:
    source = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "assets" / "brand" / "kage"
    out.mkdir(parents=True, exist_ok=True)
    on_dark, on_light = derive(source)
    on_dark.save(out / "kage_symbol_on_dark.png", optimize=True)
    on_light.save(out / "kage_symbol_on_light.png", optimize=True)
    print(on_dark.size)


if __name__ == "__main__":
    main()
