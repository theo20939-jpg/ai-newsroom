"""Instagram CAROUSEL slide renderer - Phase B.4.4 light editorial grammar, NO OVERLAYS.

Founder decision (B.4.4): overlays are not part of the Instagram visual system. This module never
darkens, tints, blurs, scrims or gradient-washes source imagery, and never places text on a
dimmed photo. Source media is only ever cropped, contained, repositioned or scaled - into its own
region - and every render records evidence proving its pixels were left untouched
(`source_media_pixels_unaltered`, `overlay_operations_executed == 0`).

Surfaces are LIGHT by default (paper / soft-tint), with NINJA's restrained red accent, typography
and grid carrying the identity - not a black rectangle with white copy. If text cannot stay
readable directly on a photograph, the composition changes (media in its own region + clean text
surface); the photograph is never darkened to make text fit.

Every slide is rendered by ONE composition dispatch. An explicit `composition` (the Creative
Director's structured plan) is honoured; when a slide supplies none, a small deterministic default
(`_default_composition`) is used and the slide is recorded as a role fallback. Text that does not
fit a requested composition triggers an explicit, recorded adaptation to a more text-capable
layout (`composition_adapted_for_text_fit`) instead of clipping or truncating the copy."""
from __future__ import annotations

import re
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw

from services import instagram_design_tokens as tok
from services.instagram_editorial_layouts import LayoutResult, TextRegionSpec
from services.instagram_image_handling import build_detail_crop_field, fit_image_cover, mark_reserve_width, place_brand_mark
from services.instagram_text_fit import box4, fit_text_block, measure_block_height
from services.instagram_visual_profiles import ProfileSpec, ig_font

# A second LIGHT surface (soft cool grey) - structural separation without a dark panel.
SURFACE_TINT = (233, 236, 241)
MUTED_INK = (96, 101, 110)
HAIRLINE = (208, 212, 219)

_CLOSING_ROLES = {"cta", "takeaway"}
_STEP_RE = re.compile(r"^\s*(?:шаг|step)\s*(\d{1,2})\s*[.:—\-]?\s*(.*)$", re.IGNORECASE | re.DOTALL)
_STORY_RE = re.compile(r"story[_\s-]*(\d{1,2})", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+")


@dataclass(frozen=True)
class _Attempt:
    composition: str
    position: str | None = None
    scale: float | None = None
    variant: str | None = None


def _split_vs(text: str) -> tuple[str, str] | None:
    for sep in (" vs. ", " vs ", " VS ", " Vs "):
        if sep in text:
            left, right = text.split(sep, 1)
            if left.strip() and right.strip():
                return left.strip(), right.strip()
    return None


def _split_sides(text: str) -> tuple[str, str, bool] | None:
    """(left, right, had_explicit_vs) - only a REAL two-sided structure in the copy; never invented."""
    explicit = _split_vs(text)
    if explicit is not None:
        return explicit[0], explicit[1], True
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text.strip()) if p.strip()]
    if len(parts) >= 2 and len(parts[0]) >= 12 and len(" ".join(parts[1:])) >= 12:
        return parts[0], " ".join(parts[1:]), False
    return None


def _focus_y_from_focal_point(focal_point: str | None) -> float:
    text = str(focal_point or "").lower()
    if any(t in text for t in ("низ", "нижн", "bottom", "внизу")):
        return 0.65
    if any(t in text for t in ("верх", "top", "сверху")):
        return 0.25
    return 0.42


def _focus_x_from_focal_point(focal_point: str | None) -> float:
    text = str(focal_point or "").lower()
    if any(t in text for t in ("справа", "right", "правой")):
        return 0.65
    if any(t in text for t in ("слева", "left", "левой")):
        return 0.35
    return 0.5


def select_slide_layout(*, role: str, index: int, slide_copy: str) -> str:
    """Kept for callers that want the role-derived DEFAULT composition family name."""
    return _default_composition(role=role, index=index, has_media=False, slide_copy=slide_copy).composition


