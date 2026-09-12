"""INSTAGRAM-VISUAL-SYSTEM-V1-1 section 9: DATA family - a genuine premium infographic, not a
plain black card with a number on it. Two deterministic variants:

  DATA_VARIANT_METRIC_ONLY  - no real series was supplied -> a large hero metric + label + context,
                               richly composed (grid texture, accent geometry, layered panels) but
                               NEVER a fabricated chart.
  DATA_VARIANT_WITH_GRAPH   - a real `series` (>=2 points) was supplied -> the metric ANCHORS the
                               composition and a real line/area chart plots the actual points -
                               exact anchors only, no synthetic/interpolated data points ever added.

Variant choice is driven purely by whether real structured series data exists (section 17's
"content/media properties, not uncontrolled randomness" + section 9's "never fabricate chart
points"). Independent of Telegram V8 - no import of nnj_board_metrics.py/brand_renderer.py; this is
a fresh Instagram-native chart implementation."""
from __future__ import annotations

from PIL import Image, ImageDraw

from services import instagram_design_tokens as tok
from services.instagram_editorial_layouts import LayoutResult, TextRegionSpec
from services.instagram_image_handling import (
    build_structured_fallback,
    draw_corner_brackets,
    draw_kicker_chip,
    draw_with_alpha,
    mark_reserve_width,
    place_brand_mark,
)
from services.instagram_text_fit import box4, fit_text_block, measure_block_height
from services.instagram_visual_profiles import ProfileSpec, ig_font

DATA_VARIANT_METRIC_ONLY = "data_metric_only"
DATA_VARIANT_WITH_GRAPH = "data_with_graph"


def select_data_variant(series: list[tuple[str, float]] | None) -> str:
    """Deterministic: a real series of >=2 points earns the graph variant; anything else (None,
    empty, a single point - not enough to draw a meaningful line) falls back to metric-only. Never
    a random choice, and never a graph drawn from invented points."""
    if series and len(series) >= 2:
        return DATA_VARIANT_WITH_GRAPH
    return DATA_VARIANT_METRIC_ONLY


def _draw_accent_geometry(canvas: Image.Image, spec: ProfileSpec) -> None:
    """Restrained brand geometry, fully CONTAINED in the top-right corner (never a stray line
    sweeping across the whole frame) - a small instrument-dial ring, the kind of quiet technical
    motif a data/markets graphic earns, giving the metric-only variant a designed identity instead
    of reading as an empty panel with text floating on it."""
    w, h = canvas.size
    r = round(w * 0.16)
    cx, cy = w - round(w * 0.10), round(w * 0.10)
    bbox = [cx - r, cy - r, cx + r, cy + r]

    def _paint(draw: ImageDraw.ImageDraw) -> None:
        draw.arc(bbox, start=0, end=360, fill=(*tok.INK_RAISED, 220), width=2)
        draw.arc(bbox, start=200, end=340, fill=(*tok.RED, 200), width=4)
        draw.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=(*tok.RED, 220))

    draw_with_alpha(canvas, _paint)
    draw_corner_brackets(canvas, spec, top=False)


def _draw_metric_watermark(canvas: Image.Image, spec: ProfileSpec, *, metric_value: str, metric_unit: str | None) -> None:
    """A large, very-low-alpha echo of the hero number, bled off the right/bottom edge - a common
    premium data-editorial device that fills what would otherwise be dead canvas space with real
    content (the actual metric, restated) rather than arbitrary decoration."""
    text = metric_value + (metric_unit or "")
    size = round(spec.width * 0.62)
    font = ig_font(size, tok.TYPE_METRIC.weight)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ldraw = ImageDraw.Draw(layer, "RGBA")
    bbox = ldraw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = spec.width - round(tw * 0.62)
    y = spec.height - round(th * 0.95)
    ldraw.text((x - bbox[0], y - bbox[1]), text, font=font, fill=(*tok.WHITE, 16))
    canvas.alpha_composite(layer)


def _draw_series_chart(
    canvas: Image.Image, *, x: int, y: int, w: int, h: int, series: list[tuple[str, float]],
) -> None:
    """Plots the REAL supplied (label, value) points only - exact anchors, straight segments
    between them, no smoothing/interpolation that could imply data that was not actually supplied.
    A light area fill under the line plus small end-dots at every real point (never only the last
    one) so the chart visibly reads as real, discrete measurements."""
    draw = ImageDraw.Draw(canvas, "RGBA")
    values = [v for _, v in series]
    vmin, vmax = min(values), max(values)
    vspan = (vmax - vmin) or 1.0
    n = len(series)
    xs = [x + round(w * i / (n - 1)) for i in range(n)]
    ys = [y + h - round(h * (v - vmin) / vspan) for v in values]

    # area fill
    poly = list(zip(xs, ys)) + [(xs[-1], y + h), (xs[0], y + h)]
    area = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(area, "RGBA").polygon(poly, fill=(*tok.RED, 30))
    canvas.alpha_composite(area)

    draw.line(list(zip(xs, ys)), fill=(*tok.RED, 255), width=4, joint="curve")
    for i, (px, py) in enumerate(zip(xs, ys)):
        rad = 7 if i in (0, n - 1) else 5
        draw.ellipse([px - rad, py - rad, px + rad, py + rad], fill=(*tok.WHITE, 255))
        draw.ellipse([px - rad, py - rad, px + rad, py + rad], outline=(*tok.RED, 255), width=2)

    # x-axis labels (the real series labels, never invented ticks)
    label_font_size = max(14, round(w * 0.022))
    lfont = ig_font(label_font_size, "medium")
    for (lbl, _), px in zip(series, xs):
        tw = draw.textlength(lbl, font=lfont)
        draw.text((px - tw / 2, y + h + round(h * 0.06)), lbl, font=lfont, fill=tok.GREY_SOFT)


