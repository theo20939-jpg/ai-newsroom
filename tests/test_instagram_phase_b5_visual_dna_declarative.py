"""Phase B.5: reference-driven Visual DNA + declarative composition system.

Zero provider calls: every LLM transport here is a local fake. The declarative fixtures are RENDERER
fixtures - they prove the safe renderer can express real asymmetry, not that a model plans well."""
from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
from pathlib import Path

import pytest
import yaml
from PIL import Image, ImageChops, ImageDraw

from integrations.llm_gateway.protocol import GenerateRequest, GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from schemas.instagram_creative import InstagramCarouselCreative, InstagramSlideLayout, LayoutRegion
from scripts._instagram_phase_b5_examples import EXAMPLES, _layout, _r
from services.instagram_art_validator import validate_instagram_art
from services.instagram_automatic_trigger import _resolve_carousel_slide_assets
from services.instagram_carousel_layouts import render_carousel_slide
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import (
    CAROUSEL_PROMPT_VERSION,
    CreativeDirectorInput,
    CreativeGenerationOutcome,
    _build_user_text,
    generate_carousel_creative,
)
from services.instagram_declarative_layout import SCALE_TOKENS, _fit_in_box, render_declared_slide
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_layout_signature import layout_characteristics, layout_signature
from services.instagram_layout_validation import validate_layout
from services.instagram_platform_renderer import derive_asset_identity, render_instagram_carousel
from services.instagram_recap_bundle import InstagramRecapBundle, RecapStory
from services.instagram_reference_analysis import (
    ReferenceImageRequired,
    analyze_reference_image,
    build_reference_image_request,
    prepare_reference_image,
)
from services.instagram_shadow_pipeline import ShadowPlanResult
from services.instagram_visual_dna import (
    REFERENCE_BOARD_PATH,
    InstagramVisualDNA,
    VisualDnaOriginalityError,
    assert_mechanics_only,
    dna_is_stale,
    load_visual_dna,
    render_visual_dna_context,
)
from services.instagram_visual_profiles import INSTAGRAM_RENDER_PROFILES, InstagramRenderProfile

_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_SPEC = INSTAGRAM_RENDER_PROFILES[InstagramRenderProfile.CAROUSEL_SLIDE]
_OPP = ContentOpportunity(id="opp-b5", source_type=OpportunitySourceType.NEWS, story_id="s-b5", product_mention_allowed=False)
_SP = ShadowPlanResult(
    campaign_name=None, campaign_phase=None, opportunity_description="b5", primary_objective="reach", audience_description="",
    recommended_format="carousel", hook_family=None, creative_concept_summary="c", alternative_format=None,
    alternative_objective=None, product_mention_allowed=False, evidence=[], confidence=0.5,
)


