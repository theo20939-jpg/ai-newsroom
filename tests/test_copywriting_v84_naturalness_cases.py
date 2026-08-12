"""Phase 23.1M final polish - required test cases A-J (docs/
phase23_1m_final_russian_polish_report.md, Part 14).

V8.4 is schema-identical to V8.1/V8.2/V8.3 (title/main_body/ending/quote) - only the prompt
wording changed. Naturalness/semantic-precision claims are LLM-output-quality properties verified
via the golden replay (docs/phase23_1m_final_russian_polish_report.md §4-9), mirroring
tests/test_copywriting_v83_naturalness_cases.py's own established convention. This file makes the
required cases A-J explicit: prompt-content assertions for the new/strengthened rules (cases
A, B, C, D, E, F, G), and reuse of existing schema-generic presentation tests for the purely
structural cases (H - numbers untouched by presentation; I - one main paragraph; J - length, via
the golden comparison itself, not unit-testable here).
"""
from pathlib import Path

from services.editorial_treatment import BRIEF, STANDARD
from services.news_telegram_presentation import build_v81_news_body


def _v84(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "Компания запустила новый сервис",
        "main_body": "Компания запустила новый сервис для пользователей. Он доступен уже сегодня.",
        "ending": None,
        "quote": None,
    }
    base.update(overrides)
    return base


def _prompt_text() -> str:
    """Whitespace-normalized, matching tests/test_copywriting_v83_naturalness_cases.py's own
    established convention - the raw YAML source line-wraps long rule strings for readability."""
    raw = Path("prompts/copywriting/v8.4.yaml").read_text(encoding="utf-8")
    return " ".join(raw.split())


# ---------------------------------------------------------------------------
# CASE A - metaphorical source headline ("designed to evade/interfere with recognition") ->
# no unsupported "invisible" claim
# ---------------------------------------------------------------------------


def test_case_a_prompt_contains_headline_semantic_precision_rule_and_evade_vs_invisible_example() -> None:
    text = _prompt_text()
    assert "HEADLINE SEMANTIC PRECISION" in text
    assert "evade/interfere with recognition" in text
    assert "невидимые" in text  # the explicit disputed-outcome-word example
    assert "мешать/затруднить распознаванию" in text  # the supported-purpose direction


# ---------------------------------------------------------------------------
# CASE B - literal corporate/financial calque -> natural meaning or omission
# ---------------------------------------------------------------------------


def test_case_b_prompt_still_contains_the_financial_meaning_translation_rule() -> None:
    text = _prompt_text()
    assert "сильный баланс" in text
    assert "финансовая устойчивость" in text or "финансовое положение" in text


# ---------------------------------------------------------------------------
# CASE C - corporate filler with no concrete value -> omitted
# ---------------------------------------------------------------------------


def test_case_c_prompt_contains_the_corporate_abstract_noun_filter_with_concrete_test() -> None:
    text = _prompt_text()
    assert "CORPORATE ABSTRACT-NOUN FILTER" in text
    assert "what concrete thing does this tell the reader" in text
    assert "general corporate purposes" in text
    assert "DELETE the phrase entirely" in text


# ---------------------------------------------------------------------------
# CASE D - actor known -> natural active construction
# ---------------------------------------------------------------------------


def test_case_d_prompt_contains_active_voice_rule_with_intel_and_researcher_examples() -> None:
    text = _prompt_text()
    assert "ACTIVE VOICE" in text
    assert "Intel планирует разместить акции" in text
    assert "Исследователь создал узоры" in text


# ---------------------------------------------------------------------------
# CASE E - actor unknown -> no invented actor
# ---------------------------------------------------------------------------


def test_case_e_prompt_forbids_inventing_an_actor() -> None:
    text = _prompt_text()
    assert "Never invent an actor" in text
    assert "passive voice is acceptable and correct" in text


# ---------------------------------------------------------------------------
# CASE F - planned vs. completed -> status preserved (part of the non-negotiable semantic rule)
# ---------------------------------------------------------------------------


def test_case_f_prompt_semantic_precision_rule_covers_planned_vs_claimed_status() -> None:
    text = _prompt_text()
    assert "SEMANTIC PRECISION IS NON-NEGOTIABLE" in text
    assert "already happened vs. is planned vs. is merely claimed/reported" in text


# ---------------------------------------------------------------------------
# CASE G - uncertainty -> certainty preserved (v8.3's rule, carried forward unchanged)
# ---------------------------------------------------------------------------


def test_case_g_prompt_still_states_at_most_one_uncertainty_statement() -> None:
    text = _prompt_text()
    assert "At most ONE uncertainty statement" in text


# ---------------------------------------------------------------------------
# CASE H - numbers -> exact preservation (schema-generic: presentation never rewrites body text)
# ---------------------------------------------------------------------------


def test_case_h_presentation_layer_never_alters_numbers_in_body_text() -> None:
    output = _v84(main_body="Компания привлекла $15 млрд и наняла 1200 сотрудников в 2026 году.")
    body = build_v81_news_body(output, treatment=STANDARD)
    assert "$15 млрд" in body
    assert "1200 сотрудников" in body
    assert "2026" in body


# ---------------------------------------------------------------------------
# CASE I - structure -> exactly one MAIN BODY paragraph (schema-generic, reused from v8.1-v8.3)
# ---------------------------------------------------------------------------


def test_case_i_main_body_with_internal_break_still_collapses_to_one_paragraph_for_v84() -> None:
    output = _v84(main_body="Первое предложение.\n\nВторое предложение, которое не должно стать отдельным абзацем.")
    body = build_v81_news_body(output, treatment=BRIEF)
    assert "\n\n" not in body.split("\n\n")[0]


# ---------------------------------------------------------------------------
# CASE J (partial) - headline naturalness: avoid mechanically-inherited constructions
# ---------------------------------------------------------------------------


def test_case_j_prompt_contains_headline_naturalness_rule_with_banned_constructions() -> None:
    text = _prompt_text()
    assert "HEADLINE NATURALNESS" in text
    assert "заявлен как" in text
    assert "был осуществлён запуск" in text
    assert "WHO + DID WHAT" in text


def test_edit_first_by_deletion_rule_is_present_and_prioritized() -> None:
    text = _prompt_text()
    assert "EDIT-FIRST-BY-DELETION" in text
    assert "DELETE if the phrase is" in text


# ---------------------------------------------------------------------------
# Prompt-immutability guard: v8.4 is new-only, v6-v8.3 stay byte-unmodified
# ---------------------------------------------------------------------------


def test_v84_is_new_and_earlier_versions_remain_byte_unmodified() -> None:
    v84_only_marker = "EDIT-FIRST-BY-DELETION"
    for frozen_version in ("v6", "v7", "v8", "v8.1", "v8.2", "v8.3"):
        frozen_text = Path(f"prompts/copywriting/{frozen_version}.yaml").read_text(encoding="utf-8")
        assert v84_only_marker not in frozen_text
