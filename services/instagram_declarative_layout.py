"""Phase B.5: the SAFE renderer for a validated DECLARATIVE slide layout (extended in B.5R / B.5R.1).

The Creative Director supplies composition relationships in normalized 0..1 canvas space. This
module owns everything brand-specific: the type family, the pixel size behind each scale token,
the colours (paper / soft / NINJA red / ink / palettes), the logo, margins and the progress marker.
There is no path for the model to introduce a font, a colour, a pixel size, code, CSS or SVG.

Guarantees (all deterministic - identical layout + copy + assets => identical pixels, no RNG):
  * NO overlay of any kind: source media is only cropped / scaled / (bounded) rotated into its own
    region; the evidence records `overlay_operations_executed=0` and whether each media region's
    pixels were left untouched right after placement;
  * text sits on a photograph ONLY when declared `on_media` and the pixels beneath it pass the
    deterministic quiet-zone measurement (services/instagram_quiet_zones.py); otherwise the plan is
    rejected - it is never rescued with a translucent layer;
  * a media region whose subject has no resolved asset is not drawn (never an unrelated image);
  * text that cannot fit at the minimum readable size is reported as clipped (fail closed).

Allowed media transforms (documented for the fidelity review): crop, uniform scale, translate,
alpha-composite of a real transparent cutout, and (collage fragments only) a bounded rotation with an
optional flat paper-white mat. Colour, brightness, blur and gradients are never applied to a source."""
from __future__ import annotations

import math
from typing import Any

from PIL import Image, ImageChops, ImageDraw

from schemas.instagram_creative import InstagramSlideLayout, LayoutRegion
from services import instagram_design_tokens as tok
from services.instagram_editorial_layouts import LayoutResult, TextRegionSpec
from services.instagram_image_handling import fit_image_contain, fit_image_cover
from services.instagram_layout_signature import layout_characteristics, layout_signature
from services.instagram_layout_validation import PROGRESS_ZONE, copy_parts
from services.instagram_quiet_zones import measure_zone
from services.instagram_text_fit import box4
from services.instagram_visual_profiles import ProfileSpec, ig_font

SURFACE_SOFT = (233, 236, 241)
MUTED_INK = (96, 101, 110)
HAIRLINE = (208, 212, 219)

# scale token -> (max font as a fraction of canvas width, font weight). Renderer-owned metrics.
SCALE_TOKENS: dict[str, tuple[float, str]] = {
    "MEGA": (0.24, "black"),
    "NUMERAL": (0.36, "black"),
    "DISPLAY": (0.16, "black"),
    "HEADLINE_XL": (0.125, "black"),
    "HEADLINE_L": (0.088, "black"),
    "HEADLINE_M": (0.072, "black"),
    "HEADLINE_S": (0.058, "black"),
    "BODY": (0.042, "semibold"),
    "CAPTION": (0.032, "semibold"),
}
_LEADING = {"MEGA": 0.06, "NUMERAL": 0.06, "DISPLAY": 0.07, "HEADLINE_XL": 0.07, "HEADLINE_L": 0.08, "HEADLINE_M": 0.12, "HEADLINE_S": 0.14}
_MIN_FONT_FRAC = 0.03  # minimum readable size (about 32px on a 1080px canvas)
GRAPHITE = (30, 32, 38)
_SURFACE_COLOURS = {"paper": tok.PAPER, "soft": SURFACE_SOFT, "red": tok.RED, "ink": tok.INK, "graphite": GRAPHITE}
MUTED_ON_DARK = (150, 155, 166)
MAX_GROUND_STD = 12.0  # a `media_ground` surface needs an asset whose border is genuinely uniform
# Renderer-owned accent roles per palette (the model only names the palette / the role, never a colour).
# brand = NINJA red only; culture and neo are the secondary accent families Visual DNA v2 permits.
PALETTES: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "brand": (tok.RED, tok.RED),
    "culture": ((212, 240, 36), (255, 72, 200)),
    "neo": ((152, 96, 255), (255, 72, 190)),
}


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


