"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 14: the smallest platform-aware Instagram Art
validation interface. Instagram content never passes through `services/telegram_art_director*.py`
(Telegram-only, section 13/14's own explicit instruction) - this module is a NEW, Instagram-native
validator over `InstagramRenderEvidence`, not a Telegram VisualSpec/SPEC_MATCH replay.

Deterministic, structural checks only (no vision-model call, no autonomous aesthetic redesign loop
- section 14's own explicit instruction). A bounded re-render hook exists
(`attempt_bounded_rerender`) but never loops silently: `max_retries` is explicit (1), it never
mutates the failing package's content on its own (no fabricated "fix"), and its default behaviour
with no caller-supplied revision strategy is fail-soft - surface the failure to the editor, never
retry blindly."""
from __future__ import annotations

from schemas.instagram_creative import TERMINAL_ROLES

from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Callable

from PIL import Image, ImageStat

from services.instagram_content_package import InstagramContentPackage
from services.instagram_platform_renderer import InstagramRenderResult
from services.instagram_visual_profiles import InstagramRenderProfile, profile_spec

MAX_ART_RERENDER_ATTEMPTS = 1

_FORMAT_EXPECTED_PROFILE = {
    "single": InstagramRenderProfile.PORTRAIT_FEED,
    "carousel": InstagramRenderProfile.CAROUSEL_SLIDE,
    "reel": InstagramRenderProfile.REEL_COVER,
}

# Phase B.4: the ONLY layout_variant values a given `composition` request may legitimately
# produce (services/instagram_carousel_layouts.py::_render_generic_composition /
# select_slide_layout's own SPLIT_COMPARE reuse) - anything else means the claim was not honoured.
_COMPOSITION_EXECUTION_EQUIVALENTS: dict[str, set[str]] = {
    "full_bleed_media": {"generic_full_bleed_media"},
    "contained_media": {f"generic_contained_media_{p}" for p in ("top", "left", "right")},
    "screenshot_ui": {f"generic_screenshot_ui_{p}" for p in ("top", "left", "right")} | {"generic_ui_frame"},
    "split_compare": {"generic_split_compare", "generic_split_compare_stacked"},
    "typographic": {
        "generic_typographic_editorial", "generic_typographic_step",
        "generic_typographic_statement", "generic_typographic_story_number",
    },
    "collage": {"generic_collage"},
}


@dataclass(frozen=True)
class InstagramArtValidationResult:
    passed: bool
    blocking_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    retry_recommended: bool = False
    retries_used: int = 0
    max_retries: int = MAX_ART_RERENDER_ATTEMPTS

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed, "blocking_issues": list(self.blocking_issues), "warnings": list(self.warnings),
            "retry_recommended": self.retry_recommended, "retries_used": self.retries_used, "max_retries": self.max_retries,
        }


def validate_instagram_art(
    package: InstagramContentPackage, render_results: list[InstagramRenderResult], *, retries_used: int = 0,
) -> InstagramArtValidationResult:
    blocking: list[str] = []
    warnings: list[str] = []

    if not render_results:
        blocking.append("empty_or_missing_media: no rendered asset was supplied for this package")
        return InstagramArtValidationResult(passed=False, blocking_issues=blocking, warnings=warnings, retries_used=retries_used)

    expected_profile = _FORMAT_EXPECTED_PROFILE.get(package.content_format.value)
    media_execution = package.media_plan.get("media_execution") or {}
    media_strategy = media_execution.get("strategy")
    creative_plan = package.media_plan.get("creative_execution_plan") or {}
    if not media_strategy and isinstance(creative_plan, dict):
        planned_strategy = creative_plan.get("media_strategy")
        if planned_strategy == "typographic":
            media_strategy = "typographic"
    if (
        package.content_format.value == "single" and not package.source_image_ref
        and media_strategy != "typographic"
    ):
        blocking.append(
            "single_media_reference_required"
            if media_strategy
            else "single_real_source_image_required"
        )
    for result in render_results:
        ev = result.evidence

        # 1. correct format/canvas
        if expected_profile is None:
            blocking.append(f"unknown_format: {package.content_format.value!r} has no expected render profile")
        else:
            spec = profile_spec(expected_profile)
            if (ev.canvas_width, ev.canvas_height) != (spec.width, spec.height):
                blocking.append(
                    f"wrong_canvas: expected {spec.width}x{spec.height} for {package.content_format.value}, "
                    f"got {ev.canvas_width}x{ev.canvas_height}"
                )
            if ev.profile != expected_profile.value:
                blocking.append(f"wrong_profile: expected {expected_profile.value!r}, got {ev.profile!r}")

        # 2. brand duplication (never 0, never > 1)
        if ev.visible_brand_mark_count == 0:
            blocking.append(f"missing_brand_mark: slide_index={ev.slide_index}")
        elif ev.visible_brand_mark_count > 1:
            blocking.append(f"duplicate_brand_mark: count={ev.visible_brand_mark_count} slide_index={ev.slide_index}")

        # 3. text overflow - a clipped HEADLINE is unacceptable quality; a clipped secondary line is
        #    a warning only (still legible, human can accept it).
        headline_clipped = any(t.clipped for t in ev.text_regions if t.kind == "headline")
        other_clipped = any(t.clipped for t in ev.text_regions if t.kind != "headline")
        if headline_clipped:
            blocking.append(f"headline_text_overflow: slide_index={ev.slide_index}")
        elif other_clipped:
            warnings.append(f"secondary_text_truncated: slide_index={ev.slide_index}")

        # 5. unreadable / empty content - no text regions drawn at all
        if not ev.text_regions:
            blocking.append(f"unreadable_or_empty_content: no text regions rendered, slide_index={ev.slide_index}")

        try:
            with Image.open(BytesIO(result.image_bytes)) as image:
                image.verify()
            with Image.open(BytesIO(result.image_bytes)) as image:
                grayscale = image.convert("L").resize((64, 64))
                if ImageStat.Stat(grayscale).stddev[0] < 2.0:
                    blocking.append(f"blank_or_near_blank_render: slide_index={ev.slide_index}")
        except (OSError, ValueError):
            blocking.append(f"rendered_media_unusable: slide_index={ev.slide_index}")

        # 6. source/media consistency (INSTAGRAM-VISUAL-SYSTEM-V1-1: this renderer now genuinely
        #    composites real source imagery - section 13). Any value outside the image-handling
        #    module's own truthful vocabulary would mean the evidence lied about what happened to
        #    the pixels - that is a BLOCKING integrity failure, not a warning.
        if ev.source_image_treatment not in ("none", "cover_cropped", "contain_preserved"):
            blocking.append(f"unknown_source_image_treatment: {ev.source_image_treatment!r} slide_index={ev.slide_index}")
        # a package that recorded a real `source_image_ref` but whose render shows no image was
        # actually applied usually means the caller forgot to pass the real bytes at render time -
        # a warning (not blocking: a legitimate no-image fallback render can still be intentional).
        if package.source_image_ref and ev.source_image_treatment == "none":
            issue = (
                f"source_image_ref_recorded_but_not_applied: package.source_image_ref={package.source_image_ref!r} "
                f"but this render's source_image_treatment is 'none' (slide_index={ev.slide_index})"
            )
            (blocking if package.content_format.value == "single" else warnings).append(issue)
        if package.content_format.value == "single":
            if ev.source_image_treatment == "none" and media_strategy != "typographic":
                blocking.append("single_source_image_not_rendered")

        # Phase B.1 objective creative-execution integrity. These checks do not pretend to judge
        # taste; they prove that the plan reached pixels and reject the exact mechanical failures
        # observed in founder review.
        leaked = {str(value).strip().upper() for value in ev.notes.get("internal_labels_rendered", [])}
        forbidden = {"CONTEXT", "THE PROBLEM", "HOW IT WORKS", "VALUE", "TAKEAWAY", "WHAT'S NEXT"}
        if leaked & forbidden:
            blocking.append(f"internal_render_label_leaked: {sorted(leaked & forbidden)} slide_index={ev.slide_index}")
        if package.media_plan.get("creative_execution_plan"):
            required_trace = {"creative_plan", "render_interpretation", "used_primitives", "source_media_treatment", "typography_treatment"}
            missing_trace = sorted(required_trace - set(ev.notes))
            if missing_trace or not ev.notes.get("render_plan_applied"):
                blocking.append(f"creative_plan_not_applied: missing={missing_trace} slide_index={ev.slide_index}")
        if ev.notes.get("source_media_treatment") == "full_bleed_hero":
            coverage = float(ev.notes.get("source_coverage_fraction", 0.0))
            if coverage < 0.70:
                blocking.append(f"hero_media_geometry_too_weak: coverage={coverage} slide_index={ev.slide_index}")
        if ev.notes.get("embedded_text_conflict_risk") and not ev.notes.get("embedded_text_strategy"):
            blocking.append(f"embedded_source_typography_untreated: slide_index={ev.slide_index}")

        # 7. caption/media package consistency
        if ev.caption_linkage != package.package_id:
            blocking.append(f"package_linkage_mismatch: render carries caption_linkage={ev.caption_linkage!r}, expected {package.package_id!r}")

        # 8. DATA number integrity (section 9/21: never a fabricated chart) - the graph variant is
        #    only ever a truthful renderer response to >=2 real supplied points; if evidence claims
        #    that variant without the series-point count to back it up, something upstream lied.
        if ev.notes.get("layout_variant") == "data_with_graph" and int(ev.notes.get("series_points", 0)) < 2:
            blocking.append(f"data_graph_without_real_series: slide_index={ev.slide_index} series_points={ev.notes.get('series_points')}")

        # 9. REEL COVER critical-content placement (section 12) - the hook text must fall inside
        #    the renderer's own recorded grid/profile-crop-safe band, not just the app-chrome safe
        #    zone, or it will be cropped away in the Reels tab / profile grid thumbnail.
        grid_band = ev.notes.get("grid_safe_band")
        if grid_band:
            band_top, band_bottom = grid_band
            for region in ev.text_regions:
                if region.kind == "hook" and (region.box[1] > band_bottom or region.box[3] < band_top):
                    blocking.append(f"reel_hook_outside_grid_safe_band: box={region.box} band={grid_band}")

    # carousel-specific: slide_count/slide_index consistency across the whole set
    if package.content_format.value == "carousel":
        slide_counts = {r.evidence.slide_count for r in render_results}
        if slide_counts != {package.slide_count}:
            blocking.append(f"slide_count_mismatch: package declares {package.slide_count}, renders report {slide_counts}")
        raw_indices = [r.evidence.slide_index for r in render_results]
        if any(idx is None for idx in raw_indices):
            blocking.append("slide_index_sequence_invalid: a carousel render is missing slide_index")
        indices = sorted(idx for idx in raw_indices if idx is not None)
        if indices != list(range(len(render_results))):
            blocking.append(f"slide_index_sequence_invalid: {indices}")

        is_news_recap = package.media_plan.get("content_archetype") == "news_recap"

        # Phase B.4.4 NO_OVERLAY_EXECUTED: every carousel render must prove it performed no overlay
        # operation and left its source-media pixels untouched. Structural evidence only - no vision
        # scoring. (A render that omits the evidence is treated as unproven, not as clean.)
        for r in render_results:
            notes = r.evidence.notes
            if "overlay_operations_executed" not in notes:
                blocking.append(f"overlay_evidence_missing: slide_index={r.evidence.slide_index}")
            elif notes.get("overlay_operations_executed"):
                blocking.append(f"overlay_executed_on_source_media: slide_index={r.evidence.slide_index}")
            if notes.get("source_media_pixels_unaltered") is False:
                blocking.append(f"source_media_pixels_altered: slide_index={r.evidence.slide_index}")

        # NEWS_RECAP's hard requirement (spec B.4 section 10/17): cross-slide asset uniqueness applies
        # to news_recap ONLY. must_match_story on any other archetype carries no uniqueness meaning.
        if is_news_recap:
            story_slides = [
                (r.evidence.slide_index, r.evidence.notes.get("media_asset_identity"))
                for r in render_results if r.evidence.notes.get("must_match_story")
            ]
            seen_identities: dict[str, int] = {}
            for slide_index, asset_identity in story_slides:
                if not asset_identity:
                    blocking.append(f"must_match_story_missing_asset: slide_index={slide_index}")
                    continue
                if asset_identity in seen_identities:
                    blocking.append(
                        f"news_recap_asset_reuse_violation: slide_index={slide_index} reuses the same "
                        f"asset_identity={asset_identity!r} already claimed by slide_index={seen_identities[asset_identity]}"
                    )
                else:
                    seen_identities[asset_identity] = slide_index

        # Phase B.5: a declarative layout the safe renderer REJECTED is surfaced (never silent); the
        # deterministic fallback renderer produced this slide's pixels instead.
        for r in render_results:
            rejected = r.evidence.notes.get("layout_plan_rejected")
            if rejected:
                warnings.append(f"layout_plan_rejected: slide_index={r.evidence.slide_index} reasons={rejected}")

        # The claimed composition family must be the one that actually rendered - unless the renderer
        # RECORDED an honest adaptation (text-fit reflow or a deliberate graphic fallback), which is
        # surfaced as a warning rather than silently passing or blocking.
        for r in render_results:
            composition_requested = r.evidence.notes.get("composition_requested")
            if composition_requested is None:
                continue
            executed = r.evidence.notes.get("layout_variant")
            equivalents = _COMPOSITION_EXECUTION_EQUIVALENTS.get(composition_requested, set())
            if executed in equivalents:
                continue
            if r.evidence.notes.get("composition_adapted_for_text_fit") or r.evidence.notes.get("graphic_fallback_used"):
                warnings.append(
                    f"composition_adapted: slide_index={r.evidence.slide_index} requested "
                    f"{composition_requested!r}, rendered {executed!r}"
                )
            else:
                blocking.append(
                    f"claimed_composition_not_executed: slide_index={r.evidence.slide_index} requested "
                    f"composition={composition_requested!r}, actual layout_variant={executed!r}"
                )

        # Phase B.6 MEDIA-FIRST: a slide that names its visual source must EXECUTE a meaningful visual (real/generated media or a substantive graphic) - never plain surface + text + logo.
        if package.media_plan.get("media_first"):
            from services.instagram_media_first import slide_has_visual

            planned = {int(s.get("index", i)): s for i, s in enumerate(package.media_plan.get("slides") or []) if isinstance(s, dict)}
            for r in render_results:
                if not slide_has_visual(notes=r.evidence.notes, planned_slide=planned.get(r.evidence.slide_index),
                                        source_image_treatment=r.evidence.source_image_treatment):
                    blocking.append(f"slide_without_meaningful_visual: slide_index={r.evidence.slide_index}")

        # carousel visual GRAMMAR (section 11/21): a real carousel should not present as the
        # identical layout on every slide after the hook - a warning (not blocking: a short, all-
        # detail-role deck can legitimately share one layout), so an editor can still see it. Phase B.5.1.2: the 4+ slide
        # "fewer than 3 variants" heuristic is a warning too - repetition can be deliberate and never blocks by itself.
        # Phase B.4 exception: NEWS_RECAP's own correct design is uniform per-story card treatment
        # (spec section 10) - its real distinctiveness is enforced separately, by asset identity
        # (news_recap_asset_reuse_violation above), not layout family. Applying a narrative-
        # progression diversity rule to a recap would be exactly the "aesthetic scoring model" the
        # validator must not become.
        non_hook_variants = {r.evidence.notes.get("layout_variant") for r in render_results if r.evidence.slide_index != 0}
        if not is_news_recap and len(render_results) >= 4 and len(non_hook_variants) < 3:
            warnings.append(f"carousel_layout_diversity_insufficient: non-hook variants={non_hook_variants}")  # advisory: repetition can be deliberate
        elif not is_news_recap and len(render_results) >= 3 and len(non_hook_variants) <= 1:
            warnings.append(f"carousel_layout_diversity_low: non-hook slides all use layout_variant={non_hook_variants}")
        if package.media_plan.get("creative_execution_plan"):
            slides = package.media_plan.get("slides") or []
            normalized_copy = [
                " ".join(str(slide.get("text") or "").lower().split())
                for slide in slides if isinstance(slide, dict)
            ]
            if len(normalized_copy) != len(set(normalized_copy)):
                blocking.append("carousel_duplicate_slide_copy")
            roles = [str(slide.get("role") or "").lower() for slide in slides if isinstance(slide, dict)]
            if slides and (not roles or roles[0] != "hook"):
                blocking.append("carousel_missing_hook_first")
            if slides and roles[-1] not in TERMINAL_ROLES:
                blocking.append("carousel_missing_closing_function")
            if slides and any(not slide.get("slide_purpose") for slide in slides if isinstance(slide, dict)):
                blocking.append("carousel_missing_slide_purpose")

    passed = not blocking
    return InstagramArtValidationResult(
        passed=passed, blocking_issues=blocking, warnings=warnings,
        retry_recommended=(not passed) and retries_used < MAX_ART_RERENDER_ATTEMPTS, retries_used=retries_used,
    )


def attempt_bounded_rerender(
    package: InstagramContentPackage, render_fn: Callable[[InstagramContentPackage], list[InstagramRenderResult]],
    *, revise_fn: Callable[[InstagramContentPackage], InstagramContentPackage] | None = None,
    max_retries: int = MAX_ART_RERENDER_ATTEMPTS,
) -> tuple[InstagramContentPackage, list[InstagramRenderResult], InstagramArtValidationResult]:
    """Renders + validates `package`; if it fails AND a `revise_fn` is supplied, retries at most
    `max_retries` times against a REVISED package (never a silent content mutation this module
    invents itself - the caller owns what "revise" means, e.g. a shorter headline). With no
    `revise_fn` (the default), this is a single deterministic render+validate pass - fail-soft,
    editor-visible, never an automatic loop."""
    current = package
    retries_used = 0
    while True:
        renders = render_fn(current)
        result = validate_instagram_art(current, renders, retries_used=retries_used)
        if result.passed or revise_fn is None or retries_used >= max_retries:
            return current, renders, result
        current = revise_fn(current)
        retries_used += 1
