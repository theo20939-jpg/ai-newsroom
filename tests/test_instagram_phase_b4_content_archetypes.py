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
from services.instagram_image_handling import fit_image_cover
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


def _region_mean_rgb(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[float, float, float]:
    region = image.convert("RGB").crop(box)
    total = region.width * region.height
    return tuple(  # type: ignore[return-value]
        sum(v * c for v, c in enumerate(region.getchannel(i).histogram())) / total for i in range(3)
    )


@pytest.mark.parametrize("composition,extra", [
    ("full_bleed_media", {}),
    ("contained_media", {"media_position": "top", "media_scale": 0.4}),
    ("contained_media", {"media_position": "left", "media_scale": 0.4}),
    ("contained_media", {"media_position": "right", "media_scale": 0.4}),
    ("screenshot_ui", {"media_position": "top", "media_scale": 0.4}),
    ("collage", {}),
    ("split_compare", {}),
    ("typographic", {}),
])
def test_no_overlay_on_any_executable_composition(composition: str, extra: dict) -> None:
    """Phase B.4.4: for EVERY executable composition, rendering with a real source image performs
    ZERO overlay operations and leaves the source media's pixels untouched."""
    img = _image()
    pkg = _package(_slides_with({"composition": composition, **extra}))
    result = render_instagram_carousel(pkg, slide_images={0: img, 1: img})[1]
    notes = result.evidence.notes
    assert notes["overlay_operations_executed"] == 0
    assert notes["source_media_pixels_unaltered"] in (True, None)


@pytest.mark.parametrize("position,box", [
    ("top", (60, 20, 300, 120)),
    ("left", (20, 40, 150, 400)),
    ("right", (930, 40, 1060, 400)),
])
def test_contained_media_region_keeps_the_source_pixels(position: str, box: tuple[int, int, int, int]) -> None:
    """Independent pixel proof (not the renderer's own flag): the mean colour of a region INSIDE the
    media rectangle equals the untouched source crop - no dark, red or gradient wash."""
    from services.instagram_carousel_layouts import _media_box

    class _Spec:
        width, height = 1080, 1350

    img = _image()
    pkg = _package(_slides_with({"composition": "contained_media", "media_position": position, "media_scale": 0.45}))
    rendered = Image.open(io.BytesIO(render_instagram_carousel(pkg, slide_images={0: img, 1: img})[1].image_bytes)).convert("RGB")
    bx0, by0, bx1, by1 = _media_box(_Spec, position, 0.45)  # type: ignore[arg-type]
    fitted = fit_image_cover(img, width=bx1 - bx0, height=by1 - by0).image
    observed = _region_mean_rgb(rendered, (bx0 + box[0] % max(1, bx1 - bx0 - 40), by0 + 20, bx0 + box[0] % max(1, bx1 - bx0 - 40) + 30, by0 + 60))
    expected = _region_mean_rgb(fitted, (box[0] % max(1, bx1 - bx0 - 40), 20, box[0] % max(1, bx1 - bx0 - 40) + 30, 60))
    assert all(abs(o - e) < 8 for o, e in zip(observed, expected)), (observed, expected)


def test_renderer_module_contains_no_overlay_scrim_dim_or_blur_execution() -> None:
    """Static audit (AST, not text): the active carousel renderer imports/calls no readability
    gradient, dimmed-field, scrim, blur or alpha-composite helper."""
    import ast

    with open("services/instagram_carousel_layouts.py", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    forbidden_names = {
        "apply_bottom_readability_gradient", "apply_top_readability_gradient", "build_dimmed_source_field",
        "_apply_overlay", "GaussianBlur", "ImageFilter", "SourceMediaPrimitive", "DIMMED_FIELD",
    }
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in forbidden_names:
            seen.add(node.id)
        if isinstance(node, ast.ImportFrom):
            seen |= {alias.name for alias in node.names if alias.name in forbidden_names}
        if isinstance(node, ast.Attribute) and node.attr in ("alpha_composite", "filter"):
            seen.add(node.attr)
    assert not seen, f"active carousel renderer references removed overlay machinery: {seen}"


def test_overlay_is_absent_from_every_active_contract() -> None:
    """Prompt (LLM schema + rules), Python creative schema, and the package media plan."""
    import yaml

    from services.instagram_creative_director import CAROUSEL_PROMPT_VERSION

    assert CAROUSEL_PROMPT_VERSION == "10.6"
    for version in ("7", "8", "9"):  # the removed concept is absent from every contract's SCHEMA; v9 may only name it in a prohibition
        text = open(f"prompts/instagram_creative_director_carousel/v{version}.yaml", encoding="utf-8").read().lower()
        parsed = yaml.safe_load(text)
        schema_text = str(parsed["output_schema"]).lower()
        for term in ("overlay", "scrim", "darken", "dimm", "gradient", "tint"):
            assert term not in schema_text, (version, term)
            if version != "9":
                assert term not in text, (version, term)
            else:  # v9 states the prohibition itself: every rule that mentions the term must negate it
                for rule in parsed["rules"]:
                    if term in rule.lower():
                        assert any(neg in rule for neg in ("NO ", "never", "NEVER", "not ", "Do NOT")), (term, rule[:80])
        slide_props = parsed["output_schema"]["properties"]["slides"]["items"]["properties"]
        assert not any(t in name for name in slide_props for t in ("overlay", "dim", "scrim", "tint", "darken"))
    fields = InstagramCarouselSlideCreative.model_fields
    assert not any(k for k in fields if any(t in k for t in ("overlay", "scrim", "dim", "tint", "darken", "readability")))
    pkg = _package(_slides_with({"composition": "typographic"}))
    assert all("overlay_mode" not in slide for slide in pkg.media_plan["slides"])


def test_legacy_overlay_mode_in_a_persisted_payload_is_ignored_at_the_schema_boundary() -> None:
    """B.4/B.4.3 drafts stored `overlay_mode`. The parse boundary
    (schemas/instagram_creative.py::InstagramCarouselSlideCreative._drop_removed_overlay_mode)
    discards it, so it can never reach the package or renderer. No DB migration."""
    legacy = {
        "role": "hook", "slide_copy": "Hook", "visual_direction": "v", "composition": "contained_media",
        "media_position": "top", "media_scale": 0.5, "overlay_mode": "editorial_scrim",
    }
    slide = InstagramCarouselSlideCreative.model_validate(legacy)
    assert "overlay_mode" not in slide.model_dump()
    carousel = InstagramCarouselCreative.model_validate({
        "objective": "saves", "slides": [legacy, {**legacy, "role": "takeaway", "slide_copy": "End", "overlay_mode": "gradient"}],
    })
    pkg = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )
    assert all("overlay_mode" not in s for s in pkg.media_plan["slides"])


def test_long_copy_adapts_the_composition_instead_of_clipping_and_is_recorded() -> None:
    long_copy = "Очень длинная, но законченная мысль, которая рассказывает о том, как именно новая функция меняет ежедневную работу команды и зачем это нужно"
    pkg = _package([
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook", visual_direction="v", composition="typographic"),
        InstagramCarouselSlideCreative(role="context", slide_copy=long_copy, visual_direction="v", composition="full_bleed_media"),
    ])
    results = render_instagram_carousel(pkg, slide_images={0: _image(), 1: _image()})
    notes = results[1].evidence.notes
    assert results[1].evidence.text_clipped is False
    assert notes["composition_adapted_for_text_fit"] is True
    assert notes["overlay_operations_executed"] == 0
    art = validate_instagram_art(pkg, results)
    assert not any("headline_text_overflow" in b for b in art.blocking_issues)


def test_asset_uniqueness_is_enforced_for_news_recap_only() -> None:
    """A trend/insight post may show derivative crops of ONE real asset on several slides even if a
    slide sets must_match_story - the cross-slide uniqueness rule is a NEWS_RECAP-only rule."""
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook", visual_direction="v", composition="typographic"),
        InstagramCarouselSlideCreative(role="beat", slide_copy="One", visual_direction="v", composition="contained_media", media_position="top", must_match_story=True),
        InstagramCarouselSlideCreative(role="beat", slide_copy="Two", visual_direction="v", composition="contained_media", media_position="left", must_match_story=True),
    ]
    for archetype, expect_block in (("trend_generative", False), ("news_recap", True)):
        pkg = _package(slides, archetype=archetype)
        results = render_instagram_carousel(pkg, slide_images={1: _image(), 2: _image()}, asset_identities={1: "same", 2: "same"})
        art = validate_instagram_art(pkg, results)
        assert any("news_recap_asset_reuse_violation" in b for b in art.blocking_issues) is expect_block, (archetype, art.blocking_issues)


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


