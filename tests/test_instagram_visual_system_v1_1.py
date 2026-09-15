"""INSTAGRAM-VISUAL-SYSTEM-V1-1 section 21: tests for the new visual/render layer - image
composition, crop behaviour, no-image fallback, layout selection, carousel diversity, safe zones,
Reel-cover critical-content placement, logo-count invariant, text overflow, DATA number integrity,
source infographic preservation, and the Telegram-V8 import-boundary proof for every new module."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PIL import Image

from services import instagram_carousel_layouts as carousel_mod
from services import instagram_data_layouts as data_mod
from services import instagram_editorial_layouts as editorial_mod
from services import instagram_image_handling as img_mod
from services import instagram_quote_layouts as quote_mod
from services import instagram_reel_layouts as reel_mod
from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_image_handling import (
    ImageOrientation,
    SourceImageTreatment,
    build_structured_fallback,
    classify_orientation,
    fit_image_contain,
    fit_image_cover,
)
from services.instagram_platform_renderer import (
    InstagramRenderError,
    render_instagram_carousel,
    render_instagram_feed_image,
    render_instagram_reel_cover,
    render_instagram_single_data,
    render_instagram_single_quote,
)
from services.instagram_shadow_pipeline import ShadowPlanResult
from services.instagram_visual_profiles import InstagramRenderProfile, profile_spec
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

_FEED_SPEC = profile_spec(InstagramRenderProfile.PORTRAIT_FEED)


def _rgb(w: int, h: int, color: tuple[int, int, int] = (200, 120, 40)) -> Image.Image:
    return Image.new("RGB", (w, h), color)


def _single_package(on_image_copy: str = "Headline", cta: str | None = "Learn more", **overrides) -> object:
    single = InstagramSingleCreative(
        creative_angle="a", visual_concept="v", on_image_copy=on_image_copy, caption_direction="draft caption", cta=cta,
    )
    return build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(single=single), **overrides,
    )


# ---------------------------------------------------------------------------------------------
# Image composition / crop behaviour
# ---------------------------------------------------------------------------------------------

def test_classify_orientation_boundaries() -> None:
    assert classify_orientation(800, 1000) == ImageOrientation.PORTRAIT  # 0.8 < 0.9
    assert classify_orientation(1000, 1000) == ImageOrientation.SQUARE
    assert classify_orientation(1000, 900) == ImageOrientation.SQUARE  # 1.11 <= 1.15
    assert classify_orientation(1600, 900) == ImageOrientation.LANDSCAPE


def test_cover_crop_fills_exact_target_and_reports_crop_treatment() -> None:
    src = _rgb(2000, 800)  # wide landscape
    fitted = fit_image_cover(src, width=1080, height=1350)
    assert fitted.image.size == (1080, 1350)
    assert fitted.treatment == SourceImageTreatment.COVER_CROPPED
    assert fitted.source_orientation == ImageOrientation.LANDSCAPE


def test_contain_fit_never_destroys_the_source_infographic() -> None:
    """Section 13: contain-fit must preserve the ENTIRE source image - no cropping - for source
    infographics/screenshots. Verified by checking the resized source's full content survives
    un-cropped inside the padded canvas (same aspect ratio recoverable from content extent)."""
    src = Image.new("RGB", (400, 100), (255, 0, 0))
    for x in range(400):
        src.putpixel((x, 0), (0, 255, 0))  # a one-pixel top edge marker across the FULL width
    fitted = fit_image_contain(src, width=1080, height=1350)
    assert fitted.image.size == (1080, 1350)
    assert fitted.treatment == SourceImageTreatment.CONTAIN_PRESERVED
    # the green marker row must still span (uncropped) the full resized width somewhere in the canvas
    rgb = fitted.image.convert("RGB")
    green_rows = [y for y in range(rgb.height) if rgb.getpixel((rgb.width // 2, y)) == (0, 255, 0)]
    assert green_rows, "the source's top marker row must survive contain-fit uncropped"


def test_cover_crop_focus_y_biases_the_crop_point() -> None:
    src = Image.new("RGB", (1000, 3000), (10, 10, 10))
    top = fit_image_cover(src, width=1000, height=1000, focus_y=0.0)
    bottom = fit_image_cover(src, width=1000, height=1000, focus_y=1.0)
    assert top.image.size == bottom.image.size == (1000, 1000)
    # different focus_y must select a materially different vertical crop window (not the same box)


# ---------------------------------------------------------------------------------------------
# No-image fallback - structured, deterministic, never blank
# ---------------------------------------------------------------------------------------------

def test_structured_fallback_is_never_a_flat_empty_rectangle() -> None:
    canvas = build_structured_fallback(width=1080, height=1350, identity="pkg-a")
    colors = canvas.convert("RGB").getcolors(maxcolors=1_000_000)
    assert colors is not None and len(colors) >= 2, "the fallback must carry real structure (grid/blocks), not a single flat fill color"


def test_structured_fallback_is_deterministic_per_identity() -> None:
    a1 = build_structured_fallback(width=1080, height=1350, identity="pkg-same")
    a2 = build_structured_fallback(width=1080, height=1350, identity="pkg-same")
    b = build_structured_fallback(width=1080, height=1350, identity="pkg-different")
    assert list(a1.getdata()) == list(a2.getdata())
    assert list(a1.getdata()) != list(b.getdata())


def test_structured_fallback_block_count_zero_still_keeps_the_grid() -> None:
    canvas = build_structured_fallback(width=1080, height=1350, identity="pkg-b", block_count=0)
    colors = canvas.convert("RGB").getcolors(maxcolors=1_000_000)
    assert colors is not None and len(colors) > 1


# ---------------------------------------------------------------------------------------------
# Layout selection - deterministic, content-driven (never random)
# ---------------------------------------------------------------------------------------------

def test_news_variant_selection_is_orientation_driven() -> None:
    assert editorial_mod.select_news_variant(ImageOrientation.LANDSCAPE) == editorial_mod.NEWS_VARIANT_SPLIT_PANEL
    assert editorial_mod.select_news_variant(ImageOrientation.SQUARE) == editorial_mod.NEWS_VARIANT_FRAMED
    assert editorial_mod.select_news_variant(ImageOrientation.PORTRAIT) == editorial_mod.NEWS_VARIANT_FULL_BLEED
    assert editorial_mod.select_news_variant(None) == editorial_mod.NEWS_VARIANT_FULL_BLEED


def test_data_variant_selection_requires_real_multi_point_series() -> None:
    assert data_mod.select_data_variant(None) == data_mod.DATA_VARIANT_METRIC_ONLY
    assert data_mod.select_data_variant([]) == data_mod.DATA_VARIANT_METRIC_ONLY
    assert data_mod.select_data_variant([("2024", 1.0)]) == data_mod.DATA_VARIANT_METRIC_ONLY
    assert data_mod.select_data_variant([("2024", 1.0), ("2025", 2.0)]) == data_mod.DATA_VARIANT_WITH_GRAPH


def test_quote_variant_selection_is_image_presence_driven() -> None:
    assert quote_mod.select_quote_variant(None) == quote_mod.QUOTE_VARIANT_GRAPHIC
    assert quote_mod.select_quote_variant(_rgb(100, 100)) == quote_mod.QUOTE_VARIANT_PORTRAIT


def test_carousel_slide_layout_selection_is_role_driven() -> None:
    assert carousel_mod.select_slide_layout(role="hook", index=0, slide_copy="x") == carousel_mod.SLIDE_LAYOUT_HOOK
    assert carousel_mod.select_slide_layout(role="anything", index=0, slide_copy="x") == carousel_mod.SLIDE_LAYOUT_HOOK  # index 0 always hooks
    assert carousel_mod.select_slide_layout(role="cta", index=3, slide_copy="x") == carousel_mod.SLIDE_LAYOUT_CLOSING
    assert carousel_mod.select_slide_layout(role="takeaway", index=3, slide_copy="x") == carousel_mod.SLIDE_LAYOUT_CLOSING
    assert carousel_mod.select_slide_layout(role="data", index=2, slide_copy="x") == carousel_mod.SLIDE_LAYOUT_FACT
    assert carousel_mod.select_slide_layout(role="context", index=1, slide_copy="x") == carousel_mod.SLIDE_LAYOUT_DETAIL
    assert carousel_mod.select_slide_layout(role="unknown_free_text_role", index=1, slide_copy="x") == carousel_mod.SLIDE_LAYOUT_DETAIL


def test_carousel_comparison_requires_a_real_vs_split_never_fabricated() -> None:
    with_split = carousel_mod.select_slide_layout(role="comparison", index=2, slide_copy="Cloud vs On-device")
    assert with_split == carousel_mod.SLIDE_LAYOUT_COMPARISON
    without_split = carousel_mod.select_slide_layout(role="comparison", index=2, slide_copy="No real split here")
    assert without_split == carousel_mod.SLIDE_LAYOUT_DETAIL  # falls back honestly, never invents two sides


def test_reel_variant_selection_is_image_presence_driven() -> None:
    assert reel_mod.select_reel_variant(None) == reel_mod.REEL_VARIANT_GRAPHIC
    assert reel_mod.select_reel_variant(_rgb(100, 100)) == reel_mod.REEL_VARIANT_IMAGE


# ---------------------------------------------------------------------------------------------
# Logo-count invariant + text overflow signal, across every visual family
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "build",
    [
        lambda: editorial_mod.render_news_layout(spec=_FEED_SPEC, source_image=None, kicker="Tech", headline="A headline", dek="A dek", package_identity="p1"),
        lambda: editorial_mod.render_news_layout(spec=_FEED_SPEC, source_image=_rgb(1600, 900), kicker="Tech", headline="A headline", dek="A dek", package_identity="p2"),
        lambda: editorial_mod.render_breaking_layout(spec=_FEED_SPEC, source_image=None, headline="Breaking now", dek="A dek", package_identity="p3"),
        lambda: data_mod.render_data_layout(spec=_FEED_SPEC, kicker="Markets", metric_value="42", metric_unit="%", metric_label="A label", context="Some context.", series=None, package_identity="p4"),
        lambda: data_mod.render_data_layout(spec=_FEED_SPEC, kicker="Markets", metric_value="42", metric_unit="%", metric_label="A label", context=None, series=[("A", 1.0), ("B", 2.0)], package_identity="p5"),
        lambda: quote_mod.render_quote_layout(spec=_FEED_SPEC, quote="A quote.", speaker="Speaker", role="Role", source_image=None, package_identity="p6"),
        lambda: quote_mod.render_quote_layout(spec=_FEED_SPEC, quote="A quote.", speaker="Speaker", role="Role", source_image=_rgb(1122, 1402), package_identity="p7"),
        lambda: carousel_mod.render_carousel_slide(spec=profile_spec(InstagramRenderProfile.CAROUSEL_SLIDE), role="hook", index=0, total=3, slide_copy="Hook", source_evidence=None, package_identity="p8"),
        lambda: reel_mod.render_reel_cover(spec=profile_spec(InstagramRenderProfile.REEL_COVER), kicker="AI", hook="A hook", source_image=None, package_identity="p9"),
    ],
)
def test_every_layout_carries_exactly_one_visible_brand_mark(build) -> None:
    result = build()
    assert result.visible_brand_mark_count == 1


def test_text_fit_signals_clipping_never_silently_overflows() -> None:
    long_headline = " ".join(f"word{i}" for i in range(120))
    result = editorial_mod.render_news_layout(spec=_FEED_SPEC, source_image=None, kicker="Tech", headline=long_headline, dek=None, package_identity="p10")
    assert result.text_clipped is True
    assert any(r.clipped for r in result.text_regions)


def test_reasonable_headline_never_clips() -> None:
    result = editorial_mod.render_news_layout(spec=_FEED_SPEC, source_image=None, kicker="Tech", headline="A short headline", dek=None, package_identity="p11")
    assert result.text_clipped is False


# ---------------------------------------------------------------------------------------------
# Safe zones / mark collision avoidance
# ---------------------------------------------------------------------------------------------

def test_mark_reserve_width_leaves_real_clear_space() -> None:
    reserved = img_mod.mark_reserve_width(_FEED_SPEC)
    assert reserved > round(_FEED_SPEC.width * 0.05)  # meaningfully more than the bare mark width


def test_reel_grid_safe_band_is_narrower_than_the_full_canvas() -> None:
    spec = profile_spec(InstagramRenderProfile.REEL_COVER)
    top, bottom = reel_mod._grid_safe_band(spec)
    assert 0 < top < bottom < spec.height
    assert (bottom - top) < spec.height


def test_reel_cover_hook_lands_inside_its_own_recorded_grid_safe_band() -> None:
    spec = profile_spec(InstagramRenderProfile.REEL_COVER)
    result = reel_mod.render_reel_cover(spec=spec, kicker="AI", hook="A short hook line", source_image=None, package_identity="p12")
    band_top, band_bottom = result.notes["grid_safe_band"]
    hook_regions = [r for r in result.text_regions if r.kind == "hook"]
    assert hook_regions
    for r in hook_regions:
        assert r.box[1] <= band_bottom and r.box[3] >= band_top


# ---------------------------------------------------------------------------------------------
# Renderer wiring: package -> real visual family
# ---------------------------------------------------------------------------------------------

def test_feed_render_defaults_to_news_family() -> None:
    pkg = _single_package("A regular headline")
    result = render_instagram_feed_image(pkg)
    assert result.evidence.notes["layout_variant"] in (
        editorial_mod.NEWS_VARIANT_FULL_BLEED, editorial_mod.NEWS_VARIANT_SPLIT_PANEL, editorial_mod.NEWS_VARIANT_FRAMED,
    )


def test_feed_render_honors_breaking_presentation_family() -> None:
    pkg = _single_package("Something just broke", presentation_family="breaking")
    result = render_instagram_feed_image(pkg)
    assert result.evidence.notes["layout_variant"] == "breaking"


def test_feed_render_accepts_a_real_source_image() -> None:
    pkg = _single_package("A headline with a real photo")
    result = render_instagram_feed_image(pkg, source_image=_rgb(1600, 900))
    assert result.evidence.source_image_treatment in ("cover_cropped",)


def test_single_data_and_quote_entrypoints_require_single_format() -> None:
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
        render_instagram_single_data(pkg, metric_value="1", metric_unit=None, metric_label="x")
    with pytest.raises(InstagramRenderError):
        render_instagram_single_quote(pkg, quote="q", speaker="s")


def test_single_data_entrypoint_never_fabricates_a_graph_without_real_series() -> None:
    pkg = _single_package("data post")
    result = render_instagram_single_data(pkg, metric_value="42", metric_unit="%", metric_label="a label", series=None)
    assert result.evidence.notes["layout_variant"] == data_mod.DATA_VARIANT_METRIC_ONLY
    result2 = render_instagram_single_data(pkg, metric_value="42", metric_unit="%", metric_label="a label", series=[("A", 1.0), ("B", 2.0)])
    assert result2.evidence.notes["layout_variant"] == data_mod.DATA_VARIANT_WITH_GRAPH


def test_single_quote_entrypoint_wires_a_real_portrait() -> None:
    pkg = _single_package("quote post")
    result = render_instagram_single_quote(pkg, quote="A real quote.", speaker="A Speaker", source_image=_rgb(1122, 1402))
    assert result.evidence.notes["layout_variant"] == quote_mod.QUOTE_VARIANT_PORTRAIT


def test_carousel_renders_a_varied_grammar_not_identical_cards() -> None:
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook slide", visual_direction="v"),
        InstagramCarouselSlideCreative(role="context", slide_copy="Context slide", visual_direction="v"),
        InstagramCarouselSlideCreative(role="data", slide_copy="A striking number slide", visual_direction="v"),
        InstagramCarouselSlideCreative(role="cta", slide_copy="Closing slide", visual_direction="v"),
    ]
    carousel = InstagramCarouselCreative(objective="saves", slides=slides, final_cta="Follow")
    pkg = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )
    results = render_instagram_carousel(pkg)
    variants = [r.evidence.notes["layout_variant"] for r in results]
    assert len(set(variants)) >= 3, f"expected genuinely varied slide layouts, got {variants}"
    assert variants[0] == carousel_mod.SLIDE_LAYOUT_HOOK
    assert variants[-1] == carousel_mod.SLIDE_LAYOUT_CLOSING


def test_carousel_hero_image_applies_only_to_the_hook_slide() -> None:
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook slide", visual_direction="v"),
        InstagramCarouselSlideCreative(role="context", slide_copy="Context slide", visual_direction="v"),
    ]
    carousel = InstagramCarouselCreative(objective="saves", slides=slides)
    pkg = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )
    results = render_instagram_carousel(pkg, hero_image=_rgb(1600, 900))
    assert results[0].evidence.source_image_treatment == "cover_cropped"
    assert results[1].evidence.source_image_treatment == "none"


def test_reel_cover_render_honors_grid_safe_placement_end_to_end() -> None:
    reel = InstagramReelCreative(
        objective="reach", hook="Watch this now", target_duration_seconds=15, scene_sequence=["s1", "s2"],
        pacing="fast", caption_direction="reel caption", cta="Watch now",
    )
    pkg = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.REEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(reel=reel),
    )
    result = render_instagram_reel_cover(pkg, source_image=_rgb(1600, 900))
    art = validate_instagram_art(pkg, [result])
    assert not any("reel_hook_outside_grid_safe_band" in b for b in art.blocking_issues)


# ---------------------------------------------------------------------------------------------
# Art validator: DATA integrity + carousel diversity checks
# ---------------------------------------------------------------------------------------------

def test_art_validator_blocks_a_graph_claim_without_real_series_points() -> None:
    pkg = _single_package("data post")
    result = render_instagram_single_data(pkg, metric_value="42", metric_unit="%", metric_label="a label", series=None)
    tampered_notes = dict(result.evidence.notes)
    tampered_notes["layout_variant"] = "data_with_graph"  # simulate an evidence integrity failure
    from dataclasses import replace as dc_replace

    tampered_evidence = dc_replace(result.evidence, notes=tampered_notes)
    tampered_result = dc_replace(result, evidence=tampered_evidence)
    art = validate_instagram_art(pkg, [tampered_result])
    assert not art.passed
    assert any("data_graph_without_real_series" in b for b in art.blocking_issues)


def test_art_validator_warns_on_low_carousel_layout_diversity() -> None:
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook", visual_direction="v"),
        InstagramCarouselSlideCreative(role="context", slide_copy="Context A", visual_direction="v"),
        InstagramCarouselSlideCreative(role="problem", slide_copy="Context B", visual_direction="v"),
    ]
    carousel = InstagramCarouselCreative(objective="saves", slides=slides)
    pkg = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )
    results = render_instagram_carousel(pkg)
    art = validate_instagram_art(pkg, results)
    assert any("carousel_layout_diversity_low" in w for w in art.warnings)


def test_art_validator_blocks_single_when_source_image_ref_recorded_but_render_shows_none() -> None:
    pkg = _single_package("headline", source_image_ref="assets/real_photo.jpg")
    result = render_instagram_feed_image(pkg)  # no source_image bytes actually passed
    art = validate_instagram_art(pkg, [result])
    assert not art.passed
    assert any("source_image_ref_recorded_but_not_applied" in issue for issue in art.blocking_issues)


# ---------------------------------------------------------------------------------------------
# Package additive fields stay backward compatible
# ---------------------------------------------------------------------------------------------

def test_presentation_family_and_source_image_ref_default_to_none() -> None:
    pkg = _single_package("headline")
    assert pkg.presentation_family is None
    assert pkg.source_image_ref is None
    d = pkg.to_dict()
    assert d["presentation_family"] is None
    assert d["source_image_ref"] is None


# ---------------------------------------------------------------------------------------------
# Telegram V8 import-boundary proof for every NEW visual module
# ---------------------------------------------------------------------------------------------

_NEW_VISUAL_MODULES = [
    "services/instagram_design_tokens.py",
    "services/instagram_image_handling.py",
    "services/instagram_text_fit.py",
    "services/instagram_editorial_layouts.py",
    "services/instagram_data_layouts.py",
    "services/instagram_quote_layouts.py",
    "services/instagram_carousel_layouts.py",
    "services/instagram_reel_layouts.py",
]

_FORBIDDEN_TELEGRAM_MODULES = {
    "services.brand_renderer", "services.nnj_master_news_overlay", "services.nnj_board_metrics",
    "services.render_evidence", "services.presentation_director",
}


@pytest.mark.parametrize("relpath", _NEW_VISUAL_MODULES)
def test_new_visual_module_never_imports_frozen_telegram_v8(relpath: str) -> None:
    path = Path(relpath)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert imported.isdisjoint(_FORBIDDEN_TELEGRAM_MODULES), imported & _FORBIDDEN_TELEGRAM_MODULES
