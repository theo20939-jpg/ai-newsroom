"""Fact binding + judge stability (founder task 2026-10-01, after the controlled Sonnet 5.5 acceptance 3f213cb).

Two supported phrases lost their relation: 'replacing Sonnet 5 from June with Sonnet 5.5' became 'с июня Sonnet 5.5 заменит Sonnet 5', and
'cybersecurity capabilities comparable to Opus 5' became 'защита ..., сопоставимая с Opus 5'. And the final judge flagged a caption sentence
that was byte-identical to the one the first judge had passed. Offline, no provider call: the saved run replays through the real validation
path with each round's SAVED verdict; the general cases below name no product of the saved story.
"""
from __future__ import annotations

import asyncio
import copy
import difflib
import json
from pathlib import Path

import pytest

from services.instagram_fact_binding import fact_binding_findings
from services.instagram_viral_editorial_judge import JudgeVerdict, judged_version, parse_verdict, split_contradicting

SAVED = json.loads((Path(__file__).parent / "fixtures/instagram_sonnet55_fact_binding/saved_run.json").read_text(encoding="utf-8"))
EVIDENCE = SAVED["director_facts"]


def slide(head: str, body: str = "", role: str = "evidence") -> dict:
    return {"slide_copy": head, "slide_body": body, "role": role}


# --- the saved run --------------------------------------------------------------------------------------------------------------------

def test_saved_run_both_misbindings_are_found_in_both_director_versions():
    for key in ("initial_output", "corrected_output"):
        out = SAVED[key]
        findings = fact_binding_findings(out["slides"], EVIDENCE, caption=out["final_caption"])
        assert any(f.startswith("fact binding (slide 2 body)") and "sonnet 5" in f for f in findings)
        assert any(f.startswith("fact binding (caption)") and "time of the event" in f for f in findings)
        assert any(f.startswith("fact binding (slide 6 body)") and "compares safeguard" in f and "capability" in f for f in findings)
        assert len(findings) == 3


def test_the_saved_judge_requests_differ_only_in_the_two_translated_words():
    a, b = ("\n".join(SAVED["judge_requests"][k]).splitlines() for k in ("initial", "correction"))
    changed = [d for d in difflib.unified_diff(a, b, lineterm="", n=0) if d[:1] in "+-" and d[:3] not in ("+++", "---")]
    assert len(changed) == 4 and all(line[1:].lstrip().startswith("body:") for line in changed)
    assert [line for line in a if line.startswith("CAPTION:")] == [line for line in b if line.startswith("CAPTION:")]


def test_the_saved_final_verdict_contradicts_the_first_on_unchanged_text():
    first_verdict = parse_verdict(SAVED["initial_verdict"], 6)
    first = judged_version(SAVED["initial_output"]["slides"], SAVED["initial_output"]["final_caption"], first_verdict)
    final = parse_verdict(SAVED["correction_verdict"], 6)
    kept, contradicting = split_contradicting(final, first, SAVED["corrected_output"]["slides"], SAVED["corrected_output"]["final_caption"])
    assert not first_verdict.unsupported_interpretation  # judge 1: clean on the same caption
    assert [c["category"] for c in contradicting] == ["unsupported_interpretation"] and contradicting[0]["where"] == "caption"
    assert kept.findings() == []


def _director_input(*, note: str = "", invariants: dict | None = None, first: dict | None = None):
    from services.instagram_creative_director import CreativeDirectorInput
    from services.instagram_viral_format import VIRAL_CAROUSEL_NOTE

    return CreativeDirectorInput(
        objective="shares", format="carousel", opportunity_summary=SAVED["premise"], allowed_evidence=list(EVIDENCE), locale="ru",
        external_news_entities_allowed=True, media_first=True, generated_media_available=True, planned_format="TREND",
        planned_archetype="trend_generative", available_media_subjects=("source",), unsuitable_media_subjects=("source",),
        viral_carousel_note=VIRAL_CAROUSEL_NOTE, contract_retry_note=note, factual_invariants=dict(invariants or {}),
        first_judgement=dict(first or {}))


