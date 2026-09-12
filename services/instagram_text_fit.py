"""INSTAGRAM-VISUAL-SYSTEM-V1-1: shared deterministic text-fit helper, used by every Instagram
layout module. Extracted from the original section-9 `_fit_text()` (INSTAGRAM-EXECUTION-
FOUNDATION-1) so every visual family shares ONE shrink -> wrap -> truncate implementation rather
than re-deriving it per layout."""
from __future__ import annotations

from PIL import ImageDraw, ImageFont

from services.instagram_visual_profiles import ig_font


def fit_text_block(
    draw: ImageDraw.ImageDraw, text: str, *, font_max: int, font_min: int, max_width: int,
    max_lines: int, weight: str = "black",
) -> tuple[ImageFont.FreeTypeFont, list[str], bool]:
    """Deterministic shrink-then-wrap-then-truncate text fit. Returns (font, lines, clipped).
    `clipped=True` whenever real content had to be truncated with an ellipsis - never silently
    dropped without a signal."""
    words = text.split()
    size = font_max
    while size >= font_min:
        font = ig_font(size, weight)
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        if len(lines) <= max_lines and all(draw.textlength(line, font=font) <= max_width for line in lines):
            return font, lines, False
        size -= 4

    font = ig_font(font_min, weight)
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    lines = lines[:max_lines]
    if lines:
        last = lines[-1]
        while draw.textlength(last + "...", font=font) > max_width and len(last) > 1:
            last = last[:-1]
        lines[-1] = last.rstrip() + "..."
    return font, lines, True


def box4(bbox: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    """Converts a PIL `textbbox()` result (four floats) into the fixed 4-int tuple
    `TextRegionSpec.box`/`TextRegion.box` actually declare - shared so every layout module gets a
    real, statically-checkable 4-tuple instead of a variable-length `tuple(int(v) for v in bbox)`."""
    return (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))


def measure_block_height(draw: ImageDraw.ImageDraw, lines: list[str], font: ImageFont.FreeTypeFont, *, line_gap_frac: float = 0.18) -> int:
    if not lines:
        return 0
    total = 0.0
    gap = round(font.size * line_gap_frac)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        total += (bbox[3] - bbox[1])
    total += gap * (len(lines) - 1)
    return round(total)
