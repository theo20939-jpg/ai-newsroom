# Phase 18.9 M0 — Runtime and Paid-Path Discovery

## ⚠ INCIDENT DISCLOSURE — a real paid OpenAI call occurred during this phase's own M6 test
development, in violation of Section A's "no paid call" restriction. Read this section first.

**What happened**: while writing `tests/test_phase18_9_controlled_batch.py` (M6, before any
Section B authorization was sought), a budget-check test
(`test_task_refused_when_conservative_estimate_would_exceed_remaining_budget`) called
`run_bounded_analysis_batch(..., max_budget_usd=Decimal("0.01"), dry_run=False)` expecting the
budget guard to refuse the task before any real execution. Instead, the task ran to `"completed"`.

**Root cause**: `scripts/phase18_9_controlled_batch_runner.py`'s original budget-check helper
(`_cumulative_cost_since_run_start`) computed "spend so far" as a *delta between two calls* using
a mutable "already-seen row IDs" set. Its first call (empty set) summed the **entire historical
`ai_executions` table** (4,632 real rows, ~$6.82) as an implicit "baseline." Its second call
(inside the per-task loop) summed only *new* rows (none yet) and the code computed
`spent_this_run = current_total − baseline_cost ≈ $0 − $6.82 = −$6.82`. Adding the $0.035
conservative per-task estimate to a deeply negative number can never exceed any positive budget -
the check was structurally incapable of ever refusing a task, regardless of `max_budget_usd`.
Because the function's earlier design also built the **real**
`assemble_ai_integration_layer()` unconditionally (before any budget check), the test's
`dry_run=False` call proceeded past the (non-functioning) budget gate and reached a genuine
`WorkflowRunner.run()` execution against the real, production-configured OpenAI provider.

**Confirmed real, via evidence independent of the (rolled-back) Postgres test transaction**: the
test used `tests/conftest.py`'s `db_session` fixture (a SAVEPOINT wrapped in a transaction that is
always rolled back), so no `EditorialTask`/`AIExecution` row from this incident persisted in
Postgres (`ai_executions` remains 4,632 rows, unchanged). However, `services/cost_tracker.py::
RedisCostTracker.record()`'s Redis writes are **not** part of any Postgres transaction and are
**not** rolled back. A direct, read-only inspection of today's Redis cost ledger
(`docker exec ai_newsroom_redis redis-cli KEYS 'phase7:cost_ledger:2026-08-05*'`) found:

| Ledger key | Value |
|---|---|
| `phase7:cost_ledger:2026-08-05` (global) | $0.006766 |
| `phase7:cost_ledger:2026-08-05:research` | $0.043028 (up from $0.042 pre-incident - a real +$0.001028 delta) |
| `phase7:cost_ledger:2026-08-05:intelligence` | $0.002432 (new key - did not exist before) |
| `phase7:cost_ledger:2026-08-05:engagement` | $0.002460 (new key - did not exist before) |
| `phase7:cost_ledger:2026-08-05:scoring` | $0.000846 (new key - did not exist before) |

$0.001028 + $0.002432 + $0.002460 + $0.000846 = **$0.006766**, exactly matching the global key -
internally consistent, not coincidental. This confirms a real `NEWS_ANALYSIS` workflow executed
all four of its steps (`research`/`intelligence`/`engagement`/`scoring`) for real, against the real
OpenAI API, incurring **$0.006766** in real, actual, non-reversible cost.

**Correction to §2 below**: this is also new, real evidence that `engagement` (the
`engagement_analysis` step) **is** a real, paid, LLM-calling capability - §2's original inference
that it was "very likely... zero-LLM-call" was wrong, corrected here rather than silently left
standing. (Its cost does not appear in the `ai_executions` table's `AICapability` enum breakdown
because that specific row was never committed to Postgres - only the independent Redis write
survived.)

**Fix applied immediately, before any further testing**: `_cumulative_cost_since_run_start` was
removed and replaced with `_cost_spent_since(session, run_started_at)` - a single, stateless
`SELECT SUM(cost) WHERE created_at >= run_started_at` query, eliminating the entire class of
stateful-delta bug. Both batch-runner functions were also changed to **never** construct the real
AI integration layer unless a task has already passed both the budget check and the eligibility
check (previously constructed unconditionally). `tests/test_phase18_9_controlled_batch.py` was
rewritten so **every** `dry_run=False` test now injects a `_PoisonPillCapabilityRegistry` (raises
immediately on any attribute access) instead of ever letting a test reach the real registry - a
structural guarantee, not a reliance on the budget logic being correct. A new test
(`test_poison_pill_registry_fires_when_budget_and_eligibility_both_pass`) proves the poison pill
itself actually fires when reached. A new regression test
(`test_large_preexisting_historical_cost_does_not_produce_negative_spend`) directly targets the
exact bug class with a $1,000 simulated historical baseline. All 21 tests in the file now pass
against the fixed implementation.

