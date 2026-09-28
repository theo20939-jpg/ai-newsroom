"""DISCLOSURE-CHRONOLOGY NON-REGRESSION (founder task 2026-09-28, after the tenth paid viral canary).

Canary 10 (a CURRENT_EVENT story) was stopped after its one correction because the first version said 'стало известно' ('the decision
became known') and the correction reworded it: the disclosure marker alone was enforced although the story has no split chronology. The
disclosure invariant is now BINDING only for PAST_EVENT_DISCLOSED_NOW (the evidence's CHRONOLOGY line, or the version dating the behaviour);
a correction may also not move the event time or the disclosure date."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.instagram_factual_status import chronology_state, factual_invariants, non_regression_findings

ROOT = Path(__file__).resolve().parent.parent
REPLAY = ROOT / "artifacts/instagram_feed_product/viral_nominated_canary10_20260928/offline_chronology/chronology_replay.json"
CHRONOLOGY_LINE = ("CHRONOLOGY: disclosed 2026-09-25; behaviour this summer; newly disclosed: commerce department - the disclosure is new, the "
                   "behaviour is not (this summer)")


def S(*texts: str) -> list[dict]:
    return [{"slide_copy": t, "slide_body": ""} for t in texts]


def inv(text: str, evidence: tuple[str, ...] = ()) -> dict:
    return factual_invariants(S(text), "", [], list(evidence))


def nonreg(first: str, corrected: str, evidence: tuple[str, ...] = ()) -> list[str]:
    return non_regression_findings(inv(first, evidence), S(corrected), "", [], list(evidence))


CURRENT = {
    "1 CURRENT_EVENT + стало известно": "Стало известно, что Anthropic не придёт на заседание Сената.",
    "2 appointment announced today": "Сегодня стало известно о назначении нового главы компании.",
    "3 decision reported today": "Компания сообщила о сегодняшнем решении не участвовать.",
    "4 future hearing announced today": "Сегодня сообщили, что заседание состоится завтра.",
    "5 company statement": "Представители компании подтвердили участие в заседании.",
}


@pytest.mark.parametrize("name", CURRENT)
def test_1_to_5_current_event_reporting_language_creates_no_binding_disclosure(name):
    got = inv(CURRENT[name])
    assert got["chronology"] == "CURRENT_EVENT" and got["disclosure"] is False, name


SPLIT = {
    "6 summer, disclosed 25 September": "Случилось летом. Раскрыли 25 сентября.",
    "7 breach earlier, revealed today": "Взлом произошёл ранее, компания раскрыла его сегодня.",
    "8 experiment earlier, published this week": "Исследование провели ранее, результаты опубликовали на этой неделе.",
    "9 underlying time + disclosure marker": "Атака произошла в июне; компания сообщила о ней сегодня.",
}


@pytest.mark.parametrize("name", SPLIT)
def test_6_to_9_a_split_chronology_creates_a_binding_disclosure(name):
    got = inv(SPLIT[name])
    assert got["chronology"] == "PAST_EVENT_DISCLOSED_NOW" and got["disclosure"] is True, name


def test_a_current_disclosure_chronology_line_alone_proves_the_split():
    assert chronology_state("OpenAI раскрыла это.", [CHRONOLOGY_LINE]) == "PAST_EVENT_DISCLOSED_NOW"
    assert inv("OpenAI раскрыла это.", (CHRONOLOGY_LINE,))["disclosure"] is True


@pytest.mark.parametrize("run", ["viral_nominated_canary6_20260927", "viral_nominated_canary7_20260927"])
def test_10_11_canaries_6_and_7_keep_their_chronology_protection(run):
    r = json.loads(REPLAY.read_text(encoding="utf-8"))[run]
    assert r["chronology_line"] and r["first_invariants"]["chronology"] == "PAST_EVENT_DISCLOSED_NOW"
    assert r["first_invariants"]["disclosure"] is True and r["first_invariants"]["underlying_time_values"] == ["summer"]
    assert r["probes"]["unchanged_first_output"] == []
    assert any("event/disclosure chronology" in f for f in r["probes"]["drop_disclosure"])
    assert any("changed WHEN the behaviour happened" in f for f in r["probes"]["move_event_time"])
    assert any("changed the disclosure date" in f for f in r["probes"]["move_disclosure_date"])


def test_12_removing_only_the_reporting_phrase_from_a_current_event_story_passes():
    assert nonreg("Стало известно, что Anthropic не придёт на заседание.", "Anthropic не придёт на заседание.") == []


def test_13_removing_the_disclosure_from_an_earlier_event_story_fails():
    assert any("event/disclosure chronology" in f for f in nonreg("Случилось летом. Раскрыли 25 сентября.", "Случилось летом."))
    assert any("event/disclosure chronology" in f for f in nonreg("OpenAI раскрыла это.", "OpenAI это сделала.", (CHRONOLOGY_LINE,)))
    collapsed = nonreg("Случилось летом. Раскрыли 25 сентября.", "Это произошло сегодня.")
    assert any("WHEN the behaviour happened" in f for f in collapsed) and any("event/disclosure" in f for f in collapsed)


def test_14_moving_the_event_time_fails():
    assert any("changed WHEN" in f for f in nonreg("Случилось летом. Раскрыли 25 сентября.", "Случилось весной. Раскрыли 25 сентября."))


def test_15_moving_the_disclosure_date_fails():
    assert any("changed the disclosure date" in f for f in nonreg("Случилось летом. Раскрыли 25 сентября.", "Случилось летом. Раскрыли 24 сентября."))


def test_a_faithful_correction_that_keeps_the_chronology_passes():
    assert nonreg("Случилось летом. Раскрыли 25 сентября.", "Это было этим летом, а раскрыли 25 сентября.") == []


def test_canary10_corrected_output_passes_non_regression_and_reaches_the_judge():
    r = json.loads(REPLAY.read_text(encoding="utf-8"))["canary10"]
    assert r["first_invariants"]["chronology"] == "CURRENT_EVENT" and r["first_invariants"]["disclosure"] is False
    assert r["first_invariants"]["disclosure_marker"] is True  # the phrase is still seen - it is just not a binding chronology
    assert r["corrected_non_regression"] == []
    assert r["corrected_real_path_correction_mode"]["result"] == "REACHED_SEMANTIC_JUDGE"
    d = r["corrected_deterministic"]
    assert d["media_first_contract"] == "PASS" and not d["quote_use"]["terminal"] and not d["quote_use"]["repairable"]
    assert d["named_person_risks"] == [] and d["status_violations"] == [] and max(d["hook_lengths"]) <= 60
    # corrected 2026-09-28: this is NOT advisory - body_repeats_headline is a viral-blocking code (the controlled completion of canary 10
    # stopped on it after a clean final judge); the chronology fix is proven by the empty non-regression above, not by this finding
    assert [f.split(" (")[0] for f in d["copy_thesis_findings"]] == ["[blocking] body_repeats_headline"]


def test_the_live_canary10_invariants_are_rebuilt_from_the_saved_outputs():
    import scripts._instagram_chronology_replay as replay
    from services.instagram_factual_status import build_status_ledger

    run = "viral_nominated_canary10_20260928"
    ev = replay.evidence(run, "02_director.json")
    first, corrected = replay.output(run, "director_raw_output_initial.json"), replay.output(run, "director_raw_output.json")
    base = factual_invariants(first["slides"], first["final_caption"], build_status_ledger(ev), ev)
    assert non_regression_findings(base, corrected["slides"], corrected["final_caption"], build_status_ledger(ev), ev) == []
