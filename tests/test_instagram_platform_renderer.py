"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 27: platform renderer - feed/carousel/reel-cover
render, brand mark invariant, text overflow behaviour. TELEGRAM_V8_RUNTIME_CHANGED=false is
verified by construction here - this file never imports services/brand_renderer.py."""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import InstagramContentPackage, build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import (
    InstagramRenderError,
    render_instagram_carousel,
    render_instagram_feed_image,
    render_instagram_reel_cover,
)
from services.instagram_shadow_pipeline import ShadowPlanResult
from services.instagram_visual_profiles import INSTAGRAM_RENDER_PROFILES, InstagramRenderProfile
from schemas.instagram_creative import (
    InstagramCarouselCreative,
    InstagramCarouselSlideCreative,
    InstagramReelCreative,
    InstagramSingleCreative,
)

_OPP = ContentOpportunity(id="opp-1", source_type=OpportunitySourceType.NEWS, story_id="s1", product_mention_allowed=True)
_SP = ShadowPlanResult(
    campaign_name=None, campaign_phase=None, opportunity_description="NEWS opp", primary_objective="reach",
    audience_description="", recommended_format="single", hook_family=None, creative_concept_summary="concept",
    alternative_format=None, alternative_objective=None, product_mention_allowed=True, evidence=[], confidence=0.5,
)


def _single_package(on_image_copy: str, cta: str | None = "Learn more") -> InstagramContentPackage:
    single = InstagramSingleCreative(
        creative_angle="a", visual_concept="v", on_image_copy=on_image_copy, caption_direction="draft caption", cta=cta,
    )
    return build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(single=single),
    )


def test_feed_render_matches_the_portrait_feed_profile_exactly() -> None:
    pkg = _single_package("500 MILLION USERS REACHED")
    result = render_instagram_feed_image(pkg)
    im = Image.open(io.BytesIO(result.image_bytes))
    spec = INSTAGRAM_RENDER_PROFILES[InstagramRenderProfile.PORTRAIT_FEED]
    assert im.size == (spec.width, spec.height)
    assert result.evidence.canvas_width == spec.width and result.evidence.canvas_height == spec.height
    assert result.evidence.content_format == "single"
    assert result.evidence.profile == "portrait_feed"
    assert result.evidence.caption_linkage == pkg.package_id


def test_feed_render_is_deterministic() -> None:
    pkg = _single_package("Deterministic headline text")
    a = render_instagram_feed_image(pkg)
    b = render_instagram_feed_image(pkg)
    assert a.image_bytes == b.image_bytes
    assert a.evidence.content_identity == b.evidence.content_identity


def test_brand_mark_invariant_exactly_one_visible_mark() -> None:
    pkg = _single_package("Brand mark check")
    result = render_instagram_feed_image(pkg)
    assert result.evidence.visible_brand_mark_count == 1


def test_reasonable_headline_never_clips() -> None:
    pkg = _single_package("A short headline")
    result = render_instagram_feed_image(pkg)
    assert result.evidence.text_clipped is False
    assert not any(t.clipped for t in result.evidence.text_regions)


def test_extremely_long_headline_clips_with_a_signal_never_silently_overflows() -> None:
    # Built as a raw dataclass (bypassing the 200-char pydantic ceiling schemas/instagram_creative.py
    # enforces at CONTENT-GENERATION time) specifically to prove the RENDERER's own overflow
    # handling never silently drops text regardless of how long a caller-supplied string is.
    from dataclasses import replace

    base = _single_package("placeholder")
    long_text = " ".join(f"WORD{i}" for i in range(80))
    pkg = replace(base, on_image_copy=long_text)
    result = render_instagram_feed_image(pkg)
    assert result.evidence.text_clipped is True
    headline_regions = [t for t in result.evidence.text_regions if t.kind == "headline"]
    assert any(t.clipped for t in headline_regions)
    im = Image.open(io.BytesIO(result.image_bytes))
    assert im.size == (1080, 1350)  # canvas geometry itself never changes just because text overflowed


def test_feed_render_wrong_format_raises() -> None:
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="a", visual_direction="v"),
        InstagramCarouselSlideCreative(role="body", slide_copy="b", visual_direction="v"),
    ]
    carousel = InstagramCarouselCreative(objective="saves", slides=slides)
    pkg = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )
    with pytest.raises(InstagramRenderError):
        render_instagram_feed_image(pkg)


def test_carousel_render_produces_one_slide_per_planned_slide_same_profile() -> None:
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook slide text", visual_direction="v1"),
        InstagramCarouselSlideCreative(role="body", slide_copy="Body slide text", visual_direction="v2"),
        InstagramCarouselSlideCreative(role="cta", slide_copy="CTA slide text", visual_direction="v3"),
    ]
    carousel = InstagramCarouselCreative(objective="saves", slides=slides, final_cta="Follow for more")
    pkg = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )
    results = render_instagram_carousel(pkg)
    assert len(results) == 3
    spec = INSTAGRAM_RENDER_PROFILES[InstagramRenderProfile.CAROUSEL_SLIDE]
    for i, r in enumerate(results):
        im = Image.open(io.BytesIO(r.image_bytes))
        assert im.size == (spec.width, spec.height)
        assert r.evidence.slide_index == i
        assert r.evidence.slide_count == 3
        assert r.evidence.visible_brand_mark_count == 1  # every slide carries the mark, never duplicated per-slide beyond 1


def test_carousel_slide_count_bound_is_enforced() -> None:
    from services.instagram_platform_renderer import _MAX_CAROUSEL_SLIDES

    too_many = [InstagramCarouselSlideCreative(role="body", slide_copy=f"slide {i}", visual_direction="v") for i in range(_MAX_CAROUSEL_SLIDES + 1)]
    too_many[0] = InstagramCarouselSlideCreative(role="hook", slide_copy="hook", visual_direction="v")
    carousel = InstagramCarouselCreative(objective="saves", slides=too_many)
    pkg = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )
    with pytest.raises(InstagramRenderError):
        render_instagram_carousel(pkg)


def _small_real_image() -> Image.Image:
    img = Image.new("RGB", (600, 900), (60, 90, 140))
    ImageDraw.Draw(img).rectangle([100, 100, 500, 800], fill=(200, 30, 20))
    return img


def test_comparison_detail_closing_use_a_real_supplied_image_when_given_one() -> None:
    """Phase B.3 forensic fix: these three families previously had no way to show a real image at
    all - `source_image_treatment` stayed "none" no matter what was supplied. Reusing the SAME
    asset across the whole deck must now actually change the rendered background, not just carry
    inert metadata."""
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook", visual_direction="v"),
        InstagramCarouselSlideCreative(role="comparison", slide_copy="A vs B", visual_direction="v"),
        InstagramCarouselSlideCreative(role="unrecognised_role_falls_to_detail", slide_copy="Detail text", visual_direction="v"),
        InstagramCarouselSlideCreative(role="takeaway", slide_copy="Takeaway", visual_direction="v"),
    ]
    carousel = InstagramCarouselCreative(objective="saves", slides=slides)
    pkg = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )
    same_image = _small_real_image()
    results = render_instagram_carousel(pkg, slide_images={0: same_image, 1: same_image, 2: same_image, 3: same_image})
    treatments = [r.evidence.source_image_treatment for r in results]
    assert treatments[1] in ("cover_cropped", "contain_preserved")  # comparison
    assert treatments[2] in ("cover_cropped", "contain_preserved")  # detail
    assert treatments[3] in ("cover_cropped", "contain_preserved")  # closing (takeaway role)
    variants = {r.evidence.notes.get("layout_variant") for r in results}
    assert len(variants) >= 3  # still visually distinct families, not collapsed into one


def test_comparison_detail_closing_unchanged_when_no_image_is_supplied() -> None:
    """Backward compatibility: a caller with no real asset at all must render byte-identically to
    before this fix - "none" treatment, the synthetic structured fallback, nothing new required."""
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook", visual_direction="v"),
        InstagramCarouselSlideCreative(role="comparison", slide_copy="A vs B", visual_direction="v"),
        InstagramCarouselSlideCreative(role="takeaway", slide_copy="Takeaway", visual_direction="v"),
    ]
    carousel = InstagramCarouselCreative(objective="saves", slides=slides)
    pkg = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )
    results = render_instagram_carousel(pkg)
    assert [r.evidence.source_image_treatment for r in results] == ["none", "none", "none"]


def test_reel_cover_render_produces_only_the_cover_image_never_claims_video() -> None:
    reel = InstagramReelCreative(
        objective="reach", hook="Watch this now", target_duration_seconds=15, scene_sequence=["s1", "s2"],
        pacing="fast", caption_direction="reel caption", cta="Watch now",
    )
    pkg = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.REEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(reel=reel),
    )
    result = render_instagram_reel_cover(pkg)
    im = Image.open(io.BytesIO(result.image_bytes))
    spec = INSTAGRAM_RENDER_PROFILES[InstagramRenderProfile.REEL_COVER]
    assert im.size == (spec.width, spec.height)
    assert "no video generated" in result.evidence.notes["video_asset"]
    assert result.evidence.visible_brand_mark_count == 1


def test_no_import_of_the_frozen_telegram_v8_renderer() -> None:
    """TELEGRAM_V8_RUNTIME_CHANGED=false is structural, not just "we didn't edit the file" - the
    Instagram renderer's own IMPORT STATEMENTS never reference the frozen Telegram V8 modules (the
    module's docstring mentions them by name in prose, deliberately, to document the boundary -
    only actual `import`/`from ... import` lines are checked here)."""
    import ast

    import services.instagram_platform_renderer as mod

    with open(mod.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())

    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden = {"services.brand_renderer", "services.nnj_master_news_overlay", "services.nnj_board_metrics", "services.render_evidence"}
    assert imported_modules.isdisjoint(forbidden), imported_modules & forbidden
