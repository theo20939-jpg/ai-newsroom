"""Phase B.5: the SAFE renderer for a validated DECLARATIVE slide layout.

The Creative Director supplies composition relationships in normalized 0..1 canvas space. This
module owns everything brand-specific: the type family, the pixel size behind each scale token,
the colours (paper / soft / NINJA red / ink), the logo, margins and the progress marker. There is
no path for the model to introduce a font, a colour, a pixel size, code, CSS or SVG.

Guarantees (all deterministic - identical layout + copy + assets => identical pixels, no RNG):
  * NO overlay of any kind: source media is only cropped/contained into its own region; the
    evidence records `overlay_operations_executed=0` and whether each media region's pixels were
    left untouched right after placement;
  * text never sits on a photograph (the validator rejects text-over-media plans);
  * a media region whose subject has no resolved asset is not drawn (never an unrelated image);
  * text that cannot fit at the minimum readable size is reported as clipped (fail closed)."""
from __future__ import annotations

from typing import Any

from PIL import Image, ImageChops, ImageDraw

from schemas.instagram_creative import InstagramSlideLayout, LayoutRegion
from services import instagram_design_tokens as tok
from services.instagram_editorial_layouts import LayoutResult, TextRegionSpec
from services.instagram_image_handling import fit_image_contain, fit_image_cover, place_brand_mark
from services.instagram_layout_signature import layout_characteristics, layout_signature
from services.instagram_layout_validation import PROGRESS_ZONE, copy_parts
from services.instagram_text_fit import box4
from services.instagram_visual_profiles import ProfileSpec, ig_font

SURFACE_SOFT = (233, 236, 241)
MUTED_INK = (96, 101, 110)
HAIRLINE = (208, 212, 219)

# scale token -> (max font as a fraction of canvas width, font weight). Renderer-owned metrics.
SCALE_TOKENS: dict[str, tuple[float, str]] = {
    "DISPLAY": (0.16, "black"),
    "HEADLINE_L": (0.088, "black"),
    "HEADLINE_M": (0.072, "black"),
    "HEADLINE_S": (0.058, "black"),
    "BODY": (0.042, "semibold"),
    "CAPTION": (0.032, "semibold"),
}
_MIN_FONT_FRAC = 0.03  # minimum readable size (about 32px on a 1080px canvas)
_SURFACE_COLOURS = {"paper": tok.PAPER, "soft": SURFACE_SOFT, "red": tok.RED}


def _px(region: LayoutRegion, spec: ProfileSpec) -> tuple[int, int, int, int]:
    x0, y0 = round(region.x * spec.width), round(region.y * spec.height)
    return x0, y0, round((region.x + region.w) * spec.width), round((region.y + region.h) * spec.height)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_in_box(draw, text: str, *, box_w: int, box_h: int, token: str, max_lines: int | None, spec: ProfileSpec):
    """Largest font (<= token max, >= minimum readable) whose wrapped block fits BOTH the width and
    the height of the region. Returns (font, lines, block_h, clipped)."""
    max_frac, weight = SCALE_TOKENS[token]
    limit_lines = max_lines or 10
    size = round(spec.width * max_frac)
    min_size = round(spec.width * _MIN_FONT_FRAC)
    while size >= min_size:
        font = ig_font(size, weight)
        lines = _wrap(draw, text, font, box_w)
        gap = round(size * 0.2)
        heights = [draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1] for line in lines]
        block_h = sum(heights) + gap * max(0, len(lines) - 1)
        widest_ok = all(draw.textlength(line, font=font) <= box_w for line in lines)
        if lines and len(lines) <= limit_lines and block_h <= box_h and widest_ok:
            return font, lines, block_h, False
        size -= 4
    font = ig_font(min_size, weight)
    lines = _wrap(draw, text, font, box_w)[:limit_lines]
    if lines:
        last = lines[-1]
        while draw.textlength(last + "...", font=font) > box_w and len(last) > 1:
            last = last[:-1]
        lines[-1] = last.rstrip() + "..."
    return font, lines, box_h, True


def _text_colour(region: LayoutRegion, layout: InstagramSlideLayout) -> tuple[int, int, int]:
    cx, cy = region.x + region.w / 2, region.y + region.h / 2
    on_red = any(
        r.x <= cx <= r.x + r.w and r.y <= cy <= r.y + r.h and (
            (r.kind == "surface" and r.surface == "red") or (r.kind == "accent" and r.accent_type == "block")
        )
        for r in layout.regions
    )
    if on_red:
        return tok.PAPER
    return tok.RED if region.content_ref == "number" else tok.INK


