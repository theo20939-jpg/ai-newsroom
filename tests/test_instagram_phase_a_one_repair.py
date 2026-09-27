"""PHASE A ONE-REPAIR ORCHESTRATION (founder task 2026-09-27, after canaries 2-4): first generation -> FULL contract -> PASS, or ONE
correction for a REPAIRABLE failure -> FULL contract again (+ non-regression) -> PASS or terminal. At most 2 Phase A calls; terminal
failures never get a correction; the Director never sees a plan that has not passed. The validators themselves are unchanged - the saved
canary outputs still fail exactly where they failed. No provider call."""
from __future__ import annotations

import asyncio
import copy
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import scripts._instagram_phase_a_contract_replay as replay
import services.instagram_automatic_trigger as trigger
import services.instagram_creative_director as cd
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_feed_product import FeedFormat
from tests.test_instagram_director_correction import _Recorder

C2, C3, C4 = replay.CANARY2, replay.CANARY3, replay.CANARY4
SAVED2, SAVED3, SAVED4 = replay.saved_output(C2), replay.saved_output(C3), replay.saved_output(C4)
FIX2, FIX3, FIX4 = replay.valid_fixture(SAVED2), replay.valid_v5_fixture(SAVED3), replay.canary4_correction_fixture(SAVED4)


def _seq(outputs, canary=C4):
    return asyncio.run(replay.run_phase_a_sequence(outputs, canary))


def _variant(**fields):
    v = copy.deepcopy(FIX4)
    v.update(fields)
    return v


# --- 1-5: the orchestration --------------------------------------------------------------------------------------------------------
def test_1_a_first_pass_plan_gets_no_correction():
    result = _seq([FIX3], C3)
    assert result["result"] == "PASS" and result["phase_a_calls"] == 1 and result["summary"]["correction_used"] is False


def test_2_a_repairable_failure_gets_one_correction_and_passes():
    result = _seq([SAVED4, FIX4])
    assert result["result"] == "PASS" and result["phase_a_calls"] == 2
    assert result["calls"][0] == {"capability": cd.EDITORIAL_DECISION_PROMPT_NAME, "correction_input": False}
    assert result["calls"][1] == {"capability": cd.EDITORIAL_DECISION_CORRECTION_PROMPT_NAME, "correction_input": True}
    assert result["summary"]["correction_prompt_version"] == "1" and result["summary"]["result"] == "PASS"


def test_3_a_failed_correction_is_terminal_after_exactly_two_calls():
    result = _seq([SAVED4, SAVED4])
    assert result["result"] == "EditorialDecisionContractError" and result["phase_a_calls"] == 2
    assert "after the one correction" in result["detail"] and result["post_correction_findings"]


@pytest.mark.parametrize("bad,error", [(dict(evidence_used=["E99"]), "UngroundedEvidenceError"),
                                       (dict(recommended_format="podcast"), "EditorialDecisionContractError")])
def test_4_a_terminal_failure_gets_no_correction(bad, error):
    first = copy.deepcopy(SAVED4)
    first.update(bad)
    result = _seq([first, FIX4])
    assert result["result"] == error and result["phase_a_calls"] == 1 and result["summary"] is None


def test_5_there_are_never_more_than_two_phase_a_calls():
    assert cd.MAX_PHASE_A_CALLS == 2
    result = _seq([SAVED4, SAVED4, FIX4, FIX4])  # a third output is available - it is never requested
    assert result["phase_a_calls"] == 2 and result["result"] != "PASS"


# --- 6: the Director waits for a passed plan -----------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_6_the_director_cannot_run_before_the_corrected_phase_a_passes(monkeypatch):
    from integrations.prompts.file_repository import FilePromptRepository

    outputs = [SAVED4, SAVED4]
    calls: list = []

    async def fake_call(_gateway, _request, **_kw):
        calls.append(1)
        from types import SimpleNamespace
        return SimpleNamespace(error=None, call=None, response=SimpleNamespace(finish_reason="stop", structured_output=copy.deepcopy(outputs[len(calls) - 1])))

    async def real_phase_a(session, **kwargs):  # the trigger's Phase A step, running the REAL generate_editorial_decision
        await cd.generate_editorial_decision(None, FilePromptRepository(replay.ROOT / "prompts"), decision_input=replay.decision_input(C4))
        raise AssertionError("unreachable: the plan never passed")

    director = _Recorder()
    monkeypatch.setattr(cd, "call_generate", fake_call)
    monkeypatch.setattr(trigger, "_build_phase_a_editorial_plan", real_phase_a)
    monkeypatch.setattr(trigger, "get_video_candidates_for_event", AsyncMock(return_value=[]))
    monkeypatch.setattr(trigger.InstagramEditorialDeliveryService, "find_current", AsyncMock(return_value=None))
    monkeypatch.setattr(trigger, "build_default_regenerator", lambda gateway, prompts: director)
    opportunity = ContentOpportunity(id=f"opp-{uuid4()}", source_type=OpportunitySourceType.NEWS, story_id=str(uuid4()), news_value=1.0,
                                     audience_relevance=0.5, product_mention_allowed=False, evidence=["fact"], confidence=0.5)
    outcome = await trigger.evaluate_and_submit_instagram_opportunity(
        AsyncMock(), AsyncMock(), opportunity=opportunity, opportunity_summary="s", gateway=object(), prompt_repository=object(),
        phase_a_enabled=True, required_feed_format=FeedFormat.MEME_TREND)
    assert outcome.reason == "editorial_decision_failed:EditorialDecisionContractError"
    assert len(calls) == 2 and director.inputs == []  # two Phase A calls, the Director never called


