"""Phase 23.1J - V8 Copywriting / Fact Safety compatibility (docs/
phase23_1j_copywriting_v8_report.md).

Written test-first, mirroring tests/test_fact_safety_v6_compatibility.py's own established shape.
V8's schema (title/main_body/ending/expandable_details/quote) needed one new recognized-schema
branch in services/fact_safety.py::_extract_draft_text(), added alongside the existing V4/V6
branches - never replacing them.
"""
from core.config import settings
from services.fact_safety import apply_fact_safety


def _v8_output(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "OpenAI releases a new model",
        "main_body": "OpenAI released a new flagship model on Thursday. It scores 92% on the industry's standard reasoning benchmark.",
        "ending": None,
        "expandable_details": None,
        "quote": None,
    }
    base.update(overrides)
    return base


def test_case_1_v8_schema_runs_fact_safety_normally(monkeypatch) -> None:
    monkeypatch.setattr(settings, "fact_safety_mode", "shadow")
    copywriting_output = _v8_output()
    quality_output = {"passed": True, "issues": []}
    out = apply_fact_safety(
        "OpenAI announces new model", "OpenAI announced a new model on Thursday, scoring 92% on the benchmark.",
        None, {}, copywriting_output, quality_output,
    )
    assert "fact_safety" in out, "V8 output must not silently no-op"
    assert out["fact_safety"]["status"] in ("pass", "review", "block")
    assert out["fact_safety"]["version"] == "v1"
    assert out["fact_safety"]["claims_checked"] >= 1


def test_case_2_v8_checks_claims_from_ending_and_expandable_details_not_just_main_body(monkeypatch) -> None:
    """A fabricated claim placed only in `expandable_details` must still be caught - proves the
    fix concatenates the whole draft (including the field that will later be visually hidden
    behind a Telegram expandable blockquote), not just title+main_body."""
    monkeypatch.setattr(settings, "fact_safety_mode", "shadow")
    copywriting_output = _v8_output(
        expandable_details="The deal was worth $4.2 billion, the largest in the company's history.",
    )
    quality_output = {"passed": True, "issues": []}
    out = apply_fact_safety(
        "OpenAI announces new model", "OpenAI announced a new model on Thursday.",
        None, {}, copywriting_output, quality_output,
    )
    findings = out["fact_safety"]["findings"]
    assert any("4.2 billion" in f["claim"] or "4.2" in f["claim"] for f in findings), (
        "the $4.2 billion claim from expandable_details must be checked, not silently skipped"
    )


def test_case_3_v8_ending_claim_is_also_checked(monkeypatch) -> None:
    monkeypatch.setattr(settings, "fact_safety_mode", "shadow")
    copywriting_output = _v8_output(ending="The rollout price increased by 15 percent from the previous tier.")
    quality_output = {"passed": True, "issues": []}
    out = apply_fact_safety(
        "OpenAI announces new model", "OpenAI announced a new model on Thursday.",
        None, {}, copywriting_output, quality_output,
    )
    findings = out["fact_safety"]["findings"]
    assert any("15" in f["claim"] for f in findings), "the ending's own claim must be checked"
