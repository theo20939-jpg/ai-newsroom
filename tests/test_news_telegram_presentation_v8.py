"""Phase 23.1J - Copywriting V8 / Final Telegram NEWS Text Format presentation tests (docs/
phase23_1j_copywriting_v8_report.md).

Pure unit tests only - no DB, no LLM, no Telegram. `services/news_telegram_presentation.py`'s
V8 functions (`build_v8_news_body`, `build_v8_expandable_details`, `build_ninja_pulse_footer_html`,
`render_v8_news_card_html`) are deterministic functions of a plain dict.

Cases A-N, O-T from the phase brief's own required list (E/F/G/H are prompt-level rules - only
their presence in prompts/copywriting/v8.yaml is structurally checked here, since LLM output
itself cannot be deterministically unit-tested). U/V/W/X (existing treatment/SKIP/legacy/router
regression) are covered by re-running the pre-existing test suites unchanged, not new tests here.
"""
from pathlib import Path

from services.editorial_treatment import BRIEF, MAJOR, STANDARD
from services.news_telegram_presentation import (
    build_ninja_pulse_footer_html,
    build_v8_expandable_details,
    build_v8_news_body,
    render_v8_news_card_html,
)


def _v8(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "A company launched a new product",
        "main_body": "The company launched its new product today. Early reviews call it a meaningful upgrade over the previous model.",
        "ending": None,
        "expandable_details": None,
        "quote": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# CASE A - simple BRIEF: short headline + short main body, no ending, no expandable
# ---------------------------------------------------------------------------


def test_case_a_simple_brief_has_no_ending_or_expandable() -> None:
    output = _v8(main_body="A small app update fixed a bug that crashed the app on startup.")
    body = build_v8_news_body(output, treatment=BRIEF)
    assert body == "A small app update fixed a bug that crashed the app on startup."
    assert build_v8_expandable_details(output) is None
    html = render_v8_news_card_html(output, treatment=BRIEF)
    assert "<blockquote expandable>" not in html


# ---------------------------------------------------------------------------
# CASE B - normal STANDARD: headline + 1-2 concise paragraphs, no forced ending
# ---------------------------------------------------------------------------


def test_case_b_standard_no_forced_ending_when_none_given() -> None:
    output = _v8(ending=None)
    body = build_v8_news_body(output, treatment=STANDARD)
    assert body == output["main_body"]  # exactly the mandatory main_body, nothing appended


# ---------------------------------------------------------------------------
# CASE C - important but simple MAJOR: treatment preserved, text stays short (critical regression)
# ---------------------------------------------------------------------------


def test_case_c_major_treatment_does_not_force_extra_length() -> None:
    """The exact regression this phase exists to prevent: a MAJOR-significance story whose real
    content is fully covered by a short main_body must NOT be padded or extended merely because
    MAJOR allows more space."""
    output = _v8(
        main_body="The CEO resigned unexpectedly, effective immediately.",
        ending=None,
    )
    body = build_v8_news_body(output, treatment=MAJOR)
    assert body == "The CEO resigned unexpectedly, effective immediately."
    assert len(body) < 100


# ---------------------------------------------------------------------------
# CASE D - information-rich MAJOR: may use more space when genuinely necessary
# ---------------------------------------------------------------------------


def test_case_d_major_keeps_a_genuinely_distinct_ending() -> None:
    output = _v8(
        main_body="The company opened its first overseas factory, adding an estimated three thousand jobs.",
        ending="The facility is part of a plan to double production capacity within two years.",
    )
    body = build_v8_news_body(output, treatment=MAJOR)
    assert "overseas factory" in body
    assert "double production capacity" in body


# ---------------------------------------------------------------------------
# CASE I - important uncertainty: one concise caveat survives
# ---------------------------------------------------------------------------


def test_case_i_material_caveat_in_ending_survives() -> None:
    output = _v8(
        main_body="NVIDIA calls the new facility the largest AI data center in the region.",
        ending="No outside group has independently verified that ranking so far.",
    )
    body = build_v8_news_body(output, treatment=STANDARD)
    assert "independently verified" in body


# ---------------------------------------------------------------------------
# CASE J - repeated uncertainty: max one statement survives
# ---------------------------------------------------------------------------


def test_case_j_same_hedge_family_in_main_body_and_ending_collapses_to_one() -> None:
    output = _v8(
        main_body="The startup claims its chip is unconfirmed to outperform rivals, and details remain unconfirmed.",
        ending="Independent benchmarks remain unconfirmed at this time.",
    )
    body = build_v8_news_body(output, treatment=STANDARD)
    # ending is dropped - same "unconfirmed" hedge family already present in main_body
    assert body == output["main_body"]


# ---------------------------------------------------------------------------
# CASE K - long enumeration: core summary in main body, list in expandable details
# ---------------------------------------------------------------------------


def test_case_k_long_enumeration_goes_into_expandable_block_not_main_body() -> None:
    output = _v8(
        main_body="The company announced twelve new supported device models at launch.",
        expandable_details="Supported models: A1, A2, A3, B1, B2, B3, C1, C2, C3, D1, D2, D3.",
    )
    body = build_v8_news_body(output, treatment=STANDARD)
    assert "A1, A2, A3" not in body  # the enumeration itself never leaks into the main body
    html = render_v8_news_card_html(output, treatment=STANDARD)
    assert "<blockquote expandable>Supported models: A1, A2, A3" in html


# ---------------------------------------------------------------------------
# CASE L - direct quote: eligible for quote block, never falsely generated here
# ---------------------------------------------------------------------------


def test_case_l_quote_field_is_independent_of_expandable_details() -> None:
    """This module never inspects/generates the `quote` field itself - quote verification/
    persistence (services/quote_verification.py, services/content_draft_service.py) is completely
    untouched by V8 presentation, exactly as for V6/V7."""
    output = _v8(quote={"text": "We are proud of this launch.", "translated_text": None, "speaker": "CEO"})
    body = build_v8_news_body(output, treatment=STANDARD)
    assert "proud of this launch" not in body  # never pulled from `quote` into the visible body
    assert build_v8_expandable_details(output) is None  # `expandable_details` itself is still None


# ---------------------------------------------------------------------------
# CASE M / N - optional ending
# ---------------------------------------------------------------------------


def test_case_m_no_useful_ending_produces_no_ending() -> None:
    output = _v8(ending=None)
    html = render_v8_news_card_html(output, treatment=STANDARD)
    # exactly 3 blocks: headline, body, footer (no ending block, no expandable block)
    assert html.count("\n\n") == 2


def test_case_n_useful_ending_is_included() -> None:
    output = _v8(ending="The update rolls out globally over the next two weeks.")
    body = build_v8_news_body(output, treatment=STANDARD)
    assert "rolls out globally" in body


# ---------------------------------------------------------------------------
# CASE O / P - NINJA PULSE footer
# ---------------------------------------------------------------------------


def test_case_o_footer_exact_text_and_link() -> None:
    footer = build_ninja_pulse_footer_html()
    assert footer == '<a href="https://t.me/nnjvpn">NINJA PULSE. Подписаться 🥷</a>'


def test_case_p_footer_appears_exactly_once() -> None:
    output = _v8(ending="A useful ending.", expandable_details="Some expandable detail.")
    html = render_v8_news_card_html(output, treatment=STANDARD)
    assert html.count("NINJA PULSE") == 1
    assert html.count('href="https://t.me/nnjvpn"') == 1


# ---------------------------------------------------------------------------
# CASE Q / R / S - source button independence, no raw URLs visible
# ---------------------------------------------------------------------------


def test_case_q_source_button_text_never_appears_in_the_v8_card_html() -> None:
    """The [🔗 Источник] button is a separate inline keyboard the caller attaches - this function
    never renders any button text or source URL itself."""
    output = _v8()
    html = render_v8_news_card_html(output, treatment=STANDARD)
    assert "Источник" not in html


def test_case_r_render_function_has_no_source_url_parameter_at_all() -> None:
    """Structural guarantee, not just an empirical one: render_v8_news_card_html()'s own
    signature never accepts a source/article URL - it cannot leak one into the text."""
    import inspect

    sig = inspect.signature(render_v8_news_card_html)
    assert "url" not in " ".join(sig.parameters.keys()).lower()


def test_case_s_ninja_pulse_url_is_never_shown_as_plain_visible_text() -> None:
    """The raw https://t.me/nnjvpn string only ever appears inside the href attribute value -
    never as the anchor's own visible text (which must be exactly "NINJA PULSE. Подписаться 🥷")."""
    footer = build_ninja_pulse_footer_html()
    assert footer.startswith('<a href="https://t.me/nnjvpn">')
    visible_text = footer.split(">", 1)[1].rsplit("<", 1)[0]
    assert visible_text == "NINJA PULSE. Подписаться 🥷"
    assert "https://t.me/nnjvpn" not in visible_text


# ---------------------------------------------------------------------------
# CASE T - Fact Safety must never inspect the deterministic footer
# ---------------------------------------------------------------------------


def test_case_t_footer_text_never_reaches_fact_safety_or_content_draft_extraction() -> None:
    """The footer is built entirely inside render_v8_news_card_html() - it is never part of
    copywriting_output, so the persistence/Fact-Safety extraction functions (which only ever see
    copywriting_output) can never encounter it."""
    from services.content_draft_service import _extract_title_and_body
    from services.fact_safety import _extract_draft_text

    output = _v8()
    _title, body = _extract_title_and_body(output)
    assert "NINJA PULSE" not in body
    assert "t.me/nnjvpn" not in body

    extracted = _extract_draft_text(output)
    assert extracted is not None
    _title2, fact_safety_text = extracted
    assert "NINJA PULSE" not in fact_safety_text
    assert "t.me/nnjvpn" not in fact_safety_text


# ---------------------------------------------------------------------------
# E/F/G/H - prompt-level rules (structural presence checks only - LLM output itself cannot be
# deterministically unit-tested)
# ---------------------------------------------------------------------------


def test_v8_prompt_contains_plain_language_and_brevity_rules() -> None:
    prompt_text = Path("prompts/copywriting/v8.yaml").read_text(encoding="utf-8")
    assert "PLAIN LANGUAGE" in prompt_text
    assert "ABBREVIATIONS" in prompt_text
    assert "DELETE BEFORE EXPLAINING" in prompt_text
    assert "IMPORTANCE DOES NOT IMPLY LENGTH" in prompt_text
    assert "UNCERTAINTY" in prompt_text
    assert "NO REPETITION" in prompt_text
    assert "EXPANDABLE DETAILS" in prompt_text
    # v6/v7 must stay completely unmodified (prompt-immutability rule).
    v6_text = Path("prompts/copywriting/v6.yaml").read_text(encoding="utf-8")
    v7_text = Path("prompts/copywriting/v7.yaml").read_text(encoding="utf-8")
    assert "DELETE BEFORE EXPLAINING" not in v6_text
    assert "DELETE BEFORE EXPLAINING" not in v7_text


def test_v8_schema_has_no_forced_seven_section_structure() -> None:
    """Structural proof that V8's own output_schema really is the smaller four-field shape, not
    V6/V7's seven/eight sections - required fields are exactly title/main_body/ending/
    expandable_details/quote."""
    import yaml

    doc = yaml.safe_load(Path("prompts/copywriting/v8.yaml").read_text(encoding="utf-8"))
    assert set(doc["output_schema"]["required"]) == {"title", "main_body", "ending", "expandable_details", "quote"}