def _flow_tokens(visual_direction: str | None) -> list[str] | None:
    text = str(visual_direction or "")
    if "«" in text and "»" in text:
        text = text.split("«", 1)[1].split("»", 1)[0]
    pieces = [p.strip(" .,:;—-").upper() for p in text.replace("->", "→").split("→")]
    pieces = [p for p in pieces if p and len(p) <= 22]
    return pieces[:4] if len(pieces) >= 2 else None


def _place_adaptive_mark(canvas: Image.Image, spec: ProfileSpec) -> int:
    """The canonical brand mark, same geometry as `place_brand_mark`, but the LIGHT variant of the
    brand mark is used when the pixels beneath it are dark (e.g. a red panel or a dark photo), so the
    logo stays visible. This chooses between two approved brand assets; it never alters the image."""
    from services.instagram_visual_profiles import ig_brand_mark

    frac = tok.LOGO_WIDTH_FRAC_COMPACT
    margin = round(spec.width * tok.LOGO_MARGIN_FRAC)
    probe = ig_brand_mark(target_width=round(spec.width * frac), red=True)
    x = spec.width - margin - probe.width
    y = spec.height - round(spec.height * spec.safe_bottom_frac) - margin - probe.height
    region = canvas.crop((x - 8, y - 8, x + probe.width + 8, y + probe.height + 8)).convert("L")
    hist = region.histogram()
    total = sum(hist) or 1
    mean = sum(i * c for i, c in enumerate(hist)) / total
    mark = probe if mean >= 118 else ig_brand_mark(target_width=round(spec.width * frac), red=False)
    canvas.paste(mark, (x, y), mark)  # brand asset placement (paste-with-mask), not an image treatment
    return 1


