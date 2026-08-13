"""Newsroom Stability Harness: the golden regression suite entry point.

Parametrized per category over tests/fixtures/news_golden_cases.json. Each test calls a real
production function (via tests/golden/runners.py) and evaluates the case's declared `expected`
invariants (tests/golden/invariants.py) - never asserts on exact LLM prose. See
docs/newsroom_stability_harness_checkpoint.md for the full design and docs/13_Testing_Strategy.md
§15 for the permanent bug-to-regression rule this suite exists to enforce.

Runs under pytest exactly like every other test in this repo - inherits conftest.py's real-
provider/real-egress/real-database safety barriers automatically. Also runnable via
scripts/run_news_golden_suite.py for a concise PASS/FAIL summary and a single exit code.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.golden import runners
from tests.golden.invariants import evaluate_expectations
from tests.golden.loader import get_case, list_cases

_EVIDENCE_CASE_IDS = [c["case_id"] for c in list_cases(category="evidence_acquisition")]
_STORY_MEMORY_CASE_IDS = [c["case_id"] for c in list_cases(category="story_memory")]
_UPDATE_CASE_IDS = [c["case_id"] for c in list_cases(category="update")]
_QUOTE_CASE_IDS = [c["case_id"] for c in list_cases(category="quote")]
_COPYWRITING_CASE_IDS = [c["case_id"] for c in list_cases(category="copywriting")]
_MEDIA_CASE_IDS = [c["case_id"] for c in list_cases(category="media")]
_PRESENTATION_CASE_IDS = [c["case_id"] for c in list_cases(category="presentation")]


def _assert_case(case_id: str, actual: dict) -> None:
    case = get_case(case_id)
    failures = evaluate_expectations(actual, case["expected"])
    assert not failures, (
        f"golden case {case_id!r} ({case['name']}) failed:\n" + "\n".join(f"  - {f}" for f in failures)
        + f"\n  provenance: {case['provenance']}\n  actual: {actual}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id", _EVIDENCE_CASE_IDS)
async def test_evidence_acquisition_golden_case(case_id: str, db_session: AsyncSession) -> None:
    actual = await runners.run_evidence_acquisition_case(get_case(case_id), session=db_session)
    _assert_case(case_id, actual)


@pytest.mark.parametrize("case_id", _STORY_MEMORY_CASE_IDS)
def test_story_memory_golden_case(case_id: str) -> None:
    actual = runners.run_story_memory_case(get_case(case_id))
    _assert_case(case_id, actual)


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id", _UPDATE_CASE_IDS)
async def test_update_golden_case(case_id: str, db_session: AsyncSession) -> None:
    case = get_case(case_id)
    pure_result = runners.run_update_case_pure(case)
    actual = pure_result if pure_result is not None else await runners.run_update_case_db(case, db_session)
    _assert_case(case_id, actual)


@pytest.mark.parametrize("case_id", _QUOTE_CASE_IDS)
def test_quote_golden_case(case_id: str) -> None:
    actual = runners.run_quote_case(get_case(case_id))
    _assert_case(case_id, actual)


@pytest.mark.parametrize("case_id", _COPYWRITING_CASE_IDS)
def test_copywriting_golden_case(case_id: str) -> None:
    actual = runners.run_copywriting_case(get_case(case_id))
    _assert_case(case_id, actual)


@pytest.mark.parametrize("case_id", _MEDIA_CASE_IDS)
def test_media_golden_case(case_id: str) -> None:
    actual = runners.run_media_case(get_case(case_id))
    _assert_case(case_id, actual)


@pytest.mark.parametrize("case_id", _PRESENTATION_CASE_IDS)
def test_presentation_golden_case(case_id: str) -> None:
    actual = runners.run_presentation_case(get_case(case_id))
    _assert_case(case_id, actual)


# ---------------------------------------------------------------------------------------------
# Harness self-tests (loader/discovery/filtering/malformed-fixture handling)
# ---------------------------------------------------------------------------------------------


def test_every_case_id_is_unique() -> None:
    all_ids = [c["case_id"] for c in list_cases()]
    assert len(all_ids) == len(set(all_ids))


def test_category_filter_returns_only_that_category() -> None:
    for category in ("evidence_acquisition", "story_memory", "update", "quote", "copywriting", "media", "presentation"):
        cases = list_cases(category=category)
        assert cases, f"expected at least one case in category {category!r}"
        assert all(c["category"] == category for c in cases)


def test_get_case_raises_key_error_for_unknown_id() -> None:
    with pytest.raises(KeyError):
        get_case("this-case-id-does-not-exist")


def test_malformed_fixture_missing_required_key_raises() -> None:
    import json
    import tempfile
    from pathlib import Path

    from tests.golden.loader import MalformedFixtureError, load_corpus

    malformed = {"cases": [{"case_id": "x", "name": "x"}]}  # missing category/failure_class/etc.
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(malformed, f)
        path = Path(f.name)
    try:
        with pytest.raises(MalformedFixtureError):
            load_corpus(path)
    finally:
        path.unlink()


def test_malformed_fixture_duplicate_case_id_raises() -> None:
    import json
    import tempfile
    from pathlib import Path

    from tests.golden.loader import MalformedFixtureError, load_corpus

    one_case = {
        "case_id": "dup", "name": "n", "category": "quote", "failure_class": "good_control",
        "kind": "deterministically_testable", "provenance": "p", "input": {}, "expected": {},
    }
    malformed = {"cases": [one_case, dict(one_case)]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(malformed, f)
        path = Path(f.name)
    try:
        with pytest.raises(MalformedFixtureError):
            load_corpus(path)
    finally:
        path.unlink()


def test_malformed_fixture_invalid_failure_class_raises() -> None:
    import json
    import tempfile
    from pathlib import Path

    from tests.golden.loader import MalformedFixtureError, load_corpus

    bad_case = {
        "case_id": "x", "name": "n", "category": "quote", "failure_class": "not_a_real_class",
        "kind": "deterministically_testable", "provenance": "p", "input": {}, "expected": {},
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({"cases": [bad_case]}, f)
        path = Path(f.name)
    try:
        with pytest.raises(MalformedFixtureError):
            load_corpus(path)
    finally:
        path.unlink()


def test_known_limitation_cases_are_not_silently_marked_fixed() -> None:
    """Every known_limitation case must document its current (unfixed) behavior, never assert a
    'fixed' outcome under a misleading label - the project's KNOWN_LIMITATION convention."""
    for case in list_cases():
        if case["failure_class"] == "known_limitation":
            assert "limitation" in case["expected"].get("note", "").lower() or "known" in case["name"].lower(), (
                f"{case['case_id']}: known_limitation case must document the limitation, not silently pass as fixed"
            )


def test_evaluate_expectations_reports_no_failures_on_exact_match() -> None:
    from tests.golden.invariants import evaluate_expectations

    assert evaluate_expectations({"a": 1, "b": "x"}, {"a": 1, "b": "x"}) == []


def test_evaluate_expectations_reports_failure_on_mismatch() -> None:
    from tests.golden.invariants import evaluate_expectations

    failures = evaluate_expectations({"a": 1}, {"a": 2})
    assert len(failures) == 1
    assert "a" in failures[0]


def test_evaluate_expectations_supports_in_gte_lte_contains_suffixes() -> None:
    from tests.golden.invariants import evaluate_expectations

    assert evaluate_expectations({"x": 5}, {"x__gte": 3, "x__lte": 10}) == []
    assert evaluate_expectations({"x": 5}, {"x__gte": 6}) != []
    assert evaluate_expectations({"outcome": "a"}, {"outcome__in": ["a", "b"]}) == []
    assert evaluate_expectations({"text": "hello world"}, {"text__contains": "hello"}) == []
    assert evaluate_expectations({"text": "hello world"}, {"text__not_contains": "goodbye"}) == []
