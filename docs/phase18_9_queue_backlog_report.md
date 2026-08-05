# Phase 18.9 M1 — Queue and Backlog Audit

Status: complete, strictly read-only. No task was acknowledged, deleted, purged, requeued, moved,
or otherwise mutated. No paid worker was started. All numbers below are direct `SELECT`-only
queries against the real database (the actual "queue," per M0 §1 - there is no separate Redis/
Celery broker to inspect).

## 1. Queue names

Not applicable in the broker sense (M0 §1). The two relevant "queues" are SQL predicates over
`EditorialTask`:
- `NEWS_ANALYSIS` queue: `status = CREATED AND workflow_name = 'NEWS_ANALYSIS' AND
  freshness <= 2h`
- `CONTENT_GENERATION` queue: `NEWS_ANALYSIS` sibling `COMPLETED`, score `>= 65`, no existing
  `CONTENT_GENERATION` task

## 2. Pending / active / reserved / scheduled / retry / dead-letter counts

| State | `NEWS_ANALYSIS` | `CONTENT_GENERATION` |
|---|---|---|
| `CREATED` (pending) | 11,917 | n/a (created only via `run_content_generation_for_event()`/`content_cycle.py`, not pre-created like analysis tasks) |
| `RUNNING` (active) | 2 (**stuck** - see M0 §6) | 0 |
| `COMPLETED` | 1,447 | 284 |
| `FAILED` (closest analog to dead-letter - no separate DLQ exists) | 504 | 89 |

"Reserved"/"scheduled"/"retry" in the Celery sense don't apply to this DB-polling design (M0 §7) -
there is no separate reservation state; a task is either `CREATED`, `RUNNING`, or terminal.
In-workflow step retries (M0 §5) are never a separate DB row/state, only `EditorialTask.retry_count`
incrementing in place.

## 3. Eligible-now backlog (within the 2h freshness cutoff)

**68 `NEWS_ANALYSIS` tasks** are eligible for automatic pickup right now (66 priority `S`, 2 other -
exact second priority tier not isolated in this pass). This is the *only* portion of the 11,917
`CREATED` backlog any currently-configured worker restart would actually touch (M0 §6).

## 4. Oldest task age

Oldest `CREATED` `NEWS_ANALYSIS` task: **2026-07-19** (≈17 days old at audit time). Newest:
2026-08-05 12:33 (a few minutes before this audit, from `automation_worker`, which has been
running continuously since Phase 18.8 M1).

## 5. Stale tasks from before 2026-08-02

**Yes, the overwhelming majority.** Of 11,917 `CREATED` `NEWS_ANALYSIS` tasks, all but a small
recent tail predate 2026-08-02 (the day the paid workers stopped) - real backlog accumulated over
~2.5 weeks of `automation_worker` running without `news_analysis_worker` keeping pace even before
the 08-02 stop (11,917 is far larger than what a few days' gap alone would produce, consistent with
`news_analysis_batch_size=5` per 300s cycle being a real, structural throughput ceiling below
`automation_worker`'s own collection rate).

## 6. Are all 13,520+ `NewsEvent` rows eligible for automatic processing?

**No.** Only events whose `COALESCE(published_at, collected_at)` falls within the rolling 2-hour
freshness window are ever eligible for `NEWS_ANALYSIS` pickup - confirmed both by the SQL predicate
(M0 §1) and directly by count (§3 above: 68 of several thousand recent events, out of a 13,520+
total corpus).

## 7. Did the 1,090 Phase 18.8 events already generate tasks?

**Yes, and more.** Of 1,253 `NewsEvent` rows created in the last 4 hours (the original 1,090 from
Phase 18.8 M2 plus further real growth from `automation_worker` continuing to run since), **all
1,253 already have a `NEWS_ANALYSIS` `EditorialTask`** - `automation_worker`'s own triage step
creates these automatically and immediately upon collection, independent of whether
`news_analysis_worker` is running to consume them (M0 §8).

## 8. Is `automation_worker` continuously adding paid-eligible tasks?

**Yes** - confirmed directly (§7) and structurally (M0 §8): every event `automation_worker`
collects gets a `NEWS_ANALYSIS` task created immediately, and that task becomes freshness-eligible
the moment it's created (age 0 < 2h cutoff). This is precisely why a bounded run must use an
explicit task/event-ID allowlist rather than a time-boxed worker restart (M4) - the eligible pool
is a continuously moving target.

## 9. Task type / failure-reason distribution

`NEWS_ANALYSIS` `FAILED`: 504 tasks, all recorded `error_type = "StepFailed"` (a generic top-level
classification - the granular underlying error lives in the per-step `WorkflowStepResult.error`
field, not aggregated in this pass; flagged as a real limitation, not silently omitted).
`CONTENT_GENERATION` `FAILED`: 89 tasks, same generic classification.

## Risk rating

| Paid worker | Risk if restarted unbounded (no allowlist) | Rating |
|---|---|---|
| `news_analysis_worker` | Would NOT touch the 11,917 historical backlog (freshness cutoff excludes it structurally) but WOULD begin consuming the 68-and-growing in-window pool automatically, 5 tasks/300s, real paid calls, indefinitely, with no per-run bound, no Telegram exposure, and real (if disclosed-imperfect, M0 §4) cost tracking | **CONTROL_REQUIRED** - safe to restart *bounded*; unsafe to restart in its normal unbounded form for a "controlled test batch" purpose specifically (indefinite, not finite/stoppable as this phase requires) |
| `content_worker` | Same batching/freshness structure as above, **plus** automatically sends real Telegram notifications for every successful draft (M0 §10) unless `CONTENT_GENERATION_DRY_RUN=true` (currently `false`) | **UNSAFE_TO_RESTART** in its normal form for this phase's purpose - the Telegram side effect alone violates this phase's explicit "no Telegram sends" restriction if the worker/cycle path is used as-is. Safe only via the isolated `run_content_generation_for_event()` function call path (M0 §10), never via `content_worker`/`content_cycle.py` itself. |