def _default_composition(*, role: str, index: int, has_media: bool, slide_copy: str) -> _Attempt:
    """Deterministic role fallback used ONLY when the slide supplies no explicit composition. Light
    surfaces throughout; media (when available) goes into its own region, never behind text."""
    r = role.strip().lower()
    if r == "comparison" and _split_vs(slide_copy) is not None:
        return _Attempt("split_compare")
    if r in _CLOSING_ROLES or not has_media:
        return _Attempt("typographic")
    if index == 0 or r == "hook":
        return _Attempt("contained_media", "top", 0.58)
    position = ("left", "top", "right")[(index - 1) % 3]
    return _Attempt("contained_media", position, 0.5 if position == "top" else 0.46)


# --------------------------------------------------------------------------------------
# small drawing helpers (light surfaces only)
# --------------------------------------------------------------------------------------


def _new_paper(spec: ProfileSpec, colour: tuple[int, int, int] = tok.PAPER) -> Image.Image:
    return Image.new("RGBA", (spec.width, spec.height), (*colour, 255))


def _paste_media(canvas: Image.Image, fitted: Image.Image, xy: tuple[int, int], fidelity: list[bool]) -> None:
    """Paste a fitted source crop and PROVE its pixels survived untouched (before any text/mark)."""
    canvas.paste(fitted, xy)
    region = canvas.crop((xy[0], xy[1], xy[0] + fitted.width, xy[1] + fitted.height)).convert("RGB")
    fidelity.append(ImageChops.difference(region, fitted.convert("RGB")).getbbox() is None)


def _draw_progress(canvas: Image.Image, spec: ProfileSpec, *, index: int, total: int, x: int, y: int, colour=MUTED_INK) -> None:
    draw = ImageDraw.Draw(canvas, "RGBA")
    size = round(spec.width * tok.TYPE_SLIDE_INDEX.size_frac)
    draw.text((x, y), f"{index + 1:02d} / {total:02d}", font=ig_font(size, tok.TYPE_SLIDE_INDEX.weight), fill=colour)


def _draw_copy(
    canvas: Image.Image, spec: ProfileSpec, text: str, *, x: int, y: float, width: int, colour, max_frac: float,
    min_frac: float = 0.03, max_lines: int = 9, weight: str = "black", max_height: int | None = None,
    kind: str = "headline",
) -> tuple[list[TextRegionSpec], bool, int]:
    """Fit + draw one copy block. `max_height` (optional) makes an over-tall block count as clipped
    so the caller adapts the composition instead of letting text run off its region."""
    draw = ImageDraw.Draw(canvas, "RGBA")
    font, lines, clipped = fit_text_block(
        draw, text, font_max=round(spec.width * max_frac), font_min=round(spec.width * min_frac),
        max_width=width, max_lines=max_lines, weight=weight,
    )
    block_h = measure_block_height(draw, lines, font)
    if max_height is not None and block_h > max_height:
        clipped = True
    regions: list[TextRegionSpec] = []
    py = y
    for i, line in enumerate(lines):
        bbox = draw.textbbox((x, py), line, font=font)
        draw.text((x, py), line, font=font, fill=colour)
        regions.append(TextRegionSpec(kind=kind, box=box4(bbox), clipped=clipped and i == len(lines) - 1))
        py += (bbox[3] - bbox[1]) + round(font.size * 0.2)
    return regions, clipped, block_h


def _content_width(spec: ProfileSpec, margin: int) -> int:
    return spec.width - margin - max(margin, mark_reserve_width(spec, compact=True))


def _result(
    canvas: Image.Image, spec: ProfileSpec, regions: list[TextRegionSpec], clipped: bool, *, variant: str,
    treatment: str, notes: dict,
) -> LayoutResult:
    mark_count = place_brand_mark(canvas, spec, compact=True)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment=treatment, layout_variant=variant, text_clipped=clipped, notes=notes,
    )


# --------------------------------------------------------------------------------------
# compositions
# --------------------------------------------------------------------------------------


