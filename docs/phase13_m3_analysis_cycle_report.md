# Phase 13 — M3 Milestone Report: Eligibility Query + Analysis Cycle

## Status: GREEN (after an in-milestone incident, contained and fully remediated — see below)

## Files changed (within authorized §4 scope)

**Production (new)**: `worker/analysis_cycle.py`
**Production (modified, narrow, brought forward from M4 for mypy correctness — see Deviations)**:
`core/config.py` (4 new Settings fields)
**Tests (new)**: `tests/test_analysis_worker_cycle.py`

## Eligibility query — implemented exactly per §9.1

`.as_string()` is the sole JSON scalar-extraction syntax used; `.astext`/`cast(..., String)` do
not appear anywhere in the implementation. `EditorialTask.status == CREATED`, workflow-name match,
`JOIN NewsEvent`, `COALESCE(published_at, collected_at) >= cutoff`, `ORDER BY created_at ASC, id
ASC`, `LIMIT settings.news_analysis_batch_size` — all SQL-side, no Python-side scan.

## Incident during this milestone: accidental real-backlog mutation, contained and remediated

While writing `tests/test_analysis_worker_cycle.py`'s orchestration-level tests (which call the
real `run_analysis_cycle()`, not just `_select_eligible_task_ids()` directly), an initial test
design failed to account for the fact that `run_analysis_cycle()`'s own eligibility query is
deliberately unscoped (by design — the same query production uses). Against this shared dev
database's real backlog (confirmed elsewhere in this Plan's own audit chain: 1000+ genuinely
fresh-eligible `NEWS_ANALYSIS`/`CREATED` tasks), three early, un-isolated test runs each claimed
and "completed" up to 5 real production `EditorialTask` rows using the test's own fake
(`AlwaysSucceedsCapability`-shaped) capability output.

**Detected**: immediately, from the test's own assertion failures showing unexpected task IDs and
`eligible_found=5` counts far exceeding the 2-3 test-owned rows actually created.

**Root-caused**: real backlog rows, being hours older than freshly-created test rows, sort first
under `ORDER BY created_at ASC LIMIT 5` and are therefore *more* eligible than the test's own rows
— the real query has no test-scoping hook, exactly as designed for production use, which means a
test calling it unscoped against a populated shared database is unsafe.

**Fixed** (before any further test execution): added a module-local `_isolated_freshness_window`
pytest fixture that temporarily narrows `settings.news_analysis_freshness_cutoff_hours` to 0.05
hours (3 minutes) for the duration of any test that queries eligibility — confirmed via direct
read-only diagnostic that the real backlog's newest row is ~4.9 hours old, giving a wide, safe
margin. Applied to all 9 tests in the file for uniform safety. Re-run 3 additional consecutive
times after the fix — zero further backlog impact, confirmed by direct query each time.

**Damage assessed and reverted**: a direct query identified exactly 15 real `EditorialTask` rows
bearing the fake-capability output signature (`{"ok": True, "capability": <name>}`) newly marked
`COMPLETED`. All 15 were reverted to a pristine `CREATED` state — `status`, `workflow` (rebuilt via
the same `WorkflowExecutionState` construction `workflow_service.create_task()` itself uses:
`current_step` set to the resolved definition's first step, `completed_steps=[]`,
`step_results=[]`, `iteration_count=0`, `failure=None`), and `retry_count=0` — using each row's own
real `workflow_name`/`workflow_version` and the real `workflows.registry.registry` to resolve the
correct first-step name. `created_at` was preserved (not touched); `updated_at` reflects the
remediation. Verified directly afterward: all 15 rows pristine `CREATED`; exactly one legitimate,
pre-existing `COMPLETED` `NEWS_ANALYSIS` row remains (unrelated, predates this session); zero
other suspicious rows found repository-wide.

This is disclosed in full here per the operating instructions' transparency requirement — it was a
genuine, real mutation of shared, unrelated production data, caused by this milestone's own new
test code, contained and fully reversed within the same milestone before proceeding.

## Validation run this milestone

- `pytest tests/test_analysis_worker_cycle.py` — **9 passed**, re-run 3 additional times for
  stability (all green, zero flakiness, zero further backlog impact each time).
- `pytest tests/test_phase10_workflow_integration.py` — **1 passed** (`CONTENT_GENERATION`
  non-regression).
- `grep` of `worker/analysis_cycle.py` for `run_content_generation_for_event`/
  `CONTENT_GENERATION`/`ContentDraft`/Telegram — zero matches.
- `ruff check` on all 3 M3-touched files — all checks passed.
- `mypy` on `worker/analysis_cycle.py`/`core/config.py` — no issues found.
- `python -m scripts.validate_architecture` — 0 violations.
- DB pollution check: zero leftover `phase13-analysis-cycle-test-*` rows.

## Deviations from the Plan

1. `core/config.py`'s 4 new Settings fields (nominally M4's own scope) were added during M3, not
   M4 — `worker/analysis_cycle.py`'s own eligibility query references `settings.news_analysis_
   batch_size`/`settings.news_analysis_freshness_cutoff_hours`, which cannot type-check under
   `mypy` until those fields exist. This is a mechanical ordering necessity (M3's own code is not
   mypy-clean without it), not a scope or architecture change — both files remain inside the
   already-authorized 8-file production scope, and M4 does not need to repeat this addition.
2. `run_analysis_cycle()`'s parameter order is `(capability_registry, session_factory=async_
   session_factory)`, not `(session_factory, capability_registry)` as the Plan's own pseudocode
   literally ordered — Python requires parameters with defaults to follow those without; giving
   `session_factory` a real default (mirroring `services/triage_orchestrator.py::run_triage_
   cycle()`'s own established convention) necessitated this reordering. Purely mechanical; the
   function's behavior is unchanged.
3. The accidental real-backlog mutation and its full remediation (above) — not a Plan deviation
   per se, but a real incident during implementation, disclosed in full.

M3 complete, backlog integrity re-verified. Continuing to M4.