**Real-world financial impact**: at minimum the sum of `intelligence`/`engagement`/`scoring`
($0.005738) plus some (not fully separable) contribution to `research` - see the dedicated,
evidence-preserving `docs/phase18_9_incident_snapshot.md` for the full, later investigation,
which found and root-caused a **second, unrelated** ledger increase this report's own investigation
had not yet resolved when first written. That second increase ($0.007000 exactly) is **not** part
of this incident - it is a pre-existing, unrelated test-hygiene defect in
`tests/test_api_cost_optimization_checklist.py` (a real cost-formula write using a fake, no-network
`CapabilityCall`, with an incomplete cleanup that leaks into the real calendar-date Redis
namespace). Read `docs/phase18_9_incident_snapshot.md` §7/§10 for the full, exact reasoning and the
final, careful incident classification (confirmed vs. suspected vs. unresolved) - this section is
intentionally left as originally written, not silently edited, with the correction layered on top
via the snapshot document instead, so the investigation's own history remains visible. The user's
real OpenAI usage dashboard remains the only fully authoritative source for the genuine incident's
exact dollar cost; it was not and cannot be checked from this environment. No further
`dry_run=False` call was or will be made against a real capability registry, and no further test
suite will be run at all, until hard isolation (poison-pill registry + no real API key available to
the test process + blocked/redirected OpenAI network egress - at least two independent barriers)
is in place and independently confirmed.

---


Status: complete, read-only. Every claim below is traced to real source code and/or real database/
Redis state (read-only queries), never inferred from naming alone, per this milestone's own
requirement. Findings are explicitly labeled **CONFIRMED** / **INFERRED** / **UNKNOWN** /
**UNSAFE/MISSING CONTROL**.

## 1. Which queues each worker consumes

**CONFIRMED.** There is no message broker (no Celery, no Redis pub/sub task queue). The "queue"
is a Postgres table: `EditorialTask` rows filtered by `status`/`workflow_name`/freshness, selected
by plain SQL (`worker/analysis_cycle.py::_select_eligible_task_ids()`,
`worker/content_cycle.py::_select_eligible_events()`). Redis is used only for the cost ledger
(`services/cost_tracker.py`) and the LLM Gateway's fallback/health-store machinery - never as a
task queue.

- `news_analysis_worker` consumes: `EditorialTask` rows where `status = CREATED`,
  `workflow->>'workflow_name' = 'NEWS_ANALYSIS'`, and `COALESCE(published_at, collected_at) >=
  now() - news_analysis_freshness_cutoff_hours`. `LIMIT news_analysis_batch_size` (5, coded
  default, not overridden in `.env`).
- `content_worker` consumes: `EditorialTask` rows where the paired `NEWS_ANALYSIS` task is
  `COMPLETED`, scored `>= content_generation_min_score` (65, `.env`-set), and no
  `CONTENT_GENERATION` task already exists for that event. `LIMIT content_generation_batch_size`
  (5, `.env`-set).

## 2. Which task types invoke paid OpenAI calls

**CONFIRMED**, from real `ai_executions` history (4,632 rows, $6.818684 lifetime recorded spend)
**and** from the real incident documented above:
- `NEWS_ANALYSIS`: capabilities `RESEARCH`, `INTELLIGENCE`, `SCORING` all show real OpenAI cost in
  `ai_executions`. A 4th step, `engagement_analysis` (capability name `"engagement"`), is defined
  in `workflows/definitions/news_analysis.py`; `"engagement"` does not appear in `database.models.
  ai_execution.AICapability`'s enum nor in any *committed* `ai_executions` row, which this audit's
  first draft mis-read as evidence it was a free, zero-LLM-call step. **That inference was wrong,
  corrected here**: the real incident above shows a genuine `phase7:cost_ledger:2026-08-05:
  engagement` Redis-ledger entry ($0.00246) from a real workflow execution - `engagement` is a
  real, paid, LLM-calling capability. Its absence from the `AICapability` enum/`ai_executions`
  table is a real, separate finding of its own (a capability whose cost the *durable* database
  record apparently cannot represent, or was simply never committed in this specific rolled-back
  case - not fully distinguished in this audit), not evidence it is free. **All 4 `NEWS_ANALYSIS`
  steps are paid.**
