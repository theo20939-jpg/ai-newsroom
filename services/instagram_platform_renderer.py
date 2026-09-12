"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 6/9: the Instagram-specific platform renderer.

Independent of `services/brand_renderer.py` (Telegram V8, FROZEN) - no import either direction.
Reuses ONLY brand-neutral shared assets via `services/instagram_visual_profiles.py` (bundled Fira
Sans Condensed, the canonical NNJ mark rasterizer) - a genuinely NEW composition for Instagram's
own geometry, never a resize of a Telegram card (section 6's own explicit instruction). No
Instagram UI chrome (progress bars, account chips, like/comment icons) is ever drawn into the
image - only the profile's own safe zones are respected so Instagram's OWN chrome never collides
with this renderer's content later.

Deterministic: the same `InstagramContentPackage` always produces byte-identical output (pure
function of the package + the bundled, versioned font/logo assets)."""
from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from services.instagram_content_package import InstagramContentPackage
from services.instagram_render_evidence import RENDER_VERSION, InstagramRenderEvidence, TextRegion
from services.instagram_visual_profiles import (
    InstagramRenderProfile,
    ProfileSpec,
    ig_brand_mark,
    ig_font,
    profile_spec,
)

# Instagram-native brand palette - deliberately its OWN constants (not imported from
# services/brand_renderer.py) so this module has zero coupling to the frozen Telegram renderer.
_BG = (8, 9, 11)
_WHITE = (245, 246, 248)
_RED = (237, 28, 36)  # matches services/nnj_master_news_mark.py::NNJ_RED_FILL (the canonical mark's own red)
_GREY = (162, 166, 174)

_MARGIN_FRAC = 0.07
_MARK_WIDTH_FRAC = 0.09
_MARK_OPACITY = 0.9  # the Instagram mark is a primary credit, not a background watermark - it is
# small and corner-placed (safe-zone respecting) rather than faint, matching section 7's own
# "readable safe-zone placement" instruction (distinct from Telegram BREAKING's deliberately
# restrained watermark - a different platform, a different brand rule, not an inherited one).


class InstagramRenderError(ValueError):
    """Raised when a package cannot be honestly rendered (e.g. a REEL cover request with no
    on-image text and no fallback) - never silently produces a blank/placeholder image."""


@dataclass(frozen=True)
class InstagramRenderResult:
    image_bytes: bytes
    evidence: InstagramRenderEvidence


def _content_identity(package: InstagramContentPackage, *, slide_index: int | None = None) -> str:
    """A stable hash of the PACKAGE'S OWN CONTENT (caption/copy/format) - never of rendered pixels
    - so two renders of the same content are traceably the same identity even if a future renderer
    version changes the pixels."""
    payload = {
        "package_id": package.package_id, "format": package.content_format.value,
        "caption": package.caption, "on_image_copy": package.on_image_copy, "cta": package.cta,
        "slide_index": slide_index,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _fit_text(
    draw: ImageDraw.ImageDraw, text: str, *, font_max: int, font_min: int, max_width: int,
    max_lines: int, weight: str = "black",
) -> tuple[ImageFont.FreeTypeFont, list[str], bool]:
    """Deterministic shrink-then-wrap-then-truncate text fit. Returns (font, lines, clipped).
    `clipped=True` whenever real content had to be truncated with an ellipsis - never silently
    dropped without a signal (section 9's own required `text_clipped` evidence)."""
    words = text.split()
    size = font_max
    while size >= font_min:
        font = ig_font(size, weight)
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        if len(lines) <= max_lines and all(draw.textlength(line, font=font) <= max_width for line in lines):
            return font, lines, False
        size -= 4

    # Even at the minimum size it does not fit cleanly - truncate to max_lines with an ellipsis,
    # never silently overflow the canvas.
    font = ig_font(font_min, weight)
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    lines = lines[:max_lines]
    if lines:
        last = lines[-1]
        while draw.textlength(last + "...", font=font) > max_width and len(last) > 1:
            last = last[:-1]
        lines[-1] = last.rstrip() + "..."
    return font, lines, True


def _draw_brand_mark(canvas: Image.Image, spec: ProfileSpec) -> tuple[int, tuple[int, int, int, int]]:
    """Composites the ONE canonical NNJ mark in the lower-right safe zone. Returns
    (visible_mark_count, its bbox) - always exactly 1, never duplicated (section 7's own "no
    duplicate brand mark" rule enforced structurally: this function is called exactly once per
    render, see the callers below)."""
    mark = ig_brand_mark(target_width=round(_MARK_WIDTH_FRAC * spec.width), red=True)
    if _MARK_OPACITY < 1.0:
        mark = mark.copy()
        alpha = mark.getchannel("A").point(lambda v: round(v * _MARK_OPACITY))
        mark.putalpha(alpha)
    margin = round(_MARGIN_FRAC * spec.width)
    bottom_safe = round(spec.safe_bottom_frac * spec.height)
    x = spec.width - margin - mark.width
    y = spec.height - bottom_safe - margin - mark.height
    canvas.alpha_composite(mark, (x, y))
    return 1, (x, y, x + mark.width, y + mark.height)


def _base_canvas(spec: ProfileSpec) -> Image.Image:
    return Image.new("RGBA", (spec.width, spec.height), (*_BG, 255))


def _render_text_card(
    package: InstagramContentPackage, *, profile: InstagramRenderProfile, headline: str, subtext: str | None,
    slide_index: int | None = None, slide_count: int | None = None,
) -> InstagramRenderResult:
    spec = profile_spec(profile)
    canvas = _base_canvas(spec)
    draw = ImageDraw.Draw(canvas)

    margin = round(_MARGIN_FRAC * spec.width)
    top_safe = round(spec.safe_top_frac * spec.height)
    bottom_safe = round(spec.safe_bottom_frac * spec.height)
    side_safe = max(margin, round(spec.safe_side_frac * spec.width))
    content_w = spec.width - 2 * side_safe

    text_regions: list[TextRegion] = []
    any_clipped = False

    headline_font, headline_lines, headline_clipped = _fit_text(
        draw, headline, font_max=round(spec.width * 0.11), font_min=round(spec.width * 0.045),
        max_width=content_w, max_lines=4, weight="black",
    )
    any_clipped = any_clipped or headline_clipped

    line_heights = []
    for line in headline_lines:
        bbox = draw.textbbox((0, 0), line, font=headline_font)
        line_heights.append(bbox[3] - bbox[1])
    line_gap = round(headline_font.size * 0.18)
    headline_block_h = sum(line_heights) + line_gap * max(0, len(headline_lines) - 1)

    subtext_lines: list[str] = []
    subtext_font = None
    subtext_clipped = False
    if subtext:
        subtext_font, subtext_lines, subtext_clipped = _fit_text(
            draw, subtext, font_max=round(spec.width * 0.045), font_min=round(spec.width * 0.028),
            max_width=content_w, max_lines=3, weight="medium",
        )
        any_clipped = any_clipped or subtext_clipped

    subtext_block_h: float = 0
    if subtext_font is not None:
        for line in subtext_lines:
            bbox = draw.textbbox((0, 0), line, font=subtext_font)
            subtext_block_h += (bbox[3] - bbox[1]) + round(subtext_font.size * 0.3)

    total_h = headline_block_h + (round(spec.height * 0.03) if subtext_lines else 0) + subtext_block_h
    available_top = top_safe + margin
    available_bottom = spec.height - bottom_safe - margin
    y: float = max(float(available_top), min(available_top + (available_bottom - available_top - total_h) * 0.35, available_bottom - total_h))

    x = side_safe
    for i, line in enumerate(headline_lines):
        draw.text((x, y), line, font=headline_font, fill=_WHITE)
        bbox = draw.textbbox((x, y), line, font=headline_font)
        text_regions.append(TextRegion(
            kind="headline", box=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
            clipped=headline_clipped and i == len(headline_lines) - 1,
        ))
        y += line_heights[i] + line_gap
    if subtext_lines and subtext_font is not None:
        y += round(spec.height * 0.03)
        for i, line in enumerate(subtext_lines):
            draw.text((x, y), line, font=subtext_font, fill=_GREY)
            bbox = draw.textbbox((x, y), line, font=subtext_font)
            text_regions.append(TextRegion(
                kind="caption_overlay", box=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
                clipped=subtext_clipped and i == len(subtext_lines) - 1,
            ))
            bh = bbox[3] - bbox[1]
            y += bh + round(subtext_font.size * 0.3)

    if slide_count and slide_count > 1:
        # a small "N / M" slide indicator - content, not Instagram UI chrome (the app draws its
        # own dot pagination separately; this is this renderer's own, inside the safe zone).
        idx_font = ig_font(round(spec.width * 0.03), "semibold")
        idx_text = f"{(slide_index or 0) + 1} / {slide_count}"
        draw.text((side_safe, spec.height - bottom_safe - margin), idx_text, font=idx_font, fill=_GREY, anchor="ls")

    mark_count, mark_box = _draw_brand_mark(canvas, spec)

    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="JPEG", quality=92)

    evidence = InstagramRenderEvidence(
        render_version=RENDER_VERSION, content_format=package.content_format.value, profile=profile.value,
        canvas_width=spec.width, canvas_height=spec.height, visible_brand_mark_count=mark_count,
        text_regions=text_regions, text_clipped=any_clipped, source_image_treatment="none",
        slide_index=slide_index, slide_count=slide_count, caption_linkage=package.package_id,
        content_identity=_content_identity(package, slide_index=slide_index),
        notes={"mark_box": list(mark_box)},
    )
    return InstagramRenderResult(image_bytes=out.getvalue(), evidence=evidence)


def render_instagram_feed_image(package: InstagramContentPackage) -> InstagramRenderResult:
    """SINGLE format -> one PORTRAIT_FEED image. Headline = the package's own `on_image_copy` (the
    Creative Director's literal on-image text) when present, else the caption itself - never
    invents on-image copy the Director did not produce."""
    if package.content_format.value != "single":
        raise InstagramRenderError(f"render_instagram_feed_image requires SINGLE, got {package.content_format!r}")
    headline = package.on_image_copy or package.caption
    subtext = package.cta
    return _render_text_card(package, profile=InstagramRenderProfile.PORTRAIT_FEED, headline=headline, subtext=subtext)


_MAX_CAROUSEL_SLIDES = 10  # Instagram's own platform ceiling (section 10's own "max slide bound")


def render_instagram_carousel(package: InstagramContentPackage) -> list[InstagramRenderResult]:
    """CAROUSEL format -> one CAROUSEL_SLIDE image per planned slide, same visual system across
    every slide (section 10). Bounded to `_MAX_CAROUSEL_SLIDES` - never an uncontrolled count."""
    if package.content_format.value != "carousel":
        raise InstagramRenderError(f"render_instagram_carousel requires CAROUSEL, got {package.content_format!r}")
    slides = package.media_plan.get("slides")
    if not isinstance(slides, list) or len(slides) < 2:
        raise InstagramRenderError("carousel package must carry >= 2 planned slides (media_plan['slides'])")
    if len(slides) > _MAX_CAROUSEL_SLIDES:
        raise InstagramRenderError(f"carousel slide count {len(slides)} exceeds the platform bound {_MAX_CAROUSEL_SLIDES}")

    results = []
    for slide in slides:
        headline = str(slide.get("text", ""))
        results.append(
            _render_text_card(
                package, profile=InstagramRenderProfile.CAROUSEL_SLIDE, headline=headline, subtext=None,
                slide_index=int(slide["index"]), slide_count=len(slides),
            )
        )
    return results


def render_instagram_reel_cover(package: InstagramContentPackage) -> InstagramRenderResult:
    """REEL format -> the cover IMAGE only (this codebase has no video-generation infrastructure -
    section 11's own explicit instruction). Never claims the actual Reel video was rendered - the
    evidence's own `notes` records that the video asset, if any, is external."""
    if package.content_format.value != "reel":
        raise InstagramRenderError(f"render_instagram_reel_cover requires REEL, got {package.content_format!r}")
    hook = package.media_plan.get("hook") or package.caption
    result = _render_text_card(package, profile=InstagramRenderProfile.REEL_COVER, headline=str(hook), subtext=package.cta)
    result.evidence.notes["video_asset"] = (
        package.external_video_asset_ref if package.external_video_asset_ref else "NONE - cover image only, no video generated"
    )
    return result
