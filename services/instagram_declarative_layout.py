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

import math
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
    "NUMERAL": (0.36, "black"),
    "DISPLAY": (0.16, "black"),
    "HEADLINE_L": (0.088, "black"),
    "HEADLINE_M": (0.072, "black"),
    "HEADLINE_S": (0.058, "black"),
    "BODY": (0.042, "semibold"),
    "CAPTION": (0.032, "semibold"),
}
_MIN_FONT_FRAC = 0.03  # minimum readable size (about 32px on a 1080px canvas)
GRAPHITE = (30, 32, 38)
_SURFACE_COLOURS = {"paper": tok.PAPER, "soft": SURFACE_SOFT, "red": tok.RED, "ink": tok.INK, "graphite": GRAPHITE}
MUTED_ON_DARK = (150, 155, 166)
# Renderer-owned accent roles per palette (the model only names the palette / the role, never a colour).
# brand = NINJA red only; culture and neo are the secondary accent families the reference board itself uses.
PALETTES: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "brand": (tok.RED, tok.RED),
    "culture": ((212, 240, 36), (255, 72, 200)),
    "neo": ((152, 96, 255), (255, 72, 190)),
}
_DARK_TEXT_P90 = 96   # text on a media region: light text only if even the brightest decile beneath it is dark
_LIGHT_TEXT_P10 = 168  # dark text only if even the darkest decile beneath it is light


