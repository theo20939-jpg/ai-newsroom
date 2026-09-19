"""INSTAGRAM-VISUAL-SYSTEM-V1-1 section 11: CAROUSEL grammar. A carousel must tell a visual STORY,
not repeat "slide N: another empty title card" - so slide layout is chosen from the real
`CarouselSlide.role` (schemas/instagram_creative.py::InstagramCarouselSlideCreative.role, a
free-text field per spec - not every carousel uses every role) rather than being identical for
every slide:

  slide 0 (or role == "hook")        -> HOOK/HERO   - the strongest visual moment, full-bleed if a
                                                        hero image was supplied, oversized index-1
                                                        numeral watermark otherwise.
  role in {"cta", "takeaway"}        -> CLOSING      - a distinct closing treatment (a soft red
                                                        wash, not the hook's/detail's palette) -
                                                        conclusion/implication, optional CTA line.
  role == "data"                     -> FACT         - a callout treatment for a single striking
                                                        figure/fact, not the plain detail card.
  role == "comparison" (and the copy - contains a real " vs " split)
                                      -> COMPARISON   - a genuine two-panel split, only when the
                                                        slide's own copy supplies two real sides
                                                        (never fabricates a comparison structure the
                                                        content doesn't actually have).
  anything else (context/problem/
  explanation/unrecognised)          -> DETAIL        - the shared "explain/build" slide: numbered
                                                        eyebrow, human-readable role label, body
                                                        statement, corner-bracket instrument frame.

Every slide shares ONE design system (instagram_design_tokens, the same margin/mark/typography
roles as every other family) - only the per-slide composition varies, and only by what the slide
itself actually is (never uncontrolled randomness, section 17)."""
from __future__ import annotations

from PIL import Image, ImageDraw

from services import instagram_design_tokens as tok
from services.instagram_editorial_layouts import LayoutResult, TextRegionSpec
from services.instagram_image_handling import (
    apply_bottom_readability_gradient,
    apply_top_readability_gradient,
    build_dimmed_source_field,
    build_structured_fallback,
    draw_corner_brackets,
    fit_image_cover,
    mark_reserve_width,
    place_brand_mark,
)
from services.instagram_text_fit import box4, fit_text_block, measure_block_height
from services.instagram_visual_profiles import ProfileSpec, ig_font

SLIDE_LAYOUT_HOOK = "carousel_hook"
SLIDE_LAYOUT_CLOSING = "carousel_closing"
SLIDE_LAYOUT_FACT = "carousel_fact"
SLIDE_LAYOUT_COMPARISON = "carousel_comparison"
SLIDE_LAYOUT_DETAIL = "carousel_detail"
SLIDE_LAYOUT_CONTEXT = "carousel_context_split"
SLIDE_LAYOUT_PROBLEM = "carousel_problem_tension"
SLIDE_LAYOUT_EXPLANATION = "carousel_mechanism_flow"

_CLOSING_ROLES = {"cta", "takeaway"}

# Phase B.3 forensic fix: these three families previously had NO way to consume a real supplied
# image at all - `render_carousel_slide` unconditionally forced ANY non-HOOK/CONTEXT layout with a
# media_image through the generic `_slide_media_base` override, which REPLACES a family's own
# distinctive composition (VS badge, red closing wash, index echo) with the same full-bleed-photo-
# plus-headline card used everywhere - visually collapsing every non-hook/context slide into one
# repeated treatment. Excluding them here lets each keep its own foreground grammar while using a
# real dimmed/blurred crop of the same asset as its background instead of a synthetic pattern.
_OWN_TREATMENT_FAMILIES = {
    SLIDE_LAYOUT_HOOK, SLIDE_LAYOUT_CONTEXT, SLIDE_LAYOUT_COMPARISON, SLIDE_LAYOUT_CLOSING, SLIDE_LAYOUT_DETAIL,
}