def _leading(size: int, token: str) -> int:
    return round(size * _LEADING.get(token, 0.2))


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
        gap = _leading(size, token)
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


def _text_colour(
    region: LayoutRegion, layout: InstagramSlideLayout, canvas: Image.Image, box: tuple[int, int, int, int], reports: list[dict],
) -> tuple[int, int, int]:
    """Colour chosen from the ACTUAL pixels beneath the text (never by altering them). Text declared
    `on_media` must sit on a quiet zone by the shared measurement, otherwise the plan is rejected."""
    if region.on_media:
        measure = measure_zone(canvas, box, name=str(region.content_ref))
        reports.append({"ref": region.content_ref, **measure.as_dict()})
        if not measure.quiet:
            raise DeclaredRenderRejected("text_on_media_unreadable")
        dark = measure.text_colour == "light"
    else:
        dark = _luma_stats(canvas, box)[0] < 118
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


def ground_of(image: Image.Image) -> tuple[tuple[int, int, int], float]:
    """(median border colour, luminance std of the border ring): how 'isolated' the asset's ground is."""
    small = image.convert("RGB").resize((64, 64), Image.Resampling.BOX)
    px = small.load()
    ring = [px[x, y] for x in range(64) for y in range(64) if x in (0, 1, 62, 63) or y in (0, 1, 62, 63)]
    med = tuple(sorted(c[i] for c in ring)[len(ring) // 2] for i in range(3))
    lumas = [(0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) for c in ring]
    mean = sum(lumas) / len(lumas)
    return med, (sum((v - mean) ** 2 for v in lumas) / len(lumas)) ** 0.5  # type: ignore[return-value]


def _surface_colour(layout: InstagramSlideLayout, region: LayoutRegion, subject_assets: dict) -> tuple[int, int, int] | None:
    s = region.surface or "soft"
    if s == "accent":
        return PALETTES[layout.palette][0]
    if s == "accent2":
        return PALETTES[layout.palette][1]
    if s == "media_ground":
        asset = subject_assets.get(str(region.content_ref))
        if asset is None:
            return None
        colour, std = ground_of(asset[0])
        if std > MAX_GROUND_STD:
            raise DeclaredRenderRejected("media_ground_not_uniform")
        return colour
    return _SURFACE_COLOURS[s]


def _fit_cutout(image: Image.Image, width: int, height: int, fx: float, fy: float, *, contain: bool) -> Image.Image:
    """Scale a real (transparent or isolated) object uniformly; cover crops it at the region edges (bleed),
    contain keeps it whole. `fx`/`fy` align it (0 = left/top, 1 = right/bottom). Pixels are not recoloured."""
    rgba = image.convert("RGBA")
    scale = min(width / rgba.width, height / rgba.height) if contain else max(width / rgba.width, height / rgba.height)
    nw, nh = max(1, round(rgba.width * scale)), max(1, round(rgba.height * scale))
    resized = rgba.resize((nw, nh), Image.Resampling.LANCZOS)
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    layer.paste(resized, (round((width - nw) * fx), round((height - nh) * fy)))
    return layer


def _object_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    """Bounding box of the OBJECT inside its photo: the alpha coverage of a real cutout, otherwise whatever differs from a
    uniform ground; the whole image when there is no uniform ground (a scene, not an isolated object)."""
    full = (0, 0, image.width, image.height)
    if image.mode == "RGBA" and image.getchannel("A").getextrema()[0] < 250:
        return image.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox() or full
    ground, std = ground_of(image)
    if std > 10.0:
        return full
    diff = ImageChops.difference(image.convert("RGB"), Image.new("RGB", image.size, ground)).convert("L")
    return diff.point(lambda v: 255 if v > 8 else 0).getbbox() or full


def _fit_object(image: Image.Image, width: int, height: int, fx: float, fy: float, *, contain: bool):
    """Stage an object by ITS extent: scale so the object's bounding box fits (contain) or covers (cover, cropping it at the
    region edge) the region, aligned by fx/fy. Crop / uniform scale / translate only - pixels are never recoloured. Returns
    (RGBA layer of the region, object box in region coordinates)."""
    rgba = image.convert("RGBA")
    bx0, by0, bx1, by1 = _object_bbox(rgba)
    bw, bh = max(1, bx1 - bx0), max(1, by1 - by0)
    scale = min(width / bw, height / bh) if contain else max(width / bw, height / bh)
    resized = rgba.resize((max(1, round(rgba.width * scale)), max(1, round(rgba.height * scale))), Image.Resampling.LANCZOS)
    ox = round((width - bw * scale) * fx - bx0 * scale)
    oy = round((height - bh * scale) * fy - by0 * scale)
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    layer.paste(resized, (ox, oy))
    return layer, (round(bx0 * scale + ox), round(by0 * scale + oy), round(bx1 * scale + ox), round(by1 * scale + oy))


def _torn_mask(w: int, h: int, amp: int) -> Image.Image:
    """A deterministic jagged 'torn paper' outline (no RNG): an inset rectangle whose edge is displaced by a fixed
    function of the position along the edge."""
    pts: list[tuple[float, float]] = []
    step = max(10, round(min(w, h) / 22))

    def jit(i: int) -> float:
        return amp * (0.55 + 0.45 * math.sin(i * 1.9) * math.cos(i * 0.61))

    for i, x in enumerate(range(0, w, step)):
        pts.append((x, jit(i)))
    for i, y in enumerate(range(0, h, step)):
        pts.append((w - jit(i + 7), y))
    for i, x in enumerate(range(w, 0, -step)):
        pts.append((x, h - jit(i + 13)))
    for i, y in enumerate(range(h, 0, -step)):
        pts.append((jit(i + 3), y))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    return mask


def _die_cut_outline(alpha: Image.Image, radius: int) -> Image.Image:
    """Dilate a real alpha mask by `radius` px (offsets on two rings, no filters): the white sticker outline of a die-cut cutout."""
    out = alpha.point(lambda a: 255 if a > 16 else 0)
    base = out.copy()
    for r in (radius, round(radius * 0.6)):
        for k in range(16):
            dx, dy = round(r * math.cos(2 * math.pi * k / 16)), round(r * math.sin(2 * math.pi * k / 16))
            shifted = Image.new("L", alpha.size, 0)
            shifted.paste(base, (dx, dy))
            out = ImageChops.lighter(out, shifted)
    return out


def _object_extent(tile: Image.Image) -> tuple[int, tuple[int, int, int, int]]:
    """(object pixel count, object bounding box in tile coordinates). The object is the alpha coverage of a real
    cutout, otherwise whatever differs from a uniform ground. A DIAGNOSTIC only (object dominance), never a gate;
    the bounding box is reported because a light object on a light ground barely differs pixel-by-pixel."""
    full = (0, 0, tile.width, tile.height)
    if tile.mode == "RGBA":
        alpha = tile.split()[3]
        if alpha.getextrema()[0] < 250:
            mask = alpha.point(lambda a: 255 if a > 16 else 0)
            return mask.histogram()[255], (mask.getbbox() or full)
    ground, std = ground_of(tile)
    if std > 10.0:
        return tile.width * tile.height, full
    diff = ImageChops.difference(tile.convert("RGB"), Image.new("RGB", tile.size, ground)).convert("L")
    strong = diff.point(lambda v: 255 if v > 28 else 0).histogram()[255]
    box = diff.point(lambda v: 255 if v > 8 else 0).getbbox()
    return strong, (box or full)


def _place_adaptive_mark(canvas: Image.Image, spec: ProfileSpec, position: str) -> int:
    """The canonical brand mark at a bounded, renderer-owned corner (BOTTOM_RIGHT default, BOTTOM_LEFT).
    The LIGHT approved variant is used when the pixels beneath it are dark. It chooses between two approved
    brand assets; it never alters the image and never draws a new mark."""
    from services.instagram_visual_profiles import ig_brand_mark

    frac = tok.LOGO_WIDTH_FRAC_COMPACT
    margin = round(spec.width * tok.LOGO_MARGIN_FRAC)
    probe = ig_brand_mark(target_width=round(spec.width * frac), red=True)
    x = margin if position == "BOTTOM_LEFT" else spec.width - margin - probe.width
    y = spec.height - round(spec.height * spec.safe_bottom_frac) - margin - probe.height
    region = canvas.crop((x - 8, y - 8, x + probe.width + 8, y + probe.height + 8)).convert("L")
    hist = region.histogram()
    total = sum(hist) or 1
    mean = sum(i * c for i, c in enumerate(hist)) / total
    mark = probe if mean >= 118 else ig_brand_mark(target_width=round(spec.width * frac), red=False)
    canvas.paste(mark, (x, y), mark)  # brand asset placement (paste-with-mask), not an image treatment
    return 1


def _scribble_points(kind: str, x0: int, y0: int, w: int, h: int) -> list[tuple[float, float]]:
    steps = 72
    if kind == "arrow_scribble":
        pts = []
        for i in range(steps + 1):
            t = i / steps
            pts.append((x0 + w * t, y0 + h * (1 - t) - h * 0.28 * math.sin(math.pi * t) + h * 0.03 * math.sin(t * 23)))
        return pts
    if kind == "circle_scribble":
        cx, cy = x0 + w / 2, y0 + h / 2
        pts = []
        for i in range(int(steps * 1.15) + 1):
            th = 2 * math.pi * 1.12 * (i / (steps * 1.15)) + 0.35
            grow = 1 + 0.06 * (i / steps) + 0.03 * math.sin(3 * th)
            pts.append((cx + (w / 2) * math.cos(th) * grow, cy + (h / 2) * math.sin(th) * grow))
        return pts
    return [
        (x0 + w * (i / steps), y0 + h / 2 + (h / 2) * math.sin(i * 0.95) * (0.55 + 0.45 * math.cos(i * 0.31)))
        for i in range(steps + 1)
    ]


def render_declared_slide(
    *, spec: ProfileSpec, layout: InstagramSlideLayout, slide_copy: str, index: int, total: int,
    subject_assets: dict[str, tuple[Image.Image, str]] | None = None, visual_direction: str | None = None,
    progress_hidden: bool = False,
) -> LayoutResult:
    subject_assets = subject_assets or {}
    W, H = spec.width, spec.height
    canvas = Image.new("RGBA", (W, H), (*(_SURFACE_COLOURS[layout.background]), 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    accent_default = PALETTES[layout.palette][0]
    parts = copy_parts(slide_copy)
    fidelity: list[bool] = []
    media_used: list[dict[str, Any]] = []
    dropped: list[str] = []
    text_specs: list[TextRegionSpec] = []
    text_metrics: list[dict[str, Any]] = []
    zone_reports: list[dict[str, Any]] = []
    clipped_any = False
    treatment = "none"
    rotations = layers = object_px = object_bbox_px = 0
    object_boxes: list[list[float]] = []
    media_mask, text_mask, content_mask = (Image.new("L", (W, H), 0) for _ in range(3))
    pad_px = round(W * 0.01)

    for region in layout.regions:  # already ordered by the validator
        x0, y0, x1, y1 = _px(region, spec)
        w, h = max(1, x1 - x0), max(1, y1 - y0)
        if region.kind == "surface":
            colour = _surface_colour(layout, region, subject_assets)
            if colour is None:
                dropped.append(str(region.content_ref))
                continue
            if region.tilt_deg:
                layer = Image.new("RGBA", (w, h), (*colour, 255)).rotate(-region.tilt_deg, expand=True, resample=Image.Resampling.BICUBIC)
                canvas.paste(layer, (x0 + w // 2 - layer.width // 2, y0 + h // 2 - layer.height // 2), layer)
                rotations += 1
            else:
                draw.rectangle([x0, y0, x1, y1], fill=(*colour, 255))
            layers += 1
        elif region.kind == "media":
            asset = subject_assets.get(str(region.content_ref))
            if asset is None:
                dropped.append(str(region.content_ref))
                continue
            image, identity = asset
            pad = round(W * {"paper": 0.022, "torn": 0.030, "die_cut": 0.011}.get(region.frame or "", 0))
            if region.frame in ("hairline", "accent"):
                ring = max(3, round(W * (0.006 if region.frame == "accent" else 0.003)))
                colour = accent_default if region.frame == "accent" else HAIRLINE
                draw.rectangle([x0 - ring, y0 - ring, x1 + ring - 1, y1 + ring - 1], fill=(*colour, 255))
            fx, fy = (region.focus_x if region.focus_x is not None else 0.5), (region.focus_y if region.focus_y is not None else 0.42)
            iw, ih = max(1, w - 2 * pad), max(1, h - 2 * pad)
            mode = region.crop_mode or "cover"
            object_box = None
            if mode in ("object_contain", "object_cover"):
                tile, object_box = _fit_object(image, iw, ih, fx, fy, contain=mode == "object_contain")
                media_treatment = "object_contained" if mode == "object_contain" else "object_cover_cropped"
            elif mode in ("cutout", "cutout_contain"):
                tile = _fit_cutout(image, iw, ih, fx, fy, contain=mode == "cutout_contain")
                media_treatment = "cutout_contained" if mode == "cutout_contain" else "cutout_cover"
            elif mode == "contain":
                bg = canvas.getpixel((min(W - 1, max(0, x0 + 2)), min(H - 1, max(0, y0 + 2))))[:3]
                tile = fit_image_contain(image, width=iw, height=ih, bg=bg).image
                media_treatment = "contain_preserved"
            else:
                tile = fit_image_cover(image, width=iw, height=ih, focus_x=fx, focus_y=fy).image
                media_treatment = "cover_cropped"
            if object_box is not None:
                ox0_, oy0_, ox1_, oy1_ = (object_box[0] + pad, object_box[1] + pad, object_box[2] + pad, object_box[3] + pad)
                px_count = max(0, ox1_ - ox0_) * max(0, oy1_ - oy0_)
            else:
                px_count, (ox0_, oy0_, ox1_, oy1_) = _object_extent(tile)
                ox0_, oy0_, ox1_, oy1_ = ox0_ + pad, oy0_ + pad, ox1_ + pad, oy1_ + pad
            object_px += px_count
            cx0, cy0, cx1, cy1 = max(0, x0 + ox0_), max(0, y0 + oy0_), min(W, x0 + ox1_), min(H, y0 + oy1_)
            object_bbox_px += max(0, cx1 - cx0) * max(0, cy1 - cy0)
            if cx1 > cx0 and cy1 > cy0:
                object_boxes.append([round(cx0 / W, 3), round(cy0 / H, 3), round(cx1 / W, 3), round(cy1 / H, 3)])
            if region.frame == "die_cut" and tile.mode == "RGBA" and tile.getchannel("A").getextrema()[0] < 250:
                inset = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                inset.paste(tile, (pad, pad))
                ring = Image.new("RGBA", (w, h), (244, 242, 236, 255))
                base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                base.paste(ring, (0, 0), _die_cut_outline(inset.getchannel("A"), max(3, pad)))
                base.paste(inset, (0, 0), inset)
                tile = base
            elif pad:
                matted = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                paper = Image.new("RGBA", (w, h), (244, 242, 236, 255))
                matted.paste(paper, (0, 0), _torn_mask(w, h, max(4, pad)) if region.frame == "torn" else None)
                matted.paste(tile.convert("RGB"), (pad, pad))
                tile = matted
            if region.tilt_deg:
                rotated = tile.convert("RGBA").rotate(-region.tilt_deg, expand=True, resample=Image.Resampling.BICUBIC)
                canvas.paste(rotated, (x0 + w // 2 - rotated.width // 2, y0 + h // 2 - rotated.height // 2), rotated)
                rotations += 1
            else:
                if tile.mode == "RGBA":
                    canvas.paste(tile, (x0, y0), tile)
                else:
                    canvas.paste(tile, (x0, y0))
                if not pad:
                    ox0, oy0, ox1, oy1 = max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h)
                    if ox1 > ox0 and oy1 > oy0:
                        crop = canvas.crop((ox0, oy0, ox1, oy1)).convert("RGB")
                        ref = tile.crop((ox0 - x0, oy0 - y0, ox1 - x0, oy1 - y0))
                        diff = ImageChops.difference(crop, ref.convert("RGB"))
                        if ref.mode == "RGBA":  # only fully opaque object pixels must be bit-identical
                            mask = ref.split()[3].point(lambda a: 255 if a == 255 else 0)
                            diff = Image.composite(diff, Image.new("RGB", diff.size, (0, 0, 0)), mask)
                        fidelity.append(diff.getbbox() is None)
            ImageDraw.Draw(media_mask).rectangle([x0, y0, x1, y1], fill=255)
            ImageDraw.Draw(content_mask).rectangle([x0, y0, x1, y1], fill=255)
            media_used.append({"subject": region.content_ref, "identity": identity, "treatment": media_treatment,
                               "tilted": bool(region.tilt_deg), "matted": bool(pad)})
            treatment = media_treatment if treatment == "none" else treatment
            layers += 1
        elif region.kind == "accent":
            draw.rectangle([x0, y0, x1, y1], fill=(*_role_colour(layout, region.tone, dark=True, default=accent_default), 255))
            ImageDraw.Draw(content_mask).rectangle([x0, y0, x1, y1], fill=255)
            layers += 1
        elif region.kind == "graphic":
            dark_bg = _luma_stats(canvas, (max(0, x0), max(0, y0), max(min(W, x1), x0 + 1), max(min(H, y1), y0 + 1)))[0] < 118
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
                gap = round(W * 0.018)
                card_h = (h - gap * (len(options) - 1)) // len(options)
                font = ig_font(max(round(W * _MIN_FONT_FRAC), min(round(card_h * 0.42), round(W * 0.045))), "semibold")
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
            elif region.graphic_type in ("highlight", "burst"):
                colour = _role_colour(layout, region.tone or ("accent" if region.graphic_type == "highlight" else "accent2"), dark=True, default=accent_default)
                shape = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                sd = ImageDraw.Draw(shape)
                if region.graphic_type == "highlight":
                    sd.rounded_rectangle([0, 0, w - 1, h - 1], radius=round(h * 0.18), fill=(*colour, 255))
                else:
                    r_out, cx_, cy_ = min(w, h) / 2, w / 2, h / 2
                    star = [(cx_ + (r_out if k % 2 == 0 else r_out * 0.76) * math.cos(math.pi * k / 14 - math.pi / 2),
                             cy_ + (r_out if k % 2 == 0 else r_out * 0.76) * math.sin(math.pi * k / 14 - math.pi / 2)) for k in range(28)]
                    sd.polygon(star, fill=(*colour, 255))
                if region.tilt_deg:
                    shape = shape.rotate(-region.tilt_deg, expand=True, resample=Image.Resampling.BICUBIC)
                    rotations += 1
                canvas.paste(shape, (x0 + w // 2 - shape.width // 2, y0 + h // 2 - shape.height // 2), shape)
            elif region.graphic_type in ("scribble", "arrow_scribble", "circle_scribble"):
                colour = _role_colour(layout, region.tone or "accent", dark=True, default=accent_default)
                pts = _scribble_points(region.graphic_type, x0, y0, w, h)
                width = max(4, round(W * 0.007))
                draw.line(pts, fill=(*colour, 255), width=width, joint="curve")
                if region.graphic_type == "arrow_scribble":
                    (ax, ay), (bx, by) = pts[-6], pts[-1]
                    ang = math.atan2(by - ay, bx - ax)
                    head = 0.24 * min(w, h)
                    for side in (-0.5, 0.5):
                        draw.line([(bx, by), (bx - head * math.cos(ang + side), by - head * math.sin(ang + side))], fill=(*colour, 255), width=width)
            elif region.graphic_type == "flow_diagram":
                tokens = _flow_tokens(visual_direction)
                if tokens is None:
                    dropped.append("flow_diagram_without_sequence")
                    continue
                gap = round(W * 0.03)
                node_w = (w - gap * (len(tokens) - 1)) // len(tokens)
                font = ig_font(round(W * 0.027), "semibold")
                for i, token in enumerate(tokens):
                    nx = x0 + i * (node_w + gap)
                    last = i == len(tokens) - 1
                    draw.rounded_rectangle([nx, y0, nx + node_w, y1], radius=18, fill=(*(accent_default if last else (GRAPHITE if dark_bg else SURFACE_SOFT)), 255), outline=(*accent_default, 255), width=3)
                    bbox = draw.textbbox((0, 0), token, font=font)
                    draw.text((nx + (node_w - (bbox[2] - bbox[0])) / 2, y0 + (h - (bbox[3] - bbox[1])) / 2 - bbox[1]), token, font=font, fill=tok.PAPER if (last or dark_bg) else tok.INK)
                    if not last:
                        cy = y0 + h // 2
                        draw.line([(nx + node_w + 4, cy), (nx + node_w + gap - 4, cy)], fill=(*accent_default, 255), width=5)
            ImageDraw.Draw(content_mask).rectangle([x0, y0, x1, y1], fill=255)
            layers += 1
        elif region.kind == "text":
            text = parts.get(str(region.content_ref), "")
            if not text:
                continue
            token = region.scale_token or "BODY"
            font, lines, block_h, clipped = _fit_in_box(draw, text, box_w=w, box_h=h, token=token, max_lines=region.max_lines, spec=spec)
            gap = _leading(font.size, token)
            heights = [draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1] for line in lines]
            used_h = sum(heights) + gap * max(0, len(lines) - 1)
            widths = [draw.textlength(line, font=font) for line in lines]
            block_w = max(widths)
            top = y0 if region.valign in (None, "top") else (y0 + (h - used_h) // 2 if region.valign == "middle" else y1 - used_h)
            left = x0 if region.align in (None, "left") else (x0 + (w - block_w) / 2 if region.align == "center" else x1 - block_w)
            tight = (round(left) - pad_px, round(top) - pad_px, round(left + block_w) + pad_px, round(top + used_h) + pad_px)
            colour = _text_colour(region, layout, canvas, (max(0, tight[0]), max(0, tight[1]), min(W, tight[2]), min(H, tight[3])), zone_reports)
            if region.tilt_deg:
                layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                ld = ImageDraw.Draw(layer)
                py = float(top - y0)
                for line, lw in zip(lines, widths):
                    px = 0.0 if region.align in (None, "left") else ((w - lw) / 2 if region.align == "center" else w - lw)
                    off = ld.textbbox((0, 0), line, font=font)[1]
                    ld.text((px, py - off), line, font=font, fill=(*colour, 255))
                    py += (ld.textbbox((0, 0), line, font=font)[3] - ld.textbbox((0, 0), line, font=font)[1]) + gap
                rotated = layer.rotate(-region.tilt_deg, expand=True, resample=Image.Resampling.BICUBIC)
                canvas.paste(rotated, (x0 + w // 2 - rotated.width // 2, y0 + h // 2 - rotated.height // 2), rotated)
                rotations += 1
                text_specs.append(TextRegionSpec(kind="headline", box=box4(tight), clipped=clipped))
            else:
                py = float(top)
                for i, (line, lw) in enumerate(zip(lines, widths)):
                    px = x0 if region.align in (None, "left") else (x0 + (w - lw) / 2 if region.align == "center" else x1 - lw)
                    off = draw.textbbox((0, 0), line, font=font)[1]  # glyph top offset: keep the ink inside its region
                    bbox = draw.textbbox((px, py - off), line, font=font)
                    draw.text((px, py - off), line, font=font, fill=colour)
                    text_specs.append(TextRegionSpec(kind="headline", box=box4(bbox), clipped=clipped and i == len(lines) - 1))
                    py += (bbox[3] - bbox[1]) + gap
            clipped_any = clipped_any or clipped
            ImageDraw.Draw(text_mask).rectangle(tight, fill=255)
            ImageDraw.Draw(content_mask).rectangle(tight, fill=255)
            text_metrics.append({
                "ref": region.content_ref, "token": token, "font_px": font.size, "lines": len(lines),
                "block_h_frac": round(used_h / H, 4), "block_w_frac": round(block_w / W, 4), "tilted": bool(region.tilt_deg),
            })
            layers += 1

    if layout.show_progress and not progress_hidden:
        size = round(W * tok.TYPE_SLIDE_INDEX.size_frac)
        draw.text((round(PROGRESS_ZONE[0] * W) + round(W * 0.03), round(H * (PROGRESS_ZONE[1] + 0.005))),
                  f"{index + 1:02d} / {total:02d}", font=ig_font(size, tok.TYPE_SLIDE_INDEX.weight),
                  fill=MUTED_ON_DARK if _luma_stats(canvas, (0, 0, W, round(H * 0.1)))[0] < 118 else MUTED_INK)

    mark_count = _place_adaptive_mark(canvas, spec, layout.logo_position)
    raw = layout.model_dump()
    chars = layout_characteristics(raw)
    signature = layout_signature(raw)
    variant = f"declared_{chars['headline_zone']}_{chars['media_zone']}_{chars['media_dominance']}_{chars['region_count']}"
    canvas_px = W * H
    return LayoutResult(
        image=canvas.convert("RGB"), text_regions=text_specs, visible_brand_mark_count=mark_count,
        source_image_treatment=treatment, layout_variant=variant, text_clipped=clipped_any,
        notes={
            "layout_plan_applied": True, "layout_signature": signature, "layout_characteristics": chars,
            "media_regions": media_used, "unresolved_media_regions": dropped,
            "source_media_pixels_unaltered": (all(fidelity) if fidelity else None),
            "graphic_fallback_used": bool(dropped),
            "media_regions_tilted": sum(1 for m in media_used if m["tilted"]), "background": layout.background, "palette": layout.palette,
            "logo_position": layout.logo_position, "arrangement": layout.arrangement, "layer_count": layers, "rotation_count": rotations,
            "media_canvas_coverage": round(media_mask.histogram()[255] / canvas_px, 4),
            "text_canvas_coverage": round(text_mask.histogram()[255] / canvas_px, 4),
            "object_canvas_coverage": round(min(object_px, canvas_px) / canvas_px, 4),
            "object_bbox_canvas_coverage": round(min(object_bbox_px, canvas_px) / canvas_px, 4),
            "object_bounding_boxes": object_boxes,
            "negative_space": round(1 - content_mask.histogram()[255] / canvas_px, 4),
            "text_metrics": text_metrics, "text_zone_reports": zone_reports,
        },
    )
