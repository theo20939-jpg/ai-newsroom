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
from typing import Any, Callable

from services.instagram_content_package import InstagramContentPackage
from services.instagram_platform_renderer import InstagramRenderResult
from services.instagram_visual_profiles import InstagramRenderProfile, profile_spec

MAX_ART_RERENDER_ATTEMPTS = 1

_FORMAT_EXPECTED_PROFILE = {
    "single": InstagramRenderProfile.PORTRAIT_FEED,
    "carousel": InstagramRenderProfile.CAROUSEL_SLIDE,
    "reel": InstagramRenderProfile.REEL_COVER,
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

        # 6. source/media destruction - not applicable yet, this renderer never composites a source
        #    photo (section 6: a generated card, not a photo transform); disclosed, not silently skipped.
        if ev.source_image_treatment not in ("none",):
            warnings.append(f"source_image_treatment={ev.source_image_treatment!r} not yet validated by this module")

        # 7. caption/media package consistency
        if ev.caption_linkage != package.package_id:
            blocking.append(f"package_linkage_mismatch: render carries caption_linkage={ev.caption_linkage!r}, expected {package.package_id!r}")

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
