"""TARGET STATUS SAFETY + COPY / JUDGE CALIBRATION (founder task 2026-09-27, after the first paid viral canary). Deterministic - no provider
call. Synthetic fixtures use institutions in general; the canary replay uses the saved artifacts of that run."""
from __future__ import annotations

import asyncio

import pytest

import scripts._instagram_viral_status_replay as replay
from services.instagram_factual_status import (
    abstract_question_findings,
    build_status_ledger,
    distinct_by_role,
    factual_invariants,
    ledger_note,
    non_regression_findings,
    slide_thesis_role,
    status_violations,
)
from services.instagram_viral_editorial_judge import apply_role_guard, parse_verdict
from services.instagram_viral_format import EditorialCorrectionRequired, lifted_wording, viral_copy_findings

EVIDENCE = [
    "Этим летом система в лабораторных условиях получила доступ к ресурсам Министерства образования, Министерства торговли и SEC.",
    "OpenAI подтвердила несанкционированный доступ к сайтам Министерства торговли и SEC.",
    "Расследование эпизода, связанного с ресурсом Министерства образования, продолжается.",
    "CHRONOLOGY: disclosed 2026-09-25; behaviour this summer - the disclosure is new, the behaviour is not.",
]
LEDGER = build_status_ledger(EVIDENCE)


def _slide(copy: str, body: str = "") -> dict:
    return {"slide_copy": copy, "slide_body": body}


def _violations(copy: str, body: str = "", caption: str = "", ledger=None, evidence=None):
    return status_violations([_slide(copy, body)], caption, ledger if ledger is not None else LEDGER, evidence or EVIDENCE)


def test_the_ledger_reads_each_targets_status_from_the_evidence():
    status = {t.target: (t.status, t.evidence_ids) for t in LEDGER}
    assert status == {"commerce": ("CONFIRMED", ("E1", "E2")), "sec": ("CONFIRMED", ("E1", "E2")),
                      "education": ("UNDER_INVESTIGATION", ("E1", "E3"))}  # the most cautious status wins over E1's grouped sentence


# --- 1-6: the status gate --------------------------------------------------------------------------------------------------------------
def test_1_a_confirmed_target_may_be_asserted_as_confirmed():
    assert _violations("OpenAI подтвердила доступ к Commerce и SEC", "Эпизод с Министерством образования всё ещё расследуется.") == []
    assert _violations("Доступ подтверждён", "OpenAI подтвердила доступ к Commerce и SEC; эпизод с Education всё ещё расследуется.") == []


def test_2_an_investigated_target_cannot_be_asserted_as_confirmed():
    found = _violations("OpenAI подтвердила доступ к сайту Министерства образования")
    assert found and found[0].target == "education" and found[0].evidence_status == "UNDER_INVESTIGATION"
    assert found[0].evidence_ids == ("E1", "E3")


def test_3_confirmed_and_investigated_targets_cannot_share_one_unqualified_claim_or_count():
    grouped = _violations("Агент получил доступ к ресурсам Министерства образования, Министерства торговли и SEC")
    assert grouped and "grouped with commerce, sec" in grouped[0].reason
    counted = _violations("Без команды — но с доступом к трём ведомствам")
    assert counted and "the count includes education" in counted[0].reason
    assert _violations("Агент получил доступ к двум ведомствам — Министерству торговли и SEC") == []  # the true count is fine


def test_4_an_attempt_is_not_a_completed_action():
    evidence = ["Агент пытался взломать сайт Министерства юстиции."]
    ledger = build_status_ledger(evidence)
    assert ledger[0].status == "ATTEMPTED"
    assert _violations("Агент взломал сайт Министерства юстиции", ledger=ledger, evidence=evidence)
    assert _violations("Агент пытался взломать сайт Министерства юстиции", ledger=ledger, evidence=evidence) == []


def test_5_a_failed_attempt_is_not_a_success():
    evidence = ["Агенту не удалось получить доступ к сайту Министерства обороны."]
    ledger = build_status_ledger(evidence)
    assert ledger[0].status == "FAILED_ATTEMPT"
    assert _violations("Агент получил доступ к сайту Министерства обороны", ledger=ledger, evidence=evidence)
    assert _violations("Получить доступ к сайту Министерства обороны агенту не удалось", ledger=ledger, evidence=evidence) == []


def test_6_an_unconfirmed_target_is_not_a_fact():
    evidence = ["По неподтверждённым данным, агент получил доступ к сайту FBI."]
    ledger = build_status_ledger(evidence)
    assert ledger[0].status == "UNCONFIRMED"
    assert _violations("Агент получил доступ к сайту FBI", ledger=ledger, evidence=evidence)
    assert _violations("Агент, возможно, получил доступ к сайту FBI", ledger=ledger, evidence=evidence) == []


