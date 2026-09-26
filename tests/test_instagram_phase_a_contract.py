"""PHASE A LIVE-CANARY REPAIR (founder task 2026-09-27): a negation-aware trend-claim guard, and the Phase A contract - target-specific
factual status (the existing ledger), visual safety, a grounded finale. Deterministic - no provider call."""
from __future__ import annotations

import asyncio

import pytest

import scripts._instagram_phase_a_contract_replay as replay
from services.instagram_creative_director import UngroundedTrendClaimError, assert_trend_rationale_grounded
from services.instagram_phase_a_contract import phase_a_finale_findings, phase_a_status_findings, phase_a_visual_findings

EVIDENCE = [
    "Этим летом система в лабораторных условиях получила доступ к ресурсам Министерства образования, Министерства торговли и SEC.",
    "OpenAI подтвердила несанкционированный доступ к сайтам Министерства торговли и SEC.",
    "Расследование эпизода, связанного с ресурсом Министерства образования, продолжается.",
    "Компания заявила, что заранее уведомила соответствующие американские ведомства.",
    "CHRONOLOGY: disclosed 2026-09-25; behaviour this summer - the disclosure is new, the behaviour is not.",
]


def _guard(text: str) -> None:
    assert_trend_rationale_grounded(text, signal_type=None, provenance=None, is_platform_native=False)


# --- 1-7: trend claims vs denials --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("claim", ["История стала трендом Instagram.", "Сюжет вирусится в Instagram.", "История набирает вирусный охват.",
                                   "Это уже Instagram-тренд.", "Пост активно разлетается по Instagram."])
def test_1_and_6_a_positive_trend_claim_without_a_signal_fails(claim):
    with pytest.raises(UngroundedTrendClaimError):
        _guard(claim)


@pytest.mark.parametrize("denial", [
    "Нельзя утверждать, что история стала трендом Instagram.",  # 2
    "История не является трендом Instagram.",  # 3
    "Нет данных, что это тренд Instagram.",  # 4
    "Instagram-native сигнал отсутствует, поэтому нельзя называть историю вирусной или утверждать, что она стала трендом Instagram.",
    "Мы не можем утверждать, что это вирусный сюжет в Instagram.",
])
def test_2_3_4_and_7_a_denial_without_a_signal_passes(denial):
    _guard(denial)


@pytest.mark.parametrize("text", ["Мы не ожидали такого, но история стала трендом Instagram.",
                                  "История, которую никто не ожидал, стала трендом Instagram.",
                                  "Хотя мы этого не планировали, сюжет вирусится в Instagram.",
                                  "Неудивительно, что история стала трендом Instagram."])
def test_5_an_unrelated_negation_does_not_suppress_a_real_trend_claim(text):
    with pytest.raises(UngroundedTrendClaimError):
        _guard(text)


def test_a_platform_native_signal_still_allows_a_real_trend_claim():
    assert_trend_rationale_grounded("История стала трендом Instagram.", signal_type="audio", provenance="instagram", is_platform_native=True)


# --- 8-10: target status in Phase A -----------------------------------------------------------------------------------------------------
def test_8_confirmed_and_investigated_targets_cannot_be_grouped_unqualified():
    found = phase_a_status_findings({"source_summary": "Агент получил доступ к сайтам Министерства торговли, Министерства образования и SEC."},
                                    EVIDENCE)
    assert found and "education is UNDER_INVESTIGATION" in found[0] and found[0].startswith("Phase A source_summary")


def test_9_a_confirmed_only_grouping_is_allowed_where_the_evidence_supports_it():
    assert phase_a_status_findings({"source_summary": "OpenAI подтвердила доступ к сайтам Министерства торговли и SEC."}, EVIDENCE) == []


