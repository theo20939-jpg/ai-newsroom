"""ONE-CORRECTION CONTRACT + EFFECTIVE SEVERITY (founder task 2026-09-28, after the controlled completion of canary 10).

Canary 10's single correction fixed the judge's finding but rewrote slide 4's body into a restatement of its headline; body_repeats_headline
is a _VIRAL_BLOCKING code (founder: stays blocking), so the post stopped - and the finding was printed '[advisory]' (the critic's generic
label), which misled the reports. Now: viral-blocking critic codes are reported as '[blocking]' in the viral layer, and the one correction
receives the viral copy rules that make a corrected version terminal."""
from __future__ import annotations

import pytest

from services.instagram_editorial_critic import ADVISORY, critique
from services.instagram_viral_format import _VIRAL_BLOCKING, VIRAL_COPY_CONTRACT, EditorialCorrectionRequired, viral_copy_findings

HEAD = "Фон — агенты OpenAI проникли на сайты правительства"
REPEAT = "История с Anthropic появилась после сообщения о том, что агенты OpenAI проникли на австралийские правительственные сайты."


def _slides(body4: str) -> list[dict]:
    return [{"role": "story", "slide_copy": f"Заголовок {i}", "slide_body": f"Отдельный факт номер {i} с собственными словами."} for i in range(3)] + [
        {"role": "story", "slide_copy": HEAD, "slide_body": body4}]


def test_viral_blocking_membership_is_unchanged():
    assert _VIRAL_BLOCKING == frozenset({"body_repeats_headline", "body_restates_headline_claim", "card_adds_no_new_information", "label_headline"})


def test_the_canary10_repeat_is_reported_as_blocking_in_the_viral_layer():
    findings = [f for f in viral_copy_findings(_slides(REPEAT), [], include_quotes=False) if "body_repeats_headline" in f]
    assert findings and findings[0].startswith("[blocking] body_repeats_headline (card 4)")
    assert not any(f.startswith("[advisory] body_repeats_headline") for f in viral_copy_findings(_slides(REPEAT), [], include_quotes=False))


def test_the_critic_keeps_its_own_context_sensitive_label_outside_the_viral_layer():
    own = [f for f in critique(_slides(REPEAT), []) if f.code == "body_repeats_headline"]
    assert own and own[0].severity == ADVISORY  # non-viral consumers of the critic are unchanged


@pytest.mark.parametrize("rule", [
    "every slide's body adds information its headline does not already state",
    "never restate, paraphrase or expand the headline's own claim in the body",
    "no two slides make the same point",
    "the caption adds context and never repeats the slides' sentences or lists",
    "no interpretation, cause or motive the evidence does not state",
    "keep every supported fact, target status and chronology exactly",
    "keep every hook within the display limit",
])
def test_every_correction_note_states_the_viral_rules_that_make_a_correction_terminal(rule):
    note = EditorialCorrectionRequired(["semantic review: unsupported interpretation in caption (x)"]).correction_note
    assert "VIRAL COPY CONTRACT" in note and rule in note


def test_the_contract_travels_with_the_structural_block_and_the_previous_version():
    note = EditorialCorrectionRequired(["x"], previous_output={"slides": [{"slide_copy": HEAD, "slide_body": "b", "story_anchor": "a"}]}).correction_note
    assert note.index("VIRAL COPY CONTRACT") < note.index("STRUCTURAL PRESERVATION") < note.index("PREVIOUS VERSION (JSON):")
    assert VIRAL_COPY_CONTRACT in note


def test_the_contract_adds_no_second_correction():
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "services/instagram_automatic_trigger.py").read_text(encoding="utf-8")
    block = source[source.index("except _EditorialRetry as retry:"):source.index("single, carousel, reel = creative_outcome")]
    assert block.count("await regenerator(") == 1
