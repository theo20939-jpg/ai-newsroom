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

import enum

from PIL import Image, ImageDraw

from services import instagram_design_tokens as tok
from services.instagram_editorial_layouts import LayoutResult, TextRegionSpec
from services.instagram_image_handling import (
    apply_bottom_readability_gradient,
    apply_top_readability_gradient,
    build_detail_crop_field,
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


class SourceMediaPrimitive(str, enum.Enum):
    """Phase B.3.1: the small, CLOSED, actually-implemented vocabulary of real pixel treatments a
    slide's media can receive. Deliberately does not include a primitive this module cannot really
    execute (e.g. a true alpha-mask silhouette cutout) - `select_media_primitive` never returns a
    value `_resolve_slide_background` cannot draw."""

    NONE = "none"                        # no source image consumed - pure typography/graphic slide
    FULL_BLEED = "source_full_bleed"     # cover-fit across the whole canvas (the hook's own look)
    STRIP = "source_strip"               # confined to a partial-width panel (context's own look)
    DETAIL_CROP = "source_detail_crop"   # a zoomed sub-region of the source, not the wide framing
    DIMMED_FIELD = "source_dimmed_field"  # full-bleed, blurred + heavily dimmed background texture


# Each family's own established visual identity supplies a DEFAULT only - real signal in a
# slide's own `media_need` text always overrides this (see `select_media_primitive`). This is the
# "role may still provide structure, but role alone must not decide" contract: a default bias, not
# a hard rule. EXPLANATION is deliberately absent (mapped to NONE via .get()'s fallback): its own
# foreground assumes a LIGHT paper canvas (dark node boxes + dark body copy) - `build_dimmed_
# source_field`'s dark scrim would make that body copy illegible. A light-variant field is real
# future work, not something to fake here. COMPARISON and CLOSING default to NONE per the explicit
# design principle that a comparison/takeaway may be "primarily typographic... or no source image
# at all" - not every family should show a photo just because one exists.
_DEFAULT_MEDIA_PRIMITIVE_BY_LAYOUT: dict[str, "SourceMediaPrimitive"] = {
    SLIDE_LAYOUT_HOOK: SourceMediaPrimitive.FULL_BLEED,
    SLIDE_LAYOUT_CONTEXT: SourceMediaPrimitive.STRIP,
    SLIDE_LAYOUT_FACT: SourceMediaPrimitive.DIMMED_FIELD,
    SLIDE_LAYOUT_DETAIL: SourceMediaPrimitive.DETAIL_CROP,
    SLIDE_LAYOUT_PROBLEM: SourceMediaPrimitive.NONE,
}


def select_media_primitive(*, layout: str, media_need: str | None, has_media: bool) -> "SourceMediaPrimitive":
    """THE real per-slide media decision. Previously nothing occupied this role at all - a slide's
    image, if any, was chosen by `render_carousel_slide`'s own blunt "layout in {HOOK,CONTEXT}"
    check, never by what the creative plan actually asked for. `media_need` (InstagramCarousel
    SlideCreative's own existing field, already carried into `media_plan['slides']` by
    `instagram_content_package.py::_carousel_media_plan`) is real per-slide creative-plan text -
    an explicit signal in it always wins over the family's own default bias."""
    if not has_media:
        return SourceMediaPrimitive.NONE
    signal = str(media_need or "").lower()
    if any(t in signal for t in (
        "без фото", "без изображен", "чист", "типограф", "no image", "text only", "минимал", "график",
    )):
        return SourceMediaPrimitive.NONE
    if any(t in signal for t in ("деталь", "крупный план", "zoom", "close-up", "detail crop", "фрагмент")):
        return SourceMediaPrimitive.DETAIL_CROP
    if any(t in signal for t in ("полос", "strip", "врез", "inset", "боков")):
        return SourceMediaPrimitive.STRIP
    if any(t in signal for t in ("фон", "приглуш", "затемн", "dim", "background field", "текстур")):
        return SourceMediaPrimitive.DIMMED_FIELD
    if any(t in signal for t in ("полный кадр", "full bleed", "hero", "герой")):
        return SourceMediaPrimitive.FULL_BLEED
    return _DEFAULT_MEDIA_PRIMITIVE_BY_LAYOUT.get(layout, SourceMediaPrimitive.NONE)


def _focus_y_from_focal_point(focal_point: str | None) -> float:
    """The carousel-wide `InstagramCreativeExecutionPlan.focal_point` text biasing WHERE a crop is
    centered - a real, if modest, causal link from the shared creative plan to actual crop
    geometry, not just evidence metadata."""
    text = str(focal_point or "").lower()
    if any(t in text for t in ("низ", "bottom", "внизу")):
        return 0.65
    if any(t in text for t in ("верх", "top", "сверху")):
        return 0.25
    return 0.42  # this system's own existing default bias (fit_image_cover's own default)


def _focus_x_from_focal_point(focal_point: str | None) -> float:
    """Horizontal counterpart to `_focus_y_from_focal_point` - without it, a zoomed DETAIL_CROP
    stays horizontally centered on the SOURCE image regardless of where the described subject
    actually sits, which lands on empty background just as often as on the subject once the
    target aspect is narrow (a strip)."""
    text = str(focal_point or "").lower()
    if any(t in text for t in ("справа", "right", "правой")):
        return 0.65
    if any(t in text for t in ("слева", "left", "левой")):
        return 0.35
    return 0.5


def _resolve_slide_background(
    primitive: "SourceMediaPrimitive", media_image: Image.Image | None, *,
    width: int, height: int, focus_y: float, focus_x: float = 0.5, identity: str, block_count: int = 0,
) -> tuple[Image.Image, str]:
    """The ONE place a slide's base canvas is chosen from from the REAL decided primitive. Every
    `_slide_*` function below calls this once instead of unconditionally hardcoding
    `build_structured_fallback()` regardless of what the creative plan asked for - the fix for
    "fields exist in metadata but never reach pixels". Returns the ACTUAL treatment that occurred,
    for the caller to record as truthful evidence (never the plan's prediction)."""
    if media_image is None or primitive is SourceMediaPrimitive.NONE:
        canvas = build_structured_fallback(width=width, height=height, identity=identity, block_count=block_count)
        return canvas, SourceMediaPrimitive.NONE.value
    if primitive is SourceMediaPrimitive.FULL_BLEED:
        fitted = fit_image_cover(media_image, width=width, height=height, focus_y=focus_y, focus_x=focus_x)
        return fitted.image, fitted.treatment.value
    if primitive is SourceMediaPrimitive.DETAIL_CROP:
        return build_detail_crop_field(media_image, width=width, height=height, focus_y=focus_y, focus_x=focus_x)
    # DIMMED_FIELD, and STRIP requested on a family with no sub-rectangle of its own (only CONTEXT
    # has one, and it never calls this helper for its strip - see `_slide_context`) - both use the
    # same real dimmed/blurred treatment.
    canvas, treatment_enum = build_dimmed_source_field(media_image, width=width, height=height, focus_y=focus_y, focus_x=focus_x)
    return canvas, treatment_enum.value


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
    media_mode: str | None = None, media_need: str | None = None, focal_point: str | None = None,
) -> LayoutResult:
    """Renders ONE carousel slide. `role` (via `select_slide_layout`) decides the FOREGROUND
    typographic/graphic grammar - which is a legitimate, disclosed default bias, not the bug. The
    bug this function fixes (Phase B.3.1) was that role ALSO silently decided whether/how a real
    image appeared, via a blunt override that replaced a family's whole composition. Media
    treatment is now `select_media_primitive`'s own decision, driven by this slide's real
    `media_need` (InstagramCarouselSlideCreative's own existing field) - role only supplies that
    function's fallback default when the plan gives no explicit signal."""
    layout = select_slide_layout(role=role, index=index, slide_copy=slide_copy)
    identity = f"{package_identity}:{index}"
    selected_image = media_image if media_image is not None else hero_image
    primitive = select_media_primitive(layout=layout, media_need=media_need, has_media=selected_image is not None)
    focus_y = _focus_y_from_focal_point(focal_point)
    focus_x = _focus_x_from_focal_point(focal_point)

    if layout == SLIDE_LAYOUT_HOOK:
        result = _slide_hook(spec=spec, slide_copy=slide_copy, index=index, total=total, package_identity=identity, media_image=selected_image, media_primitive=primitive, focus_y=focus_y, focus_x=focus_x)
    elif layout == SLIDE_LAYOUT_CONTEXT:
        result = _slide_context(spec=spec, slide_copy=slide_copy, index=index, total=total, package_identity=identity, media_image=selected_image, media_primitive=primitive, focus_y=focus_y, focus_x=focus_x)
    elif layout == SLIDE_LAYOUT_PROBLEM:
        result = _slide_problem(spec=spec, slide_copy=slide_copy, index=index, total=total, package_identity=identity, media_image=selected_image, media_primitive=primitive, focus_y=focus_y, focus_x=focus_x)
    elif layout == SLIDE_LAYOUT_EXPLANATION:
        # Deliberately NOT wired to a real image (see _DEFAULT_MEDIA_PRIMITIVE_BY_LAYOUT's own
        # comment): its foreground assumes a LIGHT paper canvas, incompatible with the dark
        # dimmed-field treatment without a light-variant field this pass does not build.
        result = _slide_explanation(spec=spec, slide_copy=slide_copy, index=index, total=total, package_identity=identity, visual_direction=visual_direction)
    elif layout == SLIDE_LAYOUT_CLOSING:
        result = _slide_closing(spec=spec, slide_copy=slide_copy, index=index, total=total, package_identity=identity, media_image=selected_image, media_primitive=primitive, focus_y=focus_y, focus_x=focus_x)
    elif layout == SLIDE_LAYOUT_FACT:
        result = _slide_fact(spec=spec, slide_copy=slide_copy, index=index, total=total, package_identity=identity, media_image=selected_image, media_primitive=primitive, focus_y=focus_y, focus_x=focus_x)
    elif layout == SLIDE_LAYOUT_COMPARISON:
        result = _slide_comparison(spec=spec, slide_copy=slide_copy, index=index, total=total, package_identity=identity, media_image=selected_image, media_primitive=primitive, focus_y=focus_y, focus_x=focus_x)
    else:
        result = _slide_detail(spec=spec, role=role, slide_copy=slide_copy, index=index, total=total, package_identity=identity, media_image=selected_image, media_primitive=primitive, focus_y=focus_y, focus_x=focus_x)
    result.notes.update(render_plan or {})
    result.notes.update({
        "rendered_copy": [slide_copy], "internal_labels_rendered": [],
        "visual_direction_consumed": bool(visual_direction),
        "media_mode_consumed": media_mode,
        "per_slide_media_consumed": media_image is not None,
        # The REAL decision and the REAL pixel-level outcome, kept as two distinct, honest facts:
        # `media_primitive_selected` is what select_media_primitive() decided BEFORE rendering;
        # `source_image_treatment` (already on the LayoutResult) is what actually happened to the
        # pixels. The art validator checks these agree - see instagram_art_validator.py.
        "media_primitive_selected": primitive.value,
        "media_need_consumed": media_need,
    })
    return result


