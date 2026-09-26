"""Founder task 2026-09-26 - DIRECTOR STRUCTURED-OUTPUT STABILITY. A truncated / runaway / invalid Director response is a TECHNICAL failure
with its own ONE recovery, separate from the ONE editorial correction; at most 3 Director calls per story. Fixtures: the exact saved runaway
response of the GTA IV retest and every saved successful Director response. No provider call."""
from __future__ import annotations

import glob
import json
import math
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import services.instagram_automatic_trigger as trigger
import services.instagram_creative_director as cd
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_creative_director import (
    CreativeDirectorInput,
    CreativeFactSafetyError,
    DirectorStructuredOutputError,
    InstagramEditorialDecision,
    classify_structured_output,
    director_output_cap,
)
from services.instagram_feed_product import FeedFormat
from services.instagram_viral_format import VIRAL_CAROUSEL_NOTE, EditorialCorrectionRequired

ROOT = Path(__file__).resolve().parent.parent
RUNAWAY = ROOT / "artifacts/instagram_feed_product/director_correction_20260926/live/post/calls/03_director.json"


def _runaway() -> dict:
    return json.loads(RUNAWAY.read_text(encoding="utf-8"))


def _valid_responses() -> list[tuple[str, dict]]:
    out = []
    for path in glob.glob(str(ROOT / "artifacts/**/calls/*director*.json"), recursive=True):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if (data.get("record") or {}).get("finish_reason") == "stop" and isinstance((data.get("response") or {}).get("structured_output"), dict):
            out.append((path, data))
    return out


# --- classification ---------------------------------------------------------------------------------------------------------------------

def test_the_saved_runaway_response_is_a_technical_failure():
    data = _runaway()
    assert data["record"]["finish_reason"] == "length" and data["record"]["output_tokens"] == 16000
    assert classify_structured_output(data["response"]["text"], "length", None) == "whitespace_runaway"


@pytest.mark.parametrize("text,finish,structured,kind", [
    ('{"slides": [{"slide_copy": "GTA IV' + " \t" * 700 + " ", "length", None, "whitespace_runaway"),
    ('{"slides": [{"slide_copy": "' + "лесенки " * 150, "length", None, "repetition_runaway"),
    ('{"slides": [{"slide_copy": "GTA IV получила сглаживание", "slide_body": "Мод', "length", None, "truncated_at_cap"),
    ('{"slides": [', "stop", None, "invalid_json"),
    ('{"slides": []}', "stop", {"slides": []}, None),
])
def test_runaways_truncation_and_invalid_json_are_classified_and_a_complete_object_is_not(text, finish, structured, kind):
    assert classify_structured_output(text, finish, structured) == kind


def test_no_saved_successful_director_response_is_mistaken_for_a_runaway():
    responses = _valid_responses()
    assert len(responses) >= 30
    for path, data in responses:
        response = data["response"]
        assert classify_structured_output(response.get("text"), "stop", response["structured_output"]) is None, path


# --- the output cap -------------------------------------------------------------------------------------------------------------------------

def _input(**kw) -> CreativeDirectorInput:
    return CreativeDirectorInput(objective="shares", format="carousel", opportunity_summary="s", **kw)


def test_the_cap_is_derived_per_post_from_the_measured_all_in_cost_per_slide():
    assert director_output_cap(_input(viral_carousel_note=VIRAL_CAROUSEL_NOTE), cd.CAROUSEL_PROMPT_NAME) == math.ceil(1.25 * 1227 * 7) == 10_737
    assert director_output_cap(_input(is_recap_bundle=True, recap_required_subjects=[f"story_{i}" for i in range(1, 8)]),
                               cd.CAROUSEL_PROMPT_NAME) == math.ceil(1.25 * 1227 * 9)
    assert director_output_cap(_input(), cd.CAROUSEL_PROMPT_NAME) == math.ceil(1.25 * 1227 * 10) < 16_000
    assert director_output_cap(_input(), cd.SINGLE_PROMPT_NAME) == director_output_cap(_input(), cd.REEL_PROMPT_NAME) == 4000


