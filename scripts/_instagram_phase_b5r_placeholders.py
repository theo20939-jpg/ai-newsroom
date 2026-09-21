"""Phase B.5R: NEUTRAL SYNTHETIC placeholder media for the family reconstruction test. Procedural, deterministic
(no RNG, no network, no provider, no real news imagery). They only stand in for 'an object', 'a portrait
scene', 'a neon scene', 'a reaction image', 'a photo band', 'a screenshot' so the renderer's family
mechanics can be judged; they say nothing about content quality."""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter


def _vgrad(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, top)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img


def object_on(ground: tuple[int, int, int], *, size=(1200, 1200), body=(70, 74, 84), light: bool = False, glow: bool = True) -> Image.Image:
    """An isolated device-like object on a flat ground that matches the slide surface, so it reads as isolated."""
    w, h = size
    img = Image.new("RGB", size, ground)
    if glow and not light:
        halo = Image.new("RGB", size, ground)
        ImageDraw.Draw(halo).ellipse([w * 0.12, h * 0.18, w * 0.88, h * 0.86], fill=tuple(min(255, c + 26) for c in ground))
        img = Image.blend(img, halo.filter(ImageFilter.GaussianBlur(w * 0.10)), 0.9)
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = w * 0.20, h * 0.16, w * 0.80, h * 0.86
    top_c = tuple(min(255, c + 34) for c in body)
    for i in range(int(y1 - y0)):
        t = i / max(1, y1 - y0)
        c = tuple(round(top_c[k] + (body[k] - top_c[k]) * t) for k in range(3))
        d.line([(x0 + w * 0.06 * (1 - abs(0.5 - t) * 0), y0 + i), (x1 - w * 0.06 * 0, y0 + i)], fill=c)
    d.rounded_rectangle([x0, y0, x1, y1], radius=int(w * 0.09), outline=tuple(min(255, c + 70) for c in body), width=5)
    for cx, cy in ((0.38, 0.30), (0.62, 0.30), (0.50, 0.44)):
        r = w * 0.055
        d.ellipse([w * cx - r, h * cy - r, w * cx + r, h * cy + r], fill=(14, 15, 18), outline=tuple(min(255, c + 90) for c in body), width=4)
    return img


def portrait_dark(*, size=(1080, 1350), rim=(190, 40, 52)) -> Image.Image:
    """A dark portrait scene whose lower ~40% is deliberately quiet (dark), like a low-key photograph."""
    w, h = size
    img = _vgrad(size, (30, 28, 40), (6, 6, 8))
    d = ImageDraw.Draw(img)
    cx = w * 0.62
    d.ellipse([cx - w * 0.16, h * 0.16, cx + w * 0.16, h * 0.44], fill=(78, 70, 76))
    d.ellipse([cx - w * 0.165, h * 0.16, cx - w * 0.14, h * 0.44], fill=rim)
    d.ellipse([cx - w * 0.152, h * 0.165, cx + w * 0.152, h * 0.435], fill=(72, 64, 70))
    d.rounded_rectangle([cx - w * 0.36, h * 0.46, cx + w * 0.34, h * 0.86], radius=int(w * 0.18), fill=(38, 34, 42))
    img = img.filter(ImageFilter.GaussianBlur(3))
    lower = Image.new("RGB", size, (5, 5, 7))
    mask = Image.linear_gradient("L").resize(size)
    mask = mask.point(lambda v: 0 if v < 120 else min(255, (v - 120) * 2))
    return Image.composite(lower, img, mask)


def neon_scene(*, size=(1080, 1350), glow=(196, 60, 220)) -> Image.Image:
    """A dark neon city-like scene; the top band stays very dark."""
    w, h = size
    img = _vgrad(size, (6, 4, 14), (34, 10, 52))
    d = ImageDraw.Draw(img)
    base = int(h * 0.92)
    for i, (bx, bw, bh) in enumerate(((0.02, 0.14, 0.44), (0.18, 0.10, 0.62), (0.30, 0.16, 0.50), (0.50, 0.12, 0.70), (0.66, 0.16, 0.54), (0.84, 0.14, 0.60))):
        x0, x1 = int(w * bx), int(w * (bx + bw))
        y0 = base - int(h * bh * 0.7)
        d.rectangle([x0, y0, x1, base], fill=(16 + i * 2, 10, 30))
        for wy in range(y0 + 20, base - 10, 34):
            for wx in range(x0 + 10, x1 - 10, 26):
                if (wx + wy + i) % 3 == 0:
                    d.rectangle([wx, wy, wx + 8, wy + 12], fill=glow)
    d.ellipse([w * 0.44, h * 0.78, w * 0.50, h * 0.92], fill=(6, 6, 8))
    d.ellipse([w * 0.455, h * 0.745, w * 0.485, h * 0.785], fill=(6, 6, 8))
    top_dark = Image.new("RGB", size, (5, 4, 12))
    mask = Image.linear_gradient("L").resize(size).transpose(Image.Transpose.FLIP_TOP_BOTTOM).point(lambda v: max(0, v - 130) * 2)
    return Image.composite(top_dark, img, mask)


