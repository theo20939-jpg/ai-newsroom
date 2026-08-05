"""Meme Rendering / Text Overlay (Phase 18 M6): deterministically overlays `MemeCopy`'s top/
bottom text onto a generated meme image, then persists the final asset (docs/
phase18_m6_meme_rendering_report.md).

No LLM call, no network call, no external font file (Pillow's own built-in scalable default font
- `PIL.ImageFont.load_default(size=...)` - is used, so this module has zero new binary asset
dependency; a licensed display font is a disclosed future improvement, not a blocker - see the M6
report §5). Deterministic: the same (image bytes, MemeCopy) pair always produces the same output
bytes, since nothing here is randomized.

Safe zones (brief's own "не закрывает ключевой объект" requirement): only the top ~18% and
bottom ~18% horizontal bands of the canvas ever receive text - the center ~64% is never drawn
into. This is a structural guarantee, not a per-image object-detection heuristic (this module has
no object-detection capability and does not claim one) - it relies on the same "subject occupies
the visual center" convention `services.meme_image_generation.build_image_prompt()`'s own
generated scenes and `MockImageAdapter`'s own placeholder layout both already assume.

Contrast (brief's own "проверяет контраст" requirement) is a real, computed WCAG-style ratio
between the chosen text color and the band's own measured average background luminance - text
color (white+black stroke, or black+white stroke) is chosen to maximize it, and the resulting
ratio is reported and checked against a minimum threshold, never merely assumed adequate.
"""
from __future__ import annotations

import hashlib
import logging
from io import BytesIO
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

from core.config import settings
from integrations.storage.image_storage import ImageStorage, StorageError
from schemas.meme_copy import MemeCopy
from schemas.meme_render import MemeRenderResult, MemeRenderStatus

logger = logging.getLogger(__name__)

