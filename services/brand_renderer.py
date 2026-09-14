"""NINJA PULSE Visual System v1 - programmatic Brand Renderer.

NOT an image-generation model - Pillow only (already an installed project dependency; no
cairosvg/svglib/reportlab added, per the checkpoint's own "prefer existing installed library, no
heavy new dependency" instruction). Consumes an already-selected media candidate's raw bytes (or,
for DATA/QUOTE, no source photo at all) - never searches, ranks, fetches, or selects media itself,
never calls the LLM Gateway, never decides relevance.

Official assets only (assets/brand/nnj_logo.svg / nnj_logo_red.svg / nnj_logo.png) - no drawn/
generated/reconstructed "N" mark anywhere in this file. `nnj_logo.svg` and `nnj_logo_red.svg` are
confirmed byte-identical wordmark-path geometry on a transparent background, differing only in
`fill` (#FFFFFF vs #ED1C24) - `_OFFICIAL_NNJ_RED` is extracted directly from that fill value
(a text/attribute read, never a pixel operation). `nnj_logo.png`, by direct pixel inspection, is a
DIFFERENT, already-composited asset - a red rounded-square badge with the white wordmark and its
accent dot baked in (not a transparent, independently-recolorable wordmark like the SVGs; a real
forensic finding, report §"NNJ official asset handling"). No SVG rasterizer is installed
(cairosvg/svglib), so this module cannot rasterize the transparent SVG wordmark at all - it uses
`nnj_logo.png` strictly AS-IS, unmodified, for every placement (NEWS/BREAKING/DATA/QUOTE alike).
An earlier version of this module attempted to "recolor" the PNG by remapping RGB channels to
`_OFFICIAL_NNJ_RED` for a red-badge variant - caught by this module's own test suite as producing
a corrupted flat-red blob (the recolor doesn't distinguish the badge's own red background from its
white wordmark) and removed; exactly the "fake variant" the spec's own asset rules prohibit. NEWS/
BREAKING/QUOTE/RECAP all still use `nnj_logo.png` strictly AS-IS via `_paste_logo()`, only ONE
brand-mark placement, never a separate white/red choice - unchanged by the exception below.

Phase V2.20A exception: DATA's own bottom-only pulse+logo signature needs a real adaptive white/
red choice (the approved DATA template's own explicit requirement), which the pre-composited
`nnj_logo.png` badge cannot provide. It reuses `services/nnj_master_news_mark.py::
rasterize_nnj_mark()` instead - the same exact-path-geometry SVG rasterizer MASTER NEWS's own
lower signature already uses (`assets/brand/nnj_logo.svg` white / `nnj_logo_red.svg` red,
byte-identical geometry, differing only in fill) - never a redrawn/approximated/generated glyph.

Typography: Pillow's own bundled scalable default font only (`ImageFont.load_default(size=...)`,
Pillow >=10) - always available, no download, no font file shipped in output, no per-OS system
font dependency (a hard requirement for portability between this dev machine and the VPS). An
optional `brand_font_path` config value can point at a project-approved TTF later; unset by
default.

Fail-safe (spec §29, non-negotiable): every public render function catches its own exceptions and
never raises past `render_branded_media()` - a rendering problem always degrades to "use the
original, unbranded media" at the caller (worker/content_cycle.py), never blocks delivery.
"""
from __future__ import annotations

import io
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFont, ImageStat

from core.config import settings
from services import nnj_board_metrics as _bm
from services.data_source_classification import DataPresentationMode
from services.nnj_master_news_mark import rasterize_nnj_mark
from services.nnj_master_news_overlay import (
    BoundingBox,
    ComponentPlacement,
    _CANVAS_H,
    _CANVAS_W,
    _EDGE_DENSITY_SAFE_THRESHOLD,
    _DETAIL_RISK_MAX_PCT,
    _GAP_FRAC,
    _LOWER_LINE_THICKNESS_FRAC,
    _LOWER_MARK_W_FRAC,
    _LOWER_PULSE_H_FRAC,
    _LOWER_PULSE_W_FRAC,
    _LOWER_TOTAL_WIDTH_FRAC,
    _SAFE_INSET_FRAC,
    _SCORE_PAD_PX_FRAC,
    _VISIBILITY_MIN_DISTANCE,
    _draw_pulse,
    _fit_photo_to_canvas,
    _rects_intersect,
    _region_box,
    _score_region,
)
from services.presentation_director import BREAKING, DATA, NEWS, QUOTE, DataCandidate, QuoteCandidate

logger = logging.getLogger(__name__)

TEMPLATE_NEWS = "pulse-news-v1"
TEMPLATE_BREAKING = "pulse-breaking-v1"
TEMPLATE_DATA = "pulse-data-v1"
TEMPLATE_QUOTE = "pulse-quote-v1"

_TEMPLATE_BY_PRESENTATION_TYPE = {
    NEWS: TEMPLATE_NEWS, BREAKING: TEMPLATE_BREAKING, DATA: TEMPLATE_DATA, QUOTE: TEMPLATE_QUOTE,
}

_BRAND_ASSET_DIR = Path("assets/brand")
_LOGO_SVG_PATH = _BRAND_ASSET_DIR / "nnj_logo.svg"
_LOGO_RED_SVG_PATH = _BRAND_ASSET_DIR / "nnj_logo_red.svg"
_LOGO_PNG_PATH = _BRAND_ASSET_DIR / "nnj_logo.png"

# FOUNDER-VISUAL-POLISH-2 §4: a source that exactly matches one of our KNOWN internal NNJ-branded
# templates already carries a canonical NNJ mark, so the renderer must add none of its own
# (FINAL_VISIBLE_NNJ_COUNT <= 1). Deterministic content match - the reliable path for our OWN
# templates; for arbitrary external images upstream must pass explicit `source_already_branded=True`
# metadata - the renderer never guesses on an external photo.
def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def source_carries_canonical_nnj(source_image_bytes: bytes) -> bool:
    """True iff `source_image_bytes` is a KNOWN internal NNJ-branded template (exact content
    match). Deterministic, no pixel heuristic. Returns False for any external / unknown image -
    those must be flagged by upstream `source_already_branded` metadata, never guessed here."""
    known = _resolve_known_internal_branded_sha256()
    return _sha256_bytes(source_image_bytes) in known


_INTERNAL_BRANDED_TEMPLATE_PATHS: tuple[Path, ...] = (
    _BRAND_ASSET_DIR / "newsroom_visuals" / "v1" / "references" / "data" / "data_template_white.png",
    _BRAND_ASSET_DIR / "newsroom_visuals" / "v1" / "references" / "data" / "data_template_red.png",
)
_known_internal_branded_sha_cache: list[frozenset[str]] = []


def _resolve_known_internal_branded_sha256() -> frozenset[str]:
    if _known_internal_branded_sha_cache:
        return _known_internal_branded_sha_cache[0]
    shas = set()
    for p in _INTERNAL_BRANDED_TEMPLATE_PATHS:
        try:
            shas.add(_sha256_bytes(p.read_bytes()))
        except OSError:
            continue
    resolved = frozenset(shas)
    _known_internal_branded_sha_cache.append(resolved)
    return resolved

# Extracted directly from assets/brand/nnj_logo_red.svg's own single `fill="#ED1C24"` (module
# docstring) - never guessed, never a generic "brand red." See report §15 for the extraction
# evidence (both SVGs verified byte-identical geometry, differing only in this fill value).
_OFFICIAL_NNJ_RED = (0xED, 0x1C, 0x24)
_OFFICIAL_NNJ_WHITE = (0xFF, 0xFF, 0xFF)
_OFFICIAL_NNJ_BLACK = (0x00, 0x00, 0x00)

_CARD_WIDTH = 1200
_CARD_HEIGHT = 675  # 16:9 - a conventional Telegram link-preview/photo aspect ratio, not the
# source photo's own aspect ratio (DATA/QUOTE have no source photo to preserve).

# Real forensic finding: Pillow's own bundled default font (`ImageFont.load_default()`) has NO
# Cyrillic glyphs and no em-dash (confirmed empirically - tofu boxes) - a hard problem for RU
# headlines/quotes, and no font file ships with any installed dependency (no matplotlib, no
# bundled TTF anywhere in site-packages - checked directly). Never downloaded: these are common
# OS-provided font paths only (Windows always ships Arial; DejaVu Sans/Liberation Sans are the
# typical Linux-server-distro defaults, commonly pre-installed via `fonts-dejavu-core`/
# `fonts-liberation`) - exactly like a browser opportunistically using whatever the OS provides,
# never a font file this project bundles or distributes. `settings.brand_font_path` can pin an
# exact path; unset (default) tries this list, then falls back to Pillow's own ASCII-only default
# font (degraded Cyrillic rendering, never a crash, never blocked delivery - report §"known
# limitations": VPS Cyrillic rendering is UNVERIFIED, no VPS access this checkpoint).
_FONT_CANDIDATE_PATHS: tuple[str, ...] = (
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)

# FOUNDER-VISUAL-OVERLAY-RECOVERY-4 §6/§12 - typography forensics: NO font file has ever been
# committed to this repo (git-history sweep) and `settings.brand_font_path` is unset by default, so
# FONT_SOURCE = UNKNOWN - the exact Founder-board typeface cannot be recovered from any project
# asset. The board's number/label hierarchy is fundamentally *weight*-driven (heavy value, medium
# label), and the renderer previously could not render a bold face at all (`bold=` was a documented
# no-op). Closest existing match, no download, same "opportunistically use whatever the OS ships"
# rule already used for the regular face: the OS-provided BOLD companions of the same families
# (Arial Bold on Windows; Liberation Sans Bold / DejaVu Sans Bold on the Linux VPS). Reported as a
# disclosed gap - a real condensed grotesque would still need a Founder-supplied font asset.
_FONT_BOLD_CANDIDATE_PATHS: tuple[str, ...] = (
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
)

# FOUNDER-VISUAL-BREAKING-DATA-RECONSTRUCTION-5 §13: the Founder board's DATA hero number ("500" /
# "МЛН") is a HEAVY near-black grotesque - Arial Bold is visibly too light. Typography comparison
# sheet (07_TYPOGRAPHY_COMPARISON.png): the closest existing OS face is Arial Black
# (`ariblk.ttf`) - near-circular zeros, heavy stems, clean Cyrillic - degrading to the bold face
# on the Linux VPS (no black-weight OS grotesque ships there). FONT_MATCH_CONFIDENCE = MEDIUM: a
# true condensed black grotesque still needs a Founder-supplied font asset (disclosed gap).
_FONT_HEAVY_CANDIDATE_PATHS: tuple[str, ...] = (
    "C:/Windows/Fonts/ariblk.ttf",
    "C:/Windows/Fonts/segoeuiz.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
)

_font_path_resolution: list[str | None] = []  # single-element cache; [] means "not yet resolved"
_font_bold_path_resolution: list[str | None] = []
_font_heavy_path_resolution: list[str | None] = []


def _resolve_font_path() -> str | None:
    if _font_path_resolution:
        return _font_path_resolution[0]
    candidates = ([settings.brand_font_path] if settings.brand_font_path else []) + list(_FONT_CANDIDATE_PATHS)
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            logger.info("brand_renderer_font_resolved", extra={"font_path": candidate})
            _font_path_resolution.append(candidate)
            return candidate
    logger.warning("brand_renderer_no_cyrillic_font_found_using_ascii_only_default")
    _font_path_resolution.append(None)
    return None


def _resolve_bold_font_path() -> str | None:
    """Closest existing BOLD face (§6). Falls back to the regular face when the OS ships no bold
    companion - never downloads, never blocks a render."""
    if _font_bold_path_resolution:
        return _font_bold_path_resolution[0]
    candidates = (
        [settings.brand_font_bold_path] if getattr(settings, "brand_font_bold_path", None) else []
    ) + list(_FONT_BOLD_CANDIDATE_PATHS)
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            logger.info("brand_renderer_bold_font_resolved", extra={"font_path": candidate})
            _font_bold_path_resolution.append(candidate)
            return candidate
    _font_bold_path_resolution.append(_resolve_font_path())  # graceful: reuse the regular face
    return _font_bold_path_resolution[0]


def _resolve_heavy_font_path() -> str | None:
    """Closest existing HEAVY / black-weight face for the DATA hero number (§13). Falls back to the
    bold face, then the regular face - never downloads."""
    if _font_heavy_path_resolution:
        return _font_heavy_path_resolution[0]
    candidates = (
        [settings.brand_font_heavy_path] if getattr(settings, "brand_font_heavy_path", None) else []
    ) + list(_FONT_HEAVY_CANDIDATE_PATHS)
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            logger.info("brand_renderer_heavy_font_resolved", extra={"font_path": candidate})
            _font_heavy_path_resolution.append(candidate)
            return candidate
    _font_heavy_path_resolution.append(_resolve_bold_font_path())
    return _font_heavy_path_resolution[0]


@dataclass(frozen=True)
class RenderResult:
    success: bool
    image_bytes: bytes | None
    template_version: str
    fallback_reason: str | None
    duration_ms: float