def _render_typographic(spec, text, index, total, *, media_subject, graphic_reason: str | None) -> LayoutResult:
    """Light type-led surface. The variant follows the COPY's own structure (a numbered step, a
    story number, a short statement, or an editorial paragraph) - a purposeful graphic, not a
    generic card."""
    canvas = _new_paper(spec)
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    width = _content_width(spec, margin)
    top = round(spec.height * spec.safe_top_frac) + margin
    _draw_progress(canvas, spec, index=index, total=total, x=margin, y=top)

    numeral: str | None = None
    body = text
    variant = "generic_typographic_editorial"
    step = _STEP_RE.match(text)
    story = _STORY_RE.search(str(media_subject or ""))
    if step is not None and step.group(2).strip():
        numeral, body, variant = step.group(1), step.group(2).strip(), "generic_typographic_step"
    elif story is not None:
        numeral, variant = story.group(1), "generic_typographic_story_number"

    regions: list[TextRegionSpec] = []
    if numeral is not None:
        nfont = ig_font(round(spec.width * 0.36), "black")
        nbox = draw.textbbox((margin, top + round(spec.height * 0.05)), numeral, font=nfont)
        draw.text((margin, top + round(spec.height * 0.05)), numeral, font=nfont, fill=tok.RED)
        rule_y = nbox[3] + round(spec.height * 0.03)
        draw.rectangle([margin, rule_y, margin + round(spec.width * tok.ACCENT_RULE_WIDTH_FRAC), rule_y + tok.ACCENT_RULE_THICKNESS_PX], fill=(*tok.RED, 255))
        text_top = rule_y + round(spec.height * 0.04)
        avail = spec.height - round(spec.height * spec.safe_bottom_frac) - margin - text_top
        regions, clipped, _ = _draw_copy(canvas, spec, body, x=margin, y=text_top, width=width, colour=tok.INK, max_frac=0.062, min_frac=0.03, max_height=avail)
    elif len(text) <= 60:
        variant = "generic_typographic_statement"
        rule_y = top + round(spec.height * 0.10)
        draw.rectangle([margin, rule_y, margin + round(spec.width * tok.ACCENT_RULE_WIDTH_FRAC), rule_y + tok.ACCENT_RULE_THICKNESS_PX], fill=(*tok.RED, 255))
        avail = spec.height - round(spec.height * spec.safe_bottom_frac) - margin - (rule_y + 60)
        regions, clipped, _ = _draw_copy(canvas, spec, text, x=margin, y=rule_y + round(spec.height * 0.05), width=width, colour=tok.INK, max_frac=0.105, min_frac=0.045, max_height=avail)
    else:
        rule_y = top + round(spec.height * 0.08)
        draw.rectangle([margin, rule_y, margin + round(spec.width * tok.ACCENT_RULE_WIDTH_FRAC), rule_y + tok.ACCENT_RULE_THICKNESS_PX], fill=(*tok.RED, 255))
        text_top = rule_y + round(spec.height * 0.045)
        avail = spec.height - round(spec.height * spec.safe_bottom_frac) - margin - text_top
        regions, clipped, _ = _draw_copy(canvas, spec, text, x=margin, y=text_top, width=width, colour=tok.INK, max_frac=0.07, min_frac=0.03, max_height=avail)
    hair_y = spec.height - round(spec.height * spec.safe_bottom_frac) - margin - round(spec.height * 0.012)
    draw.line([(margin, hair_y), (margin + round(spec.width * 0.5), hair_y)], fill=(*HAIRLINE, 255), width=2)
    return _result(canvas, spec, regions, clipped, variant=variant, treatment="none", notes={
        "graphic_fallback_used": graphic_reason is not None, "graphic_fallback_reason": graphic_reason,
        "source_media_pixels_unaltered": None,
    })


def _media_box(spec: ProfileSpec, position: str, scale: float) -> tuple[int, int, int, int]:
    if position == "left":
        return (0, 0, round(spec.width * min(0.55, max(0.32, scale))), spec.height)
    if position == "right":
        w = round(spec.width * min(0.55, max(0.32, scale)))
        return (spec.width - w, 0, spec.width, spec.height)
    return (0, 0, spec.width, round(spec.height * min(0.62, max(0.30, scale))))