def select_slide_layout(*, role: str, index: int, slide_copy: str) -> str:
    """Deterministic role-driven selection (section 17) - the same role always yields the same
    layout family; nothing here is randomized or index-jittered beyond the hook's own position."""
    r = role.strip().lower()
    if index == 0 or r == "hook":
        return SLIDE_LAYOUT_HOOK
    if r in _CLOSING_ROLES:
        return SLIDE_LAYOUT_CLOSING
    if r == "context":
        return SLIDE_LAYOUT_CONTEXT
    if r == "problem":
        return SLIDE_LAYOUT_PROBLEM
    if r == "explanation":
        return SLIDE_LAYOUT_EXPLANATION
    if r == "data":
        return SLIDE_LAYOUT_FACT
    if r == "comparison" and _split_vs(slide_copy) is not None:
        return SLIDE_LAYOUT_COMPARISON
    return SLIDE_LAYOUT_DETAIL


def _split_vs(text: str) -> tuple[str, str] | None:
    for sep in (" vs. ", " vs ", " VS ", " Vs "):
        if sep in text:
            left, right = text.split(sep, 1)
            if left.strip() and right.strip():
                return left.strip(), right.strip()
    return None


def _draw_progress(canvas: Image.Image, spec: ProfileSpec, *, index: int, total: int, dark_on_light: bool = False) -> None:
    """The small "02 / 06" progress readout every slide carries, top-left - a genuine narrative
    signal (this is slide 2 of 6 in a real sequence) instead of an unlabeled, interchangeable card."""
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    y = round(spec.height * spec.safe_top_frac) + margin
    size = round(spec.width * tok.TYPE_SLIDE_INDEX.size_frac)
    font = ig_font(size, tok.TYPE_SLIDE_INDEX.weight)
    text = f"{index + 1:02d} / {total:02d}"
    color = tok.INK if dark_on_light else tok.TYPE_SLIDE_INDEX.color
    draw.text((margin, y), text, font=font, fill=color)


def render_carousel_slide(
    *, spec: ProfileSpec, role: str, index: int, total: int, slide_copy: str, source_evidence: str | None,
    package_identity: str, hero_image: Image.Image | None = None, visual_direction: str | None = None,
    render_plan: dict | None = None, media_image: Image.Image | None = None,
    media_mode: str | None = None,
) -> LayoutResult:
    """Renders ONE carousel slide. `hero_image` is an optional renderer-time keyword (mirrors the
    Telegram `render_data_card(..., source_image_bytes=...)` precedent) - only the HOOK slide uses
    it (section 11's "slide 1 = the strongest visual moment"); other slides use this system's own
    typographic/graphic treatments since no per-slide image exists in the schema
    (InstagramCarouselSlideCreative.visual_direction is descriptive text, not a real asset)."""
    layout = select_slide_layout(role=role, index=index, slide_copy=slide_copy)
    identity = f"{package_identity}:{index}"
    selected_image = media_image if media_image is not None else hero_image
    if media_image is not None and (
        str(media_mode or "").upper() == "GENERATED"
        or layout not in _OWN_TREATMENT_FAMILIES
    ):
        result = _slide_media_base(
            spec=spec, slide_copy=slide_copy, index=index, total=total,
            package_identity=identity, media_image=media_image,
            generated=str(media_mode or "").upper() == "GENERATED",
        )
    elif layout == SLIDE_LAYOUT_HOOK:
        result = _slide_hook(spec=spec, slide_copy=slide_copy, index=index, total=total, package_identity=identity, hero_image=selected_image)
    elif layout == SLIDE_LAYOUT_CONTEXT:
        result = _slide_context(spec=spec, slide_copy=slide_copy, index=index, total=total, package_identity=identity, hero_image=selected_image)
    elif layout == SLIDE_LAYOUT_PROBLEM:
        result = _slide_problem(spec=spec, slide_copy=slide_copy, index=index, total=total, package_identity=identity)
    elif layout == SLIDE_LAYOUT_EXPLANATION:
        result = _slide_explanation(spec=spec, slide_copy=slide_copy, index=index, total=total, package_identity=identity, visual_direction=visual_direction)
    elif layout == SLIDE_LAYOUT_CLOSING:
        result = _slide_closing(spec=spec, slide_copy=slide_copy, index=index, total=total, package_identity=identity, media_image=selected_image)
    elif layout == SLIDE_LAYOUT_FACT:
        result = _slide_fact(spec=spec, slide_copy=slide_copy, index=index, total=total, package_identity=identity)
    elif layout == SLIDE_LAYOUT_COMPARISON:
        result = _slide_comparison(spec=spec, slide_copy=slide_copy, index=index, total=total, package_identity=identity, media_image=selected_image)
    else:
        result = _slide_detail(spec=spec, role=role, slide_copy=slide_copy, index=index, total=total, package_identity=identity, media_image=selected_image)
    result.notes.update(render_plan or {})
    result.notes.update({
        "rendered_copy": [slide_copy], "internal_labels_rendered": [],
        "visual_direction_consumed": bool(visual_direction),
        "media_mode_consumed": media_mode,
        "per_slide_media_consumed": media_image is not None,
    })
    return result


