"""Loads and validates tests/fixtures/news_golden_cases.json. Pure, no I/O beyond the one read."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "news_golden_cases.json"

_REQUIRED_CASE_KEYS = {"case_id", "name", "category", "failure_class", "kind", "provenance", "input", "expected"}
_VALID_FAILURE_CLASSES = {"real_regression", "known_limitation", "good_control", "negative_control"}
_VALID_KINDS = {"deterministically_testable", "requires_live_validation"}


class MalformedFixtureError(ValueError):
    """Raised when tests/fixtures/news_golden_cases.json fails structural validation."""


def _validate_case(case: dict[str, Any]) -> None:
    missing = _REQUIRED_CASE_KEYS - case.keys()
    if missing:
        raise MalformedFixtureError(f"case {case.get('case_id', '<unknown>')!r} missing required keys: {sorted(missing)}")
    if case["failure_class"] not in _VALID_FAILURE_CLASSES:
        raise MalformedFixtureError(
            f"case {case['case_id']!r} has invalid failure_class {case['failure_class']!r}, "
            f"must be one of {sorted(_VALID_FAILURE_CLASSES)}"
        )
    if case["kind"] not in _VALID_KINDS:
        raise MalformedFixtureError(
            f"case {case['case_id']!r} has invalid kind {case['kind']!r}, must be one of {sorted(_VALID_KINDS)}"
        )


def load_corpus(path: Path | None = None) -> dict[str, Any]:
    """Reads and structurally validates the fixture. Raises MalformedFixtureError on any
    structural problem - never silently skips a malformed case."""
    fixture_path = path or _FIXTURE_PATH
    try:
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MalformedFixtureError(f"{fixture_path} is not valid JSON: {exc}") from exc

    if "cases" not in data or not isinstance(data["cases"], list):
        raise MalformedFixtureError(f"{fixture_path} must contain a top-level 'cases' list")

    seen_ids: set[str] = set()
    for case in data["cases"]:
        _validate_case(case)
        case_id = case["case_id"]
        if case_id in seen_ids:
            raise MalformedFixtureError(f"duplicate case_id: {case_id!r}")
        seen_ids.add(case_id)

    return data


def list_cases(*, category: str | None = None, path: Path | None = None) -> list[dict[str, Any]]:
    """All cases, optionally filtered to one category. Order matches the fixture file."""
    cases = load_corpus(path)["cases"]
    if category is not None:
        cases = [c for c in cases if c["category"] == category]
    return cases


def get_case(case_id: str, *, path: Path | None = None) -> dict[str, Any]:
    for case in load_corpus(path)["cases"]:
        if case["case_id"] == case_id:
            return case
    raise KeyError(f"no golden case with case_id={case_id!r}")


def categories(*, path: Path | None = None) -> list[str]:
    seen: list[str] = []
    for case in load_corpus(path)["cases"]:
        if case["category"] not in seen:
            seen.append(case["category"])
    return seen
