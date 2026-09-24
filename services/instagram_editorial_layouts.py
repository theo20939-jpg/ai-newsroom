"""INSTAGRAM-VISUAL-SYSTEM-V1-1 sections 7/8: NEWS/EDITORIAL (3 composition variants) and BREAKING
(its own, non-Telegram treatment). Image-forward by construction (section 5) - every layout here
requires a real source image or the structured fallback (section 14), never a blank card.

Variant selection is driven by the SOURCE IMAGE'S OWN aspect ratio (section 17's own "based on
content/media properties, not uncontrolled randomness" instruction) - a portrait photo suits a
full-bleed treatment, a landscape photo suits a top-image/bottom-panel split, and the framed
variant is offered as the deliberate third look for square-ish sources so a feed of NEWS posts is
not visually monotonous."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageDraw

from services import instagram_design_tokens as tok
from services.instagram_image_handling import (
    ImageOrientation,
    SourceImageTreatment,
    apply_bottom_readability_gradient,
    apply_top_readability_gradient,
    build_structured_fallback,
    classify_orientation,
    draw_kicker_chip,
    fit_image_cover,
    mark_reserve_width,
    place_brand_mark,
)
from services.instagram_text_fit import box4, fit_text_block, measure_block_height
from services.instagram_visual_profiles import ProfileSpec, ig_font


@dataclass(frozen=True)
class TextRegionSpec:
    kind: str
    box: tuple[int, int, int, int]
    clipped: bool


@dataclass(frozen=True)
class LayoutResult:
    image: Image.Image  # RGB, final
    text_regions: list[TextRegionSpec]
    visible_brand_mark_count: int
    source_image_treatment: str
    layout_variant: str
    text_clipped: bool
    notes: dict[str, Any] = field(default_factory=dict)


# The renderer's own CLOSED vocabulary for `LayoutResult.source_image_treatment` (Phase B.7). `services/instagram_declarative_layout.py`
# derives its `media_treatment` labels from CROP_MODE_TREATMENTS below - it never hand-types a second copy of these strings.
# `services/instagram_art_validator.py` imports SOURCE_IMAGE_TREATMENTS as its ONLY source of truth for "is this a real treatment the
# renderer can legitimately produce" - it must never hand-maintain an independent whitelist that can silently drift from this one
# (a real bug: `object_contain`/`cutout` crop modes were added to the renderer without ever being added to the validator's own copy).
CROP_MODE_TREATMENTS: dict[str, str] = {
    "object_contain": "object_contained", "object_cover": "object_cover_cropped",
    "cutout_contain": "cutout_contained", "cutout": "cutout_cover", "contain": "contain_preserved",
}
SOURCE_IMAGE_TREATMENTS = frozenset({"none", "cover_cropped", *CROP_MODE_TREATMENTS.values()})


NEWS_VARIANT_FULL_BLEED = "news_full_bleed"
NEWS_VARIANT_SPLIT_PANEL = "news_split_panel"
NEWS_VARIANT_FRAMED = "news_framed"


def select_news_variant(orientation: ImageOrientation | None) -> str:
    """Deterministic, content-driven (section 17): the source image's own orientation decides the
    composition family - never a random/uncontrolled choice, and never the same layout for every
    post regardless of what was actually supplied."""
    if orientation is ImageOrientation.LANDSCAPE:
        return NEWS_VARIANT_SPLIT_PANEL
    if orientation is ImageOrientation.SQUARE:
        return NEWS_VARIANT_FRAMED
    return NEWS_VARIANT_FULL_BLEED  # PORTRAIT or no image at all (fallback still reads as full-bleed)


def render_news_layout(
    *, spec: ProfileSpec, source_image: Image.Image | None, kicker: str | None, headline: str,
    dek: str | None, package_identity: str, render_plan: dict[str, Any] | None = None,
) -> LayoutResult:
    plan = render_plan or {}
    family = str(plan.get("render_interpretation") or "")
    orientation = classify_orientation(*source_image.size) if source_image is not None else None
    if family == "typographic_focal":
        result = _news_typographic(spec=spec, headline=headline, package_identity=package_identity)
    else:
        variant = NEWS_VARIANT_FULL_BLEED if family == "editorial_hero" else select_news_variant(orientation)
        if variant == NEWS_VARIANT_SPLIT_PANEL:
            result = _news_split_panel(spec=spec, source_image=source_image, kicker=kicker, headline=headline, dek=dek, package_identity=package_identity)
        elif variant == NEWS_VARIANT_FRAMED:
            result = _news_framed(spec=spec, source_image=source_image, kicker=kicker, headline=headline, dek=dek, package_identity=package_identity)
        else:
            result = _news_full_bleed(spec=spec, source_image=source_image, kicker=kicker, headline=headline, dek=dek, package_identity=package_identity)
    result.notes.update(plan)
    result.notes.update({
        "rendered_copy": [headline] + ([dek] if dek else []),
        "internal_labels_rendered": [],
        "source_coverage_fraction": 1.0 if result.layout_variant == NEWS_VARIANT_FULL_BLEED and source_image is not None else result.notes.get("source_coverage_fraction", 0.0),
    })
    return result


def _news_full_bleed(*, spec: ProfileSpec, source_image, kicker, headline, dek, package_identity) -> LayoutResult:
    if source_image is not None:
        fitted = fit_image_cover(source_image, width=spec.width, height=spec.height)
        canvas = fitted.image
        treatment = fitted.treatment.value
    else:
        canvas = build_structured_fallback(width=spec.width, height=spec.height, identity=package_identity)
        treatment = SourceImageTreatment.NONE.value

    apply_bottom_readability_gradient(canvas)
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    side_safe = margin
    content_w = spec.width - side_safe - max(side_safe, mark_reserve_width(spec))

    # kicker sits ABOVE the headline, anchored from the bottom safe zone upward - compute headline
    # height first so the whole text stack is bottom-anchored consistently.
    headline_font, headline_lines, headline_clipped = fit_text_block(
        draw, headline, font_max=round(spec.width * tok.TYPE_HEADLINE_L.size_frac),
        font_min=round(spec.width * 0.045), max_width=content_w, max_lines=tok.TYPE_HEADLINE_L.max_lines, weight=tok.TYPE_HEADLINE_L.weight,
    )
    headline_h = measure_block_height(draw, headline_lines, headline_font)

    dek_font = dek_lines = None
    dek_h = 0
    dek_clipped = False
    if dek:
        dek_font, dek_lines, dek_clipped = fit_text_block(
            draw, dek, font_max=round(spec.width * tok.TYPE_DEK.size_frac), font_min=round(spec.width * 0.024),
            max_width=content_w, max_lines=tok.TYPE_DEK.max_lines, weight=tok.TYPE_DEK.weight,
        )
        dek_h = measure_block_height(draw, dek_lines, dek_font) + round(spec.height * 0.015)

    kicker_h = round(spec.width * tok.TYPE_KICKER.size_frac * 2.1) if kicker else 0
    bottom_safe_px = round(spec.height * spec.safe_bottom_frac)
    stack_h = kicker_h + round(spec.height * 0.02) + headline_h + dek_h
    y: float = spec.height - bottom_safe_px - margin - stack_h

    regions: list[TextRegionSpec] = []
    if kicker:
        draw_kicker_chip(canvas, x=side_safe, y=y, text=kicker)
        y += kicker_h + round(spec.height * 0.02)

    for i, line in enumerate(headline_lines):
        draw.text((side_safe, y), line, font=headline_font, fill=tok.TYPE_HEADLINE_L.color)
        bbox = draw.textbbox((side_safe, y), line, font=headline_font)
        regions.append(TextRegionSpec(kind="headline", box=box4(bbox), clipped=headline_clipped and i == len(headline_lines) - 1))
        bh = bbox[3] - bbox[1]
        y += bh + round(headline_font.size * 0.18)

    if dek_font is not None and dek_lines:
        y += round(spec.height * 0.005)
        for i, line in enumerate(dek_lines):
            draw.text((side_safe, y), line, font=dek_font, fill=tok.TYPE_DEK.color)
            bbox = draw.textbbox((side_safe, y), line, font=dek_font)
            regions.append(TextRegionSpec(kind="dek", box=box4(bbox), clipped=dek_clipped and i == len(dek_lines) - 1))
            y += (bbox[3] - bbox[1]) + round(dek_font.size * 0.25)

    mark_count = place_brand_mark(canvas, spec)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment=treatment, layout_variant=NEWS_VARIANT_FULL_BLEED,
        text_clipped=headline_clipped or dek_clipped,
    )


def _news_split_panel(*, spec: ProfileSpec, source_image, kicker, headline, dek, package_identity) -> LayoutResult:
    image_band_h = round(spec.height * 0.60)
    canvas = Image.new("RGBA", (spec.width, spec.height), (*tok.INK, 255))

    if source_image is not None:
        fitted = fit_image_cover(source_image, width=spec.width, height=image_band_h, focus_y=0.38)
        canvas.paste(fitted.image, (0, 0))
        treatment = fitted.treatment.value
    else:
        fb = build_structured_fallback(width=spec.width, height=image_band_h, identity=package_identity)
        canvas.paste(fb, (0, 0))
        treatment = SourceImageTreatment.NONE.value

    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    content_w = spec.width - margin - max(margin, mark_reserve_width(spec))
    panel_top = image_band_h

    regions: list[TextRegionSpec] = []
    y: float = panel_top + round(spec.height * tok.PANEL_PADDING_FRAC)
    if kicker:
        _, ch = draw_kicker_chip(canvas, x=margin, y=y, text=kicker)
        y += ch + round(spec.height * 0.025)

    headline_font, headline_lines, headline_clipped = fit_text_block(
        draw, headline, font_max=round(spec.width * tok.TYPE_HEADLINE_M.size_frac), font_min=round(spec.width * 0.04),
        max_width=content_w, max_lines=3, weight=tok.TYPE_HEADLINE_M.weight,
    )
    for i, line in enumerate(headline_lines):
        draw.text((margin, y), line, font=headline_font, fill=tok.TYPE_HEADLINE_M.color)
        bbox = draw.textbbox((margin, y), line, font=headline_font)
        regions.append(TextRegionSpec(kind="headline", box=box4(bbox), clipped=headline_clipped and i == len(headline_lines) - 1))
        y += (bbox[3] - bbox[1]) + round(headline_font.size * 0.16)

    dek_clipped = False
    if dek:
        remaining_h = spec.height - round(spec.height * spec.safe_bottom_frac) - margin - y
        if remaining_h > round(spec.width * tok.TYPE_DEK.size_frac):
            dek_font, dek_lines, dek_clipped = fit_text_block(
                draw, dek, font_max=round(spec.width * tok.TYPE_DEK.size_frac), font_min=round(spec.width * 0.022),
                max_width=content_w, max_lines=2, weight=tok.TYPE_DEK.weight,
            )
            y += round(spec.height * 0.012)
            for i, line in enumerate(dek_lines):
                draw.text((margin, y), line, font=dek_font, fill=tok.TYPE_DEK.color)
                bbox = draw.textbbox((margin, y), line, font=dek_font)
                regions.append(TextRegionSpec(kind="dek", box=box4(bbox), clipped=dek_clipped and i == len(dek_lines) - 1))
                y += (bbox[3] - bbox[1]) + round(dek_font.size * 0.25)

    mark_count = place_brand_mark(canvas, spec)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment=treatment, layout_variant=NEWS_VARIANT_SPLIT_PANEL,
        text_clipped=headline_clipped or dek_clipped,
    )


def _news_framed(*, spec: ProfileSpec, source_image, kicker, headline, dek, package_identity) -> LayoutResult:
    canvas = Image.new("RGBA", (spec.width, spec.height), (*tok.INK, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    content_w = spec.width - margin - max(margin, mark_reserve_width(spec))

    y: float = round(spec.height * spec.safe_top_frac) + margin
    if kicker:
        _, ch = draw_kicker_chip(canvas, x=margin, y=y, text=kicker)
        y += ch + round(spec.height * 0.03)

    frame_w = content_w
    frame_h = round(spec.height * 0.42)
    if source_image is not None:
        fitted = fit_image_cover(source_image, width=frame_w, height=frame_h)
        canvas.paste(fitted.image, (margin, round(y)))
        treatment = fitted.treatment.value
    else:
        fb = build_structured_fallback(width=frame_w, height=frame_h, identity=package_identity)
        canvas.paste(fb, (margin, round(y)))
        treatment = SourceImageTreatment.NONE.value
    draw.rounded_rectangle([margin, y, margin + frame_w, y + frame_h], radius=round(spec.width * tok.CORNER_RADIUS_FRAC), outline=(*tok.INK_RAISED, 255), width=3)
    y += frame_h + round(spec.height * 0.04)

    regions: list[TextRegionSpec] = []
    headline_font, headline_lines, headline_clipped = fit_text_block(
        draw, headline, font_max=round(spec.width * tok.TYPE_HEADLINE_S.size_frac), font_min=round(spec.width * 0.04),
        max_width=content_w, max_lines=4, weight=tok.TYPE_HEADLINE_S.weight,
    )
    for i, line in enumerate(headline_lines):
        draw.text((margin, y), line, font=headline_font, fill=tok.TYPE_HEADLINE_S.color)
        bbox = draw.textbbox((margin, y), line, font=headline_font)
        regions.append(TextRegionSpec(kind="headline", box=box4(bbox), clipped=headline_clipped and i == len(headline_lines) - 1))
        y += (bbox[3] - bbox[1]) + round(headline_font.size * 0.18)

    dek_clipped = False
    if dek:
        dek_font, dek_lines, dek_clipped = fit_text_block(
            draw, dek, font_max=round(spec.width * tok.TYPE_DEK.size_frac), font_min=round(spec.width * 0.022),
            max_width=content_w, max_lines=2, weight=tok.TYPE_DEK.weight,
        )
        y += round(spec.height * 0.01)
        for i, line in enumerate(dek_lines):
            draw.text((margin, y), line, font=dek_font, fill=tok.TYPE_DEK.color)
            bbox = draw.textbbox((margin, y), line, font=dek_font)
            regions.append(TextRegionSpec(kind="dek", box=box4(bbox), clipped=dek_clipped and i == len(dek_lines) - 1))
            y += (bbox[3] - bbox[1]) + round(dek_font.size * 0.25)

    mark_count = place_brand_mark(canvas, spec)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment=treatment, layout_variant=NEWS_VARIANT_FRAMED,
        text_clipped=headline_clipped or dek_clipped,
    )


def _news_typographic(
    *, spec: ProfileSpec, headline: str, package_identity: str,
) -> LayoutResult:
    """A source-free editorial composition whose focal symbol and copy occupy the canvas."""
    canvas = Image.new("RGBA", (spec.width, spec.height), (*tok.PAPER, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    symbol = "≠" if "≠" in headline or "не равно" in headline.lower() else "•"
    symbol_font = ig_font(round(spec.width * 0.72), "black")
    symbol_box = draw.textbbox((0, 0), symbol, font=symbol_font)
    draw.text(
        (spec.width - (symbol_box[2] - symbol_box[0]) - margin, round(spec.height * 0.04)),
        symbol, font=symbol_font, fill=(*tok.RED, 255),
    )
    draw.rectangle(
        [margin, round(spec.height * 0.18), margin + round(spec.width * 0.045), round(spec.height * 0.64)],
        fill=(*tok.INK, 255),
    )
    content_x = margin + round(spec.width * 0.085)
    content_w = spec.width - content_x - margin
    font, lines, clipped = fit_text_block(
        draw, headline, font_max=round(spec.width * 0.082), font_min=round(spec.width * 0.042),
        max_width=content_w, max_lines=6, weight="black",
    )
    text_h = measure_block_height(draw, lines, font)
    y: float = max(round(spec.height * 0.31), (spec.height - text_h) // 2)
    regions: list[TextRegionSpec] = []
    for i, line in enumerate(lines):
        bbox = draw.textbbox((content_x, y), line, font=font)
        draw.text((content_x, y), line, font=font, fill=tok.INK)
        regions.append(TextRegionSpec(kind="headline", box=box4(bbox), clipped=clipped and i == len(lines) - 1))
        y += (bbox[3] - bbox[1]) + round(font.size * 0.18)
    mark_count = place_brand_mark(canvas, spec)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment="none", layout_variant="news_typographic_focal",
        text_clipped=clipped, notes={"visual_coverage_fraction": 0.82},
    )


def render_breaking_layout(
    *, spec: ProfileSpec, source_image: Image.Image | None, headline: str, dek: str | None, package_identity: str,
) -> LayoutResult:
    """Section 8: stronger urgency than NEWS, NINJA red as an ACCENT (a filled "BREAKING" chip + a
    small red indicator dot), never a full red overlay. Its OWN treatment - does not reuse the
    Telegram BREAKING pulse/watermark in any way (no import of nnj_board_metrics.py /
    brand_renderer.py)."""
    if source_image is not None:
        fitted = fit_image_cover(source_image, width=spec.width, height=spec.height)
        canvas = fitted.image
        treatment = fitted.treatment.value
    else:
        canvas = build_structured_fallback(width=spec.width, height=spec.height, identity=package_identity)
        treatment = SourceImageTreatment.NONE.value

    apply_top_readability_gradient(canvas, height_frac=tok.BREAKING_ACCENT_GRADIENT_HEIGHT_FRAC, max_alpha=tok.BREAKING_ACCENT_GRADIENT_MAX_ALPHA, tint=tok.RED_DEEP)
    apply_bottom_readability_gradient(canvas)
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    content_w = spec.width - margin - max(margin, mark_reserve_width(spec))

    top_y = round(spec.height * spec.safe_top_frac) + margin
    dot_r = round(spec.width * 0.012)
    draw.ellipse([margin, top_y + dot_r // 2, margin + dot_r * 2, top_y + dot_r // 2 + dot_r * 2], fill=(*tok.RED, 255))
    draw_kicker_chip(canvas, x=margin + dot_r * 2 + round(spec.width * 0.02), y=top_y, text="breaking", accent=True)

    headline_font, headline_lines, headline_clipped = fit_text_block(
        draw, headline, font_max=round(spec.width * tok.TYPE_HEADLINE_L.size_frac), font_min=round(spec.width * 0.05),
        max_width=content_w, max_lines=4, weight=tok.TYPE_HEADLINE_L.weight,
    )
    headline_h = measure_block_height(draw, headline_lines, headline_font)
    dek_h = 0
    if dek:
        dek_font_probe, dek_lines_probe, _ = fit_text_block(
            draw, dek, font_max=round(spec.width * tok.TYPE_DEK.size_frac), font_min=round(spec.width * 0.024),
            max_width=content_w, max_lines=2, weight=tok.TYPE_DEK.weight,
        )
        dek_h = measure_block_height(draw, dek_lines_probe, dek_font_probe) + round(spec.height * 0.015)

    bottom_safe_px = round(spec.height * spec.safe_bottom_frac)
    y: float = spec.height - bottom_safe_px - margin - headline_h - dek_h
    regions: list[TextRegionSpec] = []
    for i, line in enumerate(headline_lines):
        draw.text((margin, y), line, font=headline_font, fill=tok.WHITE)
        bbox = draw.textbbox((margin, y), line, font=headline_font)
        regions.append(TextRegionSpec(kind="headline", box=box4(bbox), clipped=headline_clipped and i == len(headline_lines) - 1))
        y += (bbox[3] - bbox[1]) + round(headline_font.size * 0.18)

    dek_clipped = False
    if dek:
        y += round(spec.height * 0.005)
        dek_font, dek_lines, dek_clipped = fit_text_block(
            draw, dek, font_max=round(spec.width * tok.TYPE_DEK.size_frac), font_min=round(spec.width * 0.024),
            max_width=content_w, max_lines=2, weight=tok.TYPE_DEK.weight,
        )
        for i, line in enumerate(dek_lines):
            draw.text((margin, y), line, font=dek_font, fill=tok.GREY_STRONG)
            bbox = draw.textbbox((margin, y), line, font=dek_font)
            regions.append(TextRegionSpec(kind="dek", box=box4(bbox), clipped=dek_clipped and i == len(dek_lines) - 1))
            y += (bbox[3] - bbox[1]) + round(dek_font.size * 0.25)

    mark_count = place_brand_mark(canvas, spec)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment=treatment, layout_variant="breaking",
        text_clipped=headline_clipped or dek_clipped,
    )