def test_every_saved_valid_director_response_fits_under_the_cap_of_its_own_kind():
    worst: dict[str, int] = {}
    for path, data in _valid_responses():
        output = data["response"]["structured_output"]
        slides = len(output.get("slides") or [])
        tokens = data["record"]["output_tokens"]
        if not slides:
            kind, cap = "single/reel", director_output_cap(_input(), cd.SINGLE_PROMPT_NAME)
        elif "recap" in path:
            kind, cap = "recap", director_output_cap(_input(is_recap_bundle=True, recap_required_subjects=["s"] * (slides - 2)), cd.CAROUSEL_PROMPT_NAME)
        elif slides <= 7:
            kind, cap = "carousel<=7", director_output_cap(_input(viral_carousel_note=VIRAL_CAROUSEL_NOTE), cd.CAROUSEL_PROMPT_NAME)
        else:
            kind, cap = "carousel", director_output_cap(_input(), cd.CAROUSEL_PROMPT_NAME)
        assert tokens <= cap, (path, tokens, cap)
        worst[kind] = max(worst.get(kind, 0), tokens)
    assert worst["recap"] == 11039 and worst["single/reel"] <= 4000


# --- the Director call: a technical failure never reaches the editorial validation ---------------------------------------------------------

class _Gateway:
    def __init__(self, text, finish, structured):
        from integrations.llm_gateway.protocol import GenerateResponse
        from schemas.capability import CapabilityUsage

        self.requests = []
        self.response = GenerateResponse(text=text, structured_output=structured, finish_reason=finish, model_used="gpt-5.6-luna",
                                         usage=CapabilityUsage(input_tokens=10, output_tokens=16000))


@pytest.mark.asyncio
async def test_the_runaway_raises_a_technical_error_before_any_editorial_validation(monkeypatch):
    from types import SimpleNamespace

    from integrations.prompts.file_repository import FilePromptRepository

    data = _runaway()
    gateway = _Gateway(data["response"]["text"], "length", None)

    async def fake_call_generate(gw, request, **kwargs):
        gw.requests.append(request)
        return SimpleNamespace(error=None, response=gw.response, call=None)

    monkeypatch.setattr(cd, "call_generate", fake_call_generate)
    monkeypatch.setattr(cd, "_validate_carousel_output", lambda *a, **k: pytest.fail("editorial validation must not run"))
    director_input = _input(viral_carousel_note=VIRAL_CAROUSEL_NOTE, locale="ru", allowed_evidence=["fact"])
    with pytest.raises(DirectorStructuredOutputError) as excinfo:
        await cd.generate_carousel_creative(gateway, FilePromptRepository(ROOT / "prompts"), director_input=director_input)
    assert excinfo.value.kind == "whitespace_runaway" and gateway.requests[0].max_tokens == 10_737


# --- the call graph: technical recovery x1, editorial correction x1, at most 3 calls ----------------------------------------------------------

class _Recorder:
    def __init__(self, *outcomes):
        self.outcomes, self.inputs = list(outcomes), []

    async def __call__(self, director_input, fmt):
        self.inputs.append(director_input)
        result = self.outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _technical() -> DirectorStructuredOutputError:
    return DirectorStructuredOutputError("whitespace_runaway", "finish_reason=length, output_tokens=10737")


def _editorial() -> EditorialCorrectionRequired:
    return EditorialCorrectionRequired(["slide 1 hook is a clipped fragment", "slide 3 body is a list of product names"])


@pytest.mark.asyncio
async def test_a_valid_response_skips_technical_recovery():
    recorder = _Recorder("OK")
    outcome, trace = await trigger._run_director_sequence(recorder, _input(), None)
    assert outcome == "OK" and len(recorder.inputs) == 1 and [t["stage"] for t in trace] == ["initial"]


