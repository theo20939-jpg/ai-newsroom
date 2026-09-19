"""INSTAGRAM-VISUAL-SYSTEM-V1-1 section 13/14: deterministic real-image handling - orientation
classification, cover/contain fitting, subject-safe positioning, readability gradients, and the
structured (never blank) fallback used when no source image is supplied.

Independent of Telegram V8 - no import of services/brand_renderer.py or friends. Reuses only
services/instagram_design_tokens.py (this system's own tokens) and PIL."""
from __future__ import annotations

import enum
import hashlib
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter

from services import instagram_design_tokens as tok
from services.instagram_visual_profiles import ProfileSpec, ig_brand_mark, ig_font


class ImageOrientation(str, enum.Enum):
    PORTRAIT = "portrait"     # aspect < 0.9
    SQUARE = "square"         # 0.9 <= aspect <= 1.15
    LANDSCAPE = "landscape"   # aspect > 1.15


def classify_orientation(width: int, height: int) -> ImageOrientation:
    aspect = width / height if height else 1.0
    if aspect < 0.9:
        return ImageOrientation.PORTRAIT
    if aspect > 1.15:
        return ImageOrientation.LANDSCAPE
    return ImageOrientation.SQUARE


class SourceImageTreatment(str, enum.Enum):
    """Mirrors the vocabulary spirit of the Telegram render-evidence contract (preserve/crop/
    generated) without importing it - Instagram's own truthful record of what happened to the
    supplied bytes."""

    NONE = "none"               # no source image was supplied - the structured fallback ran
    COVER_CROPPED = "cover_cropped"   # filled the frame, cropped to fit (a real crop occurred)
    CONTAIN_PRESERVED = "contain_preserved"  # the whole image kept, letterboxed - never destroyed


@dataclass(frozen=True)
class FittedImage:
    image: Image.Image           # RGBA, exactly (width, height)
    treatment: SourceImageTreatment
    source_orientation: ImageOrientation | None


def fit_image_cover(source: Image.Image, *, width: int, height: int, focus_y: float = 0.42) -> FittedImage:
    """Cover-crop: scales the source so it fills (width, height) exactly, cropping the excess.
    `focus_y` (0=top, 1=bottom, default a bit above center - most editorial subjects/faces sit
    slightly above frame-center, never exactly centered which tends to crop chins/foreheads)
    biases which part of the taller/wider axis survives the crop - deterministic, not random."""
    src = source.convert("RGB")
    sw, sh = src.size
    orientation = classify_orientation(sw, sh)
    target_ratio = width / height
    src_ratio = sw / sh

    if src_ratio > target_ratio:
        # source is relatively wider - crop the sides, keep full height
        new_w = round(sh * target_ratio)
        x0 = max(0, min(sw - new_w, round((sw - new_w) * 0.5)))
        box = (x0, 0, x0 + new_w, sh)
    else:
        # source is relatively taller - crop top/bottom, keep full width
        new_h = round(sw / target_ratio)
        y0 = max(0, min(sh - new_h, round((sh - new_h) * focus_y)))
        box = (0, y0, sw, y0 + new_h)

    cropped = src.crop(box)
    resized = cropped.resize((width, height), Image.Resampling.LANCZOS)
    return FittedImage(image=resized.convert("RGBA"), treatment=SourceImageTreatment.COVER_CROPPED, source_orientation=orientation)


