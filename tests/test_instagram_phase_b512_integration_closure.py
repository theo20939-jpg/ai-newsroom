"""Phase B.5.1.2: the three integration defects found by the first REAL Creative Director run - evidence references, art-gate diversity
blocking, and deterministic immersive calm-zone execution - plus raw-output observability. Zero cost: no provider, no network."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from PIL import Image, ImageDraw

from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from schemas.instagram_creative import InstagramSlideLayout
from services import instagram_creative_director as cd
from services.instagram_art_validator import validate_instagram_art
from services.instagram_creative_director import (
    CreativeDirectorInput,
    UngroundedEvidenceError,
    evidence_handle_map,
    generate_carousel_creative,
    resolve_evidence_references,
    set_raw_output_sink,
)
from services.instagram_declarative_layout import DeclaredRenderRejected, render_declared_slide
from services.instagram_layout_signature import infer_family
from services.instagram_layout_validation import validate_layout
from services.instagram_platform_renderer import render_instagram_carousel
from services.instagram_visual_profiles import INSTAGRAM_RENDER_PROFILES, InstagramRenderProfile
from tests.test_instagram_phase_b5_visual_dna_declarative import (
    _EVIDENCE,
    _carousel_output_with_layouts,
    _carousel_with,
    _layout,
    _package_for,
    _r,
    _slide,
)

_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_ALLOWED = [
    "Anthropic добавила поддержку AGENTS.md в Claude Code.",
    "Яндекс открыл веса модели AliceAI-Foundation-80B под лицензией Apache 2.0.",
    "Retroid представила консоль Duo Lite+.",
]
_NAME = "instagram_creative_director_carousel"


# ------------------------------------------------------------------------------------------ evidence references


def test_handles_map_deterministically_to_the_exact_canonical_evidence() -> None:
    handles = evidence_handle_map(_ALLOWED)
    assert list(handles) == ["E1", "E2", "E3"]
    assert handles["E1"] == _ALLOWED[0] and handles["E3"] == _ALLOWED[2]
    assert evidence_handle_map(_ALLOWED) == handles


def test_known_handles_resolve_to_canonical_text_and_recap_or_trend_can_cite_several() -> None:
    assert resolve_evidence_references(["E1", "E3"], _ALLOWED) == [_ALLOWED[0], _ALLOWED[2]]
    assert resolve_evidence_references(["E2"], _ALLOWED) == [_ALLOWED[1]]  # trend: a single handle
    assert resolve_evidence_references(["E1", "E2", "E3"], _ALLOWED) == _ALLOWED  # recap: many distinct handles


@pytest.mark.parametrize("bad", ["E4", "E0", "E99", "e1", "E01", "E1a", "handle:E1"])
def test_unknown_or_invented_handles_fail(bad: str) -> None:
    with pytest.raises(UngroundedEvidenceError):
        resolve_evidence_references([bad], _ALLOWED)


def test_free_form_paraphrase_and_story_labels_fail_and_there_is_no_fuzzy_matching() -> None:
    for claim in (
        "Новая языковая модель, обученная с нуля",                          # paraphrase
        "[story_1] " + _ALLOWED[0],                                          # label the model invented
        _ALLOWED[0].rstrip("."),                                             # one character off: still not canonical
        _ALLOWED[1].lower(),                                                 # same words, different case
    ):
        with pytest.raises(UngroundedEvidenceError):
            resolve_evidence_references([claim], _ALLOWED)


def test_legacy_exact_canonical_evidence_is_still_accepted() -> None:
    assert resolve_evidence_references([_ALLOWED[1]], _ALLOWED) == [_ALLOWED[1]]
    assert resolve_evidence_references(["- " + _ALLOWED[1]], _ALLOWED) == [_ALLOWED[1]]  # the presentation bullet we ourselves add


def test_v91_lists_handles_and_older_prompts_keep_bullets() -> None:
    director_input = CreativeDirectorInput(objective="saves", format="carousel", opportunity_summary="s", allowed_evidence=_ALLOWED, locale="ru")
    handled = cd._build_user_text(director_input, evidence_handles=True)
    legacy = cd._build_user_text(director_input)
    assert f"E1: {_ALLOWED[0]}" in handled and f"E3: {_ALLOWED[2]}" in handled and "EVIDENCE BULLETS" not in handled
    assert f"- {_ALLOWED[0]}" in legacy and "E1:" not in legacy
    assert cd._uses_evidence_handles(_NAME, "9.1") and not cd._uses_evidence_handles(_NAME, "9") and not cd._uses_evidence_handles("other", "9.1")


def test_v91_is_v9_except_for_the_evidence_contract_and_v9_is_untouched() -> None:
    v9 = yaml.safe_load((_PROMPTS / _NAME / "v9.yaml").read_text(encoding="utf-8"))
    v91 = yaml.safe_load((_PROMPTS / _NAME / "v9.1.yaml").read_text(encoding="utf-8"))
    assert v9["version"] == "9" and v91["version"] == "9.1"
    assert "Do not plan black or dark surfaces" not in " ".join(v91["rules"])  # still no stale v8 rule
    changed = [i for i, (a, b) in enumerate(zip(v9["rules"], v91["rules"])) if a != b]
    assert len(v9["rules"]) == len(v91["rules"]) and len(changed) == 2
    assert all("evidence" in v91["rules"][i] for i in changed)
    assert "[story_N]" in " ".join(v91["rules"]) and "HANDLE" in v91["system"]
    strip = lambda d: {k: v for k, v in d["output_schema"]["properties"].items() if k != "evidence_used"}  # noqa: E731
    assert strip(v9) == strip(v91)  # the whole visual/layout/family schema is unchanged
    assert v9["system"].replace("evidence", "") != "" and v9["output_schema"]["required"] == v91["output_schema"]["required"]
    assert cd.CAROUSEL_PROMPT_VERSION == "9.1" and cd._CREATIVE_DIRECTOR_MAX_TOKENS == 16_000


class _Gateway:
    def __init__(self, output: dict) -> None:
        self.output = output
        self.requests: list = []

    async def generate(self, request):
        self.requests.append(request)
        return GenerateResponse(text=None, structured_output=self.output, finish_reason="stop", model_used="fake", usage=CapabilityUsage())


def _director_input(evidence: list[str]) -> CreativeDirectorInput:
    return CreativeDirectorInput(objective="saves", format="carousel", opportunity_summary="s", allowed_evidence=evidence, locale="ru")


@pytest.mark.asyncio
async def test_handles_flow_end_to_end_and_persist_canonical_evidence() -> None:
    evidence = ["Автор описал переход на модели подешевле.", "Главным критерием стала стоимость выполненной задачи."]
    output = _carousel_output_with_layouts()
    output["evidence_used"] = ["E1", "E2"]
    output["slides"][1]["source_evidence"] = "E2"
    output["slides"][0]["source_evidence"] = None
    gateway = _Gateway(output)
    outcome = await generate_carousel_creative(gateway, FilePromptRepository(_PROMPTS), director_input=_director_input(evidence))
    request_text = gateway.requests[0].messages[1].content[0].text
    assert f"E1: {evidence[0]}" in request_text and f"E2: {evidence[1]}" in request_text
    assert outcome.carousel.evidence_used == evidence  # persisted business meaning == the canonical strings
    assert outcome.carousel.slides[1].source_evidence == evidence[1]
    assert outcome.carousel.slides[0].source_evidence is None


@pytest.mark.asyncio
async def test_an_invented_handle_or_paraphrase_still_fails_the_real_generation_path() -> None:
    evidence = ["Автор описал переход на модели подешевле."]
    for bad in (["E7"], ["Новая модель обучена с нуля"], ["[story_1] " + evidence[0]]):
        output = _carousel_output_with_layouts()
        output["evidence_used"] = bad
        with pytest.raises(UngroundedEvidenceError):
            await generate_carousel_creative(_Gateway(output), FilePromptRepository(_PROMPTS), director_input=_director_input(evidence))
    output = _carousel_output_with_layouts()
    output["evidence_used"] = ["E1"]
    output["slides"][1]["source_evidence"] = "E9"
    with pytest.raises(UngroundedEvidenceError):
        await generate_carousel_creative(_Gateway(output), FilePromptRepository(_PROMPTS), director_input=_director_input(evidence))


# ------------------------------------------------------------------------------------------ raw output before validation


@pytest.mark.asyncio
async def test_raw_structured_output_is_persisted_before_validation_and_survives_a_failure(tmp_path) -> None:
    events: list[tuple[str, dict]] = []

    def sink(event: str, payload: dict) -> None:
        events.append((event, payload))
        if event == "raw_output":
            (tmp_path / "raw_creative_director_output.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    output = _carousel_output_with_layouts()
    output["evidence_used"] = ["a paraphrase the model invented"]
    set_raw_output_sink(sink)
    try:
        with pytest.raises(UngroundedEvidenceError):
            await generate_carousel_creative(_Gateway(output), FilePromptRepository(_PROMPTS), director_input=_director_input(["real evidence"]))
    finally:
        set_raw_output_sink(None)
    assert [e for e, _ in events] == ["raw_output", "validation_error"]  # raw first, then the failure - in that order
    saved = json.loads((tmp_path / "raw_creative_director_output.json").read_text(encoding="utf-8"))
    assert saved["structured_output"]["evidence_used"] == ["a paraphrase the model invented"]
    assert saved["evidence_handles"] == {"E1": "real evidence"} and saved["prompt_version"] == "9.1"
    assert events[1][1]["error_type"] == "UngroundedEvidenceError"
    blob = json.dumps(saved).lower()
    assert not any(word in blob for word in ("api_key", "password", "secret", "token=", "bearer", "postgres://", "redis://"))
    assert set(saved) == {"prompt_name", "prompt_version", "model", "input_tokens", "output_tokens", "evidence_handles", "structured_output"}


@pytest.mark.asyncio
async def test_a_failing_diagnostic_sink_never_changes_the_generation_outcome() -> None:
    def broken(event: str, payload: dict) -> None:
        raise RuntimeError("disk full")

    output = _carousel_output_with_layouts()
    set_raw_output_sink(broken)
    try:
        outcome = await generate_carousel_creative(_Gateway(output), FilePromptRepository(_PROMPTS), director_input=_director_input([_EVIDENCE]))
    finally:
        set_raw_output_sink(None)
    assert outcome.carousel is not None


# ------------------------------------------------------------------------------------------ art gate


def _four_slide_uniform_package():
    same = _layout([_r("text", 0.10, 0.34, 0.80, 0.28, content_ref="copy", scale_token="HEADLINE_S", align="center", valign="middle", max_lines=5)], density="HIGH")
    slides = [_slide("hook", "Первый экран номер один", same, slide_purpose="hook"),
              _slide("context", "Второй экран про контекст", same, slide_purpose="context"),
              _slide("evidence", "Третий экран с фактом", same, slide_purpose="evidence"),
              _slide("takeaway", "Четвёртый экран с выводом", same, slide_purpose="takeaway")]
    return _package_for(_carousel_with(slides))


def test_layout_diversity_is_a_warning_and_no_longer_blocks() -> None:
    package = _four_slide_uniform_package()
    results = render_instagram_carousel(package)
    art = validate_instagram_art(package, results)
    assert any(w.startswith("carousel_layout_diversity_insufficient") for w in art.warnings)
    assert not any("layout_diversity" in b for b in art.blocking_issues)
    assert art.passed is True


def _planned(slides: list[dict]):
    from schemas.instagram_creative import InstagramCarouselCreative

    plan = _carousel_output_with_layouts()["creative_execution_plan"]
    return InstagramCarouselCreative.model_validate({"objective": "saves", "slides": slides, "creative_execution_plan": plan})


def test_real_safety_blockers_still_block() -> None:
    same = _layout([_r("text", 0.10, 0.34, 0.80, 0.28, content_ref="copy", scale_token="HEADLINE_S", align="center", valign="middle", max_lines=5)], density="HIGH")
    package = _package_for(_planned([
        _slide("hook", "Начало истории", same, slide_purpose="hook"), _slide("context", "Середина истории", same, slide_purpose="context"),
        _slide("takeaway", "Вывод истории", same, slide_purpose="takeaway")]))
    package.media_plan["slides"][1]["text"] = package.media_plan["slides"][0]["text"]  # the input schema forbids this, so tamper the persisted plan
    assert "carousel_duplicate_slide_copy" in validate_instagram_art(package, render_instagram_carousel(package)).blocking_issues
    tampered_role = _package_for(_planned([
        _slide("hook", "Начало истории", same, slide_purpose="hook"), _slide("context", "Середина истории", same, slide_purpose="context"),
        _slide("takeaway", "Вывод истории", same, slide_purpose="takeaway")]))
    tampered_role.media_plan["slides"][-1]["role"] = "evidence"
    assert "carousel_missing_closing_function" in validate_instagram_art(tampered_role, render_instagram_carousel(tampered_role)).blocking_issues
    with pytest.raises(Exception, match="conclusion role"):  # an invalid terminal role is rejected before any render
        _planned([_slide("hook", "Начало", same, slide_purpose="hook"), _slide("context", "Середина", same, slide_purpose="context"),
                  _slide("evidence", "Ещё факт", same, slide_purpose="evidence")])


# ------------------------------------------------------------------------------------------ immersive calm zone


_SPEC = INSTAGRAM_RENDER_PROFILES[InstagramRenderProfile.CAROUSEL_SLIDE]
_COPY = "Самая умная и дорогая модель — не для каждой задачи."


def _busy_left_calm_right_photo() -> Image.Image:
    """Left 34% is dense high-contrast clutter; the top of the right side is a calm even ground."""
    img = Image.new("RGB", (1080, 1350), (168, 152, 128))
    draw = ImageDraw.Draw(img)
    for i in range(0, 380, 9):
        draw.rectangle([i, 0, i + 4, 1350], fill=(20, 20, 24) if (i // 9) % 2 else (215, 215, 215))
    for j in range(0, 1350, 11):
        draw.line([0, j, 400, j + 5], fill=(240, 240, 240), width=2)
    return img


def _immersive_layout(x: float, y: float, w: float, h: float) -> InstagramSlideLayout:
    return InstagramSlideLayout.model_validate(_layout([
        _r("media", 0, 0, 1, 1, content_ref="source", crop_mode="cover", focus_x=0.5),
        _r("accent", x, y - 0.035, 0.08, 0.02, accent_type="rule_h", tone="accent", on_media=True),
        _r("text", x, y, w, h, content_ref="copy", scale_token="HEADLINE_XL", align="left", valign="top", max_lines=3, on_media=True),
    ], background="ink", density="LOW"))


def _render(layout: InstagramSlideLayout, photo: Image.Image, **kw):
    validated = validate_layout(layout, slide_copy=_COPY, resolvable_subjects={"source"})
    assert validated.accepted, validated.rejection_codes
    return render_declared_slide(spec=_SPEC, layout=validated.layout, slide_copy=_COPY, index=0, total=4,
                                 subject_assets={"source": (photo, "id-1")}, progress_hidden=validated.progress_hidden, **kw)


def test_bad_model_coordinates_are_relocated_into_a_measured_calm_zone_deterministically() -> None:
    photo = _busy_left_calm_right_photo()
    layout = _immersive_layout(0.05, 0.12, 0.6, 0.22)  # planned right on top of the clutter
    assert infer_family(layout.model_dump()) == "immersive_image_field"
    with pytest.raises(DeclaredRenderRejected) as info:
        _render(layout, photo)  # without the adapter the renderer fails closed, as before
    assert info.value.code == "text_on_media_unreadable"
    first = _render(layout, photo, adapt_calm_zone=True)
    second = _render(layout, photo, adapt_calm_zone=True)
    notes = first.notes
    assert notes["calm_zone_adapted"] is True and notes["composition_adapted_for_text_fit"] is True
    assert notes["calm_zone_requested"] == [0.05, 0.12, 0.6, 0.22] and notes["calm_zone_executed"] in {"top-right", "right-column", "bottom-right", "bottom-left"}
    assert first.text_clipped is False and notes["overlay_operations_executed"] if "overlay_operations_executed" in notes else True
    assert first.image.tobytes() == second.image.tobytes()  # same input, same pixels, same geometry: no randomness
    assert notes["calm_zone_executed_box"] == second.notes["calm_zone_executed_box"]
    assert infer_family(layout.model_dump()) == "immersive_image_field"  # the family the model chose is the family that was executed


def test_a_plan_already_in_a_calm_zone_is_not_adapted() -> None:
    photo = _busy_left_calm_right_photo()
    result = _render(_immersive_layout(0.45, 0.12, 0.45, 0.22), photo, adapt_calm_zone=True)
    assert result.notes.get("calm_zone_adapted") is None and not result.notes.get("composition_adapted_for_text_fit")


def test_no_calm_zone_anywhere_fails_closed_with_no_overlay() -> None:
    busy = Image.new("RGB", (1080, 1350), (128, 128, 128))
    draw = ImageDraw.Draw(busy)
    for i in range(0, 1080, 8):
        draw.rectangle([i, 0, i + 3, 1350], fill=(10, 10, 10) if (i // 8) % 2 else (245, 245, 245))
    for j in range(0, 1350, 9):
        draw.line([0, j, 1080, j], fill=(250, 250, 250) if (j // 9) % 2 else (5, 5, 5), width=2)
    with pytest.raises(DeclaredRenderRejected) as info:
        _render(_immersive_layout(0.1, 0.12, 0.6, 0.22), busy, adapt_calm_zone=True)
    assert info.value.code == "text_on_media_unreadable"


def test_non_immersive_layouts_are_never_adapted() -> None:
    photo = _busy_left_calm_right_photo()
    framed = InstagramSlideLayout.model_validate(_layout([
        _r("media", 0.05, 0.05, 0.6, 0.5, content_ref="source", crop_mode="cover", focus_x=0.5),
        _r("text", 0.08, 0.12, 0.5, 0.22, content_ref="copy", scale_token="HEADLINE_XL", align="left", valign="top", max_lines=3, on_media=True),
    ], background="ink", density="LOW"))
    assert infer_family(framed.model_dump()) != "immersive_image_field"
    with pytest.raises(DeclaredRenderRejected):
        _render(framed, photo, adapt_calm_zone=True)


def test_the_pipeline_records_the_adaptation_and_the_chosen_family_is_executed() -> None:
    from services.instagram_automatic_trigger import _resolve_carousel_slide_assets
    from tests.test_instagram_phase_b5_visual_dna_declarative import _photo  # noqa: F401  (kept for parity with the other pipeline tests)

    photo = _busy_left_calm_right_photo()
    immersive = _immersive_layout(0.05, 0.12, 0.6, 0.22).model_dump()
    carousel = _carousel_with([
        _slide("hook", "Самая умная и дорогая модель — не для каждой задачи.", immersive, media_subject="source", media_function="hero",
               visual_family="immersive_image_field", visual_family_reason="dark source image", slide_purpose="hook"),
        _slide("takeaway", "Вывод про стоимость задачи", _layout([_r("text", 0.1, 0.3, 0.8, 0.3, content_ref="copy", scale_token="HEADLINE_M")]),
               visual_family="light_utility_editorial", visual_family_reason="calm close", slide_purpose="takeaway"),
    ])
    assets, _f, carousel, subject_assets = _resolve_carousel_slide_assets(carousel, recap_bundle=None, source_image=photo, source_ref="r")
    package = _package_for(carousel)
    results = render_instagram_carousel(package, subject_assets=subject_assets, asset_identities={i: a.identity for i, a in assets.items()})
    notes = results[0].evidence.notes
    assert notes["layout_plan_applied"] is True and notes["fallback_role_layout_used"] is False
    assert notes["calm_zone_adapted"] is True and notes["composition_adapted_for_text_fit"] is True and notes["overlay_operations_executed"] == 0
    from services.instagram_b4_observability import build_b4_observability

    obs = build_b4_observability(carousel=carousel, prompt_version="9.1", renders=results, art=validate_instagram_art(package, results), slide_identities={},
                                 deliberate_fallback_subjects=[])
    first = obs["slides"][0]
    assert first["visual_family_chosen"] == first["visual_family_executed"] == "immersive_image_field" and first["visual_family_matches"] is True
    assert first["calm_zone_adapted"] is True and first["calm_zone_executed"] and first["calm_zone_requested"] == [0.05, 0.12, 0.6, 0.22]