def _real_path(monkeypatch, raw: dict, di, verdict: dict):
    import services.instagram_creative_director as cd
    import services.instagram_viral_editorial_judge as judge_mod

    judged: list[int] = []
    diagnostics: dict = {}

    async def saved(_gateway, _repo, *, slides, caption, allowed_evidence):
        judged.append(len(slides))
        return judge_mod.apply_role_guard(judge_mod.parse_verdict(verdict, len(slides)), slides)

    monkeypatch.setattr(judge_mod, "judge_viral_copy", saved)
    monkeypatch.setattr(cd, "_emit_diagnostic", lambda name, payload: diagnostics.__setitem__(name, payload))
    return cd._validate_viral_carousel(None, None, copy.deepcopy(raw), None, director_input=di,
                                       archetype=raw.get("content_archetype")), judged, diagnostics


def test_saved_run_the_one_correction_receives_every_visible_problem(monkeypatch):
    from services.instagram_viral_format import EditorialCorrectionRequired

    run, judged, _ = _real_path(monkeypatch, SAVED["initial_output"], _director_input(), SAVED["initial_verdict"])
    with pytest.raises(EditorialCorrectionRequired) as exc:
        asyncio.run(run)
    findings = exc.value.findings
    assert any("medium-sized" in f for f in findings)  # the one problem the saved correction was told about
    assert sum(f.startswith("fact binding") for f in findings) == 3  # ... and now the misbindings, in the same one correction
    assert exc.value.first_judgement and judged == [6]


def test_saved_run_the_corrected_version_stops_for_the_misbindings_not_the_contradicting_verdict(monkeypatch):
    from services.instagram_viral_format import EditorialCorrectionRequired

    run1, _, _ = _real_path(monkeypatch, SAVED["initial_output"], _director_input(), SAVED["initial_verdict"])
    with pytest.raises(EditorialCorrectionRequired) as first:
        asyncio.run(run1)
    run2, judged, diagnostics = _real_path(
        monkeypatch, SAVED["corrected_output"],
        _director_input(note="EDITORIAL CORRECTION (replay)", invariants=first.value.factual_invariants, first=first.value.first_judgement),
        SAVED["correction_verdict"])
    with pytest.raises(EditorialCorrectionRequired) as final:
        asyncio.run(run2)
    assert final.value.findings and all(f.startswith("fact binding") for f in final.value.findings)
    assert final.value.first_judgement is None  # the correction round never hands on another judgement: nothing follows it
    record = diagnostics["semantic_judge_correction"]
    assert record["semantic_findings"] == [] and len(record["contradicting_unchanged_text"]) == 1
    assert judged == [6]  # one judge call in this round - no extra call, no second correction


# --- general cases: dates -------------------------------------------------------------------------------------------------------------

DEVICE_EVIDENCE = [
    "Vendor is replacing the Nimbus 7 from March with the Nimbus 8 as its main phone.",
    "The Nimbus 8 has battery life comparable to Orbit 3 and a camera similar to those used in its flagship.",
    "It charges 40% faster and its display is 20% brighter than the Nimbus 7.",
]


@pytest.mark.parametrize("body", [
    "С марта Nimbus 8 заменит Nimbus 7.",  # the old model's month became the new one's rollout
    "В марте вышел Nimbus 8.",
    "Мартовский Nimbus 8 уже в продаже.",  # the month moved to another product
])
def test_a_date_moved_off_the_product_it_describes_is_found(body):
    assert any(f.startswith("fact binding") for f in fact_binding_findings([slide("Новый телефон", body)], DEVICE_EVIDENCE))


@pytest.mark.parametrize("body", [
    "Nimbus 8 заменяет мартовский Nimbus 7.",
    "Он приходит на смену Nimbus 7, вышедшему в марте.",
    "Nimbus 8 заменяет Nimbus 7.",
])
def test_a_date_kept_on_its_product_passes(body):
    assert fact_binding_findings([slide("Новый телефон", body)], DEVICE_EVIDENCE) == []


def test_only_whole_month_words_count():
    evidence = ["Vendor is replacing the Nimbus 7 from March with the Nimbus 8.", "The Nimbus 5 from May stays on sale."]
    assert fact_binding_findings([slide("Смартфон", "Новый смартфон Nimbus 8 светит как маяк.")], evidence) == []  # 'март', 'мая' inside words
    assert any(f.startswith("fact binding") for f in fact_binding_findings([slide("Майская новинка", "Майский Nimbus 8 уже здесь.")],
                                                                          evidence))