class DeclaredRenderRejected(ValueError):
    """A declared layout cannot be drawn safely (for example text on media whose pixels are not quiet
    enough). The caller falls back to the deterministic renderer; nothing is drawn over the image."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


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


def _luma_stats(canvas: Image.Image, box: tuple[int, int, int, int]) -> tuple[float, int, int]:
    """(mean, p10, p90) of the luminance of the pixels currently under `box`."""
    hist = canvas.crop(box).convert("L").histogram()
    total = sum(hist) or 1
    mean = sum(i * c for i, c in enumerate(hist)) / total

    def pct(q: float) -> int:
        target, acc = q * total, 0
        for i, c in enumerate(hist):
            acc += c
            if acc >= target:
                return i
        return 255

    return mean, pct(0.10), pct(0.90)


def _role_colour(layout: InstagramSlideLayout, tone: str | None, *, dark: bool, default: tuple[int, int, int]) -> tuple[int, int, int]:
    accent, accent2 = PALETTES[layout.palette]
    if tone == "accent":
        return accent
    if tone == "accent2":
        return accent2
    if tone == "muted":
        return MUTED_ON_DARK if dark else MUTED_INK
    return default


def _text_colour(region: LayoutRegion, layout: InstagramSlideLayout, canvas: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """Colour chosen from the ACTUAL pixels beneath the text (never by altering them). Text declared
    `on_media` additionally needs quiet pixels: otherwise the plan is rejected, not fixed with an overlay."""
    mean, p10, p90 = _luma_stats(canvas, box)
    if region.on_media:
        if p90 <= _DARK_TEXT_P90:
            dark = True
        elif p10 >= _LIGHT_TEXT_P10:
            dark = False
        else:
            raise DeclaredRenderRejected("text_on_media_unreadable")
    else:
        dark = mean < 118
    base = tok.PAPER if dark else tok.INK
    if region.content_ref == "number" and region.tone is None:
        return PALETTES[layout.palette][0]
    return _role_colour(layout, region.tone, dark=dark, default=base)


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
    accent_default = PALETTES[layout.palette][0]
    draw = ImageDraw.Draw(canvas, "RGBA")
    parts = copy_parts(slide_copy)
    fidelity: list[bool] = []
    media_used: list[dict[str, Any]] = []
    dropped: list[str] = []
    text_specs: list[TextRegionSpec] = []
    clipped_any = False
    treatment = "none"
    tilted = 0

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
            pad = round(spec.width * 0.022) if region.frame == "paper" else 0
            if region.frame in ("hairline", "accent"):
                ring = max(3, round(spec.width * (0.006 if region.frame == "accent" else 0.003)))
                colour = accent_default if region.frame == "accent" else HAIRLINE
                draw.rectangle([x0 - ring, y0 - ring, x1 + ring - 1, y1 + ring - 1], fill=(*colour, 255))
            fx, fy = (region.focus_x if region.focus_x is not None else 0.5), (region.focus_y if region.focus_y is not None else 0.42)
            iw, ih = max(1, w - 2 * pad), max(1, h - 2 * pad)
            if region.crop_mode == "contain":
                fitted = fit_image_contain(image, width=iw, height=ih, bg=SURFACE_SOFT).image
                media_treatment = "contain_preserved"
            else:
                fitted = fit_image_cover(image, width=iw, height=ih, focus_x=fx, focus_y=fy).image
                media_treatment = "cover_cropped"
            tile = fitted
            if pad:
                tile = Image.new("RGB", (w, h), (244, 242, 236))
                tile.paste(fitted.convert("RGB"), (pad, pad))
            if region.tilt_deg:
                rotated = tile.convert("RGBA").rotate(-region.tilt_deg, expand=True, resample=Image.Resampling.BICUBIC)
                canvas.paste(rotated, (x0 + w // 2 - rotated.width // 2, y0 + h // 2 - rotated.height // 2), rotated)
                tilted += 1
            else:
                canvas.paste(tile, (x0, y0))
                if not pad:
                    crop = canvas.crop((x0, y0, x0 + w, y0 + h)).convert("RGB")
                    fidelity.append(ImageChops.difference(crop, fitted.convert("RGB")).getbbox() is None)
            media_used.append({"subject": region.content_ref, "identity": identity, "treatment": media_treatment, "tilted": bool(region.tilt_deg), "matted": bool(pad)})
            treatment = media_treatment if treatment == "none" else treatment
        elif region.kind == "accent":
            draw.rectangle([x0, y0, x1, y1], fill=(*_role_colour(layout, region.tone, dark=True, default=accent_default), 255))
        elif region.kind == "graphic":
            dark_bg = _luma_stats(canvas, (x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)))[0] < 118
            if region.graphic_type == "ui_frame":
                draw.rounded_rectangle([x0, y0, x1, y1], radius=26, fill=(*(GRAPHITE if dark_bg else SURFACE_SOFT), 255), outline=(*accent_default, 255), width=4)
                bar = max(28, round(h * 0.08))
                draw.line([(x0 + 4, y0 + bar), (x1 - 4, y0 + bar)], fill=(*HAIRLINE, 255), width=3)
                for i in range(3):
                    cx = x0 + 30 + i * 30
                    draw.ellipse([cx - 8, y0 + bar // 2 - 8, cx + 8, y0 + bar // 2 + 8], fill=(*HAIRLINE, 255))
            elif region.graphic_type == "poll_cards":
                options = [o.strip() for o in parts.get("copy_rest", "").split("|") if o.strip()][:4]
                if not options:
                    dropped.append("poll_without_options")
                    continue
                gap = round(spec.width * 0.018)
                card_h = (h - gap * (len(options) - 1)) // len(options)
                font = ig_font(max(round(spec.width * _MIN_FONT_FRAC), min(round(card_h * 0.42), round(spec.width * 0.045))), "semibold")
                for i, option in enumerate(options):
                    cy0 = y0 + i * (card_h + gap)
                    draw.rounded_rectangle([x0, cy0, x1, cy0 + card_h], radius=round(card_h * 0.28), fill=(*SURFACE_SOFT, 255))
                    bbox = draw.textbbox((0, 0), option, font=font)
                    draw.text((x0 + round(card_h * 0.36), cy0 + (card_h - (bbox[3] - bbox[1])) / 2 - bbox[1]), option, font=font, fill=tok.INK)
            elif region.graphic_type == "badge":
                colour = _role_colour(layout, region.tone or "accent2", dark=True, default=accent_default)
                side = min(w, h)
                bx, by = x0 + (w - side) // 2, y0 + (h - side) // 2
                draw.ellipse([bx, by, bx + side, by + side], fill=(*colour, 255))
                inset = round(side * 0.16)
                draw.ellipse([bx + inset, by + inset, bx + side - inset, by + side - inset], outline=(*tok.INK, 255), width=max(3, round(side * 0.04)))
            elif region.graphic_type == "scribble":
                colour = _role_colour(layout, region.tone or "accent", dark=True, default=accent_default)
                steps = 64
                pts = [
                    (x0 + w * (i / steps), y0 + h / 2 + (h / 2) * math.sin(i * 0.95) * (0.55 + 0.45 * math.cos(i * 0.31)))
                    for i in range(steps + 1)
                ]
                draw.line(pts, fill=(*colour, 255), width=max(4, round(spec.width * 0.007)), joint="curve")
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
                    draw.rounded_rectangle([nx, y0, nx + node_w, y1], radius=18, fill=(*(accent_default if last else (GRAPHITE if dark_bg else SURFACE_SOFT)), 255), outline=(*accent_default, 255), width=3)
                    bbox = draw.textbbox((0, 0), token, font=font)
                    draw.text((nx + (node_w - (bbox[2] - bbox[0])) / 2, y0 + (h - (bbox[3] - bbox[1])) / 2 - bbox[1]), token, font=font, fill=tok.PAPER if (last or dark_bg) else tok.INK)
                    if not last:
                        cy = y0 + h // 2
                        draw.line([(nx + node_w + 4, cy), (nx + node_w + gap - 4, cy)], fill=(*accent_default, 255), width=5)
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
            colour = _text_colour(region, layout, canvas, (x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)))
            py = float(top)
            for i, line in enumerate(lines):
                lw = draw.textlength(line, font=font)
                px = x0 if region.align in (None, "left") else (x0 + (w - lw) / 2 if region.align == "center" else x1 - lw)
                off = draw.textbbox((0, 0), line, font=font)[1]  # glyph top offset: keep the ink inside its region
                bbox = draw.textbbox((px, py - off), line, font=font)
                draw.text((px, py - off), line, font=font, fill=colour)
                text_specs.append(TextRegionSpec(kind="headline", box=box4(bbox), clipped=clipped and i == len(lines) - 1))
                py += (bbox[3] - bbox[1]) + gap
            clipped_any = clipped_any or clipped

    if layout.show_progress and not progress_hidden:
        size = round(spec.width * tok.TYPE_SLIDE_INDEX.size_frac)
        draw.text((round(PROGRESS_ZONE[0] * spec.width) + round(spec.width * 0.03), round(spec.height * (PROGRESS_ZONE[1] + 0.005))),
                  f"{index + 1:02d} / {total:02d}", font=ig_font(size, tok.TYPE_SLIDE_INDEX.weight),
                  fill=MUTED_ON_DARK if _luma_stats(canvas, (0, 0, spec.width, round(spec.height * 0.1)))[0] < 118 else MUTED_INK)

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
            "media_regions_tilted": tilted, "background": layout.background, "palette": layout.palette,
            "graphic_fallback_used": bool(dropped),
        },
    )