def _slide_hook(
    *, spec: ProfileSpec, slide_copy: str, index: int, total: int, package_identity: str,
    media_image: Image.Image | None, media_primitive: "SourceMediaPrimitive", focus_y: float,
    focus_x: float = 0.5,
) -> LayoutResult:
    canvas, treatment = _resolve_slide_background(
        media_primitive, media_image, width=spec.width, height=spec.height, focus_y=focus_y, focus_x=focus_x,
        identity=package_identity, block_count=0,
    )
    if treatment == SourceMediaPrimitive.NONE.value:
        # an oversized "1" watermark - the hook's own visual anchor when no real image exists.
        big = round(spec.width * 0.75)
        font = ig_font(big, "black")
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ldraw = ImageDraw.Draw(layer, "RGBA")
        ldraw.text((round(spec.width * 0.12), round(spec.height * 0.32)), "1", font=font, fill=(*tok.RED, 40))
        canvas.alpha_composite(layer)
        draw_corner_brackets(canvas, spec, top=False)

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
        source_image_treatment=treatment, layout_variant=SLIDE_LAYOUT_HOOK, text_clipped=clipped,
        notes=dict(source_coverage_fraction=1.0 if media_image is not None else 0.0),
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
    package_identity: str, media_image: Image.Image | None,
    media_primitive: "SourceMediaPrimitive" = SourceMediaPrimitive.STRIP, focus_y: float = 0.42, focus_x: float = 0.5,
) -> LayoutResult:
    """A light editorial field with a secondary image strip, not another dark report card. STRIP
    is a sub-rectangle, not a full canvas, so this stays its own bespoke geometry rather than
    calling `_resolve_slide_background` - but WHETHER it shows an image at all, and whether that
    crop is the standard strip framing or a tighter DETAIL_CROP zoom, is now the real decided
    primitive, not an unconditional "hero_image is not None" check."""
    canvas = Image.new("RGBA", (spec.width, spec.height), (*tok.PAPER, 255))
    image_w = round(spec.width * 0.34)
    treatment = "none"
    show_image = media_image is not None and media_primitive is not SourceMediaPrimitive.NONE
    if show_image:
        if media_primitive is SourceMediaPrimitive.DETAIL_CROP:
            cropped, treatment = build_detail_crop_field(media_image, width=image_w, height=spec.height, focus_y=focus_y, focus_x=focus_x, zoom=2.4)
            canvas.paste(cropped, (0, 0))
        else:
            fitted = fit_image_cover(media_image, width=image_w, height=spec.height, focus_y=focus_y, focus_x=focus_x)
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
    media_image: Image.Image | None = None, media_primitive: "SourceMediaPrimitive" = SourceMediaPrimitive.NONE,
    focus_y: float = 0.42, focus_x: float = 0.5,
) -> LayoutResult:
    """A tension composition: offset copy, a broken axis, and one dominant punctuation mark. The
    left `RED_DEEP` block (this family's own bold identity) always stays solid on top; a real
    image, when the plan asks for one, only ever shows as texture on the copy side - the same
    "foreground grammar unchanged, background source real" pattern as COMPARISON/DETAIL/CLOSING."""
    canvas, treatment = _resolve_slide_background(
        media_primitive, media_image, width=spec.width, height=spec.height, focus_y=focus_y, focus_x=focus_x,
        identity=package_identity, block_count=0,
    )
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
        source_image_treatment=treatment, layout_variant=SLIDE_LAYOUT_PROBLEM, text_clipped=clipped,
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
    media_image: Image.Image | None = None, media_primitive: "SourceMediaPrimitive" = SourceMediaPrimitive.NONE,
    focus_y: float = 0.42, focus_x: float = 0.5,
) -> LayoutResult:
    canvas, source_treatment = _resolve_slide_background(
        media_primitive, media_image, width=spec.width, height=spec.height, focus_y=focus_y, focus_x=focus_x,
        identity=package_identity, block_count=0,
    )
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