def test_no_composition_field_uses_the_recorded_light_role_fallback() -> None:
    """A slide with NO structured fields records composition_requested=None and a role fallback -
    the fallback is light, media-in-its-own-region, never an overlay."""
    img = _image()
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Самая умная модель ≠ самая полезная", visual_direction="v"),
        InstagramCarouselSlideCreative(role="takeaway", slide_copy="Вывод", visual_direction="v"),
    ]
    pkg = _package(slides)
    results = render_instagram_carousel(pkg, slide_images={0: img, 1: img})
    assert results[0].evidence.notes["composition_requested"] is None
    assert results[0].evidence.notes["fallback_role_layout_used"] is True
    assert results[0].evidence.notes["layout_variant"] == "generic_contained_media_top"
    assert results[1].evidence.notes["layout_variant"].startswith("generic_typographic")


def test_fatigue_counts_posts_not_slides() -> None:
    from datetime import datetime, timezone
    from uuid import uuid4

    from services.instagram_creative_plan_service import RecentCarouselFingerprint, build_carousel_fatigue_note

    def post(*comps: str) -> RecentCarouselFingerprint:
        return RecentCarouselFingerprint(
            draft_id=uuid4(), generated_at=datetime.now(timezone.utc), content_archetype=None,
            compositions=tuple(sorted(set(comps))),
        )

    # two posts, each using typographic on three slides -> 2 posts, never "6x"
    assert build_carousel_fatigue_note([post("typographic", "typographic", "typographic")] * 2) == ""
    note = build_carousel_fatigue_note([post("typographic")] * 6)
    assert "6 of the last 14d posts" in note


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
