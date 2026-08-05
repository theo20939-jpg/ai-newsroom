# Phase 18.9 M2 — Database State and Idempotency Audit

Status: complete, strictly read-only (`SELECT` only, verified no write executed). The pending
`meme_candidates` migration was **not** applied - out of scope, per instruction.

## 1. Table counts and states

| Table / state | Count |
|---|---|
| `NewsEvent`, total | 13,520+ (growing - `automation_worker` running) |
| `EditorialTask` `NEWS_ANALYSIS` `CREATED` | 11,917 |
| `EditorialTask` `NEWS_ANALYSIS` `RUNNING` | 2 (stuck - see below) |
| `EditorialTask` `NEWS_ANALYSIS` `COMPLETED` | 1,447 |
| `EditorialTask` `NEWS_ANALYSIS` `FAILED` | 504 |
| `EditorialTask` `CONTENT_GENERATION` `COMPLETED` | 284 |
| `EditorialTask` `CONTENT_GENERATION` `FAILED` | 89 |
| `ContentDraft`, total | 284 (exact 1:1 match with `CONTENT_GENERATION` `COMPLETED` - sane) |
| `AIExecution`, total | 4,632 (lifetime, $6.818684 recorded) |
| `AIExecution` created 2026-08-05 (today, before this audit's own future controlled run) | 0 |

Events awaiting analysis (`NEWS_ANALYSIS` not yet `COMPLETED`/`FAILED` for that event): the 11,917
`CREATED` (68 eligible-now, rest excluded by freshness - M1). Events awaiting generation: 1,073
`COMPLETED`-analysis events with no `CONTENT_GENERATION` task yet (raw count, before applying the
real `content_generation_min_score=65` filter `content_cycle.py` itself applies - not separately
recomputed here to avoid duplicating that filter's own logic incorrectly).

## 2. Duplicate / partially-completed executions

No duplicate `(event_id, workflow_type)` `EditorialTask` pair was found or is possible under
current code (M0 §12 - `_find_active_task()` blocks it at creation time, any status). "Partially
completed": the 2 stuck `RUNNING` tasks (M0 §6) are the one real example of a partial-completion
state that current code cannot resolve automatically.

## 3-9. Explicit answers

**1. Could restarting a worker process the entire historical corpus?**
No. `news_analysis_worker`'s own eligibility query structurally excludes anything older than the
2-hour freshness cutoff (M0 §6, M1 §6) - the 11,917-task historical backlog is invisible to it,
not merely deprioritized. A restart would only begin consuming the 68-and-growing in-window pool.

**2. Could it process all 1,090 (now 1,253+) newly collected events?**
Only their `NEWS_ANALYSIS` tasks, and only 5 at a time per 300s cycle (real throughput ceiling),
and only for as long as the worker keeps running (M1 §3, §7) - not "all at once," but yes,
eventually, if left running unbounded and continuously fed by `automation_worker`. This is exactly
why this phase requires an explicit allowlist rather than a bounded time window (M0 §8, M1 §8).

**3. Could the same event produce duplicate `AIExecution` records?**
Not duplicate *task-level* executions (idempotency, M0 §12) - but yes, multiple `AIExecution` rows
naturally exist per event by design (one per capability call, `research`/`intelligence`/`scoring`
for analysis, `research`/`intelligence`/`copywriting`/`quality` for content, plus one more per
retry, each tagged with its own `retry_number`) - "duplicate" in the sense of "more than one row
for the same event" is normal and expected, not a defect; "duplicate" in the sense of "the same
logical attempt billed twice" was not found to be possible under the atomic-claim design.

**4. Could a failed job be charged again on retry?**
**Yes, plausibly** - a step's `StepExecutionError` can originate from a real provider response that
failed a later validation/parsing check (not only from a pre-call rejection), and each retry
attempt runs the full step again, including a fresh provider call if the prior one is not being
reused. This was not empirically observed (0% real historical retry rate, M0 §5) but is a real,
code-permitted possibility and is explicitly included in the worst-case cost bound (M3), not
dismissed.

**5. Could content generation run without a successful analysis?**
No, not through the normal `content_worker` path (`_select_eligible_events()` requires a
`COMPLETED` `NEWS_ANALYSIS` sibling, M0 §1). `run_content_generation_for_event()` called directly
(the bounded tool M4 proposes using) does **not** itself check for a prior analysis - it creates
its own `CONTENT_GENERATION` task and runs `research`/`intelligence` fresh if needed (M0 §2's own
observation that `CONTENT_GENERATION`'s `research`/`intelligence` calls are rare, suggesting some
reuse mechanism exists but was not fully traced). **This means the bounded content-generation batch
(M4) must itself only select event IDs with a confirmed `COMPLETED` `NEWS_ANALYSIS` task**, not
rely on the tool to enforce that - a real design constraint for M4/M5, not an assumption.

**6. Could old drafts be regenerated?**
No - `create_task()`'s duplicate check (M0 §12) prevents a second `CONTENT_GENERATION` task for an
event that already has one in any status, including `COMPLETED`. An already-drafted event cannot
be silently redrafted by this mechanism.

**7. Can a finite batch be selected safely?**
Yes - by explicit `EditorialTask`/`NewsEvent` ID allowlist, bypassing both cycle functions' own
unbounded eligibility queries entirely (M4).

**8. Can the batch be isolated by explicit event IDs or task IDs?**
Yes, confirmed as the only genuinely bounded method available (M0 §10, M4) - both
`WorkflowRunner.run(session, task_id)` (for pre-existing `NEWS_ANALYSIS` tasks - 68 already exist,
real, eligible, no need to create new ones) and `run_content_generation_for_event(event_id)` (for
content) take a single explicit ID and touch nothing else.
