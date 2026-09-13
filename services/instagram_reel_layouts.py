"""INSTAGRAM-VISUAL-SYSTEM-V1-1 section 12: REEL COVER. Two deterministic variants (image / no
image, mirroring NEWS's own image-presence-driven selection). Both share the SAME critical
constraint this format alone has: a Reel cover is viewed in three very different crops -

  1. full portrait (9:16)   - the Reel viewer itself, phone-filling.
  2. the Reels tab grid     - Instagram crops a roughly CENTERED square/portrait thumbnail out of
                              the 9:16 cover; content pinned near the very top or very bottom is
                              cropped away in the grid.
  3. the profile grid       - the same center-crop behavior, slightly tighter.

So the hook text (and the mark) sit in a CENTER-SAFE band - not bottom-anchored like a feed post -
in addition to `ProfileSpec.safe_top_frac`/`safe_bottom_frac` (which only account for the Reels
player's own progress-bar/caption chrome, not grid cropping). No Telegram V8 import."""
from __future__ import annotations

from PIL import Image, ImageDraw

from services import instagram_design_tokens as tok
from services.instagram_editorial_layouts import LayoutResult, TextRegionSpec
from services.instagram_image_handling import (
    apply_bottom_readability_gradient,
    apply_top_readability_gradient,
    build_structured_fallback,
    draw_corner_brackets,
    draw_kicker_chip,
    fit_image_cover,
    mark_reserve_width,
    place_brand_mark,
)
from services.instagram_text_fit import box4, fit_text_block, measure_block_height
from services.instagram_visual_profiles import ProfileSpec

REEL_VARIANT_IMAGE = "reel_image"
REEL_VARIANT_GRAPHIC = "reel_graphic"

# The fraction of canvas height, measured from the top, where the grid/profile center-crop
# reliably keeps content - narrower than the full safe-zone-adjusted canvas. Anything drawn inside
# this band survives being viewed full-screen AND cropped to a grid thumbnail.
_GRID_SAFE_TOP_FRAC = 0.30
_GRID_SAFE_BOTTOM_FRAC = 0.62


def select_reel_variant(source_image: Image.Image | None) -> str:
    return REEL_VARIANT_IMAGE if source_image is not None else REEL_VARIANT_GRAPHIC


def render_reel_cover(
    *, spec: ProfileSpec, kicker: str, hook: str, source_image: Image.Image | None, package_identity: str,
) -> LayoutResult:
    if source_image is not None:
        return _reel_image(spec=spec, kicker=kicker, hook=hook, source_image=source_image, package_identity=package_identity)
    return _reel_graphic(spec=spec, kicker=kicker, hook=hook, package_identity=package_identity)


def _grid_safe_band(spec: ProfileSpec) -> tuple[int, int]:
    top = max(round(spec.height * spec.safe_top_frac), round(spec.height * _GRID_SAFE_TOP_FRAC))
    bottom = min(spec.height - round(spec.height * spec.safe_bottom_frac), round(spec.height * _GRID_SAFE_BOTTOM_FRAC))
    return top, bottom


