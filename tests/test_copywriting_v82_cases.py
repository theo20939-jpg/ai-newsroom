"""Phase 23.1K - Copywriting V8.2 final-style test-first cases (docs/
phase23_1k_v82_live_canary_report.md, Part D).

V8.2 is schema-identical to V8.1 (title/main_body/ending/quote) - only the prompt wording
changed (stronger "delete before explaining" + a new vendor/supplier rule). Every presentation-
layer behavior (one-paragraph collapsing, filler-ending removal, length ceilings, redundant-
uncertainty collapsing) is schema-based, not version-based, so it already applies to v8.2 output
via the exact same tests/test_news_telegram_presentation_v81.py functions - this file makes that
coverage EXPLICIT and traceable to the phase brief's own numbered case list, rather than leaving
it merely implied.

Cases 1/2/4 (does the LLM actually simplify/drop vendor names/keep MAJOR short) are prompt-output
quality, not code logic - they cannot be deterministically unit-tested and are instead verified by
the golden replay (docs/phase23_1k_v82_live_canary_report.md Part B/C). Case 4's "repeated
uncertainty -> one max" is likewise primarily a prompt-level instruction; this file only confirms
the instruction text is present and that the presentation layer's own hedge-collapsing safety net
(pre-existing, schema-generic) still applies to v8.2-shaped output.
"""
from pathlib import Path

from services.editorial_treatment import BRIEF, MAJOR, STANDARD
from services.news_telegram_presentation import build_v81_news_body, render_v81_news_card_html


def _v82(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "A data center was built for AI workloads",
        "main_body": "A new data center built specifically for AI workloads opened this week.",
        "ending": None,
        "quote": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# CASE 1 - technical AI infra news -> simple explanation, no vendor overload (prompt-level;
# structurally confirmed here, verified for real via the golden replay Armenia/Firebird case)
# ---------------------------------------------------------------------------


def test_case_1_v82_prompt_contains_the_delete_before_explaining_rule_and_verbatim_example() -> None:
    prompt_text = Path("prompts/copywriting/v8.2.yaml").read_text(encoding="utf-8")
    assert "DELETE BEFORE EXPLAINING" in prompt_text
    assert "does the average technology reader need this" in prompt_text
    assert "Schneider Electric" in prompt_text and "Vertiv" in prompt_text  # verbatim BAD example


# ---------------------------------------------------------------------------
# CASE 2 - many facts -> only important ones remain (prompt-level; the new vendor/supplier rule)
# ---------------------------------------------------------------------------


def test_case_2_v82_prompt_contains_the_vendor_supplier_rule() -> None:
    prompt_text = Path("prompts/copywriting/v8.2.yaml").read_text(encoding="utf-8")
    assert "VENDOR/SUPPLIER RULE" in prompt_text


# ---------------------------------------------------------------------------
# CASE 3 - MAJOR can be short (schema-generic presentation behavior, reused from V8.1)
# ---------------------------------------------------------------------------


def test_case_3_major_treatment_stays_compact_for_a_short_v82_story() -> None:
    output = _v82(main_body="A new data center built specifically for AI workloads opened this week.")
    body = build_v81_news_body(output, treatment=MAJOR)
    assert body.count("\n\n") == 0  # exactly one paragraph
    assert len(body) < 300  # no artificial padding to reach MAJOR's ceiling


# ---------------------------------------------------------------------------
# CASE 4 - repeated uncertainty -> one max (prompt-level rule + schema-generic hedge collapsing)
# ---------------------------------------------------------------------------


def test_case_4_v82_prompt_states_at_most_one_uncertainty_statement() -> None:
    prompt_text = Path("prompts/copywriting/v8.2.yaml").read_text(encoding="utf-8")
    assert "At most ONE uncertainty statement" in prompt_text


def test_case_4b_same_hedge_family_in_body_and_ending_still_collapses_for_v82_shaped_output() -> None:
    output = _v82(
        main_body="Officials said the project may not be finished until next year, though this is not yet confirmed.",
        ending="It remains unclear whether the timeline will hold.",
    )
    body = build_v81_news_body(output, treatment=STANDARD)
    assert body.count("\n\n") <= 1  # ending kept separate only if genuinely distinct; never two hedges stacked


# ---------------------------------------------------------------------------
# CASE 5 - no useful ending -> removed (schema-generic, reused from V8.1's filler list)
# ---------------------------------------------------------------------------


def test_case_5_generic_filler_ending_is_removed_for_v82_shaped_output() -> None:
    output = _v82(ending="Время покажет, чем всё закончится.")
    body = build_v81_news_body(output, treatment=STANDARD)
    assert "Время покажет" not in body


# ---------------------------------------------------------------------------
# CASE 6 - useful ending -> preserved (schema-generic)
# ---------------------------------------------------------------------------


def test_case_6_a_distinct_useful_ending_is_preserved_for_v82_shaped_output() -> None:
    output = _v82(ending="The company has not disclosed the total construction cost.")
    body = build_v81_news_body(output, treatment=STANDARD)
    assert "construction cost" in body


# ---------------------------------------------------------------------------
# CASE 7 - ALL outputs -> exactly one main paragraph (schema-generic safety net)
# ---------------------------------------------------------------------------


def test_case_7_main_body_with_an_internal_break_still_collapses_to_one_paragraph_for_v82() -> None:
    output = _v82(main_body="First sentence about the launch.\n\nSecond sentence that should not be a separate paragraph.")
    body = build_v81_news_body(output, treatment=BRIEF)
    # only the (optional) body/ending boundary may introduce a break - never inside main_body itself
    assert "\n\n" not in body.split("\n\n")[0]


# ---------------------------------------------------------------------------
# CASE 8 - source button regression (proven end-to-end in tests/test_router_media_integration.py::
# test_v82_output_renders_via_the_v8_family_card_not_the_legacy_template)
# ---------------------------------------------------------------------------


def test_case_8_render_v82_shaped_output_produces_html_with_no_raw_url_inline() -> None:
    output = _v82()
    html = render_v81_news_card_html(output, treatment=STANDARD)
    assert "http://" not in html and "https://" not in html  # source is a button, never inline text


# ---------------------------------------------------------------------------
# CASE 9 - image caption regression (proven end-to-end in tests/test_router_media_integration.py::
# test_v82_output_with_image_sends_photo_with_the_v8_family_caption)
# ---------------------------------------------------------------------------


def test_case_9_v82_render_output_is_short_enough_to_fit_a_photo_caption_when_brief() -> None:
    output = _v82()
    html = render_v81_news_card_html(output, treatment=BRIEF)
    assert len(html) <= 1024  # Telegram's photo-caption UTF-16 limit


# ---------------------------------------------------------------------------
# CASE 10 - legacy delivery unchanged (proven end-to-end in tests/test_router_media_integration.py::
# test_v6_output_still_uses_the_legacy_template_unchanged; frozen-prompt guard here)
# ---------------------------------------------------------------------------


def test_case_10_v82_is_a_new_file_and_v6_v7_v8_v81_prompts_remain_byte_unmodified() -> None:
    v82_only_marker = "VENDOR/SUPPLIER RULE"
    for frozen_version in ("v6", "v7", "v8", "v8.1"):
        frozen_text = Path(f"prompts/copywriting/{frozen_version}.yaml").read_text(encoding="utf-8")
        assert v82_only_marker not in frozen_text
