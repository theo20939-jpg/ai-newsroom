"""Phase 23.1M - Russian editorial naturalness test-first cases (docs/
phase23_1m_russian_editorial_naturalness_report.md, Part H).

V8.3 is schema-identical to V8.1/V8.2 (title/main_body/ending/quote) - only the prompt wording
changed. Naturalness/semantic-precision claims (calque avoidance, PR-filler removal, active voice,
etc.) are LLM-output-quality properties that cannot be deterministically unit-tested - those are
verified via the golden replay (docs/phase23_1m_russian_editorial_naturalness_report.md §6-9),
mirroring tests/test_copywriting_v82_cases.py's own established convention. This file makes the
required Part H cases explicit and traceable: prompt-content assertions for the language-quality
rules (cases 1-6, 8, 10), and reuse of the existing schema-generic presentation tests for the two
purely structural cases (7 - numbers are a Fact Safety/evidence concern, not reformatted by the
presentation layer; 9 - one main paragraph, already proven schema-generic in
tests/test_news_telegram_presentation_v81.py and re-confirmed for v8.2's identical schema in
tests/test_copywriting_v82_cases.py).
"""
from pathlib import Path

from services.editorial_treatment import BRIEF, STANDARD
from services.news_telegram_presentation import build_v81_news_body


def _v83(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "Компания запустила новый сервис",
        "main_body": "Компания запустила новый сервис для пользователей. Это расширяет доступные им возможности.",
        "ending": None,
        "quote": None,
    }
    base.update(overrides)
    return base


def _prompt_text() -> str:
    """Whitespace-normalized (collapsed to single spaces) - the raw YAML source line-wraps long
    rule strings for readability, but the prompt actually SENT to the model has those wrapped
    lines folded back together (YAML `>` block-scalar folding); testing against the folded form
    avoids false negatives from a phrase happening to straddle a source line break, matching the
    established convention from tests/test_copywriting_v82_cases.py (short substrings) applied
    here as whitespace normalization instead, since several V8.3 phrases are longer."""
    raw = Path("prompts/copywriting/v8.3.yaml").read_text(encoding="utf-8")
    return " ".join(raw.split())


# ---------------------------------------------------------------------------
# CASE 1 - English financial calque -> natural Russian meaning, not literal "сильный баланс"
# ---------------------------------------------------------------------------


def test_case_1_prompt_contains_the_financial_calque_rule_and_example() -> None:
    text = _prompt_text()
    assert "NATURAL RUSSIAN" in text
    assert "сильный баланс" in text  # the explicit BAD example
    assert "крепкое финансовое положение" in text  # the explicit GOOD direction
    assert "общекорпоративные" in text  # "general corporate purposes" calque example


# ---------------------------------------------------------------------------
# CASE 2 - corporate PR sentence -> factual content retained, PR filler removed
# ---------------------------------------------------------------------------


def test_case_2_prompt_contains_the_bureaucratic_and_pr_filler_rule() -> None:
    text = _prompt_text()
    assert "AVOID BUREAUCRATIC AND CORPORATE-PR PHRASING" in text
    assert "значимый шаг" in text
    assert "укрепляет позиции" in text


# ---------------------------------------------------------------------------
# CASE 3 - known actor + passive source wording -> natural active Russian
# ---------------------------------------------------------------------------


def test_case_3_prompt_contains_the_active_voice_rule() -> None:
    text = _prompt_text()
    assert "ACTIVE VOICE" in text
    assert "использует активный залог" in text or "active voice" in text.lower()


# ---------------------------------------------------------------------------
# CASE 4 - unknown actor -> no invented actor, passive acceptable
# ---------------------------------------------------------------------------


def test_case_4_prompt_explicitly_forbids_inventing_an_actor() -> None:
    text = _prompt_text()
    assert "Never invent an actor" in text
    assert "passive voice is" in text


# ---------------------------------------------------------------------------
# CASE 5 - semantic distinction: "designed to evade" must not become "invisible"
# ---------------------------------------------------------------------------


def test_case_5_prompt_contains_the_semantic_precision_rule_and_evade_example() -> None:
    text = _prompt_text()
    assert "SEMANTIC PRECISION IS NON-NEGOTIABLE" in text
    assert "designed to evade detection" in text
    assert "invisible" in text


# ---------------------------------------------------------------------------
# CASE 6 - overloaded sentence -> simpler syntax
# ---------------------------------------------------------------------------


def test_case_6_prompt_contains_the_simple_sentence_rule() -> None:
    text = _prompt_text()
    assert "SIMPLE SENTENCES" in text
    assert "subject-verb-object" in text


# ---------------------------------------------------------------------------
# CASE 7 - factual numbers retained exactly (schema-generic - presentation never rewrites
# main_body content, only paragraph/length shaping)
# ---------------------------------------------------------------------------


def test_case_7_presentation_layer_never_alters_body_text_content() -> None:
    output = _v83(main_body="Компания привлекла $15 млрд и наняла 1200 сотрудников.")
    body = build_v81_news_body(output, treatment=STANDARD)
    assert "$15 млрд" in body
    assert "1200 сотрудников" in body


# ---------------------------------------------------------------------------
# CASE 8 - uncertainty level preserved (the pre-existing v8.2 UNCERTAINTY rule, carried forward
# unchanged into v8.3 - confirmed present, not dropped)
# ---------------------------------------------------------------------------


def test_case_8_prompt_still_states_at_most_one_uncertainty_statement() -> None:
    text = _prompt_text()
    assert "At most ONE uncertainty statement" in text


# ---------------------------------------------------------------------------
# CASE 9 - ALL outputs -> exactly one main paragraph (schema-generic, reused from v8.1/v8.2)
# ---------------------------------------------------------------------------


def test_case_9_main_body_with_internal_break_still_collapses_to_one_paragraph_for_v83() -> None:
    output = _v83(main_body="Первое предложение.\n\nВторое предложение, которое не должно стать отдельным абзацем.")
    body = build_v81_news_body(output, treatment=BRIEF)
    assert "\n\n" not in body.split("\n\n")[0]


# ---------------------------------------------------------------------------
# CASE 10 - headline naturalness: the SAME rules apply to the headline, no exception
# ---------------------------------------------------------------------------


def test_case_10_prompt_explicitly_applies_naturalness_rules_to_the_headline_too() -> None:
    text = _prompt_text()
    assert "applies to HEADLINE and MAIN BODY" in text
    assert "headline gets no exception" in text


# ---------------------------------------------------------------------------
# Prompt-immutability guard: v8.3 is new-only, v6/v7/v8/v8.1/v8.2 stay byte-unmodified
# ---------------------------------------------------------------------------


def test_v83_is_new_and_earlier_versions_remain_byte_unmodified() -> None:
    v83_only_marker = "SEMANTIC PRECISION IS NON-NEGOTIABLE"
    for frozen_version in ("v6", "v7", "v8", "v8.1", "v8.2"):
        frozen_text = Path(f"prompts/copywriting/{frozen_version}.yaml").read_text(encoding="utf-8")
        assert v83_only_marker not in frozen_text
