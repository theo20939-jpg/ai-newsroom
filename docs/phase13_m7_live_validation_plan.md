# Phase 13 — M7 Live Validation Safety Review & Execution Plan

Planning only. This document defines the exact procedure for the one human-authorized live
`NEWS_ANALYSIS` execution. **No code in this document has been executed. No worker was started.
No OpenAI/live provider call was made. No real task was processed.** M7 itself remains
unauthorized until a human explicitly approves proceeding past §7 of this document.

## 1. Authority

Frozen by, and must not deviate from: `docs/phase13_automatic_news_analysis_architecture_
contract.md` §26 (file scope) / §30 (manual live validation), `docs/phase13_automatic_news_
analysis_implementation_plan.md` §14 (M7 procedure, as corrected across three revision passes),
`docs/phase13_automatic_news_analysis_implementation_plan_final_gate_audit.md` Gate 16/17
(M7 hard-stop and exact-task-strategy non-regression, both re-confirmed APPROVED),
`docs/phase13_m6_readiness_report.md` (M0-M6 GREEN, the precondition for M7 to even be
considered).

## 2. Why this is not "start the worker and see what happens"

Three prior audit passes on the Implementation Plan (`..._implementation_plan_audit.md`,
`..._implementation_plan_final_reaudit.md`) independently found and corrected the same class of
danger: the normal eligibility query (`worker/analysis_cycle.py::_select_eligible_task_ids()`)
is deliberately unscoped — by design, it is the same query production uses, and it has no
test/validation-scoping hook. Starting the real batch worker (`worker/analysis_main.py`,
`news_analysis_enabled=true`) for "one quick live test" would let it select and process **any**
of the currently fresh-eligible backlog tasks, not a chosen, verified one. This is exactly what
went wrong during M3 implementation (§3 below) — and the M7 procedure below is designed
specifically so that failure mode is structurally impossible, not merely avoided by care.

## 3. The M3 incident, and how this plan is designed around it

**What happened** (full account in `docs/phase13_m3_analysis_cycle_report.md`): while writing
`tests/test_analysis_worker_cycle.py`, early test runs called `run_analysis_cycle()` — which
internally invokes the real, unscoped eligibility query — against the shared development
database. Because that query orders by `created_at ASC` (oldest first) and the real backlog
(thousands of hours-old `NEWS_ANALYSIS`/`CREATED` tasks) is always older than a row a test just
created, the real backlog rows won every time, not the test's own rows. Three early runs each
claimed and "completed" up to 5 real production `EditorialTask` rows using test-fabricated
capability output. This was caught immediately from anomalous assertion output, root-caused,
fixed (a temporary, test-only narrowing of `settings.news_analysis_freshness_cutoff_hours`), and
all 15 affected rows were identified precisely and reverted to their exact pristine pre-mutation
`CREATED` state — independently re-verified clean at the M6 gate and remaining clean through the
present.

**The structural lesson, applied to this plan**: the danger was never "the atomic claim is
unsafe" (M2's own concurrency tests prove the opposite, repeatedly) — it was **calling the
eligibility-query-based selection mechanism at all** against a database with real backlog present
without a scoping mechanism. M7's own procedure (§6 below) therefore **never calls
`_select_eligible_task_ids()` or `run_analysis_cycle()`**. It bypasses batch selection entirely
and invokes `WorkflowRunner.run(session, task_id)` — which already accepts an exact task
identifier as its own parameter — directly, against exactly one, pre-recorded, human-verified
`task_id`. There is no selection step in this procedure for real backlog to win by being older;
the one task processed is the one task named, by UUID, in §5's own recorded evidence, full stop.

## 4. Current backlog reality (to re-verify at execution time, not trusted from this snapshot)

