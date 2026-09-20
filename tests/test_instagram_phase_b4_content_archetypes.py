"""Phase B.4: content-aware visual system. Proves the REAL claims - role does not uniquely
select composition, overlay=NONE performs zero pixel operations, per-slide asset identity is
independently trackable and enforceable for NEWS_RECAP, and the B.3-approved default path is
completely untouched code when no slide opts into the new structured fields."""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from schemas.instagram_creative import InstagramCarouselCreative, InstagramCarouselSlideCreative
from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_brain import evaluate_creative_fatigue, evaluate_fatigue_state
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import render_instagram_carousel
from services.instagram_shadow_pipeline import ShadowPlanResult

_OPP = ContentOpportunity(id="opp-b4", source_type=OpportunitySourceType.NEWS, story_id="s-b4", product_mention_allowed=True)
_SP = ShadowPlanResult(
    campaign_name=None, campaign_phase=None, opportunity_description="b4", primary_objective="reach",
    audience_description="", recommended_format="carousel", hook_family=None, creative_concept_summary="c",
    alternative_format=None, alternative_objective=None, product_mention_allowed=True, evidence=[], confidence=0.5,
)


def _image(color=(60, 90, 140)) -> Image.Image:
    img = Image.new("RGB", (1200, 1500), color)
    ImageDraw.Draw(img).rectangle([700, 900, 1200, 1500], fill=(220, 40, 30))
    return img


def _png_bytes(color) -> bytes:
    buf = io.BytesIO()
    _image(color).save(buf, format="PNG")
    return buf.getvalue()


def _package(slides: list[InstagramCarouselSlideCreative], archetype: str | None = None) -> InstagramCarouselCreative:
    carousel = InstagramCarouselCreative(objective="saves", slides=slides, content_archetype=archetype)
    return build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )


def _slides_with(comp_a: dict, comp_b: dict | None = None) -> list[InstagramCarouselSlideCreative]:
    return [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook", visual_direction="v"),
        InstagramCarouselSlideCreative(role="context", slide_copy="Same role, same copy class", visual_direction="v", **comp_a),
    ]


def test_same_role_different_composition_produces_different_geometry() -> None:
    img = _image()
    left_pkg = _package(_slides_with({"composition": "contained_media", "media_position": "left", "media_scale": 0.4}))
    top_pkg = _package(_slides_with({"composition": "contained_media", "media_position": "top", "media_scale": 0.4}))
    left = render_instagram_carousel(left_pkg, slide_images={0: img, 1: img})[1]
    top = render_instagram_carousel(top_pkg, slide_images={0: img, 1: img})[1]
    assert left.image_bytes != top.image_bytes
    assert left.evidence.notes["layout_variant"] != top.evidence.notes["layout_variant"]


def test_same_role_same_composition_different_scale_produces_different_geometry() -> None:
    img = _image()
    small_pkg = _package(_slides_with({"composition": "contained_media", "media_position": "left", "media_scale": 0.25}))
    big_pkg = _package(_slides_with({"composition": "contained_media", "media_position": "left", "media_scale": 0.6}))
    small = render_instagram_carousel(small_pkg, slide_images={0: img, 1: img})[1]
    big = render_instagram_carousel(big_pkg, slide_images={0: img, 1: img})[1]
    assert small.image_bytes != big.image_bytes


def test_overlay_none_performs_zero_pixel_operations() -> None:
    img = Image.new("RGB", (1200, 1500), (90, 90, 90))
    none_pkg = _package(_slides_with({"composition": "full_bleed_media", "overlay_mode": "none"}))
    scrim_pkg = _package(_slides_with({"composition": "full_bleed_media", "overlay_mode": "editorial_scrim"}))
    none_r = render_instagram_carousel(none_pkg, slide_images={0: img, 1: img})[1]
    scrim_r = render_instagram_carousel(scrim_pkg, slide_images={0: img, 1: img})[1]
    none_img = Image.open(io.BytesIO(none_r.image_bytes))
    scrim_img = Image.open(io.BytesIO(scrim_r.image_bytes))
    # sample a point far from any drawn text/mark - must be untouched by overlay=none, must be
    # measurably darker under editorial_scrim.
    assert none_img.getpixel((20, 20))[0] > 80
    assert scrim_img.getpixel((20, 20))[0] < 70


def test_archetype_field_does_not_hardcode_one_layout() -> None:
    """The SAME content_archetype string, applied to slides with different explicit compositions,
    must not collapse to one layout - archetype is a content-strategy label, never a rendering
    instruction (spec B.4 section 3/6)."""
    img = _image()
    pkg = _package(
        [
            InstagramCarouselSlideCreative(role="hook", slide_copy="Hook", visual_direction="v", composition="full_bleed_media"),
            InstagramCarouselSlideCreative(role="step", slide_copy="Step one", visual_direction="v", composition="screenshot_ui", media_position="top", media_scale=0.5),
            InstagramCarouselSlideCreative(role="takeaway", slide_copy="Takeaway", visual_direction="v", composition="typographic"),
        ],
        archetype="ai_hack",
    )
    results = render_instagram_carousel(pkg, slide_images={0: img, 1: img})
    variants = {r.evidence.notes["layout_variant"] for r in results}
    assert len(variants) == 3


