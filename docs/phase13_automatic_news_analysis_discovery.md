# Phase 13 — Automatic News Analysis Discovery

Discovery only. No production code, test, migration, or Contract was modified. No live AI/OpenAI
call was made. No existing `NEWS_ANALYSIS`/`CONTENT_GENERATION` task was executed. No Telegram
message was sent. No database row was modified — every DB query below is read-only. Every claim was
independently verified against current source (`HEAD = e6cf337`), not trusted from prior-phase
documentation.

## 1. Executive Summary

Phase 12 automates ingestion up to `EditorialTask(NEWS_ANALYSIS, CREATED)`. **Nothing in production
code consumes that task today** — confirmed by an exhaustive grep: `WorkflowRunner`/
`CapabilityExecutor` are instantiated in exactly one production file
(`scripts/run_content_generation.py`), and it is scoped to `CONTENT_GENERATION` only, never
`NEWS_ANALYSIS`. Even if something *did* try to execute it, the `NEWS_ANALYSIS` workflow would fail
partway through: its third step (`engagement_analysis`, capability name `"engagement"`) has no
registered `Capability`, no prompt, and no implementation anywhere in the repository — only a single
documented, temporary *persistence-alias* line in `capabilities/capability_mapping.py` that has
nothing to do with actually running it. Concretely, `CapabilityExecutor.execute()` would call
`CapabilityRegistry.resolve("engagement")`, raise `UnknownCapabilityError`, convert it to
`PermanentStepFailureError`, and fail the whole task — **but only after the `research` and
`intelligence` steps had already run and made real, paid LLM calls**, since steps execute in
declared order before the failure is reached.

A second, independent, previously-unverified finding: **there is no atomic claim mechanism for
`CREATED` `EditorialTask` rows.** `WorkflowRunner.run()`'s own `CREATED → RUNNING` transition is a
plain read-then-write (`session.get()` then a status check then `commit()`), not a conditional
`UPDATE ... WHERE status = 'CREATED'` the way Triage's own `_claim_new_event()` is. Phase 12's own
claim-safety precedent does **not** extend to workflow execution — this must be designed fresh, not
assumed.

**Recommended Phase 13 boundary** (§18): implement `EngagementCapability` (closing the missing-step
gap) plus a new, genuinely atomic claim-and-execute mechanism, wired into a small, dedicated,
Contract-scoped automatic execution path for `NEWS_ANALYSIS` only — explicitly **not** auto-chaining
into `CONTENT_GENERATION`, which remains a distinct, later decision. This does not require a
migration (§17) if `EngagementCapability` is built as LLM-reasoning over already-available
`NewsEvent` fields, deferring real Telegram engagement-signal persistence (views/forwards/reactions)
to a later, separately-evidenced increment.

## 2. Repository Baseline

- `git rev-parse HEAD` = `e6cf33786cd36eadc438d4b55cfb6d5224ffbcd8` — the Phase 12 checkpoint commit,
  confirmed via `git log`.
- `git status --short`: only the same 24 pre-existing, unrelated, uncommitted Phase 9/9.5/10/
  Phase-11-diagnostic/OpenAI-remediation documentation files already identified and deliberately
  excluded from the Phase 12 checkpoint — no new drift, no Phase 13 work exists yet.

## 3. Current End-to-End Pipeline

```
Configured Sources
  → scheduled Worker (worker/main.py, AUTOMATIC — Phase 12)
  → Collector (services/collector.py, AUTOMATIC)
  → NewsEvent persistence (AUTOMATIC)
  → exact-hash dedup (AUTOMATIC)
  → Triage (services/triage_orchestrator.py, AUTOMATIC)
  → EditorialTask(NEWS_ANALYSIS, CREATED)   <-- Phase 12 stops here, confirmed
  → ??? (nothing consumes this — see §4)
```

## 4. NEWS_ANALYSIS Creation and Execution Trace

- **Defined**: `WorkflowType.NEWS_ANALYSIS` (`schemas/workflow.py:26`).
- **Registered**: `workflows/registry.py:81` — `registry.register(news_analysis.DEFINITION)`,
  called at import time via the module-level `registry = build_registry()` singleton
  (`workflows/registry.py:87`). `WorkflowRegistry.resolve(WorkflowType.NEWS_ANALYSIS)` **succeeds**
  — this workflow type is not unknown/unregistered.
- **Created**: `services/triage_orchestrator.py:191-197`, inside `_run_phase_b()` — calls
  `services.workflow_service.create_task(session, EditorialTaskCreate(event_id=event_id,
  workflow_type=WorkflowType.NEWS_ANALYSIS, priority=triage_result.priority))`. This is the **only**
  production call site that creates a `NEWS_ANALYSIS` task anywhere in the repository (confirmed via
  grep — every other `NEWS_ANALYSIS` reference outside `services/triage_orchestrator.py`,
  `workflows/definitions/news_analysis.py`, and `schemas/workflow.py` is in a test file).
