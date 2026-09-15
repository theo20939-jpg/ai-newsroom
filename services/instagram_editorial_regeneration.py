"""INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-1 §10: real regeneration of an Instagram package,
reusing the EXISTING Creative Director / renderer / editorial gate - never a second, parallel
content generator (§5). Three flavors:

  - `regenerate_full()` - "🔄 Переделать": a fresh Creative Director call, fresh render, fresh gate.
  - `regenerate_text_only()` - "📝 Текст": a fresh Creative Director call, but only its
    caption-facing fields (caption_direction/cta/evidence_used) survive into the new package - the
    visual-facing fields (on_image_copy/visual_concept/creative_angle for SINGLE;
    visual_direction/role for CAROUSEL slides; the storyboard/script for REEL) are forced back to
    their PREVIOUS values, and NO render or art-revalidation call is ever made at all - "approved
    media unchanged" is true by construction (the caller never even needs the original image bytes
    for this action), not by convention.
  - `regenerate_visual_only()` - "🎨 Визуал": the inverse - visual-facing fields come from the
    fresh call, caption-facing fields are forced back to their previous values, and the render step
    always runs (the visual genuinely may have changed).

For CAROUSEL, a field-level merge only makes sense when the new and previous slide counts match
(the safe, honest choice, not a fabricated best-effort alignment across different slide counts) -
`RegenerationError` is raised in that case, with a clear reason a caller (the button handler)
surfaces to the editor rather than silently falling back to something the editor didn't ask for.

`regenerator` (a `CreativeRegenerator` callable) is always required, never a hidden default: real
production callers build one with `build_default_regenerator(gateway, prompt_repository)` (a thin
wrapper over the real, existing Creative Director functions - never a second/parallel content
generator, §5); tests inject their own fake instead. Neither path is "the fake one is production" -
this module simply never constructs its own gateway (§20 "do not create fake demo-only delivery
logic")."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from PIL import Image

from services.instagram_content_opportunity import ContentOpportunity
from services.instagram_content_package import InstagramContentPackage, build_instagram_content_package
from services.instagram_creative_director import (
    CreativeDirectorInput,
    CreativeGenerationOutcome,
    generate_carousel_creative,
    generate_reel_creative,
    generate_single_creative,
)
from services.instagram_editorial_gate import InstagramGateOutcome, evaluate_instagram_editorial_gate
from services.instagram_art_validator import validate_instagram_art
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import (
    InstagramRenderResult,
    render_instagram_carousel,
    render_instagram_feed_image,
    render_instagram_reel_cover,
)
from services.instagram_shadow_pipeline import ShadowPlanResult
from schemas.instagram_creative import InstagramCarouselCreative, InstagramReelCreative, InstagramSingleCreative

CreativeRegenerator = Callable[[CreativeDirectorInput, ContentFormat], Awaitable[CreativeGenerationOutcome]]


class RegenerationError(ValueError):
    """A regeneration request that cannot be honestly fulfilled (e.g. a slide-count mismatch that
    would make a text/visual-only merge ambiguous) - never silently downgraded to "do it anyway.\""""


@dataclass(frozen=True)
class RegenerationResult:
    package: InstagramContentPackage
    renders: list[InstagramRenderResult]  # one item for single/reel-cover, N for carousel
    gate_outcome: InstagramGateOutcome
    creative: Any
    """The actual `InstagramSingleCreative`/`InstagramCarouselCreative`/`InstagramReelCreative`
    instance used to build `package` - a caller persisting a new `package_snapshot` needs this as
    the NEXT regeneration's `previous_creative` (never re-derived lossily from `package.to_dict()`,
    which does not round-trip per-slide/storyboard granularity)."""


def build_default_regenerator(gateway: Any, prompt_repository: Any) -> CreativeRegenerator:
    """The real, production wiring: a thin closure over the EXISTING Creative Director functions -
    never a second/parallel content generator (§5). `gateway`/`prompt_repository` are supplied by
    the caller (whichever application-wiring layer already constructs the real `LLMGateway`/
    `PromptRepository` for the rest of the Instagram pipeline) - this module never constructs its
    own, matching every other Instagram-pipeline module's own convention of taking them as
    parameters, never as globals."""

    async def _regenerate(director_input: CreativeDirectorInput, fmt: ContentFormat) -> CreativeGenerationOutcome:
        if fmt is ContentFormat.SINGLE:
            return await generate_single_creative(gateway, prompt_repository, director_input=director_input)
        if fmt is ContentFormat.CAROUSEL:
            return await generate_carousel_creative(gateway, prompt_repository, director_input=director_input)
        if fmt is ContentFormat.REEL:
            return await generate_reel_creative(gateway, prompt_repository, director_input=director_input)
        raise RegenerationError(f"unsupported format: {fmt!r}")

    return _regenerate


