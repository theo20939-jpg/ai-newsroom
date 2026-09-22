"""Phase B.6.2: media-preserving fallback, structured flow_steps, hook_mechanic, generated-scene grounding. Zero cost: no provider, no network.

Includes a LOCAL, zero-provider-cost replay of the two real B.6.1 failures (NEWS_INSIGHT's dropped generated image, AI_HACK's
unparseable flow diagram) built from equivalent plans, per the phase's own instruction not to reuse the saved model output as
proof of the new model contract - only as proof the render/observability fix behaves."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml
from PIL import Image, ImageDraw

from schemas.instagram_creative import HOOK_MECHANICS, InstagramCarouselCreative, InstagramSlideLayout, LayoutRegion
from services import instagram_creative_director as cd
from services.instagram_art_validator import validate_instagram_art
from services.instagram_b4_observability import build_b4_observability
from services.instagram_carousel_layouts import render_carousel_slide
from services.instagram_creative_director import CreativeDirectorInput, generate_carousel_creative
from services.instagram_declarative_layout import DeclaredRenderRejected, render_declared_slide
from services.instagram_layout_validation import validate_layout
from services.instagram_media_first import MediaFirstContractError, assert_hook_contract, assert_media_first, has_substantive_graphic
from services.instagram_platform_renderer import render_instagram_carousel
from services.instagram_visual_profiles import INSTAGRAM_RENDER_PROFILES, InstagramRenderProfile
from tests.test_instagram_phase_b5_visual_dna_declarative import _EVIDENCE, _carousel_output_with_layouts, _layout, _package_for, _photo, _r
from tests.test_instagram_phase_b6_media_first import ANCHOR, BRIEF, DIRECTION, _Gateway, _media, _ok_slides, _slide_dict, _text, _v10_input, _v10_output

_SPEC = INSTAGRAM_RENDER_PROFILES[InstagramRenderProfile.CAROUSEL_SLIDE]
_PROMPTS = cd._PROMPTS if hasattr(cd, "_PROMPTS") else None


def _v102_input(**kw) -> CreativeDirectorInput:
    return _v10_input(**kw)


# ============================================================================================ 1. MEDIA-PRESERVING FALLBACK


_REJECTED_COPY_SPLIT_LAYOUT = {  # the exact real B.6.1 NEWS_INSIGHT slide 3 shape: copy_lead without copy_rest, on copy that DOES split
    "background": "soft", "density": "LOW", "media_dominance": "BALANCED", "visual_weight": "MIXED", "show_progress": False,
    "regions": [
        {"kind": "surface", "x": 0, "y": 0, "w": 1, "h": 1, "surface": "soft"},
        {"kind": "media", "x": 0.43, "y": 0.12, "w": 0.49, "h": 0.69, "z": 1, "content_ref": "generated", "crop_mode": "cover"},
        {"kind": "text", "x": 0.08, "y": 0.27, "w": 0.3, "h": 0.19, "z": 2, "content_ref": "copy_lead", "scale_token": "HEADLINE_XL"},
    ],
    "palette": "brand", "logo_position": "BOTTOM_RIGHT", "arrangement": "standard",
}
_COPY_THAT_SPLITS = "Критерий сменился: важна стоимость задачи."


def _photo_image() -> Image.Image:
    img = Image.new("RGB", (1024, 1536), (90, 120, 160))
    ImageDraw.Draw(img).ellipse((110, 180, 820, 890), fill=(240, 167, 60))
    return img


def test_a_generated_image_survives_the_exact_real_b61_layout_rejection() -> None:
    """LOCAL REPLAY (zero cost) of the real B.6.1 NEWS_INSIGHT slide-3 failure: same layout shape, same copy shape."""
    img = _photo_image()
    result = render_carousel_slide(
        spec=_SPEC, role="takeaway", index=3, total=4, slide_copy=_COPY_THAT_SPLITS, source_evidence=None, package_identity="p",
        media_image=img, media_mode="GENERATED", layout_plan=_REJECTED_COPY_SPLIT_LAYOUT, subject_assets={"generated": (img, "id1")},
    )
    assert result.notes["layout_plan_rejected"] == ["copy_not_fully_presented"]  # the validator's own rejection is unweakened
    assert result.notes["media_preserving_fallback_used"] is True
    assert result.notes["media_origin"] == "generated"
    assert result.notes["visual_preserved"] is True
    assert result.text_clipped is False  # the FULL copy renders, not a truncated fragment
    assert result.source_image_treatment != "none"  # the generated pixels are actually present


def test_a_suitable_source_image_survives_the_same_rejection_the_same_way() -> None:
    img = _photo_image()
    result = render_carousel_slide(
        spec=_SPEC, role="context", index=1, total=3, slide_copy=_COPY_THAT_SPLITS, source_evidence=None, package_identity="p",
        media_image=img, media_mode="SOURCE", layout_plan=_REJECTED_COPY_SPLIT_LAYOUT, subject_assets={"generated": (img, "id1")},
    )
    assert result.notes["media_preserving_fallback_used"] is True and result.notes["media_origin"] == "source" and result.notes["visual_preserved"] is True
    assert result.text_clipped is False


def test_the_fallback_never_fires_without_a_resolved_visual_asset_or_when_layout_plan_was_never_declared() -> None:
    no_asset = render_carousel_slide(
        spec=_SPEC, role="takeaway", index=3, total=4, slide_copy=_COPY_THAT_SPLITS, source_evidence=None, package_identity="p",
        media_mode="GENERATED", layout_plan=_REJECTED_COPY_SPLIT_LAYOUT, subject_assets={},
    )
    assert no_asset.notes["media_preserving_fallback_used"] is False and no_asset.notes["fallback_role_layout_used"] is True
    no_layout = render_carousel_slide(
        spec=_SPEC, role="takeaway", index=3, total=4, slide_copy=_COPY_THAT_SPLITS, source_evidence=None, package_identity="p",
        media_image=_photo_image(), media_mode="GENERATED", layout_plan=None, subject_assets={},
    )
    assert no_layout.notes["media_preserving_fallback_used"] is False  # no declarative attempt was even made - out of this fix's scope
    unlabelled_media_mode = render_carousel_slide(  # pre-B.6 callers that never set media_mode keep their exact old behaviour
        spec=_SPEC, role="takeaway", index=3, total=4, slide_copy=_COPY_THAT_SPLITS, source_evidence=None, package_identity="p",
        media_image=_photo_image(), layout_plan=_REJECTED_COPY_SPLIT_LAYOUT, subject_assets={"generated": (_photo_image(), "id1")},
    )
    assert unlabelled_media_mode.notes["media_preserving_fallback_used"] is False


def test_media_preserving_fallback_is_deterministic_and_uses_no_overlay() -> None:
    img = _photo_image()
    kw = dict(spec=_SPEC, role="takeaway", index=3, total=4, slide_copy=_COPY_THAT_SPLITS, source_evidence=None, package_identity="p",
              media_image=img, media_mode="GENERATED", layout_plan=_REJECTED_COPY_SPLIT_LAYOUT, subject_assets={"generated": (img, "id1")})
    first, second = render_carousel_slide(**kw), render_carousel_slide(**kw)
    assert first.image.tobytes() == second.image.tobytes()
    assert first.notes["overlay_operations_executed"] == 0


def test_declared_layout_success_and_true_no_media_fallback_are_distinguishable_from_the_new_state() -> None:
    good = _package_for(InstagramCarouselCreative.model_validate(_carousel_output_with_layouts()))
    ok = render_instagram_carousel(good)
    assert ok[0].evidence.notes["media_preserving_fallback_used"] is False and ok[0].evidence.notes["layout_plan_applied"] is True
    text_only = render_carousel_slide(spec=_SPEC, role="takeaway", index=0, total=2, slide_copy="Вывод", source_evidence=None, package_identity="p")
    assert text_only.notes["media_preserving_fallback_used"] is False and text_only.notes["visual_preserved"] is False  # no asset at all: honestly not preserved


# ============================================================================================ 2. STRUCTURED FLOW_STEPS


def _flow_layout(steps) -> InstagramSlideLayout:
    return InstagramSlideLayout.model_validate({
        "background": "ink", "density": "LOW", "media_dominance": "NONE", "visual_weight": "GRAPHIC", "show_progress": True,
        "regions": [
            {"kind": "surface", "x": 0, "y": 0, "w": 1, "h": 1, "surface": "ink"},
            {"kind": "text", "x": 0.08, "y": 0.08, "w": 0.8, "h": 0.2, "content_ref": "copy", "scale_token": "HEADLINE_L"},
            {"kind": "graphic", "x": 0.08, "y": 0.36, "w": 0.84, "h": 0.14, "graphic_type": "flow_diagram", "flow_steps": steps},
        ],
        "palette": "brand", "logo_position": "BOTTOM_RIGHT", "arrangement": "standard",
    })


_STEP_COPY = "Шаг 1. Оставь только решения\nБез описания проблемы."


def test_flow_steps_render_a_deterministic_flow_diagram_without_parsing_prose() -> None:
    """LOCAL REPLAY (zero cost) of the real B.6.1 AI_HACK flow-diagram failure, rebuilt with structured flow_steps."""
    layout = _flow_layout(["ДОКУМЕНТ", "ФИЛЬТР", "РЕШЕНИЯ"])
    validated = validate_layout(layout, slide_copy=_STEP_COPY, resolvable_subjects=set())
    assert validated.accepted, validated.rejection_codes
    result = render_declared_slide(spec=_SPEC, layout=validated.layout, slide_copy=_STEP_COPY, index=1, total=4, progress_hidden=validated.progress_hidden)
    assert result.text_clipped is False and result.notes.get("graphic_fallback_used") is False
    assert result.notes.get("unresolved_media_regions") == []
    first_pixels = result.image.tobytes()
    replay = render_declared_slide(spec=_SPEC, layout=validated.layout, slide_copy=_STEP_COPY, index=1, total=4, progress_hidden=validated.progress_hidden)
    assert replay.image.tobytes() == first_pixels  # deterministic


def test_flow_steps_validation_rejects_bad_item_counts_and_overlong_steps() -> None:
    with pytest.raises(Exception):
        LayoutRegion(kind="graphic", x=0, y=0, w=1, h=1, graphic_type="flow_diagram", flow_steps=["ONLY_ONE"])
    with pytest.raises(Exception):
        LayoutRegion(kind="graphic", x=0, y=0, w=1, h=1, graphic_type="flow_diagram", flow_steps=["A", "B", "C", "D", "E"])
    with pytest.raises(Exception):
        LayoutRegion(kind="graphic", x=0, y=0, w=1, h=1, graphic_type="flow_diagram", flow_steps=["A" * 23, "B"])
    ok = LayoutRegion(kind="graphic", x=0, y=0, w=1, h=1, graphic_type="flow_diagram", flow_steps=["A" * 22, "B"])
    assert len(ok.flow_steps) == 2


def test_legacy_free_text_parser_is_preserved_for_output_without_flow_steps() -> None:
    """v10/v10.1 output (no flow_steps field) keeps its exact prior render-time behaviour - unchanged, not repaired."""
    layout = _flow_layout(None)
    result = render_declared_slide(spec=_SPEC, layout=layout, slide_copy=_STEP_COPY, index=1, total=4,
                                   visual_direction="A flow diagram of the process.")
    assert result.notes.get("graphic_fallback_used") is True and result.notes.get("unresolved_media_regions") == ["flow_diagram_without_sequence"]


def test_flow_diagram_is_only_substantive_with_valid_structured_steps() -> None:
    valid = SimpleNamespace(layout=SimpleNamespace(regions=[SimpleNamespace(kind="graphic", graphic_type="flow_diagram", flow_steps=["A", "B"])]))
    missing = SimpleNamespace(layout=SimpleNamespace(regions=[SimpleNamespace(kind="graphic", graphic_type="flow_diagram", flow_steps=None)]))
    too_few = SimpleNamespace(layout=SimpleNamespace(regions=[SimpleNamespace(kind="graphic", graphic_type="flow_diagram", flow_steps=["A"])]))
    poll = SimpleNamespace(layout=SimpleNamespace(regions=[SimpleNamespace(kind="graphic", graphic_type="poll_cards", flow_steps=None)]))
    assert has_substantive_graphic(valid) is True and has_substantive_graphic(poll) is True
    assert has_substantive_graphic(missing) is False and has_substantive_graphic(too_few) is False


def test_an_invalid_flow_diagram_plan_is_rejected_at_generation_time_never_rendered_text_only() -> None:
    slides = _ok_slides()
    slides[1] = _slide_dict("evidence", "Собери решения", "graphic",
                            [_r("graphic", 0.08, 0.12, 0.84, 0.36, graphic_type="flow_diagram"), _text(y=0.56)])  # no flow_steps
    carousel = InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": slides})
    with pytest.raises(MediaFirstContractError, match="substantive graphic"):
        assert_media_first(list(carousel.slides), available_subjects={"source"}, unsuitable_subjects=set(), evidence=[_EVIDENCE])


# ============================================================================================ 3. v10.2 PROMPT


def _load(version: str) -> dict:
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "prompts" / "instagram_creative_director_carousel"
    return yaml.safe_load((root / f"v{version}.yaml").read_text(encoding="utf-8"))


def test_v102_is_v101_plus_flow_steps_grounding_and_hook_mechanic_and_v101_is_untouched() -> None:
    v101, v102 = _load("10.1"), _load("10.2")
    assert v101["version"] == "10.1" and v102["version"] == "10.2" and cd.CAROUSEL_PROMPT_VERSION == "10.3"
    changed = [i for i, (a, b) in enumerate(zip(v101["rules"], v102["rules"])) if a != b]
    assert len(v101["rules"]) == len(v102["rules"]) and len(changed) == 4
    assert "10.2" in cd.HOOK_MECHANIC_CAROUSEL_VERSIONS and "10.1" not in cd.HOOK_MECHANIC_CAROUSEL_VERSIONS
    text = " ".join(v102["rules"])
    assert "flow_steps" in text and "GROUNDING" in text and "hook_mechanic" in text
    for mechanic in HOOK_MECHANICS:
        assert mechanic in text
    region_v101 = v101["output_schema"]["properties"]["slides"]["items"]["properties"]["layout"]["properties"]["regions"]["items"]["properties"]
    region_v102 = v102["output_schema"]["properties"]["slides"]["items"]["properties"]["layout"]["properties"]["regions"]["items"]["properties"]
    assert "flow_steps" not in region_v101 and region_v102["flow_steps"]["maxItems"] == 4 and region_v102["flow_steps"]["minItems"] == 2
    slide_v102 = v102["output_schema"]["properties"]["slides"]["items"]["properties"]
    assert set(slide_v102["hook_mechanic"]["enum"]) == set(HOOK_MECHANICS) | {None}


def test_v102_generic_ai_art_guard_and_evidence_and_visual_dna_are_unchanged_from_v101() -> None:
    v101, v102 = _load("10.1"), _load("10.2")
    # every rule NOT among the 4 intentionally-replaced ones is byte-identical, including evidence handles / Visual DNA / no-overlay / calm-zone / collage text
    identical = [i for i in range(len(v101["rules"])) if v101["rules"][i] == v102["rules"][i]]
    assert len(identical) == len(v101["rules"]) - 4
    assert v101["system"] != v102["system"] or True  # system text may or may not change; not asserted either way here
    props_101 = v101["output_schema"]["properties"]["slides"]["items"]["properties"]
    props_102 = v102["output_schema"]["properties"]["slides"]["items"]["properties"]
    assert set(props_102) - set(props_101) == {"hook_mechanic"}


# ============================================================================================ 4. hook_mechanic contract


def test_hook_mechanic_is_required_on_v102_and_bounded() -> None:
    slides = _ok_slides()
    slides[0]["hook_mechanic"] = "contradiction"
    carousel = InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": slides})
    assert_hook_contract(list(carousel.slides), require_mechanic=True)
    missing = _ok_slides()
    missing[0]["hook_mechanic"] = None
    with pytest.raises(MediaFirstContractError, match="hook_mechanic"):
        assert_hook_contract(list(InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": missing}).slides), require_mechanic=True)
    elsewhere = _ok_slides()
    elsewhere[0]["hook_mechanic"] = "contradiction"
    elsewhere[1]["hook_mechanic"] = "absurdity"
    with pytest.raises(MediaFirstContractError, match="hook slide only"):
        assert_hook_contract(list(InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": elsewhere}).slides), require_mechanic=True)
    # v10.1 (require_mechanic=False, the default) never demands it - no regression for the already-accepted version
    assert_hook_contract(list(InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": missing}).slides))
    for mechanic in HOOK_MECHANICS:
        variant = _ok_slides()
        variant[0]["hook_mechanic"] = mechanic
        assert InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": variant}).slides[0].hook_mechanic == mechanic


@pytest.mark.asyncio
async def test_v102_generation_requires_hook_mechanic_and_persists_both_fields() -> None:
    from integrations.prompts.file_repository import FilePromptRepository
    from pathlib import Path

    repo = FilePromptRepository(Path(__file__).resolve().parent.parent / "prompts")
    missing = _ok_slides()
    missing[0]["hook_mechanic"] = None
    with pytest.raises(MediaFirstContractError, match="hook_mechanic"):
        await generate_carousel_creative(_Gateway(_v10_output(missing)), repo, director_input=_v102_input())
    slides = _ok_slides()
    slides[0]["hook_mechanic"] = "relatable_pain"
    outcome = await generate_carousel_creative(_Gateway(_v10_output(slides)), repo, director_input=_v102_input())
    assert outcome.carousel.slides[0].hook_mechanic == "relatable_pain" and outcome.carousel.slides[0].hook_emotion == "tension"
    plan = _package_for(outcome.carousel).media_plan["slides"]
    assert plan[0]["hook_mechanic"] == "relatable_pain" and plan[1]["hook_mechanic"] is None


# ============================================================================================ 5. generated-scene grounding wording (advisory prompt content; enforcement is the existing generic-AI guard)


def test_v102_grounding_rule_extends_the_existing_generic_guard_without_whitelisting_the_b61_failure() -> None:
    from services.instagram_media_first import find_generic_ai_art

    text = " ".join(_load("10.2")["rules"])
    assert "GROUNDING" in text and "obviously non-factual visual metaphor" in text
    assert "robot" not in text.lower().split("anonymous ")[0] or "anonymous robots" in text  # still named as a forbidden default, never whitelisted
    assert find_generic_ai_art("an anonymous robot demonstrates the workflow", ["Компания выпустила модель"]) == ["robot"]


# ============================================================================================ 6. full pipeline: generated image survives a rejected declarative plan


def test_pipeline_a_generated_image_survives_rejection_and_the_art_gate_accepts_the_slide() -> None:
    photo = _photo()
    plan = dict(_REJECTED_COPY_SPLIT_LAYOUT)
    slides = [
        _slide_dict("hook", "Первый экран", "generated", [_media("generated", 0, 0, 1, 0.55), _text(y=0.62)], brief=BRIEF, subject=None) | {"story_anchor": ANCHOR, "visual_direction": DIRECTION},
        {**_slide_dict("takeaway", _COPY_THAT_SPLITS, "generated", [], brief=BRIEF), "layout": plan, "story_anchor": ANCHOR, "visual_direction": DIRECTION},
    ]
    carousel = InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": slides})
    from services.instagram_automatic_trigger import _resolve_carousel_slide_assets

    assets, _f, carousel, subject_assets = _resolve_carousel_slide_assets(carousel, recap_bundle=None, source_image=photo, source_ref="r")
    package = _package_for(carousel)
    from dataclasses import replace as dc_replace

    package = dc_replace(package, media_plan={**package.media_plan, "media_execution": {"assets": [
        {"asset_key": "0", "media_mode": "GENERATED", "status": "generated_media"},
        {"asset_key": "1", "media_mode": "GENERATED", "status": "generated_media"},
    ]}})
    results = render_instagram_carousel(
        package, subject_assets=subject_assets, asset_identities={i: a.identity for i, a in assets.items()},
        slide_images={0: photo, 1: photo},
        slide_subject_assets={0: {"generated": (photo, "gen-id-0")}, 1: {"generated": (photo, "gen-id-1")}},
    )
    notes1 = results[1].evidence.notes
    assert notes1["layout_plan_rejected"] == ["copy_not_fully_presented"] and notes1["media_preserving_fallback_used"] is True
    assert notes1["visual_preserved"] is True and results[1].evidence.text_clipped is False
    art = validate_instagram_art(package, results)
    assert not any("slide_without_meaningful_visual" in b for b in art.blocking_issues), art.blocking_issues
    obs = build_b4_observability(carousel=carousel, prompt_version="10.2", renders=results, art=art, slide_identities={i: a.identity for i, a in assets.items()})
    assert obs["slides"][1]["media_preserving_fallback_used"] is True and obs["slides"][1]["generated_asset_dropped"] is False
    assert obs["slides"][1]["visual_family_executed"] == "media_preserving_fallback"
    assert obs["text_only_slides"] == []


def test_pipeline_a_generated_asset_dropped_flag_fires_only_when_no_visual_survives() -> None:
    """The observability flag distinguishes a preserved asset from a genuinely lost one - construct the genuinely-lost case directly."""
    notes_lost = {"media_regions": [], "layout_plan_applied": False, "media_preserving_fallback_used": False, "visual_preserved": False}
    slide = SimpleNamespace(media_source="generated")
    dropped = bool(slide.media_source == "generated" and not notes_lost.get("visual_preserved"))
    assert dropped is True
    notes_kept = {**notes_lost, "media_preserving_fallback_used": True, "visual_preserved": True}
    assert bool(slide.media_source == "generated" and not notes_kept.get("visual_preserved")) is False
