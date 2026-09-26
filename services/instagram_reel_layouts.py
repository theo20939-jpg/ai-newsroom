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

from PIL import Image, ImageDraw, ImageFilter

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
    *, spec: ProfileSpec, kicker: str | None, hook: str, source_image: Image.Image | None,
    package_identity: str, render_plan: dict | None = None,
) -> LayoutResult:
    if source_image is not None:
        result = _reel_image(spec=spec, kicker=kicker, hook=hook, source_image=source_image, package_identity=package_identity)
    else:
        result = _reel_graphic(spec=spec, kicker=kicker, hook=hook, package_identity=package_identity)
    result.notes.update(render_plan or {})
    result.notes.update({"rendered_copy": [hook], "internal_labels_rendered": []})
    return result


def _grid_safe_band(spec: ProfileSpec) -> tuple[int, int]:
    top = max(round(spec.height * spec.safe_top_frac), round(spec.height * _GRID_SAFE_TOP_FRAC))
    bottom = min(spec.height - round(spec.height * spec.safe_bottom_frac), round(spec.height * _GRID_SAFE_BOTTOM_FRAC))
    return top, bottom


def _reel_image(*, spec: ProfileSpec, kicker: str | None, hook: str, source_image: Image.Image, package_identity: str) -> LayoutResult:
    """Recompose a screenshot as material: blurred field + top-cropped masked detail + copy panel."""
    background = fit_image_cover(source_image, width=spec.width, height=spec.height, focus_y=0.62)
    canvas = background.image.filter(ImageFilter.GaussianBlur(radius=24))
    canvas = Image.alpha_composite(canvas, Image.new("RGBA", canvas.size, (*tok.INK, 178)))
    draw = ImageDraw.Draw(canvas, "RGBA")

    sw, sh = source_image.size
    clean_region = source_image.crop((0, round(sh * 0.22), sw, sh))
    panel_w = round(spec.width * 0.86)
    panel_h = round(spec.height * 0.29)
    detail = fit_image_cover(clean_region, width=panel_w, height=panel_h, focus_y=0.38)
    panel_x = (spec.width - panel_w) // 2
    panel_y = round(spec.height * 0.54)
    radius = round(spec.width * 0.025)
    mask = Image.new("L", (panel_w, panel_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, panel_w, panel_h], radius=radius, fill=255)
    canvas.paste(detail.image, (panel_x, panel_y), mask)
    draw.rounded_rectangle(
        [panel_x, panel_y, panel_x + panel_w, panel_y + panel_h],
        radius=radius, outline=(*tok.WHITE, 155), width=3,
    )
    draw.rectangle(
        [panel_x, panel_y - 8, panel_x + round(panel_w * 0.34), panel_y],
        fill=(*tok.RED, 255),
    )

    margin = round(spec.width * tok.MARGIN_FRAC)
    content_w = spec.width - margin * 2
    grid_top, grid_bottom = _grid_safe_band(spec)
    regions: list[TextRegionSpec] = []
    y: float = grid_top
    if kicker:
        _, ch = draw_kicker_chip(canvas, x=margin, y=y, text=kicker, accent=True)
        y += ch + round(spec.height * 0.018)
    hook_font, hook_lines, clipped = fit_text_block(
        draw, hook, font_max=round(spec.width * 0.076), font_min=round(spec.width * 0.044),
        max_width=content_w, max_lines=4, weight="black",
    )
    hook_h = measure_block_height(draw, hook_lines, hook_font)
    y = min(y, max(grid_top, panel_y - hook_h - round(spec.height * 0.04)))
    for i, line in enumerate(hook_lines):
        bbox = draw.textbbox((margin, y), line, font=hook_font)
        draw.text((margin, y), line, font=hook_font, fill=tok.WHITE)
        regions.append(TextRegionSpec(kind="hook", box=box4(bbox), clipped=clipped and i == len(hook_lines) - 1))
        y += (bbox[3] - bbox[1]) + round(hook_font.size * 0.16)

    mark_count = place_brand_mark(canvas, spec, compact=True)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment=detail.treatment.value, layout_variant="reel_recomposed_source",
        text_clipped=clipped,
        notes={
            "grid_safe_band": [grid_top, grid_bottom],
            "embedded_text_conflict_risk": True,
            "embedded_text_strategy": "crop_top_22pct_blur_background_masked_detail",
            "source_coverage_fraction": 0.72,
            "sharp_source_panel": [panel_x, panel_y, panel_x + panel_w, panel_y + panel_h],
        },
    )

def _reel_graphic(*, spec: ProfileSpec, kicker: str | None, hook: str, package_identity: str) -> LayoutResult:
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

    ch = 0
    if kicker:
        _, ch = draw_kicker_chip(canvas, x=margin, y=grid_top, text=kicker, accent=True)
    # a long hook takes more lines at display size (the grid-safe band holds six) instead of shrinking to caption size in four
    hook_font, hook_lines, clipped = fit_text_block(
        draw, hook, font_max=round(spec.width * tok.TYPE_HEADLINE_M.size_frac), font_min=round(spec.width * 0.06),
        max_width=content_w, max_lines=6, weight=tok.TYPE_HEADLINE_M.weight,
    )
    if clipped:  # longer still: the previous fit (smaller type, four lines) - the art gate then reports it as not designed
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
        y += round(hook_font.size * 1.1)  # one constant line advance: a line without ascenders no longer pulls the next one up

    mark_count = place_brand_mark(canvas, spec, compact=True)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment="none", layout_variant=REEL_VARIANT_GRAPHIC, text_clipped=clipped,
        notes={"grid_safe_band": [grid_top, grid_bottom],
               # a designed no-photo cover: the hook set at display size, whole (the art gate's typographic_render_not_designed)
               "designed_typographic": hook_font.size >= round(spec.width * 0.06) and not clipped},
    )