_SINGLE_TEXT_FIELDS = ("caption_direction", "final_caption", "source_subject", "cta", "evidence_used")
_SINGLE_VISUAL_FIELDS = ("creative_angle", "visual_concept", "on_image_copy", "asset_requirements")
_SLIDE_TEXT_FIELDS = ("slide_copy",)
_SLIDE_VISUAL_FIELDS = ("role", "visual_direction", "source_evidence")
_CAROUSEL_TEXT_FIELDS = ("final_cta",)
_REEL_TEXT_FIELDS = ("caption_direction", "final_caption", "source_subject", "cta", "evidence_used", "scenes")
_REEL_VISUAL_FIELDS = (
    "hook", "target_duration_seconds", "scene_sequence", "shot_list", "voiceover_script",
    "on_screen_text", "b_roll_requirements", "pacing", "audio_direction", "loop_ending_concept",
    "scenes",
)


def _merge_single(previous: InstagramSingleCreative, fresh: InstagramSingleCreative, *, keep_fields: tuple[str, ...]) -> InstagramSingleCreative:
    update = {f: getattr(fresh, f) for f in InstagramSingleCreative.model_fields if f not in keep_fields and f != "schema_version"}
    return previous.model_copy(update=update)


def _merge_carousel(previous: InstagramCarouselCreative, fresh: InstagramCarouselCreative, *, text_only: bool) -> InstagramCarouselCreative:
    if len(previous.slides) != len(fresh.slides):
        raise RegenerationError(
            f"cannot merge a {'text' if text_only else 'visual'}-only regeneration: slide count changed "
            f"({len(previous.slides)} -> {len(fresh.slides)}) - use full regeneration instead"
        )
    slide_keep = _SLIDE_VISUAL_FIELDS if text_only else _SLIDE_TEXT_FIELDS
    merged_slides = []
    for old_slide, new_slide in zip(previous.slides, fresh.slides):
        update = {f: getattr(new_slide, f) for f in type(old_slide).model_fields if f not in slide_keep}
        merged_slides.append(old_slide.model_copy(update=update))
    top_update: dict[str, Any] = {"slides": merged_slides}
    for f in ("final_cta", "objective", "evidence_used"):
        if f == "slides":
            continue
        if text_only and f in _CAROUSEL_TEXT_FIELDS:
            top_update[f] = getattr(fresh, f)
        elif not text_only and f not in _CAROUSEL_TEXT_FIELDS:
            top_update[f] = getattr(fresh, f)
    return previous.model_copy(update=top_update)


def _merge_reel(previous: InstagramReelCreative, fresh: InstagramReelCreative, *, keep_fields: tuple[str, ...]) -> InstagramReelCreative:
    update = {f: getattr(fresh, f) for f in InstagramReelCreative.model_fields if f not in keep_fields and f != "schema_version"}
    return previous.model_copy(update=update)


async def _rebuild(
    *, opportunity: ContentOpportunity, format_decision: FormatDecision, shadow_plan: ShadowPlanResult,
    creative_outcome: CreativeGenerationOutcome, account_key: str, external_video_asset_ref: str | None,
    presentation_family: str | None, source_image_ref: str | None, media_selection: Any | None,
    source_image: Image.Image | None, needs_render: bool, previous_renders: list[InstagramRenderResult],
) -> RegenerationResult:
    package = build_instagram_content_package(
        opportunity=opportunity, format_decision=format_decision, shadow_plan=shadow_plan,
        creative_outcome=creative_outcome, account_key=account_key,
        external_video_asset_ref=external_video_asset_ref, presentation_family=presentation_family,
        source_image_ref=source_image_ref, media_selection=media_selection,
    )
    if not needs_render:
        renders = previous_renders
    elif format_decision.recommended_format is ContentFormat.SINGLE:
        renders = [render_instagram_feed_image(package, source_image=source_image)]
    elif format_decision.recommended_format is ContentFormat.CAROUSEL:
        renders = render_instagram_carousel(package, hero_image=source_image)
    else:
        renders = [render_instagram_reel_cover(package, source_image=source_image)]

    art = validate_instagram_art(package, renders)
    gate = evaluate_instagram_editorial_gate(package, art)
    creative = creative_outcome.single or creative_outcome.carousel or creative_outcome.reel
    return RegenerationResult(package=package, renders=renders, gate_outcome=gate, creative=creative)


async def regenerate_full(
    *, opportunity: ContentOpportunity, format_decision: FormatDecision, shadow_plan: ShadowPlanResult,
    director_input: CreativeDirectorInput, account_key: str = "default",
    external_video_asset_ref: str | None = None, presentation_family: str | None = None,
    source_image_ref: str | None = None, media_selection: Any | None = None,
    source_image: Image.Image | None = None, regenerator: CreativeRegenerator,
) -> RegenerationResult:
    fresh = await regenerator(director_input, format_decision.recommended_format)
    return await _rebuild(
        opportunity=opportunity, format_decision=format_decision, shadow_plan=shadow_plan,
        creative_outcome=fresh, account_key=account_key, external_video_asset_ref=external_video_asset_ref,
        presentation_family=presentation_family, source_image_ref=source_image_ref, media_selection=media_selection,
        source_image=source_image, needs_render=True, previous_renders=[],
    )