def test_a_month_the_evidence_uses_as_event_time_is_not_restricted():
    evidence = ["The update arrives in June for every supported phone.", "Vendor also sells the Nimbus 7 from March."]
    assert fact_binding_findings([slide("Обновление", "В июне обновление получат все поддерживаемые телефоны.")], evidence) == []


# --- general cases: comparisons and numbers -----------------------------------------------------------------------------------------------

def test_a_comparison_moved_to_another_property_is_found():
    found = fact_binding_findings([slide("Камера", "Камера Nimbus 8 сопоставима с Orbit 3.")], DEVICE_EVIDENCE)
    assert any("compares camera with Orbit 3" in f and "battery" in f for f in found)


@pytest.mark.parametrize("body", ["Автономность Nimbus 8 сопоставима с Orbit 3.", "Батарея — на уровне Orbit 3."])
def test_a_comparison_on_its_own_property_passes(body):
    assert fact_binding_findings([slide("Батарея", body)], DEVICE_EVIDENCE) == []


def test_a_number_moved_to_another_metric_is_found_and_its_own_metric_passes():
    assert any("40 is given to display" in f for f in fact_binding_findings([slide("Экран", "Экран на 40% ярче.")], DEVICE_EVIDENCE))
    assert fact_binding_findings([slide("Зарядка", "Заряжается на 40% быстрее, экран на 20% ярче.")], DEVICE_EVIDENCE) == []


def test_unrecognised_relations_stay_silent():
    evidence = ["The company says the rollout was comparable to Orbit 3 in scale.", "OpenAI disclosed the activity on September 25."]
    copy_text = [slide("Хронология", "Летом агенты заходили на сайты, а 25 сентября OpenAI рассказала об этом."),
                 slide("Масштаб", "Запуск сопоставим с Orbit 3.")]
    assert fact_binding_findings(copy_text, evidence) == []


# --- judge stability: what stays a finding ------------------------------------------------------------------------------------------------

def _verdict(**kw) -> JudgeVerdict:
    raw = {"same_thesis_pairs": [], "caption_repeats_slides": {"present": False, "reason": ""},
           "caption_aphorism": {"present": False, "sentence": "", "reason": ""}, "unsupported_interpretation": []}
    raw.update(kw)
    return parse_verdict(raw, 3)


SLIDES = [slide("Хук", "Факт один."), slide("Два", "Факт два."), slide("Три", "Факт три.")]
CAPTION = "Первое предложение. Главное здесь — факт два."


def test_a_finding_on_changed_text_stays_blocking():
    first = judged_version(SLIDES, CAPTION, _verdict())
    changed = "Первое предложение. Главное здесь — совсем другое."
    final = _verdict(unsupported_interpretation=[{"where": "caption", "sentence": "Главное здесь — совсем другое.", "reason": "r"}])
    kept, contradicting = split_contradicting(final, first, SLIDES, changed)
    assert contradicting == [] and len(kept.findings()) == 1


def test_a_finding_the_first_judge_also_made_stays_blocking():
    item = {"where": "caption", "sentence": "Главное здесь — факт два.", "reason": "r"}
    first = judged_version(SLIDES, CAPTION, _verdict(unsupported_interpretation=[item]))
    kept, contradicting = split_contradicting(_verdict(unsupported_interpretation=[item]), first, SLIDES, CAPTION)
    assert contradicting == [] and len(kept.findings()) == 1


def test_a_same_thesis_pair_on_moved_or_changed_slides_stays_blocking_and_on_unchanged_slides_is_contradicting():
    first = judged_version(SLIDES, CAPTION, _verdict())
    pair = _verdict(same_thesis_pairs=[{"slides": [2, 3], "reason": "r"}])
    moved = [SLIDES[0], slide("Два", "Факт два, иначе."), SLIDES[2]]
    assert split_contradicting(pair, first, moved, CAPTION)[1] == []
    assert [c["category"] for c in split_contradicting(pair, first, SLIDES, CAPTION)[1]] == ["same_thesis_pair"]


def test_the_first_round_has_nothing_to_contradict():
    final = _verdict(unsupported_interpretation=[{"where": "caption", "sentence": "Главное здесь — факт два.", "reason": "r"}])
    kept, contradicting = split_contradicting(final, {}, SLIDES, CAPTION)
    assert contradicting == [] and kept == final