- `CONTENT_GENERATION`: capabilities `RESEARCH`, `INTELLIGENCE` (rare - see §5), `COPYWRITING`,
  `QUALITY` all show real OpenAI cost.

## 3. Provider/model selection code path

**CONFIRMED.** `integrations/llm_gateway/routing/engine.py` ranks candidate models; a real
**fallback chain** exists (`integrations/llm_gateway/fallback/policy.py::FallbackPolicy`) - a
single capability call CAN attempt more than one model/provider in sequence if an earlier
candidate fails (bounded by `fallback.max_fallback_attempts`/`max_cost_multiplier`/
`max_additional_cost` - real, existing eligibility filtering, not unbounded). Real observed models
in production history: `gpt-5.6-luna` (cheap, dominant - >95% of real calls), `gpt-5.6-sol`
(expensive, rare - fallback/escalation tier), `gpt-5.6-terra` (mid-tier, rare).

## 4. Token usage / cost recording path

**CONFIRMED**, two genuinely **independent** write operations, both triggered from
`capabilities/executor.py` after a real provider call returns:
- `services/cost_tracker.py::RedisCostTracker.record()` - increments two Redis keys
  (`phase7:cost_ledger:{date}` global, `phase7:cost_ledger:{date}:{capability}` per-capability)
  via `INCRBYFLOAT`. **Write failures are silently swallowed** (`except Exception: return` -
  explicitly documented as intentional, "§18: write failure is a cost-audit data-loss risk, never
  call-blocking").
- A durable `AIExecution` row (`database/models/ai_execution.py`) - a separate persistence path
  (`services/ai_execution_mapper.py`, not traced line-by-line in this pass).

**UNSAFE/MISSING CONTROL - real, currently-open discrepancy found and investigated (not
assumed away):** `docker exec ai_newsroom_redis redis-cli KEYS 'phase7:cost_ledger:2026-08-05*'`
shows `phase7:cost_ledger:2026-08-05:research` = **$0.042**, but a direct query of `ai_executions`
for `created_at::date = '2026-08-05'` returns **0 rows**, and the *global* ledger key
`phase7:cost_ledger:2026-08-05` (the one `BudgetGuard.check()` actually reads) **does not exist**
(`TTL` = -2, i.e., absent). Investigated and ruled out: clock skew (Postgres `now()` and Redis
`TIME` both agree it is genuinely 2026-08-05); test pollution from `tests/test_cost_tracker_real.py`
/`tests/test_budget_guard_real.py` (both use per-test UUID `ledger_namespace`s with explicit
teardown deletion - verified via `grep`, not assumed); `automation_worker`/`telegram_bot` calling
a capability (both verified to import zero LLM/capability/OpenAI modules). Root cause **not fully
traced** within this audit's scope - the code confirms the two write paths are independent and one
can silently fail without the other, which is *sufficient* to explain drift, but the exact
historical call that produced this specific $0.042 was not identified. **Practical consequence for
§M3/M4**: the global ledger `BudgetGuard.check()` reads is currently effectively $0 for today, but
this finding means the ledger's own write-reliability has a real, demonstrated gap - a caveat on
how much to trust it as a hard technical backstop, disclosed rather than hidden.

## 5. Retry policy / max retry count / timeout behavior

**CONFIRMED**, both workflow definitions (`workflows/definitions/news_analysis.py`,
`content_generation.py`) are identical in shape: 4 steps, each `max_attempts=3` (schema default,
`schemas/workflow.py`, hard-capped `le=10`), `max_iterations=3`, overall workflow
`timeout_seconds=120`, per-step `timeout_seconds=30`. A step's `StepExecutionError`/
`StepTimeoutError` is retried up to `max_attempts` within the *same* task (never a new task) -
`EditorialTask.retry_count` increments per retry. **Every real historical `ai_executions` row has
`retry_number = 0`** - zero retries have ever actually occurred in this system's real history, so
the retry *rate* is empirically ~0%, though the *ceiling* (up to 3 attempts/step) remains real and
must be used for worst-case bounding (§M3), not the empirical 0%.

## 6. Requeue / stale-task / historical-backlog behavior

**CONFIRMED**, real database state (read-only, not mutated):
- **11,917 `NEWS_ANALYSIS` tasks sit `CREATED`**, dating back to 2026-07-19 - the historical
  backlog. Only **68** are within the current 2-hour freshness cutoff
  (`NEWS_ANALYSIS_FRESHNESS_CUTOFF_HOURS=2`, `.env`-set) and thus visible to
  `_select_eligible_task_ids()` right now. **The freshness cutoff is a real, working control**:
  restarting `news_analysis_worker` normally would *not* process the 11,917 backlog (they are
  permanently invisible to the eligibility query as currently designed, not merely deprioritized)
  - it would process only the 68 in-window tasks, 5 per 300s cycle.
- **A failed `EditorialTask` is never automatically retried/requeued.** `services/
  workflow_service.py::_find_active_task()` blocks creating a second task for the same
  `(event_id, workflow_type)` in *any* status (including `FAILED`) - a real, deliberate,
  already-fixed-once bug-history control (its own docstring: a Phase 15 M0 bug let 108 duplicate
  `NEWS_ANALYSIS` tasks get created before this was widened to check every status, not just
  `CREATED`/`RUNNING`).
- **UNSAFE/MISSING CONTROL - confirmed, currently real**: 2 `EditorialTask` rows are stuck in
  `RUNNING` status (`NEWS_ANALYSIS`, dated 2026-07-25 and 2026-08-02 - almost certainly from a
  worker being killed mid-task, e.g. the 2026-08-02 21:09 shutdown Phase 18.8 M0 already
  documented). `services/triage_orchestrator.py::_select_recovery_candidates()` exists but only
  recovers stale `NewsEvent.status = PROCESSING` claims *before* a task is created - it does
  **not** cover an `EditorialTask` stuck in `RUNNING` *after* being claimed. No code path was
  found that ever resets these 2 tasks. They will remain `RUNNING` forever under current code,
  invisible to every eligibility query (which all filter on `CREATED`/`COMPLETED`), and their
  events can never get a fresh task either (`_find_active_task` still finds them). Real, disclosed
  gap - not touched or fixed in this phase.

## 7. Worker concurrency / prefetch

**CONFIRMED.** Both `run_analysis_cycle()` and the content-generation equivalent process their
selected batch **sequentially** (a plain `for` loop, one `async with session_factory()` block at a
time, no `asyncio.gather`) - concurrency is effectively **1** by construction, not a configurable
setting. "Prefetch" in the Celery sense doesn't apply to this DB-polling design; the closest analog
is the batch-size `LIMIT` (5), and all 5 rows are fetched up front but executed one at a time.

## 8. Can scheduled automation keep creating new paid tasks while workers run?

**CONFIRMED, yes** - `automation_worker` (currently running, restarted in Phase 18.8) creates
`NEWS_ANALYSIS` `EditorialTask` rows continuously as it collects+triages real news, independent of
whether `news_analysis_worker` is running. This is exactly why a *bounded* run (explicit task-ID
allowlist, §M4) is necessary rather than a time-boxed worker restart - the eligible pool keeps
growing underneath any such window.

## 9. Can analysis automatically trigger content generation?

**CONFIRMED, no** - they are two independent worker loops, each with its own DB-polling
eligibility query. `content_worker` discovers already-`COMPLETED` `NEWS_ANALYSIS` events on its
own schedule; nothing in `news_analysis_worker`'s own code path calls into content generation.

## 10. Can content generation trigger Telegram sends?

**CONFIRMED, yes - a critical finding for Section B's design.** `worker/content_cycle.py` (the
*cycle* orchestrator `content_worker` normally runs) imports `services.telegram_notifier.
send_editorial_card` and `services.image_preview_notifier.send_news_with_image_preview` directly,
and sends a real Telegram notification for every successfully-generated `ContentDraft`, gated only
by `CONTENT_GENERATION_DRY_RUN` (currently **`false`** in the real `.env` - live) and a fact-safety
enforcement check. **`scripts/run_content_generation.py::run_content_generation_for_event()`
(the function `content_cycle.py` itself calls to do the actual generation) contains zero Telegram/
image-preview import** - Telegram-sending is purely `content_cycle.py`'s own additional
orchestration layered on top, not part of the generation function itself. This is the basis for
§M4's controlled-run design: call `run_content_generation_for_event()` directly, never go through
`content_cycle.py`/`content_worker`'s normal cycle, and Telegram sending is structurally impossible
via that path.