def _font(
    size: int, *, bold: bool = False, heavy: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    # NEWS / QUOTE / RECAP typography (frozen this phase): OS-provided faces, graceful degradation.
    if heavy:
        font_path = _resolve_heavy_font_path()
    elif bold:
        font_path = _resolve_bold_font_path()
    else:
        font_path = _resolve_font_path()
    if font_path is not None:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            logger.warning("brand_renderer_font_load_failed", extra={"font_path": font_path})
    return ImageFont.load_default(size=size)


# FOUNDER-VISUAL-BOARD-REBUILD-6 §7/§19: the DATA hero renderer uses a PROJECT-BUNDLED font
# (assets/brand/fonts/, SIL OFL 1.1 - see that folder's README), NEVER an OS face, so dev
# (Windows) and production (Linux) render byte-identically - WINDOWS_RENDER_FONT == LINUX_RENDER_FONT
# is true by construction (one committed file, path resolved relative to the repo root).
_DATA_FONT_DIR = _BRAND_ASSET_DIR / "fonts"
_DATA_FONT_FILES: dict[str, str] = {
    "black": "FiraSansCondensed-Black.ttf",
    "bold": "FiraSansCondensed-Bold.ttf",
    "semibold": "FiraSansCondensed-SemiBold.ttf",
    "medium": "FiraSansCondensed-Medium.ttf",
    "regular": "FiraSansCondensed-Regular.ttf",
}
_data_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def data_font_path(weight: str = "regular") -> Path:
    """The absolute path of the bundled DATA font for `weight` - the single source of truth for
    `WINDOWS_RENDER_FONT == LINUX_RENDER_FONT` (§19)."""
    return (_DATA_FONT_DIR / _DATA_FONT_FILES.get(weight, _DATA_FONT_FILES["regular"])).resolve()


def _data_font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = (weight, int(size))
    hit = _data_font_cache.get(key)
    if hit is not None:
        return hit
    path = _DATA_FONT_DIR / _DATA_FONT_FILES.get(weight, _DATA_FONT_FILES["regular"])
    try:
        font = ImageFont.truetype(str(path), size)
        _data_font_cache[key] = font
        return font
    except OSError:
        logger.warning("brand_renderer_bundled_data_font_missing", extra={"path": str(path)})
        return _font(size, heavy=(weight == "black"), bold=(weight in ("bold", "semibold", "medium")))


def _load_logo_png() -> Image.Image:
    with Image.open(_LOGO_PNG_PATH) as img:
        return img.convert("RGBA").copy()


def load_brand_mark() -> Image.Image:
    """Returns the official NNJ mark exactly as shipped in `assets/brand/nnj_logo.png` (480x480
    RGBA, 1:1 - never stretched, never re-geometried, never recolored). See module docstring for
    why this module has no separate white/red mark variant."""
    return _load_logo_png()


def _paste_logo(canvas: Image.Image, *, target_width: int, margin: int) -> None:
    logo = load_brand_mark()
    scale = target_width / logo.width
    target_height = round(logo.height * scale)
    logo = logo.resize((target_width, target_height), Image.Resampling.LANCZOS)
    x = canvas.width - target_width - margin
    y = canvas.height - target_height - margin
    canvas.alpha_composite(logo, (x, y))


def _paste_svg_mark(canvas: Image.Image, *, target_width: int, margin: int) -> None:
    """PRESENTATION RECOVERY (2026-09-02): the canonical mark authority for BREAKING/QUOTE,
    replacing `_paste_logo()` - pastes `rasterize_nnj_mark()`'s output (the same SVG rasterizer/
    path geometry MASTER NEWS's own upper/lower signatures and DATA's adaptive mark already use)
    instead of the separate, pre-composited `nnj_logo.png` badge, converging every real-production
    NEWS-family renderer onto one logo asset. Position (bottom-right corner, same margin
    convention `_paste_logo()` already used) is intentionally unchanged - only the asset/rendering
    method is unified, never each type's own existing layout choice. `render_news_hero()` (dead/
    unreachable from the real send path - see its own call-site audit) is left on `_paste_logo()`
    unchanged; it is out of scope for this migration."""
    mark = rasterize_nnj_mark(target_width=target_width, red=True)
    x = canvas.width - mark.width - margin
    y = canvas.height - mark.height - margin
    canvas.alpha_composite(mark, (x, y))


def _draw_pulse_line(draw: ImageDraw.ImageDraw, *, x: int, y: int, width: int, color: tuple[int, int, int], line_width: int = 3) -> None:
    """A simple abstract heartbeat/pulse waveform - accent only, deliberately not logo-like
    (module docstring's own "never a new logo-like symbol" rule)."""
    segment = width / 8
    points = [
        (x, y), (x + segment * 2, y), (x + segment * 3, y - width * 0.12),
        (x + segment * 4, y + width * 0.16), (x + segment * 5, y), (x + width, y),
    ]
    draw.line(points, fill=color, width=line_width, joint="curve")


# ==================================================================================================
# FOUNDER-VISUAL-BREAKING-DATA-RECONSTRUCTION-5 §7/§8/§9(D) - the NINJA PULSE waveform, reconstructed
# DIRECTLY from `docs/founder_telegram_board.png` (visual authority #1).
#
# Asset forensics (re-run this phase, design/founder_visual_breaking_data_fix_5_asset_inventory.md):
# the tracked image set IS the complete historical set (no deleted image blob has ever existed);
# there is still NO vector pulse asset and NO font file. The only BREAKING raster
# (`overlays/breaking/breaking_minimal_01.png`) is FOUND_REJECTED. The RECOVERY-4 waveform - a
# hand-set P-QRS-T loosely off the 4:5 `universal_minimal_01.png` - was itself REJECTED by the
# Founder as "still crude / mechanically constructed". So per §9 option D the geometry below is a
# faithful pixel-trace of the board's OWN BREAKING pulse:
#   - baseline sits at the photo's bottom edge; the S-wave dips just past it
#   - the complex is LEFT-anchored (QRS in roughly x 0.24..0.42 of the drawn span), then a flat tail
#   - measured amplitude ratios: R apex +20px, S trough -14px  ->  S/R ~= 0.70
#     P bump ~0.26 R, T bump ~0.29 R ; R apex at x ~= 0.341 of the drawn span (BOARD-REBUILD-6)
#   - drawn span ~= 0.425 of the photo width; thin, clean, consistent stroke (not exaggerated)
# The retired `flat -> spike -> valley -> flat` `_draw_pulse` polyline is used only by the FROZEN
# NEWS / DATA-source lower signature.
#
# FINAL-BOARD-MATCH-7 §5: re-measured same-scale - the line reads as a RESTRAINED LOWER-MEDIA
# BRANDED LINE WITH A COMPACT PULSE EVENT, not a standalone ECG. x in [0, 1] spans the drawn line;
# y in "R apex == 1.0" units (baseline 0, up = positive). Board proportions:
#   calm baseline before the complex   ~= 0.23 of the line   (_bm.BREAKING.pulse_pre_flat_frac)
#   the P-QRS-T complex                 ~= 0.28 of the line   (_bm.BREAKING.pulse_complex_frac)
#   a LONG calm tail after              ~= 0.49 of the line
#   R apex inside the complex at 0.341  (_bm.BREAKING.pulse_apex_at_frac)  ->  line x ~= 0.325
_PULSE_WAVEFORM_UNIT: tuple[tuple[float, float], ...] = (
    (0.000, 0.000), (0.120, 0.000), (0.210, 0.000),                    # calm baseline (0.23)
    (0.235, 0.040), (0.262, 0.240), (0.286, 0.060),                    # P wave
    (0.300, -0.050), (0.315, -0.090),                                  # Q dip
    (0.322, 0.520), (0.325, 1.000),                                    # R rise (sharp, narrow)
    (0.333, 0.360), (0.348, -0.720),                                   # S plunge (deep, S/R ~= 0.72)
    (0.362, -0.360), (0.386, -0.080), (0.410, 0.000),                  # recovery
    (0.442, 0.090), (0.475, 0.230), (0.505, 0.130), (0.525, 0.030), (0.545, 0.000),  # T wave
    (0.650, 0.000), (0.780, 0.000), (0.900, 0.000), (1.000, 0.000),    # long calm tail (0.49)
)


def _catmull_rom(points: list[tuple[float, float]], samples_per_segment: int = 14) -> list[tuple[float, float]]:
    """Centripetal Catmull-Rom spline through `points` (>= 2). Pure `math`, no numpy. Used only to
    smooth an already-fixed control path for antialiased rendering - it introduces NO new data,
    only sub-pixel curvature between the given control points."""
    if len(points) < 3:
        return list(points)
    pts = [points[0], *points, points[-1]]
    out: list[tuple[float, float]] = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for s in range(samples_per_segment):
            t = s / samples_per_segment
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t
                       + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                       + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t
                       + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                       + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            out.append((x, y))
    out.append(points[-1])
    return out


_PULSE_SUPERSAMPLE = 4


def _draw_recovered_pulse(
    base_rgba: Image.Image, *, x_left: int, baseline_y: int, span: int, amplitude: int,
    color: tuple[int, int, int], stroke: int,
    waveform: tuple[tuple[float, float], ...] = _PULSE_WAVEFORM_UNIT,
) -> None:
    """Composite the board-traced NINJA PULSE waveform (§9 D) onto `base_rgba`, LEFT-anchored at
    `x_left`, calm baseline at `baseline_y`, drawn width `span`, R apex `amplitude` px above the
    baseline (the S trough reaches ~0.7x that below it). Rendered on a 4x supersampled layer and
    LANCZOS-downscaled for a smooth, consistently-stroked, cleanly-joined line (§10) - never
    Pillow's jagged direct polyline. Proportions are preserved across aspect ratios (span/amplitude
    are supplied by the caller as fractions of the source, never derived from raw canvas pixels).
    Adds nothing but the one waveform."""
    span = max(40, span)
    amplitude = max(4, amplitude)
    stroke = max(2, stroke)
    pad = stroke * 3 + 6
    top = max(0, int(baseline_y - amplitude - pad))
    # room for the deep S undershoot, but never past the media bottom (FINAL-BOARD-MATCH-7 §5: the
    # baseline hugs the lower edge; the S may kiss it - like the board - but is not drawn off-canvas)
    bottom = min(base_rgba.height, int(baseline_y + amplitude * 0.85 + pad))
    layer_w = (span + pad * 2) * _PULSE_SUPERSAMPLE
    layer_h = max(1, (bottom - top)) * _PULSE_SUPERSAMPLE
    layer = Image.new("RGBA", (layer_w, layer_h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)

    ox = pad * _PULSE_SUPERSAMPLE  # layer-local origin of x_left
    oy = (baseline_y - top) * _PULSE_SUPERSAMPLE
    control = [
        (ox + xf * span * _PULSE_SUPERSAMPLE, oy - yf * amplitude * _PULSE_SUPERSAMPLE)
        for xf, yf in waveform
    ]
    smooth = _catmull_rom(control, samples_per_segment=16)
    ld.line(smooth, fill=(*color, 255), width=max(1, stroke * _PULSE_SUPERSAMPLE), joint="curve")

    small = layer.resize(
        (max(1, layer_w // _PULSE_SUPERSAMPLE), max(1, layer_h // _PULSE_SUPERSAMPLE)),
        Image.Resampling.LANCZOS,
    )
    base_rgba.alpha_composite(small, (int(x_left - pad), int(top)))


def _draw_code_label(draw: ImageDraw.ImageDraw, *, x: int, y: int, text: str, color: tuple[int, int, int], size: int) -> None:
    draw.text((x, y), text, font=_font(size), fill=color)


def render_news_hero(source_image_bytes: bytes, *, category: str, editorial_code: str, branding_strength: str) -> bytes:
    """Subtle NEWS branding: original source media stays the visual foundation (spec §17) - a
    small official mark + thin pulse line in one bottom corner only, never covering the subject,
    never resized/cropped/stretched. `branding_strength == "MINIMAL"` renders a smaller mark with
    no pulse line at all - the majority-case, most conservative treatment."""
    with Image.open(io.BytesIO(source_image_bytes)) as src:
        canvas = src.convert("RGBA").copy()

    short_side = min(canvas.width, canvas.height)
    margin = max(12, round(short_side * 0.025))
    logo_width = max(28, round(short_side * (0.05 if branding_strength == "MINIMAL" else 0.07)))
    _paste_logo(canvas, target_width=logo_width, margin=margin)

    if branding_strength != "MINIMAL":
        draw = ImageDraw.Draw(canvas)
        pulse_width = max(60, round(short_side * 0.14))
        pulse_x = margin
        pulse_y = canvas.height - margin - round(logo_width * 0.35)
        _draw_pulse_line(draw, x=pulse_x, y=pulse_y, width=pulse_width, color=_OFFICIAL_NNJ_RED)
        _draw_code_label(
            draw, x=margin, y=margin, text=f"{category} · {editorial_code}",
            color=_OFFICIAL_NNJ_WHITE, size=max(14, round(short_side * 0.028)),
        )

    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()


# FOUNDER-VISUAL-BOARD-REBUILD-6 §3-§5: BREAKING's lower overlay is a COMPLETE composition -
# the board-measured NINJA PULSE + a restrained LARGE grey NNJ watermark - NOT "pulse + separate
# logo". Every value comes from services/nnj_board_metrics.py :: BREAKING (pixel-measured on
# tests/fixtures/founder_breaking_media_crop.png).
_BREAKING_PULSE_WIDTH_FRAC = _bm.BREAKING.pulse_width_frac       # 0.795 of photo width (board full span)
_BREAKING_PULSE_LEFT_FRAC = _bm.BREAKING.pulse_start_frac        # 0.065 left inset
_BREAKING_PULSE_Y_FRAC = _bm.BREAKING.pulse_baseline_frac        # 0.972 (board 0.958; runtime clamps S)
_BREAKING_PULSE_AMP_FRAC = _bm.BREAKING.pulse_r_amp_frac_of_width  # 0.078 of the drawn SPAN
_BREAKING_PULSE_STROKE_FRAC = _bm.BREAKING.pulse_stroke_frac     # 0.0034 of photo width - thin
_BREAKING_SAFE_INSET_FRAC = 0.03


def _draw_breaking_watermark(photo: Image.Image, *, media_w: int, media_h: int) -> None:
    """§4: the board's restrained LARGE NNJ watermark inside the lower-right of the media - a big
    (~44% media width), low-opacity, quiet glyph integrated with the photo, adapting light/dark to
    the local content. NEVER a bright solid-red CTA logo, no badge/background. Composited from the
    canonical `rasterize_nnj_mark()` geometry, recoloured to grey + low alpha."""
    m = _bm.BREAKING
    target_w = max(48, round(m.watermark_width_frac * media_w))
    glyph = rasterize_nnj_mark(target_width=target_w, red=False)  # white geometry -> we tint it
    gw, gh = glyph.size
    right_inset = round(m.watermark_right_inset_frac * media_w)
    bottom_inset = round(m.watermark_bottom_inset_frac * media_h)
    x = media_w - right_inset - gw
    y = media_h - bottom_inset - gh
    # adapt to the local luminance of the region the glyph will sit in
    region = photo.convert("RGB").crop((max(0, x), max(0, y), min(media_w, x + gw), min(media_h, y + gh)))
    local_luma = sum(ImageStat.Stat(region).mean) / 3 if region.width and region.height else 0
    tint = m.watermark_grey_on_light if local_luma > 140 else m.watermark_grey_on_dark
    layer = Image.new("RGBA", glyph.size, (*tint, 0))
    layer.putalpha(glyph.getchannel("A").point(lambda v: round(v * m.watermark_opacity)))
    photo.alpha_composite(layer, (max(0, x), max(0, y)))


def _breaking_quieter_bottom_corner(photo: Image.Image, *, mark_w: int, mark_h: int, inset: int) -> str:
    """Pick whichever bottom corner (lower_right preferred) has the lower local detail, so the one
    restrained mark never lands on busy content. Uses the same ImageStat stddev signal the DATA
    signature scorer already uses - no new safety model."""
    w, h = photo.size
    rgb = photo.convert("RGB")
    boxes = {
        "lower_right": (w - inset - mark_w, h - inset - mark_h, w - inset, h - inset),
        "lower_left": (inset, h - inset - mark_h, inset + mark_w, h - inset),
    }
    scores = {}
    for name, (x0, y0, x1, y1) in boxes.items():
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        if x1 <= x0 or y1 <= y0:
            scores[name] = 1e9
            continue
        scores[name] = max(ImageStat.Stat(rgb.crop((x0, y0, x1, y1))).stddev)
    # lower_right wins ties (matches every other renderer's preferred corner)
    return "lower_right" if scores["lower_right"] <= scores["lower_left"] + 4.0 else "lower_left"


def render_breaking_frame(source_image_bytes: bytes | None, *, category: str, editorial_code: str) -> bytes:
    """FOUNDER-VISUAL-BOARD-REBUILD-6 §3-§5: BREAKING = the source photo at NATIVE size (preserve)
    + a COMPLETE lower-media overlay composition measured from `docs/founder_telegram_board.png`:
    the board NINJA PULSE (short, LEFT-anchored, along the lower edge, deep S undershoot) AND a
    restrained LARGE grey NNJ watermark in the lower-right (adaptive light/dark, low opacity, quiet,
    integrated - never a bright red CTA mark). Distinct from NEWS (no pulse).

    Forbidden and absent: the retired ~22% dark band, a baked "BREAKING" wordmark, a red accent
    rule, any banner. `category`/`editorial_code` are accepted for dispatch symmetry but never
    drawn. No source photo -> a minimal solid NNJ-black card carrying only the one restrained mark
    (never blocks BREAKING delivery)."""
    if source_image_bytes is None:
        card = Image.new("RGBA", (_CARD_WIDTH, _CARD_HEIGHT), (*_OFFICIAL_NNJ_BLACK, 255))
        _draw_breaking_watermark(card, media_w=_CARD_WIDTH, media_h=_CARD_HEIGHT)
        out = io.BytesIO()
        card.convert("RGB").save(out, format="JPEG", quality=92)
        return out.getvalue()

    with Image.open(io.BytesIO(source_image_bytes)) as src:
        photo = src.convert("RGBA").copy()
    w, h = photo.size

    # the board NINJA PULSE: short, LEFT-anchored, along the lower media edge
    pulse_w = max(40, round(_BREAKING_PULSE_WIDTH_FRAC * w))
    x_left = max(4, round(_BREAKING_PULSE_LEFT_FRAC * w))
    pulse_y = round(_BREAKING_PULSE_Y_FRAC * h)
    amp = max(6, round(_BREAKING_PULSE_AMP_FRAC * pulse_w))
    stroke = max(2, round(_BREAKING_PULSE_STROKE_FRAC * w))
    _draw_recovered_pulse(
        photo, x_left=x_left, baseline_y=pulse_y, span=pulse_w, amplitude=amp,
        color=_OFFICIAL_NNJ_RED, stroke=stroke,
    )

    # the restrained LARGE grey NNJ watermark, lower-right
    _draw_breaking_watermark(photo, media_w=w, media_h=h)

    out = io.BytesIO()
    photo.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()


# Phase V2.17: real production text-safety fix - see _fit_single_line()/_fit_wrapped_block() below,
# still shared by render_quote_card() and (Phase V2.20) the new DATA stat block.

# Phase V2.20: DATA visual system redesign - retires the standalone dark "infographic card" (the
# old pulse-data-v1 v1: "PULSE / {category}" label, giant isolated number, boxed logo, NP-xxxx
# code, full-frame dark panel) entirely. DATA now belongs to the SAME minimal visual family as
# MASTER NEWS: the real source/editorial image stays the primary visual, and exactly ONE compact
# stat block (a single fused "value + unit" line, e.g. "2,6 млн $"/"+20%" - never a giant number
# with a small floating suffix - plus an optional short descriptor beneath it) is placed in a safe
# corner. No "PULSE / {category}" label, no NP-xxxx code, no dark full-frame card anywhere in this
# function - `category`/`editorial_code` are still accepted (dispatch-symmetry with NEWS/BREAKING/
# QUOTE in render_branded_media()) but are never drawn here.
#
# Phase V2.20A - approved-template alignment: the approved DATA mockup's own branding is BOTTOM-
# ONLY (one continuous pulse-line-then-NNJ signature, no separate upper mark at all) - a real,
# deliberate difference from MASTER NEWS's own two-component (upper mark + lower signature)
# contract. DATA therefore no longer calls apply_master_news_branding() (which always evaluates
# and can place BOTH components) - that would necessarily risk introducing the forbidden upper
# mark. Instead it reuses MASTER's own lower-level, already-tested primitives directly: safe-zone
# scoring (`_score_region`/`_region_box`/`_rects_intersect`), the canvas-fit helper
# (`_fit_photo_to_canvas`), the exact locked lower-signature geometry fractions
# (`_LOWER_TOTAL_WIDTH_FRAC` etc.), the pulse-waveform drawer (`_draw_pulse`), and the canonical
# SVG rasterizer (`rasterize_nnj_mark`) - restricted to the two BOTTOM corners only, never
# escalating to an upper corner. MASTER NEWS's own `select_master_news_branding()`/
# `apply_master_news_branding()` two-component composition is completely untouched by this.
_DATA_BLOCK_WIDTH_FRAC = 0.30  # a compact corner accent (~30% of canvas width) - never a full-frame panel
_DATA_BLOCK_MARGIN = 16
_DATA_LINE_GAP = 10
_DATA_STAT_FONT_MAX = 88
_DATA_STAT_FONT_MIN = 48
_DATA_LABEL_FONT_MAX = 26
_DATA_LABEL_FONT_MIN = 18
_DATA_LABEL_MAX_LINES = 2
# Below this measured local contrast (ImageStat stddev - the same signal nnj_master_news_overlay
# already computes for its own scoring, reused not reinvented), the source region is quiet enough
# for direct on-image text (style A, spec's "clean source area"). At/above it, a compact
# translucent backing sized to the text block only (style B/C, spec's "busy"/"extremely unsafe"
# treatments - folded into one graduated backing here rather than a 3-way branch, since both call
# for the same "backing behind the text only, never a large panel" shape) is added for readability.
_DATA_BACKING_CONTRAST_THRESHOLD = 18.0
# Approved template's own stated preference: "LEFT side when safe. Then: top-right / lower-right /
# other safe region only when necessary" - left corners tried first, right corners only as fallback.
_DATA_STAT_CANDIDATE_PLACEMENTS: tuple[ComponentPlacement, ...] = (
    ComponentPlacement.UPPER_LEFT, ComponentPlacement.LOWER_LEFT,
    ComponentPlacement.UPPER_RIGHT, ComponentPlacement.LOWER_RIGHT,
)
# Bottom-only, never upper (the approved template's own explicit "no upper NNJ mark" rule).
# LOWER_RIGHT is the canonical/preferred arrangement - it is the only corner where reading the
# frame left-to-right actually produces the approved mockup's own stated order ("pulse toward the
# left portion of the line... NNJ sits at the right end"). LOWER_LEFT is kept only as a same-
# established-pattern fallback (mirrors MASTER NEWS's own bottom-edge degradation order - glyph
# never mirrored, only the mark-first-vs-mark-last arrangement flips) for when the bottom-right
# region is unsafe, rather than dropping the brand signature outright on any bottom-right-busy
# photo (a real case - the robot-vacuum fixture's own "9to5Google" bottom-right watermark).
_DATA_SIGNATURE_CANDIDATE_PLACEMENTS: tuple[ComponentPlacement, ...] = (
    ComponentPlacement.LOWER_RIGHT, ComponentPlacement.LOWER_LEFT,
)
# Phase V2.20C - approved-template alignment (real, measured mismatch found during the final
# alignment audit against assets/brand/newsroom_visuals/v1/references/data/data_template_*.png):
# the canonical reference PNG's own bottom pulse-then-NNJ line is NOT a short corner accent - it
# spans ~82-93% of the frame width (measured directly on data_template_white.png: solid line
# pixels run from x=125 to x=1432 on a 1600px-wide reference canvas, i.e. ~82% of the full canvas
# / ~93% of the mockup's own "source image" card width) - a deliberately different, much longer
# treatment than MASTER NEWS's own compact ~32%-width corner accent (_LOWER_TOTAL_WIDTH_FRAC,
# still used AS-IS for MASTER NEWS itself, never changed). DATA gets its own width fraction here;
# every other lower-signature geometry constant (pulse size, line thickness, mark width, gap) is
# still reused UNCHANGED from nnj_master_news_overlay.py - only the total horizontal span (and
# therefore the straight-line segment's own length) differs for DATA specifically.
_DATA_SIGNATURE_FULL_WIDTH_FRAC = 0.85

# Phase V2.20D - real regression found in V2.20C's own preview evidence: scoring the ENTIRE
# ~85%-wide signature footprint as one coarse rectangle made the edge-density/detail-risk gate
# effectively require the whole bottom strip to be quiet - 4 of 6 real preview fixtures lost the
# signature entirely, even though only a thin 2-4px line actually occupies most of that width. Fix
# is geometry-aware, not a threshold change: the mark, the pulse, and the connecting line are each
# scored against their OWN real rendered footprint (see _data_signature_geometry()) - never one
# tall box for a thin horizontal line. Four-tier graceful degradation (see _select_data_signature()
# for the full search): FULL (approved ~85% width) -> SHORTENED (line trimmed from its own outer
# end, away from the mark, until its own narrow band clears) -> COMPACT (MASTER NEWS's own already-
# approved short accent width, `_LOWER_TOTAL_WIDTH_FRAC`, reused unchanged rather than inventing a
# third fraction) -> omitted only if even the compact tier's mark+pulse+line all fail. The mark and
# pulse footprints are identical across every tier and must pass at EVERY tier - only the
# connecting line's length is ever degraded, matching this phase's own explicit "the mark is the
# highest-priority protected branding component" instruction.
_DATA_SIGNATURE_COMPACT_WIDTH_FRAC = _LOWER_TOTAL_WIDTH_FRAC
_DATA_SIGNATURE_SHORTEN_STEPS = 5  # intermediate line lengths tried between the full and compact tiers


def _fit_single_line(
    draw: ImageDraw.ImageDraw, text: str, *, font_max: int, font_min: int, max_width: float,
    bold: bool = False, heavy: bool = False, data_weight: str | None = None,
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, int]:
    """Deterministically shrinks the font (within [font_min, font_max], step 4) until `text` fits
    `max_width` on one line - never a mid-character pixel clip. Returns the smallest size actually
    tried even if `font_min` still does not fit (a hard-bound caller is expected to already keep
    `text` short by construction in that rare case - this never truncates a single-line value).
    `data_weight` (§19) forces the BUNDLED DATA font at that weight."""
    def _f(sz: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        return _data_font(sz, data_weight) if data_weight else _font(sz, bold=bold, heavy=heavy)

    size = font_max
    font = _f(size)
    for candidate_size in range(font_max, font_min - 1, -4):
        font = _f(candidate_size)
        size = candidate_size
        if draw.textlength(text, font=font) <= max_width:
            break
    return font, size


def _require_single_line_fits(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    *, max_width: float, element: str,
) -> None:
    """TELEGRAM-DATA-SEMANTIC-OVERFLOW-HOTFIX-1: `_fit_single_line()` above is deliberately left
    unchanged (shared with `render_quote_card()`, out of this hotfix's scope) - it still returns
    the smallest font it tried even when that still does not fit `max_width` (its own docstring's
    disclosed fail-open behavior). The DATA hero renderer's own MANDATORY value/unit elements must
    never be DRAWN past that point - this raises instead, so `render_branded_media()`'s existing
    exception boundary converts it into `success=False` -> RENDER_FAILED -> HOLD/recovery, never a
    widened canvas, never a shrunk-below-floor font, never a clipped/overflowing draw (the real
    ASML-card defect: "% РЫНКА ЛИТОГР..." spilling past the canvas edge)."""
    measured = draw.textlength(text, font=font)
    if measured > max_width:
        raise ValueError(
            f"DATA hero {element} text does not fit its approved layout even at the minimum "
            f"font size (measured {measured:.0f}px > {max_width:.0f}px allowed): {text!r}"
        )


def _fit_wrapped_block(
    draw: ImageDraw.ImageDraw, text: str, *, font_max: int, font_min: int, max_width: int, max_lines: int,
    bold: bool = False, data_weight: str | None = None,
) -> tuple[list[str], ImageFont.FreeTypeFont | ImageFont.ImageFont, int]:
    """Deterministically fits `text` inside `max_width`/`max_lines` by shrinking the font within
    [font_min, font_max] (step 2) and word-wrapping (`_wrap_text()`) at each candidate size. If it
    still does not fit at `font_min` (content-selection has already bounded `text` upstream via
    `label[:80]`, so this is a last-resort safety net, not the primary length control), the final
    line is shortened at a word boundary with a trailing ellipsis until it fits - never a blind
    pixel clip, never a mid-character cut."""
    def _fw(sz: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        return _data_font(sz, data_weight) if data_weight else _font(sz, bold=bold)

    lines: list[str] = []
    font = _fw(font_min)
    size = font_min
    for candidate_size in range(font_max, font_min - 1, -2):
        font = _fw(candidate_size)
        size = candidate_size
        lines = _wrap_text(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return lines, font, size

    lines = _wrap_text(draw, text, font, max_width)[:max_lines]
    if lines:
        last = lines[-1]
        while last and draw.textlength(f"{last}…", font=font) > max_width:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        lines[-1] = f"{last}…" if last else "…"
    return lines, font, size


def _region_mean_rgb(photo: Image.Image, box: BoundingBox) -> tuple[float, float, float]:
    """Same whole-region mean-color measurement nnj_master_news_overlay's own _score_region()
    already computes internally for its own red-only visibility check - duplicated here (not
    imported; it is a private local inside that function's body, not a separate helper) only to
    get the mean color itself, needed here to choose BETWEEN white and red rather than test
    visibility against red alone."""
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(photo.width, x1), min(photo.height, y1)
    if x1 <= x0 or y1 <= y0:
        return (0.0, 0.0, 0.0)
    mean = ImageStat.Stat(photo.convert("RGB").crop((x0, y0, x1, y1))).mean
    return (mean[0], mean[1], mean[2])


def _pick_adaptive_data_color(mean_rgb: tuple[float, float, float]) -> tuple[int, int, int] | None:
    """Picks red on light backgrounds / white on dark backgrounds (spec's own adaptive rule),
    reusing nnj_master_news_overlay's own _VISIBILITY_MIN_DISTANCE contrast gate - never a new
    threshold. Falls back to the other color if the preferred one can't clear the gate; returns
    None (caller must then treat this placement as unsafe for TEXT specifically, distinct from
    unsafe for background content) only if neither color clears it."""
    luminance = 0.299 * mean_rgb[0] + 0.587 * mean_rgb[1] + 0.114 * mean_rgb[2]
    preferred = _OFFICIAL_NNJ_RED if luminance >= 128 else _OFFICIAL_NNJ_WHITE
    fallback = _OFFICIAL_NNJ_WHITE if preferred == _OFFICIAL_NNJ_RED else _OFFICIAL_NNJ_RED
    for color in (preferred, fallback):
        if math.dist(mean_rgb, color) >= _VISIBILITY_MIN_DISTANCE:
            return color
    return None


def _measure_data_stat_block(
    draw: ImageDraw.ImageDraw, data_candidate: DataCandidate, *, max_width: int,
) -> tuple[
    str, ImageFont.FreeTypeFont | ImageFont.ImageFont, tuple[float, float, float, float],
    list[str], ImageFont.FreeTypeFont | ImageFont.ImageFont | None, int, float,
]:
    """Fits the ONE primary stat line (value + unit fused, per the spec's own "2,6 млн $"/"+20%"-
    style examples - never rendered as a giant number with a small floating suffix) and the
    optional descriptor beneath it. Returns (primary_text, stat_font, stat_bbox, label_lines,
    label_font, label_line_height, total_block_height)."""
    unit = data_candidate.unit.strip()
    primary_text = f"{data_candidate.value} {unit.upper()}".strip() if unit else data_candidate.value
    stat_font, _size = _fit_single_line(
        draw, primary_text, font_max=_DATA_STAT_FONT_MAX, font_min=_DATA_STAT_FONT_MIN, max_width=max_width,
    )
    stat_bbox = draw.textbbox((0, 0), primary_text, font=stat_font)
    stat_height = stat_bbox[3] - stat_bbox[1]

    label_lines: list[str] = []
    label_font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None
    label_line_height = 0
    if data_candidate.label:
        label_lines, label_font, label_size = _fit_wrapped_block(
            draw, data_candidate.label, font_max=_DATA_LABEL_FONT_MAX, font_min=_DATA_LABEL_FONT_MIN,
            max_width=max_width, max_lines=_DATA_LABEL_MAX_LINES,
        )
        label_line_height = label_size + 6

    total_height = stat_height + (_DATA_LINE_GAP + len(label_lines) * label_line_height if label_lines else 0)
    return primary_text, stat_font, stat_bbox, label_lines, label_font, label_line_height, total_height


def _select_data_block_placement(
    canvas: Image.Image, *, block_w: int, block_h: int, inset: int, pad: int, avoid_box: BoundingBox | None,
) -> tuple[BoundingBox, tuple[int, int, int], bool] | None:
    """Tries the four corners in the approved template's own stated preference - LEFT side first
    (upper-left, then lower-left), right side only when necessary - reusing nnj_master_news_
    overlay's OWN _score_region() edge-density/detail-risk safety gate unchanged: a corner unsafe
    for the brand mark is unsafe for the stat block too, same real-pixel evidence, no separate
    safety model invented. A candidate box that would overlap the bottom pulse/logo signature
    (`avoid_box` - precise rectangle intersection, not a same-corner heuristic, since the two
    components are different sizes) is skipped outright.

    DATA-CARD-2: the approved template (assets/brand/newsroom_visuals/v1/references/data/
    data_template_manifest.json) has no card/backing element at all - text sits directly on the
    photo. The translucent backing is a legibility safety net for a corner whose CONTENT is safe
    (passes edge-density/detail-risk) but whose local CONTRAST is too low for readable text - it
    must stay a genuine last resort, never the automatic companion of whichever corner happens to
    be tried first. Two passes over the SAME candidate order/safety gates (no new mechanism): pass
    1 accepts only a corner that needs NO backing at all; pass 2 (only reached when no corner
    qualifies backing-free) falls back to the original single-pass behavior. Returns
    (box, text_color, needs_backing) for the winning corner, or None when no corner qualifies even
    with backing allowed - the caller must then fail safe to source+branding-only, never forcing
    the statistic onto the image (spec's own explicit requirement)."""
    canvas_w, canvas_h = canvas.size

    def _candidates() -> list[tuple[BoundingBox, tuple[int, int, int], bool]]:
        found = []
        for placement in _DATA_STAT_CANDIDATE_PLACEMENTS:
            box = _region_box((canvas_w, canvas_h), block_w, block_h, placement, inset)
            if avoid_box is not None and _rects_intersect(box, avoid_box):
                continue
            score_box = (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)
            edge_density, contrast, _red_visibility, detail_risk = _score_region(canvas, score_box, subject_bbox=None)
            if edge_density >= _EDGE_DENSITY_SAFE_THRESHOLD or detail_risk >= _DETAIL_RISK_MAX_PCT:
                continue
            color = _pick_adaptive_data_color(_region_mean_rgb(canvas, box))
            if color is None:
                continue
            found.append((box, color, contrast >= _DATA_BACKING_CONTRAST_THRESHOLD))
        return found

    candidates = _candidates()
    for box, color, needs_backing in candidates:
        if not needs_backing:
            return box, color, False
    return candidates[0] if candidates else None


@dataclass(frozen=True)
class DataSignaturePlan:
    placement: ComponentPlacement
    red: bool
    line_len: int
    tier: str  # "full" | "shortened" | "compact" | "none" (mark+pulse only, zero connecting line)


def _data_signature_line_length(canvas_w: int, width_frac: float) -> int:
    """The connecting-line length implied by a given total-signature-width fraction - pulse/mark/
    gap sizes are identical across every tier (imported MASTER fractions, unchanged); only the
    line itself grows or shrinks between tiers."""
    total_w = max(10, round(width_frac * canvas_w))
    pulse_w = max(1, round(_LOWER_PULSE_W_FRAC * canvas_w))
    mark_w = max(1, round(_LOWER_MARK_W_FRAC * canvas_w))
    gap = max(1, round(_GAP_FRAC * canvas_w))
    return max(10, total_w - pulse_w - mark_w - gap)


def _data_signature_length_candidates(full_len: int, compact_len: int) -> list[tuple[int, str]]:
    """FULL -> up to _DATA_SIGNATURE_SHORTEN_STEPS evenly-spaced intermediate SHORTENED lengths ->
    COMPACT, longest first. Degrades only the connecting line's own length - never the mark or the
    pulse - matching the phase's required FULL/SHORTENED/COMPACT/NONE fallback order exactly."""
    candidates: list[tuple[int, str]] = [(full_len, "full")]
    if full_len > compact_len:
        step = (full_len - compact_len) / (_DATA_SIGNATURE_SHORTEN_STEPS + 1)
        for i in range(1, _DATA_SIGNATURE_SHORTEN_STEPS + 1):
            length = round(full_len - step * i)
            if compact_len < length < full_len:
                candidates.append((length, "shortened"))
    candidates.append((compact_len, "compact"))
    return candidates


def _data_signature_geometry(
    canvas_size: tuple[int, int], placement: ComponentPlacement, inset: int, line_len: int,
) -> tuple[BoundingBox, BoundingBox, BoundingBox]:
    """(mark_box, pulse_box, line_box) for one DATA bottom-signature placement + connecting-line
    length - the SINGLE SOURCE OF TRUTH both the safety scorer (_select_data_signature()) and the
    real compositor (_build_data_lower_signature_image()) use, so a scored box can never silently
    drift from a drawn one. Phase V2.20D's own fix for the V2.20C regression: `line_box` is a
    NARROW horizontal band matching only the line's own rendered stroke (+ a small anti-aliasing
    margin) - never a tall rectangle spanning the mark's full height for a 2-4px line. `mark_box`/
    `pulse_box` do not depend on `line_len` at all - only the line's own extent does."""
    w, h = canvas_size
    pulse_w = max(1, round(_LOWER_PULSE_W_FRAC * w))
    pulse_h = max(1, round(_LOWER_PULSE_H_FRAC * h))
    line_thick = max(1, round(_LOWER_LINE_THICKNESS_FRAC * h))
    mark_w = max(1, round(_LOWER_MARK_W_FRAC * w))
    gap = max(1, round(_GAP_FRAC * w))
    mark_h = rasterize_nnj_mark(target_width=mark_w).height  # identical for red/white (same SVG geometry)
    y = h - inset

    if placement is ComponentPlacement.LOWER_RIGHT:
        mark_x0 = w - inset - mark_w
        pulse_end_x = mark_x0 - gap
        pulse_x0 = pulse_end_x - pulse_w
        line_end_x = pulse_x0
        line_x0 = line_end_x - line_len
    else:  # LOWER_LEFT - mark unmirrored, only the mark-first-vs-mark-last order flips
        mark_x0 = inset
        pulse_x0 = mark_x0 + mark_w + gap
        line_x0 = pulse_x0 + pulse_w
        line_end_x = line_x0 + line_len

    mark_y0 = y - mark_h // 2
    mark_box = (mark_x0, mark_y0, mark_x0 + mark_w, mark_y0 + mark_h)
    pulse_y0 = y - pulse_h // 2
    pulse_box = (pulse_x0, pulse_y0, pulse_x0 + pulse_w, pulse_y0 + pulse_h)
    line_margin = max(2, line_thick)
    line_x_min, line_x_max = min(line_x0, line_end_x), max(line_x0, line_end_x)
    line_box = (line_x_min, y - line_margin, line_x_max, y + line_margin)
    return mark_box, pulse_box, line_box


def _score_box_safe(canvas: Image.Image, box: BoundingBox, *, pad: int) -> bool:
    """True iff `box` (padded by `pad` for a statistically meaningful edge-density sample - the
    same padding nnj_master_news_overlay.py's own scoring already uses) clears the shared edge-
    density/detail-risk safety gate. Content-safety only; color/visibility is a separate check."""
    padded = (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)
    edge_density, _contrast, _visibility, detail_risk = _score_region(canvas, padded, subject_bbox=None)
    return edge_density < _EDGE_DENSITY_SAFE_THRESHOLD and detail_risk < _DETAIL_RISK_MAX_PCT


def _data_signature_anchor_box(mark_box: BoundingBox, pulse_box: BoundingBox) -> BoundingBox:
    """The mark+pulse union - see _select_data_signature()'s own docstring for why these two are
    scored TOGETHER, not as two fully separate tiny boxes."""
    return (
        min(mark_box[0], pulse_box[0]), min(mark_box[1], pulse_box[1]),
        max(mark_box[2], pulse_box[2]), max(mark_box[3], pulse_box[3]),
    )


def _select_data_signature(canvas: Image.Image, *, inset: int, pad: int) -> DataSignaturePlan | None:
    """Geometry-aware, four-tier graceful-degradation search for DATA's bottom-only branding
    (Phase V2.20D - see _DATA_SIGNATURE_COMPACT_WIDTH_FRAC's own comment for the V2.20C coarse-
    rectangle regression this replaces). Restricted to the two BOTTOM corners only (never upper -
    the approved template has no upper mark).

    Step 1: for each bottom corner, score the mark+pulse "anchor" (their union box - see
    _data_signature_anchor_box()) as ONE region, plus the adaptive color at the mark. Corners that
    fail either check are dropped entirely - this whole anchor is the highest-priority protected
    branding footprint, never degraded around, never split further.

    IMPORTANT deviation from a naive fully-independent mark/pulse split, found empirically during
    real-photo validation, not a design preference: nnj_master_news_overlay.py's shared
    _score_region() (reused unmodified, per this phase's own explicit instruction not to touch
    MASTER NEWS) always divides whatever box it is given into a fixed 4x2 sub-patch grid for its
    own worst-case scoring (Phase V2.10I). A box as small as the mark alone (~51x20px at a 1280-
    wide canvas) or the pulse alone (~48x45px) produces patches only ~12px across - far finer than
    that grid was ever calibrated for (MASTER's own combined lower-signature box, ~307-410px wide,
    produces ~77-100px patches). Confirmed directly against a real fixture (assets/brand/
    newsroom_visuals/v2_10a_overlay_fix/honor_camera_source.jpg): scoring mark and pulse as two
    separate boxes there FAILED at both bottom corners (edge_density 8-18, over the 8.0 threshold)
    even though MASTER's own real, unmodified select_master_news_branding() scores the exact same
    pixels as one combined LOWER_LEFT box and PASSES (edge_density 6.79) - i.e. a naive full split
    would have made real-photo coverage WORSE than the V2.20C regression this phase exists to fix,
    the opposite of its own explicit goal. The mark and pulse sit immediately adjacent (only the
    small `_GAP_FRAC` gap between them) and always move together at the same corner, so scoring
    their union is not a loosening of protection - it is the same real pixels MASTER's own already-
    trusted combined-box calibration was built for. The LINE below remains scored completely
    separately as its own narrow band - THAT is the literal fix this phase asked for: the thin
    connecting line no longer drags the mark+pulse anchor into one 85%-wide coarse rectangle, and
    conversely the anchor's own real calibration scale is preserved instead of over-fragmenting it.

    Step 2: for corners whose anchor passed, try line lengths longest-first (FULL -> SHORTENED ->
    COMPACT, `_data_signature_length_candidates()`), LOWER_RIGHT before LOWER_LEFT at each length -
    "prefer the orientation whose actual geometry is safer" while never settling for a shorter
    line at the canonical corner when a longer one is available at the fallback corner. Returns the
    first (placement, length) whose own narrow line band clears the gate.

    Returns None only when every bottom corner's anchor (or, for corners whose anchor passes, even
    the compact-tier line) fails - never an upper-corner escalation, never a forced/distorted mark."""
    canvas_w, canvas_h = canvas.size
    full_len = _data_signature_line_length(canvas_w, _DATA_SIGNATURE_FULL_WIDTH_FRAC)
    compact_len = _data_signature_line_length(canvas_w, _DATA_SIGNATURE_COMPACT_WIDTH_FRAC)

    anchor_color: dict[ComponentPlacement, tuple[int, int, int]] = {}
    for placement in _DATA_SIGNATURE_CANDIDATE_PLACEMENTS:
        mark_box, pulse_box, _line_box = _data_signature_geometry(canvas.size, placement, inset, full_len)
        anchor_box = _data_signature_anchor_box(mark_box, pulse_box)
        if not _score_box_safe(canvas, anchor_box, pad=pad):
            continue
        color = _pick_adaptive_data_color(_region_mean_rgb(canvas, mark_box))
        if color is None:
            continue
        anchor_color[placement] = color

    if not anchor_color:
        return None

    for length, tier in _data_signature_length_candidates(full_len, compact_len):
        for placement in _DATA_SIGNATURE_CANDIDATE_PLACEMENTS:
            if placement not in anchor_color:
                continue
            _mark_box, _pulse_box, line_box = _data_signature_geometry(canvas.size, placement, inset, length)
            if _score_box_safe(canvas, line_box, pad=pad):
                return DataSignaturePlan(
                    placement=placement, red=anchor_color[placement] == _OFFICIAL_NNJ_RED,
                    line_len=length, tier=tier,
                )

    # R2.10-FINALIZATION-1: the module's own docstring above has always claimed a "FULL/SHORTENED/
    # COMPACT/NONE fallback order", but "NONE" was never actually implemented as a candidate here -
    # the loop above simply exhausted every line length down to COMPACT and returned None outright,
    # discarding an anchor (mark+pulse) that had ALREADY independently passed the safety gate,
    # purely because every tried CONNECTING LINE crossed real busy content (root-caused against the
    # real assets/brand/newsroom_visuals/v2_10a_overlay_fix/iphone_recomposed_source.jpg fixture -
    # the hand/fingers span nearly the full width of the bottom strip, so every line length at both
    # corners failed edge-density, while each corner's own mark+pulse anchor passed comfortably).
    # "NONE" draws the mark+pulse only, with zero connecting line - `line_len=0` collapses
    # `_data_signature_geometry()`'s own line_box to a single point (`line_x0 == line_end_x`),
    # which `_build_data_lower_signature_image()` now skips drawing entirely (never a visible
    # zero-length line artifact) - so no further safety check is needed for it: nothing is drawn
    # there. Preserves the approved signature (mark+pulse remains visible, §12/§13's own explicit
    # requirement) instead of losing branding entirely on a real busy photo.
    for placement in _DATA_SIGNATURE_CANDIDATE_PLACEMENTS:
        if placement in anchor_color:
            return DataSignaturePlan(
                placement=placement, red=anchor_color[placement] == _OFFICIAL_NNJ_RED,
                line_len=0, tier="none",
            )
    return None


# MEDIA-PROD-1: fixed, never-sampled scrim behind the guaranteed-branding fallback below - the
# entire reason every real corner failed _select_data_signature()'s own scoring is that no sampled
# color could be trusted there, so legibility here is guaranteed by construction instead. Same
# alpha-blended-scrim idiom render_data_card()'s own stat-block backing already established
# (DATA-CARD-2's `backing_fill`), reused for consistency, not redesigned.
_SIGNATURE_FALLBACK_SCRIM_FILL = (0, 0, 0, 190)
_SIGNATURE_FALLBACK_SCRIM_PADDING_FRAC = 0.012


def _build_data_signature_fallback(canvas_size: tuple[int, int], *, inset: int) -> tuple[Image.Image, BoundingBox]:
    """MEDIA-PROD-1: the guaranteed-always-succeeds branding tier `_select_data_signature()`
    itself deliberately never provides - that function's own docstring contract ("never a forced/
    distorted mark") describes its real-pixel-safety-scored search only, and is intentionally left
    untouched here. Reached ONLY when that search returns `None` (both bottom corners fail even
    the mark+pulse ANCHOR itself - a strictly deeper failure than the "none" line-length tier
    above, which already covers "anchor safe, connecting line unsafe" and therefore rarely returns
    None on its own) - a DATA card must never ship with zero NNJ branding at all (this phase's own
    "every image receives final branding layer" requirement).

    A small white NNJ mark on an opaque dark scrim, sized tightly to the mark alone (no pulse, no
    connecting line - deliberately the smallest possible footprint, visually distinct from the
    real signature's full form) at the fixed, canonical LOWER_RIGHT corner - no scoring, no color
    sampling, so it cannot itself fail the way every scored candidate just did. Returns the
    composited layer plus its own real drawn bounding box, for the caller to feed to
    `_select_data_block_placement()`'s `avoid_box` exactly like the scored signature's own box."""
    w, h = canvas_size
    mark_w = max(1, round(_LOWER_MARK_W_FRAC * w))
    mark = rasterize_nnj_mark(target_width=mark_w, red=False)
    padding = max(1, round(_SIGNATURE_FALLBACK_SCRIM_PADDING_FRAC * w))

    x1, y1 = w - inset, h - inset
    x0, y0 = x1 - mark.width, y1 - mark.height
    scrim_box: BoundingBox = (x0 - padding, y0 - padding, x1 + padding, y1 + padding)

    layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.rectangle(list(scrim_box), fill=_SIGNATURE_FALLBACK_SCRIM_FILL)
    layer.alpha_composite(mark, (x0, y0))
    return layer, scrim_box


def _build_data_lower_signature_image(
    canvas_size: tuple[int, int], placement: ComponentPlacement, inset: int, *, red: bool, line_len: int,
) -> Image.Image:
    """DATA's own bottom-only pulse+NNJ signature. Reuses nnj_master_news_overlay's own locked
    MASTER_BALANCED pulse/mark/gap/line-thickness fraction constants EXACTLY (imported, never re-
    derived) via `_data_signature_geometry()` - the exact same box math `_select_data_signature()`
    just scored, so what gets drawn can never silently drift from what was verified safe.
    `line_len` is supplied by the caller's own tier search (full/shortened/compact) - this function
    has no opinion about which tier it is. Adaptively colored: MASTER's own lower signature is
    always red by its own locked contract (module docstring); the separately approved DATA
    template requires white on a dark safe region / red on a light one. Only ever called with
    LOWER_RIGHT/LOWER_LEFT - DATA has no upper mark and no upper-corner escalation. The mark itself
    is `rasterize_nnj_mark()`'s real, unmodified canonical SVG rasterization (`nnj_logo.svg` white /
    `nnj_logo_red.svg` red) - never redrawn, approximated, stretched, or substituted with text."""
    w, h = canvas_size
    color = (*_OFFICIAL_NNJ_RED, 255) if red else (*_OFFICIAL_NNJ_WHITE, 255)
    pulse_w, pulse_h = max(1, round(_LOWER_PULSE_W_FRAC * w)), max(1, round(_LOWER_PULSE_H_FRAC * h))
    line_thick = max(1, round(_LOWER_LINE_THICKNESS_FRAC * h))
    mark_w = max(1, round(_LOWER_MARK_W_FRAC * w))
    mark = rasterize_nnj_mark(target_width=mark_w, red=red)

    mark_box, pulse_box, line_box = _data_signature_geometry(canvas_size, placement, inset, line_len)
    mark_x, mark_y = mark_box[0], mark_box[1]
    pulse_x0 = pulse_box[0]
    y = h - inset
    line_x0, line_x1 = line_box[0], line_box[2]

    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # R2.10-FINALIZATION-1 ("none" tier): line_len=0 collapses line_x0/line_x1 to the same point -
    # skip drawing it outright rather than let Pillow render a degenerate zero-length line segment
    # (cosmetically near-invisible either way, but explicit is safer than relying on that).
    draw_line = line_x0 != line_x1

    if placement is ComponentPlacement.LOWER_RIGHT:
        if draw_line:
            draw.line([(line_x0, y), (line_x1, y)], fill=color, width=line_thick)
        _draw_pulse(draw, pulse_x0, y, pulse_w, pulse_h, color, line_thick)
        canvas.alpha_composite(mark, (mark_x, mark_y))
    else:  # LOWER_LEFT - built from primitives, NNJ never mirrored (same rule as MASTER NEWS)
        canvas.alpha_composite(mark, (mark_x, mark_y))
        _draw_pulse(draw, pulse_x0, y, pulse_w, pulse_h, color, line_thick)
        if draw_line:
            draw.line([(line_x0, y), (line_x1, y)], fill=color, width=line_thick)

    return canvas


# ==================================================================================================
# FOUNDER-VISUAL-BOARD-ALIGNMENT-1 - the Founder-approved GENERATED DATA "hero-metric" card.
#
# `docs/founder_telegram_board.png`, format 3 ("DATA - Инфографика с цифрами. Фирменный стиль:
# чёрный фон, красный акцент, линейный импульс, техническая сетка."): a generated dark-graphite
# infographic panel with ONE dominant primary number, unit in NNJ red, a smaller white label, a
# grey secondary line, an optional red delta pill, an optional red trend line, a subtle technical
# grid, and exactly one canonical NNJ mark. This REPLACES the retired V2.20 compact-corner-stat
# treatment for FULL_DATA_CARD only - EXISTING_INFOGRAPHIC sources still route to
# MINIMAL_SOURCE_PRESERVING (render_data_card() below, untouched), so a pre-made infographic's own
# printed metric is never converted into a hero card (Founder decision, phase §3).
# ==================================================================================================
# FOUNDER-VISUAL-CANVAS-COMPOSITION-CORRECTION-8 §2-§6: the generated DATA card is NO LONGER a
# 16:9 composition. The Founder board's DATA MEDIA rectangle (chrome excluded) is 322x295 ->
# aspect ~= 1.09, near-square. Telegram accepts non-16:9 photo media, so DATA gets its OWN
# deterministic canvas: `_HERO_CW` x `_HERO_CH` = 1280 x 1172 (width kept at the production-safe
# 1280, height = 1280 * 295 / 322). Every fraction below is re-measured against the 322x295 media
# (services/nnj_board_metrics.py :: DATA). The metric block is TOP-anchored at the board-measured
# `value_top_frac`, not vertically centred, so it does not float inside a tall canvas.
_HERO_CW = _bm.DATA.canvas_w                     # 1280
_HERO_CH = _bm.DATA.canvas_h                     # 1172  (aspect 1.0922)
_HERO_BG = _bm.DATA.bg_rgb                       # (6, 7, 9)
_HERO_GRID_COLOR = _bm.DATA.grid_rgb             # (13, 14, 17) - contrast-guarded
_HERO_MARGIN = 76
_HERO_LEFT_ZONE_FRAC = _bm.DATA.left_zone_frac   # 0.41
_HERO_VALUE_FONT_MAX = 270                       # board "500" cap = 0.163 * 1172 ~= 191px -> Fira Cond Black ~270
_HERO_VALUE_FONT_MIN = 120
_HERO_LABEL_FONT_MAX = 66                        # board label_over_value 0.188
_HERO_LABEL_FONT_MIN = 26
_HERO_LABEL_MAX_LINES = 2
_HERO_DESC_FONT_MAX = 62                         # board desc_over_value 0.21
_HERO_DESC_FONT_MIN = 22
_HERO_DESC_MAX_LINES = 3
_HERO_DESC_COLOR = (150, 154, 162)   # neutral cool grey secondary (board-measured)
_HERO_PILL_TEXT_COLOR = _OFFICIAL_NNJ_WHITE
_HERO_MARK_W_FRAC = _bm.DATA.mark_width_frac      # 0.040 - very restrained (board media shows NO mark)
_HERO_MARK_OPACITY = _bm.DATA.mark_opacity        # 0.26
_HERO_TEMPLATE = "pulse-data-hero-v4-square"


def _luma(rgb: tuple[int, int, int]) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _guarded_grid_color() -> tuple[int, int, int]:
    """§13 contrast guard: the grid line luma minus the background luma is clamped into
    [grid_luma_delta_min, grid_luma_delta_max] so the grid can never read as visible squares,
    on this board or any future re-measurement."""
    lo, hi = _bm.DATA.grid_luma_delta_min, _bm.DATA.grid_luma_delta_max
    delta = _luma(_HERO_GRID_COLOR) - _luma(_HERO_BG)
    if delta < lo or delta > hi:
        target = max(lo, min(hi, delta))
        step = target - delta
        return tuple(max(0, min(255, round(c + step))) for c in _HERO_BG)  # type: ignore[return-value]
    return _HERO_GRID_COLOR


def _draw_hero_grid(draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
    # FINAL-BOARD-MATCH-7 §9/§10: the board does NOT read as full-canvas graph paper - the grid
    # belongs to the RIGHT GRAPH ZONE and supports the chart. The LEFT text zone stays clean
    # near-black. A tiny, contrast-guarded bleed into a narrow transition band is barely perceptible.
    step = max(24, round(_bm.DATA.grid_step_frac * w))
    color = _guarded_grid_color()
    zone_x = round((_bm.DATA.graph_x_start_frac - 0.03) * w)  # a hair before the graph starts
    for gx in range(step, w, step):
        if gx >= zone_x:
            draw.line([(gx, 0), (gx, h)], fill=color, width=1)
    for gy in range(step, h, step):
        draw.line([(zone_x, gy), (w, gy)], fill=color, width=1)


def _monotone_cubic(xs: list[float], ys: list[float], samples_per_segment: int = 24) -> list[tuple[float, float]]:
    """Fritsch-Carlson monotone cubic Hermite interpolation through (xs, ys). Pure `math`.

    FOUNDER-VISUAL-OVERLAY-RECOVERY-4 §11: this is VISUAL interpolation only - it adds smooth
    curvature *between* the real series points, and its monotone construction guarantees the curve
    never overshoots the [min, max] of any adjacent pair, so it can never imply a value outside the
    supplied series. No numeric label is derived from the interpolated path; the real points remain
    the only factual anchors."""
    n = len(xs)
    if n < 3:
        return list(zip(xs, ys))
    dx = [xs[i + 1] - xs[i] for i in range(n - 1)]
    slope = [(ys[i + 1] - ys[i]) / dx[i] if dx[i] else 0.0 for i in range(n - 1)]
    m = [slope[0]] + [
        0.0 if slope[i - 1] * slope[i] <= 0 else (slope[i - 1] + slope[i]) / 2
        for i in range(1, n - 1)
    ] + [slope[-1]]
    for i in range(n - 1):
        if slope[i] == 0:
            m[i] = m[i + 1] = 0.0
            continue
        a, b = m[i] / slope[i], m[i + 1] / slope[i]
        h = math.hypot(a, b)
        if h > 3.0:
            t = 3.0 / h
            m[i], m[i + 1] = t * a * slope[i], t * b * slope[i]
    out: list[tuple[float, float]] = []
    for i in range(n - 1):
        for s in range(samples_per_segment):
            t = s / samples_per_segment
            h00 = 2 * t**3 - 3 * t**2 + 1
            h10 = t**3 - 2 * t**2 + t
            h01 = -2 * t**3 + 3 * t**2
            h11 = t**3 - t**2
            x = xs[i] + t * dx[i]
            y = h00 * ys[i] + h10 * dx[i] * m[i] + h01 * ys[i + 1] + h11 * dx[i] * m[i + 1]
            out.append((x, y))
    out.append((xs[-1], ys[-1]))
    return out


def _segmented_anchor_path(xs: list[float], ys: list[float]) -> list[tuple[float, float]]:
    """FINAL-BOARD-MATCH-7 §11-§13: a CLEAN SEGMENTED EDITORIAL LINE. The real anchors are
    connected DIRECTLY - this returns exactly the supplied `(x, y)` points, in order, and NOTHING
    else. The renderer owns STYLE (antialiasing, rounded joins, glow); the input owns SHAPE. No
    spline, no densification, no fabricated intermediate value, no synthetic wiggle, no overshoot
    (there is nothing between anchors to overshoot with)."""
    return list(zip(xs, ys))


def _draw_hero_sparkline(
    canvas: Image.Image, series: tuple[float, ...], *, box: tuple[int, int, int, int],
) -> None:
    """The board's DATA trend line (docs/founder_telegram_board.png, re-measured same-scale):
    - the RED LINE is the PRIMARY feature (§15); the under-curve tint is VERY subtle, no red wedge;
    - a small crisp white endpoint dot (§16);
    - a CLEAN SEGMENTED path (`_segmented_anchor_path`, §11-§13) - real anchors connected directly,
      antialiased with rounded joins via a 4x supersampled layer + LANCZOS; visible directional
      changes are preserved because the segments are not splined away.

    §12: `series` values are the ONLY factual anchors - exact linear x, min-max normalised y, drawn
    VERBATIM; the renderer synthesises NO points. Requires >= 2 points (guarded by the caller)."""
    x0, y0, x1, y1 = box
    pad = max(8, round(_bm.DATA.graph_endpoint_radius_frac * _HERO_CW) + 4)  # dot headroom
    y0 += pad
    lo, hi = min(series), max(series)
    span = (hi - lo) or 1.0
    n = len(series)
    anchor_xs = [x0 + (x1 - x0) * (i / (n - 1)) for i in range(n)]
    anchor_ys = [y1 - (y1 - y0) * ((v - lo) / span) for v in series]
    curve = _segmented_anchor_path(anchor_xs, anchor_ys)

    ss = _PULSE_SUPERSAMPLE
    lw, lh = (x1 - x0) * ss, (y1 - y0) * ss + ss
    layer = Image.new("RGBA", (max(1, lw), max(1, lh)), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    loc = [((cx - x0) * ss, (cy - y0) * ss) for cx, cy in curve]

    # §15 area fill: a VERY subtle tint that only hugs the underside of the segments - a bounded
    # band below the line, fast downward fade, eased off at the vertical right edge. Most of the
    # chart area stays dark; the line is the feature.
    peak = _bm.DATA.graph_fill_peak_alpha
    fall = _bm.DATA.graph_fill_falloff
    band = round((y1 - y0) * _bm.DATA.graph_fill_band_frac) * ss
    fill_poly = [*loc] + [(cx, min(lh, cy + band)) for cx, cy in reversed(loc)]
    area = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(area).polygon(fill_poly, fill=(*_OFFICIAL_NNJ_RED, 255))
    vgrad = Image.new("L", (1, layer.size[1]))
    vgrad.putdata([int(peak * (1 - j / max(1, layer.size[1] - 1)) ** fall) for j in range(layer.size[1])])
    hgrad = Image.new("L", (layer.size[0], 1))
    # gently brighter to the right, but capped well below opaque, then eased back down over the
    # last 12% so the vertical right edge never reads as a column
    hg = []
    W = layer.size[0]
    for i in range(W):
        f = i / max(1, W - 1)
        v = 55 + 120 * f ** 0.9
        if f > 0.88:
            v *= max(0.25, 1 - (f - 0.88) / 0.12)
        hg.append(int(v))
    hgrad.putdata(hg)
    mask = ImageChops.multiply(vgrad.resize(layer.size), hgrad.resize(layer.size))
    area.putalpha(ImageChops.multiply(area.getchannel("A"), mask))
    layer.alpha_composite(area)

    # the red line + a small crisp white endpoint dot (board-measured radius)
    stroke = max(2, round(_bm.DATA.graph_stroke_frac * _HERO_CW)) * ss
    ld.line(loc, fill=(*_OFFICIAL_NNJ_RED, 255), width=stroke, joint="curve")
    ex, ey = loc[-1]
    r = max(3, round(_bm.DATA.graph_endpoint_radius_frac * _HERO_CW)) * ss
    ld.ellipse([ex - r, ey - r, ex + r, ey + r], fill=(*_OFFICIAL_NNJ_WHITE, 255))

    small = layer.resize((max(1, x1 - x0), max(1, y1 - y0)), Image.Resampling.LANCZOS)
    canvas.alpha_composite(small, (x0, y0))


def render_data_hero_card(data_candidate: DataCandidate, *, source_image_bytes: bytes | None = None) -> bytes:
    """FOUNDER-VISUAL-BOARD-ALIGNMENT-1 (board format 3). A deterministic, generated dark-graphite
    DATA hero-metric card:

      - `data_candidate.value` - the dominant primary number, white, font-fitted (never invented,
        never reformatted - drawn exactly as the string given);
      - `data_candidate.unit` - directly beneath, NNJ red, uppercased, font-fitted (skipped if empty);
      - `data_candidate.label` - a smaller white line beneath, wrapped to <= 2 lines, no clipping;
      - `data_candidate.evidence_fact` - a grey secondary line drawn VERBATIM, wrapped, no clipping;
      - `data_candidate.delta` - an optional red-outlined pill (drawn only when supplied);
      - `data_candidate.series` - an optional red trend LINE (`_draw_hero_sparkline`): the real
        points are the only anchors, connected DIRECTLY (`_segmented_anchor_path`, clean segmented
        editorial line, no spline, no synthetic points), a very subtle under-curve tint, a small
        crisp white endpoint dot. Drawn only when >= 2 real points are supplied;
      - a contrast-guarded grid concentrated behind the graph + the board NINJA PULSE motif;
      - one very restrained NNJ mark (the board DATA media itself shows none - see report §M).

    No source photo is used - the hero metric IS the visual.

    FOUNDER-VISUAL-CANVAS-COMPOSITION-CORRECTION-8: the canvas is `_HERO_CW` x `_HERO_CH` =
    1280 x 1172 (aspect ~1.09, the MEASURED board DATA-media aspect - NOT 16:9). The metric block
    is TOP-anchored at the board-measured `value_top_frac`. value/unit use the BUNDLED Fira Sans
    Condensed Black, label SemiBold, secondary Medium (assets/brand/fonts/, SIL OFL - identical on
    Windows and Linux). Every proportion is pixel-measured from `docs/founder_telegram_board.png`
    via services/nnj_board_metrics.py. Every factual element is retained; series values verbatim."""
    canvas = Image.new("RGB", (_HERO_CW, _HERO_CH), _HERO_BG)
    draw = ImageDraw.Draw(canvas)
    _draw_hero_grid(draw, _HERO_CW, _HERO_CH)

    x = _HERO_MARGIN
    left_col_w = round(_HERO_CW * _HERO_LEFT_ZONE_FRAC) - _HERO_MARGIN  # board-measured text column
    series = tuple(data_candidate.series)
    has_chart = len(series) >= 2

    blocks: list[tuple[str, object, tuple, tuple, int]] = []  # (kind, font, bbox, color, gap_after)
    total_h: float = 0

    # RECONSTRUCTION-6 §7/§8: the BUNDLED Fira Sans Condensed (black/bold/regular) - identical on
    # Windows and Linux. `unit` and `label` are sized by the board's MEASURED cap-height ratios off
    # the fitted `value` size, not independently.
    value_text = data_candidate.value
    value_font, value_size = _fit_single_line(
        draw, value_text, font_max=_HERO_VALUE_FONT_MAX, font_min=_HERO_VALUE_FONT_MIN,
        max_width=left_col_w, data_weight="black",
    )
    _require_single_line_fits(draw, value_text, value_font, max_width=left_col_w, element="value")
    vb = draw.textbbox((0, 0), value_text, font=value_font)
    blocks.append(("value", value_font, vb, _OFFICIAL_NNJ_WHITE, 4))
    total_h += (vb[3] - vb[1]) + 4

    unit_text = data_candidate.unit.strip().upper()
    if unit_text:
        unit_size = max(28, round(value_size * _bm.DATA.unit_over_value))
        unit_font, unit_size = _fit_single_line(
            draw, unit_text, font_max=unit_size, font_min=max(24, unit_size - 40),
            max_width=left_col_w, data_weight="black",
        )
        _require_single_line_fits(draw, unit_text, unit_font, max_width=left_col_w, element="unit")
        ub = draw.textbbox((0, 0), unit_text, font=unit_font)
        blocks.append(("unit", unit_font, ub, _OFFICIAL_NNJ_RED, 16))
        total_h += (ub[3] - ub[1]) + 14

    # FINAL-BOARD-MATCH-7 §7/§8: SEPARATE the weights - label is SemiBold (V6's Bold was too
    # heavy), secondary copy is Medium (V6's Regular read too weak). Board cap-height ratios:
    # label = 0.19 x value, secondary = 0.165 x value.
    label_lines: list[str] = []
    label_font = _data_font(_HERO_LABEL_FONT_MIN, "semibold")
    label_size = _HERO_LABEL_FONT_MIN
    if data_candidate.label.strip():
        lmax = max(_HERO_LABEL_FONT_MIN + 2, min(_HERO_LABEL_FONT_MAX, round(value_size * _bm.DATA.label_over_value)))
        label_lines, label_font, label_size = _fit_wrapped_block(
            draw, data_candidate.label.strip().upper(), font_max=lmax,
            font_min=_HERO_LABEL_FONT_MIN, max_width=left_col_w, max_lines=_HERO_LABEL_MAX_LINES,
            data_weight="semibold",
        )
        total_h += len(label_lines) * (label_size + 6) + 10

    desc_lines: list[str] = []
    desc_font = _data_font(_HERO_DESC_FONT_MIN, "medium")
    desc_size = _HERO_DESC_FONT_MIN
    if data_candidate.evidence_fact.strip():
        dmax = max(_HERO_DESC_FONT_MIN + 2, min(_HERO_DESC_FONT_MAX, round(value_size * _bm.DATA.desc_over_value)))
        desc_lines, desc_font, desc_size = _fit_wrapped_block(
            draw, data_candidate.evidence_fact.strip(), font_max=dmax,
            font_min=_HERO_DESC_FONT_MIN, max_width=left_col_w, max_lines=_HERO_DESC_MAX_LINES,
            data_weight="medium",
        )
        total_h += len(desc_lines) * (desc_size + 5) + 16

    pill_h: float = 0
    if data_candidate.delta:
        pill_font = _data_font(max(22, round(value_size * 0.17)), "semibold")
        pb = draw.textbbox((0, 0), data_candidate.delta, font=pill_font)
        pill_h = (pb[3] - pb[1]) + 22
        total_h += pill_h + 20

    total_h += 26  # the small pulse motif under the block

    # --- draw, TOP-anchored at the board-measured metric position (not vertically centred, so the
    #     block does not float inside the tall canvas) -------------------------------------------
    y: float = max(_HERO_MARGIN, min(_bm.DATA.value_top_frac * _HERO_CH, _HERO_CH - total_h - _HERO_MARGIN))

    draw.text((x, y - vb[1]), value_text, font=value_font, fill=_OFFICIAL_NNJ_WHITE)
    y += (vb[3] - vb[1]) + 4
    if unit_text:
        draw.text((x, y - ub[1]), unit_text, font=unit_font, fill=_OFFICIAL_NNJ_RED)
        y += (ub[3] - ub[1]) + 14
    for line in label_lines:
        draw.text((x, y), line, font=label_font, fill=_OFFICIAL_NNJ_WHITE)
        y += label_size + 6
    if label_lines:
        y += 10
    for line in desc_lines:
        draw.text((x, y), line, font=desc_font, fill=_HERO_DESC_COLOR)
        y += desc_size + 5
    if desc_lines:
        y += 16
    if data_candidate.delta:
        pw = pb[2] - pb[0]
        pill_box = (x, y, x + pw + 44, y + pill_h)
        draw.rounded_rectangle(list(pill_box), radius=pill_h // 2, outline=_OFFICIAL_NNJ_RED, width=3)
        draw.text((x + 22, y + 14 - pb[1]), data_candidate.delta, font=pill_font, fill=_HERO_PILL_TEXT_COLOR)
        y += pill_h + 22

    canvas_rgba = canvas.convert("RGBA")

    # §18: the small pulse motif under the metric block - the SAME board line family as BREAKING,
    # thin and short, VISUALLY SECONDARY (it must not compete with +38% or the chart).
    _draw_recovered_pulse(
        canvas_rgba, x_left=x, baseline_y=round(y) + 10, span=132, amplitude=13,
        color=_OFFICIAL_NNJ_RED, stroke=2,
    )

    # §13: the trend line - board-measured geometry on the near-square canvas: it begins right
    # after the metric block (x 0.40) and fills the lower-right, integrated with the metric block,
    # no oversized empty gap. The red LINE is the feature; the fill stays dark.
    if has_chart:
        _draw_hero_sparkline(
            canvas_rgba, series,
            box=(round(_HERO_CW * _bm.DATA.graph_x_start_frac), round(_HERO_CH * _bm.DATA.graph_y_top_frac),
                 round(_HERO_CW * _bm.DATA.graph_x_end_frac), round(_HERO_CH * _bm.DATA.graph_y_bottom_frac)),
        )

    # §18: one very restrained NNJ mark (the board DATA media shows none - kept for the prior
    # one-mark decision, flagged for Founder review). Small, low opacity, must not compete.
    mark = rasterize_nnj_mark(target_width=max(30, round(_HERO_MARK_W_FRAC * _HERO_CW)), red=True)
    if _HERO_MARK_OPACITY < 1.0:
        a = mark.getchannel("A").point(lambda v: round(v * _HERO_MARK_OPACITY))
        mark.putalpha(a)
    canvas_rgba.alpha_composite(
        mark, (_HERO_CW - mark.width - _HERO_MARGIN, _HERO_CH - mark.height - _HERO_MARGIN),
    )

    out = io.BytesIO()
    canvas_rgba.convert("RGB").save(out, format="JPEG", quality=95)
    return out.getvalue()


# FOUNDER-VISUAL-BOARD-REBUILD-6 §16-§18: a small, restrained NNJ watermark for a PRESERVED source
# infographic. Not the big BREAKING watermark, not a signature line - a quiet corner glyph, and
# only if a bounded safe corner exists.
_SOURCE_WM_W_FRAC = 0.062        # small - genuinely a quiet corner watermark
_SOURCE_WM_BUSY_STDDEV = 18.0     # above this local detail (even small text), a corner is "occupied"


def _place_source_watermark(canvas: Image.Image) -> bool:
    """Try the four bounded corners (lower-right first) for ONE small adaptive NNJ watermark on a
    preserved source infographic. Returns True if placed, False -> BRAND SUPPRESSION (§18: never
    cover numbers / labels / axes / bars / legends / attribution / a publisher logo). Adaptive:
    dark-grey on a light region, light-grey on a dark region; always low opacity."""
    w, h = canvas.size
    inset = max(8, round(0.028 * w))
    wm_w = max(28, round(_SOURCE_WM_W_FRAC * w))
    glyph = rasterize_nnj_mark(target_width=wm_w, red=False)
    gw, gh = glyph.size
    rgb = canvas.convert("RGB")
    corners = (
        ("lower_right", (w - inset - gw, h - inset - gh)),
        ("lower_left", (inset, h - inset - gh)),
        ("upper_right", (w - inset - gw, inset)),
        ("upper_left", (inset, inset)),
    )
    best: tuple[float, tuple[int, int], float] | None = None
    for _name, (gx, gy) in corners:
        region = rgb.crop((max(0, gx), max(0, gy), min(w, gx + gw), min(h, gy + gh)))
        if region.width < 4 or region.height < 4:
            continue
        stddev = max(ImageStat.Stat(region).stddev)
        if stddev > _SOURCE_WM_BUSY_STDDEV:
            continue
        mean = sum(ImageStat.Stat(region).mean) / 3
        if best is None or stddev < best[0]:
            best = (stddev, (gx, gy), mean)
    if best is None:
        return False
    _, (gx, gy), mean = best
    if mean > 150:
        tint, op = (58, 58, 64), 0.30
    elif mean > 88:
        tint, op = (112, 112, 120), 0.34
    else:
        tint, op = (210, 210, 214), 0.28
    layer = Image.new("RGBA", glyph.size, (*tint, 0))
    layer.putalpha(glyph.getchannel("A").point(lambda v: round(v * op)))
    canvas.alpha_composite(layer, (max(0, gx), max(0, gy)))
    return True


def render_data_card(
    data_candidate: DataCandidate, *, category: str, editorial_code: str, source_image_bytes: bytes,
    presentation_mode: DataPresentationMode = DataPresentationMode.FULL_DATA_CARD,
    source_already_branded: bool = False,
) -> bytes:
    """FOUNDER-VISUAL-BOARD-ALIGNMENT-1: `presentation_mode=FULL_DATA_CARD` now delegates to
    `render_data_hero_card()` - the Founder-approved generated hero-metric card (board format 3).
    The retired V2.20 compact-corner-stat-on-the-photo treatment is no longer a shipped path (its
    helper functions - `_select_data_block_placement()`, `_measure_data_stat_block()`, the adaptive
    backing - are retained for their direct unit coverage and a possible future mode, but are not
    reached from any production dispatch). `MINIMAL_SOURCE_PRESERVING` / `NO_OVERLAY_SAFETY` are
    completely unchanged below - an EXISTING_INFOGRAPHIC source is never converted into a hero card.

    Phase V2.20A - see the module comment above this function's constants for the full
    approved-template rationale. The source/editorial image is composited directly (via the
    shared `_fit_photo_to_canvas()` helper - NOT apply_master_news_branding(), which would
    necessarily risk introducing MASTER's own separate upper mark, forbidden by the approved DATA
    template). The ONLY branding is one bottom-only pulse+NNJ signature (adaptive red/white,
    `_select_data_signature()`); exactly one compact stat block is then added in whichever safe,
    non-colliding corner `_select_data_block_placement()` finds - or none at all, if no corner
    qualifies, in which case the source+signature-only image is returned as-is (never a forced or
    clipped overlay). `category`/`editorial_code` are accepted for dispatch-symmetry with the
    other render_* functions but are not drawn anywhere here.

    DIRECTOR-CONTROL-PLANE-1 §23-26: `presentation_mode=MINIMAL_SOURCE_PRESERVING` (the real
    Kirin 9050 Pro regression fix - services/data_source_classification.py's own module docstring)
    skips the stat-block step ENTIRELY and returns right after the NNJ signature is composited -
    the source image's own already-printed metric is never redrawn, overpainted, or risked
    colliding with a second competing number."""
    if presentation_mode == DataPresentationMode.FULL_DATA_CARD:
        return render_data_hero_card(data_candidate, source_image_bytes=source_image_bytes)

    photo = Image.open(io.BytesIO(source_image_bytes)).convert("RGBA")
    canvas = _fit_photo_to_canvas(photo, (_CANVAS_W, _CANVAS_H))
    canvas_w, canvas_h = canvas.size
    draw = ImageDraw.Draw(canvas)

    inset = max(1, round(_SAFE_INSET_FRAC * canvas_w))
    pad = max(1, round(_SCORE_PAD_PX_FRAC * canvas_w))

    if source_already_branded or source_carries_canonical_nnj(source_image_bytes):
        # FOUNDER-VISUAL-POLISH-2 §4: FINAL_VISIBLE_NNJ_COUNT <= 1. The source already carries a
        # canonical NNJ mark (a KNOWN internal NNJ-branded template, exact content match; or a
        # source flagged by upstream `source_already_branded` metadata) - adding another renderer
        # NNJ would put two canonical marks on the final image. So add NOTHING: the source is
        # preserved exactly, zero renderer marks. (Third-party publisher logos are never touched.)
        out = io.BytesIO()
        canvas.convert("RGB").save(out, format="JPEG", quality=95)
        return out.getvalue()

    if presentation_mode == DataPresentationMode.MINIMAL_SOURCE_PRESERVING:
        # FOUNDER-VISUAL-BOARD-REBUILD-6 §16-§18 (Founder-approved architecture): SOURCE FIDELITY
        # FIRST. The source infographic is NOT converted to imitate the generated DATA card - it
        # ships preserved, with AT MOST one small restrained adaptive NNJ watermark placed in a
        # bounded safe corner; if no corner is safe, BRAND SUPPRESSION. No pulse line, no bottom
        # signature, no frame, no technical grid, no DATA-card background, no second metric.
        _place_source_watermark(canvas)
        out = io.BytesIO()
        canvas.convert("RGB").save(out, format="JPEG", quality=95)
        return out.getvalue()

    signature_box: BoundingBox | None = None
    signature_plan = _select_data_signature(canvas, inset=inset, pad=pad)
    if signature_plan is not None:
        signature_image = _build_data_lower_signature_image(
            canvas.size, signature_plan.placement, inset, red=signature_plan.red, line_len=signature_plan.line_len,
        )
        canvas.alpha_composite(signature_image)
        # Tight union of the mark/pulse/line's own REAL drawn boxes (not one coarse rectangle) -
        # the stat block only needs to avoid what's actually occupied, at whatever tier was used.
        mark_box, pulse_box, line_box = _data_signature_geometry(
            canvas.size, signature_plan.placement, inset, signature_plan.line_len,
        )
        signature_box = (
            min(mark_box[0], pulse_box[0], line_box[0]), min(mark_box[1], pulse_box[1], line_box[1]),
            max(mark_box[2], pulse_box[2], line_box[2]), max(mark_box[3], pulse_box[3], line_box[3]),
        )
    elif presentation_mode != DataPresentationMode.MINIMAL_SOURCE_PRESERVING:
        # MEDIA-PROD-1: for the legacy stat-block DATA card, every bottom corner failed the scored
        # search - never ship it with zero NNJ branding.
        fallback_image, signature_box = _build_data_signature_fallback(canvas.size, inset=inset)
        canvas.alpha_composite(fallback_image)
    # RECONSTRUCTION-5 §20/§21: for the Founder-reviewed SOURCE-PRESERVING infographic path, if the
    # adaptive pulse+mark signature cannot be placed safely, BRAND_SUPPRESSION wins - never a
    # rectangular logo badge / dark plate pasted over a third-party infographic. The source ships
    # unbranded; FINAL_VISIBLE_NNJ_COUNT stays <= 1 (here: 0 renderer marks).

    if presentation_mode == DataPresentationMode.MINIMAL_SOURCE_PRESERVING:
        # DIRECTOR-CONTROL-PLANE-1 §25: source information already IS the presentation - the ONLY
        # addition is the NNJ signature already composited above. Never measures/places/draws a
        # second stat block that could visually collide with or duplicate the source's own number.
        out = io.BytesIO()
        canvas.convert("RGB").save(out, format="JPEG", quality=95)
        return out.getvalue()

    block_w = max(160, round(_DATA_BLOCK_WIDTH_FRAC * canvas_w))
    inner_max_width = max(1, block_w - _DATA_BLOCK_MARGIN * 2)
    primary_text, stat_font, stat_bbox, label_lines, label_font, label_line_height, text_height = (
        _measure_data_stat_block(draw, data_candidate, max_width=inner_max_width)
    )
    block_h = round(text_height) + _DATA_BLOCK_MARGIN * 2

    placement_result = _select_data_block_placement(
        canvas, block_w=block_w, block_h=block_h, inset=inset, pad=pad, avoid_box=signature_box,
    )

    if placement_result is not None:
        box, color, needs_backing = placement_result
        x0, y0, _x1, _y1 = box
        text_x, text_y = x0 + _DATA_BLOCK_MARGIN, y0 + _DATA_BLOCK_MARGIN

        if needs_backing:
            # DATA-CARD-2: the approved template has no card/backing element at all (data_template_
            # manifest.json) - `_select_data_block_placement()` now only reaches for one as a last
            # resort when every candidate corner is too visually busy for direct on-image text.
            # Even then, it must stay the smallest possible legibility aid, never a nominal-block-
            # sized panel: sized tightly to the REAL measured text content (never wider/taller than
            # `primary_text`/`label_lines` actually render), not the fixed `block_w`/`block_h`
            # footprint reserved for corner-safety scoring - a short value like "35%" must never
            # carry a backing as wide as a long label would need.
            content_width = draw.textlength(primary_text, font=stat_font)
            for line in label_lines:
                content_width = max(content_width, draw.textlength(line, font=label_font))
            tight_box = (x0, y0, x0 + content_width + _DATA_BLOCK_MARGIN * 2, y0 + block_h)
            backing_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            backing_draw = ImageDraw.Draw(backing_layer)
            backing_fill = (0, 0, 0, 140) if color == _OFFICIAL_NNJ_WHITE else (255, 255, 255, 150)
            backing_draw.rounded_rectangle(list(tight_box), radius=10, fill=backing_fill)
            canvas = Image.alpha_composite(canvas, backing_layer)
            draw = ImageDraw.Draw(canvas)

        draw.text((text_x, text_y - stat_bbox[1]), primary_text, font=stat_font, fill=color)
        if label_lines:
            y = text_y - stat_bbox[1] + (stat_bbox[3] - stat_bbox[1]) + _DATA_LINE_GAP
            for line in label_lines:
                draw.text((text_x, y), line, font=label_font, fill=color)
                y += label_line_height

    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="JPEG", quality=95)
    return out.getvalue()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


_QUOTE_MARK_GLYPH = "“"  # left double quotation mark - the board's large red quote-mark motif
_QUOTE_BODY_FONT_MAX = 46
_QUOTE_BODY_FONT_MIN = 28
_QUOTE_BODY_MAX_LINES = 7
_QUOTE_ROLE_COLOR = (168, 170, 176)  # neutral grey - matches the hero card's secondary grey
_QUOTE_BG = (14, 14, 16)             # deep graphite (same as the hero card)
_QUOTE_PORTRAIT_W_FRAC = 0.44        # right-hand portrait region
_QUOTE_MARGIN = 64                   # pinned - RenderEvidence parity


def _composite_dark_portrait(base: Image.Image, portrait_bytes: bytes, *, region_x: int) -> None:
    """FOUNDER-VISUAL-POLISH-2 §7/§8: place the portrait in the right-hand region and INTEGRATE it
    into the deep-graphite composition - regardless of the portrait's own background brightness
    (Founder rejected the light/white right half). Steps: cover-crop to the region; blend the
    whole portrait ~22% toward graphite so a white studio background reads as dark grey; a
    left->right graphite gradient dissolves the inner edge into the text panel (no hard vertical
    seam, no light panel); a soft bottom vignette grounds it. Deterministic, no external calls."""
    w, h = base.size
    region_w = w - region_x
    with Image.open(io.BytesIO(portrait_bytes)) as pim:
        p = pim.convert("RGB")
    scale = max(region_w / p.width, h / p.height)
    p = p.resize((max(1, round(p.width * scale)), max(1, round(p.height * scale))), Image.Resampling.LANCZOS)
    left = max(0, (p.width - region_w) // 2)
    top = max(0, (p.height - h) // 2)
    p = p.crop((left, top, left + region_w, top + h))

    graphite = Image.new("RGB", p.size, _QUOTE_BG)
    p = Image.blend(p, graphite, 0.34)                     # pull a white studio bg down to dark grey
    p = ImageEnhance.Brightness(p).enhance(0.78)           # overall moody-dark, consistent with the board
    base.paste(p, (region_x, 0))

    # left->right graphite gradient across the inner ~72% of the portrait region: dissolves the
    # inner edge into the text panel so there is no hard vertical seam and no light panel.
    grad_w = round(region_w * 0.72)
    grad = Image.new("L", (grad_w, 1))
    grad.putdata([int(255 * (1 - i / max(1, grad_w - 1)) ** 0.85) for i in range(grad_w)])
    grad = grad.resize((grad_w, h))
    base.paste(Image.new("RGB", (grad_w, h), _QUOTE_BG), (region_x, 0), grad)

    # a light outer-edge fade + a bottom vignette ground the portrait in the composition
    edge_w = round(region_w * 0.14)
    edge = Image.new("L", (edge_w, 1))
    edge.putdata([int(120 * (i / max(1, edge_w - 1))) for i in range(edge_w)])
    edge = edge.resize((edge_w, h))
    base.paste(Image.new("RGB", (edge_w, h), _QUOTE_BG), (base.size[0] - edge_w, 0), edge)
    vg = Image.new("L", (1, h))
    vg.putdata([0 if i < h * 0.5 else int(170 * ((i - h * 0.5) / (h * 0.5))) for i in range(h)])
    vg = vg.resize((region_w, h))
    base.paste(Image.new("RGB", (region_w, h), _QUOTE_BG), (region_x, 0), vg)


def render_quote_card(
    quote_candidate: QuoteCandidate, *, category: str, editorial_code: str, portrait_bytes: bytes | None = None,
) -> bytes:
    """FOUNDER-VISUAL-POLISH-2 §7/§8 (board format 4): a deep-graphite composition - large red
    quote-mark motif, a dominant white quote body on the left, the author portrait integrated into
    the RIGHT region via a graphite blend + left->right gradient (never a hard 50/50 split, never
    a light panel - true even for a white-background portrait), author name in NNJ red, author
    role beneath in smaller neutral grey. Exactly ONE restrained canonical NNJ mark (lower-right).
    No baked Telegram chrome (no `PULSE / QUOTE` label, no `NP-xxxx`); `category`/`editorial_code`
    accepted for dispatch symmetry, never drawn.

    `quote_candidate.text` is rendered EXACTLY as given (deterministically font-fitted + wrapped,
    never mid-word clipped). `quote_candidate.role` is drawn only when supplied - a missing role
    is never fabricated; the visual language is otherwise IDENTICAL to the with-role card."""
    canvas = Image.new("RGB", (_CARD_WIDTH, _CARD_HEIGHT), _QUOTE_BG)
    region_x = _CARD_WIDTH - round(_CARD_WIDTH * _QUOTE_PORTRAIT_W_FRAC)
    if portrait_bytes is not None:
        try:
            _composite_dark_portrait(canvas, portrait_bytes, region_x=region_x)
        except Exception:
            logger.warning("brand_renderer_quote_portrait_failed", exc_info=True)

    draw = ImageDraw.Draw(canvas)
    margin = _QUOTE_MARGIN
    text_w = region_x - margin - 40 if portrait_bytes is not None else _CARD_WIDTH - margin * 2

    draw.text((margin, 96), _QUOTE_MARK_GLYPH, font=_font(140), fill=_OFFICIAL_NNJ_RED)

    body_lines, body_font, body_size = _fit_wrapped_block(
        draw, f"“{quote_candidate.text}”", font_max=_QUOTE_BODY_FONT_MAX,
        font_min=_QUOTE_BODY_FONT_MIN, max_width=text_w, max_lines=_QUOTE_BODY_MAX_LINES,
    )
    attrib_h = (42 if quote_candidate.speaker else 0) + (30 if quote_candidate.role else 0) + 24
    body_h = len(body_lines) * (body_size + 12)
    y = max(232.0, (_CARD_HEIGHT - body_h - attrib_h) / 2 + 40)
    for line in body_lines:
        draw.text((margin, y), line, font=body_font, fill=_OFFICIAL_NNJ_WHITE)
        y += body_size + 12

    y += 24
    if quote_candidate.speaker:
        draw.text((margin, y), quote_candidate.speaker, font=_font(30), fill=_OFFICIAL_NNJ_RED)
        y += 42
    if quote_candidate.role:
        draw.text((margin, y), quote_candidate.role, font=_font(22), fill=_QUOTE_ROLE_COLOR)

    canvas_rgba = canvas.convert("RGBA")
    _paste_svg_mark(canvas_rgba, target_width=84, margin=margin)

    out = io.BytesIO()
    canvas_rgba.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()


def render_branded_media(
    *,
    presentation_type: str,
    source_image_bytes: bytes | None,
    category: str,
    editorial_code: str,
    branding_strength: str = "EDITORIAL",
    data_candidate: DataCandidate | None = None,
    quote_candidate: QuoteCandidate | None = None,
    data_presentation_mode: DataPresentationMode = DataPresentationMode.FULL_DATA_CARD,
    source_already_branded: bool = False,
) -> RenderResult:
    """The one dispatch entry point. Never raises - any failure (missing asset, decode error,
    unexpected exception) is caught here and reported as `success=False`; the caller
    (worker/content_cycle.py) must then use the original, unbranded media (or plain NEWS text)
    unchanged, per spec §29's non-negotiable fail-safe rule.

    DIRECTOR-CONTROL-PLANE-1 §23-26: `data_presentation_mode` is forwarded to render_data_card()
    unchanged for DATA only - every other presentation_type ignores it. Defaults to the existing
    FULL_DATA_CARD behavior, so every pre-existing caller that never passes this parameter is
    completely unaffected."""
    started = time.monotonic()
    template_version = _TEMPLATE_BY_PRESENTATION_TYPE.get(presentation_type, TEMPLATE_NEWS)
    try:
        # PRESENTATION RECOVERY (2026-09-02): this precondition is now scoped to NEWS only -
        # BREAKING/QUOTE were migrated off `nnj_logo.png`/`_paste_logo()` onto the canonical
        # SVG-rasterized mark (`_paste_svg_mark()`, same rasterizer DATA already uses), so they no
        # longer depend on this asset at all; checking it for them here would be an unnecessary,
        # overly broad failure mode. NEWS's own `render_news_hero()` call below is the only
        # remaining live consumer of `_LOGO_PNG_PATH` in this dispatch.
        if presentation_type == NEWS and not _LOGO_PNG_PATH.exists():
            raise FileNotFoundError(f"missing official brand asset: {_LOGO_PNG_PATH}")

        if presentation_type == BREAKING:
            image_bytes = render_breaking_frame(source_image_bytes, category=category, editorial_code=editorial_code)
        elif presentation_type == DATA:
            if data_candidate is None:
                raise ValueError("DATA presentation requested with no data_candidate")
            if source_image_bytes is None:
                # Phase V2.20: DATA no longer has a source-photo-free synthetic card form - the
                # source image is now the primary visual, so a missing one is a genuine fail-safe
                # case (never renders a dark full-frame fallback card). This existing dispatch's
                # own unmodified failure path already demotes to ordinary NEWS delivery at the
                # caller (worker/content_cycle.py) - no new fallback logic needed here.
                raise ValueError("DATA presentation requested with no source_image_bytes")
            image_bytes = render_data_card(
                data_candidate, category=category, editorial_code=editorial_code,
                source_image_bytes=source_image_bytes, presentation_mode=data_presentation_mode,
                source_already_branded=source_already_branded,
            )
        elif presentation_type == QUOTE:
            if quote_candidate is None:
                raise ValueError("QUOTE presentation requested with no quote_candidate")
            image_bytes = render_quote_card(
                quote_candidate, category=category, editorial_code=editorial_code, portrait_bytes=source_image_bytes,
            )
        elif presentation_type == NEWS and source_image_bytes is not None:
            image_bytes = render_news_hero(
                source_image_bytes, category=category, editorial_code=editorial_code, branding_strength=branding_strength,
            )
        else:
            raise ValueError(f"no source image available to brand for presentation_type={presentation_type}")

        duration_ms = (time.monotonic() - started) * 1000
        return RenderResult(
            success=True, image_bytes=image_bytes, template_version=template_version,
            fallback_reason=None, duration_ms=duration_ms,
        )
    except Exception as exc:  # noqa: BLE001 - fail-safe boundary, must never propagate (spec §29)
        duration_ms = (time.monotonic() - started) * 1000
        logger.warning(
            "brand_render_failed",
            extra={"presentation_type": presentation_type, "template_version": template_version, "error": str(exc)},
        )
        return RenderResult(
            success=False, image_bytes=None, template_version=template_version,
            fallback_reason=str(exc), duration_ms=duration_ms,
        )


TEMPLATE_RECAP_FALLBACK = "pulse-recap-fallback-v1"
TEMPLATE_RECAP_FALLBACK_BACKGROUND = "pulse-recap-fallback-background-v1"


def build_recap_fallback_background(subject: str, *, category: str | None = None) -> RenderResult:
    """PRESENTATION RECOVERY (2026-09-02), WYSIWYG requirement: the new Tier 3 media for
    `services.event_recap_processor.render_branded_fallback_media()`, replacing
    `render_recap_fallback_card()` below. Deliberately carries NO branding at all (no logo, no
    pulse line, no "NINJA PULSE"/"EVENT RECAP" labels) - candidate/research-stage media may stay
    unbranded (plan review correction 2), since the real NNJ identity is now applied exactly once,
    uniformly across every RECAP media tier, by `apply_master_news_branding()` at Final Post
    Review preview time AND real publication time (the same canonical call, never duplicated) -
    never here, never twice. Sized to MASTER's own canvas (`_CANVAS_W`/`_CANVAS_H`, 1280x720) so
    that later branding step's own geometry assumptions hold unchanged. Purely a plain background +
    the subject label, so an editor/reviewer can still identify which story this fallback belongs
    to before real branding is applied."""
    started = time.monotonic()
    try:
        canvas = Image.new("RGB", (_CANVAS_W, _CANVAS_H), _OFFICIAL_NNJ_BLACK)
        draw = ImageDraw.Draw(canvas)
        margin = 64

        if category:
            draw.text((margin, margin), category.upper(), font=_font(20), fill=_OFFICIAL_NNJ_WHITE)

        subject_font = _font(64)
        max_text_width = _CANVAS_W - margin * 2
        lines = _wrap_text(draw, subject, subject_font, max_text_width)
        y = round(_CANVAS_H * 0.4)
        for line in lines[:4]:
            draw.text((margin, y), line, font=subject_font, fill=_OFFICIAL_NNJ_WHITE)
            y += 76

        out = io.BytesIO()
        canvas.save(out, format="JPEG", quality=92)
        image_bytes = out.getvalue()

        duration_ms = (time.monotonic() - started) * 1000
        return RenderResult(
            success=True, image_bytes=image_bytes, template_version=TEMPLATE_RECAP_FALLBACK_BACKGROUND,
            fallback_reason=None, duration_ms=duration_ms,
        )
    except Exception as exc:  # noqa: BLE001 - fail-safe boundary, mirrors every other render_* function
        duration_ms = (time.monotonic() - started) * 1000
        logger.warning("recap_fallback_background_failed", extra={"error": str(exc)})
        return RenderResult(
            success=False, image_bytes=None, template_version=TEMPLATE_RECAP_FALLBACK_BACKGROUND,
            fallback_reason=str(exc), duration_ms=duration_ms,
        )


def render_recap_fallback_card(subject: str, *, category: str | None = None) -> RenderResult:
    """NINJA PULSE RECAP Phase H.3C: a deterministic, source-photo-free branded card - EVENT_RECAP's
    Tier 3 media fallback. Superseded by `build_recap_fallback_background()` above as of
    PRESENTATION RECOVERY (2026-09-02) - no longer called from services.event_recap_processor's
    real Tier 3 path (kept, unmodified, only because its own existing test suite still exercises it
    directly; not deleted, mirrors this module's own `render_news_hero()` precedent for dead-but-
    harmless code). Was called only when neither the confirmed Story media pool (Tier 1) nor
    confirmed-source re-acquisition (Tier 2B) produced a usable image (services.event_recap_
    processor.render_branded_fallback_media()). Reuses this module's own established canvas/logo/
    pulse-line/typography helpers UNCHANGED - `_paste_logo()`, `_draw_pulse_line()`, `_draw_code_
    label()`, `_font()`, `_wrap_text()`, `_OFFICIAL_NNJ_*` colors, `_CARD_WIDTH`/`_CARD_HEIGHT` -
    never a second renderer. No AI image-generation model, no paid provider, no third-party
    company logo (module docstring's own established "official assets only" rule already forbids
    drawing a reconstructed brand mark - the same discipline extends here to any OTHER company's
    mark, never attempted).

    Deliberately called directly, never through `render_branded_media()`'s `presentation_type`
    dispatch: EVENT_RECAP is a fully separate workflow with its own Tier 1/2B/3 gate (services.
    event_recap_processor), not a NEWS presentation-treatment decision - this function never reads
    `settings.presentation_director_mode` and is not gated by it.

    `subject` is `services.event_recap.derive_recap_visual_subject()`'s own deterministic, LLM-free
    output - this function does no entity extraction or text derivation of its own, mirroring
    `render_data_card()`'s "text drawn exactly as given, never generative" discipline. Purely a
    short subject label + brand identity, never the full recap (title/summary/key_takeaways) -
    Telegram's own MESSAGE 2 already carries the complete factual text (module docstring's own
    "never a recap screenshot" rule)."""
    started = time.monotonic()
    try:
        if not _LOGO_PNG_PATH.exists():
            raise FileNotFoundError(f"missing official brand asset: {_LOGO_PNG_PATH}")

        canvas = Image.new("RGB", (_CARD_WIDTH, _CARD_HEIGHT), _OFFICIAL_NNJ_BLACK)
        draw = ImageDraw.Draw(canvas)
        margin = 64

        draw.text((margin, margin), "NINJA PULSE / RECAP", font=_font(26), fill=_OFFICIAL_NNJ_RED)
        if category:
            draw.text((margin, margin + 38), category.upper(), font=_font(18), fill=_OFFICIAL_NNJ_WHITE)

        subject_font = _font(72)
        max_text_width = _CARD_WIDTH - margin * 2
        lines = _wrap_text(draw, subject, subject_font, max_text_width)
        y = round(_CARD_HEIGHT * 0.38)
        for line in lines[:4]:
            draw.text((margin, y), line, font=subject_font, fill=_OFFICIAL_NNJ_WHITE)
            y += 84

        _draw_pulse_line(draw, x=margin, y=_CARD_HEIGHT - 96, width=220, color=_OFFICIAL_NNJ_RED)
        _draw_code_label(
            draw, x=margin, y=_CARD_HEIGHT - 56, text="EVENT RECAP", color=_OFFICIAL_NNJ_WHITE, size=20,
        )

        canvas_rgba = canvas.convert("RGBA")
        _paste_logo(canvas_rgba, target_width=90, margin=margin)

        out = io.BytesIO()
        canvas_rgba.convert("RGB").save(out, format="JPEG", quality=92)
        image_bytes = out.getvalue()

        duration_ms = (time.monotonic() - started) * 1000
        return RenderResult(
            success=True, image_bytes=image_bytes, template_version=TEMPLATE_RECAP_FALLBACK,
            fallback_reason=None, duration_ms=duration_ms,
        )
    except Exception as exc:  # noqa: BLE001 - fail-safe boundary, must never propagate (spec §29)
        duration_ms = (time.monotonic() - started) * 1000
        logger.warning(
            "brand_render_recap_fallback_failed",
            extra={"template_version": TEMPLATE_RECAP_FALLBACK, "error": str(exc)},
        )
        return RenderResult(
            success=False, image_bytes=None, template_version=TEMPLATE_RECAP_FALLBACK,
            fallback_reason=str(exc), duration_ms=duration_ms,
        )
