"""THESIS-LEVEL SLIDE UNIQUENESS + CAPTION COPY (founder task 2026-09-26): every carousel slide adds a new idea, not more specific words
for the previous idea; the caption is audience-facing copy, never a re-list of the slides. Zero provider calls."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from services.instagram_viral_format import VIRAL_CAROUSEL_NOTE, caption_findings, lifted_wording, thesis_relation, viral_copy_findings

ROOT = Path(__file__).resolve().parent.parent


def _replay():
    spec = importlib.util.spec_from_file_location("thesis_replay", ROOT / "scripts/_instagram_thesis_uniqueness_replay.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _s(head: str, body: str, ref: str = "E1") -> dict:
    return {"role": "beat", "slide_copy": head, "slide_body": body, "source_evidence": ref}


# --- the exact final corrected GTA output ----------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def gta():
    mod = _replay()
    raw, director_input = mod.final_gta()
    return mod, raw, director_input


def test_slide_3_only_specifies_slide_2_and_the_explanation_says_so(gta):
    _mod, raw, director_input = gta
    findings = viral_copy_findings(raw["slides"], list(director_input.allowed_evidence), caption=raw.get("final_caption") or "")
    beat = next(f for f in findings if f.startswith("slides 2 and 3:"))
    assert "only specifies the first slide's claim" in beat and "adds specificity, not a new beat" in beat
    assert "merge them into one slide, then use the freed slide for another distinct grounded fact or make the carousel shorter" in beat


def test_the_caption_list_that_repeats_the_slides_and_the_teaser_label_are_surfaced(gta):
    _mod, raw, director_input = gta
    findings = viral_copy_findings(raw["slides"], list(director_input.allowed_evidence), caption=raw.get("final_caption") or "")
    assert any(f.startswith("caption sentence is a list of names") and f.endswith("it repeats the slides' list") for f in findings)
    assert any("label_headline" in f and "Вот что приехало в игру" in f and "instead of a teaser" in f for f in findings)
    assert any("copies the source's wording verbatim" in f and "глобальная техническая модификация" in f for f in findings)


def test_the_final_gta_output_is_one_structured_correction_not_a_terminal_error(gta):
    mod, raw, director_input = gta
    from scripts._instagram_director_correction_replay import validate

    result = validate(copy.deepcopy(raw), director_input)
    assert result["result"].startswith("EditorialCorrectionRequired")
    assert "your one correction attempt" in result["correction_note"]


@pytest.mark.parametrize("name", ["deepseek", "hamster"])
def test_the_accepted_golden_carousels_still_pass(name):
    import scripts._instagram_viral_copy_polish as polish
    from scripts._instagram_director_correction_replay import validate

    polished = json.loads((ROOT / "artifacts/instagram_feed_product/viral_copy_polish_20260926" / name / "polished_director_output.json")
                          .read_text(encoding="utf-8"))
    assert validate(polished, polish._director_input(name, polish.STORIES[name])) == {"result": "PASS"}


# --- the rule reads meaning, never evidence ids -----------------------------------------------------------------------------------------

def test_two_different_facts_from_the_same_evidence_item_pass():
    mod = _replay()
    assert viral_copy_findings(copy.deepcopy(mod.SAME_ITEM_DIFFERENT_FACTS), mod.FIXTURE_EVIDENCE) == []


def test_the_same_thesis_from_different_evidence_ids_fails():
    mod = _replay()
    findings = viral_copy_findings(copy.deepcopy(mod.DIFFERENT_IDS_SAME_THESIS), mod.FIXTURE_EVIDENCE)
    assert any(f.startswith("slides 1 and 2: the second slide restates the first slide's thesis") for f in findings)


def test_a_generic_claim_then_its_enumeration_is_subsumption_but_a_consequence_is_a_new_beat():
    generic = _s("Приложение обновили", "Разработчики добавили поддержку новых форматов файлов.")
    listing = _s("Какие форматы", "Разработчики добавили поддержку форматов WebP, AVIF и HEIC.")
    assert "adds specificity, not a new beat" in (thesis_relation(generic, listing, earlier_slides=[generic]) or "")
    consequence = _s("Что это даёт", "Фотографии с iPhone теперь открываются без конвертации и весят вдвое меньше.")
    assert thesis_relation(listing, consequence, earlier_slides=[generic, listing]) is None


def test_the_rule_code_carries_no_story_specific_terms():
    assert not any(_replay().rule_code_terms().values())


# --- caption and source wording ----------------------------------------------------------------------------------------------------------

def test_a_caption_name_list_is_caught_but_names_inside_a_normal_sentence_are_not():
    slides = [_s("Новый мод", "Мод добавляет Nvidia DLSS 4 и AMD FSR 3.")]
    assert caption_findings("В наборе — Nvidia DLSS 4, AMD FSR 3, DLAA и HDR.", slides)
    assert caption_findings("Мод сделал один энтузиаст, и через неделю его скачали сорок тысяч человек.", slides) == []
    assert caption_findings("Старую игру теперь можно запускать с Nvidia DLSS 4, хотя сама студия её давно не обновляет.", slides) == []


def test_lifted_wording_needs_a_long_formal_run_not_names_or_a_short_plain_sentence():
    source = ["Для работы требуется глобальная техническая модификация Fusion Fix.", "Его нашёл сосед и вернул владельцу."]
    assert lifted_wording("Для работы мода требуется глобальная техническая модификация Fusion Fix.", source)
    assert lifted_wording("Его нашёл сосед и вернул владельцу.", source) is None
    assert lifted_wording("Мод добавляет Nvidia DLSS 4 AMD FSR 3 DLAA.", ["Nvidia DLSS 4 AMD FSR 3 DLAA и HDR"]) is None


def test_the_director_note_asks_for_one_beat_per_slide_and_a_caption_that_adds_context():
    assert "assign ONE distinct factual beat to each slide" in VIRAL_CAROUSEL_NOTE
    assert "merge them - a new detail is not a new beat" in VIRAL_CAROUSEL_NOTE
    assert "never re-lists the slides' names or features" in VIRAL_CAROUSEL_NOTE