def test_no_intrusion_verb_the_evidence_never_uses_and_no_today_for_earlier_behaviour():
    assert any("stronger action" in v.reason for v in _violations("Агент OpenAI взломал сайты ведомств"))
    assert any("chronology" in v.target for v in _violations("Сегодня агент получил доступ к сайтам ведомств"))


# --- 7-8: copied wording ----------------------------------------------------------------------------------------------------------------
def test_7_short_exact_factual_status_wording_is_allowed():
    for sentence in ("OpenAI подтвердила несанкционированный доступ к сайтам Министерства торговли и SEC.",
                     "Расследование эпизода, связанного с ресурсом Министерства образования, продолжается.",
                     "Этим летом агент получил доступ к ресурсам Министерства образования, Министерства торговли и SEC."):
        assert lifted_wording(sentence, EVIDENCE) is None, sentence


def test_8_long_source_like_copying_still_fails():
    source = ["Компания заявила, что заранее уведомила соответствующие американские ведомства и признала, что автономный агент "
              "взаимодействовал с государственными сайтами нетипичным способом.",
              "Для работы требуется глобальная техническая модификация Fusion Fix."]
    assert lifted_wording("Компания признала, что автономный агент взаимодействовал с государственными сайтами нетипичным способом.", source)
    assert lifted_wording("Компания заявила, что заранее уведомила соответствующие американские ведомства.", source)
    assert lifted_wording("Для работы мода требуется глобальная техническая модификация Fusion Fix.", source)


# --- 9-10: thesis roles ------------------------------------------------------------------------------------------------------------------
ACTION = _slide("Доступ — без активных инструкций", "Этим летом агент в лабораторных условиях заходил на сайты нескольких ведомств США.")
STATUS = _slide("Commerce и SEC — подтверждено", "OpenAI подтвердила несанкционированный доступ к сайтам Министерства торговли и SEC.")


def test_9_event_action_and_target_status_are_distinct_theses():
    assert slide_thesis_role(ACTION, 2) == "EVENT_ACTION" and slide_thesis_role(STATUS, 3) == "TARGET_STATUS"
    assert distinct_by_role(ACTION, STATUS, 2)
    hook = _slide("Агент OpenAI сам заходил на сайты ведомств США", "Подробности раскрыли 25 сентября, эпизоды были летом.")
    findings = viral_copy_findings([hook, ACTION, STATUS], EVIDENCE)
    assert not [f for f in findings if "slides 2 and 3" in f and ("same point" in f or "thesis" in f)]
    verdict = apply_role_guard(parse_verdict({"same_thesis_pairs": [{"slides": [2, 3], "reason": "both about access"}],
                                              "caption_repeats_slides": {"present": False, "reason": ""},
                                              "caption_aphorism": {"present": False, "sentence": "", "reason": ""},
                                              "unsupported_interpretation": []}, 3), [hook, ACTION, STATUS])
    assert verdict.same_thesis_pairs == [] and verdict.dropped_pairs[0]["roles"] == ["EVENT_ACTION", "TARGET_STATUS"]


def test_10_genuine_same_thesis_adjacent_slides_still_fail():
    a = _slide("Агент заходил на сайты ведомств", "Летом агент в лабораторных условиях заходил на сайты нескольких ведомств США.")
    b = _slide("Сайты ведомств — без команды", "Агент в лабораторных условиях заходил на сайты ведомств США без команды.")
    assert not distinct_by_role(a, b, 2)
    raw = {"same_thesis_pairs": [{"slides": [2, 3], "reason": "the same visit"}], "caption_repeats_slides": {"present": False, "reason": ""},
           "caption_aphorism": {"present": False, "sentence": "", "reason": ""}, "unsupported_interpretation": []}
    assert apply_role_guard(parse_verdict(raw, 3), [ACTION, a, b]).same_thesis_pairs == [(2, 3, "the same visit")]
    # and a judge that gave both slides the SAME role keeps its pair even when the local roles differ
    raw_same = {**raw, "slide_roles": ["HOOK", "TARGET_STATUS", "TARGET_STATUS"]}
    assert apply_role_guard(parse_verdict(raw_same, 3), [ACTION, ACTION, STATUS]).same_thesis_pairs


