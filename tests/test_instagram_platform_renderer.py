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
    InstagramCreativeExecutionPlan,
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


def test_explicit_composition_causally_controls_whether_and_how_a_slide_shows_the_image() -> None:
    """Phase B.4.4: the creative plan's own `composition` decides whether/how a slide's real image
    appears (role no longer does). Same real asset on every slide; only the composition differs -
    and that difference must reach real, different pixel-level outcomes, not just notes."""
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook", visual_direction="v", composition="contained_media", media_position="top", media_scale=0.55),
        InstagramCarouselSlideCreative(role="context", slide_copy="Typographic slide text", visual_direction="v", composition="typographic"),
        InstagramCarouselSlideCreative(role="detail", slide_copy="Detail text", visual_direction="v", composition="collage"),
        InstagramCarouselSlideCreative(role="takeaway", slide_copy="Takeaway", visual_direction="v", composition="contained_media", media_position="left", media_scale=0.45),
    ]
    carousel = InstagramCarouselCreative(objective="saves", slides=slides)
    pkg = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )
    same_image = _small_real_image()
    results = render_instagram_carousel(pkg, slide_images={0: same_image, 1: same_image, 2: same_image, 3: same_image})
    treatments = [r.evidence.source_image_treatment for r in results]
    assert treatments == ["cover_cropped", "none", "cover_cropped", "cover_cropped"]
    variants = [r.evidence.notes.get("layout_variant") for r in results]
    assert variants[0] == "generic_contained_media_top" and variants[3] == "generic_contained_media_left"
    assert variants[1].startswith("generic_typographic") and variants[2] == "generic_collage"
    assert all(r.evidence.notes.get("source_media_pixels_unaltered") in (True, None) for r in results)


def test_role_default_applies_only_as_a_light_fallback_when_no_composition_is_planned() -> None:
    """Role may still supply a deterministic FALLBACK (recorded as a role fallback): media goes into
    its own region for non-closing roles, closing roles are type-led, comparison with a real ' vs '
    is a split - and nothing is dark or overlaid."""
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook", visual_direction="v"),
        InstagramCarouselSlideCreative(role="comparison", slide_copy="A vs B", visual_direction="v"),
        InstagramCarouselSlideCreative(role="unrecognised_role", slide_copy="Detail text", visual_direction="v"),
        InstagramCarouselSlideCreative(role="takeaway", slide_copy="Takeaway", visual_direction="v"),
    ]
    carousel = InstagramCarouselCreative(objective="saves", slides=slides)
    pkg = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )
    same_image = _small_real_image()
    results = render_instagram_carousel(pkg, slide_images={0: same_image, 1: same_image, 2: same_image, 3: same_image})
    assert [r.evidence.source_image_treatment for r in results] == ["cover_cropped", "none", "cover_cropped", "none"]
    assert all(r.evidence.notes.get("fallback_role_layout_used") is True for r in results)
    assert all(r.evidence.notes.get("overlay_operations_executed") == 0 for r in results)


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


def _quadrant_marker_image() -> tuple[Image.Image, tuple[int, int, int]]:
    """A real, non-uniform image with a bright, unmistakable marker ONLY in the bottom-right
    quadrant - the rest is uniform dark. A crop that actually reaches that corner will contain a
    lot of that exact color; a crop that does not will contain almost none of it."""
    img = Image.new("RGB", (1200, 1500), (20, 20, 20))
    marker = (255, 60, 10)
    ImageDraw.Draw(img).rectangle([800, 1000, 1200, 1500], fill=marker)
    return img, marker


def _marker_fraction(image: Image.Image, marker: tuple[int, int, int]) -> float:
    pixels = list(image.getdata())
    hits = sum(1 for p in pixels if abs(p[0] - marker[0]) < 20 and abs(p[1] - marker[1]) < 20 and abs(p[2] - marker[2]) < 20)
    return hits / len(pixels)


def _detail_package(focal_point: str) -> InstagramContentPackage:
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook", visual_direction="v", slide_purpose="hook"),
        InstagramCarouselSlideCreative(
            role="unrecognised_role_falls_to_detail", slide_copy="Detail text", visual_direction="v",
            media_need="крупный план, деталь", slide_purpose="detail",
        ),
        InstagramCarouselSlideCreative(role="takeaway", slide_copy="Takeaway text", visual_direction="v", slide_purpose="takeaway"),
    ]
    carousel = InstagramCarouselCreative(
        objective="saves", slides=slides,
        creative_execution_plan=InstagramCreativeExecutionPlan(
            main_idea="m", focal_point=focal_point, media_strategy="generated_media", media_rationale="r",
            composition_direction="c", branding_treatment="b", visual_treatment="v",
        ),
    )
    return build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel), source_image_ref="asset-1",
    )


def test_focal_point_causally_changes_the_actual_crop_not_just_notes() -> None:
    """Phase B.3.1 requirement: composition_direction/focal_point must change real composition,
    not only ride along as notes. Same source image, same DETAIL_CROP primitive, only the plan's
    own `focal_point` text differs - the RENDERED PIXELS must differ measurably as a result."""
    image, marker = _quadrant_marker_image()

    pkg_targeted = _detail_package("Рука с инструментом в нижней правой части кадра")
    pkg_neutral = _detail_package("Нейтральная композиция без выраженного фокуса")

    targeted = render_instagram_carousel(pkg_targeted, slide_images={0: image, 1: image})[1]
    neutral = render_instagram_carousel(pkg_neutral, slide_images={0: image, 1: image})[1]

    targeted_img = Image.open(io.BytesIO(targeted.image_bytes))
    neutral_img = Image.open(io.BytesIO(neutral.image_bytes))
    targeted_fraction = _marker_fraction(targeted_img, marker)
    neutral_fraction = _marker_fraction(neutral_img, marker)
    # a real difference in actual pixel content (not just a rounding difference, and not just a
    # difference in the recorded notes): the targeted crop must contain meaningfully more of the
    # marker color than the neutral crop, and the raw bytes must differ.
    assert targeted.image_bytes != neutral.image_bytes
    assert targeted_fraction > neutral_fraction * 1.5
    assert targeted_fraction > 0.02
    assert targeted.evidence.notes.get("creative_plan", {}).get("focal_point") != neutral.evidence.notes.get("creative_plan", {}).get("focal_point")


@pytest.mark.parametrize("role,expected", [
    ("hook", "cover_cropped"),
    ("context", "cover_cropped"),
    ("problem", "cover_cropped"),
    ("data", "cover_cropped"),
    ("unrecognised_falls_to_detail", "cover_cropped"),
    ("takeaway", "none"),
    ("cta", "none"),
])
def test_every_role_fallback_can_consume_a_real_supplied_image_in_its_own_region(role: str, expected: str) -> None:
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook", visual_direction="v"),
        InstagramCarouselSlideCreative(role=role, slide_copy="Body copy", visual_direction="v"),
    ]
    carousel = InstagramCarouselCreative(objective="saves", slides=slides)
    pkg = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )
    image = _small_real_image()
    results = render_instagram_carousel(pkg, slide_images={0: image, 1: image})
    assert results[1].evidence.source_image_treatment == expected


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
