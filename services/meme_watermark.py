"""MEME PRODUCTION PIPELINE (overnight phase): mandatory, deterministic NNJ watermark compositor
for every successfully generated meme image.

Reuses `services/brand_renderer.py::load_brand_mark()` verbatim - the exact same official,
already-shipped `assets/brand/nnj_logo.png` raster asset every NEWS/BREAKING/QUOTE/RECAP render
already uses AS-IS (that module's own docstring: "Official assets only... no drawn/generated/
reconstructed 'N' mark anywhere"). No new asset, no redrawn/approximated logo, no SVG rasterizer
dependency (unlike `services/nnj_master_news_mark.py`, used only where an independently-
recolorable mark is needed - a meme watermark is always the single official red/white PNG badge,
exactly like every other `_paste_logo()` call site already established).

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

from PIL import Image, UnidentifiedImageError

from schemas.meme_copy import MemeCopy
from services.brand_renderer import load_brand_mark

logger = logging.getLogger(__name__)

# Proportional to the shorter image side, mirroring brand_renderer.render_news_hero()'s own
# "MINIMAL"/"EDITORIAL" sizing convention (a meme watermark is closer in spirit to the
# conservative MINIMAL treatment - present, legible, never dominant over the joke).
_WATERMARK_WIDTH_FRACTION = 0.16
_MARGIN_FRACTION = 0.035
_MIN_WATERMARK_WIDTH_PX = 32
_MIN_MARGIN_PX = 10


class MemeWatermarkError(Exception):
    """Raised on any failure to apply the mandatory NNJ watermark - decode failure, missing brand
    asset, or an unexpected compositing error. Never caught and silently ignored by this module
    itself; the caller must treat this as a hard failure of the whole generation attempt, never a
    "ship without watermark" fallback (module docstring's own non-negotiable requirement)."""


def apply_nnj_watermark(image_bytes: bytes, *, copy: MemeCopy | None = None) -> bytes:
    """Composites the official NNJ mark onto `image_bytes` and returns new PNG bytes. Raises
    `MemeWatermarkError` (never returns unwatermarked bytes, never returns `None`) on any decode,
    asset-loading, or compositing failure - deliberately fail-CLOSED here (the opposite of
    `brand_renderer.render_branded_media()`'s own fail-OPEN-to-unbranded-media convention, which
    is correct for optional NEWS branding but wrong for a MANDATORY watermark)."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            canvas = source.convert("RGBA").copy()
    except (UnidentifiedImageError, OSError) as exc:
        raise MemeWatermarkError(f"could not decode meme image for watermarking: {exc!r}") from exc

    try:
        logo = load_brand_mark()
    except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
        raise MemeWatermarkError(f"could not load canonical NNJ brand asset: {exc!r}") from exc

    try:
        short_side = min(canvas.width, canvas.height)
        target_width = max(_MIN_WATERMARK_WIDTH_PX, round(short_side * _WATERMARK_WIDTH_FRACTION))
        margin = max(_MIN_MARGIN_PX, round(short_side * _MARGIN_FRACTION))
        scale = target_width / logo.width
        target_height = max(1, round(logo.height * scale))
        resized_logo = logo.resize((target_width, target_height), Image.Resampling.LANCZOS)

        bottom_band_in_use = copy is not None and bool(copy.bottom_text)
        x = canvas.width - target_width - margin
        y = margin if bottom_band_in_use else canvas.height - target_height - margin

        canvas.alpha_composite(resized_logo, (x, y))

        buffer = io.BytesIO()
        canvas.convert("RGB").save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception as exc:  # noqa: BLE001 - fail-closed boundary, never silently unwatermarked
        raise MemeWatermarkError(f"watermark compositing failed: {exc!r}") from exc
