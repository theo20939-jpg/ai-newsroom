"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 6/9 + INSTAGRAM-VISUAL-SYSTEM-V1-1: the Instagram-
specific platform renderer.

Independent of `services/brand_renderer.py` (Telegram V8, FROZEN) - no import either direction.
Reuses ONLY brand-neutral shared assets via `services/instagram_visual_profiles.py` (bundled Fira
Sans Condensed, the canonical NNJ mark rasterizer) - a genuinely NEW composition for Instagram's
own geometry, never a resize of a Telegram card (section 6's own explicit instruction). No
Instagram UI chrome (progress bars, account chips, like/comment icons) is ever drawn into the
image - only the profile's own safe zones are respected so Instagram's OWN chrome never collides
with this renderer's content later.

Deterministic: the same `InstagramContentPackage` (+ the same optional real-media keyword
arguments) always produces byte-identical output (pure function of the package + those arguments +
the bundled, versioned font/logo assets).

V1.1 note: the Founder rejected this renderer's original visual output (a plain black text card,
section 0/1 of docs/instagram_visual_system_v1_1_report.md) - the actual composition now lives in
the visual-family layout modules (`services/instagram_editorial_layouts.py` NEWS/BREAKING,
`services/instagram_data_layouts.py` DATA, `services/instagram_quote_layouts.py` QUOTE,
`services/instagram_carousel_layouts.py` CAROUSEL, `services/instagram_reel_layouts.py` REEL COVER)
and their shared `services/instagram_design_tokens.py`/`services/instagram_image_handling.py`. This
module's job is now the STABLE part of the contract: package validation, evidence/identity
production, and the entrypoint signatures every other execution-architecture layer (review package,
editorial gate, Art validator, publish adapter) already calls - none of THOSE call signatures
changed."""
from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass

from PIL import Image

from services.instagram_carousel_layouts import render_carousel_slide
from services.instagram_content_package import InstagramContentPackage
from services.instagram_data_layouts import render_data_layout
from services.instagram_editorial_layouts import LayoutResult, render_breaking_layout, render_news_layout
from services.instagram_quote_layouts import render_quote_layout
from services.instagram_reel_layouts import render_reel_cover as _render_reel_cover_layout
from services.instagram_render_evidence import RENDER_VERSION, InstagramRenderEvidence, TextRegion
from services.instagram_visual_profiles import InstagramRenderProfile, profile_spec


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


def _kicker_for(package: InstagramContentPackage) -> str:
    """A truthful, non-fabricated category label: the real Director-produced
    `director_evidence["primary_objective"]` (e.g. "reach", "saves", "engagement" - see
    `ShadowPlanResult.primary_objective`, carried verbatim by `build_instagram_content_package()`),
    never an invented topic/section name no upstream layer actually produced."""
    objective = package.director_evidence.get("primary_objective")
    return str(objective).upper() if objective else "NINJA PULSE"


def _result_from_layout(
    layout: LayoutResult, package: InstagramContentPackage, *, profile: InstagramRenderProfile,
    slide_index: int | None = None, slide_count: int | None = None,
) -> InstagramRenderResult:
    """The one conversion point from a visual-family `LayoutResult` (instagram_editorial_layouts.py
    and friends) into the STABLE `InstagramRenderResult`/`InstagramRenderEvidence` contract every
    other execution-architecture layer already consumes - unchanged shape, new pixels underneath."""
    spec = profile_spec(profile)
    out = io.BytesIO()
    layout.image.save(out, format="JPEG", quality=92)

    text_regions = [TextRegion(kind=r.kind, box=r.box, clipped=r.clipped) for r in layout.text_regions]
    notes = dict(layout.notes)
    notes["layout_variant"] = layout.layout_variant

    evidence = InstagramRenderEvidence(
        render_version=RENDER_VERSION, content_format=package.content_format.value, profile=profile.value,
        canvas_width=spec.width, canvas_height=spec.height, visible_brand_mark_count=layout.visible_brand_mark_count,
        text_regions=text_regions, text_clipped=layout.text_clipped,
        source_image_treatment=layout.source_image_treatment,
        source_media_candidate_id=(package.media_candidate_id if layout.source_image_treatment not in ("none", "generated") else None),
        slide_index=slide_index, slide_count=slide_count, caption_linkage=package.package_id,
        content_identity=_content_identity(package, slide_index=slide_index),
        notes=notes,
    )
    return InstagramRenderResult(image_bytes=out.getvalue(), evidence=evidence)


def render_instagram_feed_image(package: InstagramContentPackage, *, source_image: Image.Image | None = None) -> InstagramRenderResult:
    """SINGLE format -> one PORTRAIT_FEED image, NEWS or BREAKING treatment (section 7/8).
    `presentation_family="breaking"` selects BREAKING; anything else (including the field's own
    default None) is the safe NEWS default - never an inferred family from freetext copy.
    `source_image` is an optional renderer-time keyword (mirrors Telegram's own
    `render_data_card(..., source_image_bytes=...)` precedent) - real bytes are never stored on the
    package itself, only `package.source_image_ref`'s traceable string."""
    if package.content_format.value != "single":
        raise InstagramRenderError(f"render_instagram_feed_image requires SINGLE, got {package.content_format!r}")
    headline = package.on_image_copy or package.caption
    spec = profile_spec(InstagramRenderProfile.PORTRAIT_FEED)

    if (package.presentation_family or "").strip().lower() == "breaking":
        layout = render_breaking_layout(spec=spec, source_image=source_image, headline=headline, dek=package.cta, package_identity=package.package_id)
    else:
        layout = render_news_layout(
            spec=spec, source_image=source_image, kicker=_kicker_for(package), headline=headline, dek=package.cta,
            package_identity=package.package_id,
        )
    return _result_from_layout(layout, package, profile=InstagramRenderProfile.PORTRAIT_FEED)


