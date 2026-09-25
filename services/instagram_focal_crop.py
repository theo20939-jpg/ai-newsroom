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
