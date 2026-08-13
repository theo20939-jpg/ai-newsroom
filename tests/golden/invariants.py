"""Generic invariant evaluation: compares a case's declared `expected` dict (from the JSON
fixture) against the `actual` dict a category runner (tests/golden/runners.py) returned.

Deliberately NOT a registry of named semantic checks with their own bespoke logic - the real
semantic work (evidence/story/quote/media/presentation invariants) lives in the production
functions the runners call. This module is just the generic key-comparison layer, matching the
`__in`/`__contains`/`__not_contains`/`__gte`/`__lte` suffix DSL documented in the fixture's own
`_meta.schema_note`.
"""
from __future__ import annotations

from typing import Any

_SUFFIXES = ("__in", "__contains", "__not_contains", "__gte", "__lte")


def _base_key(key: str) -> tuple[str, str | None]:
    for suffix in _SUFFIXES:
        if key.endswith(suffix):
            return key[: -len(suffix)], suffix
    return key, None


def evaluate_expectations(actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """Returns a list of human-readable failure descriptions (empty list = every expectation
    held). `note`/`*__note` keys in `expected` are documentation only, never evaluated."""
    failures: list[str] = []
    for key, expected_value in expected.items():
        if key == "note" or key.endswith("__note"):
            continue
        base_key, suffix = _base_key(key)
        if base_key not in actual:
            failures.append(f"expected key {base_key!r} missing from actual result (actual keys: {sorted(actual.keys())})")
            continue
        actual_value = actual[base_key]

        if suffix is None:
            if actual_value != expected_value:
                failures.append(f"{base_key}: expected {expected_value!r}, got {actual_value!r}")
        elif suffix == "__in":
            if actual_value not in expected_value:
                failures.append(f"{base_key}: expected one of {expected_value!r}, got {actual_value!r}")
        elif suffix == "__contains":
            if expected_value not in (actual_value or ""):
                failures.append(f"{base_key}: expected to contain {expected_value!r}, got {actual_value!r}")
        elif suffix == "__not_contains":
            if expected_value in (actual_value or ""):
                failures.append(f"{base_key}: expected NOT to contain {expected_value!r}, got {actual_value!r}")
        elif suffix == "__gte":
            if not (actual_value >= expected_value):
                failures.append(f"{base_key}: expected >= {expected_value!r}, got {actual_value!r}")
        elif suffix == "__lte":
            if not (actual_value <= expected_value):
                failures.append(f"{base_key}: expected <= {expected_value!r}, got {actual_value!r}")
    return failures
