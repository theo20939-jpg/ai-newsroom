"""KAGE downstream format contract: the frozen feed planner's PLANNED_FORMAT (AI_HACK / TREND / WEEKLY_RECAP) is authoritative
downstream. Phase A chooses the angle INSIDE the product; its source taxonomy never re-decides or drops the post; a weekly recap keeps
every selected story (coverage plan + Creative Director coverage); Russian prose may carry source-faithful English UI / code
literals; evidence is quoted exactly (a display preview may be shortened, the grounding string never is). No provider."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import services.instagram_automatic_trigger as trigger
import services.instagram_creative_director as cd
import services.instagram_evidence_package as ep
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from services.instagram_feed_product import FeedFormat
from services.instagram_recap_bundle import InstagramRecapBundle, RecapStory
from tests.test_instagram_phase_b42_orchestration import _DECISION, _news_opportunity, _patch_delivery

PROMPTS = FilePromptRepository(Path(__file__).resolve().parent.parent / "prompts")


class _Gateway:
    """Answers Phase A with the given decision; the Creative Director call answers with an invalid payload, so reaching it (a
    `creative_director_failed:*` outcome) proves the post survived the format contract."""

    def __init__(self, decision: dict) -> None:
        self.decision, self.requests = decision, []

    async def generate(self, request):
        self.requests.append(request)
        props = (request.response_schema or {}).get("properties", {})
        out = self.decision if "opportunity_type" in props else {"not": "a carousel"}
        return GenerateResponse(text=None, structured_output=out, finish_reason="stop", model_used="fake", usage=CapabilityUsage())

    def phase_a_request(self):
        return next(r for r in self.requests if "opportunity_type" in (r.response_schema or {}).get("properties", {}))

    def director_request(self):
        return next((r for r in self.requests if "opportunity_type" not in (r.response_schema or {}).get("properties", {})), None)


def _decision(**kw) -> dict:
    return {**_DECISION, "coverage_plan": None, **kw}


async def _run(db_session, monkeypatch, decision, *, feed_format=None, recap_bundle=None):
    _patch_delivery(monkeypatch)
    monkeypatch.setattr(trigger, "_resolve_single_source_image", AsyncMock(return_value=(None, None, 0, 0)))
    gateway = _Gateway(decision)
    outcome = await trigger.evaluate_and_submit_instagram_opportunity(
        db_session, AsyncMock(), opportunity=_news_opportunity(), opportunity_summary="s", gateway=gateway, prompt_repository=PROMPTS,
        phase_a_enabled=True, required_feed_format=feed_format, recap_bundle=recap_bundle)
    return outcome, gateway


def _user(request) -> str:
    return request.messages[1].content[0].text


# --- the planned format is authoritative ------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ai_hack_with_an_explainer_angle_stays_an_ai_hack(db_session, monkeypatch):
    outcome, gateway = await _run(db_session, monkeypatch, _decision(angle_intent="EXPLAINER"), feed_format=FeedFormat.AI_HACK)
    assert not outcome.reason.startswith("feed_format_mismatch"), outcome.reason
    assert outcome.reason.startswith("creative_director_failed")  # it reached the Creative Director
    assert "PLANNED PRODUCT FORMAT (fixed by the feed planner" in _user(gateway.phase_a_request()) and "AI_HACK" in _user(gateway.phase_a_request())
    director = _user(gateway.director_request())
    assert "PLANNED PRODUCT FORMAT (fixed by the feed planner; the carousel delivers THIS product): AI_HACK" in director
    assert "CONTENT ARCHETYPE (derived, plan for it): ai_hack" in director


@pytest.mark.asyncio
async def test_a_news_origin_reaction_planned_as_trend_stays_a_trend(db_session, monkeypatch):
    outcome, gateway = await _run(db_session, monkeypatch, _decision(origin="NEWS", angle_intent="REACTION"), feed_format=FeedFormat.MEME_TREND)
    assert outcome.reason.startswith("creative_director_failed"), outcome.reason
    assert "CONTENT ARCHETYPE (derived, plan for it): trend_generative" in _user(gateway.director_request())


@pytest.mark.asyncio
async def test_a_weekly_news_reading_never_reclassifies_a_planned_trend(db_session, monkeypatch, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger=trigger.__name__):
        outcome, gateway = await _run(db_session, monkeypatch, _decision(angle_intent="IMPACT"), feed_format=FeedFormat.MEME_TREND)
    assert outcome.reason.startswith("creative_director_failed"), outcome.reason  # not dropped as feed_format_mismatch:weekly_news
    assert any(r.getMessage() == "instagram_phase_a_taxonomy_ignored" for r in caplog.records)  # recorded as a diagnostic only
    decision = json.loads(_user(gateway.director_request()).split("APPROVED EDITORIAL DECISION:\n", 1)[1].split("\n", 1)[0])
    assert decision["planned_format"] == "TREND" and decision["phase_a_source_taxonomy_format"] == "weekly_news"


@pytest.mark.asyncio
async def test_an_unplanned_legacy_call_still_uses_phase_a_v1_unchanged(db_session, monkeypatch):
    _outcome, gateway = await _run(db_session, monkeypatch, _decision())
    request = gateway.phase_a_request()
    assert "coverage_plan" not in request.response_schema["properties"] and "PLANNED PRODUCT FORMAT" not in _user(request)


@pytest.mark.asyncio
async def test_a_planned_post_is_never_offered_an_unexecutable_reel(db_session, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "instagram_reel_execution_enabled", False)
    _outcome, gateway = await _run(db_session, monkeypatch, _decision(), feed_format=FeedFormat.MEME_TREND)
    assert "EXECUTABLE FORMATS: ['single', 'carousel']" in _user(gateway.phase_a_request())


# --- weekly recap: every selected story survives ----------------------------------------------------------------------------------

def _bundle(n=7) -> InstagramRecapBundle:
    return InstagramRecapBundle(stories=tuple(RecapStory(
        key=f"story_{i}", story_id=f"s{i}", event_id=f"e{i}", title=f"Story {i}", evidence=[f"[story_{i}] Story {i}"],
        premise=f"Premise {i}", category="AI", evidence_quality="SUFFICIENT") for i in range(1, n + 1)))


def _plan(keys) -> list[dict]:
    return [{"story_key": k, "role": "LEAD" if i == 0 else "STANDARD", "angle": f"angle {k}"} for i, k in enumerate(keys)]


@pytest.mark.asyncio
async def test_a_seven_story_recap_carries_all_seven_into_phase_a_and_the_director(db_session, monkeypatch):
    keys = [f"story_{i}" for i in range(1, 8)]
    outcome, gateway = await _run(db_session, monkeypatch, _decision(coverage_plan=_plan(keys)), recap_bundle=_bundle())
    assert outcome.reason.startswith("creative_director_failed"), outcome.reason
    phase_a = _user(gateway.phase_a_request())
    assert all(f"{k} | category AI | evidence SUFFICIENT" in phase_a for k in keys) and "WEEKLY_RECAP" in phase_a
    director = _user(gateway.director_request())
    assert "RECAP COVERAGE PLAN" in director and all(f"{k} (" in director for k in keys)
    assert "CONTENT ARCHETYPE (derived, plan for it): news_recap" in director


@pytest.mark.asyncio
@pytest.mark.parametrize("plan", [
    _plan(["story_4"]),  # collapse to one story
    _plan([f"story_{i}" for i in range(1, 7)]),  # one dropped
    _plan([f"story_{i}" for i in range(1, 8)] + ["story_4"]),  # duplicated
    _plan([f"story_{i}" for i in range(1, 7)] + ["story_99"]),  # a story swapped for an invented one
    None,  # no plan at all
])
async def test_phase_a_cannot_collapse_drop_duplicate_or_inject_a_recap_story(db_session, monkeypatch, plan):
    outcome, gateway = await _run(db_session, monkeypatch, _decision(coverage_plan=plan), recap_bundle=_bundle())
    assert outcome.reason == "editorial_decision_failed:RecapCoverageContractError"
    assert gateway.director_request() is None  # rejected before the Creative Director


@pytest.mark.asyncio
async def test_the_director_cannot_collapse_a_recap_either(monkeypatch):
    carousel = SimpleNamespace(slides=[SimpleNamespace(media_subject="story_4"), SimpleNamespace(media_subject=None)])
    monkeypatch.setattr(cd, "_call_creative_director", AsyncMock(return_value=({}, None)))
    monkeypatch.setattr(cd, "_validate_carousel_output", lambda *a, **kw: SimpleNamespace(carousel=carousel))
    director_input = cd.CreativeDirectorInput(objective="o", format="carousel", opportunity_summary="s", is_recap_bundle=True,
                                              planned_format="WEEKLY_RECAP", planned_archetype="news_recap",
                                              recap_required_subjects=[f"story_{i}" for i in range(1, 8)])
    with pytest.raises(cd.MediaFirstContractError, match="weekly recap coverage"):  # the existing single contract retry applies
        await cd.generate_carousel_creative(object(), PROMPTS, director_input=director_input)


# --- Russian prose, English UI / code literals ------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Открой VS Code и выбери File > Open Folder, затем распакованную папку.",
    "Нажми на шестерёнку и открой See all settings → General → Smart features.",
    "Вставь в конфиг: «model»: «moonshotai/kimi-k3-free»\n«apiBase»: «https://api.tokenrouter.com/v1»\n«roles»: [«chat», «edit», «apply»]",
    '{ "model": "moonshotai/kimi-k3-free", "apiBase": "https://api.tokenrouter.com/v1", "roles": ["chat", "edit", "apply"] }',
    "Введи @Adobe в новом чате и выбери плагин из меню.",
])
def test_russian_prose_with_source_faithful_english_ui_or_code_passes(text):
    cd.assert_russian_final_text([text], locale="ru")


def test_full_english_editorial_prose_still_fails():
    with pytest.raises(cd.CreativeLanguageError):
        cd.assert_russian_final_text(["Open the settings panel and turn off every AI feature so you can focus on your actual work."], locale="ru")


# --- exact evidence --------------------------------------------------------------------------------------------------------------

LONG = ("The Adobe plugin in ChatGPT brings together tools from our previously released Adobe apps for ChatGPT, along with additional tools "
        "and capabilities across Adobe Express, Photoshop, Firefly, Premiere, Acrobat and more, so you can move from an idea to a finished "
        "asset without leaving the conversation, then keep editing it in the same Adobe plugin session across Photoshop and Firefly.")


def _adobe_package():
    doc = ep.EvidenceSource(url="https://blog.adobe.com/a", source_type=ep.OFFICIAL_DOC, text=LONG)
    return ep.assemble_package(post_id="p", fmt="meme_trend", premise="Adobe plugin in ChatGPT tools Photoshop Firefly", sources=[doc],
                               media=ep.SourceMedia(status=ep.NOT_AVAILABLE))


def test_the_exact_source_line_is_preserved_and_grounds():
    package = _adobe_package()
    item = next(f for f in package.facts if f.text.startswith("The Adobe plugin"))
    assert item.exact_text == LONG and "…" not in item.exact_text
    cd.assert_evidence_grounded([item.exact_text], package.director_evidence())


def test_a_shortened_display_preview_never_touches_grounding():
    package = _adobe_package()
    item = next(f for f in package.facts if f.text.startswith("The Adobe plugin"))
    assert item.display_preview.endswith("…") and len(item.display_preview) < len(LONG)
    assert item.display_preview not in package.director_evidence() and item.exact_text in package.director_evidence()
    cd.assert_evidence_grounded([item.exact_text], package.director_evidence())
    with pytest.raises(cd.UngroundedEvidenceError):  # the 2026-09-25 failure: a quote of the shortened line is not the evidence
        cd.assert_evidence_grounded([item.display_preview.rstrip("…")], package.director_evidence())


def test_a_line_too_long_to_quote_is_left_out_never_shortened():
    long_line = "Open ChatGPT, go to Plugins, and add the Adobe plugin, " * 20
    package = ep.assemble_package(post_id="p", fmt="ai_hack", premise="Adobe plugin", media=ep.SourceMedia(status=ep.NOT_AVAILABLE),
                                  sources=[ep.EvidenceSource(url="u", source_type=ep.OFFICIAL_DOC, text=long_line.strip())])
    assert all(len(line) <= ep.MAX_EXACT_CHARS or line == package.premise for line in package.director_evidence())
    assert not any("…" in line for line in package.director_evidence())


# --- selection immutability -------------------------------------------------------------------------------------------------------

def test_the_selection_modules_are_untouched_by_the_contract():
    root = Path(__file__).resolve().parent.parent / "services"
    for module in ("instagram_feed_product.py", "instagram_feed_planner.py", "instagram_weekly_recap.py", "instagram_weekly_recap_editor.py"):
        text = (root / module).read_text(encoding="utf-8")
        assert "planned_format" not in text and "PLANNED_PRODUCT" not in text, module


def test_a_heading_and_attribution_are_never_glued_onto_the_sentence_the_director_will_quote():
    """E2E 2026-09-25 (Adobe): '– attribution' + 'What you can create ...' heading + the real sentence became ONE evidence item, so
    the Director's exact quote of the sentence failed grounding. The sentence is now its own exact item."""
    blog = ("Introducing the Adobe plugin in ChatGPT\nIntroducing the Adobe plugin in ChatGPT - an intro paragraph that is long enough to "
            "count as the start of the real article body, well over one hundred and twenty characters.\n"
            "– Vibhor Chhabra, product lead for ChatGPT Ecosystem, OpenAI\nWhat you can create with the Adobe plugin in ChatGPT\n"
            "The Adobe plugin in ChatGPT brings together tools from our previously released Adobe apps for ChatGPT, along with additional "
            "tools and capabilities across Adobe Express, Photoshop, Firefly, Premiere, Acrobat, Lightroom, Illustrator, InDesign, Stock and more.")
    sentence = blog.rsplit("\n", 1)[1]
    package = ep.assemble_package(post_id="p", fmt="ai_hack", premise="Introducing the Adobe plugin in ChatGPT", media=ep.SourceMedia(status=ep.NOT_AVAILABLE),
                                  sources=[ep.EvidenceSource(url="https://blog.adobe.com/a", source_type=ep.OFFICIAL_DOC, text=blog)])
    items = [i.exact_text for i in (*package.steps, *package.facts, *package.limitations)]
    assert sentence in items
    cd.assert_evidence_grounded([sentence], package.director_evidence())
