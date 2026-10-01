"""Founder task 2026-09-30: the ONE correction must not keep a slide only to preserve the count. A slide that restates earlier slides - in any
words, next to them or not - is a finding on the first version and is DROPPED from the corrected version; the carousel may shrink to the viral
floor. Offline, no provider call: the saved natural acceptance run (Claude Sonnet 5.5, HEAD 4046376) replays through the real validation path
with each round's SAVED judge verdict."""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
from pathlib import Path

import pytest

from services.instagram_viral_format import (
    VIRAL_MIN_SLIDES,
    caption_findings,
    drop_padding_slides,
    restates_earlier_slides,
    viral_copy_findings,
)

SAVED = json.loads((Path(__file__).parent / "fixtures/instagram_sonnet55_acceptance/saved_run.json").read_text(encoding="utf-8"))


def slide(head: str, body: str, role: str = "evidence") -> dict:
    return {"slide_copy": head, "slide_body": body, "role": role}


# a story with nothing in common with the acceptance run: the rule is general, never keyed to a company, a slide number or a phrase
BASE = [
    slide("Лиссабон запретил прокат самокатов", "Запрет начнёт действовать с 1 марта во всех районах города.", "hook"),
    slide("Причина — аварии", "За год в городе произошло 412 аварий с участием самокатов."),
    slide("Операторы против", "Компании Lime и Bolt заявили, что оспорят решение в суде."),
    slide("Самокаты вывезут", "Операторы должны убрать все машины с улиц до конца февраля.", "story"),
]
RESTATEMENT = slide("Самокатов в городе больше не будет", "Прокат самокатов в Лиссабоне запрещён во всех районах.", "takeaway")
SUMMARY = slide("Итог: запрет и суд", "Прокат самокатов запрещён, а операторы собираются оспорить решение.", "takeaway")
NEW_NUMBER = slide("Штраф — 500 евро", "Нарушителям запрета грозит штраф 500 евро.", "takeaway")
NEW_PROPOSITION = slide("Жители поддержали решение", "Большинство жителей на городском опросе высказались за такое ограничение.", "takeaway")


# A. two differently worded slides with the same informational thesis -> the later one is blocked / removed
def test_a_same_thesis_in_other_words_is_found_even_when_not_adjacent():
    assert restates_earlier_slides(RESTATEMENT, BASE)  # it echoes slide 1, three slides away
    findings = viral_copy_findings([*BASE, RESTATEMENT], [])
    assert any(f.startswith("slide 5 restates earlier slides") for f in findings)


def test_a_quantifier_equivalents_state_one_proposition():
    earlier = [slide("Приложение обновили", "Разработчики выпустили новую версию приложения.", "hook"),
               slide("Это не одна функция", "Появились заметки, календарь и общий доступ к файлам.")]
    echo = slide("Функций стало больше", "В приложении теперь несколько новых функций.", "takeaway")
    assert restates_earlier_slides(echo, earlier)


def test_a_restatement_is_dropped_from_the_corrected_version_and_the_carousel_shrinks():
    kept, dropped = drop_padding_slides([*BASE, RESTATEMENT])
    assert [s["slide_copy"] for s in kept] == [s["slide_copy"] for s in BASE]
    assert [d["index"] for d in dropped] == [5]


# B. a correction that removes a duplicate and leaves 4 distinct slides -> 4 slides is valid
def test_b_four_distinct_slides_stay_four_and_raise_no_padding_finding():
    kept, dropped = drop_padding_slides(BASE)
    assert kept == BASE and dropped == []
    assert not [f for f in viral_copy_findings(BASE, []) if "restates earlier slides" in f]


def test_b_the_slide_that_now_ends_the_carousel_takes_the_conclusion_role_with_its_copy_untouched():
    kept, dropped = drop_padding_slides([*BASE, RESTATEMENT])
    assert kept[-1]["role"] == "takeaway"
    assert (kept[-1]["slide_copy"], kept[-1]["slide_body"]) == (BASE[-1]["slide_copy"], BASE[-1]["slide_body"])
    assert dropped[0]["role_moved_to"] == {"slide": 4, "role": "takeaway"}


def test_b_nothing_is_dropped_below_the_viral_floor_and_the_hook_is_never_dropped():
    four = [*BASE[:3], RESTATEMENT]
    kept, dropped = drop_padding_slides(four)
    assert len(kept) == VIRAL_MIN_SLIDES and dropped == []  # the finding stays and stops the post, as before this change
    assert [f for f in viral_copy_findings(four, []) if f.startswith("slide 4 restates earlier slides")]
    echo_hook = [BASE[0], slide("Прокат самокатов запретили", "Лиссабон запретил самокаты во всех районах с 1 марта.", "hook"), *BASE[1:]]
    kept, _ = drop_padding_slides(echo_hook)
    assert kept[0] is echo_hook[0]


