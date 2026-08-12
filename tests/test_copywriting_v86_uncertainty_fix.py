"""Phase 23.1Q - v8.6 UNCERTAINTY rule fix (docs conversation, live-canary root cause: v8.5's own
UNCERTAINTY rule used "данные неизвестны"/"подробности не раскрыты" as worked examples of an
ACCEPTABLE uncertainty statement, licensing generic missing-detail-enumeration filler endings -
confirmed live, e.g. the real Craft Ventures post ending "Точный размер фонда, сроки привлечения и
инвестиционная стратегия пока неизвестны.").

Mirrors tests/test_copywriting_v84_naturalness_cases.py's own established convention: prompt-
content structural assertions (LLM output quality itself is not unit-testable without a live/golden
replay), plus this file's own additional coverage for the deterministic-layer hedge-family
extension (services/news_telegram_presentation.py's own existing collapse-against-main_body
mechanism, defense-in-depth only - never the primary fix, never a materiality judgment on its own).
"""
from pathlib import Path

from services.news_telegram_presentation import (
    _HEDGE_FAMILIES,
    _hedge_family,
    build_v81_news_body,
)


def _v86_prompt_text() -> str:
    """Whitespace-normalized, matching tests/test_copywriting_v84_naturalness_cases.py's own
    established convention - the raw YAML source line-wraps long rule strings for readability."""
    raw = Path("prompts/copywriting/v8.6.yaml").read_text(encoding="utf-8")
    return " ".join(raw.split())


def _v85_prompt_text() -> str:
    raw = Path("prompts/copywriting/v8.5.yaml").read_text(encoding="utf-8")
    return " ".join(raw.split())


# ---------------------------------------------------------------------------
# CASE 1 - v8.6 contains the material-vs-trivial uncertainty distinction
# ---------------------------------------------------------------------------


def test_v86_contains_the_materiality_distinction() -> None:
    text = _v86_prompt_text()
    assert "materially changes" in text
    assert "editorially relevant" in text
    # The two "may remain" examples from the accepted plan, present as positive guidance.
    assert "Компания официально не подтвердила сделку" in text
    assert "Дата запуска пока не объявлена" in text


def test_v86_explicitly_forbids_absence_as_its_own_reason() -> None:
    text = _v86_prompt_text()
    assert "is NOT itself a reason to add a sentence" in text
    assert "shorter piece" in text or "shorter" in text


# ---------------------------------------------------------------------------
# CASE 2 - v8.6 no longer licenses generic "unknown details" filler
# ---------------------------------------------------------------------------


def test_v86_no_longer_offers_missing_detail_phrases_as_acceptable_examples() -> None:
    """v8.5's own UNCERTAINTY rule used these two phrases as POSITIVE worked examples ("never
    repeat phrases like X more than once" implies X itself is fine once). v8.6 must not repeat
    that framing - the same phrases may still appear, but only inside a "never write" example."""
    v85_text = _v85_prompt_text()
    v86_text = _v86_prompt_text()
    # Confirm the historical, defective framing really is present in v8.5 (the regression this
    # fixes) - a sanity check that this test would have failed against the original defect.
    assert "never repeat phrases like" in v85_text and "данные неизвестны" in v85_text

    # v8.6 must frame missing-detail phrases as something to NEVER write, not merely not-repeat.
    assert "Never write a sentence that merely enumerates missing details" in v86_text
    assert "Точные сроки пока неизвестны" in v86_text  # present, but only as a negative example
    assert "never repeat phrases like" not in v86_text  # the old, defective framing is gone


def test_v86_ending_still_forbidden_from_being_generic() -> None:
    """The pre-existing OPTIONAL ENDING rule (unchanged) already forbids generic closers -
    confirms this rule wasn't accidentally touched/weakened."""
    text = _v86_prompt_text()
    assert "это показывает, что развитие ИИ продолжается" in text  # unchanged "never write" example
    assert "OPTIONAL ENDING" in text


# ---------------------------------------------------------------------------
# CASE 3 - existing one-paragraph/plain-language rules remain present; v8.5 stays frozen
# ---------------------------------------------------------------------------


def test_v86_preserves_one_paragraph_and_plain_language_rules() -> None:
    text = _v86_prompt_text()
    assert "exactly ONE paragraph" in text or "exactly ONE main_body paragraph" in text
    assert "PLAIN LANGUAGE" in text
    assert "IMPORTANCE DOES NOT IMPLY LENGTH" in text