## 11. Can one NewsEvent generate multiple paid calls?

**CONFIRMED, yes** - up to 4 capability calls for `NEWS_ANALYSIS` (research/intelligence/
[engagement, likely free]/scoring) plus, if content generation later runs for the same event, up
to 4 more (research/intelligence/copywriting/quality) - up to 8 total paid capability calls across
one `NewsEvent`'s full lifecycle, each potentially retried up to 3x and each potentially attempting
more than one model via the fallback chain.

## 12. Idempotency / duplicate-execution protections

**CONFIRMED, real, layered protection**:
1. `workflows/runner.py::WorkflowRunner.run()` claims a task via an atomic
   `UPDATE ... WHERE status = CREATED SET status = RUNNING` (`rowcount == 1` check) - a genuine
   compare-and-swap, safe against two workers claiming the same task.
2. `services/workflow_service.py::create_task()` refuses to create a second task for the same
   `(event_id, workflow_type)` in any status (`DuplicateActiveTaskError`).
3. Real consequence: a `NewsEvent` cannot get two `NEWS_ANALYSIS` (or two `CONTENT_GENERATION`)
   `EditorialTask` rows, and a claimed task cannot be claimed twice. **A retry cannot produce a
   duplicate `AIExecution` row for the "same" logical attempt** (each real attempt, retried or not,
   gets its own `retry_number`-tagged row - by design, not a bug) - but a retry *does* mean
   possible additional real cost for what looks like "one task" (§M3).

