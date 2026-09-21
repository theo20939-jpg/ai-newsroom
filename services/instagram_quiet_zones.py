"""Phase B.5R.1: deterministic QUIET-ZONE measurement for text laid directly on media (immersive family).

No ML, no overlay. For a zone of the (already cropped/scaled) image it measures
  * luminance: mean and the 10th / 90th percentile,
  * busyness: luminance standard deviation and edge energy (mean absolute neighbour difference),
  * WCAG-style contrast of light text against the BRIGHTEST decile and of dark text against the DARKEST decile.
A zone is quiet for a text colour only if that worst-case contrast is high enough AND the zone is not busy.
`select_text_zone` ranks candidate zones deterministically and returns None when no zone is usable: the
caller must then fail closed (pure media slide, or 'not suitable for immersive image field') - it must
never rescue an unreadable image with a translucent layer.

The same measurement is used by the renderer (services/instagram_declarative_layout.py) to accept or
reject `on_media` text, so planning and rendering can never disagree."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from PIL import Image

MIN_CONTRAST = 4.5     # worst-case contrast ratio (light/dark text vs the brightest/darkest decile)
MAX_LUMA_STD = 46.0    # standard deviation of luminance inside the zone
MAX_EDGE_ENERGY = 14.0  # mean absolute neighbour difference on a 96px-wide sample of the zone

# Candidate text zones (normalized x, y, w, h). Names are the vocabulary reported in manifests.
NAMED_ZONES: dict[str, tuple[float, float, float, float]] = {
    "top-left": (0.07, 0.06, 0.62, 0.30),
    "top-right": (0.31, 0.06, 0.62, 0.30),
    "bottom-left": (0.07, 0.58, 0.62, 0.28),
    "bottom-right": (0.31, 0.58, 0.62, 0.28),
    "left-column": (0.07, 0.10, 0.40, 0.66),
    "right-column": (0.53, 0.10, 0.40, 0.66),
}


def _lin(v: float) -> float:
    c = v / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def contrast_ratio(luma_a: float, luma_b: float) -> float:
    la, lb = _lin(luma_a), _lin(luma_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


@dataclass(frozen=True)
class ZoneMeasure:
    name: str
    box: tuple[float, float, float, float]
    mean: float
    p10: int
    p90: int
    std: float
    edge_energy: float
    contrast_light_text: float  # white text vs the brightest decile
    contrast_dark_text: float   # near-black text vs the darkest decile
    text_colour: str | None     # "light" | "dark" | None (not usable)
    quiet: bool

    def as_dict(self) -> dict:
        d = asdict(self)
        d["box"] = [round(v, 3) for v in self.box]
        for k in ("mean", "std", "edge_energy", "contrast_light_text", "contrast_dark_text"):
            d[k] = round(float(d[k]), 2)
        return d


def measure_zone(image: Image.Image, box_px: tuple[int, int, int, int], *, name: str = "zone") -> ZoneMeasure:
    x0, y0, x1, y1 = box_px
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(image.width, max(x1, x0 + 1)), min(image.height, max(y1, y0 + 1))
    crop = image.crop((x0, y0, x1, y1)).convert("L")
    hist = crop.histogram()
    total = sum(hist) or 1
    mean = sum(i * c for i, c in enumerate(hist)) / total
    var = sum(c * (i - mean) ** 2 for i, c in enumerate(hist)) / total

    def pct(q: float) -> int:
        target, acc = q * total, 0
        for i, c in enumerate(hist):
            acc += c
            if acc >= target:
                return i
        return 255

    p10, p90 = pct(0.10), pct(0.90)
    sample = crop.resize((96, max(2, round(96 * crop.height / max(1, crop.width)))), Image.Resampling.BILINEAR)
    px = list(sample.getdata())
    w, h = sample.size
    diffs = [abs(px[y * w + x] - px[y * w + x + 1]) for y in range(h) for x in range(w - 1)]
    diffs += [abs(px[y * w + x] - px[(y + 1) * w + x]) for y in range(h - 1) for x in range(w)]
    edge = sum(diffs) / max(1, len(diffs))
    c_light, c_dark = contrast_ratio(255, p90), contrast_ratio(p10, 12)
    calm = var ** 0.5 <= MAX_LUMA_STD and edge <= MAX_EDGE_ENERGY
    colour = None
    if calm and (c_light >= MIN_CONTRAST or c_dark >= MIN_CONTRAST):
        colour = "light" if c_light >= c_dark else "dark"
    return ZoneMeasure(name, (x0 / image.width, y0 / image.height, (x1 - x0) / image.width, (y1 - y0) / image.height),
                       mean, p10, p90, var ** 0.5, edge, c_light, c_dark, colour, colour is not None)


@dataclass(frozen=True)
class ZoneSelection:
    selected: ZoneMeasure | None
    reports: tuple[ZoneMeasure, ...]
    why: str

    @property
    def eligible(self) -> bool:
        return self.selected is not None


def select_text_zone(
    canvas_image: Image.Image, *, zones: dict[str, tuple[float, float, float, float]] | None = None,
    subject_focus: tuple[float, float] | None = None, avoid: tuple[float, float, float, float] | None = None,
) -> ZoneSelection:
    """Deterministically pick the quietest usable candidate zone of an image already fitted to the slide canvas.
    Ranking: usable colour, then calm (lower busyness), then farther from the subject focus, then fixed name order."""
    zones = zones or NAMED_ZONES
    reports: list[ZoneMeasure] = []
    for name, (x, y, w, h) in zones.items():
        if avoid is not None:  # a zone that would overlap the reserved logo zone is not a candidate
            ix = min(x + w, avoid[2]) - max(x, avoid[0])
            iy = min(y + h, avoid[3]) - max(y, avoid[1])
            if ix > 0 and iy > 0:
                continue
        box = (round(x * canvas_image.width), round(y * canvas_image.height), round((x + w) * canvas_image.width), round((y + h) * canvas_image.height))
        reports.append(measure_zone(canvas_image, box, name=name))
    usable = [r for r in reports if r.quiet]
    if not usable:
        return ZoneSelection(None, tuple(reports), "no candidate zone is both calm and high-contrast for light or dark text; not suitable for text on this image")

    def rank(r: ZoneMeasure) -> tuple:
        busyness = r.std / MAX_LUMA_STD + r.edge_energy / MAX_EDGE_ENERGY
        far = 0.0
        if subject_focus is not None:
            cx, cy = r.box[0] + r.box[2] / 2, r.box[1] + r.box[3] / 2
            far = -((cx - subject_focus[0]) ** 2 + (cy - subject_focus[1]) ** 2) ** 0.5
        return (round(busyness, 2), round(far, 2), list(zones).index(r.name))

    best = sorted(usable, key=rank)[0]
    why = (f"{best.name}: calmest usable zone (std {best.std:.0f}, edge {best.edge_energy:.1f}); "
           f"{best.text_colour} text reaches {max(best.contrast_light_text, best.contrast_dark_text):.1f}:1 against its worst-case pixels")
    return ZoneSelection(best, tuple(reports), why)