def _reel_image(*, spec: ProfileSpec, kicker: str, hook: str, source_image: Image.Image, package_identity: str) -> LayoutResult:
    fitted = fit_image_cover(source_image, width=spec.width, height=spec.height, focus_y=0.32)
    canvas = fitted.image
    apply_top_readability_gradient(canvas, height_frac=0.5, max_alpha=150)
    apply_bottom_readability_gradient(canvas, height_frac=0.55, max_alpha=235)
    draw = ImageDraw.Draw(canvas, "RGBA")

    margin = round(spec.width * tok.MARGIN_FRAC)
    content_w = spec.width - margin - max(margin, mark_reserve_width(spec, compact=True))
    grid_top, grid_bottom = _grid_safe_band(spec)
    regions: list[TextRegionSpec] = []

    cw, ch = draw_kicker_chip(canvas, x=margin, y=grid_top, text=kicker, accent=True)
    hook_font, hook_lines, clipped = fit_text_block(
        draw, hook, font_max=round(spec.width * tok.TYPE_HEADLINE_M.size_frac), font_min=round(spec.width * 0.045),
        max_width=content_w, max_lines=4, weight=tok.TYPE_HEADLINE_M.weight,
    )
    hook_h = measure_block_height(draw, hook_lines, hook_font)
    y: float = grid_top + ch + round(spec.height * 0.025)
    if y + hook_h > grid_bottom:
        y = max(grid_top + ch + round(spec.height * 0.015), grid_bottom - hook_h)

    for i, line in enumerate(hook_lines):
        bbox = draw.textbbox((margin, y), line, font=hook_font)
        draw.text((margin, y), line, font=hook_font, fill=tok.WHITE)
        regions.append(TextRegionSpec(kind="hook", box=box4(bbox), clipped=clipped and i == len(hook_lines) - 1))
        y += (bbox[3] - bbox[1]) + round(hook_font.size * 0.18)

    # the mark sits just below the grid-safe band's own lower edge, near (not at) the true bottom -
    # still inside ProfileSpec's own Reels-chrome safe zone, but positioned so it is not the very
    # first thing cropped away by the grid thumbnail either.
    mark_count = place_brand_mark(canvas, spec, compact=True)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment=fitted.treatment.value, layout_variant=REEL_VARIANT_IMAGE, text_clipped=clipped,
        notes={"grid_safe_band": [grid_top, grid_bottom]},
    )


def _reel_graphic(*, spec: ProfileSpec, kicker: str, hook: str, package_identity: str) -> LayoutResult:
    canvas = build_structured_fallback(width=spec.width, height=spec.height, identity=package_identity, block_count=0)
    draw_corner_brackets(canvas, spec, top=False)
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    content_w = spec.width - margin - max(margin, mark_reserve_width(spec, compact=True))
    grid_top, grid_bottom = _grid_safe_band(spec)
    regions: list[TextRegionSpec] = []

    # a large, low-alpha play-button glyph (a filled triangle in a ring) - a genuine "this is video
    # content" visual cue instead of a static text card indistinguishable from a feed post.
    ring_r = round(spec.width * 0.30)
    cx, cy = spec.width // 2, (grid_top + grid_bottom) // 2 - round(spec.height * 0.05)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ldraw = ImageDraw.Draw(layer, "RGBA")
    ldraw.ellipse([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r], outline=(*tok.RED, 40), width=6)
    tri = round(ring_r * 0.6)
    ldraw.polygon(
        [(cx - tri * 0.5, cy - tri * 0.75), (cx - tri * 0.5, cy + tri * 0.75), (cx + tri * 0.75, cy)],
        fill=(*tok.RED, 34),
    )
    canvas.alpha_composite(layer)

    cw, ch = draw_kicker_chip(canvas, x=margin, y=grid_top, text=kicker, accent=True)
    hook_font, hook_lines, clipped = fit_text_block(
        draw, hook, font_max=round(spec.width * tok.TYPE_HEADLINE_M.size_frac), font_min=round(spec.width * 0.045),
        max_width=content_w, max_lines=4, weight=tok.TYPE_HEADLINE_M.weight,
    )
    hook_h = measure_block_height(draw, hook_lines, hook_font)
    y: float = grid_top + ch + round(spec.height * 0.03)
    if y + hook_h > grid_bottom:
        y = max(grid_top + ch + round(spec.height * 0.015), grid_bottom - hook_h)
    for i, line in enumerate(hook_lines):
        bbox = draw.textbbox((margin, y), line, font=hook_font)
        draw.text((margin, y), line, font=hook_font, fill=tok.WHITE)
        regions.append(TextRegionSpec(kind="hook", box=box4(bbox), clipped=clipped and i == len(hook_lines) - 1))
        y += (bbox[3] - bbox[1]) + round(hook_font.size * 0.18)

    mark_count = place_brand_mark(canvas, spec, compact=True)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment="none", layout_variant=REEL_VARIANT_GRAPHIC, text_clipped=clipped,
        notes={"grid_safe_band": [grid_top, grid_bottom]},
    )
