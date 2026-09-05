"""MEME PRODUCTION PIPELINE (overnight phase; MEME-PROD-2.1 brand-source fix): mandatory,
deterministic NNJ watermark compositor for every successfully generated meme image.

MEME-PROD-2.1: reuses `services/nnj_master_news_mark.py::rasterize_nnj_mark()` - the SAME
official-SVG rasterizer `services/brand_renderer.py`'s own DATA-card bottom signature and MASTER
NEWS lower mark already use in production - rather than the flat `assets/brand/nnj_logo.png`
raster this module previously loaded via `load_brand_mark()`. Real production evidence showed the
PNG-sourced watermark reading as "the wrong logo variant" - the canonical brand source of truth is
the SVG (`assets/brand/nnj_logo.svg`/`nnj_logo_red.svg`), never the PNG, for any NEW call site;
`rasterize_nnj_mark()` parses the SVG's own exact straight-line path geometry (no curve
approximation, no hand-tracing, no new asset) and rasterizes it at the requested width, preserving
transparency (a fully transparent canvas, only the wordmark polygon fill is opaque - never a
background rectangle). Adaptive red/white variant selection (mirrors `brand_renderer.py`'s own
`_pick_adaptive_data_color()` luminance threshold exactly, duplicated locally per this codebase's
own established per-module-private-helper convention) keeps the mark visible against the AI-
generated meme image's own unpredictable background brightness - a single fixed color, unlike the
old self-contained PNG badge, can otherwise vanish against a matching background.

The image model is never trusted to draw the logo (module's own hard requirement) - this function
runs strictly AFTER image generation and AFTER `services/meme_render.py::render_meme()`'s own
text-overlay compositing, on the final pixel-complete image, so the watermark can never be
obscured by a later rendering step, and a failure here can never silently ship an unwatermarked
meme (the caller, `services/meme_generation_orchestrator.py`, treats a raised
`MemeWatermarkError` as a hard generation failure - never a "deliver anyway" fallback).

Placement mirrors `brand_renderer._paste_logo()`'s own simple, already-tested, safe-corner
approach exactly (bottom-right, proportional size, fixed margin) - deliberately NOT a new
content-aware safe-zone scorer (`nnj_master_news_overlay.py`'s own edge-density heuristic exists
for photographic NEWS hero images with an unpredictable subject; a meme's own text overlay already
occupies known, fixed top/bottom bands per `meme_render.py`'s own `_BAND_HEIGHT_FRACTION`, so a
much smaller "which side has current text" check is sufficient here). One adaptive decision: if
the meme's `MemeCopy.bottom_text` is present (the bottom band is in use), the watermark is placed
in the TOP-right corner instead of bottom-right, so it never sits inside/against the bottom
caption band; otherwise (or if `copy` is not supplied) it defaults to bottom-right, matching every
other brand-mark placement in this codebase.
"""
from __future__ import annotations

import io
import logging

from PIL import Image, ImageStat, UnidentifiedImageError

from schemas.meme_copy import MemeCopy
from services.nnj_master_news_mark import rasterize_nnj_mark

logger = logging.getLogger(__name__)

# Proportional to the shorter image side, mirroring brand_renderer.render_news_hero()'s own
# "MINIMAL"/"EDITORIAL" sizing convention (a meme watermark is closer in spirit to the
# conservative MINIMAL treatment - present, legible, never dominant over the joke).
# MEME-PROD-3.1: was 0.16/0.035 - production canary confirmed SVG source, adaptive color, and
# placement were all already correct; only the visual size was too large. Halved the width
# fraction and tightened the margin accordingly - no other sizing/placement math touched.
_WATERMARK_WIDTH_FRACTION = 0.08
_MARGIN_FRACTION = 0.025
_MIN_WATERMARK_WIDTH_PX = 32
_MIN_MARGIN_PX = 10
# Same threshold/formula as brand_renderer.py::_pick_adaptive_data_color() - a light background
# (>=128) gets the red mark, a dark one gets the white mark, for the same contrast reason.
_LUMINANCE_RED_THRESHOLD = 128


class MemeWatermarkError(Exception):
    """Raised on any failure to apply the mandatory NNJ watermark - decode failure, missing brand
    asset, or an unexpected compositing error. Never caught and silently ignored by this module
    itself; the caller must treat this as a hard failure of the whole generation attempt, never a
    "ship without watermark" fallback (module docstring's own non-negotiable requirement)."""


def _region_luminance(canvas: Image.Image, box: tuple[int, int, int, int]) -> float | None:
    """Mean luminance of `canvas` cropped to `box` (left, upper, right, lower) - same formula as
    `brand_renderer.py::_pick_adaptive_data_color()` (`0.299*R + 0.587*G + 0.114*B`), duplicated
    locally per this codebase's own established per-module-private-helper convention. Returns
    `None` for a degenerate (zero-area) box - only reachable on a canvas smaller than the
    watermark's own minimum footprint (`_MIN_WATERMARK_WIDTH_PX`/`_MIN_MARGIN_PX`), where there is
    no real corner region to sample; the caller then falls back to the red variant, matching this
    module's own pre-MEME-PROD-2.1 single-color default."""
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    r, g, b = ImageStat.Stat(canvas.convert("RGB").crop(box)).mean
    return 0.299 * r + 0.587 * g + 0.114 * b


def apply_nnj_watermark(image_bytes: bytes, *, copy: MemeCopy | None = None) -> bytes:
    """Composites the official NNJ mark onto `image_bytes` and returns new PNG bytes. Raises
    `MemeWatermarkError` (never returns unwatermarked bytes, never returns `None`) on any decode,
    rasterization, or compositing failure - deliberately fail-CLOSED here (the opposite of
    `brand_renderer.render_branded_media()`'s own fail-OPEN-to-unbranded-media convention, which
    is correct for optional NEWS branding but wrong for a MANDATORY watermark)."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            canvas = source.convert("RGBA").copy()
    except (UnidentifiedImageError, OSError) as exc:
        raise MemeWatermarkError(f"could not decode meme image for watermarking: {exc!r}") from exc

    try:
        short_side = min(canvas.width, canvas.height)
        target_width = max(_MIN_WATERMARK_WIDTH_PX, round(short_side * _WATERMARK_WIDTH_FRACTION))
        margin = max(_MIN_MARGIN_PX, round(short_side * _MARGIN_FRACTION))

        # Both variants share identical geometry (only the fill color differs), so a single
        # rasterization is enough to determine placement before deciding red vs. white.
        red_mark = rasterize_nnj_mark(target_width=target_width, red=True)
        target_height = red_mark.height

        bottom_band_in_use = copy is not None and bool(copy.bottom_text)
        x = canvas.width - target_width - margin
        y = margin if bottom_band_in_use else canvas.height - target_height - margin

        box = (
            max(0, x), max(0, y),
            min(canvas.width, x + target_width), min(canvas.height, y + target_height),
        )
        luminance = _region_luminance(canvas, box)
        use_red = luminance is None or luminance >= _LUMINANCE_RED_THRESHOLD
        mark = red_mark if use_red else rasterize_nnj_mark(target_width=target_width, red=False)

        canvas.alpha_composite(mark, (x, y))

        buffer = io.BytesIO()
        canvas.convert("RGB").save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception as exc:  # noqa: BLE001 - fail-closed boundary, never silently unwatermarked
        raise MemeWatermarkError(f"watermark compositing failed: {exc!r}") from exc