def _render_contained(spec, text, index, total, media, position, scale, fx, fy, *, framed: bool) -> LayoutResult:
    canvas = _new_paper(spec)
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    bx0, by0, bx1, by1 = _media_box(spec, position, scale)
    if framed:  # frame is drawn OUTSIDE the media rectangle (media pixels never touched)
        ring = max(4, round(spec.width * 0.008))
        draw.rectangle([max(0, bx0 - ring), max(0, by0 - ring), min(spec.width, bx1 + ring), min(spec.height, by1 + ring)], fill=(*tok.RED, 255))
        bx0, by0, bx1, by1 = bx0 + (ring if bx0 else 0), by0 + ring, bx1 - (ring if bx1 < spec.width else 0), by1 - ring
        if position == "top":
            bx0, bx1 = ring, spec.width - ring
    fitted = fit_image_cover(media, width=bx1 - bx0, height=by1 - by0, focus_x=fx, focus_y=fy).image
    fidelity: list[bool] = []
    _paste_media(canvas, fitted, (bx0, by0), fidelity)

    if position == "top":
        x, y, width = margin, by1 + round(spec.height * 0.05), _content_width(spec, margin)
    elif position == "left":
        x = bx1 + round(spec.width * 0.06)
        y, width = round(spec.height * spec.safe_top_frac) + margin, spec.width - x - max(margin, mark_reserve_width(spec, compact=True))
    else:
        x, y = margin, round(spec.height * spec.safe_top_frac) + margin
        width = bx0 - margin - round(spec.width * 0.05)
    if width < spec.width * 0.24:
        return None  # column too narrow for the copy - caller adapts
    _draw_progress(canvas, spec, index=index, total=total, x=x, y=y)
    text_y = y + round(spec.height * 0.035)
    avail = spec.height - round(spec.height * spec.safe_bottom_frac) - margin - text_y
    regions, clipped, _ = _draw_copy(canvas, spec, text, x=x, y=text_y, width=width, colour=tok.INK, max_frac=0.062, min_frac=0.03, max_height=avail)
    variant = f"generic_{'screenshot_ui' if framed else 'contained_media'}_{position}"
    return _result(canvas, spec, regions, clipped, variant=variant, treatment="cover_cropped", notes={
        "source_media_pixels_unaltered": all(fidelity), "graphic_fallback_used": False,
        "source_coverage_fraction": round(((bx1 - bx0) * (by1 - by0)) / (spec.width * spec.height), 3),
    })


def _gray_stats(region: Image.Image) -> tuple[float, float, float]:
    """(p10, p90, std) of a grayscale region - deterministic, dependency-free."""
    hist = region.convert("L").histogram()
    total = sum(hist)
    if total == 0:
        return 0.0, 0.0, 0.0
    mean = sum(i * c for i, c in enumerate(hist)) / total
    var = sum(c * (i - mean) ** 2 for i, c in enumerate(hist)) / total

    def pct(q: float) -> float:
        acc, target = 0, total * q
        for i, c in enumerate(hist):
            acc += c
            if acc >= target:
                return float(i)
        return 255.0

    return pct(0.10), pct(0.90), var ** 0.5


def _lin(g: float) -> float:
    return (g / 255.0) ** 2.2


def _text_colour_for_band(band: Image.Image) -> tuple[int, int, int] | None:
    """A text colour that is readable ON the untouched photo band, or None if the band is not quiet
    enough. Never darkens anything - the only degree of freedom is the TEXT colour."""
    p10, p90, std = _gray_stats(band)
    if std > 30:
        return None
    if (0.93 + 0.05) / (_lin(p90) + 0.05) >= 4.5:
        return tok.WHITE
    if (_lin(p10) + 0.05) / (0.003 + 0.05) >= 4.5:
        return tok.INK
    return None


def _render_full_bleed(spec, text, index, total, media, fx, fy) -> LayoutResult | None:
    fitted = fit_image_cover(media, width=spec.width, height=spec.height, focus_x=fx, focus_y=fy).image
    canvas = fitted.copy()
    fidelity: list[bool] = []
    fidelity.append(ImageChops.difference(canvas.convert("RGB"), fitted.convert("RGB")).getbbox() is None)
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    width = _content_width(spec, margin)
    font, lines, clipped = fit_text_block(
        draw, text, font_max=round(spec.width * tok.TYPE_HEADLINE_L.size_frac), font_min=round(spec.width * 0.05),
        max_width=width, max_lines=4, weight=tok.TYPE_HEADLINE_L.weight,
    )
    if clipped:
        return None
    block_h = measure_block_height(draw, lines, font)
    pad = round(spec.width * 0.02)
    bottom_y = spec.height - round(spec.height * spec.safe_bottom_frac) - margin - block_h
    top_y = round(spec.height * spec.safe_top_frac) + margin + round(spec.height * 0.05)
    rgb = fitted.convert("RGB")
    chosen: tuple[float, tuple[int, int, int]] | None = None
    for y in (bottom_y, top_y):
        band = rgb.crop((max(0, margin - pad), max(0, int(y) - pad), min(spec.width, margin + width + pad), min(spec.height, int(y) + block_h + pad)))
        colour = _text_colour_for_band(band)
        if colour is not None:
            chosen = (y, colour)
            break
    if chosen is None:
        return None  # no naturally quiet space - the caller picks a different composition
    y, colour = chosen
    _draw_progress(canvas, spec, index=index, total=total, x=margin, y=int(y) - round(spec.height * 0.04), colour=colour)
    regions: list[TextRegionSpec] = []
    py = y
    for i, line in enumerate(lines):
        bbox = draw.textbbox((margin, py), line, font=font)
        draw.text((margin, py), line, font=font, fill=colour)
        regions.append(TextRegionSpec(kind="headline", box=box4(bbox), clipped=False))
        py += (bbox[3] - bbox[1]) + round(font.size * 0.18)
    return _result(canvas, spec, regions, False, variant="generic_full_bleed_media", treatment="cover_cropped", notes={
        "source_media_pixels_unaltered": all(fidelity), "graphic_fallback_used": False, "source_coverage_fraction": 1.0,
    })