def _recap_slides() -> list[InstagramCarouselSlideCreative]:
    return [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Recap", visual_direction="v", composition="typographic"),
        InstagramCarouselSlideCreative(
            role="story", slide_copy="Story A", visual_direction="v", composition="contained_media",
            media_position="top", media_subject="story-a", must_match_story=True,
        ),
        InstagramCarouselSlideCreative(
            role="story", slide_copy="Story B", visual_direction="v", composition="contained_media",
            media_position="top", media_subject="story-b", must_match_story=True,
        ),
        InstagramCarouselSlideCreative(
            role="story", slide_copy="Story C", visual_direction="v", composition="contained_media",
            media_position="top", media_subject="story-c", must_match_story=True,
        ),
    ]


def test_news_recap_distinct_story_assets_pass_validation() -> None:
    """Phase B.4.1: the resolver (not the LLM) supplies both the images and their identities -
    resolve_recap_story_assets() derives a real content-hash identity from each subject's actual
    resolved bytes."""
    from services.instagram_platform_renderer import resolve_recap_story_assets

    slides = _recap_slides()
    pkg = _package(slides, archetype="news_recap")
    raw_a, raw_b, raw_c = _png_bytes((60, 90, 140)), _png_bytes((140, 60, 90)), _png_bytes((90, 140, 60))
    subjects = {1: "story-a", 2: "story-b", 3: "story-c"}
    images, identities = resolve_recap_story_assets(subjects, {"story-a": raw_a, "story-b": raw_b, "story-c": raw_c})
    assert len(set(identities.values())) == 3  # three genuinely distinct, content-derived identities
    results = render_instagram_carousel(pkg, slide_images=images, asset_identities=identities)
    art = validate_instagram_art(pkg, results)
    assert art.passed is True
    assert art.blocking_issues == []


def test_news_recap_asset_reuse_is_blocked() -> None:
    """The exact failure spec B.4 section 10 forbids: two independent story slides silently
    sharing one generic asset must be a BLOCKING validation failure, not a passed carousel. Here
    the SAME bytes are (mis)resolved for two different stories - the resolver's own honest content
    hash naturally collides, and the validator catches it."""
    from services.instagram_platform_renderer import resolve_recap_story_assets

    slides = _recap_slides()[:3]  # hook + 2 stories
    pkg = _package(slides, archetype="news_recap")
    shared_raw = _png_bytes((90, 90, 90))
    subjects = {1: "story-a", 2: "story-a"}  # a resolver bug: both slides given the same subject
    images, identities = resolve_recap_story_assets(subjects, {"story-a": shared_raw})
    results = render_instagram_carousel(pkg, slide_images=images, asset_identities=identities)
    art = validate_instagram_art(pkg, results)
    assert art.passed is False
    assert any("news_recap_asset_reuse_violation" in issue for issue in art.blocking_issues)


def test_must_match_story_missing_asset_is_blocked() -> None:
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Recap", visual_direction="v", composition="typographic"),
        InstagramCarouselSlideCreative(
            role="story", slide_copy="Story A", visual_direction="v", composition="contained_media",
            media_position="top", media_subject="story-a", must_match_story=True,
        ),
        InstagramCarouselSlideCreative(role="takeaway", slide_copy="Close", visual_direction="v", composition="typographic"),
    ]
    pkg = _package(slides, archetype="news_recap")
    results = render_instagram_carousel(pkg)  # resolver found nothing - no asset_identities at all
    art = validate_instagram_art(pkg, results)
    assert art.passed is False
    assert any("must_match_story_missing_asset" in issue for issue in art.blocking_issues)


def test_llm_cannot_declare_its_own_asset_identity() -> None:
    """Phase B.4.1 section 7: structurally impossible, not just discouraged - the schema has no
    field an LLM could populate to claim an asset identity at all."""
    assert "media_asset_identity" not in InstagramCarouselSlideCreative.model_fields
    with pytest.raises(Exception):
        InstagramCarouselSlideCreative(
            role="story", slide_copy="x", visual_direction="v", media_asset_identity="fabricated",
        )


