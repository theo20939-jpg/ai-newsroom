"""INSTAGRAM-VISUAL-SYSTEM-V1-1 section 10: QUOTE family. Two deterministic variants:

  QUOTE_VARIANT_PORTRAIT  - a real portrait/person image was supplied -> full-bleed portrait,
                             darkened for readability, large quotation composited directly over it -
                             a genuine editorial portrait treatment, not a text card with a photo
                             stapled on.
  QUOTE_VARIANT_GRAPHIC   - no portrait available -> an intentional, designed graphic composition
                             (oversized quotation-mark glyph as the visual anchor, technical grid,
                             corner geometry) - explicitly NOT "plain text on black" (section 10's
                             own instruction).

Variant choice is driven purely by whether a real portrait image was supplied (section 17). No
import of Telegram V8 modules."""
from __future__ import annotations

from PIL import Image, ImageDraw

from services import instagram_design_tokens as tok
from services.instagram_editorial_layouts import LayoutResult, TextRegionSpec
from services.instagram_image_handling import (
    SourceImageTreatment,
    apply_bottom_readability_gradient,
    build_structured_fallback,
    draw_corner_brackets,
    fit_image_cover,
    mark_reserve_width,
    place_brand_mark,
)
from services.instagram_text_fit import box4, fit_text_block, measure_block_height
from services.instagram_visual_profiles import ProfileSpec, ig_font

QUOTE_VARIANT_PORTRAIT = "quote_portrait"
QUOTE_VARIANT_GRAPHIC = "quote_graphic"


def select_quote_variant(source_image: Image.Image | None) -> str:
    """Deterministic: a real portrait earns the portrait treatment; no image falls back to the
    designed graphic variant - never a random choice, and never a plain text-on-black default."""
    return QUOTE_VARIANT_PORTRAIT if source_image is not None else QUOTE_VARIANT_GRAPHIC


def render_quote_layout(
    *, spec: ProfileSpec, quote: str, speaker: str, role: str | None, source_image: Image.Image | None,
    package_identity: str,
) -> LayoutResult:
    if source_image is not None:
        return _quote_portrait(spec=spec, quote=quote, speaker=speaker, role=role, source_image=source_image, package_identity=package_identity)
    return _quote_graphic(spec=spec, quote=quote, speaker=speaker, role=role, package_identity=package_identity)


def _quote_portrait(*, spec: ProfileSpec, quote: str, speaker: str, role: str | None, source_image: Image.Image, package_identity: str) -> LayoutResult:
    fitted = fit_image_cover(source_image, width=spec.width, height=spec.height, focus_y=0.30)
    canvas = fitted.image
    # a stronger, fuller darkening than the NEWS readability gradient - the whole lower two-thirds
    # need to hold a large quotation legibly over a real photographed face.
    apply_bottom_readability_gradient(canvas, height_frac=0.85, max_alpha=245)
    draw = ImageDraw.Draw(canvas, "RGBA")

    margin = round(spec.width * tok.MARGIN_FRAC)
    content_w = spec.width - margin - max(margin, mark_reserve_width(spec))
    regions: list[TextRegionSpec] = []

    mark_size = round(spec.width * tok.TYPE_QUOTE_MARK.size_frac)
    mfont = ig_font(mark_size, tok.TYPE_QUOTE_MARK.weight)

    quote_font, quote_lines, quote_clipped = fit_text_block(
        draw, quote, font_max=round(spec.width * tok.TYPE_QUOTE_BODY.size_frac), font_min=round(spec.width * 0.034),
        max_width=content_w, max_lines=tok.TYPE_QUOTE_BODY.max_lines, weight=tok.TYPE_QUOTE_BODY.weight,
    )
    quote_h = measure_block_height(draw, quote_lines, quote_font, line_gap_frac=0.28)

    name_size = round(spec.width * tok.TYPE_QUOTE_NAME.size_frac)
    nfont = ig_font(name_size, tok.TYPE_QUOTE_NAME.weight)
    name_h = draw.textbbox((0, 0), speaker, font=nfont)[3]

    role_h = 0
    role_font = role_lines = None
    if role:
        role_font, role_lines, _ = fit_text_block(
            draw, role, font_max=round(spec.width * tok.TYPE_QUOTE_ROLE.size_frac), font_min=round(spec.width * 0.02),
            max_width=content_w, max_lines=tok.TYPE_QUOTE_ROLE.max_lines, weight=tok.TYPE_QUOTE_ROLE.weight,
        )
        role_h = measure_block_height(draw, role_lines, role_font)

    stack_h = mark_size + round(spec.height * 0.015) + quote_h + round(spec.height * 0.03) + name_h + (round(spec.height * 0.008) + role_h if role else 0)
    bottom_safe_px = round(spec.height * spec.safe_bottom_frac)
    y: float = spec.height - bottom_safe_px - margin - stack_h

    draw.text((margin, y), "“", font=mfont, fill=(*tok.RED, 255))
    y += mark_size + round(spec.height * 0.015)

    for i, line in enumerate(quote_lines):
        bbox = draw.textbbox((margin, y), line, font=quote_font)
        draw.text((margin, y), line, font=quote_font, fill=tok.TYPE_QUOTE_BODY.color)
        regions.append(TextRegionSpec(kind="quote", box=box4(bbox), clipped=quote_clipped and i == len(quote_lines) - 1))
        y += (bbox[3] - bbox[1]) + round(quote_font.size * 0.28)

    y += round(spec.height * 0.02)
    bbox = draw.textbbox((margin, y), speaker, font=nfont)
    draw.text((margin, y), speaker, font=nfont, fill=tok.TYPE_QUOTE_NAME.color)
    regions.append(TextRegionSpec(kind="speaker", box=box4(bbox), clipped=False))
    y = bbox[3] + round(spec.height * 0.008)

    if role_font is not None and role_lines:
        for line in role_lines:
            bbox = draw.textbbox((margin, y), line, font=role_font)
            draw.text((margin, y), line, font=role_font, fill=tok.TYPE_QUOTE_ROLE.color)
            regions.append(TextRegionSpec(kind="role", box=box4(bbox), clipped=False))
            y += (bbox[3] - bbox[1]) + round(role_font.size * 0.25)

    mark_count = place_brand_mark(canvas, spec)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment=fitted.treatment.value, layout_variant=QUOTE_VARIANT_PORTRAIT,
        text_clipped=quote_clipped,
    )