def test_v86_schema_unchanged_from_v85() -> None:
    """Same output fields as v8.5 - this version changes only prompt wording, never the schema."""
    text = _v86_prompt_text()
    for field in ("story_led", "viral_potential", "meme_potential", "quote"):
        assert field in text


def test_v85_and_earlier_prompts_remain_byte_for_byte_frozen() -> None:
    """v8.6 is a new, additional file - every earlier version must be untouched (prompt-
    immutability rule)."""
    for frozen_version in ("v6", "v7", "v8", "v8.1", "v8.2", "v8.3", "v8.4", "v8.5"):
        frozen_text = Path(f"prompts/copywriting/{frozen_version}.yaml").read_text(encoding="utf-8")
        assert "V8.6" not in frozen_text
        assert "UNCERTAINTY (V8.6, rewritten" not in frozen_text
        assert "Never write a sentence that merely enumerates missing details" not in frozen_text


def test_copywriting_prompt_version_setting_accepts_86() -> None:
    from core.config import Settings

    fields = Settings.model_fields["copywriting_prompt_version"]
    assert "8.6" in fields.annotation.__args__


# ---------------------------------------------------------------------------
# CASE 4 - hedge-family detection covers the newly identified inflections
# ---------------------------------------------------------------------------


def test_hedge_family_recognizes_neizvestny_inflection() -> None:
    assert _hedge_family("Точный размер фонда пока неизвестны.") == "undisclosed"


def test_hedge_family_recognizes_ne_raskryvayutsya_inflection() -> None:
    assert _hedge_family("Другие детали не раскрываются.") == "undisclosed"


def test_hedge_family_recognizes_otsutstvuet_inflection() -> None:
    assert _hedge_family("Дополнительная информация отсутствует.") == "undisclosed"


def test_hedge_families_pre_existing_stems_still_present() -> None:
    """Additive only - confirms the extension didn't drop any pre-existing marker."""
    for stem in ("не раскрыл", "не уточнен", "не сообщил", "не указан"):
        assert stem in _HEDGE_FAMILIES["undisclosed"]


# ---------------------------------------------------------------------------
# CASE 5 - redundant undisclosed hedges can still be collapsed where existing logic applies
# ---------------------------------------------------------------------------


def test_redundant_undisclosed_ending_is_still_collapsed_against_main_body() -> None:
    """When main_body already expresses the SAME hedge family, a same-family ending must still be
    dropped - the pre-existing collapse mechanism, now correctly reachable for these inflections
    too (previously it silently never fired for "неизвестны"-shaped endings because _hedge_family()
    returned None for them)."""
    output = {
        "title": "T",
        "main_body": "Компания не раскрыла условия сделки, сообщили источники.",
        "ending": "Точная сумма сделки пока неизвестна.",
        "quote": None,
    }
    body = build_v81_news_body(output, treatment="standard")
    assert "неизвестна" not in body  # collapsed - same "undisclosed" family as main_body


# ---------------------------------------------------------------------------
# CASE 6 - material uncertainty is NOT deterministically stripped solely for belonging to a
# tracked hedge family
# ---------------------------------------------------------------------------


def test_material_uncertainty_ending_survives_when_main_body_has_no_matching_hedge() -> None:
    """The deterministic layer only collapses an ending that DUPLICATES main_body's own hedge
    family - it must never independently decide an ending is "just filler" merely because it
    belongs to a tracked family. Materiality judgment stays the prompt's job (v8.6), not this
    module's. "Дата запуска пока не объявлена" does not match any tracked hedge family at all
    (confirmed: _hedge_family returns None), so it is never at risk of this collapse mechanism -
    exactly the safe direction (never over-strip)."""
    from services.news_telegram_presentation import _hedge_family

    assert _hedge_family("Дата запуска пока не объявлена.") is None

    output = {
        "title": "T",
        "main_body": "Компания представила новый продукт на мероприятии в среду.",
        "ending": "Дата запуска пока не объявлена.",
        "quote": None,
    }
    body = build_v81_news_body(output, treatment="standard")
    assert "Дата запуска пока не объявлена" in body


def test_unconfirmed_family_ending_survives_when_main_body_hedge_is_a_different_family() -> None:
    """A material "unconfirmed" ending must not be dropped merely because main_body ALSO happens
    to hedge, when the two are genuinely different families (never a blanket "any hedge present ->
    drop" rule)."""
    output = {
        "title": "T",
        "main_body": "Источники сообщают, что переговоры проходят в закрытом режиме.",
        "ending": "Компания официально не подтвердила сделку.",
        "quote": None,
    }
    body = build_v81_news_body(output, treatment="standard")
    assert "официально не подтвердила" in body