def fit_image_contain(source: Image.Image, *, width: int, height: int, bg: tuple[int, int, int] = tok.INK) -> FittedImage:
    """Contain-fit: the ENTIRE source image is kept (never cropped, never destroyed) and centered
    on a `bg`-filled canvas of exactly (width, height). Used for source infographics/screenshots
    where cropping would destroy real content (section 13's own "do not destroy source
    infographics" instruction)."""
    src = source.convert("RGB")
    sw, sh = src.size
    orientation = classify_orientation(sw, sh)
    scale = min(width / sw, height / sh)
    new_w, new_h = max(1, round(sw * scale)), max(1, round(sh * scale))
    resized = src.resize((new_w, new_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), bg)
    canvas.paste(resized, ((width - new_w) // 2, (height - new_h) // 2))
    return FittedImage(image=canvas.convert("RGBA"), treatment=SourceImageTreatment.CONTAIN_PRESERVED, source_orientation=orientation)


def apply_bottom_readability_gradient(
    canvas: Image.Image, *, height_frac: float = tok.GRADIENT_BOTTOM_HEIGHT_FRAC,
    max_alpha: int = tok.GRADIENT_BOTTOM_MAX_ALPHA, tint: tuple[int, int, int] = tok.INK,
) -> None:
    """Composites a bottom-anchored gradient (transparent -> `tint`) directly onto `canvas`
    in-place - a CONTROLLED readability aid (section 13), never a flat full-image darken."""
    w, h = canvas.size
    band_h = round(h * height_frac)
    gradient = Image.new("L", (1, band_h), 0)
    for y in range(band_h):
        # eased (quadratic) ramp - most of the ramp stays near-transparent near the top of the
        # band, concentrating opacity in the bottom third where the text actually sits.
        t = y / max(1, band_h - 1)
        gradient.putpixel((0, y), round(max_alpha * (t ** 1.6)))
    gradient = gradient.resize((w, band_h))
    overlay = Image.new("RGBA", (w, band_h), (*tint, 0))
    overlay.putalpha(gradient)
    canvas.alpha_composite(overlay, (0, h - band_h))


def apply_top_readability_gradient(
    canvas: Image.Image, *, height_frac: float = tok.GRADIENT_TOP_HEIGHT_FRAC,
    max_alpha: int = tok.GRADIENT_TOP_MAX_ALPHA, tint: tuple[int, int, int] = tok.INK,
) -> None:
    w, h = canvas.size
    band_h = round(h * height_frac)
    gradient = Image.new("L", (1, band_h), 0)
    for y in range(band_h):
        t = 1 - (y / max(1, band_h - 1))
        gradient.putpixel((0, y), round(max_alpha * (t ** 1.6)))
    gradient = gradient.resize((w, band_h))
    overlay = Image.new("RGBA", (w, band_h), (*tint, 0))
    overlay.putalpha(gradient)
    canvas.alpha_composite(overlay, (0, 0))


def _seed_from(identity: str) -> int:
    return int(hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8], 16)


def draw_with_alpha(canvas: Image.Image, painter) -> None:
    """Runs `painter(draw)` on a fresh fully-transparent layer, then `Image.alpha_composite`s that
    layer onto `canvas`. This is the ONLY way a fill/outline alpha below 255 actually blends: PIL's
    `ImageDraw` on an existing RGBA canvas does not composite against the canvas's own pixels - it
    overwrites their RGB outright and simply stores the alpha value it was given, which a later
    `.convert("RGB")` then silently drops, so a "faint"/"restrained" alpha value would otherwise be
    dead code that quietly renders at full strength. Every low-alpha draw in this visual system
    routes through here (or an equivalent manual layer+composite) for that reason."""
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    painter(ImageDraw.Draw(layer, "RGBA"))
    canvas.alpha_composite(layer)


def build_dimmed_source_field(
    media_image: Image.Image, *, width: int, height: int, focus_y: float = 0.42,
    dim_alpha: int = 205, blur_radius: float = 6.0,
) -> tuple[Image.Image, SourceImageTreatment]:
    """A REAL photographic background for the typography-led carousel families (COMPARISON/
    DETAIL/CLOSING) that previously only ever drew `build_structured_fallback`'s synthetic grid
    regardless of whether a real asset existed - the actual root cause of those slides reading as
    a generic template even when a real generated hero image was available for the whole deck
    (docs: Phase B.3 visual-divergence forensic trace). A heavy, uniform dark scrim (not just the
    bottom/top readability bands those families never needed before) keeps foreground text legible
    from anywhere on the card, and a gentle blur keeps the photograph as recognisable texture/mood
    rather than competing detail. Reuses `fit_image_cover`'s own truthful treatment vocabulary -
    never invents a new `source_image_treatment` value the art validator would reject."""
    fitted = fit_image_cover(media_image, width=width, height=height, focus_y=focus_y)
    canvas = fitted.image.convert("RGB").filter(ImageFilter.GaussianBlur(blur_radius)).convert("RGBA")
    scrim = Image.new("RGBA", canvas.size, (*tok.INK, dim_alpha))
    canvas.alpha_composite(scrim)
    return canvas, fitted.treatment


def build_structured_fallback(*, width: int, height: int, identity: str, block_count: int | None = None) -> Image.Image:
    """Section 14: the intentional, structured composition used when NO source image exists -
    layered brand-geometry blocks + a faint technical grid, NEVER an empty rectangle. Deterministic
    per `identity` (e.g. the package id) - the SAME package always produces the SAME fallback, but
    two different packages produce visibly different arrangements (content-derived, not random).

    `block_count` overrides `tok.FALLBACK_BLOCK_COUNT` - pass 0 for a grid-only backdrop (DATA's own
    layouts already carry a hero metric + chart as their visual weight, so the floating panel blocks
    meant to give a bare NEWS/BREAKING text card some depth would just read as unrelated clutter)."""
    canvas = Image.new("RGBA", (width, height), (*tok.INK, 255))
    seed = _seed_from(identity)

    def _paint(draw: ImageDraw.ImageDraw) -> None:
        # a faint technical grid across the whole frame - structure, not decoration
        step = round(width * tok.FALLBACK_GRID_STEP_FRAC)
        for x in range(0, width, step):
            draw.line([(x, 0), (x, height)], fill=(*tok.INK_RAISED, tok.FALLBACK_GRID_ALPHA), width=1)
        for y in range(0, height, step):
            draw.line([(0, y), (width, y)], fill=(*tok.INK_RAISED, tok.FALLBACK_GRID_ALPHA), width=1)

        # deterministically placed raised geometry blocks - large, soft rectangles offset by `seed`
        rng_vals = [(seed >> (i * 4)) & 0xF for i in range(6)]
        for i in range(tok.FALLBACK_BLOCK_COUNT if block_count is None else block_count):
            bw = round(width * (0.35 + 0.08 * rng_vals[i % len(rng_vals)] / 15))
            bh = round(height * (0.18 + 0.05 * rng_vals[(i + 2) % len(rng_vals)] / 15))
            bx = round((width - bw) * (rng_vals[(i + 1) % len(rng_vals)] / 15))
            by = round(height * (0.10 + i * 0.28) + (rng_vals[(i + 3) % len(rng_vals)] / 15) * height * 0.08)
            draw.rounded_rectangle(
                [bx, by, bx + bw, by + bh], radius=round(width * tok.CORNER_RADIUS_FRAC),
                fill=(*tok.INK_RAISED, tok.FALLBACK_BLOCK_ALPHA),
            )

    draw_with_alpha(canvas, _paint)
    return canvas


def mark_reserve_width(spec: ProfileSpec, *, compact: bool = False) -> int:
    """How much horizontal space every bottom-right-anchored text layout must keep clear, so the
    brand mark this system ALWAYS places there never collides with a text line's last word.
    Shared by every visual-family layout module (NEWS/BREAKING/DATA/QUOTE/CAROUSEL/REEL).

    MUST mirror `place_brand_mark`'s own geometry exactly: the mark sits `LOGO_MARGIN_FRAC` in from
    the right edge, so a caller reserving only `mark_width + a small buffer` (forgetting the mark's
    OWN right-margin) under-reserves by that margin - a short single-line last row (e.g. a one-line
    dek) then lands close enough to the mark to visually collide even though it measured "under"
    the wrong, too-generous boundary. (First caught the same way in a full-bleed NEWS render whose
    dek happened to wrap to two lines and coincidentally cleared the mark either way; a one-line
    fallback render is what actually exposed the missing margin term.)"""
    frac = tok.LOGO_WIDTH_FRAC_COMPACT if compact else tok.LOGO_WIDTH_FRAC_STANDARD
    mark_width = round(spec.width * frac)
    margin = round(spec.width * tok.LOGO_MARGIN_FRAC)
    gap = round(spec.width * 0.035)
    return margin + mark_width + gap


def place_brand_mark(canvas: Image.Image, spec: ProfileSpec, *, compact: bool = False) -> int:
    """Composites the ONE canonical NNJ mark into the bottom-right safe corner and returns the
    visible-mark count (always 1) so callers can populate `LayoutResult.visible_brand_mark_count`
    truthfully instead of hardcoding it."""
    frac = tok.LOGO_WIDTH_FRAC_COMPACT if compact else tok.LOGO_WIDTH_FRAC_STANDARD
    mark = ig_brand_mark(target_width=round(spec.width * frac), red=True)
    margin = round(spec.width * tok.LOGO_MARGIN_FRAC)
    bottom_safe = round(spec.height * spec.safe_bottom_frac)
    x = spec.width - margin - mark.width
    y = spec.height - bottom_safe - margin - mark.height
    canvas.alpha_composite(mark, (x, y))
    return 1


def draw_corner_brackets(canvas: Image.Image, spec: ProfileSpec, *, top: bool = True, bottom: bool = True) -> None:
    """Small dashboard-style corner brackets, top-left and/or bottom-left - a quiet, restrained
    "designed instrument" touch shared by any layout whose background would otherwise read as a
    bare panel (DATA, no-portrait QUOTE, CAROUSEL). Never placed bottom-right, which stays reserved
    for the brand mark. Callers that already draw a kicker/progress readout in the exact top-left
    corner pass `top=False` - the bracket would otherwise sit directly under that text and read as
    visual clutter rather than a deliberate frame."""
    w, h = canvas.size
    margin = round(w * tok.MARGIN_FRAC)
    bl = round(w * 0.045)

    def _paint(draw: ImageDraw.ImageDraw) -> None:
        if top:
            draw.line([(margin, margin + bl), (margin, margin), (margin + bl, margin)], fill=(*tok.GREY_SOFT, 90), width=2)
        if bottom:
            bottom_y = h - margin
            draw.line([(margin, bottom_y - bl), (margin, bottom_y), (margin + bl, bottom_y)], fill=(*tok.GREY_SOFT, 60), width=2)

    draw_with_alpha(canvas, _paint)


def draw_kicker_chip(canvas: Image.Image, *, x: float, y: float, text: str, accent: bool = False) -> tuple[int, int]:
    """A small rounded-rect metadata chip (category / BREAKING indicator). Returns (width, height)
    actually drawn so callers can lay out what follows. `accent=True` -> filled NNJ red (BREAKING /
    emphasis); otherwise a quiet outlined chip (standard NEWS category metadata)."""
    draw = ImageDraw.Draw(canvas, "RGBA")
    role = tok.TYPE_KICKER_ACCENT if accent else tok.TYPE_KICKER
    size = max(16, round(canvas.width * role.size_frac))
    font = ig_font(size, role.weight)
    text_w = draw.textlength(text.upper(), font=font)
    pad_x = round(size * 0.9)
    pad_y = round(size * 0.55)
    chip_w = round(text_w + pad_x * 2)
    chip_h = round(size + pad_y * 2)
    radius = chip_h // 2
    if accent:
        draw.rounded_rectangle([x, y, x + chip_w, y + chip_h], radius=radius, fill=(*tok.RED, 255))
        text_color = tok.WHITE
    else:
        draw_with_alpha(canvas, lambda d: d.rounded_rectangle([x, y, x + chip_w, y + chip_h], radius=radius, outline=(*tok.GREY_SOFT, 200), width=2))
        text_color = role.color
    draw.text((x + pad_x, y + pad_y), text.upper(), font=font, fill=text_color)
    return chip_w, chip_h
