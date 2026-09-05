"""Meme Rendering / Text Overlay (Phase 18 M6): deterministically overlays `MemeCopy`'s top/
bottom text onto a generated meme image, then persists the final asset (docs/
phase18_m6_meme_rendering_report.md).

No LLM call, no network call. MEME-PROD-2.1 requires Russian on-image text, and Pillow's own
built-in default font (`PIL.ImageFont.load_default()`) has NO Cyrillic glyphs - confirmed
empirically (real production evidence + reproduced locally: Cyrillic renders as ".notdef" tofu
boxes). `_load_font()` below reuses `services/brand_renderer.py`'s own already-established,
already-working font-resolution mechanism verbatim (never downloaded, never bundled: common
OS-provided font paths only - Windows always ships Arial; DejaVu Sans/Liberation Sans are the
typical Linux-server-distro defaults, commonly pre-installed via `fonts-dejavu-core`/
`fonts-liberation` - `settings.brand_font_path` can pin an exact path). Falls back to Pillow's own
ASCII-only default font only if no candidate path resolves (degraded Cyrillic rendering, never a
crash, never blocked delivery) - disclosed production prerequisite: the VPS must actually have one
of these fonts installed for Cyrillic meme text to render correctly (this exact caveat is already
disclosed, unresolved, for `brand_renderer.py`'s identical mechanism - "VPS Cyrillic rendering is
UNVERIFIED, no VPS access" - the same disclosed limitation applies here, now duplicated rather than
newly introduced). Deterministic: the same (image bytes, MemeCopy) pair always produces the same
output bytes, since nothing here is randomized.

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
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

from core.config import settings
from integrations.storage.image_storage import ImageStorage, StorageError
from schemas.meme_copy import MemeCopy
from schemas.meme_render import MemeRenderResult, MemeRenderStatus

logger = logging.getLogger(__name__)

# MEME-PROD-2.1: byte-for-byte the same candidate list services/brand_renderer.py::
# _FONT_CANDIDATE_PATHS already established - duplicated locally per this codebase's own
# established per-module-private-helper convention, not imported (that module's own list is
# module-private too). Reuses the SAME `settings.brand_font_path` override, so one operator-set
# path pins the font for both NEWS/DATA/QUOTE cards and memes at once.
_FONT_CANDIDATE_PATHS: tuple[str, ...] = (
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)

_font_path_resolution: list[str | None] = []  # single-element cache; [] means "not yet resolved"


def _resolve_font_path() -> str | None:
    if _font_path_resolution:
        return _font_path_resolution[0]
    candidates = ([settings.brand_font_path] if settings.brand_font_path else []) + list(_FONT_CANDIDATE_PATHS)
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            logger.info("meme_render_font_resolved", extra={"font_path": candidate})
            _font_path_resolution.append(candidate)
            return candidate
    logger.warning("meme_render_no_cyrillic_font_found_using_ascii_only_default")
    _font_path_resolution.append(None)
    return None

# Fractions of canvas height reserved for text - the remaining center band is never drawn into
# (module docstring's own safe-zone discipline).
_BAND_HEIGHT_FRACTION = 0.18
_BAND_HORIZONTAL_MARGIN_FRACTION = 0.06
# MEME-PROD-2.1: was 3 - the brief's own "top text max 2 lines; bottom text max 2 lines" rule.
_MAX_LINES_PER_BAND = 2
# MEME-PROD-2.1: ~17% smaller than the prior (72, 60, 48, 40, 32) - brief's own "reduce meme text
# size approximately 15-20%" typography-polish request; still descending in the same five steps
# `_fit_text_to_band()` shrinks through.
_FONT_SIZES_DESCENDING = (60, 50, 40, 33, 27)
_STROKE_WIDTH = 4
_MIN_CONTRAST_RATIO = 3.0
# MEME-PROD-2.1: mirrors `meme_watermark.py`'s own `_WATERMARK_WIDTH_FRACTION` (0.16) +
# `_MARGIN_FRACTION` (0.035) footprint, duplicated locally per this codebase's established
# per-module-private-helper convention (that module is watermark-only and these are private).
# Reserved as extra right-side clearance, canvas-width-relative, ONLY in the one band the
# watermark actually occupies (brief's own "no overlap with watermark" rule) - real overlap was
# confirmed by rendering a long top/bottom line before this fix (watermark composites AFTER this
# module's own text, so an overlap would draw the mark on top of - i.e. obscuring - the text).
_WATERMARK_CLEARANCE_FRACTION = 0.22


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """MEME-PROD-2.1: tries `_resolve_font_path()`'s real Cyrillic-capable TrueType font first
    (mirrors `brand_renderer.py::_font()`'s own identical try/except-fallback shape) - only falls
    back to Pillow's own ASCII-only `load_default()` if no OS font path resolved, or if loading the
    resolved path fails for any reason (never a crash, never blocked delivery).

    Return type is a real union, not just `FreeTypeFont` - the fallback branch returns Pillow's own
    base `ImageFont` type instead. Both are accepted transparently by every `ImageDraw` method this
    module calls (`textbbox`/`text`), so callers never need to distinguish them (found by mypy
    during Phase 18 final acceptance - the original narrower annotation was simply inaccurate, not
    a real bug)."""
    font_path = _resolve_font_path()
    if font_path is not None:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:  # noqa: BLE001 - a font-load failure must degrade, never crash rendering
            logger.warning("meme_render_font_load_failed", extra={"font_path": font_path})
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


def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, max_width: int,
) -> list[str]:
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
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, list[str], bool]:
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
    reserve_watermark_clearance: bool = False,
) -> tuple[float | None, list[str]]:
    if not text:
        return None, []

    width, height = image.size
    band_height = int(height * _BAND_HEIGHT_FRACTION)
    margin = int(width * _BAND_HORIZONTAL_MARGIN_FRACTION)
    # MEME-PROD-2.1: the watermark-side right margin is widened (never the left) so wrapped lines
    # stay clear of the mark's own footprint in whichever corner it will occupy.
    right_margin = margin + (round(width * _WATERMARK_CLEARANCE_FRACTION) if reserve_watermark_clearance else 0)
    usable_width = width - margin - right_margin
    max_width = usable_width

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
        x = margin + (usable_width - line_width) // 2
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
        # MEME-PROD-2.1: same decision `meme_watermark.py::apply_nnj_watermark()` makes from the
        # same `copy.bottom_text` presence - watermark goes top-right when the bottom band is in
        # use, bottom-right otherwise - so the matching band reserves horizontal clearance for it.
        bottom_band_in_use = bool(copy.bottom_text)
        top_ratio, top_violations = _draw_band(
            image, draw, copy.top_text, band="top", reserve_watermark_clearance=bottom_band_in_use,
        )
        bottom_ratio, bottom_violations = _draw_band(
            image, draw, copy.bottom_text, band="bottom", reserve_watermark_clearance=not bottom_band_in_use,
        )

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