As of the Final Gate Audit and M3/M5 milestone work, this repository's shared development
database contained on the order of **1,100+** genuinely fresh-eligible (≤48h)
`NEWS_ANALYSIS`/`CREATED` tasks, out of ~4,723 total historical `NEWS_ANALYSIS` tasks of every
age. This number changes continuously (ages out of the 48h window over time; would grow again if
Phase 12's `automation_worker`/Triage were running). **Do not treat any previously-recorded count
as current** — §5 step 1 re-derives it live, read-only, at the start of the actual authorized
run.

## 5. Pre-flight: exact task selection (read-only, no claim, no mutation)

To be run by a human-supervised session, interactively, **before** requesting final
authorization to proceed to §6. This step makes no write to the database.

```python
# READ-ONLY. No claim. No mutation. Run this first, in isolation, to choose the sample.
import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy import func, select
from database.session import async_session_factory
from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.news_event import NewsEvent
from schemas.workflow import WorkflowType
from core.config import settings

async def preflight():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.news_analysis_freshness_cutoff_hours)
    anchor = func.coalesce(NewsEvent.published_at, NewsEvent.collected_at)

    async with async_session_factory() as session:
        # 1. Re-derive the current fresh-eligible count (do not trust §4's snapshot).
        count_stmt = (
            select(func.count(EditorialTask.id))
            .join(NewsEvent, EditorialTask.event_id == NewsEvent.id)
            .where(
                EditorialTask.status == TaskStatus.CREATED,
                EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
                anchor >= cutoff,
            )
        )
        current_fresh_eligible_count = (await session.execute(count_stmt)).scalar()
        print("CURRENT fresh-eligible NEWS_ANALYSIS/CREATED count:", current_fresh_eligible_count)

        # 2. Deterministically identify ONE candidate - same ORDER BY the real query uses, but
        #    LIMIT 1 and read-only. This is a DIAGNOSTIC, not the batch worker's own selection.
        candidate_stmt = (
            select(EditorialTask.id, EditorialTask.event_id, NewsEvent.title, anchor.label("freshness_anchor"))
            .join(NewsEvent, EditorialTask.event_id == NewsEvent.id)
            .where(
                EditorialTask.status == TaskStatus.CREATED,
                EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
                anchor >= cutoff,
            )
            .order_by(EditorialTask.created_at.asc(), EditorialTask.id.asc())
            .limit(1)
        )
        row = (await session.execute(candidate_stmt)).first()
        if row is None:
            print("NO ELIGIBLE CANDIDATE EXISTS - M7 cannot proceed until one exists.")
            return
        task_id, event_id, title, freshness_anchor = row
        print("CANDIDATE task_id:      ", task_id)
        print("CANDIDATE event_id:     ", event_id)
        print("CANDIDATE event title:  ", title)
        print("CANDIDATE freshness:    ", freshness_anchor)

        # 3. Re-confirm status == CREATED at the moment of recording (belt-and-suspenders -
        #    the WHERE clause above already guarantees it, this is an explicit, separate check).
        task = await session.get(EditorialTask, task_id)
        print("CONFIRMED status ==", task.status.value)
        assert task.status == TaskStatus.CREATED

asyncio.run(preflight())
```

**Record, verbatim, before proceeding to §6** (this is the human-reviewable evidence record, not
optional):

- Exact `task_id` (UUID)
- Exact `event_id` (UUID)
- Event title (for human sanity-check — is this a real, sensible news item, not test debris?)
- Freshness anchor timestamp and its numeric age
- Confirmed `status == CREATED` at read time
- Current fresh-eligible count (context only — irrelevant to safety, since §6 never selects
  from this pool; recorded for audit completeness)
- Explicit written sentence: **"This task_id is the intended, controlled sample for this M7
  run. No other task_id will be intentionally processed."**

If the query returns no candidate (zero fresh-eligible tasks exist), M7 cannot proceed — this is
not an error to work around; wait until a real task exists, or reconsider whether a synthetic,
test-owned task inserted for this sole purpose is preferable (out of this document's own scope
to decide — a human, forward-looking decision, not a default).

## 6. Human authorization checkpoint

**STOP HERE.** Everything above this line is read-only and requires no special authorization
(it queries the database, makes no live provider call, mutates nothing). Everything below this
line performs the actual live execution — a real, committed atomic claim and, if that claim
succeeds, up to several real, billed LLM provider calls. **Do not proceed past this point without
an explicit, separate human "yes, proceed" for the exact `task_id` recorded in §5.** A different
`task_id` discovered later, or a re-run of §5 that returns a different candidate, requires a new
authorization — the authorization is for the specific, named UUID, not for "run M7 generically."

## 7. Baseline counts to record before execution

```python
# READ-ONLY. Run once, immediately before §8's live execution, in the same session.
import asyncio
from sqlalchemy import select, func
from database.session import async_session_factory
from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.content_draft import ContentDraft
from schemas.workflow import WorkflowType

async def baseline():
    async with async_session_factory() as session:
        for status in (TaskStatus.CREATED, TaskStatus.RUNNING, TaskStatus.COMPLETED, TaskStatus.FAILED):
            n = (await session.execute(
                select(func.count(EditorialTask.id)).where(EditorialTask.status == status)
            )).scalar()
            print(f"EditorialTask count [{status.value}]:", n)

        cg = (await session.execute(
            select(func.count(EditorialTask.id)).where(
                EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.CONTENT_GENERATION.value
            )
        )).scalar()
        print("CONTENT_GENERATION task count:", cg)

        drafts = (await session.execute(select(func.count(ContentDraft.id)))).scalar()
        print("ContentDraft count:", drafts)

asyncio.run(baseline())
```

Record all six numbers. §10 re-runs this exact query set after execution and diffs against these
recorded values.

## 8. The live execution itself (exactly one real atomic claim, exactly one task)

Human-supervised, interactive session. `TASK_ID` below must be the **exact, literal** UUID
recorded and authorized in §5/§6 — not re-derived, not re-queried, not "whichever task is
eligible now."

```python
# LIVE. Performs a real atomic claim and, if it wins, real provider calls. Requires §6's
# explicit authorization for this exact TASK_ID.
import asyncio
from pathlib import Path
from uuid import UUID

from capabilities.executor import CapabilityExecutor
from core.config import settings
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.prompts.file_repository import FilePromptRepository
from workflows.runner import WorkflowRunner

TASK_ID = UUID("PASTE-THE-EXACT-AUTHORIZED-UUID-HERE")  # from §5/§6 - do not substitute

async def live_run():
    prompt_repository = FilePromptRepository(Path("prompts"))
    ai_layer = assemble_ai_integration_layer(settings, prompt_repository)  # real gateway,
    # real CapabilityRegistry, real EngagementCapability - no redis_client kwarg, matching
    # scripts/run_content_generation.py's own established production pattern exactly.

    async with async_session_factory() as session:
        executor = CapabilityExecutor(session, TASK_ID, ai_layer.capability_registry)
        runner = WorkflowRunner(executor)
        result = await runner.run(session, TASK_ID)
        print("FINAL STATUS:", result.status)
        print("STEP RESULTS:", [(r.step_name, r.status) for r in result.step_results])
        return result

asyncio.run(live_run())
```

**This call, and only this call, may touch the database's task state during M7.** The normal
batch worker (`worker/analysis_main.py`) is **not started**. `worker.analysis_cycle.
run_analysis_cycle()`/`_select_eligible_task_ids()` are **never called** during M7 — this is the
structural guarantee (§3) that no historical backlog task and no unrelated fresh task can ever be
selected, because nothing in this procedure performs selection at all past §5's own read-only
diagnostic.

**If `runner.run()` raises `TaskAlreadyRunningError`/`TaskAlreadyCompletedError`**: the
pre-selected task changed state between §5 and §8 (another process touched it). This is the
atomic claim correctly protecting against exactly this — **do not select a substitute task ad
hoc**. Stop, report the exception, and return to a human for a fresh §5/§6 cycle if a retry is
wanted.

## 9. Requirement-by-requirement mapping (this section is the explicit safety proof)

| # | Requirement | How this plan satisfies it |
|---|---|---|
| 1 | Exactly one controlled task is selected | §5 deterministically identifies and records one `task_id`; §8 hardcodes that literal UUID; `WorkflowRunner.run()` operates on exactly the one ID passed to it — there is no code path in §8 that could select a second task |
| 2 | No historical CREATED backlog task can be selected | §8 never calls the eligibility query (`_select_eligible_task_ids()`) or `run_analysis_cycle()` at all — the mechanism that could sweep in old backlog (§3) is not present in the execution path, structurally, not by configuration |
| 3 | No unrelated fresh task can be selected | Same reasoning as #2 — freshness filtering is irrelevant to §8's own direct-invocation path, since no selection happens there; the only task ID that can be claimed is the one literal, human-authorized UUID |
| 4 | Maximum provider calls are bounded | Best case: 4 real calls (research, intelligence, engagement, scoring — one attempt each). Structural worst case: `workflows/definitions/news_analysis.py`'s 4 steps each default to `max_attempts=3` (no per-step override), so a genuinely pathological run (every step needing its full retry budget) is bounded at 4 × 3 = **12 calls** — disclosed honestly as the true ceiling, not the expected case. No task-level retry exists beyond this (§18 of the Plan: no automatic `FAILED` retry) |
| 5 | `WorkflowRunner` atomic claim is exercised | §8's `runner.run(session, TASK_ID)` is the real, unmodified `run()` method (Plan §8.1) — the same atomic conditional `UPDATE ... WHERE status = 'CREATED'` M2's own concurrency tests already proved race-safe is exercised for real here, against a real row |
| 6 | `EngagementCapability` executes | The real `ai_layer.capability_registry` (via `assemble_ai_integration_layer()`, not a fake) resolves `"engagement"` to the real `EngagementCapability` — the 3rd of 4 real steps in the real `NEWS_ANALYSIS` definition |
| 7 | Final state becomes `COMPLETED` | §8 prints `result.status` and per-step results directly; §10 re-verifies via a fresh DB read (not merely trusting the in-process return value) |
| 8 | `CONTENT_GENERATION` is never triggered | §7/§10's before/after `CONTENT_GENERATION`-task-count diff must be zero; `NEWS_ANALYSIS`'s own real `WorkflowDefinition` (§ M0's own re-verification) has no step that invokes `run_content_generation_for_event` or creates a `CONTENT_GENERATION` task — mechanically impossible via this code path, and mechanically checked anyway |
| 9 | `ContentDraft` is never created | §7/§10's before/after `ContentDraft`-count diff must be zero; no code in `EngagementCapability`, `WorkflowRunner`, or `CapabilityExecutor` ever constructs a `ContentDraft` row (Contract §7/§12, re-confirmed by `tests/test_content_draft_service.py::test_capabilities_never_import_content_draft`'s own auto-discovering AST check, which already covers every file under `capabilities/`) |
| 10 | Rollback/cleanup strategy | §11 below |

## 10. Post-execution verification (re-run §7's exact query set, diff against recorded baseline)

```python
# READ-ONLY verification. Run immediately after §8.
import asyncio
from sqlalchemy import select, func
from database.session import async_session_factory
from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.content_draft import ContentDraft
from schemas.workflow import WorkflowType
from uuid import UUID

TASK_ID = UUID("PASTE-THE-SAME-EXACT-UUID-FROM-SECTION-8-HERE")

async def verify():
    async with async_session_factory() as session:
        task = await session.get(EditorialTask, TASK_ID)
        print("Target task final status:", task.status.value)
        print("Target task step_results:", task.workflow.get("step_results"))

        # Re-run §7's exact six counts; every one of the other five (all except the target
        # task's own status bucket) must be unchanged from the recorded baseline. The
        # CONTENT_GENERATION count and ContentDraft count MUST be identical to baseline -
        # zero delta, not merely "small."
        for status in (TaskStatus.CREATED, TaskStatus.RUNNING, TaskStatus.COMPLETED, TaskStatus.FAILED):
            n = (await session.execute(
                select(func.count(EditorialTask.id)).where(EditorialTask.status == status)
            )).scalar()
            print(f"EditorialTask count [{status.value}]:", n)

        cg = (await session.execute(
            select(func.count(EditorialTask.id)).where(
                EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.CONTENT_GENERATION.value
            )
        )).scalar()
        print("CONTENT_GENERATION task count (must equal §7 baseline exactly):", cg)

        drafts = (await session.execute(select(func.count(ContentDraft.id)))).scalar()
        print("ContentDraft count (must equal §7 baseline exactly):", drafts)

asyncio.run(verify())
```

**Pass criteria**: `EditorialTask [CREATED]` count decreases by exactly 1 relative to baseline
(the target task leaving `CREATED`); exactly one of `[RUNNING]`/`[COMPLETED]`/`[FAILED]` reflects
that same task landing somewhere (in the success case, `[COMPLETED]` increases by exactly 1,
`[RUNNING]`/`[FAILED]` unchanged); `CONTENT_GENERATION` count and `ContentDraft` count are
**bit-for-bit identical** to the §7 baseline — zero tolerance, any nonzero delta is an
immediate STOP-and-report condition, not something to explain away.

## 11. Rollback / cleanup strategy

**If the target task reaches `COMPLETED` with valid output**: no rollback — this is the intended,
successful outcome. Nothing to clean up; the task's real, correct completion is exactly what M7
exists to prove.

**If the target task reaches `FAILED`** (a genuine step failure, not a claim-loss): this is an
honest, disclosed outcome per the Plan's own instruction ("confirm the task reaches COMPLETED, or
document the real outcome honestly if it does not, without adjusting thresholds to force
success"). No rollback of the `FAILED` state itself — it is real, informative data. Report the
failure's exact `step`/`error_type`/`message` (from `EditorialTask.workflow["failure"]`) and stop;
do not retry the same task_id without a fresh, separate human authorization (§8's own instruction,
mirrors Plan §14 step 9).

**If §10's verification finds any unexpected delta** (a `CONTENT_GENERATION` task,
`ContentDraft` row, or a change to any `EditorialTask` other than the one target `task_id`):
this is a genuine safety-invariant violation, not a cosmetic issue. Stop immediately. Do **not**
attempt an automated rollback of unrelated rows — identify the exact affected row(s) by direct
query (mirroring M3's own remediation technique: read the row, diff against what it should be, if
genuinely caused by this session's own action revert to its pristine pre-run state using the same
`WorkflowExecutionState`-reconstruction technique M3's report documents), and report to a human
before any further action. This mirrors the exact remediation path already proven necessary and
sufficient during the M3 incident.

**If the atomic claim itself fails** (`TaskAlreadyRunningError`/`TaskAlreadyCompletedError`, §8):
no rollback needed — the target task's state was never touched by this session's own action (the
`UPDATE` affected 0 rows); whatever changed it was a different, external process. Report and
return to §5/§6 for a fresh cycle if desired.

**Test-owned artifacts**: none are created by this procedure — §5/§7/§8/§10 are all read-only or
operate on one real, pre-existing production row. There is no synthetic `NewsSource`/`NewsEvent`
to clean up (unlike M3/M5's own automated tests), so no FK-safe teardown sequence is required
here.

## 12. Explicit non-goals / boundary restated

M7, even once authorized and executed successfully, does **not** authorize: starting
`worker/analysis_main.py` against the live backlog; enabling `news_analysis_enabled=true` in any
persistent environment; a second or repeated live task without a fresh, separate authorization;
any `CONTENT_GENERATION`, `ContentDraft`, image, or publishing work (Phase 14+ territory,
untouched by Phase 13 entirely). A successful M7 is evidence the implementation works — it is not,
by itself, authorization to begin continuous production operation.

---

**This document defines the procedure only. No step in §5 or later has been executed in
producing this document. M7 remains unauthorized pending a human's explicit go-ahead at the §6
checkpoint for a specific, then-current `task_id`.**
