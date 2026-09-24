"""The Instagram KAGE brand layer: palette + the K symbol + its adaptive light/dark behaviour.

Instagram-only. Telegram, memes and every shared NNJ asset (services/nnj_master_news_mark.py, assets/brand/nnj_logo*) are untouched and
unimported - Instagram's visible brand mark no longer comes from the NNJ rasterizer.

Palette = the printed labels of the founder brandboard (references/kage/kage_brandboard.jpg), never the JPEG swatch pixels. KAGE is
near-monochrome: five neutrals and ONE violet accent, used small and precisely - never as a surface system.

Symbol = assets/brand/kage/, derived deterministically from the founder reference by scripts/_kage_brand_assets.py: the supplied faceted
pixels for DARK surfaces, and the same alpha mask with inverted channels for LIGHT surfaces. Never redrawn, traced or generated."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image

SHADOW = (0x0B, 0x0B, 0x0D)    # #0B0B0D primary dark ground
GRAPHITE = (0x1A, 0x1A, 0x1D)  # #1A1A1D second dark ground
STONE = (0x2B, 0x2B, 0x2F)     # #2B2B2F raised dark: cards, panels, key-card fills
MIST = (0x8E, 0x8E, 0x93)      # #8E8E93 secondary copy on dark, quiet rules, neutral secondary accent
LIGHT = (0xED, 0xED, 0xED)     # #EDEDED the ONE approved light surface (founder decision 4)
ACCENT = (0x7F, 0x5F, 0xFF)    # #7F5FFF the canonical KAGE violet (founder decision 2)

_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "brand" / "kage"
SYMBOL_ON_DARK = _ASSET_DIR / "kage_symbol_on_dark.png"
SYMBOL_ON_LIGHT = _ASSET_DIR / "kage_symbol_on_light.png"

# The K is compact where the NNJ wordmark was wide and flat: at the old 5%-of-width box it would read as a heavy block. It is drawn at this
# share of the reserved mark width, right-aligned inside the same reserved box, so no text layout moves.
SYMBOL_WIDTH_SHARE = 0.72
# mean luminance under the mark at or above this -> the surface is light (same threshold the renderer uses for text colour)
LIGHT_SURFACE_LUMA = 118


@lru_cache(maxsize=16)
def kage_symbol(*, target_width: int, on_light: bool) -> Image.Image:
    """The approved K at `target_width` px (aspect preserved), dark planes for a light surface or the supplied light planes for a dark one."""
    if target_width <= 0:
        raise ValueError("target_width must be positive")
    source = Image.open(SYMBOL_ON_LIGHT if on_light else SYMBOL_ON_DARK).convert("RGBA")
    height = max(1, round(source.height * target_width / source.width))
    return source.resize((target_width, height), Image.Resampling.LANCZOS)


def surface_is_light(canvas: Image.Image, box: tuple[int, int, int, int]) -> bool:
    hist = canvas.crop(box).convert("L").histogram()
    total = sum(hist) or 1
    return sum(i * c for i, c in enumerate(hist)) / total >= LIGHT_SURFACE_LUMA


def place_kage_symbol(canvas: Image.Image, *, reserve_x: int, bottom_y: int, reserve_width: int, align: str = "right") -> tuple[int, int, int, int]:
    """Composite ONE K into the reserved mark box whose left edge is `reserve_x` and whose bottom is `bottom_y`. The variant is chosen from
    the pixels actually beneath it. Returns the symbol's box."""
    width = max(1, round(reserve_width * SYMBOL_WIDTH_SHARE))
    probe = kage_symbol(target_width=width, on_light=False)
    x = reserve_x + (reserve_width - width if align == "right" else 0)
    y = bottom_y - probe.height
    box = (max(0, x - 8), max(0, y - 8), min(canvas.width, x + probe.width + 8), min(canvas.height, bottom_y + 8))
    mark = kage_symbol(target_width=width, on_light=True) if surface_is_light(canvas, box) else probe
    if canvas.mode == "RGBA":
        canvas.alpha_composite(mark, (x, y))
    else:
        canvas.paste(mark, (x, y), mark)
    return x, y, x + mark.width, y + mark.height