def _slide_media_base(
    *, spec: ProfileSpec, slide_copy: str, index: int, total: int,
    package_identity: str, media_image: Image.Image, generated: bool,
) -> LayoutResult:
    """Compose exact copy/brand over one explicitly assigned source or generated base asset."""
    fitted = fit_image_cover(media_image, width=spec.width, height=spec.height)
    canvas = fitted.image
    apply_bottom_readability_gradient(canvas, height_frac=0.66, max_alpha=235)
    apply_top_readability_gradient(canvas, height_frac=0.20, max_alpha=115)
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    content_w = spec.width - margin - max(margin, mark_reserve_width(spec, compact=True))
    _draw_progress(canvas, spec, index=index, total=total)
    headline_font, headline_lines, clipped = fit_text_block(
        draw, slide_copy,
        font_max=round(spec.width * tok.TYPE_HEADLINE_L.size_frac),
        font_min=round(spec.width * 0.046),
        max_width=content_w, max_lines=5, weight=tok.TYPE_HEADLINE_L.weight,
    )
    headline_h = measure_block_height(draw, headline_lines, headline_font)
    y: float = spec.height - round(spec.height * spec.safe_bottom_frac) - margin - headline_h
    regions: list[TextRegionSpec] = []
    for line_index, line in enumerate(headline_lines):
        bbox = draw.textbbox((margin, y), line, font=headline_font)
        draw.text((margin, y), line, font=headline_font, fill=tok.WHITE)
        regions.append(TextRegionSpec(
            kind="headline", box=box4(bbox),
            clipped=clipped and line_index == len(headline_lines) - 1,
        ))
        y += (bbox[3] - bbox[1]) + round(headline_font.size * 0.18)
    mark_count = place_brand_mark(canvas, spec, compact=True)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions,
        visible_brand_mark_count=mark_count,
        source_image_treatment="generated" if generated else fitted.treatment.value,
        layout_variant="carousel_generated_base" if generated else "carousel_source_base",
        text_clipped=clipped,
        notes={"source_coverage_fraction": 1.0, "generated_base_consumed": generated},
    )