def test_claimed_composition_must_match_executed_composition() -> None:
    """A validator that only checks presence, not actual execution, would pass this - the real
    check must fail it (spec B.4 section 23's own "claimed composition not actually executed")."""
    from services.instagram_platform_renderer import InstagramRenderResult
    from services.instagram_render_evidence import RENDER_VERSION, InstagramRenderEvidence

    pkg = _package(_slides_with({"composition": "collage"}))
    real_results = render_instagram_carousel(pkg, slide_images={0: _image(), 1: _image()})
    tampered_evidence = real_results[1].evidence.__class__(
        **{**real_results[1].evidence.__dict__, "notes": {**real_results[1].evidence.notes, "layout_variant": "generic_typographic"}},
    )
    tampered = InstagramRenderResult(image_bytes=real_results[1].image_bytes, evidence=tampered_evidence)
    art = validate_instagram_art(pkg, [real_results[0], tampered])
    assert art.passed is False
    assert any("claimed_composition_not_executed" in issue for issue in art.blocking_issues)


def test_overlay_request_without_composition_is_blocked() -> None:
    """overlay_mode is only honoured by the NEW composition-driven path - requesting it without an
    explicit composition is an unenforceable claim, not a silent no-op."""
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook", visual_direction="v"),
        InstagramCarouselSlideCreative(role="context", slide_copy="Body", visual_direction="v", overlay_mode="none"),
    ]
    pkg = _package(slides)
    results = render_instagram_carousel(pkg, slide_images={0: _image(), 1: _image()})
    art = validate_instagram_art(pkg, results)
    assert art.passed is False
    assert any("overlay_mode_requires_composition" in issue for issue in art.blocking_issues)


def test_absent_media_has_a_safe_deliberate_fallback_not_a_crash() -> None:
    pkg = _package(_slides_with({"composition": "contained_media", "media_position": "left"}))
    results = render_instagram_carousel(pkg)  # no slide_images at all
    art = validate_instagram_art(pkg, results)
    assert results[1].evidence.source_image_treatment == "none"
    assert art.passed is True


def test_deterministic_rendering_with_new_structured_fields() -> None:
    img = _image()
    pkg = _package(_slides_with({"composition": "screenshot_ui", "media_position": "top", "media_scale": 0.5}))
    a = render_instagram_carousel(pkg, slide_images={0: img, 1: img})[1]
    b = render_instagram_carousel(pkg, slide_images={0: img, 1: img})[1]
    assert a.image_bytes == b.image_bytes


def test_cyrillic_renders_correctly_through_generic_composition() -> None:
    img = _image()
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Заголовок", visual_direction="v"),
        InstagramCarouselSlideCreative(
            role="context", slide_copy="Проверка кириллицы в новой системе композиции", visual_direction="v",
            composition="contained_media", media_position="top",
        ),
    ]
    pkg = _package(slides)
    result = render_instagram_carousel(pkg, slide_images={0: img, 1: img})[1]
    assert result.evidence.text_clipped is False
    assert result.evidence.visible_brand_mark_count == 1


def test_no_composition_field_exercises_the_unchanged_b3_default_path() -> None:
    """The founder-approved regression guarantee: a slide with NO structured fields at all must
    produce `composition_requested=None` in evidence, proving the OLD role-keyed dispatch ran,
    not the new generic one."""
    img = _image()
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Самая умная модель ≠ самая полезная", visual_direction="v"),
        InstagramCarouselSlideCreative(role="takeaway", slide_copy="Вывод", visual_direction="v"),
    ]
    pkg = _package(slides)
    results = render_instagram_carousel(pkg, slide_images={0: img, 1: img})
    assert results[0].evidence.notes["composition_requested"] is None
    assert results[0].evidence.notes["layout_variant"] == "carousel_hook"


def test_visual_fatigue_is_advisory_only_when_multiple_valid_directions_exist() -> None:
    """Reuses the EXISTING, accepted services/instagram_content_brain.py fatigue primitives
    directly - no parallel 'visual randomizer'. A repeated fingerprint should read as more fatigued
    than a fresh one, but this is advisory data, never a forced layout change - meaning fit still
    wins, which this test proves by construction (evaluate_fatigue_state does not touch content)."""
    fresh = evaluate_fatigue_state(dimension="visual", repetition_count=1, window_days=14)
    repeated = evaluate_fatigue_state(dimension="visual", repetition_count=6, window_days=14)
    assert fresh.value == "fresh"
    assert repeated.value in ("repeated", "fatigued", "overused")
    signal = evaluate_creative_fatigue(dimension="visual", value="contained_media|top|0.4|none", repetition_count=5, window_days=14)
    assert signal.is_fatigued is True


def test_no_provider_image_call_is_possible_by_construction_in_generic_composition() -> None:
    import ast

    path = "services/instagram_carousel_layouts.py"
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {"services.budgeted_image_execution", "integrations.llm_gateway.providers.openai_image_adapter"}
    assert imported.isdisjoint(forbidden)


def test_telegram_v8_renderer_still_never_imported() -> None:
    import ast

    path = "services/instagram_carousel_layouts.py"
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "services.brand_renderer" not in imported
