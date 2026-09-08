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

from PIL import Image, ImageDraw, ImageFont, ImageStat

from core.config import settings
from services.data_source_classification import DataPresentationMode
from services.nnj_master_news_mark import rasterize_nnj_mark
from services.nnj_master_news_overlay import (
    BoundingBox,
    ComponentPlacement,
    composite_master_news_decision,
    select_master_news_branding,
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

_font_path_resolution: list[str | None] = []  # single-element cache; [] means "not yet resolved"


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


@dataclass(frozen=True)
class RenderResult:
    success: bool
    image_bytes: bytes | None
    template_version: str
    fallback_reason: str | None
    duration_ms: float


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    # `bold` accepted for call-site readability/future extension - Arial/DejaVu/Liberation Sans
    # are all installed as single (non-bold) faces here, so it has no effect yet.
    font_path = _resolve_font_path()
    if font_path is not None:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            logger.warning("brand_renderer_font_load_failed", extra={"font_path": font_path})
    return ImageFont.load_default(size=size)


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


def render_breaking_frame(source_image_bytes: bytes | None, *, category: str, editorial_code: str) -> bytes:
    """VISUAL-RENDERER-RECONCILIATION-1 §5-7: BREAKING belongs to the SAME restrained NEWS family
    as `apply_master_news_branding()`. The retired treatment - a ~22%-tall dark-gradient lower-
    third band, a baked "BREAKING" wordmark, a red accent rule - is GONE: it was never approved
    against the master prototype (`assets/brand/newsroom_visuals/v1/references/
    nnj_editorial_visual_system_master_prototype.png` shows BREAKING with the identical thin
    bottom line + pulse + one "nnj" mark NEWS/DATA use, no band, no baked text), and
    `breaking_minimal_01` is `production_approved: false` in the overlay manifest.

    BREAKING now composites the source at its NATIVE size (source_image_treatment=preserve) with
    the exact MASTER NEWS single lower signature (`select_master_news_branding()` -> one thin edge
    line + pulse + exactly one canonical NNJ mark, adaptive safe-corner placement, the single-
    brand-mark invariant already enforced there). No band, no baked text, no badge, no ribbon.
    `category`/`editorial_code` are accepted for dispatch symmetry with the other render_* funcs
    (like DATA) but are never drawn. No source photo -> a minimal solid NNJ-black card carrying
    only the one canonical mark (never blocks BREAKING delivery on a missing image)."""
    if source_image_bytes is not None:
        with Image.open(io.BytesIO(source_image_bytes)) as src:
            photo = src.convert("RGBA").copy()
        decision = select_master_news_branding(photo)
        branded = composite_master_news_decision(photo, decision)
    else:
        branded = Image.new("RGBA", (_CARD_WIDTH, _CARD_HEIGHT), (*_OFFICIAL_NNJ_BLACK, 255))
        _paste_svg_mark(branded, target_width=max(48, round(_CARD_WIDTH * 0.08)), margin=64)

    out = io.BytesIO()
    branded.convert("RGB").save(out, format="JPEG", quality=92)
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
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, int]:
    """Deterministically shrinks the font (within [font_min, font_max], step 4) until `text` fits
    `max_width` on one line - never a mid-character pixel clip. Returns the smallest size actually
    tried even if `font_min` still does not fit (a hard-bound caller is expected to already keep
    `text` short by construction in that rare case - this never truncates a single-line value)."""
    size = font_max
    font = _font(size)
    for candidate_size in range(font_max, font_min - 1, -4):
        font = _font(candidate_size)
        size = candidate_size
        if draw.textlength(text, font=font) <= max_width:
            break
    return font, size


def _fit_wrapped_block(
    draw: ImageDraw.ImageDraw, text: str, *, font_max: int, font_min: int, max_width: int, max_lines: int,
) -> tuple[list[str], ImageFont.FreeTypeFont | ImageFont.ImageFont, int]:
    """Deterministically fits `text` inside `max_width`/`max_lines` by shrinking the font within
    [font_min, font_max] (step 2) and word-wrapping (`_wrap_text()`) at each candidate size. If it
    still does not fit at `font_min` (content-selection has already bounded `text` upstream via
    `label[:80]`, so this is a last-resort safety net, not the primary length control), the final
    line is shortened at a word boundary with a trailing ellipsis until it fits - never a blind
    pixel clip, never a mid-character cut."""
    lines: list[str] = []
    font = _font(font_min)
    size = font_min
    for candidate_size in range(font_max, font_min - 1, -2):
        font = _font(candidate_size)
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