# --- 7-12: the corrected plan is held to the FULL contract + non-regression ---------------------------------------------------------
@pytest.mark.parametrize("name,corrected,marker", [
    ("7 promotes Education to confirmed", _variant(source_summary="OpenAI подтвердила доступ к сайту Министерства образования."),
     "education is UNDER_INVESTIGATION"),
    ("8 collapses mixed target status", _variant(source_summary="Агент получил доступ к сайтам Министерства торговли, Министерства образования и SEC."),
     "grouped with commerce, sec"),
    ("10 introduces hack wording", _variant(creative_direction=FIX4["creative_direction"].replace("Затем отдельная карточка",
                                                                                                "Агент взломал сайты ведомств. Затем отдельная карточка")),
     "stronger action than the evidence"),
    ("11 introduces fake government UI", _variant(creative_direction=FIX4["creative_direction"].replace(
        "Использовать исходное изображение", "Фон — интерфейс государственного сайта. Использовать исходное изображение")), "fabricated official material"),
    ("12 introduces an unsupported trend claim", _variant(trend_rationale="История стала трендом Instagram."), "trend:"),
])
def test_7_8_10_11_12_a_correction_that_breaks_the_contract_is_terminal(name, corrected, marker):
    result = _seq([SAVED4, corrected])
    assert result["result"] == "EditorialDecisionContractError" and result["phase_a_calls"] == 2, name
    assert any(marker in f for f in result["post_correction_findings"]), (name, result["post_correction_findings"])


def test_9_a_correction_cannot_alter_the_summer_vs_disclosure_chronology():
    timeless = _variant(
        source_summary=("Автономный ИИ-агент OpenAI взаимодействовал с сайтами американских ведомств. OpenAI подтвердила доступ к ресурсам "
                        "Министерства торговли и SEC; эпизод с Министерством образования остаётся под расследованием."),
        why_now="Важно объяснить разницу между подтверждёнными случаями и эпизодом, который ещё расследуется.",
        angle="Реакция на тревожную аномалию: что подтверждено, а что ещё расследуется.",
        creative_direction=("Открытие: крупная типографика «ИИ сам взаимодействовал с госсайтами?». Далее отдельные карточки: OpenAI подтвердила "
                            "доступ к сайтам Министерства торговли и SEC. Затем отдельная карточка: эпизод с Министерством образования ещё "
                            "расследуется. Исходное изображение и абстрактная графика инфраструктуры. Финал: ответ компании."),
        format_reason="Карусель чётко разделит подтверждённые и расследуемые эпизоды.")
    result = _seq([SAVED4, timeless])
    assert result["result"] == "EditorialDecisionContractError" and result["phase_a_calls"] == 2
    assert any("removed WHEN the behaviour happened" in f for f in result["post_correction_findings"])


# --- 13-15: the saved canaries ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("canary,saved,fixture,expected", [
    (C2, SAVED2, FIX2, ("fabricated official material", "invents governance framing", "education is UNDER_INVESTIGATION")),  # 13
    (C3, SAVED3, FIX3, ("INCOMPLETE_CREATIVE_DIRECTION",)),  # 14
    (C4, SAVED4, FIX4, ("stronger action than the evidence", "promoted to 'confirmed'")),  # 15
])
def test_13_14_15_the_saved_canary_still_fails_where_it_failed_and_one_correction_repairs_it(canary, saved, fixture, expected):
    first_alone = _seq([saved, saved], canary)  # the saved output is still a contract failure (validators unchanged)
    assert first_alone["result"] == "EditorialDecisionContractError"
    for marker in expected:
        assert any(marker in f for f in first_alone["first_findings"]), (marker, first_alone["first_findings"])
    repaired = _seq([saved, fixture], canary)
    assert repaired["result"] == "PASS" and repaired["phase_a_calls"] == 2 and repaired["post_correction_findings"] == []


def test_the_correction_prompt_is_separate_and_v5_is_untouched():
    from integrations.prompts.file_repository import FilePromptRepository

    repo = FilePromptRepository(replay.ROOT / "prompts")
    correction = repo.resolve(cd.EDITORIAL_DECISION_CORRECTION_PROMPT_NAME, "1")
    v5 = repo.resolve(cd.EDITORIAL_DECISION_PROMPT_NAME, "5")
    assert correction.output_schema == v5.output_schema and cd._EDITORIAL_DECISION_PLANNED_PROMPT_VERSION == "5"
    text = " ".join(correction.rules)
    for rule in ("change nothing else", "Do not add facts", "Do not strengthen any factual claim", "Do not alter the chronology",
                 "fabricated official material", "at most 650 characters"):
        assert rule in text, rule
