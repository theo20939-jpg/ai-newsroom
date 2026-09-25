"""Focal-aware framing for recap photos (deterministic, PIL only - no ML, no network).

A photo is framed around its SUBJECT, not around the rectangle's centre. The subject is estimated from a saliency map (edge energy + colour
distance from the image's own dominant tone + skin tones, so a face pulls the frame + a mild centre prior) on a small thumbnail: its
weighted centroid is the focal point and the box holding most of the saliency is the subject box. A cover crop that would cut too much of that box is not used - the whole picture is
placed on a blurred extension of itself instead (the photo's own pixels, uncropped and unaltered)."""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageFilter, ImageOps

_THUMB = 96
SUBJECT_MASS = 0.72          # the subject box holds this share of the saliency
MIN_SUBJECT_KEPT = 0.82      # a cover crop must keep at least this share of the subject box, else the photo is shown whole


@dataclass(frozen=True)
class Focus:
    x: float
    y: float
    box: tuple[float, float, float, float]  # subject box (x0, y0, x1, y1), fractions of the image


def _saliency(image: Image.Image) -> tuple[list[float], int, int]:
    small = ImageOps.contain(image.convert("RGB"), (_THUMB, _THUMB))
    w, h = small.size
    edges = small.convert("L").filter(ImageFilter.FIND_EDGES).filter(ImageFilter.BoxBlur(1))
    blurred = small.filter(ImageFilter.BoxBlur(2))
    px = list(blurred.getdata())
    n = len(px)
    mean = tuple(sum(p[i] for p in px) / n for i in range(3))
    e = list(edges.getdata())
    sal = []
    for i, (p, ev) in enumerate(zip(px, e)):
        x, y = i % w, i // w
        dist = ((p[0] - mean[0]) ** 2 + (p[1] - mean[1]) ** 2 + (p[2] - mean[2]) ** 2) ** 0.5 / 441.0
        sat = (max(p) - min(p)) / 255.0
        centre = 1.0 - 0.35 * (((x / max(1, w - 1)) - 0.5) ** 2 + ((y / max(1, h - 1)) - 0.5) ** 2) / 0.5
        r, g, b = p
        skin = r > 95 and g > 40 and b > 20 and r > g and r > b and r - min(g, b) > 15 and abs(r - g) > 15  # faces pull the frame
        sal.append((0.55 * ev / 255.0 + 0.30 * dist + 0.15 * sat + (0.35 if skin else 0.0)) * centre)
    # keep the salient part only (a busy background texture must not drag the centroid)
    cut = sorted(sal)[int(0.7 * n)]
    return [s if s >= cut else 0.0 for s in sal], w, h


def _box(sal: list[float], w: int, h: int, mass: float) -> tuple[float, float, float, float]:
    total = sum(sal) or 1.0
    cols = [sum(sal[y * w + x] for y in range(h)) for x in range(w)]
    rows = [sum(sal[y * w:(y + 1) * w]) for y in range(h)]

    def span(values: list[float], n: int) -> tuple[int, int]:
        trim = (1.0 - mass) / 2 * total
        lo, acc = 0, 0.0
        while lo < n - 1 and acc + values[lo] <= trim:
            acc += values[lo]
            lo += 1
        hi, acc = n - 1, 0.0
        while hi > lo and acc + values[hi] <= trim:
            acc += values[hi]
            hi -= 1
        return lo, hi + 1

    x0, x1 = span(cols, w)
    y0, y1 = span(rows, h)
    return x0 / w, y0 / h, x1 / w, y1 / h