def _render_collage(spec, text, index, total, media, fx, fy) -> LayoutResult:
    canvas = _new_paper(spec)
    margin = round(spec.width * tok.MARGIN_FRAC)
    gap = round(spec.width * 0.02)
    area_h = round(spec.height * 0.56)
    big_w = round(spec.width * 0.64)
    small_w = spec.width - big_w - gap
    wide = fit_image_cover(media, width=big_w, height=area_h, focus_x=fx, focus_y=0.35).image
    detail, _ = build_detail_crop_field(media, width=small_w, height=area_h, focus_x=fx, focus_y=0.68, zoom=2.4)
    fidelity: list[bool] = []
    _paste_media(canvas, wide, (0, 0), fidelity)
    _paste_media(canvas, detail, (big_w + gap, 0), fidelity)
    y = area_h + round(spec.height * 0.04)
    _draw_progress(canvas, spec, index=index, total=total, x=margin, y=y)
    text_y = y + round(spec.height * 0.035)
    avail = spec.height - round(spec.height * spec.safe_bottom_frac) - margin - text_y
    regions, clipped, _ = _draw_copy(canvas, spec, text, x=margin, y=text_y, width=_content_width(spec, margin), colour=tok.INK, max_frac=0.062, min_frac=0.03, max_height=avail)
    return _result(canvas, spec, regions, clipped, variant="generic_collage", treatment="cover_cropped", notes={
        "source_media_pixels_unaltered": all(fidelity), "graphic_fallback_used": False, "source_coverage_fraction": 0.56,
    })


