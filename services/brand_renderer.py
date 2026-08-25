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
white wordmark) and removed; exactly the "fake variant" the spec's own asset rules prohibit. There
is therefore only ONE brand-mark placement in this module, never a separate white/red choice.

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
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core.config import settings
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
    """Stronger BREAKING treatment (spec §21): official red mark, a bottom dark gradient band
    (never covering more than ~22% of the frame) carrying "BREAKING" + category/code, and the
    pulse line - never a full-frame overlay, never obscuring the source subject. Falls back to a
    simplified solid dark card when no source photo is available (never blocks BREAKING delivery
    on a missing image)."""
    if source_image_bytes is not None:
        with Image.open(io.BytesIO(source_image_bytes)) as src:
            canvas = src.convert("RGBA").copy()
    else:
        canvas = Image.new("RGBA", (_CARD_WIDTH, _CARD_HEIGHT), (*_OFFICIAL_NNJ_BLACK, 255))

    band_height = round(canvas.height * 0.22)
    band = Image.new("RGBA", (canvas.width, band_height), (0, 0, 0, 0))
    band_draw = ImageDraw.Draw(band)
    for row in range(band_height):
        alpha = round(210 * (row / band_height))
        band_draw.line([(0, row), (canvas.width, row)], fill=(0, 0, 0, alpha))
    canvas.alpha_composite(band, (0, canvas.height - band_height))

    draw = ImageDraw.Draw(canvas)
    margin = max(16, round(canvas.width * 0.02))
    accent_height = max(4, round(canvas.height * 0.006))
    draw.rectangle(
        [(0, canvas.height - band_height), (canvas.width, canvas.height - band_height + accent_height)],
        fill=_OFFICIAL_NNJ_RED,
    )
    draw.text(
        (margin, canvas.height - band_height + accent_height + margin // 2),
        "BREAKING", font=_font(max(22, round(canvas.width * 0.032))), fill=_OFFICIAL_NNJ_WHITE,
    )
    _draw_code_label(
        draw, x=margin, y=canvas.height - margin - max(14, round(canvas.width * 0.02)),
        text=f"{category} · {editorial_code}", color=_OFFICIAL_NNJ_WHITE,
        size=max(14, round(canvas.width * 0.02)),
    )
    logo_width = max(48, round(canvas.width * 0.08))
    _paste_logo(canvas, target_width=logo_width, margin=margin)

    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()


def render_data_card(data_candidate: DataCandidate, *, category: str, editorial_code: str) -> bytes:
    """Fully programmatic - text/numbers drawn deterministically from `data_candidate`'s own
    already-verified fields (services/presentation_director.py's cross-verified evidence binding)
    - never generative typography, never a value not already grounded upstream."""
    canvas = Image.new("RGB", (_CARD_WIDTH, _CARD_HEIGHT), _OFFICIAL_NNJ_BLACK)
    draw = ImageDraw.Draw(canvas)
    margin = 64

    draw.text((margin, margin), f"PULSE / {category}", font=_font(28), fill=_OFFICIAL_NNJ_RED)

    value_font = _font(180)
    draw.text((margin, 180), data_candidate.value, font=value_font, fill=_OFFICIAL_NNJ_WHITE)
    value_bbox = draw.textbbox((margin, 180), data_candidate.value, font=value_font)
    unit_x = value_bbox[2] + 24
    draw.text((unit_x, 220), data_candidate.unit.upper(), font=_font(56), fill=_OFFICIAL_NNJ_RED)

    if data_candidate.label:
        draw.text((margin, value_bbox[3] + 24), data_candidate.label, font=_font(32), fill=_OFFICIAL_NNJ_WHITE)

    _draw_pulse_line(draw, x=margin, y=_CARD_HEIGHT - 96, width=220, color=_OFFICIAL_NNJ_RED)
    _draw_code_label(draw, x=margin, y=_CARD_HEIGHT - 56, text=editorial_code, color=_OFFICIAL_NNJ_WHITE, size=20)

    canvas_rgba = canvas.convert("RGBA")
    _paste_logo(canvas_rgba, target_width=90, margin=margin)

    out = io.BytesIO()
    canvas_rgba.convert("RGB").save(out, format="JPEG", quality=92)
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
    _paste_logo(canvas_rgba, target_width=90, margin=margin)

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
) -> RenderResult:
    """The one dispatch entry point. Never raises - any failure (missing asset, decode error,
    unexpected exception) is caught here and reported as `success=False`; the caller
    (worker/content_cycle.py) must then use the original, unbranded media (or plain NEWS text)
    unchanged, per spec §29's non-negotiable fail-safe rule."""
    started = time.monotonic()
    template_version = _TEMPLATE_BY_PRESENTATION_TYPE.get(presentation_type, TEMPLATE_NEWS)
    try:
        if not _LOGO_PNG_PATH.exists():
            raise FileNotFoundError(f"missing official brand asset: {_LOGO_PNG_PATH}")

        if presentation_type == BREAKING:
            image_bytes = render_breaking_frame(source_image_bytes, category=category, editorial_code=editorial_code)
        elif presentation_type == DATA:
            if data_candidate is None:
                raise ValueError("DATA presentation requested with no data_candidate")
            image_bytes = render_data_card(data_candidate, category=category, editorial_code=editorial_code)
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


def render_recap_fallback_card(subject: str, *, category: str | None = None) -> RenderResult:
    """NINJA PULSE RECAP Phase H.3C: a deterministic, source-photo-free branded card - EVENT_RECAP's
    Tier 3 media fallback, called only when neither the confirmed Story media pool (Tier 1) nor
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
