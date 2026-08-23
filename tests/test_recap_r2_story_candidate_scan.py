"""NINJA PULSE RECAP Phase R2 - pure-logic tests for scripts/_recap_r2_story_candidate_scan.py's
ranking helpers.

Mirrors tests/test_recap_r2_single_attempt_gateway.py's own established pattern for testing a
`_`-prefixed diagnostic script's pure helper functions via `importlib` (scripts/ has no package
`__init__.py`, so a plain `import scripts._recap_r2_story_candidate_scan` is not available) - never
a DB-backed end-to-end test of the script's own read-only scan, which needs a real database and is
out of scope for this offline test suite. Only `_sort_key()` (pure, deterministic) is exercised
here; `_scan_story()`/`_run()` themselves are unit-untestable without a live Story fixture, exactly
like `_recap_r2_event_shadow.py`'s own DB-touching `main()` is never unit-tested either."""
from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "_recap_r2_story_candidate_scan",
    Path(__file__).resolve().parent.parent / "scripts" / "_recap_r2_story_candidate_scan.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
# Registered in sys.modules BEFORE exec - `@dataclass(frozen=True)` on CandidateRow needs
# `sys.modules[cls.__module__]` to already exist while the class body executes (a plain
# module_from_spec()+exec_module() without this registration raises AttributeError on Python 3.13
# for any frozen dataclass defined in the executed module - confirmed by direct execution).
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

CandidateRow = _MODULE.CandidateRow
_sort_key = _MODULE._sort_key


def _row(*, announcement_count: int | None, event_count: int, rejected: bool = False) -> CandidateRow:
    return CandidateRow(
        story_id=uuid.uuid4(), title="t", event_count=event_count,
        announcement_count=announcement_count,
        readiness_state=None if rejected else "ACTIVE",
        readiness_source_count=None if rejected else 1,
        evidence_reference_count=None if rejected else 1,
        integrity_status="rejected" if rejected else "eligible",
        rejection_reason="no confirmed events" if rejected else None,
    )


def test_sort_key_orders_by_announcement_count_first():
    high_announcements = _row(announcement_count=5, event_count=3)
    low_announcements_more_events = _row(announcement_count=2, event_count=10)
    rows = sorted([low_announcements_more_events, high_announcements], key=_sort_key, reverse=True)
    assert rows[0] is high_announcements


def test_sort_key_breaks_ties_by_event_count():
    fewer_events = _row(announcement_count=4, event_count=3)
    more_events = _row(announcement_count=4, event_count=9)
    rows = sorted([fewer_events, more_events], key=_sort_key, reverse=True)
    assert rows[0] is more_events


def test_sort_key_ranks_rejected_rows_last_regardless_of_event_count():
    """A Story build_event_recap_candidate() rejected outright (announcement_count=None) is never
    a usable shadow-synthesis candidate, even if its raw event_count happens to be large."""
    rejected_high_event_count = _row(announcement_count=None, event_count=50, rejected=True)
    built_low_event_count = _row(announcement_count=1, event_count=2)
    rows = sorted([rejected_high_event_count, built_low_event_count], key=_sort_key, reverse=True)
    assert rows[0] is built_low_event_count