def _merge_creative(fmt: ContentFormat, previous_creative: Any, fresh_outcome: CreativeGenerationOutcome, *, text_only: bool) -> CreativeGenerationOutcome:
    if fmt is ContentFormat.SINGLE:
        keep = _SINGLE_VISUAL_FIELDS if text_only else _SINGLE_TEXT_FIELDS
        return CreativeGenerationOutcome(single=_merge_single(previous_creative, fresh_outcome.single, keep_fields=keep))
    if fmt is ContentFormat.CAROUSEL:
        return CreativeGenerationOutcome(carousel=_merge_carousel(previous_creative, fresh_outcome.carousel, text_only=text_only))
    if fmt is ContentFormat.REEL:
        keep = _REEL_VISUAL_FIELDS if text_only else _REEL_TEXT_FIELDS
        return CreativeGenerationOutcome(reel=_merge_reel(previous_creative, fresh_outcome.reel, keep_fields=keep))
    raise RegenerationError(f"unsupported format: {fmt!r}")


@dataclass(frozen=True)
class TextOnlyRegenerationResult:
    """§10 "📝 Текст"'s own, deliberately lighter-weight result shape - NO render, NO art
    re-validation, NO image bytes required anywhere in this call: the visual-facing fields are
    forced back to their exact previous values (never merely "probably unchanged"), so the
    previously-computed QA verdict provably still applies and is carried forward unchanged rather
    than recomputed against nothing."""

    package: InstagramContentPackage
    creative: Any
    """The merged creative object - needed as the NEXT regeneration's `previous_creative`."""


async def regenerate_text_only(
    *, opportunity: ContentOpportunity, format_decision: FormatDecision, shadow_plan: ShadowPlanResult,
    director_input: CreativeDirectorInput, previous_creative: Any, account_key: str = "default",
    external_video_asset_ref: str | None = None, presentation_family: str | None = None,
    source_image_ref: str | None = None, media_selection: Any | None = None, regenerator: CreativeRegenerator,
) -> TextOnlyRegenerationResult:
    """No `source_image`/render/art-validation dependency at all - this is the whole point: a
    caption-only change can never require the original image bytes to still be available."""
    fresh_outcome = await regenerator(director_input, format_decision.recommended_format)
    creative_outcome = _merge_creative(format_decision.recommended_format, previous_creative, fresh_outcome, text_only=True)
    package = build_instagram_content_package(
        opportunity=opportunity, format_decision=format_decision, shadow_plan=shadow_plan,
        creative_outcome=creative_outcome, account_key=account_key,
        external_video_asset_ref=external_video_asset_ref, presentation_family=presentation_family,
        source_image_ref=source_image_ref, media_selection=media_selection,
    )
    merged = creative_outcome.single or creative_outcome.carousel or creative_outcome.reel
    return TextOnlyRegenerationResult(package=package, creative=merged)


async def regenerate_visual_only(
    *, opportunity: ContentOpportunity, format_decision: FormatDecision, shadow_plan: ShadowPlanResult,
    director_input: CreativeDirectorInput, previous_creative: Any, account_key: str = "default",
    external_video_asset_ref: str | None = None, presentation_family: str | None = None,
    source_image_ref: str | None = None, media_selection: Any | None = None,
    source_image: Image.Image | None = None, regenerator: CreativeRegenerator,
) -> RegenerationResult:
    """§10 "🎨 Визуал": visual-facing fields come from a fresh Creative Director call, the caption
    is forced back to its previous value, and a fresh render always runs (the visual genuinely may
    have changed). `media_selection`/`source_image` must resolve to the SAME already-approved
    media (never a fresh subject-discovery pass) - "do not change subject identity" (§10) is the
    caller's responsibility to uphold by re-supplying the same inputs, not something this function
    can verify on its own."""
    fresh_outcome = await regenerator(director_input, format_decision.recommended_format)
    creative_outcome = _merge_creative(format_decision.recommended_format, previous_creative, fresh_outcome, text_only=False)
    return await _rebuild(
        opportunity=opportunity, format_decision=format_decision, shadow_plan=shadow_plan,
        creative_outcome=creative_outcome, account_key=account_key, external_video_asset_ref=external_video_asset_ref,
        presentation_family=presentation_family, source_image_ref=source_image_ref, media_selection=media_selection,
        source_image=source_image, needs_render=True, previous_renders=[],
    )