def _photo(size=(1200, 1500)) -> Image.Image:
    img = Image.new("RGB", size, (70, 100, 150))
    d = ImageDraw.Draw(img)
    d.rectangle([size[0] // 2, size[1] // 2, size[0], size[1]], fill=(220, 60, 40))
    d.ellipse([100, 100, 500, 500], fill=(240, 200, 60))
    return img


def _fixture_dna(tag: str = "A", **overrides) -> InstagramVisualDNA:
    base = dict(
        version="1", reference_path="docs/references/instagram/instagram_visual_reference_board_v1.png",
        reference_sha256="0" * 64, analysis_prompt_version="2",
        typography=[f"very large headline against small supporting text creates strong scale contrast ({tag})"],
        spatial_system=["intentional whitespace and asymmetric balance rather than centered symmetry"],
        image_behavior=["image is the subject on some slides and a small accent on others"],
        composition_rhythm=["adjacent slides alternate between dense and airy moments"],
        accent_system=["restrained red used for rules and numbers only"],
        brand_invariants=["logo placement discipline and type family stay constant"],
        non_invariants=["image position, split ratio and density vary with content"],
        must_not_copy=["the reference's exact wording", "its exact imagery", "its obsolete logo"],
        originality_constraints=["learn mechanics; never reproduce the source piece"],
    )
    base.update(overrides)
    return InstagramVisualDNA(**base)


class _CapturingGateway:
    def __init__(self, output: dict) -> None:
        self.output = output
        self.requests: list[GenerateRequest] = []

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.requests.append(request)
        return GenerateResponse(text=None, structured_output=self.output, finish_reason="stop", model_used="fake", usage=CapabilityUsage())


def _analysis_output() -> dict:
    return {
        "hook_mechanics": "scale contrast in the first frame", "pacing": "fast", "scene_structure": "board of directions",
        "narrative_progression": "n/a", "typography_behavior": "huge condensed headlines", "visual_rhythm": "alternating density",
        "editing_rhythm": "n/a", "cta_mechanics": "n/a", "interaction_pattern": "n/a",
        "what_appears_effective": ["hypothesis: large numerals anchor a list post"],
        "typography": ["very large headline against small supporting text"], "spatial_system": ["asymmetric balance with intentional empty space"],
        "image_behavior": ["image as subject or as small accent depending on the message"],
        "composition_rhythm": ["adjacent pieces alternate density and media dominance"], "accent_system": ["restrained accent used on rules and numerals"],
        "brand_invariants": ["logo discipline and type family constant"], "non_invariants": ["image position and split ratio vary"],
        "style_directions": [{"name": "editorial news", "mechanics": "media-led with a compact headline block"}],
        "must_not_copy": ["the board's exact copy", "its obsolete logo"], "originality_constraints": ["mechanics only, never the pieces"],
    }


# ----------------------------------------------------------------------------- reference analysis (A, B)


@pytest.mark.asyncio
async def test_A_the_real_reference_file_is_actually_consumed_as_image_bytes() -> None:
    assert REFERENCE_BOARD_PATH.is_file()
    jpeg, data_uri, digest = prepare_reference_image(REFERENCE_BOARD_PATH)
    assert digest == hashlib.sha256(REFERENCE_BOARD_PATH.read_bytes()).hexdigest()
    gateway = _CapturingGateway(_analysis_output())
    deconstruction, dna = await analyze_reference_image(
        gateway, FilePromptRepository(_PROMPTS), reference_path=REFERENCE_BOARD_PATH,  # type: ignore[arg-type]
        repo_relative_path="docs/references/instagram/instagram_visual_reference_board_v1.png",
    )
    request = gateway.requests[0]
    assert "image" in request.modalities
    image_parts = [p for m in request.messages for p in m.content if p.type == "artifact_ref"]
    assert len(image_parts) == 1 and image_parts[0].mime_type == "image/jpeg"
    payload = base64.b64decode(image_parts[0].artifact_ref.split(",", 1)[1])
    sent = Image.open(io.BytesIO(payload))
    original = Image.open(REFERENCE_BOARD_PATH)
    assert abs(sent.width / sent.height - original.width / original.height) < 0.01  # the real board's pixels
    assert dna.reference_sha256 == digest and deconstruction.must_not_copy
    text = " ".join(p.text or "" for m in request.messages for p in m.content if p.type == "text")
    assert "docs/references" not in text  # no path illusion in the request text


@pytest.mark.asyncio
async def test_B_a_path_string_alone_is_never_visual_evidence(tmp_path: Path) -> None:
    with pytest.raises(ReferenceImageRequired):
        prepare_reference_image("docs/references/instagram/does_not_exist.png")
    fake_png = tmp_path / "not_really.png"
    fake_png.write_text("this is just text", encoding="utf-8")
    with pytest.raises(ReferenceImageRequired):
        prepare_reference_image(fake_png)
    gateway = _CapturingGateway(_analysis_output())
    with pytest.raises(ReferenceImageRequired):
        await analyze_reference_image(gateway, FilePromptRepository(_PROMPTS), reference_path="docs/references/instagram/missing.png")  # type: ignore[arg-type]
    assert gateway.requests == []  # no call was spent without a real image


def test_reference_prompt_v2_requests_an_image_and_forbids_coordinates() -> None:
    prompt = FilePromptRepository(_PROMPTS).resolve("instagram_reference_analysis", "2")
    request = build_reference_image_request(prompt, data_uri="data:image/jpeg;base64,AAAA")
    assert request.modalities == ["text", "image"]
    props = prompt.output_schema["properties"]
    assert {"typography", "spatial_system", "image_behavior", "composition_rhythm", "accent_system", "brand_invariants", "non_invariants", "must_not_copy"} <= set(props)
    assert set(prompt.output_schema["required"]) == set(props)


# ----------------------------------------------------------------------------- Visual DNA (C, D, E, originality)


def test_C_visual_dna_reaches_creative_director_input(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import services.instagram_automatic_trigger as trigger
    import services.instagram_visual_dna as dna_module

    # Phase B.5.1: the ACTIVE Visual DNA is v2 (family library). The v1 loader must no longer be on the planning path.
    monkeypatch.setattr(dna_module, "load_visual_dna", lambda *a, **k: (_ for _ in ()).throw(AssertionError("v1 must not be loaded by the planner")))
    context = trigger._visual_dna_context()
    assert "VISUAL DNA v2" in context and "MUST NOT COPY" in context and "RENDERER CONSTRAINTS" in context
    assert "immersive_image_field" in context and "hero_object_stage" in context and "internet_culture_collage" in context
    assert trigger._visual_dna_version() == "2"
    director_input = CreativeDirectorInput(objective="saves", format="carousel", opportunity_summary="s", visual_dna_context=context, visual_dna_version="2")
    assert director_input.visual_dna_context == context


@pytest.mark.asyncio
async def test_D_visual_dna_reaches_the_actual_v8_prompt_request() -> None:
    dna = _fixture_dna("D")
    context = render_visual_dna_context(dna)
    gateway = _CapturingGateway(_carousel_output_with_layouts())
    outcome = await generate_carousel_creative(
        gateway, FilePromptRepository(_PROMPTS),  # type: ignore[arg-type]
        director_input=CreativeDirectorInput(
            objective="saves", format="carousel", opportunity_summary="s", allowed_evidence=[_EVIDENCE], locale="ru",
            visual_dna_context=context, visual_dna_version="1",
        ),
    )
    assert CAROUSEL_PROMPT_VERSION == "9" and outcome.carousel is not None
    request = gateway.requests[0]
    user_text = request.messages[1].content[0].text
    assert "VISUAL DNA v1" in user_text and "scale contrast" in user_text and "very large headline" in user_text
    system_text = request.messages[0].content[0].text
    assert "docs/references" not in system_text and "docs/references" not in user_text  # the model is never told to open a file
    assert "layout" in request.response_schema["properties"]["slides"]["items"]["properties"]
    assert "visual_rhythm" in request.response_schema["properties"]
    assert outcome.carousel.slides[1].layout is not None and outcome.carousel.visual_rhythm is not None


def test_E_must_not_copy_survives_and_is_mandatory() -> None:
    dna = _fixture_dna()
    assert "MUST NOT COPY" in render_visual_dna_context(dna) and "obsolete logo" in render_visual_dna_context(dna)
    with pytest.raises(ValueError):
        _fixture_dna(must_not_copy=[])


def test_originality_dna_describes_mechanics_never_coordinates_or_reference_copy() -> None:
    assert_mechanics_only(_fixture_dna())
    for bad in (
        "put the headline at x=145, y=300 because the reference did",
        "background colour #FF0000 behind the headline",
        "headline exactly 96 px tall",
        "use the phrase GPT-5 already here as the hook",
        "place the image at (145, 300)",
    ):
        with pytest.raises(VisualDnaOriginalityError):
            assert_mechanics_only(_fixture_dna(typography=[bad]))


def test_stored_visual_dna_if_present_is_valid_mechanics_only_and_not_stale() -> None:
    dna = load_visual_dna()
    if dna is None:
        pytest.skip("no stored Visual DNA yet")
    assert_mechanics_only(dna)
    assert not dna_is_stale(dna), "the reference board changed since this DNA was extracted - re-analyse"
    assert dna.must_not_copy and dna.originality_constraints


# ----------------------------------------------------------------------------- declarative layout (F-K, Q, R)


def _layout_of(name: str) -> InstagramSlideLayout:
    return InstagramSlideLayout.model_validate(EXAMPLES[name]["layout"])


def test_F_declarative_layout_validates_bounds() -> None:
    copy = "Проверка границ"
    zero = _layout([_r("text", 0.1, 0.1, 0.0, 0.2, content_ref="copy", scale_token="BODY")])
    assert "non_positive_size" in validate_layout(InstagramSlideLayout.model_validate(zero), slide_copy=copy, resolvable_subjects=set()).rejection_codes
    way_out = InstagramSlideLayout.model_validate(_layout([_r("text", 0.6, 0.1, 0.9, 0.3, content_ref="copy", scale_token="BODY")]))
    result = validate_layout(way_out, slide_copy=copy, resolvable_subjects=set())
    assert not result.accepted and "out_of_bounds" in result.rejection_codes
    negative = InstagramSlideLayout.model_validate(_layout([_r("text", 0.1, 0.1, -0.2, 0.3, content_ref="copy", scale_token="BODY")]))
    assert "non_positive_size" in validate_layout(negative, slide_copy=copy, resolvable_subjects=set()).rejection_codes


def test_G_unsafe_coordinates_reject_or_adapt_safely_and_the_slide_still_renders() -> None:
    copy = "Небольшой выход за край"
    slight = InstagramSlideLayout.model_validate(_layout([_r("text", 0.08, 0.2, 0.93, 0.3, content_ref="copy", scale_token="HEADLINE_M")]))
    result = validate_layout(slight, slide_copy=copy, resolvable_subjects=set())
    assert result.accepted and any(i.severity == "adapted" for i in result.issues)
    over_logo = InstagramSlideLayout.model_validate(_layout([_r("text", 0.30, 0.80, 0.62, 0.12, content_ref="copy", scale_token="BODY")]))
    trimmed = validate_layout(over_logo, slide_copy=copy, resolvable_subjects=set())
    assert trimmed.accepted and trimmed.layout.regions[0].x + trimmed.layout.regions[0].w < 0.83
    on_media = InstagramSlideLayout.model_validate(_layout([
        _r("media", 0.0, 0.0, 1.0, 0.7, content_ref="source", crop_mode="cover"),
        _r("text", 0.1, 0.2, 0.6, 0.2, content_ref="copy", scale_token="HEADLINE_M"),
    ]))
    rejected = validate_layout(on_media, slide_copy=copy, resolvable_subjects={"source"})
    assert not rejected.accepted and "text_over_media" in rejected.rejection_codes
    # a rejected plan never produces broken pixels: the deterministic fallback renders the slide
    unsafe = on_media.model_dump()
    fallback = render_carousel_slide(
        spec=_SPEC, role="context", index=1, total=3, slide_copy=copy, source_evidence=None, package_identity="p",
        layout_plan=unsafe, subject_assets={"source": (_photo(), "id")},
    )
    assert fallback.notes["layout_plan_rejected"] == ["text_over_media"] and fallback.notes["fallback_role_layout_used"] is True
    assert fallback.text_clipped is False and fallback.notes["overlay_operations_executed"] == 0


def test_H_same_plan_and_assets_are_deterministic() -> None:
    ex = EXAMPLES["D_two_unequal_media_regions"]
    layout = _layout_of("D_two_unequal_media_regions")
    a = render_declared_slide(spec=_SPEC, layout=layout, slide_copy=ex["copy"], index=0, total=4, subject_assets={"source": (_photo(), "id")})
    b = render_declared_slide(spec=_SPEC, layout=layout, slide_copy=ex["copy"], index=0, total=4, subject_assets={"source": (_photo(), "id")})
    assert ImageChops.difference(a.image, b.image).getbbox() is None


def _pixel_diff_fraction(a: Image.Image, b: Image.Image) -> float:
    diff = ImageChops.difference(a.convert("L"), b.convert("L")).point(lambda v: 255 if v > 24 else 0)
    return sum(1 for v in diff.getdata() if v) / (a.width * a.height)


def test_I_different_valid_plans_produce_materially_different_geometry_and_pixels() -> None:
    copy = "Одна и та же мысль в разной композиции"
    assets = {"source": (_photo(), "id")}
    plan_a = _layout([
        _r("media", 0.0, 0.0, 0.20, 1.0, content_ref="source", crop_mode="cover"),
        _r("text", 0.32, 0.14, 0.56, 0.34, content_ref="copy", scale_token="HEADLINE_M", max_lines=8),
    ], dominance="SUPPORTING", weight="MIXED")
    plan_b = _layout([
        _r("media", 0.0, 0.0, 1.0, 0.70, content_ref="source", crop_mode="cover"),
        _r("text", 0.08, 0.77, 0.74, 0.14, content_ref="copy", scale_token="HEADLINE_S", max_lines=3),
    ], dominance="DOMINANT", weight="MEDIA")
    ra = render_declared_slide(spec=_SPEC, layout=InstagramSlideLayout.model_validate(plan_a), slide_copy=copy, index=0, total=3, subject_assets=assets)
    rb = render_declared_slide(spec=_SPEC, layout=InstagramSlideLayout.model_validate(plan_b), slide_copy=copy, index=0, total=3, subject_assets=assets)
    assert layout_signature(plan_a) != layout_signature(plan_b)
    assert _pixel_diff_fraction(ra.image, rb.image) > 0.35  # not merely a different crop of the same card
    ca, cb = layout_characteristics(plan_a), layout_characteristics(plan_b)
    assert ca["media_zone"] != cb["media_zone"] and ca["media_dominance"] != cb["media_dominance"]


def test_all_eight_hand_authored_layouts_render_valid_distinct_and_overlay_free() -> None:
    images, signatures = [], set()
    for name, ex in EXAMPLES.items():
        layout = _layout_of(name)
        validated = validate_layout(layout, slide_copy=ex["copy"], resolvable_subjects={"source"})
        assert validated.accepted, (name, validated.issues)
        result = render_declared_slide(
            spec=_SPEC, layout=validated.layout, slide_copy=ex["copy"], index=0, total=5,
            subject_assets={"source": (_photo(), "id")}, progress_hidden=validated.progress_hidden,
        )
        assert result.text_clipped is False and result.visible_brand_mark_count == 1, name
        assert result.notes["source_media_pixels_unaltered"] in (True, None)
        images.append(result.image)
        signatures.add(layout_signature(layout.model_dump()))
    assert len(signatures) == len(EXAMPLES)  # eight materially different normalized geometries
    for i, a in enumerate(images):
        for b in images[i + 1:]:
            assert _pixel_diff_fraction(a, b) > 0.03


def test_J_legacy_b4_draft_with_composition_and_overlay_mode_still_renders() -> None:
    legacy = {
        "objective": "saves",
        "slides": [
            {"role": "hook", "slide_copy": "Старый черновик", "visual_direction": "v", "composition": "typographic", "overlay_mode": "gradient"},
            {"role": "context", "slide_copy": "Контекст со старой композицией", "visual_direction": "v", "composition": "contained_media",
             "media_position": "left", "media_scale": 0.45, "overlay_mode": "editorial_scrim"},
        ],
    }
    carousel = InstagramCarouselCreative.model_validate(legacy)
    package = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )
    results = render_instagram_carousel(package, slide_images={1: _photo()})
    assert all(r.evidence.notes["overlay_operations_executed"] == 0 for r in results)
    assert results[1].evidence.notes["layout_variant"] == "generic_contained_media_left"
    assert all(s["layout"] is None for s in package.media_plan["slides"])


def test_K_no_overlay_code_exists_in_the_declarative_path() -> None:
    forbidden = {"apply_bottom_readability_gradient", "apply_top_readability_gradient", "build_dimmed_source_field", "GaussianBlur", "ImageFilter"}
    for module in ("services/instagram_declarative_layout.py", "services/instagram_layout_validation.py", "services/instagram_carousel_layouts.py"):
        tree = ast.parse(Path(module).read_text(encoding="utf-8"))
        seen = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in forbidden:
                seen.add(node.id)
            if isinstance(node, ast.ImportFrom):
                seen |= {a.name for a in node.names if a.name in forbidden}
            if isinstance(node, ast.Attribute) and node.attr in ("alpha_composite", "filter"):
                seen.add(node.attr)
        assert not seen, (module, seen)


def test_Q_text_that_cannot_fit_never_produces_clipped_pixels() -> None:
    long_copy = "Очень длинная законченная мысль о том, как именно новая функция меняет ежедневную работу большой команды и зачем это нужно"
    tiny = _layout([_r("text", 0.08, 0.10, 0.30, 0.06, content_ref="copy", scale_token="DISPLAY", max_lines=2)])
    slide = render_carousel_slide(
        spec=_SPEC, role="context", index=1, total=3, slide_copy=long_copy, source_evidence=None, package_identity="p",
        layout_plan=tiny, subject_assets={},
    )
    assert slide.notes["layout_plan_rejected"] and slide.text_clipped is False
    from PIL import ImageFont  # noqa: F401

    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    _font, _lines, _h, clipped = _fit_in_box(draw, long_copy, box_w=120, box_h=40, token="DISPLAY", max_lines=2, spec=_SPEC)
    assert clipped is True  # the fitter itself reports the overflow instead of hiding it


def test_R_brand_tokens_are_renderer_owned_the_model_cannot_supply_them() -> None:
    fields = set(LayoutRegion.model_fields) | set(InstagramSlideLayout.model_fields)
    assert not any(t in f for f in fields for t in ("font", "color", "colour", "hex", "px", "size_px", "css", "svg", "code"))
    with pytest.raises(ValueError):
        LayoutRegion.model_validate({**_r("text", 0.1, 0.1, 0.5, 0.2, content_ref="copy", scale_token="BODY"), "font_family": "Comic Sans"})
    with pytest.raises(ValueError):
        LayoutRegion.model_validate({**_r("text", 0.1, 0.1, 0.5, 0.2, content_ref="copy", scale_token="BODY"), "color": "#123456"})
    assert set(SCALE_TOKENS) == {"MEGA", "NUMERAL", "DISPLAY", "HEADLINE_XL", "HEADLINE_L", "HEADLINE_M", "HEADLINE_S", "BODY", "CAPTION"}
    result = render_declared_slide(
        spec=_SPEC, layout=_layout_of("G_image_free_editorial_statement"), slide_copy=EXAMPLES["G_image_free_editorial_statement"]["copy"], index=0, total=3,
    )
    assert result.visible_brand_mark_count == 1


# ----------------------------------------------------------------------------- asset planning (L, M, N, O, P)


def _carousel_with(slides: list[dict], archetype: str | None = None) -> InstagramCarouselCreative:
    return InstagramCarouselCreative.model_validate({"objective": "saves", "slides": slides, "content_archetype": archetype})


def _slide(role: str, copy: str, layout: dict, **kw) -> dict:
    base = {"role": role, "slide_copy": copy, "visual_direction": "v", "layout": layout}
    base.update(kw)
    return base


def _package_for(carousel: InstagramCarouselCreative):
    return build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )


def test_L_a_different_subject_never_silently_consumes_the_unrelated_hero_image() -> None:
    media_slide = _layout([
        _r("media", 0.05, 0.08, 0.5, 0.4, content_ref="story_9", crop_mode="cover"),
        _r("text", 0.08, 0.58, 0.7, 0.2, content_ref="copy", scale_token="HEADLINE_S"),
    ])
    carousel = _carousel_with([
        _slide("hook", "Другой сюжет", _layout([_r("text", 0.08, 0.2, 0.8, 0.3, content_ref="copy", scale_token="HEADLINE_L")])),
        _slide("story", "Материал про совсем другое", media_slide, media_subject="story_9"),
    ])
    assets, _fallback, carousel, subject_assets = _resolve_carousel_slide_assets(carousel, recap_bundle=None, source_image=_photo(), source_ref="r")
    assert 1 not in assets and set(subject_assets) == {"source"}  # the hero is not attached to story_9
    package = _package_for(carousel)
    results = render_instagram_carousel(package, subject_assets=subject_assets)
    notes = results[1].evidence.notes
    assert notes["media_regions"] == [] and notes["unresolved_media_regions"] == ["story_9"] and notes["graphic_fallback_used"] is True


def test_M_the_same_subject_may_legitimately_reuse_one_image() -> None:
    two_uses = _layout([
        _r("media", 0.05, 0.08, 0.6, 0.4, content_ref="source", crop_mode="cover", focus_x=0.4),
        _r("media", 0.70, 0.20, 0.25, 0.28, content_ref="source", crop_mode="cover", focus_x=0.8, focus_y=0.8),
        _r("text", 0.08, 0.58, 0.7, 0.2, content_ref="copy", scale_token="HEADLINE_S"),
    ])
    carousel = _carousel_with([
        _slide("hook", "Общий план и деталь", two_uses, media_subject="source", media_function="hero"),
        _slide("detail", "Тот же предмет ещё раз", two_uses, media_subject="source", media_function="detail"),
    ])
    assets, _f, carousel, subject_assets = _resolve_carousel_slide_assets(carousel, recap_bundle=None, source_image=_photo(), source_ref="r")
    package = _package_for(carousel)
    results = render_instagram_carousel(package, subject_assets=subject_assets, asset_identities={i: a.identity for i, a in assets.items()})
    assert all(len(r.evidence.notes["media_regions"]) == 2 for r in results)
    assert not validate_instagram_art(package, results).blocking_issues


def test_N_news_recap_keeps_story_specific_asset_identity_with_declarative_layouts() -> None:
    def story_layout(key: str, x: float) -> dict:
        return _layout([
            _r("media", x, 0.08, 0.5, 0.42, content_ref=key, crop_mode="cover"),
            _r("text", 0.08, 0.60, 0.7, 0.22, content_ref="copy", scale_token="HEADLINE_S"),
        ])
    photos = {f"story_{i}": _photo((1200 + i * 10, 1500)) for i in (1, 2, 3)}
    for i, im in enumerate(photos.values()):
        ImageDraw.Draw(im).rectangle([i * 100, 0, i * 100 + 200, 300], fill=(10 + i * 60, 200, 90))

    def to_bytes(im: Image.Image) -> bytes:
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()

    stories = tuple(
        RecapStory(key=k, story_id=k, event_id=k, title=f"Сюжет {k}", evidence=[f"[{k}] t"], image_bytes=to_bytes(im), source_ref=k)
        for k, im in photos.items()
    ) + (RecapStory(key="story_4", story_id="s4", event_id="e4", title="Сюжет без картинки", evidence=["[story_4] t"]),)
    bundle = InstagramRecapBundle(stories=stories)
    slides = [_slide("hook", "Итоги", _layout([_r("text", 0.08, 0.2, 0.8, 0.3, content_ref="copy", scale_token="HEADLINE_L")]))]
    for i, key in enumerate(("story_1", "story_2", "story_3", "story_4")):
        slides.append(_slide("story", f"Новость номер {i + 1} о важном", story_layout(key, 0.05 + 0.1 * (i % 2)), media_subject=key, must_match_story=True))
    carousel = _carousel_with(slides, archetype="news_recap")
    assets, fallback, carousel, subject_assets = _resolve_carousel_slide_assets(carousel, recap_bundle=bundle, source_image=None, source_ref=None)
    identities = {i: a.identity for i, a in assets.items()}
    assert len(set(identities.values())) == 3 and fallback == ["story_4"]
    package = _package_for(carousel)
    results = render_instagram_carousel(package, subject_assets=subject_assets, asset_identities=identities)
    art = validate_instagram_art(package, results)
    assert not art.blocking_issues, art.blocking_issues
    assert results[4].evidence.notes["graphic_fallback_used"] is True  # story 4: its own graphic fallback


def test_O_ai_hack_uses_a_graphic_instructional_layout_instead_of_a_random_hero() -> None:
    step = _layout([
        _r("graphic", 0.30, 0.10, 0.62, 0.40, graphic_type="ui_frame"),
        _r("media", 0.34, 0.20, 0.54, 0.26, content_ref="source", crop_mode="cover"),  # a screenshot request, but only a photo exists
        _r("text", 0.08, 0.60, 0.6, 0.22, content_ref="copy_no_number", scale_token="HEADLINE_S"),
        _r("text", 0.08, 0.12, 0.2, 0.18, content_ref="number", scale_token="DISPLAY", max_lines=1),
    ], weight="GRAPHIC")
    carousel = _carousel_with([
        _slide("hook", "Шаг 2. Попросите модель сделать чек-лист", step, media_subject="source", media_function="ui_screenshot"),
        _slide("takeaway", "Проверьте на своём тексте", _layout([_r("text", 0.08, 0.3, 0.8, 0.3, content_ref="copy", scale_token="HEADLINE_L")])),
    ], archetype="ai_hack")
    assets, _f, carousel, subject_assets = _resolve_carousel_slide_assets(carousel, recap_bundle=None, source_image=_photo(), source_ref="r")
    assert 0 not in assets  # the story photo is not a screenshot: never attached to a ui_screenshot slide
    results = render_instagram_carousel(_package_for(carousel), subject_assets=subject_assets)
    assert results[0].evidence.notes["media_regions"] == [] and results[0].evidence.notes["layout_plan_applied"] is True


def test_P_trend_generative_can_use_a_media_free_graphic_slide() -> None:
    punchline = _layout([
        _r("surface", 0.0, 0.62, 1.0, 0.38, surface="red"),
        _r("text", 0.08, 0.14, 0.84, 0.36, content_ref="copy", scale_token="DISPLAY", valign="middle", max_lines=4),
    ], weight="GRAPHIC")
    result = render_declared_slide(spec=_SPEC, layout=InstagramSlideLayout.model_validate(punchline), slide_copy="Реальность: ещё один чат-бот", index=1, total=3)
    assert result.notes["media_regions"] == [] and result.source_image_treatment == "none" and result.text_clipped is False


# ----------------------------------------------------------------------------- carousel plan, prompt, fatigue, causal DNA


_EVIDENCE = "confirmed feature: NINJA drafts Instagram carousels on its own"


def _carousel_output_with_layouts(asymmetric: bool = True) -> dict:
    def slide(role: str, copy: str, layout: dict, **kw) -> dict:
        base = {"role": role, "slide_copy": copy, "visual_direction": "v", "source_evidence": None, "slide_purpose": role,
                "media_need": None, "media_subject": None, "media_function": None, "must_match_story": False, "layout": layout}
        base.update(kw)
        return base
    if asymmetric:
        first = _layout([_r("text", 0.08, 0.14, 0.62, 0.5, content_ref="copy", scale_token="DISPLAY", align="left", valign="top", max_lines=6)], density="LOW")
        second = _layout([_r("text", 0.40, 0.30, 0.50, 0.34, content_ref="copy", scale_token="HEADLINE_M", align="left", max_lines=6)], density="LOW")
        third = _layout([_r("text", 0.08, 0.60, 0.7, 0.2, content_ref="copy", scale_token="HEADLINE_S", align="left", max_lines=4)], density="LOW")
    else:
        first = _layout([_r("text", 0.10, 0.36, 0.80, 0.24, content_ref="copy", scale_token="HEADLINE_S", align="center", valign="middle", max_lines=5)], density="HIGH")
        second = _layout([_r("text", 0.10, 0.34, 0.80, 0.28, content_ref="copy", scale_token="HEADLINE_S", align="center", valign="middle", max_lines=5)], density="HIGH")
        third = _layout([_r("text", 0.10, 0.36, 0.80, 0.24, content_ref="copy", scale_token="HEADLINE_S", align="center", valign="middle", max_lines=5)], density="HIGH")
    return {
        "objective": "saves",
        "slides": [slide("hook", "Ты это видел?", first), slide("context", "Вот что теперь умеет NINJA", second, source_evidence=_EVIDENCE),
                   slide("takeaway", "Смотри сам в профиле", third)],
        "final_cta": "Смотри в профиле", "evidence_used": [_EVIDENCE], "final_caption": "NINJA собирает карусель для Instagram самостоятельно.",
        "content_archetype": "news_insight",
        "visual_rhythm": {"arc": "громкий вход, спокойное объяснение, тихий финал", "interruption_slides": [1], "repetition_note": None},
        "creative_execution_plan": {
            "main_idea": "idea", "focal_point": "the subject", "media_strategy": "typographic", "media_rationale": "r",
            "composition_direction": "vary", "branding_treatment": "logo", "visual_treatment": "light", "avoid_recent_treatment": None,
        },
    }


class _DnaSensitiveGateway:
    """Fake transport that plans differently depending on the Visual DNA it actually receives."""

    def __init__(self) -> None:
        self.requests: list[GenerateRequest] = []

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.requests.append(request)
        text = request.messages[1].content[0].text
        output = _carousel_output_with_layouts(asymmetric="asymmetric balance" in text)
        return GenerateResponse(text=None, structured_output=output, finish_reason="stop", model_used="fake", usage=CapabilityUsage())


@pytest.mark.asyncio
async def test_visual_dna_is_causal_not_metadata_two_dnas_yield_different_plans() -> None:
    sparse = _fixture_dna("sparse")  # mentions asymmetric balance + intentional whitespace
    dense = _fixture_dna(
        "dense", spatial_system=["dense centered blocks with minimal whitespace"],
        composition_rhythm=["uniform density across slides"],
    )
    plans = {}
    for label, dna in (("sparse", sparse), ("dense", dense)):
        outcome = await generate_carousel_creative(
            _DnaSensitiveGateway(), FilePromptRepository(_PROMPTS),  # type: ignore[arg-type]
            director_input=CreativeDirectorInput(
                objective="saves", format="carousel", opportunity_summary="s", allowed_evidence=[_EVIDENCE], locale="ru",
                visual_dna_context=render_visual_dna_context(dna), visual_dna_version="1",
            ),
        )
        plans[label] = [layout_characteristics(s.layout.model_dump()) for s in outcome.carousel.slides]
    assert plans["sparse"] != plans["dense"]
    assert {c["asymmetry"] for c in plans["sparse"]} == {"asymmetric"} and {c["asymmetry"] for c in plans["dense"]} == {"centered"}
    assert {c["density"] for c in plans["sparse"]} == {"LOW"} and {c["density"] for c in plans["dense"]} == {"HIGH"}


def test_prompt_v8_contract_is_declarative_strict_and_free_of_removed_concepts() -> None:
    text = (_PROMPTS / "instagram_creative_director_carousel" / "v8.yaml").read_text(encoding="utf-8").lower()
    for term in ("overlay", "scrim", "darken", "dimm", "gradient", "docs/references", ".png"):
        assert term not in text, term
    prompt = FilePromptRepository(_PROMPTS).resolve("instagram_creative_director_carousel", "8")
    slide = prompt.output_schema["properties"]["slides"]["items"]
    assert set(slide["required"]) == set(slide["properties"]) and slide["additionalProperties"] is False
    assert "layout" in slide["properties"] and not {"composition", "media_position", "media_scale"} & set(slide["properties"])
    region = slide["properties"]["layout"]["properties"]["regions"]["items"]
    assert set(region["required"]) == set(region["properties"]) and region["additionalProperties"] is False
    assert not any(t in f for f in region["properties"] for t in ("font", "color", "hex", "px"))
    assert "visual_rhythm" in prompt.output_schema["properties"]
    assert "VISUAL DNA" in " ".join(prompt.rules)
    parsed = yaml.safe_load(text)
    assert parsed["version"] == "8"


def test_fatigue_fingerprint_uses_normalized_layout_traits_never_coordinates() -> None:
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from uuid import uuid4

    from services.instagram_creative_plan_service import _fingerprint_from_draft, build_carousel_fatigue_note

    layout = _layout_of("A_large_left_headline_small_right_media").model_dump()
    draft = SimpleNamespace(id=uuid4(), generated_at=datetime.now(timezone.utc), payload={"slides": [{"layout": layout, "role": "hook"}], "content_archetype": "news_insight"})
    fp = _fingerprint_from_draft(draft)  # type: ignore[arg-type]
    assert fp is not None and fp.layout_traits
    assert all(":" in t and not any(ch.isdigit() and "." in t for ch in t) for t in fp.layout_traits)  # no floats
    note = build_carousel_fatigue_note([fp] * 6)
    assert "layout trait" in note and "6 of the last 14d posts" in note
    legacy = SimpleNamespace(id=uuid4(), generated_at=datetime.now(timezone.utc), payload={"slides": [{"role": "hook", "slide_copy": "x"}]})
    assert _fingerprint_from_draft(legacy) is None  # legacy payload with no structured fields is never fabricated


def test_declared_layout_evidence_and_observability_are_recorded() -> None:
    carousel = _carousel_with([
        _slide("hook", "Самая умная модель — не самая полезная", _layout_of("A_large_left_headline_small_right_media").model_dump(), media_subject="source", media_function="hero"),
        _slide("takeaway", "Смотрите сами", _layout_of("G_image_free_editorial_statement").model_dump()),
    ])
    assets, _f, carousel, subject_assets = _resolve_carousel_slide_assets(carousel, recap_bundle=None, source_image=_photo(), source_ref="r")
    package = _package_for(carousel)
    results = render_instagram_carousel(package, subject_assets=subject_assets, asset_identities={i: a.identity for i, a in assets.items()})
    notes = results[0].evidence.notes
    assert notes["layout_plan_applied"] is True and notes["structured_composition_executed"] is True
    assert notes["fallback_role_layout_used"] is False and notes["overlay_operations_executed"] == 0
    assert notes["media_asset_identity"] == derive_asset_identity_like(subject_assets["source"][1])
    assert not validate_instagram_art(package, results).blocking_issues


def derive_asset_identity_like(identity: str) -> str:
    return identity


def test_step_labels_never_leave_a_dangling_word_when_the_numeral_is_shown_separately() -> None:
    from services.instagram_layout_validation import copy_parts

    parts = copy_parts("Шаг 2. Попросите модель переформулировать вывод в чек-лист")
    assert parts["number"] == "2" and parts["copy_no_number"].startswith("Попросите") and "Шаг" not in parts["copy_no_number"]
    assert copy_parts("Вместо 20 минут — 30 секунд")["number"] == "20"


def test_brand_mark_uses_the_light_approved_variant_on_a_red_panel_and_the_red_one_on_paper() -> None:
    red_panel = InstagramSlideLayout.model_validate(_layout([
        _r("surface", 0.0, 0.70, 1.0, 0.30, surface="red"),
        _r("text", 0.08, 0.16, 0.84, 0.44, content_ref="copy", scale_token="DISPLAY", max_lines=4),
    ]))
    paper = InstagramSlideLayout.model_validate(_layout([_r("text", 0.08, 0.16, 0.84, 0.44, content_ref="copy", scale_token="DISPLAY", max_lines=4)]))
    on_red = render_declared_slide(spec=_SPEC, layout=red_panel, slide_copy="Проверка знака", index=0, total=2)
    on_paper = render_declared_slide(spec=_SPEC, layout=paper, slide_copy="Проверка знака", index=0, total=2)
    box = (860, 1180, 1000, 1290)
    def brightest(im: Image.Image) -> int:
        return max(sum(p) // 3 for p in im.convert("RGB").crop(box).getdata())
    assert on_red.visible_brand_mark_count == 1 and on_paper.visible_brand_mark_count == 1
    assert brightest(on_red.image) > 200  # a light mark is visible against the red panel