def render_data_card(
    data_candidate: DataCandidate, *, category: str, editorial_code: str, source_image_bytes: bytes,
    presentation_mode: DataPresentationMode = DataPresentationMode.FULL_DATA_CARD,
) -> bytes:
    """Phase V2.20A - see the module comment above this function's constants for the full
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
    colliding with a second competing number. Default FULL_DATA_CARD is completely unchanged -
    every existing caller that never passes this parameter gets byte-identical behavior."""
    photo = Image.open(io.BytesIO(source_image_bytes)).convert("RGBA")
    canvas = _fit_photo_to_canvas(photo, (_CANVAS_W, _CANVAS_H))
    canvas_w, canvas_h = canvas.size
    draw = ImageDraw.Draw(canvas)

    inset = max(1, round(_SAFE_INSET_FRAC * canvas_w))
    pad = max(1, round(_SCORE_PAD_PX_FRAC * canvas_w))

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
    else:
        # MEDIA-PROD-1: every bottom corner failed _select_data_signature()'s own scored search -
        # never ship a DATA card with zero NNJ branding (see _build_data_signature_fallback()'s
        # own docstring for why this is a deliberately different, scoring-free guarantee).
        fallback_image, signature_box = _build_data_signature_fallback(canvas.size, inset=inset)
        canvas.alpha_composite(fallback_image)

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


def render_quote_card(
    quote_candidate: QuoteCandidate, *, category: str, editorial_code: str, portrait_bytes: bytes | None = None,
) -> bytes:
    """Fully programmatic. `quote_candidate.text` is rendered EXACTLY as given - never paraphrased,
    shortened, or reworded by this renderer (spec §23/§40)."""
    canvas = Image.new("RGB", (_CARD_WIDTH, _CARD_HEIGHT), _OFFICIAL_NNJ_BLACK)
    if portrait_bytes is not None:
        try:
            with Image.open(io.BytesIO(portrait_bytes)) as portrait_src:
                portrait_rgb = portrait_src.convert("RGB")
                portrait_w = round(_CARD_HEIGHT * portrait_rgb.width / portrait_rgb.height)
                portrait_resized = portrait_rgb.resize((portrait_w, _CARD_HEIGHT), Image.Resampling.LANCZOS)
                canvas.paste(portrait_resized, (_CARD_WIDTH - portrait_w, 0))
                overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                overlay_draw = ImageDraw.Draw(overlay)
                overlay_draw.rectangle([(0, 0), (_CARD_WIDTH - portrait_w + 40, _CARD_HEIGHT)], fill=(0, 0, 0, 235))
                canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        except Exception:
            logger.warning("brand_renderer_quote_portrait_failed", exc_info=True)

    draw = ImageDraw.Draw(canvas)
    margin = 64
    max_text_width = round(_CARD_WIDTH * 0.55) if portrait_bytes else _CARD_WIDTH - margin * 2

    draw.text((margin, margin), f"PULSE / {category}", font=_font(24), fill=_OFFICIAL_NNJ_RED)

    quote_font = _font(42)
    lines = _wrap_text(draw, f"“{quote_candidate.text}”", quote_font, max_text_width)
    y = round(_CARD_HEIGHT * 0.32)
    for line in lines[:6]:
        draw.text((margin, y), line, font=quote_font, fill=_OFFICIAL_NNJ_WHITE)
        y += 54

    if quote_candidate.speaker:
        draw.text((margin, y + 16), f"— {quote_candidate.speaker}", font=_font(28), fill=_OFFICIAL_NNJ_RED)

    _draw_code_label(draw, x=margin, y=_CARD_HEIGHT - 56, text=editorial_code, color=_OFFICIAL_NNJ_WHITE, size=20)

    canvas_rgba = canvas.convert("RGBA")
    _paste_svg_mark(canvas_rgba, target_width=90, margin=margin)

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