- **Execution consumer — searched exhaustively, found none**: grepped every file for
  `WorkflowRunner(` and `CapabilityExecutor(` construction — the only production match is
  `scripts/run_content_generation.py:104-105`, which constructs both, but exclusively for
  `WorkflowType.CONTENT_GENERATION` (line 102). Grepped `worker/*.py` for `NEWS_ANALYSIS` — **zero
  matches**: Phase 12's worker never references it, confirming the frozen Contract boundary held.
  No scheduler, cron, or CLI script anywhere picks up `CREATED` `NEWS_ANALYSIS` tasks.

**Proven answer**: after Phase 12 creates `EditorialTask(NEWS_ANALYSIS, CREATED)`, **nothing consumes
it automatically or manually via any existing entry point**. It sits in `CREATED` status
indefinitely, exactly as Phase 12's own governance chain already disclosed and accepted as temporary
operational debt.

## 5. NEWS_ANALYSIS Workflow Audit

`workflows/definitions/news_analysis.py`, `DEFINITION` (version 1):

| Step | Capability name | Timeout | Registered? | Prompt exists? | Tested (real wiring)? |
|---|---|---|---|---|---|
| `research` | `research` | 30s | **Yes** (`capabilities/research_capability.py`, `RESEARCH_CAPABILITY_DEFINITION`) | Yes (`prompts/research/`) | Yes — `tests/test_phase9_research_intelligence_integration.py` exercises it via `assemble_ai_integration_layer()` with a real (test-config) gateway |
| `intelligence` | `intelligence` | 30s | **Yes** (`capabilities/intelligence_capability.py`) | Yes (`prompts/intelligence/`) | Yes, same integration test |
| `engagement_analysis` | `engagement` | 30s | **No** — `CapabilityRegistry.resolve("engagement")` raises `UnknownCapabilityError` (confirmed: `capabilities/registry.py`'s `build_registry()` registers exactly 5 capabilities — Scoring, Quality, Research, Intelligence, Copywriting — no Engagement) | **No** — no `prompts/engagement/` directory exists (confirmed via directory listing) | No — cannot be, since no implementation exists |
| `scoring` | `scoring` | 30s | **Yes** (`capabilities/scoring_capability.py`) | Yes (`prompts/scoring/`) | Yes |

`max_iterations=3`, `timeout_seconds=120` (whole-workflow budget), `retry_policy` allows 3 attempts
per step on `StepExecutionError`. `required_input=["event_id"]`,
`expected_output=["research_summary", "intelligence_report", "engagement_analysis", "score"]`. Every
step defaults `required=True` (`WorkflowStepDefinition.required: bool = True`, no override in this
definition) — **`engagement_analysis` is a required step**; its failure fails the whole workflow, it
is not silently skipped.

**Output contract**: none of the four steps has a dedicated Pydantic output schema referenced by the
`WorkflowDefinition` itself — `expected_output` is just a list of string labels, not enforced
structurally at the workflow level (each `Capability`'s own `structured_output` is whatever that
Capability's own output schema defines — Research/Intelligence/Scoring each have their own, already
in production use for other workflows).

## 6. EngagementCapability Gap

Directly re-verified at current `HEAD`, not trusted from the post-Phase-11 discovery document:

1. **Does `EngagementCapability` exist?** No. `ls capabilities/*.py` lists exactly: `errors.py`,
   `executor.py`, `gateway_call.py`, `registry.py`, plus the five real capability implementations
   (research/intelligence/quality/scoring/copywriting) and `capability_mapping.py`. No
   `engagement_capability.py`.
2. **Is `engagement_analysis` registered?** No — `capabilities/registry.py::build_registry()`
   registers exactly 5 capabilities; `"engagement"` is not among them.
3. **Does a prompt exist?** No — `prompts/` contains exactly: `copywriting/`, `demo_summary/`,
   `intelligence/`, `quality/`, `research/`, `scoring/`. No `engagement/`.
4. **Output schema/contract?** None exists — there is nothing to have one.
5. **Would real `WorkflowRunner` execution currently fail?** Yes.
6. **At what exact step/error?** The `engagement_analysis` step (3rd of 4), via
   `CapabilityExecutor.execute()` → `self._registry.resolve("engagement")` →
   `UnknownCapabilityError` → caught and re-raised as `PermanentStepFailureError` (`capabilities/
   executor.py:87-91`) → `WorkflowRunner._run_step()`'s `except PermanentStepFailureError` branch
   returns `"FAILED"` immediately, no retry (`workflows/runner.py:245-252`) → since the step is
   `required`, `_execute_steps()` calls `_fail()`, transitioning the task to `FAILED` with
   `state.failure = {"step": "engagement_analysis", "error_type": "StepFailed", ...}`.
7. **Missing implementation, or stale workflow-definition reference?** **Missing implementation.**
   The workflow definition's own module docstring (`workflows/definitions/news_analysis.py:1-7`)
   and `capability_mapping.py`'s own docstring both explicitly, currently describe this as
   deliberate, disclosed, temporary technical debt (`"Amendment A... a temporary persistence
   stopgap... MUST be reconsidered before any real Engagement Capability is implemented"`) — not a
   stale reference nobody noticed. The workflow definition is correct and current; the capability
   simply was never built.

**Consequence not previously quantified**: because `research` and `intelligence` run *before*
`engagement_analysis` in step order, any attempt to execute `NEWS_ANALYSIS` today — accidental or
deliberate — would make two real, paid LLM calls (whatever `assemble_ai_integration_layer()`'s
configured provider/model is) before failing. This is a concrete cost-risk finding for §14/§18, not
merely a correctness gap.

## 7. Available Engagement / Reach Data

Verified directly against the installed `telethon==1.44.0` package (not assumed from memory): the
raw `telethon.tl.types.Message` constructor (which Telethon's own `custom.message.Message` wrapper
class copies attributes from at construction — confirmed via `inspect.getsource`) includes `views:
Optional[int]`, `forwards: Optional[int]`, `replies: Optional[types.TypeMessageReplies]`,
`reactions: Optional[types.TypeMessageReactions]` as real, populated fields for channel posts.

| Signal | Available from source? | Currently collected? | Persisted? | Model field? | Usable by NEWS_ANALYSIS today? |
|---|---|---|---|---|---|
| Telegram views | **Yes** (`message.views`) | No | No | No | No |
| Telegram forwards | **Yes** (`message.forwards`) | No | No | No | No |
| Telegram replies (comment count) | **Yes** (`message.replies.replies`) | No | No | No | No |
| Telegram reactions | **Yes** (`message.reactions.results[].count`) | No | No | No | No |
| Hacker News score (points) | **Yes** (HN Firebase API's `item.score` field) | No | No | No | No |
| Hacker News comment count | **Yes** (`item.descendants`) | No | No | No | No |
| RSS/Atom engagement of any kind | No — the format has no such field | — | — | — | — |
| arXiv citation/engagement | No — the arXiv Atom API exposes no such field | — | — | — | — |
| GitHub release reactions | Partially (GitHub REST can return reaction counts on some endpoints, not fetched here) | No | No | No | No |
| Source/channel size (subscriber count) | Not fetched by any current adapter (Telethon can retrieve channel participant counts via a separate API call, not made here) | No | No | No | No |

**Confirmed root cause for Telegram specifically**: `integrations/sources/telegram_source.py::
_to_raw_item()` (lines 62-67) constructs `RawNewsItem` from only `message.id`, `message.text`,
a derived URL, and `message.date` — `message.views`/`.forwards`/`.replies`/`.reactions` are read
from the Telethon object in memory but never referenced, so they are discarded when the function
returns. `RawNewsItem` itself (`schemas/raw_news_item.py`) has no fields for any of this — even if
the adapter extracted them, there is nowhere to put them without a schema change. `NewsEvent`
(`database/models/news_event.py`) likewise has no engagement-related column.

**This confirms the product requirement's premise is technically sound**: real, per-message
Telegram engagement data genuinely exists and is genuinely discarded today — this is not a dead end,
but it is presently unused by anything, including Triage (§8) and the not-yet-built
`EngagementCapability`.

## 8. Current Triage Scoring Reality

Re-read `services/triage.py` directly (unchanged since Phase 9, re-confirmed byte-for-byte): the
`decide_triage()` function's own docstring states, as a binding contract: *"Freshness (§2.1) and
NewsSource.reliability_score (§6) are the complete, closed signal set... no other NewsEvent/
NewsSource field may be added to this formula without a Contract amendment."*

`combined_score = 0.6 * freshness_weight + 0.4 * reliability_score` (`reliability_score` a static,
per-source value, defaulting to `0.5` if unset) — **no engagement, reach, channel size, reactions,
comments, or reposts signal of any kind is used by Triage.** This matches product documentation's
own framing exactly (Triage is deliberately a cheap, deterministic, zero-AI, zero-network pre-filter
— Phase 9's own explicit design goal), not a discrepancy between docs and code.

**Complementary, not duplicative**: `NEWS_ANALYSIS`'s own `expected_output` includes a `score`
distinct from Triage's `priority`, plus `engagement_analysis` and richer `research_summary`/
`intelligence_report` fields Triage never computes. The evident intent (from the workflow's own
structure, not merely inferred) is that `NEWS_ANALYSIS` is a deeper, AI-assisted, per-event
enrichment pass that could inform a *later* decision (e.g., whether to greenlight
`CONTENT_GENERATION`) — Triage's cheap score decides *urgency/ordering* for review, `NEWS_ANALYSIS`
would decide *substantive newsworthiness/angle*. Nothing in current code implements this handoff
(§9/§10).

## 9. Workflow Execution Infrastructure

- **`WorkflowRunner`** (`workflows/runner.py`): generic, has zero knowledge of any concrete
  Capability — dispatches through the `StepExecutor` Protocol only. `CapabilityExecutor`
  (`capabilities/executor.py`) is the one real bridge, used today only by
  `scripts/run_content_generation.py`.
- **Session ownership**: caller-provided — `WorkflowRunner.run(session, task_id)` takes an
  already-open `AsyncSession`; it does not open its own. `CapabilityExecutor` is constructed with
  the *same* session (`scripts/run_content_generation.py:104`), so the whole run happens inside one
  session/transaction scope, matching Triage's own single-session-per-batch discipline.
- **`CREATED → RUNNING → COMPLETED/FAILED` transitions — the critical finding**: `WorkflowRunner.
  run()` itself is the *only* place that ever changes `EditorialTask.status` (its own docstring
  states this explicitly: *"Only WorkflowRunner ever changes an EditorialTask's status -
  services.workflow_service never does"*). The `CREATED → RUNNING` transition
  (`workflows/runner.py:111-123`) is: `task = await session.get(EditorialTask, task_id)` → check
  `task.status` → if not already `RUNNING`/terminal, set `task.status = TaskStatus.RUNNING` →
  `await session.commit()`. **This is a plain read-then-write, not an atomic conditional `UPDATE`**
  — structurally different from Triage's own `_claim_new_event()`
  (`services/triage_orchestrator.py:45-67`), which is a single `UPDATE ... WHERE status = 'NEW'`
  statement whose `rowcount` is the atomic race-outcome signal.
- **Is execution idempotent / duplicate-safe?** `TaskAlreadyRunningError`/`TaskAlreadyCompletedError`
  (`workflows/errors.py:51-56`) exist, but re-reading their exact guard placement
  (`workflows/runner.py:114-117`) proves they only protect against *sequential* misuse (calling
  `run()` again on a task whose status-change from a *previous* call is already visible to this
  read) — they do **not** prevent two concurrent callers from both reading `CREATED` before either
  commits `RUNNING`, both passing the check, and both proceeding to execute the same task
  concurrently. **No atomic claim mechanism exists for this today.** This must be designed fresh for
  Phase 13, not assumed from Phase 12's Triage precedent (per this task's own explicit instruction
  to verify independently — confirmed, they are architecturally different problems with different
  existing solutions).
- **Crash/restart recovery**: if a process crashes mid-`RUNNING`, the task is left permanently
  `RUNNING` — `WorkflowRunner.run()` itself would then raise `TaskAlreadyRunningError` on any future
  attempt, with no built-in recovery path (unlike Triage's own stale-`PROCESSING` recovery via
  `_select_recovery_candidates()`/`_acquire_recovery_ownership()`, which has no `EditorialTask`
  equivalent anywhere in `workflow_service.py`).
- **`scripts/run_content_generation.py`** is the only real, currently-exercised precedent for wiring
  `WorkflowRunner` + `CapabilityExecutor` + a real `CapabilityRegistry` together in production —
  useful as a template, but it is manually, individually invoked per `event_id` by a human; it has
  no batch/claim logic of its own to reuse for "find all `CREATED` tasks and run them."

## 10. Automation Architecture Options

| Option | Description | Coupling | Failure isolation | Duplicate-execution risk | CONTENT_GENERATION reuse | Crash recovery |
|---|---|---|---|---|---|---|
| **A** — extend Phase 12 worker | Add a third phase after collection+triage in `worker/cycle.py` that also drains `CREATED` `NEWS_ANALYSIS` tasks | High — couples ingestion cadence to AI-execution cadence; a slow/expensive analysis batch would delay the next collection cycle | Partial — one cycle's failure already isolated per-task if designed carefully, but shares the same process/loop as collection | Same risk as any option — still needs a new atomic claim (§9); not solved by placement | Same-process reuse is easy but blurs Phase 12's own frozen "collection+triage only" boundary — reopens an already-approved Contract | Same as Phase 12: process restart re-runs from wherever the last commit left off |
| **B** — dedicated analysis worker/process | New, separate worker (own loop, own interval/backlog-drain policy), analogous to `worker/main.py` but for task execution | Low — cleanly separated from ingestion; can be scaled/rate-limited independently | High — a crash or slow AI provider never blocks collection | Needs a new atomic claim mechanism (unavoidable in any option) but isolated blast radius | Clean template for a *future*, similarly-scoped `CONTENT_GENERATION` worker, without forcing that decision now | Own restart semantics, independent of collection/triage |
| **C** — generic workflow-task worker (consumes any `CREATED` `EditorialTask` regardless of `workflow_type`) | One generic executor loop for both `NEWS_ANALYSIS` and (later) `CONTENT_GENERATION` | Medium — one piece of infrastructure, but conflates two workflows with very different cost/risk profiles (analysis vs. draft generation, which the product explicitly wants human-gated) | Depends on implementation; a bug affecting one workflow type risks affecting both | Same claim-mechanism need | Maximizes reuse, but risks silently making `CONTENT_GENERATION` automatic before that is an authorized decision — a real product/scope risk given the explicit "no auto-publish, no unreviewed content" constraints | Same |
| **D** — no new worker; extend `scripts/run_content_generation.py`'s own pattern into a new `scripts/run_news_analysis.py`, invoked manually only | Reuses the exact, proven, already-tested production wiring pattern; adds zero automation | None — fully manual | N/A (one task at a time, human-triggered) | Low — human paces invocation | Directly reusable, unmodified | N/A |

**Evaluation, not chosen on code volume alone**: Option **B** (dedicated worker) is the smallest
design that does not create Phase 14 debt: it does not reopen Phase 12's own frozen worker Contract
(Option A would), it does not prematurely conflate `NEWS_ANALYSIS` with `CONTENT_GENERATION`
(Option C would, and the product's own explicit "no auto-publish, human review required" constraint
makes that conflation a real risk, not just a style preference), and unlike Option D it actually
solves the stated product problem (fresh news currently *not* automatically analyzed). The genuinely
new piece of infrastructure every option except D requires — an atomic `CREATED`-task claim
mechanism — is a one-time cost regardless of which option is chosen, so it should not be weighed
against B specifically.

## 11. NEWS_ANALYSIS Output / Persistence

- **Where is the result stored?** `EditorialTask.workflow` (JSON column) — `WorkflowRunner.
  _execute_steps()` writes `state.step_results` (each step's `structured_output`) into
  `task.workflow` after every step and at completion (`workflows/runner.py:196-199, 205-207`). No
  dedicated table/column exists for analysis results specifically.
- **`AIExecution` records**: confirmed **zero** rows exist in this database currently
  (`AIExecution count: 0`, read-only query this session). This is consistent with, not contradicted
  by, `CapabilityExecutor`'s own documented constraint (Amendment B, §16: *"CapabilityExecutor MUST
  NOT persist any AIExecution row"*) — this is a **pre-existing, orthogonal gap**: even
  `CONTENT_GENERATION`'s own already-working, human-invoked path does not currently write
  `AIExecution` audit rows either. Not a Phase 13 blocker, but worth naming precisely: "zero
  `AIExecution` rows" is not by itself proof that no AI call occurred — Phase 12's own M4/M5/M6
  evidence remained valid because it *also* independently confirmed via import-boundary checks and
  direct behavioral tracing that `WorkflowRunner` was never invoked at all, not merely via this one
  proxy signal.
- **Queryable later?** Yes, via `EditorialTask.workflow` JSON, but only by ad hoc JSON inspection —
  no read service exists for it (unlike `EditorialInboxService` for `ContentDraft`).
- **Decision threshold?** None exists anywhere in code — no logic reads a completed `NEWS_ANALYSIS`
  task's `score`/`engagement_analysis` output and decides anything.
- **Does completion automatically create `CONTENT_GENERATION`?** No — confirmed by direct grep: the
  only production call sites creating `WorkflowType.CONTENT_GENERATION` tasks are
  `scripts/run_content_generation.py` and test files. `services/triage_orchestrator.py` never
  references `CONTENT_GENERATION`, and no code anywhere reads `NEWS_ANALYSIS` completion state to
  trigger anything.

**Proven answer**: if `NEWS_ANALYSIS` successfully completed today (hypothetically, with
`EngagementCapability` fixed), **nothing happens next** — its output sits in that one task's
`workflow` JSON column, unread by any other code path.

## 12. CONTENT_GENERATION Integration

`run_content_generation_for_event(event_id, ...)` (`scripts/run_content_generation.py:65-124`):

- **Required `NewsEvent` state**: none beyond existing — it does not check `NewsEvent.status`, does
  not require a prior `NEWS_ANALYSIS` task, does not require Triage to have run. It is fully
  independent, driven only by `event_id`.
- **New `EditorialTask` created?** Yes, always — a fresh `WorkflowType.CONTENT_GENERATION` task per
  call (`workflow_service.create_task(...)`), reusing the same `_find_active_task()` duplicate-guard
  Triage's own task creation already relies on.
- **Duplicate-generation risk**: already mitigated by `DuplicateActiveTaskError` — calling this
  function twice for the same `event_id` while a `CONTENT_GENERATION` task is still
  `CREATED`/`RUNNING` raises, not silently double-generates.
- **Is `NEWS_ANALYSIS` output consumed?** No — `CapabilityExecutor._build_context()`
  (`capabilities/executor.py:112-154`) builds context only from the *current* task's own
  `NewsEvent` and its own prior completed steps (`WorkflowExecutionStateSnapshot`) — it has no
  mechanism to read a *different* `EditorialTask`'s results. Even once `NEWS_ANALYSIS` is
  executable, its `research_summary`/`intelligence_report`/`score` would not automatically flow into
  a later `CONTENT_GENERATION` run without new, deliberate plumbing.
- **Automatic triggering — Phase 13 or later?** Evidence supports **deferring this specifically to a
  separate, later decision**, not folding it into Phase 13: the product's own explicit constraints
  (no auto-publish, `/news` remains editorial-only, Approve/Reject/Rework not yet architected) mean
  automatically generating a full `ContentDraft` for every analyzed event has real downstream
  product-policy implications (editorial review load, cost) that the discovery evidence alone cannot
  resolve — this is a human decision, not a technical one, and belongs in Decision Resolution, not
  assumed here.

## 13. /news Freshness Gap Map

```
new Telegram/RSS/arXiv/etc. item
  → NewsEvent                                              AUTOMATIC (Phase 12)
  → dedup                                                  AUTOMATIC (Phase 12)
  → Triage → EditorialTask(NEWS_ANALYSIS, CREATED)          AUTOMATIC (Phase 12)
  → EditorialTask(NEWS_ANALYSIS) execution                  MISSING   (§4 — nothing consumes it)
  → NEWS_ANALYSIS completion (score, engagement_analysis)   NOT IMPLEMENTED (blocked by §4, and
                                                              would additionally fail on the
                                                              missing EngagementCapability, §6)
  → EditorialTask(CONTENT_GENERATION, CREATED)               MISSING   (§11 — no automatic trigger
                                                              exists at all, regardless of §4/§6)
  → CONTENT_GENERATION execution                             MANUAL ONLY (scripts/
                                                              run_content_generation.py, human-run)
  → ContentDraft persistence                                 AUTOMATIC (once CONTENT_GENERATION is
                                                              manually triggered and completes)
  → /news editorial inbox card                               AUTOMATIC (EditorialInboxService,
                                                              real-time query — Phase 11, unchanged)
```

**The first broken/missing edge after Phase 12 is unambiguous**: `EditorialTask(NEWS_ANALYSIS,
CREATED) → execution`. Everything downstream of it is *also* missing or manual, but this is the
first gap encountered, and closing it alone does not close the others (§11/§12 already prove no
automatic chaining exists past it).

## 14. Image Requirement — Future Integration Point

Per the product's own explicit instruction, investigated only enough to determine the future
attachment point — no design performed.

- **Source media currently collected?** No — `integrations/sources/telegram_source.py::
  _to_raw_item()` actively discards Telethon's `.photo`/`.media` (unchanged since Phase 4, confirmed
  Contract §20's own prior finding still holds at current `HEAD`).
- **`NewsEvent` stores media?** No column exists.
- **`ContentDraft` stores media?** No column exists (`hashtags` is the only structured/JSON field
  beyond text).
- **LLM Gateway image support?** Vision **input** only (accepting an image as part of a prompt) —
  confirmed no `generate_image()`/image-search method exists anywhere in
  `integrations/llm_gateway/`.
- **Image generation exists?** No.
- **New persistence required?** Yes, eventually — at minimum a way to associate N candidate image
  references with a `ContentDraft` (or an intermediate stage), which does not exist today in any
  form.

**Answer to "where should this logically attach"**: after `CONTENT_GENERATION` (or as a parallel
step alongside it), not as part of `NEWS_ANALYSIS`, since `NEWS_ANALYSIS`'s own purpose (per its
`expected_output`) is textual analysis/scoring, not asset assembly — image candidates are naturally
a *content-production* concern, arriving once a draft's angle/copy exists to select relevant images
for, not before. **Missing prerequisites**: source-level media capture (would require touching the
currently-frozen `telegram_source.py`, a real architecture change, not a Phase 13 concern), an image
discovery/generation integration, and new persistence for candidates — none of which is evidence-
justified as part of Phase 13's own scope (making `NEWS_ANALYSIS` executable does not require any of
this).

## 15. Current Task Backlog

Read-only query, `2026-07-23` (this session):

| Status | Count |
|---|---|
| `CREATED` | 4723 |
| `RUNNING` | 0 |
| `COMPLETED` | 3 |
| `FAILED` | 1 |

**4723 `CREATED` tasks already exist**, entirely from Phase 12's own now-live automatic ingestion
(3130 pre-existing before Phase 12's M6 live run, +1593 from the two real M6 cycles) — this backlog
is real, growing, and entirely `NEWS_ANALYSIS` (the only workflow type Triage ever creates). The 3
`COMPLETED`/1 `FAILED` predate Phase 12 entirely (from earlier `CONTENT_GENERATION` manual
validation runs, per their low count and the git history's own Phase 10 checkpoint record) — not
`NEWS_ANALYSIS` tasks, since nothing has ever executed one. **Not executed, not deleted, not
modified** during this discovery.

## 16. Cost / Retry / Concurrency Risks

- **`BudgetGuard`**: a real, working `RedisBudgetGuard` implementation exists (`services/
  budget_guard.py`), consulted by the Routing Gateway (`FallbackPolicy`, per Amendment C) **before
  every dispatch attempt**, not per-Capability — meaning it is structurally already wired into
  whatever `assemble_ai_integration_layer()` produces, and would automatically apply to
  `NEWS_ANALYSIS`'s calls too, with zero new code, *provided* `settings.max_daily_ai_cost` is
  actually configured. **It is optional and unset by default** — "no ceiling is enforced if left
  unset." This is an operational precondition Phase 13 must call out explicitly, not a missing
  mechanism.
- **Rate limiting / provider routing / fallback**: `RateLimiter`, `FallbackPolicy`, `ProviderHealth
  Store` already exist and are already exercised by the real `assemble_ai_integration_layer()` path
  `CONTENT_GENERATION` already uses — directly reusable, no new implementation needed for the
  routing layer itself.
- **Retry**: `WorkflowStepDefinition.max_attempts` (default 3) + `WorkflowRetryPolicy` already bound
  per-step retries; `NEWS_ANALYSIS`'s own definition sets `max_attempts=3` (workflow-level) —
  existing, adequate, unmodified infrastructure.
- **Backlog burst risk — real and currently unmitigated**: 4723 already-`CREATED` tasks (§15) mean
  that a naive "drain all `CREATED` tasks every cycle" implementation would attempt to run **4723
  real, paid AI workflows** (each making at least 2, and once `EngagementCapability` exists,
  potentially 4, real LLM calls) on its very first execution — a genuine, quantified uncontrolled-
  spend risk this discovery surfaces concretely, not hypothetically. Any Phase 13 automatic-execution
  design **must** bound per-cycle throughput (a batch-size cap), not process the whole backlog at
  once.
- **Duplicate execution**: no protection exists today (§9) — a required new primitive regardless of
  which automation option (§10) is chosen.
- **Provider overload**: existing `RateLimiter`/`ProviderHealthStore` infrastructure already
  addresses this at the routing layer, reusable unmodified.

**This backlog-burst finding must directly influence Phase 13's boundary**: whatever automatic
execution mechanism is built must launch with a conservative, explicit per-cycle batch cap and
`max_daily_ai_cost` genuinely configured before enabling automatic execution against the real
backlog — this is an operational rollout concern for Decision Resolution / Manual Live Acceptance,
not something Discovery resolves itself.

## 17. Migration Analysis

**The recommended Phase 13 boundary (§18) does not require a migration.** `EngagementCapability`,
built as an LLM-reasoning capability over already-available `NewsEvent` fields (title, content,
category — the same inputs Research/Intelligence already consume), needs no new column. The new
atomic-claim mechanism needs no schema change either — it can use the same "conditional `UPDATE ...
WHERE status = 'CREATED'`" pattern Triage's own `_claim_new_event()` already demonstrates, against
the existing `EditorialTask.status` column.

**Explicit comparison, since real engagement data (§7) is genuinely available and genuinely valuable**:

| | Without migration (recommended for Phase 13) | With migration (future increment) |
|---|---|---|
| Scope | `EngagementCapability` reasons over existing `NewsEvent` text/metadata only | Adds `NewsEvent` columns (or a related table) for `views`/`forwards`/`replies`/`reactions` counts, populated by extending `telegram_source.py::_to_raw_item()` |
| Risk | Lower — no schema change, no backfill question, no new adapter behavior | Higher — touches a currently-frozen file (`telegram_source.py`), raises questions about historical backfill (none possible — data wasn't captured), and RSS/arXiv/GitHub sources still have no equivalent signal, so the new column(s) would be `NULL` for most events |
| Value | Directionally useful (LLM can reason about *stated* newsworthiness/virality potential from content alone) | More precise/grounded (real numbers), but only for the ~4/82 currently-configured Telegram sources — a partial win, not a general one |
| Fit for "smallest architecture-preserving next phase" | Yes — closes the actual blocking gap (§4/§6) with no new persistence | No — solves a different, adjacent problem (data richness) that is valuable but not what blocks execution today |

**Recommendation**: do not migrate in Phase 13. Real engagement-signal persistence is a well-evidenced,
worthwhile, but *separate* future increment — its absence does not block making `NEWS_ANALYSIS`
executable at all.

## 18. Recommended Phase 13 Boundary

**Recommended: a variant of Option B (§10) — "Implement `EngagementCapability` + a new atomic
claim mechanism + a dedicated, conservatively-bounded automatic execution path for `NEWS_ANALYSIS`
only."** This most closely matches the user's own listed Option B, refined by this discovery's
concrete findings (§9's claim-mechanism gap, §16's backlog-burst risk).

**IN SCOPE**:
- `EngagementCapability` implementation (LLM-reasoning-based, no new persistence — §17), its prompt,
  its `CapabilityDefinition`, registration in `capabilities/registry.py::build_registry()`.
- A new, genuinely atomic claim primitive for `CREATED` `EditorialTask` rows (mirroring Triage's own
  `UPDATE ... WHERE status = 'CREATED'` pattern), closing the §9 gap.
- A new, dedicated worker/process (or a clearly-scoped extension, to be decided in Architecture
  Contract) that claims and executes `NEWS_ANALYSIS` tasks only, using the existing, unmodified
  `WorkflowRunner`/`CapabilityExecutor`/`assemble_ai_integration_layer()` machinery
  (`scripts/run_content_generation.py`'s own proven wiring pattern).
- An explicit, conservative per-cycle batch cap (addressing §16's quantified backlog-burst risk).
- Operational precondition: `settings.max_daily_ai_cost` must be genuinely configured before any
  live enablement (documented, not silently assumed).

**OUT OF SCOPE**:
- Automatic `CONTENT_GENERATION` triggering (§12) — deferred to a later, explicitly product-decided
  phase.
- Real Telegram/HN engagement-signal persistence (§7/§17) — deferred, no migration in this phase.
- Any image-candidate work (§14).
- Any editorial action (Approve/Reject/Rework), any public/channel publishing.
- Changing Triage's own scoring formula (§8) — remains frozen, closed input set.
- Backfilling the existing 4723-task backlog in one pass — must be throttled, not dumped.

**WHY**: this is the smallest change that actually solves the concrete, evidenced blocker (§4/§6)
without inventing new product-policy decisions (auto-content-generation, auto-publishing) the
discovery evidence cannot resolve, and without introducing a migration the evidence doesn't require
yet (§17).

**DEPENDENCIES**: `assemble_ai_integration_layer()` and its already-proven wiring
(`scripts/run_content_generation.py`); Phase 9's atomic-claim pattern as a design template (not
reusable code, per §9's own finding); `BudgetGuard`'s existing `max_daily_ai_cost` configuration
point.

**RISKS**: the 4723-task backlog (§15/§16) if not throttled; `EngagementCapability`'s own prompt
quality (untested, new); the new claim mechanism must be got right the first time (concurrency bugs
here are exactly the class of defect Triage's own Phase 9 Contract invested heavily in preventing).

**WHAT USER-VISIBLE PROBLEM IT SOLVES**: fresh news will be automatically, substantively analyzed
(research, intelligence, engagement estimate, score) without manual intervention — closing the gap
this discovery's own primary objective named.

**WHAT STILL WILL NOT WORK AFTER PHASE 13**: `/news` will still not automatically receive new
`ContentDraft`s — `CONTENT_GENERATION` remains manual (§12), so a human must still explicitly invoke
`scripts/run_content_generation.py` (or its future equivalent) per event, even for a fully-analyzed,
high-scoring `NEWS_ANALYSIS` result. No images. No editorial actions. No public publishing.

## 19. Explicitly Deferred

Automatic `CONTENT_GENERATION` triggering; real engagement-data persistence/migration; image
candidate discovery/generation; editorial Approve/Reject/Rework actions; public/channel publishing;
per-source cadence; any Digest Engine (`DAILY_DIGEST`) work; `AIExecution` audit-row persistence gap
(§11, pre-existing, orthogonal).

## 20. Open Human Decisions

1. **Automation placement** (§10): dedicated worker (recommended) vs. extending Phase 12's own
   worker vs. a generic task-executor — Decision Resolution must pick one explicitly.
2. **Batch-size cap and rollout throttling** for the existing 4723-task backlog (§16) — a specific
   number/strategy must be chosen, not left implicit.
3. **`max_daily_ai_cost` value** — must be set to something before live enablement; no default
   recommendation is made here (product/finance decision, not technical).
4. **`EngagementCapability`'s exact prompt/output contract** — Architecture Contract-level detail,
   not resolved here.
5. Whether `AIExecution` audit-row persistence (§11's orthogonal gap) should be addressed
   opportunistically in Phase 13 or deferred further — evidence-neutral, a scope-preference
   decision.

## 21. Risks

Backlog burst / uncontrolled spend if the batch cap is skipped or `max_daily_ai_cost` is left unset
(§16); new atomic-claim mechanism introducing a concurrency bug (§9); `EngagementCapability`'s
untested prompt producing low-quality output that undermines trust in `NEWS_ANALYSIS`'s own score;
scope creep into `CONTENT_GENERATION` automation before the product has decided the editorial-review
policy that gates it (§12/§18's explicit exclusion exists precisely to prevent this).

## 22. Next Step

Proceed to **Phase 13 Decision Resolution**, addressing the five open human decisions in §20 —
starting with automation placement (§10) and the batch-cap/cost-ceiling rollout strategy (§16),
since those two most directly determine Architecture Contract shape.

---

PHASE 13 DISCOVERY COMPLETE — READY FOR DECISION RESOLUTION
