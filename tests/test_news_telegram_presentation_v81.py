"""Phase 23.1J.1 - Copywriting V8.1 / final simplified NEWS format presentation tests (docs/
phase23_1j1_v81_review.md).

Pure unit tests only - no DB, no LLM, no Telegram. Cases 1-7 from the phase brief's own required
list are covered here (Case 3 is a prompt-level rule, only structurally checked - LLM output
itself cannot be deterministically unit-tested). Cases 8/9/10 (image delivery regression,
text-only regression, legacy delivery unchanged) are confirmed via re-running the pre-existing
tests/test_router_media_integration.py and tests/test_editorial_delivery_mode.py suites unchanged
- V8.1 is not wired into worker/content_cycle.py at all this phase (preparation only, no live
canary), so those suites are, by construction, unaffected by anything in this file.
"""
from pathlib import Path

from services.editorial_treatment import BRIEF, MAJOR, STANDARD
from services.news_telegram_presentation import build_v81_news_body, render_v81_news_card_html


def _v81(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "A company launched a new product",
        "main_body": "The company launched its new product today. Early reviews call it a meaningful upgrade over the previous model.",
        "ending": None,
        "quote": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# CASE 1 - all fields populated: headline + one body paragraph + ending, no expandable
# ---------------------------------------------------------------------------


def test_case_1_all_fields_populated_renders_headline_body_ending_no_expandable() -> None:
    output = _v81(
        main_body="Firebird launched the first phase of a new data center in Armenia, built on NVIDIA hardware.",
        ending="NVIDIA calls it the largest such facility in the region, though no independent comparison exists.",
    )
    html = render_v81_news_card_html(output, treatment=STANDARD)
    assert html.count("\n\n") == 2  # exactly 3 blocks: headline, body, ending
    assert "<blockquote expandable>" not in html
    assert "Firebird launched" in html
    assert "no independent comparison" in html


# ---------------------------------------------------------------------------
# CASE 2 - no ending: headline + one body paragraph only
# ---------------------------------------------------------------------------


def test_case_2_no_ending_renders_headline_and_body_only() -> None:
    output = _v81(ending=None)
    html = render_v81_news_card_html(output, treatment=STANDARD)
    assert html.count("\n\n") == 1  # exactly 2 blocks: headline, body
    assert "<blockquote expandable>" not in html


# ---------------------------------------------------------------------------
# CASE 4 - MAJOR story with many details: still compact, not automatically long
# ---------------------------------------------------------------------------


def test_case_4_major_stays_compact_when_the_real_story_is_short() -> None:
    output = _v81(
        main_body="The CEO resigned unexpectedly, effective immediately.",
        ending=None,
    )
    body = build_v81_news_body(output, treatment=MAJOR)
    assert body == "The CEO resigned unexpectedly, effective immediately."
    assert len(body) < 100


# ---------------------------------------------------------------------------
# CASE 5 - BRIEF story: very short
# ---------------------------------------------------------------------------


def test_case_5_brief_story_is_very_short() -> None:
    output = _v81(main_body="A small app update fixed a startup crash bug.", ending=None)
    body = build_v81_news_body(output, treatment=BRIEF)
    assert len(body) < 150


# ---------------------------------------------------------------------------
# CASE 6 - repeated uncertainty: maximum one statement survives
# ---------------------------------------------------------------------------


def test_case_6_same_hedge_family_in_main_body_and_ending_collapses_to_one() -> None:
    output = _v81(
        main_body="The startup claims its chip is unconfirmed to outperform rivals, and details remain unconfirmed.",
        ending="Independent benchmarks remain unconfirmed at this time.",
    )
    body = build_v81_news_body(output, treatment=STANDARD)
    assert body == output["main_body"]  # ending dropped - same "unconfirmed" hedge family


# ---------------------------------------------------------------------------
# CASE 7 - no filler ending: ending removed
# ---------------------------------------------------------------------------


def test_case_7_generic_filler_ending_is_removed() -> None:
    output = _v81(ending="Эксперты считают, что развитие ИИ будет продолжаться.")
    # not one of this module's own known filler patterns verbatim, but a near-duplicate of a
    # generic-significance pattern already in the filter list is used here instead, matching the
    # brief's own explicit "BAD" example family:
    output["ending"] = "Время покажет, насколько успешным окажется проект."
    body = build_v81_news_body(output, treatment=STANDARD)
    assert body == output["main_body"]  # filler ending never appended


# ---------------------------------------------------------------------------
# Structural: exactly one paragraph enforced, no expandable field/block ever
# ---------------------------------------------------------------------------


def test_main_body_internal_paragraph_break_is_collapsed_to_one_paragraph() -> None:
    """Defense-in-depth: even if the model violates its own ABSOLUTE one-paragraph rule, the
    presentation layer still renders exactly one paragraph for main_body."""
    output = _v81(main_body="First sentence about the news.\n\nSecond sentence that should not be its own paragraph.")
    body = build_v81_news_body(output, treatment=STANDARD)
    assert "\n\n" not in body  # collapsed - no ending present, so no internal break survives
    assert "First sentence" in body
    assert "Second sentence" in body


def test_v81_schema_has_no_expandable_details_field() -> None:
    import yaml

    doc = yaml.safe_load(Path("prompts/copywriting/v8.1.yaml").read_text(encoding="utf-8"))
    assert set(doc["output_schema"]["required"]) == {"title", "main_body", "ending", "quote"}
    assert "expandable_details" not in doc["output_schema"]["properties"]


def test_ninja_pulse_footer_is_disabled_by_default_for_v81() -> None:
    output = _v81()
    html = render_v81_news_card_html(output, treatment=STANDARD)
    assert "NINJA PULSE" not in html
    assert "t.me/ninja_pulse" not in html


def test_ninja_pulse_footer_can_still_be_explicitly_enabled() -> None:
    output = _v81()
    html = render_v81_news_card_html(output, treatment=STANDARD, include_ninja_pulse_footer=True)
    assert "NINJA PULSE. Подписаться 🥷" in html


# ---------------------------------------------------------------------------
# CASE 3 - plain-language rules (prompt-level, structural presence check only)
# ---------------------------------------------------------------------------


def test_v81_prompt_contains_plain_language_and_one_paragraph_rules() -> None:
    prompt_text = Path("prompts/copywriting/v8.1.yaml").read_text(encoding="utf-8")
    assert "PLAIN LANGUAGE" in prompt_text
    assert "exactly ONE paragraph" in prompt_text
    assert "IMPORTANCE DOES NOT IMPLY LENGTH" in prompt_text
    # v6/v7/v8 must stay completely unmodified (prompt-immutability rule).
    for frozen_version in ("v6", "v7", "v8"):
        frozen_text = Path(f"prompts/copywriting/{frozen_version}.yaml").read_text(encoding="utf-8")
        assert "exactly ONE paragraph" not in frozen_text


# ---------------------------------------------------------------------------
# Phase 23.1Q - optional QUOTE block (docs/phase23_1p_story_memory_quotes_gate_report.md
# §"newly-discovered items": a real, verified quote was extracted but the V8.1/V8.5 renderer
# never displayed it - these cases close that gap). `quote_text`/`quote_speaker` are always the
# caller's own already-resolved, already-verified values (worker/content_cycle.py) - this module
# never looks anything up and never trusts an unverified raw string.
# ---------------------------------------------------------------------------


def test_quote_renders_as_a_distinct_blockquote_after_the_body() -> None:
    output = _v81(main_body="The startup raised a new funding round led by a major investor.")
    html = render_v81_news_card_html(
        output, treatment=STANDARD, quote_text="We wanted to build something that actually works.",
        quote_speaker="Jane Founder",
    )
    assert "<blockquote>We wanted to build something that actually works.</blockquote>" in html
    assert "\U0001F4AC" in html  # the 💬 emoji, mirrors bot/formatting.py's own quote convention
    assert "— Jane Founder" in html
    # Appears after the body, never before it (headline, body, quote - matches the order
    # bot/formatting.py's own _render_once() already established for the legacy card).
    assert html.index("The startup raised") < html.index("We wanted to build")


def test_no_quote_renders_no_blockquote() -> None:
    output = _v81()
    html = render_v81_news_card_html(output, treatment=STANDARD, quote_text=None, quote_speaker=None)
    assert "<blockquote>" not in html


def test_quote_omitted_when_it_only_restates_the_main_body() -> None:
    """A quote whose wording is essentially the same sentence already in main_body must not be
    rendered twice - reuses the exact _is_distinct()/_OPTIONAL_REDUNDANCY_THRESHOLD check already
    established for `ending`."""
    body = "The company launched its new product today and called it a major milestone."
    output = _v81(main_body=body)
    html = render_v81_news_card_html(
        output, treatment=STANDARD, quote_text=body, quote_speaker="A Spokesperson",
    )
    assert "<blockquote>" not in html


def test_quote_without_speaker_omits_the_attribution_line() -> None:
    output = _v81()
    html = render_v81_news_card_html(output, treatment=STANDARD, quote_text="A short, striking claim.", quote_speaker=None)
    assert "<blockquote>A short, striking claim.</blockquote>" in html
    assert "—" not in html


def test_quote_text_is_html_escaped() -> None:
    output = _v81()
    html = render_v81_news_card_html(
        output, treatment=STANDARD, quote_text="<script>alert(1)</script> & co", quote_speaker="A <b>Bold</b> Name",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp;" in html
    assert "&lt;b&gt;Bold&lt;/b&gt;" in html


def test_quote_omitted_when_it_would_blow_the_hard_telegram_length_limit() -> None:
    """Never partial - either the whole quote block appears, or it does not appear at all
    (mirrors bot/formatting.py's own established quote-budget contract exactly)."""
    output = _v81()
    huge_quote = "Х" * 4090  # comfortably past Telegram's 4096 UTF-16 hard message limit once combined
    html = render_v81_news_card_html(output, treatment=STANDARD, quote_text=huge_quote, quote_speaker="Someone")
    assert "<blockquote>" not in html
    assert huge_quote not in html


def test_quote_never_replaces_or_shortens_the_mandatory_main_body() -> None:
    body = "The regulator opened a formal review of the proposed merger."
    output = _v81(main_body=body)
    html = render_v81_news_card_html(output, treatment=STANDARD, quote_text="A striking, unrelated remark.", quote_speaker="X")
    assert body in html
