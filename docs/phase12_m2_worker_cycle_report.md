# Phase 12 — M2 Worker Cycle Report

## Changes

**`worker/__init__.py`** (new) — docstring only, matching `bot/__init__.py`'s own convention.

**`worker/cycle.py`** (new) — `AutomationCycleResult` dataclass (`started_at`, `finished_at`,
`duration_seconds`, `collection: CollectionReport`, `triage: TriageCycleReport`) and
`run_automation_cycle()`: calls `run_collection_cycle()` then `run_triage_cycle()` sequentially,
both imported as module-level names (`from services.collector import ... run_collection_cycle`,
`from services.triage_orchestrator import ... run_triage_cycle`) so tests can monkeypatch
`worker.cycle.run_collection_cycle`/`worker.cycle.run_triage_cycle` directly. Catches nothing itself
— `run_collection_cycle()` never raises (its own outer `try/except Exception`), and
`run_triage_cycle()`'s real top-level exception (if any) propagates through unmodified; the one
cycle-level `except Exception` handler belongs to `worker/main.py` (M3), not here.

**`tests/test_worker_cycle.py`** (new) — 6 tests.

## Verification

- `pytest tests/test_worker_cycle.py -v` — **6 passed**: collection-before-triage ordering
  (exactly once each), triage still runs after a collection result reflecting source-level
  failures, an ordinary `Exception` from `run_triage_cycle` propagates out of
  `run_automation_cycle()` uncaught (not swallowed here — that's `worker/main.py`'s job),
  `asyncio.CancelledError` from `run_triage_cycle` propagates uncaught, a mechanical AST-based check
  confirms `worker/cycle.py` imports none of `workflows.runner`/`capabilities.executor`/any
  `capabilities.*`/`scripts.run_content_generation`, and `AutomationCycleResult.duration_seconds`
  is consistent with its own `started_at`/`finished_at` timestamps.
- `ruff check worker/__init__.py worker/cycle.py tests/test_worker_cycle.py` — **all checks
  passed**.
- `mypy worker/cycle.py tests/test_worker_cycle.py` — **clean, no issues found**.

No deviation from the frozen Contract §6/Plan §8 design. No pre-existing defect encountered.

**M2 complete. Proceeding to M3.**