def _slide_hook(*, spec: ProfileSpec, slide_copy: str, index: int, total: int, package_identity: str, hero_image: Image.Image | None) -> LayoutResult:
    if hero_image is not None:
        fitted = fit_image_cover(hero_image, width=spec.width, height=spec.height)
        canvas = fitted.image
        treatment = fitted.treatment.value
    else:
        canvas = build_structured_fallback(width=spec.width, height=spec.height, identity=package_identity, block_count=0)
        # an oversized "1" watermark - the hook's own visual anchor when no real hero image exists.
        big = round(spec.width * 0.75)
        font = ig_font(big, "black")
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ldraw = ImageDraw.Draw(layer, "RGBA")
        ldraw.text((round(spec.width * 0.12), round(spec.height * 0.32)), "1", font=font, fill=(*tok.RED, 40))
        canvas.alpha_composite(layer)
        draw_corner_brackets(canvas, spec, top=False)
        treatment = "none"

    apply_bottom_readability_gradient(canvas, height_frac=0.62, max_alpha=240)
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    content_w = spec.width - margin - max(margin, mark_reserve_width(spec, compact=True))
    _draw_progress(canvas, spec, index=index, total=total)

    headline_font, headline_lines, clipped = fit_text_block(
        draw, slide_copy, font_max=round(spec.width * tok.TYPE_HEADLINE_L.size_frac), font_min=round(spec.width * 0.05),
        max_width=content_w, max_lines=4, weight=tok.TYPE_HEADLINE_L.weight,
    )
    headline_h = measure_block_height(draw, headline_lines, headline_font)
    bottom_safe_px = round(spec.height * spec.safe_bottom_frac)
    y: float = spec.height - bottom_safe_px - margin - headline_h
    regions: list[TextRegionSpec] = []
    for i, line in enumerate(headline_lines):
        bbox = draw.textbbox((margin, y), line, font=headline_font)
        draw.text((margin, y), line, font=headline_font, fill=tok.WHITE)
        regions.append(TextRegionSpec(kind="headline", box=box4(bbox), clipped=clipped and i == len(headline_lines) - 1))
        y += (bbox[3] - bbox[1]) + round(headline_font.size * 0.18)

    mark_count = place_brand_mark(canvas, spec, compact=True)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment=treatment, layout_variant=SLIDE_LAYOUT_HOOK, text_clipped=clipped, notes=dict(source_coverage_fraction=1.0 if hero_image is not None else 0.0),
    )


def _draw_copy(
    canvas: Image.Image, spec: ProfileSpec, text: str, *, x: int, y: int, max_width: int,
    max_lines: int, max_size_frac: float, min_size_frac: float, color: tuple[int, int, int],
    weight: str = "semibold", kind: str = "body",
) -> tuple[list[TextRegionSpec], bool]:
    draw = ImageDraw.Draw(canvas, "RGBA")
    font, lines, clipped = fit_text_block(
        draw, text, font_max=round(spec.width * max_size_frac),
        font_min=round(spec.width * min_size_frac), max_width=max_width,
        max_lines=max_lines, weight=weight,
    )
    regions: list[TextRegionSpec] = []
    py: float = y
    for i, line in enumerate(lines):
        bbox = draw.textbbox((x, py), line, font=font)
        draw.text((x, py), line, font=font, fill=color)
        regions.append(TextRegionSpec(kind=kind, box=box4(bbox), clipped=clipped and i == len(lines) - 1))
        py += (bbox[3] - bbox[1]) + round(font.size * 0.22)
    return regions, clipped