def render_instagram_single_data(
    package: InstagramContentPackage, *, metric_value: str, metric_unit: str | None, metric_label: str,
    context: str | None = None, series: list[tuple[str, float]] | None = None,
) -> InstagramRenderResult:
    """SINGLE format -> the DATA visual family (section 9). A deliberate SEPARATE entrypoint, not a
    `presentation_family="data"` branch of `render_instagram_feed_image` - `InstagramSingleCreative`
    carries no structured metric/series fields today, and parsing one out of freetext copy would be
    exactly the kind of fabrication section 9 forbids ("never fabricate chart points"). A caller
    that genuinely has real structured data (a metric a Data/Insight opportunity already computed)
    calls this directly with it; `series`, if supplied, must be the real measured points."""
    if package.content_format.value != "single":
        raise InstagramRenderError(f"render_instagram_single_data requires SINGLE, got {package.content_format!r}")
    spec = profile_spec(InstagramRenderProfile.PORTRAIT_FEED)
    layout = render_data_layout(
        spec=spec, kicker=_kicker_for(package), metric_value=metric_value, metric_unit=metric_unit,
        metric_label=metric_label, context=context, series=series, package_identity=package.package_id,
    )
    return _result_from_layout(layout, package, profile=InstagramRenderProfile.PORTRAIT_FEED)


def render_instagram_single_quote(
    package: InstagramContentPackage, *, quote: str, speaker: str, role: str | None = None,
    source_image: Image.Image | None = None,
) -> InstagramRenderResult:
    """SINGLE format -> the QUOTE visual family (section 10). A separate entrypoint for the same
    reason as `render_instagram_single_data` - no existing Instagram creative schema carries a
    structured speaker/quote pair, so a caller that has one (e.g. a real interview/statement)
    supplies it explicitly rather than this renderer inferring one from freetext copy."""
    if package.content_format.value != "single":
        raise InstagramRenderError(f"render_instagram_single_quote requires SINGLE, got {package.content_format!r}")
    spec = profile_spec(InstagramRenderProfile.PORTRAIT_FEED)
    layout = render_quote_layout(spec=spec, quote=quote, speaker=speaker, role=role, source_image=source_image, package_identity=package.package_id)
    return _result_from_layout(layout, package, profile=InstagramRenderProfile.PORTRAIT_FEED)


_MAX_CAROUSEL_SLIDES = 10  # Instagram's own platform ceiling (section 10's own "max slide bound")


def render_instagram_carousel(package: InstagramContentPackage, *, hero_image: Image.Image | None = None) -> list[InstagramRenderResult]:
    """CAROUSEL format -> one CAROUSEL_SLIDE image per planned slide, a real visual GRAMMAR across
    the deck (section 11) - slide layout is chosen from each slide's own real `role`
    (services/instagram_carousel_layouts.py::select_slide_layout), never identical title cards.
    Bounded to `_MAX_CAROUSEL_SLIDES` - never an uncontrolled count. `hero_image`, if supplied, is
    used ONLY for the hook/opening slide (section 11's "slide 1 = the strongest visual moment")."""
    if package.content_format.value != "carousel":
        raise InstagramRenderError(f"render_instagram_carousel requires CAROUSEL, got {package.content_format!r}")
    slides = package.media_plan.get("slides")
    if not isinstance(slides, list) or len(slides) < 2:
        raise InstagramRenderError("carousel package must carry >= 2 planned slides (media_plan['slides'])")
    if len(slides) > _MAX_CAROUSEL_SLIDES:
        raise InstagramRenderError(f"carousel slide count {len(slides)} exceeds the platform bound {_MAX_CAROUSEL_SLIDES}")

    total = len(slides)
    results = []
    for slide in slides:
        index = int(slide["index"])
        role = str(slide.get("role", ""))
        slide_copy = str(slide.get("text", ""))
        layout = render_carousel_slide(
            spec=profile_spec(InstagramRenderProfile.CAROUSEL_SLIDE), role=role, index=index, total=total,
            slide_copy=slide_copy, source_evidence=slide.get("source_evidence"), package_identity=package.package_id,
            hero_image=hero_image if index == 0 else None,
        )
        results.append(_result_from_layout(layout, package, profile=InstagramRenderProfile.CAROUSEL_SLIDE, slide_index=index, slide_count=total))
    return results


def render_instagram_reel_cover(package: InstagramContentPackage, *, source_image: Image.Image | None = None) -> InstagramRenderResult:
    """REEL format -> the cover IMAGE only (this codebase has no video-generation infrastructure -
    section 11's own explicit instruction). Never claims the actual Reel video was rendered - the
    evidence's own `notes` records that the video asset, if any, is external. Section 12's own
    grid/profile-crop-aware composition lives in `services/instagram_reel_layouts.py`."""
    if package.content_format.value != "reel":
        raise InstagramRenderError(f"render_instagram_reel_cover requires REEL, got {package.content_format!r}")
    hook = str(package.media_plan.get("hook") or package.caption)
    spec = profile_spec(InstagramRenderProfile.REEL_COVER)
    layout = _render_reel_cover_layout(spec=spec, kicker=_kicker_for(package), hook=hook, source_image=source_image, package_identity=package.package_id)
    result = _result_from_layout(layout, package, profile=InstagramRenderProfile.REEL_COVER)
    result.evidence.notes["video_asset"] = (
        package.external_video_asset_ref if package.external_video_asset_ref else "NONE - cover image only, no video generated"
    )
    return result