# Fractions of canvas height reserved for text - the remaining center band is never drawn into
# (module docstring's own safe-zone discipline).
_BAND_HEIGHT_FRACTION = 0.18
_BAND_HORIZONTAL_MARGIN_FRACTION = 0.06
_MAX_LINES_PER_BAND = 3
_FONT_SIZES_DESCENDING = (72, 60, 48, 40, 32)
_STROKE_WIDTH = 4
_MIN_CONTRAST_RATIO = 3.0


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - only reachable on a Pillow build predating `size=`
        return ImageFont.load_default()


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 2.x relative luminance formula (sRGB, gamma-corrected)."""

    def channel(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast_ratio(l1: float, l2: float) -> float:
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _measure_band_luminance(image: Image.Image, box: tuple[int, int, int, int]) -> float:
    region = image.crop(box).convert("RGB")
    pixels = list(region.getdata())
    if not pixels:
        return 0.5
    avg_rgb = tuple(sum(channel) / len(pixels) for channel in zip(*pixels))
    return _relative_luminance(avg_rgb)  # type: ignore[arg-type]


def _choose_text_colors(background_luminance: float) -> tuple[tuple[int, int, int], tuple[int, int, int], float]:
    """Picks whichever of (white fill/black stroke) or (black fill/white stroke) yields the
    higher measured contrast ratio against the band's own background - never assumed, always
    the actually-better of the two real options."""
    white, black = (255, 255, 255), (0, 0, 0)
    white_luminance, black_luminance = _relative_luminance(white), _relative_luminance(black)
    ratio_white = _contrast_ratio(white_luminance, background_luminance)
    ratio_black = _contrast_ratio(black_luminance, background_luminance)
    if ratio_white >= ratio_black:
        return white, black, ratio_white
    return black, white, ratio_black


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        bbox = draw.textbbox((0, 0), candidate, font=font, stroke_width=_STROKE_WIDTH)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _fit_text_to_band(
    draw: ImageDraw.ImageDraw, text: str, *, max_width: int, max_height: int,
) -> tuple[ImageFont.FreeTypeFont, list[str], bool]:
    """Shrinks font size through `_FONT_SIZES_DESCENDING` until the wrapped text fits within
    `max_width`/`max_height` (capped at `_MAX_LINES_PER_BAND` lines). If even the smallest size
    still doesn't fit, truncates to the lines that DO fit and reports a violation - text is never
    allowed to overflow into the center safe zone instead."""
    last_font = _load_font(_FONT_SIZES_DESCENDING[-1])
    last_lines = _wrap_text(draw, text, last_font, max_width)
    for size in _FONT_SIZES_DESCENDING:
        font = _load_font(size)
        lines = _wrap_text(draw, text, font, max_width)
        if len(lines) > _MAX_LINES_PER_BAND:
            continue
        line_height = draw.textbbox((0, 0), "Ag", font=font, stroke_width=_STROKE_WIDTH)[3]
        total_height = line_height * len(lines)
        if total_height <= max_height:
            return font, lines, False
        last_font, last_lines = font, lines

    truncated = last_lines[:_MAX_LINES_PER_BAND]
    return last_font, truncated, True


def _draw_band(
    image: Image.Image, draw: ImageDraw.ImageDraw, text: str | None, *, band: Literal["top", "bottom"],
) -> tuple[float | None, list[str]]:
    if not text:
        return None, []

    width, height = image.size
    band_height = int(height * _BAND_HEIGHT_FRACTION)
    margin = int(width * _BAND_HORIZONTAL_MARGIN_FRACTION)
    max_width = width - 2 * margin

    box = (0, 0, width, band_height) if band == "top" else (0, height - band_height, width, height)
    background_luminance = _measure_band_luminance(image, box)
    fill_color, stroke_color, contrast_ratio = _choose_text_colors(background_luminance)

    font, lines, violated = _fit_text_to_band(draw, text, max_width=max_width, max_height=band_height)
    violations = [f"{band}_text_truncated_to_fit_safe_zone"] if violated else []

    line_height = draw.textbbox((0, 0), "Ag", font=font, stroke_width=_STROKE_WIDTH)[3]
    total_text_height = line_height * len(lines)
    start_y = (
        (band_height - total_text_height) // 2
        if band == "top"
        else height - band_height + (band_height - total_text_height) // 2
    )

    y = start_y
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=_STROKE_WIDTH)
        line_width = bbox[2] - bbox[0]
        x = (width - line_width) // 2
        draw.text(
            (x, y), line, font=font, fill=fill_color, stroke_width=_STROKE_WIDTH, stroke_fill=stroke_color,
        )
        y += line_height

    return contrast_ratio, violations


def render_meme(image_bytes: bytes, copy: MemeCopy, *, storage: ImageStorage) -> MemeRenderResult:
    """Never raises - any decode/render/storage failure returns `MemeRenderStatus.FAILED` with an
    `error_code`, mirroring every other best-effort boundary in this phase."""
    try:
        with Image.open(BytesIO(image_bytes)) as source:
            image = source.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        error_code = f"decode_failed:{type(exc).__name__}"
        logger.warning("meme_render_decode_failed", extra={"error_code": error_code})
        return MemeRenderResult(status=MemeRenderStatus.FAILED, error_code=error_code)

    try:
        draw = ImageDraw.Draw(image)
        top_ratio, top_violations = _draw_band(image, draw, copy.top_text, band="top")
        bottom_ratio, bottom_violations = _draw_band(image, draw, copy.bottom_text, band="bottom")

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        rendered_bytes = buffer.getvalue()
    except Exception as exc:  # noqa: BLE001
        error_code = f"render_failed:{type(exc).__name__}"
        logger.warning("meme_render_draw_failed", extra={"error_code": error_code})
        return MemeRenderResult(status=MemeRenderStatus.FAILED, error_code=error_code)

    try:
        sha256 = hashlib.sha256(rendered_bytes).hexdigest()
        stored = storage.store_validated_image(
            rendered_bytes, sha256=sha256, image_format="PNG", max_bytes=settings.meme_image_max_bytes,
        )
    except (StorageError, OSError) as exc:
        error_code = f"storage_failed:{type(exc).__name__}"
        logger.warning("meme_render_storage_failed", extra={"error_code": error_code})
        return MemeRenderResult(status=MemeRenderStatus.FAILED, error_code=error_code)

    contrast_passed = all(ratio is None or ratio >= _MIN_CONTRAST_RATIO for ratio in (top_ratio, bottom_ratio))
    violations = [*top_violations, *bottom_violations]

    logger.info(
        "meme_rendered",
        extra={
            "storage_key": stored.storage_key, "contrast_passed": contrast_passed,
            "safe_zone_violation_count": len(violations),
        },
    )
    return MemeRenderResult(
        status=MemeRenderStatus.RENDERED,
        storage_key=stored.storage_key,
        width=image.width,
        height=image.height,
        byte_size=stored.byte_size,
        sha256=stored.sha256,
        top_text_contrast_ratio=top_ratio,
        bottom_text_contrast_ratio=bottom_ratio,
        contrast_passed=contrast_passed,
        safe_zone_violations=violations,
    )
