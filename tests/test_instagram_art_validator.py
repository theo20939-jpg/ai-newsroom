"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 27: Instagram Art validation."""
from __future__ import annotations

from dataclasses import replace

from PIL import Image

from services.instagram_art_validator import (
    MAX_ART_RERENDER_ATTEMPTS,
    attempt_bounded_rerender,
    validate_instagram_art,
)
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import InstagramContentPackage, build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import render_instagram_carousel, render_instagram_feed_image
from services.instagram_render_evidence import TextRegion
from services.instagram_shadow_pipeline import ShadowPlanResult
from schemas.instagram_creative import InstagramCarouselCreative, InstagramCarouselSlideCreative, InstagramSingleCreative

_SOURCE_IMAGE = Image.new("RGB", (512, 512), "navy")

_OPP = ContentOpportunity(id="opp-1", source_type=OpportunitySourceType.NEWS, story_id="s1", product_mention_allowed=True)
_SP = ShadowPlanResult(
    campaign_name=None, campaign_phase=None, opportunity_description="NEWS opp", primary_objective="reach",
    audience_description="", recommended_format="single", hook_family=None, creative_concept_summary="concept",
    alternative_format=None, alternative_objective=None, product_mention_allowed=True, evidence=[], confidence=0.5,
)


def _single_package(on_image_copy: str = "A clean short headline") -> InstagramContentPackage:
    single = InstagramSingleCreative(creative_angle="a", visual_concept="v", on_image_copy=on_image_copy, caption_direction="draft", final_caption="Company X announced a real update.", source_subject="Company X", cta="Learn more")
    return build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(single=single), source_image_ref="test-source",
    )


def test_valid_feed_render_passes() -> None:
    pkg = _single_package()
    result = render_instagram_feed_image(pkg, source_image=_SOURCE_IMAGE)
    art = validate_instagram_art(pkg, [result])
    assert art.passed is True
    assert art.blocking_issues == []


def test_empty_render_list_blocks() -> None:
    pkg = _single_package()
    art = validate_instagram_art(pkg, [])
    assert art.passed is False
    assert any("empty_or_missing_media" in issue for issue in art.blocking_issues)


def test_missing_brand_mark_blocks() -> None:
    pkg = _single_package()
    result = render_instagram_feed_image(pkg, source_image=_SOURCE_IMAGE)
    zeroed = replace(result, evidence=replace(result.evidence, visible_brand_mark_count=0))
    art = validate_instagram_art(pkg, [zeroed])
    assert art.passed is False
    assert any("missing_brand_mark" in issue for issue in art.blocking_issues)


def test_duplicate_brand_mark_blocks() -> None:
    pkg = _single_package()
    result = render_instagram_feed_image(pkg, source_image=_SOURCE_IMAGE)
    doubled = replace(result, evidence=replace(result.evidence, visible_brand_mark_count=2))
    art = validate_instagram_art(pkg, [doubled])
    assert art.passed is False
    assert any("duplicate_brand_mark" in issue for issue in art.blocking_issues)


def test_wrong_canvas_blocks() -> None:
    pkg = _single_package()
    result = render_instagram_feed_image(pkg, source_image=_SOURCE_IMAGE)
    wrong = replace(result, evidence=replace(result.evidence, canvas_width=999, canvas_height=999))
    art = validate_instagram_art(pkg, [wrong])
    assert art.passed is False
    assert any("wrong_canvas" in issue for issue in art.blocking_issues)


def test_clipped_headline_blocks_but_clipped_secondary_text_is_only_a_warning() -> None:
    pkg = _single_package()
    result = render_instagram_feed_image(pkg, source_image=_SOURCE_IMAGE)
    headline_region = TextRegion(kind="headline", box=(0, 0, 10, 10), clipped=True)
    clipped_headline = replace(result, evidence=replace(result.evidence, text_regions=[headline_region], text_clipped=True))
    art_headline = validate_instagram_art(pkg, [clipped_headline])
    assert art_headline.passed is False
    assert any("headline_text_overflow" in issue for issue in art_headline.blocking_issues)

    secondary_region = TextRegion(kind="caption_overlay", box=(0, 0, 10, 10), clipped=True)
    ok_headline = TextRegion(kind="headline", box=(0, 20, 100, 40), clipped=False)
    clipped_secondary = replace(result, evidence=replace(result.evidence, text_regions=[ok_headline, secondary_region], text_clipped=True))
    art_secondary = validate_instagram_art(pkg, [clipped_secondary])
    assert art_secondary.passed is True
    assert any("secondary_text_truncated" in w for w in art_secondary.warnings)