def reaction_blob(*, size=(1000, 1000), ground=(6, 6, 8)) -> Image.Image:
    """A generic cartoon mascot on the surface colour (not any existing meme)."""
    w, h = size
    img = Image.new("RGB", size, ground)
    d = ImageDraw.Draw(img)
    d.ellipse([w * 0.10, h * 0.12, w * 0.92, h * 0.94], fill=(214, 128, 46), outline=(120, 66, 20), width=8)
    for ex in (0.34, 0.66):
        d.ellipse([w * ex - w * 0.11, h * 0.36 - w * 0.11, w * ex + w * 0.11, h * 0.36 + w * 0.11], fill=(250, 250, 246), outline=(30, 20, 10), width=6)
        d.ellipse([w * ex - w * 0.04, h * 0.37 - w * 0.04, w * ex + w * 0.04, h * 0.37 + w * 0.04], fill=(20, 14, 10))
    d.line([(w * 0.28, h * 0.22), (w * 0.44, h * 0.26)], fill=(30, 20, 10), width=12)
    d.line([(w * 0.72, h * 0.22), (w * 0.56, h * 0.26)], fill=(30, 20, 10), width=12)
    d.arc([w * 0.32, h * 0.58, w * 0.68, h * 0.84], 200, 340, fill=(30, 20, 10), width=12)
    return img


def photo_band(*, size=(1080, 640), hue=(90, 70, 60)) -> Image.Image:
    """A dark photo-like band (soft blobs), a neutral 'a photograph' stand-in."""
    w, h = size
    img = _vgrad(size, tuple(max(0, c // 3) for c in hue), (10, 10, 12))
    d = ImageDraw.Draw(img)
    d.ellipse([w * 0.30, h * 0.14, w * 0.74, h * 0.86], fill=hue)
    d.ellipse([w * 0.40, h * 0.30, w * 0.50, h * 0.44], fill=(230, 220, 200))
    d.ellipse([w * 0.56, h * 0.30, w * 0.66, h * 0.44], fill=(230, 220, 200))
    return img.filter(ImageFilter.GaussianBlur(4))


def photo_paper(*, size=(900, 700), sky=(150, 190, 220), ground=(96, 140, 96)) -> Image.Image:
    """A light, generic landscape-like photo fragment for paper-style collage pieces."""
    w, h = size
    img = _vgrad(size, sky, (230, 236, 244))
    d = ImageDraw.Draw(img)
    d.ellipse([w * 0.62, h * 0.12, w * 0.80, h * 0.12 + w * 0.18], fill=(250, 226, 130))
    d.polygon([(0, h), (0, h * 0.62), (w * 0.35, h * 0.46), (w * 0.7, h * 0.66), (w, h * 0.5), (w, h)], fill=ground)
    return img


def screenshot_card(*, size=(900, 1100)) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, (243, 245, 248))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, h * 0.09], fill=(220, 224, 231))
    for i in range(3):
        d.ellipse([w * 0.03 + i * w * 0.05, h * 0.03, w * 0.03 + i * w * 0.05 + h * 0.03, h * 0.06], fill=(170, 176, 186))
    for i, frac in enumerate((0.9, 0.7, 0.8, 0.5)):
        y = h * (0.16 + i * 0.13)
        d.rounded_rectangle([w * 0.06, y, w * 0.06 + w * 0.88 * frac, y + h * 0.07], radius=14, fill=(206, 212, 222))
    return img


def app_tile(ground: tuple[int, int, int], *, size=(1000, 1200)) -> Image.Image:
    """A large rounded app-icon-like tile bleeding to the edge of its region, on the surface colour."""
    w, h = size
    img = Image.new("RGB", size, ground)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([w * 0.20, h * 0.10, w * 1.10, h * 0.88], radius=int(w * 0.14), fill=(18, 44, 70))
    d.rounded_rectangle([w * 0.20, h * 0.60, w * 1.10, h * 0.88], radius=int(w * 0.14), fill=(212, 64, 62))
    d.ellipse([w * 0.42, h * 0.22, w * 0.90, h * 0.22 + w * 0.48], outline=(240, 244, 248), width=int(w * 0.03))
    return img