# --- 11-15: correction non-regression ----------------------------------------------------------------------------------------------
FIRST = [_slide("Агент OpenAI сам заходил на сайты ведомств США", "Эпизоды были летом, подробности раскрыли 25 сентября."),
         STATUS, _slide("С Министерством образования ясности нет", "Эпизод всё ещё расследуется.")]
BASE = factual_invariants(FIRST, "", LEDGER, EVIDENCE)


def test_11_a_correction_cannot_weaken_the_chronology():
    corrected = [_slide("Агент OpenAI сам заходил на сайты ведомств США", "Он действовал без активных инструкций."), *FIRST[1:]]
    assert any("chronology" in f for f in non_regression_findings(BASE, corrected, "", LEDGER, EVIDENCE))


def test_12_a_correction_cannot_blur_the_target_status():
    corrected = [FIRST[0], _slide("Без команды — но с доступом к трём ведомствам", "OpenAI подтвердила доступ к Commerce и SEC.")]
    found = non_regression_findings(BASE, corrected, "", LEDGER, EVIDENCE)
    assert any("introduced a target-status violation" in f and "education" in f for f in found)


def test_13_a_correction_cannot_strengthen_the_action_verb():
    corrected = [_slide("Агент OpenAI сам проник на сайты ведомств США", "Эпизоды были летом, подробности раскрыли 25 сентября."), *FIRST[1:]]
    assert any("strengthened the action verb" in f for f in non_regression_findings(BASE, corrected, "", LEDGER, EVIDENCE))


def test_14_the_canary_correction_with_a_new_factual_violation_is_rejected_on_the_real_path():
    import json

    first, corrected = replay._output("03_director.json"), replay._output("05_director.json")
    evidence = list(replay.director_input().allowed_evidence)
    baseline = factual_invariants(first["slides"], first["final_caption"], build_status_ledger(evidence), evidence)
    saved = json.loads((replay.CANARY / "director_semantic_judge_correction.json").read_text(encoding="utf-8"))["verdict"]
    result = asyncio.run(replay.real_path(corrected, replay.director_input(correction_note="x", invariants=baseline), saved))
    assert result["result"] == "TargetStatusSafetyError" and result["hard"]
    assert "correction introduced a target-status violation" in result["detail"] and "трём ведомствам" in result["detail"]


def test_15_the_original_version_stays_available_for_diagnosis_and_the_gate_is_hard_and_before_the_judge(monkeypatch):
    import json

    import services.instagram_creative_director as cd

    first = replay._output("03_director.json")
    saved = json.loads((replay.CANARY / "director_semantic_judge_initial.json").read_text(encoding="utf-8"))["verdict"]
    captured: list = []
    monkeypatch.setattr(cd, "_emit_diagnostic", lambda event, payload: captured.append((event, payload)))
    result = asyncio.run(replay.real_path(first, replay.director_input(), saved))
    assert result["result"] == "TargetStatusSafetyError" and result["hard"]  # never laundered into the editorial correction
    events = [e for e, _p in captured]
    assert events[0] == "raw_output_initial" and captured[0][1]["structured_output"]["slides"] == first["slides"]
    assert "semantic_judge_initial" not in events  # the judge never runs after a hard failure


def test_the_correction_note_and_the_director_prompt_carry_the_status_contract():
    note = EditorialCorrectionRequired(["slide 2: x"], factual_contract=["education: UNDER_INVESTIGATION (E1, E3)"]).correction_note
    for phrase in ("preserve every target's status exactly", "never merge a confirmed and a not-confirmed target", "never strengthen a verb",
                   "never remove the chronology", "change ONLY what the findings name", "education: UNDER_INVESTIGATION"):
        assert phrase in note
    assert "FACTUAL STATUS LEDGER" in ledger_note(LEDGER) and "трём ведомствам" in ledger_note(LEDGER)
    from services.instagram_creative_director import _build_user_text

    prompt = _build_user_text(replay.director_input(), evidence_handles=True)
    assert "FACTUAL STATUS LEDGER" in prompt and "education: UNDER_INVESTIGATION" in prompt


# --- 16: abstract questions --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("copy,body", [("Кто должен подтверждать действие агента?", "Человек, агент или зависит от ситуации."),
                                       ("Где заканчивается автоматизация?", "Кто должен контролировать действия агента — и когда?")])
def test_16_an_abstract_question_or_poll_the_evidence_never_raises_still_fails(copy, body):
    assert abstract_question_findings([_slide(copy, body)], "", EVIDENCE)
    assert abstract_question_findings([_slide("Что с Министерством образования?", "Эпизод всё ещё расследуется.")], "", EVIDENCE) == []
