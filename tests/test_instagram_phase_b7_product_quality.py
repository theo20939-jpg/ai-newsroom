"""Product Quality Pass (Phase B.7): the two architecture fixes the founder's corrected plan required.

1. ONE canonical renderer-owned treatment vocabulary (services.instagram_editorial_layouts) - the art validator imports it,
   never hand-copies a second whitelist. A real hero_object_stage (object_contain) and a real cutout slide, rendered through
   the ACTUAL declarative renderer and validated through the ACTUAL art validator, must both pass.
2. `generated` slides are grounded through the EXISTING evidence-handle system (source_evidence + resolve_evidence_references),
   never a lexical/keyword heuristic. VAGUE_DIRECTION_PHRASES is gone with no replacement blacklist.

Zero cost: no provider, no network."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from integrations.prompts.file_repository import FilePromptRepository
from schemas.instagram_creative import InstagramCarouselCreative, InstagramSlideLayout
from services import instagram_creative_director as cd
from services.instagram_art_validator import validate_instagram_art
from services.instagram_creative_director import UngroundedEvidenceError, generate_carousel_creative
from services.instagram_creative_media import _evidence_for_slide
from services.instagram_declarative_layout import render_declared_slide
from services.instagram_editorial_layouts import CROP_MODE_TREATMENTS, SOURCE_IMAGE_TREATMENTS
from services.instagram_layout_validation import validate_layout
from services.instagram_media_first import MediaFirstContractError, find_generic_ai_art
from services.instagram_platform_renderer import render_instagram_carousel
from services.instagram_visual_profiles import INSTAGRAM_RENDER_PROFILES, InstagramRenderProfile
from tests.test_instagram_phase_b5_visual_dna_declarative import _EVIDENCE, _package_for
from tests.test_instagram_phase_b6_media_first import _Gateway, _ok_slides, _v10_output

_SPEC = INSTAGRAM_RENDER_PROFILES[InstagramRenderProfile.CAROUSEL_SLIDE]
_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_COPY = "Тестовая подпись слайда"


def _object_photo() -> Image.Image:
    img = Image.new("RGB", (900, 900), (40, 42, 48))
    ImageDraw.Draw(img).ellipse((150, 150, 750, 750), fill=(210, 180, 140))
    return img


def _alpha_cutout() -> Image.Image:
    img = Image.new("RGBA", (900, 900), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((150, 150, 750, 750), fill=(210, 180, 140, 255))
    return img


def _staged_layout(crop_mode: str) -> InstagramSlideLayout:
    return InstagramSlideLayout.model_validate({
        "background": "graphite", "density": "LOW", "media_dominance": "DOMINANT", "visual_weight": "MEDIA", "show_progress": True,
        "regions": [
            {"kind": "surface", "x": 0, "y": 0, "w": 1, "h": 1, "surface": "graphite"},
            {"kind": "media", "x": 0.1, "y": 0.1, "w": 0.8, "h": 0.55, "content_ref": "source", "crop_mode": crop_mode},
            {"kind": "text", "x": 0.08, "y": 0.7, "w": 0.8, "h": 0.2, "content_ref": "copy", "scale_token": "HEADLINE_M"},
        ],
        "palette": "brand", "logo_position": "BOTTOM_RIGHT", "arrangement": "stage",
    })


# ============================================================================================ 1. one canonical treatment vocabulary


def test_the_art_validator_imports_the_renderer_owned_vocabulary_not_a_hand_copied_list() -> None:
    import inspect

    import services.instagram_art_validator as av

    assert "SOURCE_IMAGE_TREATMENTS" in inspect.getsource(av)
    assert "not in (\"none\"" not in inspect.getsource(av)  # no independent hand-typed tuple left behind
    assert SOURCE_IMAGE_TREATMENTS == {
        "none", "cover_cropped", "contain_preserved", "object_contained", "object_cover_cropped", "cutout_contained", "cutout_cover",
    }


def test_the_declarative_renderer_derives_media_treatment_from_the_same_constant() -> None:
    import inspect

    source = inspect.getsource(__import__("services.instagram_declarative_layout", fromlist=["x"]))
    assert 'media_treatment = "object_contained"' not in source and 'media_treatment = "cutout_contained"' not in source
    assert "CROP_MODE_TREATMENTS.get(mode" in source


@pytest.mark.parametrize("crop_mode,expected_treatment,alpha", [
    ("object_contain", "object_contained", False), ("object_cover", "object_cover_cropped", False),
    ("cutout", "cutout_cover", True), ("cutout_contain", "cutout_contained", True), ("contain", "contain_preserved", False),
])
def test_every_renderer_treatment_is_accepted_by_the_real_art_validator(crop_mode, expected_treatment, alpha) -> None:
    """The exact real AI_HACK/B.6.2 failure: a hero_object_stage (object_contain) slide was rejected by a stale validator
    whitelist. Render through the REAL declarative renderer, validate through the REAL art validator, for every treatment
    the renderer can legitimately produce."""
    image = _alpha_cutout() if alpha else _object_photo()
    layout = _staged_layout(crop_mode)
    validated = validate_layout(layout, slide_copy=_COPY, resolvable_subjects={"source"})
    assert validated.accepted, validated.rejection_codes
    result = render_declared_slide(spec=_SPEC, layout=validated.layout, slide_copy=_COPY, index=0, total=1,
                                   subject_assets={"source": (image, "id1")}, progress_hidden=validated.progress_hidden)
    assert result.source_image_treatment == expected_treatment == CROP_MODE_TREATMENTS[crop_mode]
    assert result.source_image_treatment in SOURCE_IMAGE_TREATMENTS


def test_a_real_hero_object_stage_carousel_post_passes_the_art_gate() -> None:
    """End-to-end: the exact real B.6.2 AI_HACK failure mode (a real hero_object_stage slide) must clear the full pipeline."""
    from tests.test_instagram_phase_b5_visual_dna_declarative import _carousel_with, _layout, _r, _slide

    photo = _object_photo()
    hero_layout = _layout([
        _r("media", 0.1, 0.1, 0.8, 0.55, content_ref="source", crop_mode="object_contain"),
        _r("text", 0.08, 0.7, 0.8, 0.2, content_ref="copy", scale_token="HEADLINE_M"),
    ], background="graphite", density="LOW")
    hero_layout["arrangement"] = "stage"
    carousel = _carousel_with([
        _slide("hook", "Заголовок первого экрана", _layout([_r("text", 0.08, 0.2, 0.8, 0.3, content_ref="copy", scale_token="HEADLINE_L")])),
        _slide("takeaway", "Вывод про объект", hero_layout, media_subject="source"),
    ])
    from services.instagram_automatic_trigger import _resolve_carousel_slide_assets

    assets, _f, carousel, subject_assets = _resolve_carousel_slide_assets(carousel, recap_bundle=None, source_image=photo, source_ref="r")
    package = _package_for(carousel)
    results = render_instagram_carousel(package, subject_assets=subject_assets, asset_identities={i: a.identity for i, a in assets.items()})
    assert results[1].evidence.source_image_treatment == "object_contained"
    art = validate_instagram_art(package, results)
    assert not any("unknown_source_image_treatment" in b for b in art.blocking_issues), art.blocking_issues


# ============================================================================================ 2. evidence-handle grounding, not word matching


def _v103_input(**kw):
    from services.instagram_creative_director import CreativeDirectorInput
    from services.kage_voice import load_kage_voice

    base = dict(objective="saves", format="carousel", opportunity_summary="s", allowed_evidence=[_EVIDENCE], locale="ru", media_first=True,
                kage_voice_context=load_kage_voice().render_context(), available_media_subjects=("source",), unsuitable_media_subjects=())
    base.update(kw)
    return CreativeDirectorInput(**base)


def _out(slides: list[dict]) -> dict:
    out = _v10_output(slides)
    out["evidence_used"] = ["E1"]
    return out


def test_v103_generated_slide_requires_source_evidence() -> None:
    slides = _ok_slides()
    slides[0]["source_evidence"] = None
    with pytest.raises(MediaFirstContractError, match="source_evidence"):
        import asyncio

        asyncio.run(generate_carousel_creative(_Gateway(_out(slides)), FilePromptRepository(_PROMPTS), director_input=_v103_input()))


def test_v103_an_unresolvable_source_evidence_handle_raises_ungrounded() -> None:
    import asyncio

    slides = _ok_slides()
    slides[0]["source_evidence"] = "E99"
    with pytest.raises(UngroundedEvidenceError, match="E99"):
        asyncio.run(generate_carousel_creative(_Gateway(_out(slides)), FilePromptRepository(_PROMPTS), director_input=_v103_input()))


def test_v103_a_valid_handle_resolves_to_the_canonical_evidence_string() -> None:
    import asyncio

    slides = _ok_slides()
    slides[0]["source_evidence"] = "E1"
    outcome = asyncio.run(generate_carousel_creative(_Gateway(_out(slides)), FilePromptRepository(_PROMPTS), director_input=_v103_input()))
    assert outcome.carousel.slides[0].source_evidence == _EVIDENCE


def test_v103_the_real_b62_false_positive_now_passes() -> None:
    """The exact real NEWS_RECAP failure: a grounded plan rejected only because its prose contained 'abstract AI'."""
    import asyncio

    evidence = "[story_1] Xiaomi's MiMo-V2.6 series includes Pro and Flash and is released with open weights."
    slides = _ok_slides()
    slides[0]["source_evidence"] = "E1"
    slides[0]["story_anchor"] = "Xiaomi's MiMo-V2.6 series includes Pro and Flash and is released with open weights."
    slides[0]["generation_brief"] = ("Portrait editorial still life of two abstract AI model cores, one larger and one smaller, emerging from an "
                                     "opened archive of geometric data blocks. No text, logos or literal interface; dark, precise, technical mood.")
    slides[0]["visual_direction"] = ("Portrait editorial image of two distinct abstract model cores emerging from an opened technical archive, one "
                                     "larger and one smaller, on a quiet dark ground, visualizing the two-model MiMo-V2.6 release without labels.")
    outcome = asyncio.run(generate_carousel_creative(_Gateway(_out(slides)), FilePromptRepository(_PROMPTS), director_input=_v103_input(allowed_evidence=[evidence])))
    assert outcome.carousel.slides[0].story_anchor.startswith("Xiaomi's MiMo-V2.6")


def test_a_genuinely_unsupported_generic_motif_still_fails() -> None:
    import asyncio

    slides = _ok_slides()
    slides[0]["source_evidence"] = "E1"
    slides[0]["generation_brief"] = "Portrait editorial scene showing an anonymous glowing robot presenting the idea, dramatic lighting and depth."
    with pytest.raises(MediaFirstContractError, match="generic AI-art default"):
        asyncio.run(generate_carousel_creative(_Gateway(_out(slides)), FilePromptRepository(_PROMPTS), director_input=_v103_input()))


def test_the_generic_art_check_is_scoped_to_the_slides_own_evidence_not_the_whole_post() -> None:
    # "robot" is supported ONLY by a DIFFERENT slide's evidence (E2) - the hook's OWN evidence (E1) says nothing about it,
    # so citing E1 while depicting a robot must still fail: whole-post evidence must never excuse an ungrounded motif.
    evidence = ["[fact] Модель работает быстрее.", "[fact] Компания показала робота для дома."]
    slides = _ok_slides()
    slides[0]["source_evidence"] = "E1"
    slides[0]["generation_brief"] = "Portrait editorial scene with an anonymous robot presenting the result, dramatic lighting and material depth."
    with pytest.raises(MediaFirstContractError, match="generic AI-art default"):
        import asyncio

        asyncio.run(generate_carousel_creative(_Gateway(_out(slides)), FilePromptRepository(_PROMPTS), director_input=_v103_input(allowed_evidence=evidence)))


def test_find_generic_ai_art_has_no_unescaped_phrase_list_left() -> None:
    assert not hasattr(__import__("services.instagram_media_first", fromlist=["x"]), "VAGUE_DIRECTION_PHRASES")
    # a real, grounded sentence using ordinary prose words is never flagged merely for using them
    assert find_generic_ai_art("an abstract dynamic futuristic technology composition", ["дело в абстракции"]) == []


def test_evidence_for_slide_scopes_to_the_slides_own_source_evidence_when_no_recap_story_prefix() -> None:
    whole_post = ["[story_1] Первая история.", "[story_1] Ещё про первую.", "не относится к этому слайду"]
    slide = {"media_subject": None, "source_evidence": "Первая история."}
    assert _evidence_for_slide(whole_post, slide) == ["Первая история."]
    recap_slide = {"media_subject": "story_1", "source_evidence": None}
    assert _evidence_for_slide(whole_post, recap_slide) == ["[story_1] Первая история.", "[story_1] Ещё про первую."]  # unchanged recap behaviour
    empty_slide = {"media_subject": None, "source_evidence": None}
    assert _evidence_for_slide(whole_post, empty_slide) == whole_post  # defensive last resort only


# ============================================================================================ 3. real run #1 finding: hook teasing a story's OWN image is not asset reuse


def test_the_hook_reusing_its_leading_storys_own_image_is_not_a_reuse_violation() -> None:
    """The exact real Product Quality Pass finding: a NEWS_RECAP hook (media_subject=story_1) legitimately teases that story's
    own real photo, which ALSO appears on story_1's own dedicated `story` slide. Same subject, same real asset, deliberate -
    must not block. Two DIFFERENT story slides (or story vs closing) sharing one asset must still block (unchanged, tested
    elsewhere in test_instagram_phase_b4_content_archetypes.py)."""
    from schemas.instagram_creative import InstagramCarouselSlideCreative
    from tests.test_instagram_phase_b4_content_archetypes import _image, _package

    img = _image()
    slides = [
        InstagramCarouselSlideCreative(
            role="hook", slide_copy="Открываем неделю", visual_direction="v", composition="contained_media", media_position="top",
            media_subject="story_1", must_match_story=True,
        ),
        InstagramCarouselSlideCreative(
            role="story", slide_copy="Story about story_1", visual_direction="v", composition="contained_media", media_position="top",
            media_subject="story_1", must_match_story=True,
        ),
        InstagramCarouselSlideCreative(role="closing", slide_copy="Итог", visual_direction="v", composition="typographic"),
    ]
    pkg = _package(slides, archetype="news_recap")
    results = render_instagram_carousel(pkg, slide_images={0: img, 1: img}, asset_identities={0: "story1-photo", 1: "story1-photo"})
    art = validate_instagram_art(pkg, results)
    assert not any("news_recap_asset_reuse_violation" in b for b in art.blocking_issues), art.blocking_issues