def _slide_context(
    *, spec: ProfileSpec, slide_copy: str, index: int, total: int,
    package_identity: str, hero_image: Image.Image | None,
) -> LayoutResult:
    """A light editorial field with a secondary image strip, not another dark report card."""
    canvas = Image.new("RGBA", (spec.width, spec.height), (*tok.PAPER, 255))
    image_w = round(spec.width * 0.34)
    treatment = "none"
    if hero_image is not None:
        fitted = fit_image_cover(hero_image, width=image_w, height=spec.height, focus_y=0.42)
        canvas.paste(fitted.image, (0, 0))
        treatment = fitted.treatment.value
    else:
        draw = ImageDraw.Draw(canvas, "RGBA")
        draw.rectangle([0, 0, image_w, spec.height], fill=(*tok.INK_RAISED, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rectangle([image_w, 0, image_w + round(spec.width * 0.018), spec.height], fill=(*tok.RED, 255))
    _draw_progress(canvas, spec, index=index, total=total, dark_on_light=True)
    margin = round(spec.width * tok.MARGIN_FRAC)
    x = image_w + round(spec.width * 0.075)
    regions, clipped = _draw_copy(
        canvas, spec, slide_copy, x=x, y=round(spec.height * 0.29),
        max_width=spec.width - x - margin, max_lines=7, max_size_frac=0.052,
        min_size_frac=0.03, color=tok.INK, weight="semibold",
    )
    mark_count = place_brand_mark(canvas, spec, compact=True)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment=treatment, layout_variant=SLIDE_LAYOUT_CONTEXT,
        text_clipped=clipped, notes={"source_coverage_fraction": 0.34},
    )


def _slide_problem(
    *, spec: ProfileSpec, slide_copy: str, index: int, total: int, package_identity: str,
) -> LayoutResult:
    """A tension composition: offset copy, a broken axis, and one dominant punctuation mark."""
    canvas = Image.new("RGBA", (spec.width, spec.height), (*tok.INK, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    split_x = round(spec.width * 0.30)
    draw.rectangle([0, 0, split_x, spec.height], fill=(*tok.RED_DEEP, 255))
    draw.rectangle([split_x - 4, round(spec.height * 0.20), split_x + 4, round(spec.height * 0.72)], fill=(*tok.RED, 255))
    bang = ig_font(round(spec.width * 0.50), "black")
    draw.text((round(spec.width * 0.045), round(spec.height * 0.36)), "!", font=bang, fill=(*tok.RED, 255))
    _draw_progress(canvas, spec, index=index, total=total)
    x = split_x + round(spec.width * 0.07)
    regions, clipped = _draw_copy(
        canvas, spec, slide_copy, x=x, y=round(spec.height * 0.28),
        max_width=spec.width - x - round(spec.width * tok.MARGIN_FRAC),
        max_lines=7, max_size_frac=0.055, min_size_frac=0.03,
        color=tok.WHITE, weight="black",
    )
    mark_count = place_brand_mark(canvas, spec, compact=True)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment="none", layout_variant=SLIDE_LAYOUT_PROBLEM, text_clipped=clipped,
        notes={"visual_coverage_fraction": 0.86},
    )


def _flow_tokens(visual_direction: str | None) -> list[str]:
    text = str(visual_direction or "")
    if "«" in text and "»" in text:
        text = text.split("«", 1)[1].split("»", 1)[0]
    pieces = [piece.strip(" .,:;—-").upper() for piece in text.replace("->", "→").split("→")]
    pieces = [piece for piece in pieces if piece and len(piece) <= 22]
    return pieces[:3] if len(pieces) >= 2 else ["КОД", "API", "ОБНОВЛЕНИЯ"]


def _slide_explanation(
    *, spec: ProfileSpec, slide_copy: str, index: int, total: int,
    package_identity: str, visual_direction: str | None,
) -> LayoutResult:
    """A mechanism slide that turns the plan's arrow sequence into actual connected nodes."""
    canvas = Image.new("RGBA", (spec.width, spec.height), (*tok.PAPER, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    _draw_progress(canvas, spec, index=index, total=total, dark_on_light=True)
    margin = round(spec.width * tok.MARGIN_FRAC)
    tokens = _flow_tokens(visual_direction)
    node_y = round(spec.height * 0.24)
    gap = round(spec.width * 0.025)
    node_w = (spec.width - margin * 2 - gap * (len(tokens) - 1)) // len(tokens)
    node_h = round(spec.height * 0.13)
    node_font = ig_font(round(spec.width * 0.027), "semibold")
    for i, token in enumerate(tokens):
        x = margin + i * (node_w + gap)
        fill = tok.RED if i == len(tokens) - 1 else tok.INK
        draw.rounded_rectangle([x, node_y, x + node_w, node_y + node_h], radius=18, fill=(*fill, 255))
        shown = token[:18]
        bbox = draw.textbbox((0, 0), shown, font=node_font)
        draw.text((x + (node_w - (bbox[2] - bbox[0])) / 2, node_y + (node_h - (bbox[3] - bbox[1])) / 2 - bbox[1]), shown, font=node_font, fill=tok.WHITE)
        if i < len(tokens) - 1:
            x0 = x + node_w
            x1 = x0 + gap
            cy = node_y + node_h // 2
            draw.line([(x0 + 4, cy), (x1 - 4, cy)], fill=(*tok.RED, 255), width=5)
    regions, clipped = _draw_copy(
        canvas, spec, slide_copy, x=margin, y=round(spec.height * 0.51),
        max_width=spec.width - margin * 2, max_lines=6, max_size_frac=0.048,
        min_size_frac=0.029, color=tok.INK, weight="semibold",
    )
    mark_count = place_brand_mark(canvas, spec, compact=True)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment="none", layout_variant=SLIDE_LAYOUT_EXPLANATION,
        text_clipped=clipped, notes={"mechanism_tokens": tokens},
    )


def _slide_closing(
    *, spec: ProfileSpec, slide_copy: str, index: int, total: int, package_identity: str,
    media_image: Image.Image | None = None,
) -> LayoutResult:
    if media_image is not None:
        canvas, treatment = build_dimmed_source_field(media_image, width=spec.width, height=spec.height)
        source_treatment = treatment.value
    else:
        canvas = build_structured_fallback(width=spec.width, height=spec.height, identity=package_identity, block_count=0)
        source_treatment = "none"
    apply_top_readability_gradient(canvas, height_frac=0.5, max_alpha=150, tint=tok.RED_DEEP)
    draw_corner_brackets(canvas, spec, top=False)
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    content_w = spec.width - margin - max(margin, mark_reserve_width(spec, compact=True))
    _draw_progress(canvas, spec, index=index, total=total)
    regions: list[TextRegionSpec] = []

    rule_w = round(spec.width * tok.ACCENT_RULE_WIDTH_FRAC)
    top_y = round(spec.height * spec.safe_top_frac) + margin + round(spec.height * 0.05)
    draw.rectangle([margin, top_y, margin + rule_w, top_y + tok.ACCENT_RULE_THICKNESS_PX], fill=(*tok.RED, 255))

    body_font, body_lines, clipped = fit_text_block(
        draw, slide_copy, font_max=round(spec.width * tok.TYPE_HEADLINE_M.size_frac), font_min=round(spec.width * 0.04),
        max_width=content_w, max_lines=5, weight=tok.TYPE_HEADLINE_M.weight,
    )
    body_h = measure_block_height(draw, body_lines, body_font)
    top_safe_px = round(spec.height * spec.safe_top_frac) + margin
    bottom_safe_px = round(spec.height * spec.safe_bottom_frac) + margin
    y: float = top_safe_px + max(0, (spec.height - bottom_safe_px - top_safe_px - body_h) // 2)
    for i, line in enumerate(body_lines):
        bbox = draw.textbbox((margin, y), line, font=body_font)
        draw.text((margin, y), line, font=body_font, fill=tok.WHITE)
        regions.append(TextRegionSpec(kind="body", box=box4(bbox), clipped=clipped and i == len(body_lines) - 1))
        y += (bbox[3] - bbox[1]) + round(body_font.size * 0.2)

    mark_count = place_brand_mark(canvas, spec, compact=True)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment=source_treatment, layout_variant=SLIDE_LAYOUT_CLOSING, text_clipped=clipped,
    )


def _slide_fact(*, spec: ProfileSpec, slide_copy: str, index: int, total: int, package_identity: str) -> LayoutResult:
    canvas = build_structured_fallback(width=spec.width, height=spec.height, identity=package_identity, block_count=0)
    draw_corner_brackets(canvas, spec, top=False)
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    content_w = spec.width - margin - max(margin, mark_reserve_width(spec, compact=True))
    _draw_progress(canvas, spec, index=index, total=total)
    regions: list[TextRegionSpec] = []

    huge_size = round(spec.width * 0.42)
    hfont = ig_font(huge_size, "black")
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ldraw = ImageDraw.Draw(layer, "RGBA")
    ldraw.text((margin - round(spec.width * 0.02), round(spec.height * 0.10)), "#", font=hfont, fill=(*tok.RED, 42))
    canvas.alpha_composite(layer)

    body_font, body_lines, clipped = fit_text_block(
        draw, slide_copy, font_max=round(spec.width * tok.TYPE_QUOTE_BODY.size_frac), font_min=round(spec.width * 0.036),
        max_width=content_w, max_lines=6, weight=tok.TYPE_QUOTE_BODY.weight,
    )
    body_h = measure_block_height(draw, body_lines, body_font, line_gap_frac=0.26)
    top_safe_px = round(spec.height * spec.safe_top_frac) + margin
    bottom_safe_px = round(spec.height * spec.safe_bottom_frac) + margin
    y: float = top_safe_px + max(0, (spec.height - bottom_safe_px - top_safe_px - body_h) // 2)
    for i, line in enumerate(body_lines):
        bbox = draw.textbbox((margin, y), line, font=body_font)
        draw.text((margin, y), line, font=body_font, fill=tok.WHITE)
        regions.append(TextRegionSpec(kind="body", box=box4(bbox), clipped=clipped and i == len(body_lines) - 1))
        y += (bbox[3] - bbox[1]) + round(body_font.size * 0.26)

    mark_count = place_brand_mark(canvas, spec, compact=True)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment="none", layout_variant=SLIDE_LAYOUT_FACT, text_clipped=clipped,
    )


def _slide_comparison(
    *, spec: ProfileSpec, slide_copy: str, index: int, total: int, package_identity: str,
    media_image: Image.Image | None = None,
) -> LayoutResult:
    split = _split_vs(slide_copy)
    assert split is not None  # select_slide_layout only routes here when a real split exists
    left_text, right_text = split

    # The left panel is always covered by its own solid `INK_RAISED` rectangle below (unchanged),
    # so a real image only ever shows through as the RIGHT panel's texture - the existing "left
    # solid / right whatever's-behind-it" asymmetry was already the design; only the background
    # source changes here, none of the panel/VS-badge drawing logic below does.
    if media_image is not None:
        canvas, source_treatment_enum = build_dimmed_source_field(media_image, width=spec.width, height=spec.height)
        source_treatment = source_treatment_enum.value
    else:
        canvas = build_structured_fallback(width=spec.width, height=spec.height, identity=package_identity, block_count=0)
        source_treatment = "none"
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    _draw_progress(canvas, spec, index=index, total=total)

    mid_x = spec.width // 2
    panel_top = round(spec.height * (spec.safe_top_frac + 0.10))
    panel_bottom = spec.height - round(spec.height * spec.safe_bottom_frac) - margin
    # solid (not translucent) fills - a direct `ImageDraw` call on an existing RGBA canvas does not
    # blend against the canvas's own pixels (see instagram_image_handling.py::draw_with_alpha's own
    # docstring), so these are drawn at their true, honest full opacity rather than a alpha value
    # that would silently do nothing once flattened to JPEG.
    draw.rectangle([0, panel_top, mid_x, panel_bottom], fill=(*tok.INK_RAISED, 255))
    draw.line([(mid_x, panel_top), (mid_x, panel_bottom)], fill=(*tok.RED, 255), width=3)

    vs_size = round(spec.width * 0.05)
    vfont = ig_font(vs_size, "black")
    vbbox = draw.textbbox((0, 0), "VS", font=vfont)
    vw, vh = vbbox[2] - vbbox[0], vbbox[3] - vbbox[1]
    vy = (panel_top + panel_bottom) // 2 - vh
    draw.ellipse([mid_x - vh, vy - round(vh * 0.4), mid_x + vh, vy + vh + round(vh * 0.4)], fill=(*tok.INK, 255), outline=(*tok.RED, 255), width=2)
    draw.text((mid_x - vw / 2, vy - vbbox[1]), "VS", font=vfont, fill=tok.RED)

    col_w = mid_x - margin - round(spec.width * 0.04)
    regions: list[TextRegionSpec] = []

    def _panel(text: str, x0: int, align_color) -> None:
        pfont, plines, pclip = fit_text_block(
            draw, text, font_max=round(spec.width * tok.TYPE_HEADLINE_S.size_frac), font_min=round(spec.width * 0.03),
            max_width=col_w, max_lines=5, weight=tok.TYPE_HEADLINE_S.weight,
        )
        ph = measure_block_height(draw, plines, pfont)
        py: float = (panel_top + panel_bottom) // 2 - ph // 2
        for line in plines:
            bbox = draw.textbbox((x0, py), line, font=pfont)
            draw.text((x0, py), line, font=pfont, fill=align_color)
            regions.append(TextRegionSpec(kind="comparison_side", box=box4(bbox), clipped=pclip))
            py += (bbox[3] - bbox[1]) + round(pfont.size * 0.2)

    _panel(left_text, margin, tok.WHITE)
    _panel(right_text, mid_x + round(spec.width * 0.04), tok.WHITE)

    mark_count = place_brand_mark(canvas, spec, compact=True)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment=source_treatment, layout_variant=SLIDE_LAYOUT_COMPARISON, text_clipped=False,
    )


def _slide_detail(
    *, spec: ProfileSpec, role: str, slide_copy: str, index: int, total: int, package_identity: str,
    media_image: Image.Image | None = None,
) -> LayoutResult:
    if media_image is not None:
        canvas, _detail_treatment = build_dimmed_source_field(media_image, width=spec.width, height=spec.height)
        detail_source_treatment = _detail_treatment.value
    else:
        canvas = build_structured_fallback(width=spec.width, height=spec.height, identity=package_identity, block_count=0)
        detail_source_treatment = "none"
    draw_corner_brackets(canvas, spec, top=False)

    # a large, low-alpha echo of this slide's own index number - real content (this IS slide N),
    # not decoration - filling what would otherwise be the plainest, most text-only layout in the
    # deck with genuine visual weight instead of reading as an empty black card.
    big_size = round(spec.width * 0.62)
    big_font = ig_font(big_size, "black")
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ldraw = ImageDraw.Draw(layer, "RGBA")
    ldraw.text((round(spec.width * 0.42), round(spec.height * 0.58)), f"{index + 1:02d}", font=big_font, fill=(*tok.WHITE, 14))
    canvas.alpha_composite(layer)

    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    content_w = spec.width - margin - max(margin, mark_reserve_width(spec, compact=True))
    _draw_progress(canvas, spec, index=index, total=total)
    regions: list[TextRegionSpec] = []

    # Structural roles are internal metadata, never audience-facing copy.
    rule_y = round(spec.height * (spec.safe_top_frac + 0.20))
    draw.rectangle([margin, rule_y, margin + round(spec.width * 0.1), rule_y + 4], fill=(*tok.RED, 255))

    body_font, body_lines, clipped = fit_text_block(
        draw, slide_copy, font_max=round(spec.width * tok.TYPE_HEADLINE_S.size_frac), font_min=round(spec.width * 0.032),
        max_width=content_w, max_lines=6, weight=tok.TYPE_HEADLINE_S.weight,
    )
    body_h = measure_block_height(draw, body_lines, body_font)
    body_top = rule_y + round(spec.height * 0.05)
    bottom_safe_px = round(spec.height * spec.safe_bottom_frac) + margin
    y: float = body_top + max(0, (spec.height - bottom_safe_px - body_top - body_h) // 2)
    for i, line in enumerate(body_lines):
        bbox = draw.textbbox((margin, y), line, font=body_font)
        draw.text((margin, y), line, font=body_font, fill=tok.WHITE)
        regions.append(TextRegionSpec(kind="body", box=box4(bbox), clipped=clipped and i == len(body_lines) - 1))
        y += (bbox[3] - bbox[1]) + round(body_font.size * 0.2)

    mark_count = place_brand_mark(canvas, spec, compact=True)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment=detail_source_treatment, layout_variant=SLIDE_LAYOUT_DETAIL, text_clipped=clipped,
    )
