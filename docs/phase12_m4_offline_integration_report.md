# Phase 12 — M4 Offline Integration Report

## Changes

**`tests/test_automation_integration.py`** (existing file from M1, extended) — 3 new tests added to
the existing `factory`/`test_source` fixtures and `_fake_seam()` helper:

1. **Full chain proof**: fake `source_pack_loader`/`adapter_resolver_factory` (2 canned items) →
   real `run_collection_cycle(session_factory=independent_session_factory-derived factory, ...)` →
   2 committed `NewsEvent` rows → real `run_triage_cycle(session_factory=...)` → 2 committed
   `EditorialTask(status=CREATED)` rows, scoped-asserted (not a raw report-count assertion, since
   `run_triage_cycle()` re-queries **all** eligible `NewsEvent` rows in the shared database, not
   just this test's own) → mechanical **zero-rows** assertions (not "no exception") that no
   `AIExecution` or `ContentDraft` row exists whose `task_id` is among this test's own
   `EditorialTask` ids.
2. **Dedup proof**: same fake seam, same `external_id`, polled twice — first poll creates 1
   `NewsEvent`, second poll creates 0 (`duplicates_skipped == 1`), exercising the real, unmodified
   `services/deduplication.py::is_duplicate()` path.
3. **Duplicate-active-task proof**: after one collection + one triage pass, a **second**
   `run_triage_cycle()` call (simulating the next scheduled cycle) creates zero additional
   `EditorialTask` rows for the same event — exercising `DuplicateActiveTaskError`'s existing,
   unmodified catch in `_run_phase_b()`.

No production file was touched in this milestone — only the test file.

## Verification

- `pytest tests/test_automation_integration.py -v` — **10 passed** (7 from M1 + 3 new M4 tests),
  17.5s total (real Postgres round-trips for collection + triage + assertions + FK-safe cleanup).
- **Post-test pollution check** (M5's own mandatory gate, run here as an early proof): direct query
  for any `NewsSource` row matching `phase12-integration-test-%` and any `NewsEvent` row matching
  this run's own test article titles — **zero rows found**. Test-owned cleanup (children-first:
  `EditorialTask` → `NewsEvent` → `NewsSource`, via the `test_source` fixture's `finally` block)
  worked correctly across all three new tests.
- `ruff check tests/test_automation_integration.py` — **all checks passed**.
- `mypy services/collector.py tests/test_automation_integration.py` — clean except the same
  pre-existing, unrelated `telethon.errors` stub warning noted in M1 (confirmed present at `HEAD`,
  not caused by this milestone).
- `mypy tests/fakes/fake_source_adapter.py` (checked in isolation to avoid a benign
  double-module-path mypy artifact when passed alongside files that import it transitively) —
  **clean, no issues found**.

No pre-existing collector defect was discovered during this milestone — every assertion passed on
the first corrected run (after M1's own `FakeAdapterRegistry` scoping fix, already applied before
M4 began).

**M4 complete. Proceeding to M5.**