def focus_of(image: Image.Image) -> Focus:
    """Focal point and subject box of a photo (a 96px thumbnail pass - cheap enough to run per placement, nothing is cached)."""
    sal, w, h = _saliency(image)
    total = sum(sal) or 1.0
    fx = sum((i % w + 0.5) * s for i, s in enumerate(sal)) / total / w
    fy = sum((i // w + 0.5) * s for i, s in enumerate(sal)) / total / h
    return Focus(round(fx, 3), round(fy, 3), tuple(round(v, 3) for v in _box(sal, w, h, SUBJECT_MASS)))


def cover_window(size: tuple[int, int], target: tuple[int, int], focus: Focus) -> tuple[float, float, float, float]:
    """The cover-crop window (fractions of the image) for a target box, centred on the focal point and clamped to the image."""
    sw, sh = size
    tw, th = target
    if sw / sh > tw / th:  # crop the sides
        cw = (sh * tw / th) / sw
        x0 = min(max(focus.x - cw / 2, 0.0), 1.0 - cw)
        return x0, 0.0, x0 + cw, 1.0
    ch = (sw * th / tw) / sh
    y0 = min(max(focus.y - ch * 0.45, 0.0), 1.0 - ch)
    return 0.0, y0, 1.0, y0 + ch


def subject_kept(window: tuple[float, float, float, float], box: tuple[float, float, float, float]) -> float:
    bx0, by0, bx1, by1 = box
    area = max(1e-6, (bx1 - bx0) * (by1 - by0))
    ix = max(0.0, min(window[2], bx1) - max(window[0], bx0))
    iy = max(0.0, min(window[3], by1) - max(window[1], by0))
    return ix * iy / area


def frame_photo(image: Image.Image, width: int, height: int, *, min_kept: float = MIN_SUBJECT_KEPT) -> tuple[Image.Image, str]:
    """(tile, treatment): a focal cover crop when it keeps enough of the subject (`min_kept`), else the whole photo on a blurred
    extension of itself."""
    src = image.convert("RGB")
    focus = focus_of(image)
    window = cover_window(src.size, (width, height), focus)
    if subject_kept(window, focus.box) >= min_kept:
        sw, sh = src.size
        crop = src.crop((round(window[0] * sw), round(window[1] * sh), round(window[2] * sw), round(window[3] * sh)))
        return crop.resize((width, height), Image.Resampling.LANCZOS).convert("RGBA"), "focal_cover"
    backdrop = ImageOps.fit(src, (width, height), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(max(8, width // 28)))
    backdrop = Image.blend(backdrop, Image.new("RGB", backdrop.size, (12, 12, 14)), 0.35)
    whole = ImageOps.contain(src, (width, height), Image.Resampling.LANCZOS)
    backdrop.paste(whole, ((width - whole.width) // 2, (height - whole.height) // 2))
    return backdrop.convert("RGBA"), "whole_on_blurred_extension"


# --- hero canvas (founder direction: a strong photo IS the canvas, the copy is composed over it) -------------------------------------

HERO_CANVAS = (1080, 1350)


def _canvas_crop(image: Image.Image, width: int, height: int) -> Image.Image:
    src = image.convert("RGB")
    window = cover_window(src.size, (width, height), focus_of(image))
    sw, sh = src.size
    box = (round(window[0] * sw), round(window[1] * sh), round(window[2] * sw), round(window[3] * sh))
    return src.crop(box).resize((width, height), Image.Resampling.LANCZOS)


def _skin_box(image: Image.Image) -> tuple[float, float, float, float] | None:
    """The box of the photo's skin-tone pixels (faces, heads, hands) - None when there are almost none."""
    small = ImageOps.contain(image.convert("RGB"), (_THUMB, _THUMB)).filter(ImageFilter.BoxBlur(1))
    w, h = small.size
    pts = [(i % w, i // w) for i, (r, g, b) in enumerate(small.getdata())
           if r > 95 and g > 40 and b > 20 and r > g and r > b and r - min(g, b) > 15 and abs(r - g) > 15]
    if len(pts) < 0.01 * w * h:
        return None
    xs, ys = sorted(x for x, _ in pts), sorted(y for _, y in pts)
    cut = max(0, len(pts) // 50)  # ignore a few stray warm pixels at the extremes
    return xs[cut] / w, ys[cut] / h, (xs[-1 - cut] + 1) / w, (ys[-1 - cut] + 1) / h


def protected_box(image: Image.Image) -> tuple[float, float, float, float]:
    """What copy must not cover (fractions of the photo): the salient subject plus any faces / heads (skin) - the subject box alone can
    stop below the heads of a standing pair (real recap: GTA VI key art)."""
    box = focus_of(image).box
    skin = _skin_box(image)
    if skin is None:
        return box
    return min(box[0], skin[0]), min(box[1], skin[1]), max(box[2], skin[2]), max(box[3], skin[3])


HERO_MIN_ASPECT, HERO_MAX_ASPECT = 0.9, 1.5  # the photo's own shape on the hero canvas, cropped no further than this
_FEATHER = 0.1                               # the soft join between the photo and its extension (share of the canvas height)
_MIN_FEATHER = 0.015
# the hero copy areas (services.instagram_recap_frames.hero_story_layout), canvas fractions (x0, y0, x1, y1)
COPY_BOXES = {"top": (0.07, 0.06, 0.93, 0.40), "bottom": (0.07, 0.60, 0.93, 0.915)}
MAX_SUBJECT_COVERED = 0.03  # at most this share of the protected subject may sit under the copy


@dataclass(frozen=True)
class HeroPlan:
    zone: str
    band: tuple[float, float]                      # the photo's top and bottom edge on the canvas (fractions)
    window: tuple[float, float, float, float]      # the photo crop (fractions of the photo)
    subject: tuple[float, float, float, float]     # the protected subject on the canvas (fractions)


def _plan(image: Image.Image, zone: str, width: int = HERO_CANVAS[0], height: int = HERO_CANVAS[1]) -> HeroPlan:
    aspect = min(HERO_MAX_ASPECT, max(HERO_MIN_ASPECT, image.width / image.height))
    band_h = min(1.0, (width / aspect) / height)
    window = cover_window(image.size, (width, round(band_h * height)), focus_of(image))
    top = 0.0 if zone == "bottom" else 1.0 - band_h  # copy at the bottom -> the photo is anchored to the top, and the other way round
    px0, py0, px1, py1 = protected_box(image)

    def fx(v: float) -> float:
        return min(1.0, max(0.0, (v - window[0]) / (window[2] - window[0])))

    def fy(v: float) -> float:
        return top + band_h * min(1.0, max(0.0, (v - window[1]) / (window[3] - window[1])))

    return HeroPlan(zone, (top, top + band_h), window, (fx(px0), fy(py0), fx(px1), fy(py1)))


def _covered(subject: tuple[float, float, float, float], box: tuple[float, float, float, float]) -> float:
    area = max(1e-6, (subject[2] - subject[0]) * (subject[3] - subject[1]))
    ix = max(0.0, min(subject[2], box[2]) - max(subject[0], box[0]))
    iy = max(0.0, min(subject[3], box[3]) - max(subject[1], box[1]))
    return ix * iy / area


def subject_covered(plan: HeroPlan) -> float:
    """Share of the protected subject that the copy area would sit on. (The small brand mark keeps its corner: the photo's subject
    box is coarse at its edges - real recap: 3% of the ChatGPT shot's typing hands - and moving a whole composition for the mark alone
    is not worth it.)"""
    return _covered(plan.subject, COPY_BOXES[plan.zone])


def hero_copy_zone(image: Image.Image) -> str | None:
    """'top' or 'bottom': the copy goes past the photo's CALMER end (GTA's sky, the dark base of a phone shot) - unless the copy there
    would sit on the protected subject (faces, the device, the product), in which case the other end is used; None when neither end
    is clear, so the slide keeps a composition where copy and photo do not overlap."""
    sal, w, h = _saliency(image)
    rows = [sum(sal[y * w:(y + 1) * w]) for y in range(h)]
    band = max(1, round(h * 0.3))
    calm = "top" if sum(rows[:band]) < 0.85 * sum(rows[-band:]) else "bottom"
    for zone in (calm, "bottom" if calm == "top" else "top"):
        if subject_covered(_plan(image, zone)) <= MAX_SUBJECT_COVERED:
            return zone
    return None


def _gradient(size: tuple[int, int], zone: str, *, copy_edge: float, ramp_from: float, strength: float = 0.93) -> Image.Image:
    """An L mask over the copy end: nothing before `ramp_from`, a soft ramp to 0.8 at `copy_edge` (where the copy begins), then
    deepening to `strength` at the canvas edge. Positions are canvas fractions; no hard edge anywhere."""
    width, height = size
    column = Image.new("L", (1, height), 0)
    for y in range(height):
        t = y / height
        d, start, edge = (t, ramp_from, copy_edge) if zone == "bottom" else (1.0 - t, 1.0 - ramp_from, 1.0 - copy_edge)
        if d <= start:
            a = 0.0
        elif d <= edge:
            a = 0.8 * ((d - start) / max(1e-6, edge - start)) ** 1.6
        else:
            a = 0.8 + (strength - 0.8) * (d - edge) / max(1e-6, 1.0 - edge)
        column.putpixel((0, y), round(255 * a))
    return column.resize((width, height))


def frame_hero(image: Image.Image, width: int, height: int, zone: str) -> Image.Image:
    """The hero canvas: the photo keeps a strong shape of its own (a subject-centred crop to HERO_MIN..MAX_ASPECT), anchored to the edge
    away from the copy, and the rest of the canvas continues the SAME photo - softened and darkened - through a feathered join. The copy
    end deepens into a gradient. The join and the gradient both stop short of the protected subject (faces, the device): it is never
    faded or darkened to make room for type."""
    src = image.convert("RGB")
    plan = _plan(image, zone, width, height)
    band_top, band_bottom = plan.band
    band_h = max(1, round((band_bottom - band_top) * height))
    window = plan.window
    crop = src.crop((round(window[0] * src.width), round(window[1] * src.height), round(window[2] * src.width), round(window[3] * src.height)))
    photo = crop.resize((width, band_h), Image.Resampling.LANCZOS)
    canvas = ImageOps.fit(src, (width, height), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(max(10, width // 40)))
    canvas = Image.blend(canvas, Image.new("RGB", canvas.size, (10, 10, 12)), 0.45)
    # the soft join lives between the photo's inner edge and the subject, never over it
    inner_edge = band_bottom if zone == "bottom" else band_top
    room = (inner_edge - plan.subject[3]) if zone == "bottom" else (plan.subject[1] - inner_edge)
    feather = max(1, round(height * min(_FEATHER, max(_MIN_FEATHER, room - 0.01))))
    mask = Image.new("L", (1, band_h), 255)
    for i in range(min(feather, band_h)):
        mask.putpixel((0, band_h - 1 - i if zone == "bottom" else i), round(255 * (i / feather) ** 1.2))
    canvas.paste(photo, (0, round(band_top * height)), mask.resize((width, band_h)))
    copy_edge = COPY_BOXES[zone][1] - 0.02 if zone == "bottom" else COPY_BOXES[zone][3] + 0.02
    ramp_from = copy_edge - 0.18 if zone == "bottom" else copy_edge + 0.18
    # the subject stays undarkened - except, at most, the thin edge the copy check already allows (<= MAX_SUBJECT_COVERED): a short ramp
    # before the copy is always kept, or the type would sit on unreadable pixels (real recap: the bottom of Jony Ive's shirt)
    if zone == "bottom":
        ramp_from = min(max(ramp_from, plan.subject[3]), copy_edge - 0.05)
    else:
        ramp_from = max(min(ramp_from, plan.subject[1]), copy_edge + 0.05)
    dark = Image.new("RGB", canvas.size, (10, 10, 12))
    return Image.composite(dark, canvas, _gradient(canvas.size, zone, copy_edge=copy_edge, ramp_from=ramp_from)).convert("RGBA")


def frame_ambient(image: Image.Image, width: int, height: int) -> Image.Image:
    """A weak photo as a quiet contextual LAYER under typography: oversized, softened and darkened - never an attached thumbnail."""
    photo = _canvas_crop(image, width, height).filter(ImageFilter.GaussianBlur(max(6, width // 90)))
    return Image.blend(photo, Image.new("RGB", photo.size, (10, 10, 12)), 0.62).convert("RGBA")
