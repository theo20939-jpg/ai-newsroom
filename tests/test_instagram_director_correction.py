"""Founder decision 2026-09-26: ONE Director correction pass for editorial copy. Correctable copy problems of a viral carousel are collected
and sent back once with every finding; a second failure is terminal; grounding failures never enter the retry. No provider call."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import services.instagram_automatic_trigger as trigger
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_creative_director import CreativeFactSafetyError, CreativeLanguageError, InstagramEditorialDecision
from services.instagram_feed_product import FeedFormat
from services.instagram_viral_format import EditorialCorrectionRequired, clipped_hook, generic_filler, product_list, viral_copy_findings

ROOT = Path(__file__).resolve().parent.parent
REPLAY = ROOT / "artifacts/instagram_feed_product/director_correction_20260926/offline/correction_replay.json"


# --- the exact saved GTA output and the golden examples (zero cost) ----------------------------------------------------------------------

def test_the_saved_gta_output_gets_one_structured_correction_instead_of_a_terminal_language_error():
    gta = json.loads(REPLAY.read_text(encoding="utf-8"))["gta_saved_output"]
    assert gta["result"].startswith("EditorialCorrectionRequired")
    assert all(gta["required_detected"].values()), gta["required_detected"]
    assert gta["correction_note"].startswith("EDITORIAL CORRECTION (your one correction attempt)")
    assert "never keep a slide only to preserve the count" in gta["correction_note"]


@pytest.mark.parametrize("golden", ["golden_deepseek", "golden_hamster"])
def test_the_accepted_golden_carousels_get_no_correction_request(golden):
    assert json.loads(REPLAY.read_text(encoding="utf-8"))[golden] == {"result": "PASS"}


# --- the detectors: positives from the failed output, negatives from the accepted copy ---------------------------------------------------

def test_a_clipped_telegraphic_hook_is_found_and_a_plain_nominal_hook_is_not():
    assert clipped_hook("GTA IV: «лесенки» — всё, через 18 лет")
    for accepted in ("460 целей. Ни одного взлома.", "Хомяк пробежал 6,06 мили.", "После 18 лет «лесенок» моддер добавил в GTA IV сглаживание"):
        assert not clipped_hook(accepted)


def test_a_product_name_list_is_not_prose_but_a_sentence_with_those_names_is():
    assert product_list("Nvidia DLSS 4 · AMD FSR 3 · DLAA · HDR")
    assert not product_list("Мод добавляет поддержку Nvidia DLSS 4, AMD FSR 3, DLAA и HDR.")


def test_generic_filler_is_a_generalisation_without_a_concrete_anchor():
    assert generic_filler("Классика получила апгрейд от сообщества — спустя почти два десятилетия.")
    assert not generic_filler("Мод DLSS-IV можно скачать на Nexus Mods.")
    assert not generic_filler("Колесо, трекер и отдельный аккаунт — всё как у настоящего бегуна.")


def test_an_anglicism_with_a_natural_russian_word_is_named_and_product_names_are_not():
    findings = viral_copy_findings([{"slide_copy": "Апгрейд пришёл не от Rockstar", "slide_body": "Мод поддерживает Nvidia DLSS 4 и HDR."}], [])
    assert any("anglicism 'Апгрейд'" in f for f in findings)
    assert not any("DLSS" in f or "HDR" in f for f in findings if "anglicism" in f)


# --- the trigger: exactly ONE correction attempt; grounding never retried ----------------------------------------------------------------

class _Recorder:
    def __init__(self, *outcomes):
        self.outcomes, self.inputs = list(outcomes), []

    async def __call__(self, director_input, fmt):
        self.inputs.append(director_input)
        result = self.outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


async def _run(monkeypatch, recorder):
    decision = InstagramEditorialDecision(
        source_summary="s", opportunity_type="NEWS", why_now="w", audience_value="a", angle="a", angle_intent="MEME",
        topic="t", purpose="VALUE", origin="NEWS", recommended_format="carousel", format_reason="f", creative_direction="c")
    opportunity = ContentOpportunity(id=f"opp-{uuid4()}", source_type=OpportunitySourceType.NEWS, story_id=str(uuid4()), news_value=1.0,
                                     audience_relevance=0.5, product_mention_allowed=False, evidence=["fact"], confidence=0.5)
    decided = trigger.replace(opportunity, editorial_decision=decision.model_dump())

    async def fake_plan(session, **kwargs):
        rec = trigger.recommend_objective(opportunity=decided, has_multi_step_narrative=False)
        return trigger._PhaseAEditorialPlan(
            opportunity=decided, format_decision=trigger.evaluate_format_shadow(objective=rec.primary_objective, has_video_asset=False,
                                                                                has_multi_step_narrative=False),
            duplicate=trigger.InstagramEditorialDuplicateDecision(False, "none"), brand_context="", account_context="", product_context="",
            recent_content_context="")

    monkeypatch.setattr(trigger, "_build_phase_a_editorial_plan", fake_plan)
    monkeypatch.setattr(trigger, "get_video_candidates_for_event", AsyncMock(return_value=[]))
    monkeypatch.setattr(trigger.InstagramEditorialDeliveryService, "find_current", AsyncMock(return_value=None))
    monkeypatch.setattr(trigger, "_resolve_single_source_image", AsyncMock(return_value=(None, None, 0, 0)))
    monkeypatch.setattr(trigger, "_decoded_source_candidates", AsyncMock(return_value=([], 0)))
    monkeypatch.setattr(trigger, "build_default_regenerator", lambda gateway, prompts: recorder)
    return await trigger.evaluate_and_submit_instagram_opportunity(
        AsyncMock(), AsyncMock(), opportunity=opportunity, opportunity_summary="s", gateway=object(), prompt_repository=object(),
        phase_a_enabled=True, required_feed_format=FeedFormat.MEME_TREND)


@pytest.mark.asyncio
async def test_a_correctable_failure_gets_exactly_one_structured_retry_and_a_second_failure_is_terminal(monkeypatch):
    first = EditorialCorrectionRequired(["slide 1 hook is a clipped fragment", "slide 3 body is a list of product names"])
    recorder = _Recorder(first, EditorialCorrectionRequired(["still clipped"]))
    outcome = await _run(monkeypatch, recorder)
    assert len(recorder.inputs) == 2  # the original call + ONE correction - never a third
    assert recorder.inputs[1].contract_retry_note == first.correction_note and "2. slide 3 body is a list" in first.correction_note
    assert outcome.reason == "creative_director_failed:EditorialCorrectionRequired"


@pytest.mark.asyncio
@pytest.mark.parametrize("hard", [CreativeFactSafetyError("invented quote(s) not in the evidence"),
                                  CreativeFactSafetyError("generated-image review: likeness of a named real person")])
async def test_grounding_and_likeness_failures_never_enter_the_correction_retry(monkeypatch, hard):
    recorder = _Recorder(hard)
    outcome = await _run(monkeypatch, recorder)
    assert len(recorder.inputs) == 1 and outcome.reason == "creative_director_failed:CreativeFactSafetyError"


@pytest.mark.asyncio
async def test_a_non_viral_language_error_keeps_its_existing_terminal_behaviour(monkeypatch):
    # the correction pass applies where the validation collects findings (a viral carousel); a bare CreativeLanguageError stays terminal
    recorder = _Recorder(CreativeLanguageError("clearly English audience-facing field"))
    outcome = await _run(monkeypatch, recorder)
    assert len(recorder.inputs) == 1 and outcome.reason == "creative_director_failed:CreativeLanguageError"