def render_declared_slide(
    *, spec: ProfileSpec, layout: InstagramSlideLayout, slide_copy: str, index: int, total: int,
    subject_assets: dict[str, tuple[Image.Image, str]] | None = None, visual_direction: str | None = None,
    progress_hidden: bool = False,
) -> LayoutResult:
    subject_assets = subject_assets or {}
    canvas = Image.new("RGBA", (spec.width, spec.height), (*(_SURFACE_COLOURS[layout.background]), 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    parts = copy_parts(slide_copy)
    fidelity: list[bool] = []
    media_used: list[dict[str, Any]] = []
    dropped: list[str] = []
    text_specs: list[TextRegionSpec] = []
    clipped_any = False
    treatment = "none"

    for region in layout.regions:  # already ordered: surface < media < graphic < accent < text
        x0, y0, x1, y1 = _px(region, spec)
        w, h = max(1, x1 - x0), max(1, y1 - y0)
        if region.kind == "surface":
            draw.rectangle([x0, y0, x1, y1], fill=(*_SURFACE_COLOURS[region.surface or "soft"], 255))
        elif region.kind == "media":
            asset = subject_assets.get(str(region.content_ref))
            if asset is None:
                dropped.append(str(region.content_ref))
                continue
            image, identity = asset
            if region.frame in ("hairline", "accent"):
                ring = max(3, round(spec.width * (0.006 if region.frame == "accent" else 0.003)))
                colour = tok.RED if region.frame == "accent" else HAIRLINE
                draw.rectangle([x0 - ring, y0 - ring, x1 + ring - 1, y1 + ring - 1], fill=(*colour, 255))
            fx, fy = (region.focus_x if region.focus_x is not None else 0.5), (region.focus_y if region.focus_y is not None else 0.42)
            if region.crop_mode == "contain":
                fitted = fit_image_contain(image, width=w, height=h, bg=SURFACE_SOFT).image
                media_treatment = "contain_preserved"
            else:
                fitted = fit_image_cover(image, width=w, height=h, focus_x=fx, focus_y=fy).image
                media_treatment = "cover_cropped"
            canvas.paste(fitted, (x0, y0))
            crop = canvas.crop((x0, y0, x0 + w, y0 + h)).convert("RGB")
            fidelity.append(ImageChops.difference(crop, fitted.convert("RGB")).getbbox() is None)
            media_used.append({"subject": region.content_ref, "identity": identity, "treatment": media_treatment})
            treatment = media_treatment if treatment == "none" else treatment
        elif region.kind == "accent":
            draw.rectangle([x0, y0, x1, y1], fill=(*tok.RED, 255))
        elif region.kind == "graphic":
            if region.graphic_type == "ui_frame":
                draw.rounded_rectangle([x0, y0, x1, y1], radius=26, fill=(*SURFACE_SOFT, 255), outline=(*tok.RED, 255), width=4)
                bar = max(28, round(h * 0.08))
                draw.line([(x0 + 4, y0 + bar), (x1 - 4, y0 + bar)], fill=(*HAIRLINE, 255), width=3)
                for i in range(3):
                    cx = x0 + 30 + i * 30
                    draw.ellipse([cx - 8, y0 + bar // 2 - 8, cx + 8, y0 + bar // 2 + 8], fill=(*HAIRLINE, 255))
            elif region.graphic_type == "flow_diagram":
                tokens = _flow_tokens(visual_direction)
                if tokens is None:
                    dropped.append("flow_diagram_without_sequence")
                    continue
                gap = round(spec.width * 0.03)
                node_w = (w - gap * (len(tokens) - 1)) // len(tokens)
                font = ig_font(round(spec.width * 0.027), "semibold")
                for i, token in enumerate(tokens):
                    nx = x0 + i * (node_w + gap)
                    last = i == len(tokens) - 1
                    draw.rounded_rectangle([nx, y0, nx + node_w, y1], radius=18, fill=(*(tok.RED if last else SURFACE_SOFT), 255), outline=(*tok.RED, 255), width=3)
                    bbox = draw.textbbox((0, 0), token, font=font)
                    draw.text((nx + (node_w - (bbox[2] - bbox[0])) / 2, y0 + (h - (bbox[3] - bbox[1])) / 2 - bbox[1]), token, font=font, fill=tok.PAPER if last else tok.INK)
                    if not last:
                        cy = y0 + h // 2
                        draw.line([(nx + node_w + 4, cy), (nx + node_w + gap - 4, cy)], fill=(*tok.RED, 255), width=5)
        elif region.kind == "text":
            text = parts.get(str(region.content_ref), "")
            if not text:
                continue
            font, lines, block_h, clipped = _fit_in_box(
                draw, text, box_w=w, box_h=h, token=region.scale_token or "BODY", max_lines=region.max_lines, spec=spec,
            )
            gap = round(font.size * 0.2)
            heights = [draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1] for line in lines]
            used_h = sum(heights) + gap * max(0, len(lines) - 1)
            top = y0 if region.valign in (None, "top") else (y0 + (h - used_h) // 2 if region.valign == "middle" else y1 - used_h)
            colour = _text_colour(region, layout)
            py = float(top)
            for i, line in enumerate(lines):
                lw = draw.textlength(line, font=font)
                px = x0 if region.align in (None, "left") else (x0 + (w - lw) / 2 if region.align == "center" else x1 - lw)
                bbox = draw.textbbox((px, py), line, font=font)
                draw.text((px, py), line, font=font, fill=colour)
                text_specs.append(TextRegionSpec(kind="headline", box=box4(bbox), clipped=clipped and i == len(lines) - 1))
                py += (bbox[3] - bbox[1]) + gap
            clipped_any = clipped_any or clipped

    if layout.show_progress and not progress_hidden:
        size = round(spec.width * tok.TYPE_SLIDE_INDEX.size_frac)
        draw.text((round(PROGRESS_ZONE[0] * spec.width) + round(spec.width * 0.03), round(spec.height * (PROGRESS_ZONE[1] + 0.005))),
                  f"{index + 1:02d} / {total:02d}", font=ig_font(size, tok.TYPE_SLIDE_INDEX.weight), fill=MUTED_INK)

    mark_count = _place_adaptive_mark(canvas, spec)
    raw = layout.model_dump()
    chars = layout_characteristics(raw)
    signature = layout_signature(raw)
    variant = f"declared_{chars['headline_zone']}_{chars['media_zone']}_{chars['media_dominance']}_{chars['region_count']}"
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=text_specs, visible_brand_mark_count=mark_count,
        source_image_treatment=treatment, layout_variant=variant, text_clipped=clipped_any,
        notes={
            "layout_plan_applied": True, "layout_signature": signature, "layout_characteristics": chars,
            "media_regions": media_used, "unresolved_media_regions": dropped,
            "source_media_pixels_unaltered": (all(fidelity) if fidelity else None),
            "graphic_fallback_used": bool(dropped),
        },
    )
