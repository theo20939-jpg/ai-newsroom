"""ONE SAFE FACTUAL REPAIR BEFORE A TERMINAL STATUS FAILURE (founder decision 2026-09-27, on top of the accepted target-status gate f30d508).

A first Director version whose only factual problem is REPAIRABLE status wording (the evidence supports actor, action and targets) gets the
ONE existing editorial correction; the corrected version must pass the SAME hard gate or the post stops - never a second correction, never
the judge before a factual PASS. Non-repairable failures (missing evidence, an unsupported target) stay terminal. No provider call."""
from __future__ import annotations

import asyncio
import copy
import json

import pytest

import scripts._instagram_viral_status_replay as replay
import services.instagram_creative_director as cd
from services.instagram_factual_status import (
    build_status_ledger,
    classify_repairability,
    factual_invariants,
    status_violations,
    unsupported_target_violations,
)
from services.instagram_viral_format import EditorialCorrectionRequired
from tests.test_instagram_director_correction import _Recorder, _run

EVIDENCE = [
    "Этим летом система в лабораторных условиях получила доступ к ресурсам Министерства образования, Министерства торговли и SEC.",
    "OpenAI подтвердила несанкционированный доступ к сайтам Министерства торговли и SEC.",
    "Расследование эпизода, связанного с ресурсом Министерства образования, продолжается.",
    "Агент пытался войти на сайт Министерства юстиции.",
    "CHRONOLOGY: disclosed 2026-09-25; behaviour this summer - the disclosure is new, the behaviour is not.",
]
LEDGER = build_status_ledger(EVIDENCE)
FIRST = replay._output("03_director.json")
CORRECTED = replay._output("05_director.json")
SAVED_INITIAL = json.loads((replay.CANARY / "director_semantic_judge_initial.json").read_text(encoding="utf-8"))["verdict"]
CANARY_EVIDENCE = list(replay.director_input().allowed_evidence)
BASELINE = factual_invariants(FIRST["slides"], FIRST["final_caption"], build_status_ledger(CANARY_EVIDENCE), CANARY_EVIDENCE)


def _classify(copy_text: str, body: str = "", evidence=None):
    evidence = EVIDENCE if evidence is None else evidence
    slides = [{"slide_copy": copy_text, "slide_body": body}]
    violations = [*status_violations(slides, "", build_status_ledger(evidence), evidence), *unsupported_target_violations(slides, "", evidence)]
    return violations, classify_repairability(violations, evidence)


def _correction_mode(raw: dict, verdict: dict | None = None) -> dict:
    return asyncio.run(replay.real_path(raw, replay.director_input(correction_note="EDITORIAL CORRECTION", invariants=BASELINE),
                                        verdict or replay.EMPTY_VERDICT))


# --- 1-6: repairable vs non-repairable ---------------------------------------------------------------------------------------------
def test_1_the_first_unsafe_grouped_claim_is_repairable():
    violations, verdict = _classify("Доступ без инструкций", "Агент получил доступ к ресурсам Министерства образования, Министерства торговли и SEC.")
    assert [v.kind for v in violations] == ["grouping"] and verdict.repairable
    result = asyncio.run(replay.real_path(FIRST, replay.director_input(), SAVED_INITIAL))  # the saved first canary output itself
    assert result["result"] == "EditorialCorrectionRequired" and result["factual_repair"]


def test_2_missing_evidence_is_not_repairable():
    violations, verdict = _classify("Агент получил доступ к ресурсам Министерства образования и SEC",
                                    evidence=["SOURCE MEDIA: none", "CHRONOLOGY: disclosed recently"])
    assert violations and not verdict.repairable and "missing evidence" in verdict.reason


def test_3_an_unsupported_target_is_not_repairable():
    violations, verdict = _classify("Агент также получил доступ к сайту FBI")
    assert any(v.kind == "unsupported_target" for v in violations) and not verdict.repairable


@pytest.mark.parametrize("copy_text,kind", [
    ("OpenAI подтвердила доступ к сайту Министерства образования", "promoted_confirmed"),  # 4: investigated -> confirmed
    ("Агент получил доступ к сайту Министерства юстиции", "attempt_completed"),  # 5: attempted -> completed
    ("Без команды — но с доступом к трём ведомствам", "count"),  # 6: unsafe target count
])
def test_4_5_6_status_promotions_and_unsafe_counts_are_repairable_once(copy_text, kind):
    violations, verdict = _classify(copy_text)
    assert kind in [v.kind for v in violations] and verdict.repairable