@pytest.mark.asyncio
async def test_a_malformed_response_gets_exactly_one_technical_recovery_with_only_a_concise_reason():
    recorder = _Recorder(_technical(), "OK")
    outcome, trace = await trigger._run_director_sequence(recorder, _input(), None)
    assert outcome == "OK" and len(recorder.inputs) == 2 and [t["stage"] for t in trace] == ["initial", "technical_recovery"]
    note = recorder.inputs[1].structured_output_recovery_note
    assert "whitespace_runaway" in note and "do not add any fact" in note and len(note) < 600 and "\t" not in note
    assert recorder.inputs[1].contract_retry_note == ""  # the editorial allowance is untouched


@pytest.mark.asyncio
async def test_a_second_malformed_response_is_terminal():
    recorder = _Recorder(_technical(), _technical())
    with pytest.raises(DirectorStructuredOutputError):
        await trigger._run_director_sequence(recorder, _input(), None)
    assert len(recorder.inputs) == 2


@pytest.mark.asyncio
async def test_valid_but_bad_copy_goes_to_the_editorial_correction_not_to_technical_recovery():
    recorder = _Recorder(_editorial())
    with pytest.raises(trigger._EditorialRetry) as excinfo:
        await trigger._run_director_sequence(recorder, _input(), None)
    assert len(recorder.inputs) == 1 and [t["stage"] for t in excinfo.value.trace] == ["initial"]


@pytest.mark.asyncio
async def test_malformed_then_valid_but_bad_may_still_use_the_editorial_correction():
    recorder = _Recorder(_technical(), _editorial())
    with pytest.raises(trigger._EditorialRetry) as excinfo:
        await trigger._run_director_sequence(recorder, _input(), None)
    assert len(recorder.inputs) == 2 and [t["stage"] for t in excinfo.value.trace] == ["initial", "technical_recovery"]


async def _run_trigger(monkeypatch, recorder):
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
@pytest.mark.parametrize("sequence,reason", [
    ((_technical(), _editorial(), _editorial()), "creative_director_failed:EditorialCorrectionRequired"),
    ((_technical(), _editorial(), _technical()), "creative_director_failed:DirectorStructuredOutputError"),
    ((_editorial(), _technical()), "creative_director_failed:DirectorStructuredOutputError"),
    ((_technical(), _technical()), "creative_director_failed:DirectorStructuredOutputError"),
])
async def test_the_director_is_never_called_more_than_three_times(monkeypatch, sequence, reason):
    recorder = _Recorder(*sequence)
    outcome = await _run_trigger(monkeypatch, recorder)
    assert len(recorder.inputs) == len(sequence) <= 3 and outcome.reason == reason
    if len(sequence) == 3:
        assert recorder.inputs[2].contract_retry_note and not recorder.inputs[2].structured_output_recovery_note


@pytest.mark.asyncio
async def test_a_grounding_hard_failure_gets_neither_recovery_path(monkeypatch):
    recorder = _Recorder(CreativeFactSafetyError("invented quote(s) not in the evidence"))
    outcome = await _run_trigger(monkeypatch, recorder)
    assert len(recorder.inputs) == 1 and outcome.reason == "creative_director_failed:CreativeFactSafetyError"


def test_the_accepted_golden_carousels_are_unaffected():
    replay = json.loads((ROOT / "artifacts/instagram_feed_product/director_correction_20260926/offline/correction_replay.json").read_text(encoding="utf-8"))
    assert replay["golden_deepseek"] == {"result": "PASS"} and replay["golden_hamster"] == {"result": "PASS"}
    for name in ("deepseek", "hamster"):
        call = next(iter(glob.glob(str(ROOT / f"artifacts/instagram_feed_product/viral_carousel_20260926/{name}/calls/*director*.json"))))
        data = json.loads(Path(call).read_text(encoding="utf-8"))
        assert classify_structured_output(data["response"].get("text"), "stop", data["response"]["structured_output"]) is None