def test_10_the_under_investigation_qualifier_is_preserved():
    ok = {"source_summary": "OpenAI подтвердила доступ к сайтам Министерства торговли и SEC; эпизод с Министерством образования ещё расследуется."}
    assert phase_a_status_findings(ok, EVIDENCE) == []
    promoted = {"angle": "OpenAI подтвердила доступ к сайту Министерства образования."}
    assert phase_a_status_findings(promoted, EVIDENCE)


# --- 11-13: visual direction --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("direction", ["Первый слайд - интерфейс государственного сайта и крупная надпись.",
                                       "Визуал: скриншот сайта министерства с формой входа.",
                                       "Показать фейковый документ с печатью ведомства.",
                                       "Сгенерировать поддельный скриншот переписки агента."])
def test_11_and_12_fake_government_ui_screenshots_and_evidence_are_rejected(direction):
    assert phase_a_visual_findings({"creative_direction": direction})


@pytest.mark.parametrize("direction", ["Визуал: реальное фото из источника и абстрактная серверная инфраструктура.",
                                       "Абстрактные цифровые сети, светящиеся линии данных, типографская композиция.",
                                       "Без имитации интерфейсов государственных сайтов и без поддельных документов."])
def test_13_abstract_editorial_infrastructure_imagery_is_allowed(direction):
    assert phase_a_visual_findings({"creative_direction": direction}) == []


# --- 14-16: the finale -------------------------------------------------------------------------------------------------------------
def test_14_an_unsupported_governance_debate_finale_is_rejected():
    assert phase_a_finale_findings({"creative_direction": "Финал — вопрос о том, где должна проходить граница автономности ИИ."}, EVIDENCE)
    assert phase_a_finale_findings({"angle": "В конце вынести на обсуждение, кто должен контролировать действия агента."}, EVIDENCE)


def test_15_an_evidence_grounded_open_question_is_allowed():
    grounded = {"format_reason": "Финал — открытый вопрос: чем закончится расследование эпизода с Министерством образования."}
    assert phase_a_finale_findings(grounded, EVIDENCE) == []
    raised = EVIDENCE + ["Регуляторы спросили, кто должен контролировать автономных агентов."]  # the evidence itself raises governance
    assert phase_a_finale_findings({"creative_direction": "Финал — вопрос: кто должен контролировать автономных агентов?"}, raised) == []


def test_16_a_factual_grounded_final_takeaway_is_allowed():
    assert phase_a_finale_findings({"creative_direction": "Финальный слайд: что ответила OpenAI - компания заранее уведомила ведомства."},
                                   EVIDENCE) == []


# --- 17 + the saved canary --------------------------------------------------------------------------------------------------------
def test_17_phase_a_still_produces_a_valid_carousel_plan_after_all_guards():
    result = asyncio.run(replay.run_phase_a(replay.valid_fixture(replay.saved_output())))
    assert result["result"] == "PASS" and result["recommended_format"] == "carousel"
    assert "phase_a_contract_violation" not in result["diagnostics"]


def test_the_saved_canary_2_phase_a_is_diagnosed_not_made_safe():
    view = replay.component_view(replay.saved_output())
    assert view["trend_disclaimer_recognised"]  # the live false positive is fixed
    assert view["status"] and view["visual"] and view["finale"]  # but the old output stays unsafe
    result = asyncio.run(replay.run_phase_a(replay.saved_output()))
    assert result["result"] == "EditorialDecisionContractError" and "UngroundedTrendClaimError" not in result["detail"]
    assert "phase_a_contract_violation" in result["diagnostics"]


def test_phase_a_receives_the_existing_ledgers_status_summary():
    from services.instagram_creative_director import _build_decision_user_text

    text = _build_decision_user_text(replay.decision_input(), handles=True, contract=True)
    assert "FACTUAL STATUS LEDGER" in text and "education: UNDER_INVESTIGATION" in text and "commerce: CONFIRMED" in text
    assert "FACTUAL STATUS LEDGER" not in _build_decision_user_text(replay.decision_input(), handles=True)  # v3 text unchanged