# C. a fifth slide with a genuinely new grounded fact -> may remain
@pytest.mark.parametrize("fifth", [NEW_NUMBER, NEW_PROPOSITION], ids=["new_number", "new_proposition"])
def test_c_a_genuinely_new_fifth_slide_is_kept(fifth):
    assert restates_earlier_slides(fifth, BASE) is None
    kept, dropped = drop_padding_slides([*BASE, fifth])
    assert len(kept) == 5 and dropped == []


# D. a rephrased summary of earlier slides does not count as new information
def test_d_a_rephrased_summary_of_several_earlier_slides_is_not_new():
    assert restates_earlier_slides(SUMMARY, BASE)  # slide 1's ban + slide 3's court challenge, reworded
    kept, dropped = drop_padding_slides([*BASE, SUMMARY])
    assert len(kept) == 4 and dropped[0]["index"] == 5


# E. caption repetition rules are unchanged
def test_e_caption_rules_intact():
    listing = "Lime, Bolt, Tier, Dott."
    assert caption_findings(listing, BASE)  # a bare list of names is still a caption finding
    clean = "Город ограничивает прокат после роста аварий, а операторы готовятся к суду."
    assert caption_findings(clean, BASE) == []
    kept, _ = drop_padding_slides([*BASE, RESTATEMENT])
    assert caption_findings(listing, kept) == caption_findings(listing, BASE)  # dropping a slide never relaxes the caption check


# the saved natural acceptance run, through the real validation path - zero provider calls
def _director_input(*, note: str = "", invariants: dict | None = None):
    from services.instagram_creative_director import CreativeDirectorInput

    known = {f.name for f in dataclasses.fields(CreativeDirectorInput)}
    fields = {k: v for k, v in SAVED["director_input"].items() if k in known}
    return CreativeDirectorInput(**{**fields, "media_first": True, "generated_media_available": True, "planned_format": "TREND",
                                    "available_media_subjects": ("source",), "unsuitable_media_subjects": ("source",),
                                    "contract_retry_note": note, "factual_invariants": dict(invariants or {})})


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
    run = cd._validate_viral_carousel(None, None, copy.deepcopy(raw), None, director_input=di, archetype=raw.get("content_archetype"))
    return run, judged, diagnostics


def test_saved_run_first_version_names_the_padding_slide_for_the_one_correction(monkeypatch):
    from services.instagram_viral_format import EditorialCorrectionRequired

    run, judged, _ = _real_path(monkeypatch, SAVED["initial_output"], _director_input(), SAVED["initial_verdict"])
    with pytest.raises(EditorialCorrectionRequired) as exc:
        asyncio.run(run)
    assert any(f.startswith("slide 5 restates earlier slides") for f in exc.value.findings)
    assert judged == [5]  # the first version is not pruned: the one correction decides how to fix it


def test_saved_run_refilled_slide_does_not_survive_the_correction_and_the_carousel_ends_at_four(monkeypatch):
    from services.instagram_viral_format import EditorialCorrectionRequired

    raw = SAVED["corrected_output"]
    assert len(raw["slides"]) == 5 and raw["slides"][4]["slide_copy"] == "Sonnet 5.5 — обновление середины"
    run, judged, diagnostics = _real_path(monkeypatch, raw, _director_input(note="EDITORIAL CORRECTION (replay)",
                                                                             invariants=SAVED["correction_baseline_invariants"]),
                                          SAVED["correction_verdict"])
    # founder task 2026-10-01: this saved carousel also states a false chronology - its hook 'Sonnet 5.5 заменит Sonnet 5 с июня' turns the
    # evidence's 'Sonnet 5 from June' into a June rollout (services.instagram_fact_binding). The padding result is unchanged; the post now
    # stops for that factual error, and for nothing else
    with pytest.raises(EditorialCorrectionRequired) as exc:
        asyncio.run(run)
    assert exc.value.findings and all(f.startswith("fact binding") and "sonnet 5" in f for f in exc.value.findings)
    slides = exc.value.previous_output["slides"]  # the version that was judged: the padding already dropped
    assert len(slides) == 4
    assert [s["slide_copy"] for s in slides] == [s["slide_copy"] for s in raw["slides"][:4]]  # no copy written or changed
    assert [s["slide_body"] for s in slides] == [s["slide_body"] for s in raw["slides"][:4]]
    assert slides[-1]["role"] == "takeaway"
    assert diagnostics["correction_padding_dropped"]["dropped"][0]["index"] == 5
    assert judged == [4]  # the one post-correction judge round, on the shorter carousel - no second correction, no model call
