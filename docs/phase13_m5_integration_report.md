# Phase 13 — M5 Milestone Report: Offline Integration

## Status: GREEN

## Files changed (within authorized §4 scope)

**Tests (new)**: `tests/test_news_analysis_integration.py`

## What this milestone proves that earlier milestones did not

M1's own `tests/test_phase9_research_intelligence_integration.py` test proves the real 4-step
chain completes via a **direct** `WorkflowRunner.run()` call. M3's own `tests/test_analysis_
worker_cycle.py` proves `run_analysis_cycle()`'s own orchestration (eligibility, batch cap,
sequential execution, lost-race, mid-batch failure) using **ad hoc fake** `Capability` objects,
not the real ones. M5 closes the remaining gap: the **full**, real path — eligibility query →
atomic claim → `WorkflowRunner` → `CapabilityExecutor` → a `build_registry()`-constructed
`CapabilityRegistry` running the **real** `ResearchCapability`/`IntelligenceCapability`/
`EngagementCapability`/`ScoringCapability` implementations (never test doubles), `FakeLLMGateway`
underneath (never a real network call) — end to end via `run_analysis_cycle()` itself.

## Real-backlog isolation (mirrors M3's own incident and fix — applied correctly from the start
this time)

Every test in this file that calls `run_analysis_cycle()` uses the same `_isolated_freshness_
window` technique M3's incident established: `settings.news_analysis_freshness_cutoff_hours`
temporarily narrowed to 3 minutes, restored via fixture teardown. Verified after the full test
run: zero new suspicious (fake-signature) `COMPLETED` `NEWS_ANALYSIS` rows in the real backlog;
exactly the one pre-existing, unrelated legitimate row remains, as before.

## Proofs

1. **Full-chain completion**: `research → intelligence → engagement_analysis → scoring`, all
   `SUCCESS`, final status `COMPLETED`. Propagation: Engagement's own request (verified via the
   real gateway's `received_requests[2]`) contains both Research's facts and Intelligence's
   angle.
2. **`CONTENT_GENERATION`/`ContentDraft` boundary**: zero other `EditorialTask` rows for the same
   event, zero `ContentDraft` rows for the task — both mechanically queried, not merely asserted
   in prose.
3. **Freshness exclusion**: a stale (1h older than the isolated 3-minute window) test-owned task
   is never claimed — confirmed both by absence from `result.task_ids` and by direct query
   (`status` remains `CREATED`, untouched).
4. **Batch cap**: 6 test-owned eligible tasks inserted, `result.eligible_found == 5` and
   `len(result.task_ids) == 5` — the SQL `LIMIT`, not application-level truncation.
5. **Zero-pollution cleanup**: FK-safe `try/finally` (`ContentDraft` → `EditorialTask` →
   `NewsEvent` → `NewsSource`, in that order) — verified zero leftover `phase13-m5-integration-
   test-*` rows after the run.

## Validation run this milestone

- `pytest tests/test_news_analysis_integration.py` — **3 passed**.
- Real-backlog safety re-check (direct query) — zero new suspicious rows, zero regression from
  M3's earlier incident.
- DB pollution check — zero leftover test-owned rows.
- `ruff check tests/test_news_analysis_integration.py` — all checks passed.

## Deviations from the Plan

None of substance. `FakeLLMGateway`'s own documented "repeat the last response once exhausted"
behavior (not a Plan detail, a pre-existing fake-infrastructure convention) means the batch-cap
test's later tasks (beyond the first, which consumes all 4 queued responses) receive a
mismatched-shape response for their own first step and fail validation gracefully — this is
harmless and doesn't affect the test's own actual assertions (`eligible_found`/`task_ids` length),
which are about selection, not per-task completion.

M5 complete. Continuing to M6.