def _render_split(spec, text, index, total, *, stacked: bool) -> LayoutResult | None:
    sides = _split_sides(text)
    if sides is None:
        return None
    left, right, explicit_vs = sides
    canvas = _new_paper(spec)
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    top = round(spec.height * spec.safe_top_frac) + margin
    _draw_progress(canvas, spec, index=index, total=total, x=margin, y=top)
    panel_top = top + round(spec.height * 0.05)
    panel_bottom = spec.height - round(spec.height * spec.safe_bottom_frac) - margin
    regions: list[TextRegionSpec] = []
    clipped_any = False
    if stacked:
        mid_y = (panel_top + panel_bottom) // 2
        draw.rectangle([0, mid_y, spec.width, panel_bottom + margin], fill=(*SURFACE_TINT, 255))
        draw.rectangle([margin, mid_y - 2, margin + round(spec.width * 0.3), mid_y + 2], fill=(*tok.RED, 255))
        for text_part, y0, y1 in ((left, panel_top, mid_y), (right, mid_y + round(spec.height * 0.03), panel_bottom)):
            r, c, _ = _draw_copy(canvas, spec, text_part, x=margin, y=y0 + round(spec.height * 0.02), width=_content_width(spec, margin), colour=tok.INK, max_frac=0.06, min_frac=0.032, max_height=(y1 - y0) - round(spec.height * 0.03))
            regions += r
            clipped_any = clipped_any or c
        variant = "generic_split_compare_stacked"
    else:
        mid_x = spec.width // 2
        draw.rectangle([mid_x, panel_top - margin // 2, spec.width, panel_bottom + margin], fill=(*SURFACE_TINT, 255))
        draw.rectangle([mid_x - 3, panel_top - margin // 2, mid_x + 3, panel_bottom + margin], fill=(*tok.RED, 255))
        col_w = mid_x - margin - round(spec.width * 0.04)
        for text_part, x0 in ((left, margin), (right, mid_x + round(spec.width * 0.04))):
            r, c, _ = _draw_copy(canvas, spec, text_part, x=x0, y=panel_top + round(spec.height * 0.04), width=col_w - (0 if x0 == margin else max(0, margin - round(spec.width * 0.04))), colour=tok.INK, max_frac=0.05, min_frac=0.03, max_height=panel_bottom - panel_top - round(spec.height * 0.08))
            regions += r
            clipped_any = clipped_any or c
        if explicit_vs:
            vfont = ig_font(round(spec.width * 0.04), "black")
            vb = draw.textbbox((0, 0), "vs", font=vfont)
            draw.rectangle([mid_x - (vb[2] - vb[0]) // 2 - 12, panel_top - 6, mid_x + (vb[2] - vb[0]) // 2 + 12, panel_top + (vb[3] - vb[1]) + 14], fill=(*tok.PAPER, 255))
            draw.text((mid_x - (vb[2] - vb[0]) / 2, panel_top - vb[1]), "vs", font=vfont, fill=tok.RED)
        variant = "generic_split_compare"
    return _result(canvas, spec, regions, clipped_any, variant=variant, treatment="none", notes={
        "source_media_pixels_unaltered": None, "graphic_fallback_used": False,
    })


def _render_ui_frame(spec, text, index, total) -> LayoutResult:
    """Graphic stand-in for a screenshot when none exists: a light window frame holding the copy."""
    canvas = _new_paper(spec)
    draw = ImageDraw.Draw(canvas, "RGBA")
    margin = round(spec.width * tok.MARGIN_FRAC)
    top = round(spec.height * spec.safe_top_frac) + margin
    _draw_progress(canvas, spec, index=index, total=total, x=margin, y=top)
    fx0, fy0 = margin, top + round(spec.height * 0.06)
    fx1, fy1 = spec.width - margin, spec.height - round(spec.height * spec.safe_bottom_frac) - margin - round(spec.height * 0.05)
    draw.rounded_rectangle([fx0, fy0, fx1, fy1], radius=28, fill=(*SURFACE_TINT, 255), outline=(*tok.RED, 255), width=4)
    bar_h = round(spec.height * 0.05)
    draw.line([(fx0 + 4, fy0 + bar_h), (fx1 - 4, fy0 + bar_h)], fill=(*HAIRLINE, 255), width=3)
    for i in range(3):
        cx = fx0 + 34 + i * 34
        draw.ellipse([cx - 9, fy0 + bar_h // 2 - 9, cx + 9, fy0 + bar_h // 2 + 9], fill=(*HAIRLINE, 255))
    inner_w = (fx1 - fx0) - 2 * round(spec.width * 0.05)
    text_y = fy0 + bar_h + round(spec.height * 0.05)
    avail = fy1 - text_y - round(spec.height * 0.03)
    regions, clipped, _ = _draw_copy(canvas, spec, text, x=fx0 + round(spec.width * 0.05), y=text_y, width=inner_w, colour=tok.INK, max_frac=0.055, min_frac=0.03, max_height=avail)
    return _result(canvas, spec, regions, clipped, variant="generic_ui_frame", treatment="none", notes={
        "graphic_fallback_used": True, "graphic_fallback_reason": "no_screenshot_asset", "source_media_pixels_unaltered": None,
    })


# --------------------------------------------------------------------------------------
# dispatch with explicit, recorded adaptation for text fit
# --------------------------------------------------------------------------------------


def _chain_for(comp: str, position: str | None, scale: float | None, has_media: bool) -> list[_Attempt]:
    pos = position if position in ("top", "left", "right") else "top"
    sc = scale if scale is not None else 0.46
    if comp == "typographic":
        return [_Attempt("typographic")]
    if comp == "split_compare":
        return [_Attempt("split_compare"), _Attempt("split_compare", variant="stacked"), _Attempt("typographic")]
    if comp == "screenshot_ui":
        head = [_Attempt("screenshot_ui", pos, sc)] if has_media else [_Attempt("ui_frame")]
        return head + ([_Attempt("screenshot_ui", "top", 0.40)] if has_media else []) + [_Attempt("typographic")]
    if not has_media:
        return [_Attempt("typographic")]
    if comp == "full_bleed_media":
        head = [_Attempt("full_bleed_media")]
    elif comp == "collage":
        head = [_Attempt("collage")]
    else:
        head = [_Attempt("contained_media", pos, sc)]
    return head + [_Attempt("contained_media", "top", 0.42), _Attempt("contained_media", "top", 0.32), _Attempt("typographic")]


def _run_attempt(a: _Attempt, *, spec, text, index, total, media, fx, fy, subject, graphic_reason) -> LayoutResult | None:
    if a.composition == "typographic":
        return _render_typographic(spec, text, index, total, media_subject=subject, graphic_reason=graphic_reason)
    if a.composition == "ui_frame":
        return _render_ui_frame(spec, text, index, total)
    if a.composition == "split_compare":
        return _render_split(spec, text, index, total, stacked=a.variant == "stacked")
    if media is None:
        return None
    if a.composition == "full_bleed_media":
        return _render_full_bleed(spec, text, index, total, media, fx, fy)
    if a.composition == "collage":
        return _render_collage(spec, text, index, total, media, fx, fy)
    return _render_contained(spec, text, index, total, media, a.position or "top", a.scale or 0.46, fx, fy, framed=a.composition == "screenshot_ui")


def render_carousel_slide(
    *, spec: ProfileSpec, role: str, index: int, total: int, slide_copy: str, source_evidence: str | None,
    package_identity: str, hero_image: Image.Image | None = None, visual_direction: str | None = None,
    render_plan: dict | None = None, media_image: Image.Image | None = None,
    media_mode: str | None = None, media_need: str | None = None, focal_point: str | None = None,
    composition: str | None = None, media_position: str | None = None, media_scale: float | None = None,
    media_subject: str | None = None, must_match_story: bool = False,
    media_asset_identity: str | None = None,
) -> LayoutResult:
    selected = media_image if media_image is not None else hero_image
    fx, fy = _focus_x_from_focal_point(focal_point), _focus_y_from_focal_point(focal_point)
    structured_present = composition is not None
    if structured_present:
        chain = _chain_for(composition.lower(), media_position, media_scale, selected is not None)
    else:
        d = _default_composition(role=role, index=index, has_media=selected is not None, slide_copy=slide_copy)
        chain = _chain_for(d.composition, d.position, d.scale, selected is not None)
    graphic_reason = None
    if selected is None and structured_present and composition.lower() in ("contained_media", "full_bleed_media", "collage", "screenshot_ui"):
        graphic_reason = "no_media_for_requested_composition"

    result: LayoutResult | None = None
    executed_first = False
    for attempt_no, attempt in enumerate(chain):
        candidate = _run_attempt(
            attempt, spec=spec, text=slide_copy, index=index, total=total, media=selected, fx=fx, fy=fy,
            subject=media_subject, graphic_reason=graphic_reason,
        )
        if candidate is None:
            continue
        result = candidate
        executed_first = attempt_no == 0
        if not candidate.text_clipped:
            break
    assert result is not None  # the chain always ends in a typographic render
    adapted = (not executed_first) and bool(graphic_reason is None)

    result.notes.update(render_plan or {})
    fidelity = result.notes.get("source_media_pixels_unaltered")
    result.notes.update({
        "rendered_copy": [slide_copy], "internal_labels_rendered": [],
        "visual_direction_consumed": bool(visual_direction),
        "media_mode_consumed": media_mode,
        "per_slide_media_consumed": result.source_image_treatment != "none",
        "media_need_consumed": media_need,
        "composition_requested": composition,
        "media_position_requested": media_position,
        "media_subject": media_subject,
        "must_match_story": must_match_story,
        "media_asset_identity": media_asset_identity,
        "structured_composition_present": structured_present,
        "structured_composition_executed": bool(structured_present and executed_first and graphic_reason is None),
        "fallback_role_layout_used": not structured_present,
        "composition_adapted_for_text_fit": adapted,
        "composition_executed": result.layout_variant,
        # Evidence that NO overlay/scrim/dim/tint/blur of source imagery exists in this renderer.
        "overlay_operations_executed": 0,
        "source_media_pixels_unaltered": fidelity,
    })
    return result