def render_data_layout(
    *, spec: ProfileSpec, kicker: str, metric_value: str, metric_unit: str | None, metric_label: str,
    context: str | None, series: list[tuple[str, float]] | None, package_identity: str,
) -> LayoutResult:
    variant = select_data_variant(series)
    canvas = build_structured_fallback(width=spec.width, height=spec.height, identity=package_identity, block_count=0)
    _draw_accent_geometry(canvas, spec)
    _draw_metric_watermark(canvas, spec, metric_value=metric_value, metric_unit=metric_unit)
    draw = ImageDraw.Draw(canvas, "RGBA")

    margin = round(spec.width * tok.MARGIN_FRAC)
    content_w = spec.width - margin - max(margin, mark_reserve_width(spec))
    regions: list[TextRegionSpec] = []

    top_y = round(spec.height * spec.safe_top_frac) + margin
    cw, ch = draw_kicker_chip(canvas, x=margin, y=top_y, text=kicker)
    kicker_bottom = top_y + ch + round(spec.height * 0.035)
    bottom_safe_px = round(spec.height * spec.safe_bottom_frac) + margin

    # --- measurement pass: know every block's real height BEFORE placing anything, so the whole
    # hero content stack can be vertically CENTERED in the space below the kicker rather than
    # left jammed at the top with a dead empty zone below it (the Founder's "empty black canvas"
    # rejection) - true regardless of how short the copy for a given post happens to be.
    value_font = tok.TYPE_METRIC
    value_size = round(spec.width * value_font.size_frac)
    unit_size = round(spec.width * tok.TYPE_METRIC_UNIT.size_frac)
    vfont = ig_font(value_size, value_font.weight)
    metric_h = round(draw.textbbox((0, 0), metric_value, font=vfont)[3])
    gap_a = round(spec.height * 0.012)

    label_font, label_lines, label_clipped = fit_text_block(
        draw, metric_label, font_max=round(spec.width * tok.TYPE_METRIC_LABEL.size_frac),
        font_min=round(spec.width * 0.028), max_width=content_w, max_lines=tok.TYPE_METRIC_LABEL.max_lines,
        weight=tok.TYPE_METRIC_LABEL.weight,
    )
    label_h = measure_block_height(draw, label_lines, label_font)
    gap_b = round(spec.height * 0.03)

    chart_h = round(spec.height * 0.26) if (variant == DATA_VARIANT_WITH_GRAPH and series) else 0
    gap_c = round(spec.height * 0.09) if chart_h else 0

    context_lines: list[str] = []
    ctx_font = None
    context_clipped = False
    context_h = 0
    gap_d = 0
    if context:
        available_for_ctx = spec.height - bottom_safe_px - kicker_bottom - metric_h - gap_a - label_h - gap_b - chart_h - gap_c
        max_lines = max(1, min(tok.TYPE_METRIC_CONTEXT.max_lines, available_for_ctx // round(spec.width * tok.TYPE_METRIC_CONTEXT.size_frac * 1.4)))
        ctx_font, context_lines, context_clipped = fit_text_block(
            draw, context, font_max=round(spec.width * tok.TYPE_METRIC_CONTEXT.size_frac), font_min=round(spec.width * 0.022),
            max_width=content_w, max_lines=max_lines, weight=tok.TYPE_METRIC_CONTEXT.weight,
        )
        context_h = measure_block_height(draw, context_lines, ctx_font)
        gap_d = round(spec.height * 0.015)

    stack_h = metric_h + gap_a + label_h + gap_b + chart_h + gap_c + (gap_d + context_h if context_lines else 0)
    available_h = spec.height - bottom_safe_px - kicker_bottom
    y: float = kicker_bottom + max(0, (available_h - stack_h) // 2)

    # --- draw pass ---
    vbbox = draw.textbbox((margin, y), metric_value, font=vfont)
    draw.text((margin, y), metric_value, font=vfont, fill=value_font.color)
    regions.append(TextRegionSpec(kind="metric_value", box=box4(vbbox), clipped=False))
    if metric_unit:
        ufont = ig_font(unit_size, tok.TYPE_METRIC_UNIT.weight)
        draw.text((vbbox[2] + round(spec.width * 0.015), vbbox[3] - unit_size), metric_unit, font=ufont, fill=tok.TYPE_METRIC_UNIT.color)
    y = vbbox[3] + gap_a

    for line in label_lines:
        bbox = draw.textbbox((margin, y), line, font=label_font)
        draw.text((margin, y), line, font=label_font, fill=tok.TYPE_METRIC_LABEL.color)
        regions.append(TextRegionSpec(kind="metric_label", box=box4(bbox), clipped=False))
        y += (bbox[3] - bbox[1]) + round(label_font.size * 0.2)

    y += gap_b

    if chart_h and series:
        _draw_series_chart(canvas, x=margin, y=round(y), w=content_w, h=chart_h, series=series)
        y += chart_h + gap_c

    if ctx_font is not None and context_lines:
        y += gap_d
        for line in context_lines:
            bbox = draw.textbbox((margin, y), line, font=ctx_font)
            draw.text((margin, y), line, font=ctx_font, fill=tok.TYPE_METRIC_CONTEXT.color)
            regions.append(TextRegionSpec(kind="context", box=box4(bbox), clipped=context_clipped))
            y += (bbox[3] - bbox[1]) + round(ctx_font.size * 0.3)

    mark_count = place_brand_mark(canvas, spec)
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=regions, visible_brand_mark_count=mark_count,
        source_image_treatment="none", layout_variant=variant,
        text_clipped=label_clipped or context_clipped,
        notes={"series_points": len(series) if series else 0},
    )
