"""PHASE A CANARY-3 REPAIR (founder task 2026-09-27): a denied / disclaimed action word in Phase A's reasoning is not an assertion, while a
real assertion (incl. affirming idioms) is still blocked; and a creative_direction cut mid-sentence never reaches the Director (v5: up to
650 requested, 700 schema bound). Only the Phase A layer changed - the Director's factual-status gate is untouched. No provider call."""
from __future__ import annotations

import asyncio

import pytest

import scripts._instagram_phase_a_contract_replay as replay
from services.instagram_factual_status import build_status_ledger, status_violations
from services.instagram_phase_a_contract import incomplete_creative_direction, phase_a_status_findings

EVIDENCE = [
    "Этим летом система в лабораторных условиях получила доступ к ресурсам Министерства образования, Министерства торговли и SEC.",
    "OpenAI подтвердила несанкционированный доступ к сайтам Министерства торговли и SEC.",
    "Расследование эпизода, связанного с ресурсом Министерства образования, продолжается.",
]


def _findings(text: str, field: str = "audience_value") -> list[str]:
    return phase_a_status_findings({field: text}, EVIDENCE)


# --- 1-5: a denial is not an assertion ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Помогает не воспринимать это как доказанный взлом.",  # 1
    "Нет доказательств взлома.",  # 2
    "Мы не утверждаем, что агент взломал сайт.",  # 3
    "Формулировка «взлом» не подтверждена.",  # 4
    "Это не доказанный «взлом» всех трёх ведомств.",  # 5
    "Помогает отделить подтверждённые факты от неподтверждённых формулировок и не воспринимать историю как доказанный «взлом» всех трёх ведомств.",
])
def test_1_to_5_a_negated_or_disclaimed_action_passes(text):
    assert _findings(text) == []


# --- 6-11: an assertion still fails --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Агент взломал сайт.",  # 6
    "Это был взлом.",  # 7
    "Агент не только взломал сайт.",  # 8
    "Агент не просто взломал сайт.",  # 9
    "Нельзя исключать, что агент взломал сайт.",  # 10
    "Неудивительно, что агент взломал сайт.",  # 11
    "Агент без активных инструкций взломал сайт.",  # a bare 'без' negates something else
    "Агент взломал сайт, хотя доказательства обратного отсутствуют.",  # a denial past a contrastive boundary does not count
])
def test_6_to_11_a_positive_unsupported_action_is_still_blocked(text):
    found = _findings(text)
    assert found and "stronger action than the evidence" in found[0]


def test_every_phase_a_field_stays_checked_and_the_downstream_gate_is_unchanged():
    for field in ("audience_value", "why_now", "source_summary", "angle"):
        assert _findings("Агент взломал сайт.", field)
    # the Director's gate still reads a negated 'взлом' in AUDIENCE copy as it always did (no downstream change)
    ledger = build_status_ledger(EVIDENCE)
    assert status_violations([{"slide_copy": "Это не доказанный «взлом»."}], "", ledger, EVIDENCE)


def test_a_grouped_status_claim_behind_an_unrelated_without_is_still_caught():
    summary = ("Стало известно, что автономный ИИ-агент OpenAI летом в лабораторных условиях без активных инструкций получил доступ к сайтам "
               "Министерства торговли, Министерства образования и SEC.")
    found = phase_a_status_findings({"source_summary": summary}, EVIDENCE)
    assert found and "education is UNDER_INVESTIGATION" in found[0]


# --- 12-18: creative_direction completeness --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("tail", [
    "Первый слайд — хук, далее статусы,",  # 12 comma
    "Первый слайд — хук. Финал:",  # 13 colon
    "Первый слайд — хук. Финал —",  # 14 em dash
    "Первый слайд — хук. Финал — «Главный факт: это не событие сегодняшнего дня",  # 15 unclosed quote
    "Первый слайд — хук. Финал (главный факт",  # 16 unclosed bracket
    "Первый слайд — хук; далее;",
])
def test_12_to_16_an_unfinished_creative_direction_fails(tail):
    finding = incomplete_creative_direction({"creative_direction": tail})
    assert finding and finding.startswith("INCOMPLETE_CREATIVE_DIRECTION")


def test_17_a_complete_plan_under_650_characters_passes():
    plan = replay.valid_v5_fixture(replay.saved_output(replay.CANARY3))["creative_direction"]
    assert len(plan) < 650 and incomplete_creative_direction({"creative_direction": plan}) is None


@pytest.mark.parametrize("plan", ["Первый слайд — хук. Финал — «Главный факт: раскрыли только сейчас».",
                                  "Финал — «это раскрытие летнего эпизода, а не событие сегодняшнего дня»",
                                  "Финал — „раскрытие, а не событие дня“.", "Финал — “disclosed now”."])
def test_18_a_complete_quoted_final_sentence_passes(plan):
    assert incomplete_creative_direction({"creative_direction": plan}) is None


def test_the_v5_schema_and_prompt_bound_the_plan():
    import yaml

    from schemas.instagram_creative import InstagramEditorialDecision

    v5 = yaml.safe_load((replay.ROOT / "prompts/instagram_editorial_decision/v5.yaml").read_text(encoding="utf-8"))
    v4 = yaml.safe_load((replay.ROOT / "prompts/instagram_editorial_decision/v4.yaml").read_text(encoding="utf-8"))
    assert v5["output_schema"]["properties"]["creative_direction"]["maxLength"] == 700
    assert v4["output_schema"]["properties"]["creative_direction"]["maxLength"] == 400  # v4 untouched
    assert any("at most 650 characters" in rule for rule in v5["rules"])
    assert InstagramEditorialDecision.model_fields["creative_direction"].metadata[-1].max_length == 700


# --- the saved canary-3 output and the v5 fixture on the real Phase A path ------------------------------------------------------------
def test_the_saved_canary3_phase_a_fails_only_on_its_truncated_creative_direction():
    view = replay.component_view(replay.saved_output(replay.CANARY3), replay.CANARY3)
    assert view["trend_disclaimer_recognised"] and view["status"] == [] and view["visual"] == [] and view["finale"] == []
    assert view["incomplete_creative_direction"].startswith("INCOMPLETE_CREATIVE_DIRECTION")
    result = asyncio.run(replay.run_phase_a(replay.saved_output(replay.CANARY3), replay.CANARY3))
    assert result["result"] == "EditorialDecisionContractError" and "INCOMPLETE_CREATIVE_DIRECTION" in result["detail"]
    assert "stronger action" not in result["detail"]  # the live false positive is gone


def test_the_valid_v5_fixture_passes_the_real_phase_a_path():
    result = asyncio.run(replay.run_phase_a(replay.valid_v5_fixture(replay.saved_output(replay.CANARY3)), replay.CANARY3))
    assert result["result"] == "PASS" and result["recommended_format"] == "carousel"