def _quote_graphic(*, spec: ProfileSpec, quote: str, speaker: str, role: str | None, package_identity: str) -> LayoutResult:
    canvas = build_structured_fallback(width=spec.width, height=spec.height, identity=package_identity, block_count=0)
    draw_corner_brackets(canvas, spec, top=False)
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    content_w = spec.width - margin - max(margin, mark_reserve_width(spec))
    regions: list[TextRegionSpec] = []

    quote_font, quote_lines, quote_clipped = fit_text_block(
        draw, quote, font_max=round(spec.width * tok.TYPE_QUOTE_BODY.size_frac), font_min=round(spec.width * 0.034),
        max_width=content_w, max_lines=tok.TYPE_QUOTE_BODY.max_lines, weight=tok.TYPE_QUOTE_BODY.weight,
    )
    quote_h = measure_block_height(draw, quote_lines, quote_font, line_gap_frac=0.28)

    name_size = round(spec.width * tok.TYPE_QUOTE_NAME.size_frac)
    nfont = ig_font(name_size, tok.TYPE_QUOTE_NAME.weight)
    name_h = draw.textbbox((0, 0), speaker, font=nfont)[3]

    role_h = 0
    role_font = role_lines = None
    if role:
        role_font, role_lines, _ = fit_text_block(
            draw, role, font_max=round(spec.width * tok.TYPE_QUOTE_ROLE.size_frac), font_min=round(spec.width * 0.02),
            max_width=content_w, max_lines=tok.TYPE_QUOTE_ROLE.max_lines, weight=tok.TYPE_QUOTE_ROLE.weight,
        )
        role_h = measure_block_height(draw, role_lines, role_font)

    rule_h = round(spec.height * 0.006)
    stack_h = quote_h + round(spec.height * 0.035) + rule_h + round(spec.height * 0.025) + name_h + (round(spec.height * 0.008) + role_h if role else 0)
    top_safe_px = round(spec.height * spec.safe_top_frac) + margin
    bottom_safe_px = round(spec.height * spec.safe_bottom_frac) + margin
    available_h = spec.height - bottom_safe_px - top_safe_px
    y: float = top_safe_px + max(0, (available_h - stack_h) // 2)

    # the visual anchor for a no-portrait quote: one oversized, low-alpha quotation glyph, anchored
    # to sit directly ABOVE the actual quote block (not floating disconnected near the top of an
    # otherwise-empty canvas) - the designed graphic identity section 10 requires instead of plain
    # text on black.
    huge_size = round(spec.width * 0.5)
    hfont = ig_font(huge_size, tok.TYPE_QUOTE_MARK.weight)
    glyph_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glyph_layer, "RGBA")
    gdraw.text((margin - round(spec.width * 0.03), y - round(huge_size * 0.72)), "“", font=hfont, fill=(*tok.RED, 50))
    canvas.alpha_composite(glyph_layer)

    for i, line in enumerate(quote_lines):
        bbox = draw.textbbox((margin, y), line, font=quote_font)
        draw.text((margin, y), line, font=quote_font, fill=tok.TYPE_QUOTE_BODY.color)
        regions.append(TextRegionSpec(kind="quote", box=box4(bbox), clipped=quote_clipped and i == len(quote_lines) - 1))
        y += (bbox[3] - bbox[1]) + round(quote_font.size * 0.28)

    y += round(spec.height * 0.02)
    rule_w = round(spec.width * tok.ACCENT_RULE_WIDTH_FRAC)
    draw.rectangle([margin, y, margin + rule_w, y + tok.ACCENT_RULE_THICKNESS_PX], fill=(*tok.RED, 255))
    y += tok.ACCENT_RULE_THICKNESS_PX + round(spec.height * 0.025)

    bbox = draw.textbbox((margin, y), speaker, font=nfont)
    draw.text((margin, y), speaker, font=nfont, fill=tok.TYPE_QUOTE_NAME.color)
    regions.append(TextRegionSpec(kind="speaker", box=box4(bbox), clipped=False))
    y = bbox[3] + round(spec.height * 0.008)

    if role_font is not None and role_lines:
        for line in role_lines:
            bbox = draw.textbbox((margin, y), line, font=role_font)
            draw.text((margin, y), line, font=role_font, fill=tok.TYPE_QUOTE_ROLE.color)
            regions.append(TextRegionSpec(kind="role", box=box4(bbox), clipped=False))
            y += (bbox[3] - bbox[1]) + round(role_font.size * 0.25)

    mark_count = place_brand_mark(canvas, spec)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment=SourceImageTreatment.NONE.value, layout_variant=QUOTE_VARIANT_GRAPHIC,
        text_clipped=quote_clipped,
    )