# --- 7-8: exactly one correction ---------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_7_and_8_one_factual_correction_is_allowed_and_a_second_is_impossible(monkeypatch):
    first = EditorialCorrectionRequired(["target-status violation in slide 2 body: ..."], factual_repair=["FAILING CLAIM in slide 2 body: ..."])
    recorder = _Recorder(first, cd.TargetStatusSafetyError(["target-status violation in slide 2 headline: still grouped"]))
    outcome = await _run(monkeypatch, recorder)
    assert len(recorder.inputs) == 2  # the original + ONE correction; the corrected version's failure is terminal, never a third call
    assert "FACTUAL STATUS REPAIR" in recorder.inputs[1].contract_retry_note and "FAILING CLAIM in slide 2 body" in recorder.inputs[1].contract_retry_note
    assert outcome.reason == "creative_director_failed:TargetStatusSafetyError"


def test_the_repair_contract_carries_every_required_field():
    result = asyncio.run(replay.real_path(FIRST, replay.director_input(), SAVED_INITIAL))
    repair = "\n".join(result["factual_repair"])
    for field in ("FAILING CLAIM in slide 2 body", "targets: education", "ledger: education=UNDER_INVESTIGATION (E4, E6)",
                  "evidence: E4, E6", "only with its investigation qualifier", "reason: grouped with commerce, sec",
                  "CHRONOLOGY INVARIANTS", "STRONGEST PERMITTED ACTION VERB: access"):
        assert field in repair, field
    note = result["correction_note"]
    for rule in ("Fix ONLY these claims plus the editorial findings", "do not introduce new facts", "do not merge targets",
                 "do not strengthen verbs", "do not remove the chronology", "do not paraphrase precise status language"):
        assert rule in note, rule


# --- 9-13: the corrected version re-passes the hard gate ------------------------------------------------------------------------------
def test_9_and_10_the_corrected_output_is_rechecked_and_a_remaining_violation_is_terminal():
    still_grouped = copy.deepcopy(FIRST)  # the correction left the grouped claim as it was
    result = _correction_mode(still_grouped)
    assert result["result"] == "TargetStatusSafetyError" and result["hard"] and not result["judge_called"]


def test_11_a_new_violation_after_the_correction_is_terminal():
    result = _correction_mode(CORRECTED)  # the saved canary correction: 'доступом к трём ведомствам'
    assert result["result"] == "TargetStatusSafetyError" and not result["judge_called"]
    assert "correction introduced a target-status violation" in result["detail"]


def test_12_the_chronology_cannot_regress():
    fixture = copy.deepcopy(replay.repair_fixtures(FIRST)["B_full_repair"])
    # every time marker gone: WHEN the behaviour happened is no longer said anywhere
    fixture["slides"][0]["slide_body"] = "Агент сам заходил на сайты американских ведомств."
    fixture["slides"][1]["slide_body"] = "В лабораторных условиях агент без активных инструкций заходил на сайты нескольких американских ведомств."
    fixture["final_caption"] = "OpenAI подтвердила доступ к сайтам Министерства торговли США и SEC; эпизод с Министерством образования расследуют."
    result = _correction_mode(fixture)
    assert result["result"] == "TargetStatusSafetyError" and "removed the chronology" in result["detail"] and not result["judge_called"]


def test_13_the_action_verb_cannot_strengthen():
    fixture = copy.deepcopy(replay.repair_fixtures(FIRST)["B_full_repair"])
    fixture["slides"][1]["slide_body"] = "Этим летом агент проник на сайты нескольких американских ведомств без активных инструкций."
    result = _correction_mode(fixture)
    assert result["result"] == "TargetStatusSafetyError" and not result["judge_called"]
    assert "stronger action than the evidence" in result["detail"] or "strengthened the action verb" in result["detail"]


# --- 14-15: a safe repair reaches the judge; an unsafe one never does ----------------------------------------------------------------
def test_14_a_safe_corrected_fixture_passes_factual_status_and_reaches_the_judge():
    fixtures = replay.repair_fixtures(FIRST)
    status_only = _correction_mode(fixtures["A_status_only"])
    assert status_only["judge_called"] and status_only["result"] == "EditorialCorrectionRequired"  # editorial findings remain - not factual
    assert "target-status" not in status_only["detail"]
    full = _correction_mode(fixtures["B_full_repair"])
    assert full["judge_called"] and full["result"] == "PASS"


def test_15_the_judge_is_never_called_on_a_corrected_output_that_still_fails_factual_status():
    for raw in (CORRECTED, FIRST):
        result = _correction_mode(raw, SAVED_INITIAL)
        assert result["result"] == "TargetStatusSafetyError" and not result["judge_called"]


def test_a_non_repairable_first_version_stays_terminal_without_a_correction():
    bad = copy.deepcopy(FIRST)
    bad["slides"][2]["slide_body"] = "OpenAI подтвердила доступ к сайтам Министерства торговли, SEC и FBI."  # FBI: not in the evidence
    result = asyncio.run(replay.real_path(bad, replay.director_input(), SAVED_INITIAL))
    assert result["result"] == "TargetStatusSafetyError" and "non-repairable" in result["detail"] and not result["judge_called"]