def _slide_fact(
    *, spec: ProfileSpec, slide_copy: str, index: int, total: int, package_identity: str,
    media_image: Image.Image | None = None, media_primitive: "SourceMediaPrimitive" = SourceMediaPrimitive.NONE,
    focus_y: float = 0.42, focus_x: float = 0.5,
) -> LayoutResult:
    canvas, fact_treatment = _resolve_slide_background(
        media_primitive, media_image, width=spec.width, height=spec.height, focus_y=focus_y, focus_x=focus_x,
        identity=package_identity, block_count=0,
    )
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
        source_image_treatment=fact_treatment, layout_variant=SLIDE_LAYOUT_FACT, text_clipped=clipped,
    )


def _slide_comparison(
    *, spec: ProfileSpec, slide_copy: str, index: int, total: int, package_identity: str,
    media_image: Image.Image | None = None, media_primitive: "SourceMediaPrimitive" = SourceMediaPrimitive.NONE,
    focus_y: float = 0.42, focus_x: float = 0.5,
) -> LayoutResult:
    split = _split_vs(slide_copy)
    assert split is not None  # select_slide_layout only routes here when a real split exists
    left_text, right_text = split

    # The left panel is always covered by its own solid `INK_RAISED` rectangle below (unchanged),
    # so a real image only ever shows through as the RIGHT panel's texture - the existing "left
    # solid / right whatever's-behind-it" asymmetry was already the design; only the background
    # source changes here, none of the panel/VS-badge drawing logic below does. Default primitive
    # is NONE (a comparison may be "primarily graphic, no photo" - the plan decides otherwise via
    # media_need, not this function).
    canvas, source_treatment = _resolve_slide_background(
        media_primitive, media_image, width=spec.width, height=spec.height, focus_y=focus_y, focus_x=focus_x,
        identity=package_identity, block_count=0,
    )
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
    media_image: Image.Image | None = None, media_primitive: "SourceMediaPrimitive" = SourceMediaPrimitive.DETAIL_CROP,
    focus_y: float = 0.42, focus_x: float = 0.5,
) -> LayoutResult:
    canvas, detail_source_treatment = _resolve_slide_background(
        media_primitive, media_image, width=spec.width, height=spec.height, focus_y=focus_y, focus_x=focus_x,
        identity=package_identity, block_count=0,
    )
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
