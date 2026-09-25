"""The three downstream blockers of the 2026-09-25 targeted canary, fixed at zero cost:
1. Phase A v2: a NEWS-origin decision for a planned TREND may carry a trend_rationale (v1 unchanged); a malformed Phase A output is a
   captured pipeline failure, never an uncaught ValidationError;
2. weekly recap evidence: the exact source text is the grounding string, the story is structural metadata (never a "[story_k] " label);
3. visual capability contract: with image generation off the Director is offered only what the renderer can draw into meaningful
   pixels - an empty ui_frame and a carousel carried by one generic primitive are rejected before render. No provider."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

import services.instagram_automatic_trigger as trigger
import services.instagram_creative_director as cd
from core.config import settings
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from schemas.instagram_creative import InstagramCarouselCreative, InstagramEditorialDecision
from services.instagram_creative_media import _evidence_for_slide
from services.instagram_feed_product import FeedFormat
from services.instagram_media_first import EXECUTABLE_VISUAL_PRIMITIVES, MediaFirstContractError, assert_media_first
from services.instagram_recap_bundle import InstagramRecapBundle, RecapStory
from tests.test_instagram_format_contract import _decision, _run, _user
from tests.test_instagram_phase_b5_visual_dna_declarative import _carousel_output_with_layouts, _r
from tests.test_instagram_phase_b6_media_first import _media, _slide_dict, _text

PROMPTS = FilePromptRepository(Path(__file__).resolve().parent.parent / "prompts")
REACTION = {**_decision(), "opportunity_type": "NEWS", "origin": "NEWS", "angle_intent": "REACTION",
            "trend_rationale": "Контраст громкого заголовка и реального результата делает историю поводом для реакции."}


# --- 1. Phase A v2 TREND schema ---------------------------------------------------------------------------------------------------

def test_a_news_origin_trend_decision_is_valid_on_the_planned_path_and_v1_is_unchanged():
    decision = InstagramEditorialDecision.model_validate(REACTION, context={"planned_format": "TREND"})
    assert decision.origin == "NEWS" and decision.trend_rationale
    with pytest.raises(ValidationError, match="trend_rationale is only valid"):
        InstagramEditorialDecision.model_validate(REACTION)  # v1 (no planned format): its rule still holds


class _PhaseAOnly:
    def __init__(self, output):
        self.output, self.requests = output, []

    async def generate(self, request):
        self.requests.append(request)
        return GenerateResponse(text=None, structured_output=self.output, finish_reason="stop", model_used="fake", usage=CapabilityUsage())


@pytest.mark.asyncio
async def test_a_malformed_phase_a_output_is_a_captured_contract_error_never_an_uncaught_validation_error():
    diagnostics = []
    cd.set_raw_output_sink(lambda event, payload: diagnostics.append(event))
    try:
        with pytest.raises(cd.EditorialDecisionContractError):
            await cd.generate_editorial_decision(_PhaseAOnly(REACTION), PROMPTS, decision_input=cd.InstagramEditorialDecisionInput(
                source_type="news", source_summary="s"))  # an unplanned (v1) call: this combination is invalid there
        decision, _ = await cd.generate_editorial_decision(_PhaseAOnly(REACTION), PROMPTS, decision_input=cd.InstagramEditorialDecisionInput(
            source_type="news", source_summary="s", planned_format="TREND"))
    finally:
        cd.set_raw_output_sink(None)
    assert decision.trend_rationale and "phase_a_raw_output" in diagnostics  # the raw output is kept for the artifacts


@pytest.mark.asyncio
async def test_the_saved_deepseek_shape_now_routes_to_the_director_as_a_trend(db_session, monkeypatch):
    outcome, gateway = await _run(db_session, monkeypatch, REACTION, feed_format=FeedFormat.MEME_TREND)
    assert outcome.reason.startswith("creative_director_failed"), outcome.reason  # it reached the Creative Director
    assert "CONTENT ARCHETYPE (derived, plan for it): trend_generative" in _user(gateway.director_request())


# --- 2. recap exact evidence -------------------------------------------------------------------------------------------------------

def _bundle() -> InstagramRecapBundle:
    return InstagramRecapBundle(stories=tuple(RecapStory(
        key=f"story_{i}", story_id=f"s{i}", event_id=f"e{i}", title=f"Story {i}", premise=f"Premise {i}", evidence_quality="SUFFICIENT",
        evidence=[f"Story {i} headline", f"Exact fact number {i} from the source."], evidence_sources=("event_title", f"https://src/{i}"))
        for i in range(1, 8)))


def test_recap_evidence_is_exact_text_with_the_story_attached_structurally():
    bundle = _bundle()
    assert bundle.evidence == [t for i in range(1, 8) for t in (f"Story {i} headline", f"Exact fact number {i} from the source.")]
    assert not any(t.startswith("[story_") for t in bundle.evidence)
    assert bundle.evidence_story_keys["Exact fact number 4 from the source."] == "story_4"
    item = next(i for i in bundle.evidence_items if i.exact_text == "Exact fact number 4 from the source.")
    assert (item.story_key, item.source) == ("story_4", "https://src/4")


@pytest.mark.asyncio
async def test_phase_a_sees_story_headers_and_its_exact_quotes_ground(db_session, monkeypatch):
    bundle = _bundle()
    quotes = ["Exact fact number 2 from the source.", "Story 7 headline"]
    plan = [{"story_key": f"story_{i}", "role": "STANDARD", "angle": "a"} for i in range(1, 8)]
    outcome, gateway = await _run(db_session, monkeypatch, _decision(coverage_plan=plan, evidence_used=quotes), recap_bundle=bundle)
    assert outcome.reason.startswith("creative_director_failed"), outcome.reason  # grounding passed: the Director was reached
    phase_a = _user(gateway.phase_a_request())
    assert "story_2:\n- Story 2 headline\n- Exact fact number 2 from the source." in phase_a  # the key is a header, not a label
    director = _user(gateway.director_request())
    assert "[story_2]: Exact fact number 2 from the source." in director and "RECAP COVERAGE PLAN" in director


def test_a_generated_recap_slide_still_gets_only_its_own_storys_evidence():
    bundle = _bundle()
    own = _evidence_for_slide(bundle.evidence, {"media_subject": "story_3"}, bundle.evidence_story_keys)
    assert own == ["Story 3 headline", "Exact fact number 3 from the source."]


# --- 3. the visual capability contract ---------------------------------------------------------------------------------------------

def test_with_generation_off_the_director_is_told_exactly_what_the_renderer_can_draw(monkeypatch):
    monkeypatch.setattr(settings, "instagram_image_generation_mode", "off")
    note = trigger._carousel_media_note(source_image=None, recap_bundle=None, media_first=True)
    assert all(primitive in note for primitive in EXECUTABLE_VISUAL_PRIMITIVES)
    assert "ui_frame alone is an empty placeholder" in note


def _carousel(slides):
    return list(InstagramCarouselCreative.model_validate({**_carousel_output_with_layouts(), "slides": slides}).slides)


def _flow(role, text, steps=("ШАГ", "ДЕЙСТВИЕ", "ИТОГ")):
    return _slide_dict(role, text, "graphic", [_r("graphic", 0.08, 0.12, 0.84, 0.36, graphic_type="flow_diagram", tone="accent", flow_steps=list(steps)),
                                               _text(y=0.56)])


def _poll(role, text):
    return _slide_dict(role, text, "graphic", [_r("graphic", 0.08, 0.12, 0.84, 0.36, graphic_type="poll_cards", tone="accent"), _text(y=0.56)])


def test_an_empty_ui_frame_is_rejected_before_render():
    slides = [_flow("hook", "Как подключить"), _slide_dict("step", "Шаг 2. Создай ключ", "graphic",
                                                          [_r("graphic", 0.08, 0.12, 0.84, 0.36, graphic_type="ui_frame", tone="accent"), _text(y=0.56)]),
              _poll("takeaway", "Готово: model | apiBase | apiKey")]
    with pytest.raises(MediaFirstContractError, match="empty window frame"):
        assert_media_first(_carousel(slides), available_subjects=set(), unsuitable_subjects=set(), generated_media_available=False)


def test_a_ui_frame_around_a_real_listed_ui_image_is_executable():
    slides = [_slide_dict("hook", "Вот настройки", "source", [_r("graphic", 0.05, 0.05, 0.9, 0.5, graphic_type="ui_frame", tone="accent"),
                                                                _media("source", 0.08, 0.1, 0.84, 0.42), _text(y=0.6)], subject="source"),
              _flow("step", "Шаг 1"), _poll("takeaway", "Готово: A | B")]
    assert_media_first(_carousel(slides), available_subjects={"source"}, unsuitable_subjects=set(), generated_media_available=False)


def test_one_mechanically_duplicated_composition_cannot_carry_the_carousel():
    # 2026-09-25: the 60% share is now a design diagnostic; the same layout + the same flow steps on 6 of 7 slides is still degenerate
    same = [_flow("hook", "Как это работает")] + [_flow("step", f"Шаг {i}") for i in range(1, 6)] + [_poll("takeaway", "Итог: A | B")]
    with pytest.raises(MediaFirstContractError, match="identical composition"):
        assert_media_first(_carousel(same), available_subjects=set(), unsuitable_subjects=set(), generated_media_available=False)
    varied = [_flow("hook", "Как это работает"), _flow("step", "Шаг 1"), _poll("step", "Шаг 2: A | B"), _flow("step", "Шаг 3"),
              _poll("step", "Шаг 4: A | B"), _flow("step", "Шаг 5"), _poll("takeaway", "Итог: A | B")]
    assert_media_first(_carousel(varied), available_subjects=set(), unsuitable_subjects=set(), generated_media_available=False)


def test_the_art_gate_is_untouched():
    from services import instagram_art_validator

    assert "slide_without_meaningful_visual" in Path(instagram_art_validator.__file__).read_text(encoding="utf-8")
