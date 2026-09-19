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
    "contained_media": {f"generic_contained_media_{p}" for p in ("top", "left", "right", "full", "none")},
    "screenshot_ui": {f"generic_screenshot_ui_{p}" for p in ("top", "left", "right", "full", "none")},
    "split_compare": {"generic_split_compare", "carousel_comparison"},
    "typographic": {"generic_typographic"},
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
            # Phase B.3.1: a field existing in notes is NOT the same claim as the corresponding
            # pixel-level operation having actually occurred (the exact "fake implementation
            # evidence" the Founder flagged). `source_media_treatment` is the plan's own PREDICTION
            # (computed pre-render, package-level media availability); `media_primitive_selected`
            # is the REAL per-slide decision `render_carousel_slide` actually acted on. They must
            # agree - a mismatch means the plan's own recorded intent never reached these pixels
            # (e.g. a package-level asset existed but this specific slide was never given one).
            predicted = ev.notes.get("source_media_treatment")
            executed = ev.notes.get("media_primitive_selected")
            if predicted not in (None, "legacy_selection") and executed is not None and predicted != executed:
                blocking.append(
                    f"creative_plan_media_treatment_mismatch: plan predicted {predicted!r}, "
                    f"actual executed primitive was {executed!r} slide_index={ev.slide_index}"
                )
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

        # Phase B.4 §17/§23: NEWS_RECAP's hard requirement - a slide marked must_match_story=True
        # must have its OWN asset identity, and no two must_match_story slides may share one (the
        # exact "silent generic-source-reuse across unrelated stories" failure spec §10 forbids).
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

        # Phase B.4 §9/§23: a slide that explicitly requested an overlay treatment (including
        # "none") only has that request actually honoured by the NEW composition-driven render
        # path (_render_generic_composition) - the OLD role-keyed dispatch never reads
        # overlay_mode at all, so an overlay request with no explicit `composition` is silently
        # unenforceable, not a real "no overlay" guarantee. Fail closed rather than let that claim
        # pass unverified.
        for r in render_results:
            overlay_requested = r.evidence.notes.get("overlay_mode_requested")
            composition_requested = r.evidence.notes.get("composition_requested")
            if overlay_requested is not None and composition_requested is None:
                blocking.append(
                    f"overlay_mode_requires_composition: slide_index={r.evidence.slide_index} requested "
                    f"overlay_mode={overlay_requested!r} without an explicit composition to enforce it"
                )
            # Phase B.4 §8/§23: the claimed composition family must be the one that actually
            # rendered - never metadata that merely echoes the request.
            if composition_requested is not None:
                executed = r.evidence.notes.get("layout_variant")
                equivalents = _COMPOSITION_EXECUTION_EQUIVALENTS.get(composition_requested, set())
                if executed not in equivalents:
                    blocking.append(
                        f"claimed_composition_not_executed: slide_index={r.evidence.slide_index} requested "
                        f"composition={composition_requested!r}, actual layout_variant={executed!r}"
                    )

        # carousel visual GRAMMAR (section 11/21): a real carousel should not present as the
        # identical layout on every slide after the hook - a warning (not blocking: a short, all-
        # detail-role deck can legitimately share one layout), so an editor can still see it.
        # Phase B.4 exception: NEWS_RECAP's own correct design is uniform per-story card treatment
        # (spec section 10) - its real distinctiveness is enforced separately, by asset identity
        # (news_recap_asset_reuse_violation above), not layout family. Applying a narrative-
        # progression diversity rule to a recap would be exactly the "aesthetic scoring model" the
        # validator must not become.
        is_news_recap = package.media_plan.get("content_archetype") == "news_recap"
        non_hook_variants = {r.evidence.notes.get("layout_variant") for r in render_results if r.evidence.slide_index != 0}
        if not is_news_recap and len(render_results) >= 4 and len(non_hook_variants) < 3:
            blocking.append(f"carousel_layout_diversity_insufficient: non-hook variants={non_hook_variants}")
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
            if slides and roles[-1] not in {"takeaway", "cta"}:
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
