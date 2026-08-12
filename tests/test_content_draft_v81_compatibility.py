"""Phase 23.1J.1 - V8.1 Copywriting / ContentDraft + Fact Safety compatibility.

V8.1's schema (title/main_body/ending/quote - no `expandable_details` field at all) is a strict
subset of V8's own recognized shape (title/main_body/ending/expandable_details/quote). Confirmed
by direct testing that the existing V8 extraction branches in services/content_draft_service.py::
_extract_title_and_body() and services/fact_safety.py::_extract_draft_text() already handle V8.1
output correctly with ZERO code changes - both iterate their own `_V8_TEXT_KEYS_IN_ORDER`/
`_V8_OPTIONAL_TEXT_KEYS` tuples via `.get()`, which returns None (silently skipped) for a key that
simply does not exist in the dict, exactly like an explicitly-null optional V8 field. These tests
lock that behavior in as a permanent regression guard, not a new implementation.
"""
from core.config import settings
from services.content_draft_service import _extract_title_and_body
from services.fact_safety import apply_fact_safety, _extract_draft_text


def _v81_output(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "OpenAI releases a new model",
        "main_body": "OpenAI released a new flagship model on Thursday. It scores 92% on the industry's standard reasoning benchmark.",
        "ending": None,
        "quote": None,
    }
    base.update(overrides)
    return base


def test_v81_schema_extracted_by_content_draft_service() -> None:
    title, body = _extract_title_and_body(_v81_output())
    assert title == "OpenAI releases a new model"
    assert "flagship model" in body
    assert "scores 92%" in body


def test_v81_ending_included_only_when_present() -> None:
    _title, body_with = _extract_title_and_body(_v81_output(ending="A follow-up model is expected next quarter."))
    assert "follow-up model is expected" in body_with

    _title, body_without = _extract_title_and_body(_v81_output())
    assert "follow-up model is expected" not in body_without


def test_v81_has_no_expandable_details_key_and_is_still_extracted_correctly() -> None:
    """The defining structural difference from V8: this dict has no `expandable_details` key at
    all (not even set to None) - proves the extraction code degrades gracefully rather than
    raising a KeyError or failing to recognize the schema."""
    output = _v81_output()
    assert "expandable_details" not in output
    title, body = _extract_title_and_body(output)
    assert title and body


def test_v81_schema_runs_fact_safety_normally(monkeypatch) -> None:
    monkeypatch.setattr(settings, "fact_safety_mode", "shadow")
    out = apply_fact_safety(
        "OpenAI announces new model", "OpenAI announced a new model on Thursday, scoring 92% on the benchmark.",
        None, {}, _v81_output(), {"passed": True, "issues": []},
    )
    assert "fact_safety" in out
    assert out["fact_safety"]["status"] in ("pass", "review", "block")
    assert out["fact_safety"]["claims_checked"] >= 1


def test_v81_extract_draft_text_directly() -> None:
    extracted = _extract_draft_text(_v81_output(ending="A material caveat."))
    assert extracted is not None
    title, text = extracted
    assert title == "OpenAI releases a new model"
    assert "material caveat" in text