def test_unreadable_empty_content_blocks() -> None:
    pkg = _single_package()
    result = render_instagram_feed_image(pkg, source_image=_SOURCE_IMAGE)
    empty = replace(result, evidence=replace(result.evidence, text_regions=[]))
    art = validate_instagram_art(pkg, [empty])
    assert art.passed is False
    assert any("unreadable_or_empty_content" in issue for issue in art.blocking_issues)


def test_package_linkage_mismatch_blocks() -> None:
    pkg = _single_package()
    result = render_instagram_feed_image(pkg, source_image=_SOURCE_IMAGE)
    mismatched = replace(result, evidence=replace(result.evidence, caption_linkage="some-other-package-id"))
    art = validate_instagram_art(pkg, [mismatched])
    assert art.passed is False
    assert any("package_linkage_mismatch" in issue for issue in art.blocking_issues)


def test_carousel_slide_count_and_index_consistency() -> None:
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook", visual_direction="v1"),
        InstagramCarouselSlideCreative(role="body", slide_copy="Body", visual_direction="v2"),
    ]
    carousel = InstagramCarouselCreative(objective="saves", slides=slides)
    pkg = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )
    results = render_instagram_carousel(pkg)
    art_ok = validate_instagram_art(pkg, results)
    assert art_ok.passed is True

    tampered = list(results)
    tampered[1] = replace(tampered[1], evidence=replace(tampered[1].evidence, slide_count=99))
    art_bad = validate_instagram_art(pkg, tampered)
    assert art_bad.passed is False
    assert any("slide_count_mismatch" in issue for issue in art_bad.blocking_issues)


def test_bounded_rerender_hook_never_loops_without_a_caller_supplied_revision_strategy() -> None:
    pkg = _single_package()
    calls = {"n": 0}

    def failing_render(p):
        calls["n"] += 1
        result = render_instagram_feed_image(p, source_image=_SOURCE_IMAGE)
        return [replace(result, evidence=replace(result.evidence, visible_brand_mark_count=0))]

    final_pkg, renders, art = attempt_bounded_rerender(pkg, failing_render)
    assert art.passed is False
    assert calls["n"] == 1  # no revise_fn supplied -> exactly one attempt, fail-soft, editor-visible
    assert art.retry_recommended is True
    assert art.max_retries == MAX_ART_RERENDER_ATTEMPTS


def test_bounded_rerender_hook_respects_explicit_max_retries_with_a_revision_strategy() -> None:
    calls = {"n": 0}

    def failing_render(p):
        calls["n"] += 1
        result = render_instagram_feed_image(p, source_image=_SOURCE_IMAGE)
        return [replace(result, evidence=replace(result.evidence, visible_brand_mark_count=0))]

    def revise(p):
        return replace(p, on_image_copy=(p.on_image_copy or "") + " revised")

    pkg = _single_package()
    final_pkg, renders, art = attempt_bounded_rerender(pkg, failing_render, revise_fn=revise, max_retries=2)
    assert calls["n"] == 3  # initial + 2 retries, never unbounded
    assert art.passed is False
    assert art.retries_used == 2


def test_single_without_real_source_image_is_blocked() -> None:
    pkg = _single_package()
    no_source = replace(pkg, source_image_ref=None)
    render = render_instagram_feed_image(no_source)
    art = validate_instagram_art(no_source, [render])
    assert art.passed is False
    assert "single_real_source_image_required" in art.blocking_issues
    assert "single_source_image_not_rendered" in art.blocking_issues