## 13. Existing budget guards

**CONFIRMED, a real, already-implemented mechanism exists** - not something this phase needs to
build (`services/budget_guard.py::RedisBudgetGuard`, consulted by `FallbackPolicy` before each
dispatch attempt, three modes `off`/`shadow`/`enforce`). Current real, unmodified defaults
(`core/config.py`, none overridden in `.env`):

```
llm_budget_mode: Literal["off", "shadow", "enforce"] = "shadow"
llm_daily_warning_usd: float = 0.50
llm_daily_budget_usd: float = 1.00
```

**Currently in `"shadow"` mode - computes and logs the deny decision but never actually blocks a
call.** This is a **daily**, **global** (shared across all capabilities/workflows, not scoped to
any one batch or run) ceiling keyed by real UTC calendar date. To make it a genuine, code-enforced
backstop for a controlled run, `LLM_BUDGET_MODE` would need to be set to `"enforce"` for the
run's duration - itself a real settings change, not proposed as done-by-default here (§M4/M5
decides whether to recommend this).

## 14. Existing per-task cost caps

**NOT FOUND** - no per-task (as opposed to daily-aggregate) cost ceiling exists anywhere in the
traced code. `BudgetGuard.check()` is consulted per-*dispatch-attempt* against the cumulative daily
ledger, not per-task.

## 15. Existing emergency-stop mechanism

**MISSING CONTROL, confirmed by absence** - no dedicated kill-switch was found beyond: (a) stopping
the container (`docker stop`), or (b) setting `*_ENABLED=false` in `.env` (requires a container
restart to take effect - config is not hot-reloaded, confirmed by every `_run_enabled_loop()`
reading `settings` once at process start). `LLM_BUDGET_MODE=enforce` (§13) is the closest thing to
an automatic stop, but it is daily-cumulative, not a per-run kill switch, and requires an explicit
opt-in.

## Summary table

| # | Question | Answer | Confidence |
|---|---|---|---|
| 1 | Queue mechanism | DB-polling on `EditorialTask`, no broker | CONFIRMED |
| 2 | Paid capabilities | RESEARCH/INTELLIGENCE/SCORING (analysis), RESEARCH/INTELLIGENCE/COPYWRITING/QUALITY (content) | CONFIRMED |
| 3 | Provider/model selection | Routing engine + real fallback chain (bounded) | CONFIRMED |
| 4 | Cost recording | Two independent writes (Redis ledger, `AIExecution` row); real drift found | CONFIRMED (mechanism), UNKNOWN (this specific drift's root cause) |
| 5 | Retry policy | max_attempts=3/step, max_iterations=3, 0% real historical retry rate | CONFIRMED |
| 6 | Old-task processing | 11,917 backlog, only 68 in the 2h freshness window; failed tasks never auto-retried; 2 tasks stuck RUNNING forever | CONFIRMED |
| 7 | Concurrency/prefetch | 1 (sequential), batch size 5 | CONFIRMED |
| 8 | Automation keeps creating tasks | Yes | CONFIRMED |
| 9 | Analysis auto-triggers content gen | No | CONFIRMED |
| 10 | Content gen can Telegram-send | Yes, via `content_cycle.py` only - not via `run_content_generation_for_event()` directly | CONFIRMED |
| 11 | One event → multiple paid calls | Yes, up to 8 across full lifecycle | CONFIRMED |
| 12 | Idempotency | Real, layered (atomic claim + duplicate-task rejection) | CONFIRMED |
| 13 | Daily budget guard | Exists, real, currently `shadow` mode, $1.00 default | CONFIRMED |
| 14 | Per-task cost cap | None exists | CONFIRMED (absence) |
| 15 | Emergency stop | None dedicated; container stop / `.env` flag + restart only | MISSING CONTROL |
