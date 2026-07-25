# Phase 9.5 — Workflow Hardening Decision Resolution

**Status: analysis only. No production code, test, or migration was modified to produce this
document. No commit was created.** This document resolves the exact, binding shape Option A
(per-step persistence, recommended by `docs/phase9_5_workflow_hardening_discovery.md`) must take
if a future phase implements it. It does not implement Option A. It is not itself a Contract —
it is the precursor a Contract amendment would be drafted from.

Re-read fresh for this document, confirmed unchanged since Discovery: `workflows/runner.py`,
`services/workflow_service.py`, `capabilities/executor.py`, `schemas/workflow.py`,
`database/models/editorial_task.py`. `git rev-parse HEAD` = `9d51a1c5304586bfc30f918ba73b860f8b5826d7`,
matching Discovery's baseline exactly. No drift.

---

## 1. Exact Phase 9.5 boundary

**In scope**: deciding, precisely and unambiguously, the exact commit-timing, transaction, and
failure semantics for one specific, narrow change — adding a per-step persistence point inside
`WorkflowRunner._execute_steps()`'s loop — sufficient for a future implementation phase to build
it without further architectural judgment calls, and for a Contract amendment to cite exact
line-level intent.

**Out of scope** (unchanged from Discovery's non-goals, restated here for this document's own
completeness, not re-derived): implementing Option A; redesigning `WorkflowRunner`; redesigning
`WorkflowDefinition`/`WorkflowStepDefinition`/`WorkflowExecutionState`/`WorkflowStepResult`/
`WorkflowRunResult`; any migration; any scheduler; durable distributed execution; crash/process-
interruption recovery (a distinct, larger problem, already disclosed in Contract §14.1 and
Discovery §5/§6); any change to `Capability`/`CapabilityContext`/`CapabilityResult` contracts;
any change to `LLMGateway`; any change to `PromptRepository`. This document produces a decision
record only — no file under `workflows/`, `capabilities/`, `services/`, `schemas/`, or
`database/` is touched by producing it.

---

## 2. What Option A changes

Exactly one thing: **the number and placement of the already-existing `state.step_results =
step_results; task.workflow = state.model_dump(mode="json"); await session.commit()` triplet's
execution sites** inside `workflows/runner.py`. Today this triplet (in slightly different local
variable order, but the same three operations) executes at exactly two sites, both already
present in the file: the post-loop success path (`_execute_steps()`, current lines 191–195) and
`_fail()` (lines 276–285). Option A adds **one more execution site** for this same triplet,
positioned inside the `for step in remaining_steps:` loop (current lines 159–187), immediately
after `state.completed_steps.append(step.name)` (current line 187) — i.e., for every step whose
outcome allows the loop to continue to the next step (a `SUCCESS` outcome, or a `SKIPPED`
optional-step failure), not for a required step's failure, which already exits via the existing
`_fail()` path before reaching line 187.

No new field is introduced on `WorkflowExecutionState`/`WorkflowStepResult`/`EditorialTask`. No
existing field's *meaning* changes — only the *frequency* at which the already-existing
`task.workflow` snapshot and its already-existing commit are produced.

---

## 3. What Option A explicitly does NOT change

- `StepExecutor` Protocol signature (`workflows/runner.py:64-80`) — unchanged; `execute(self,
  step: WorkflowStepDefinition) -> dict[str, Any]` remains exactly as is.
- `WorkflowDefinition`/`WorkflowStepDefinition`/`WorkflowExecutionState`/`WorkflowStepResult`/
  `WorkflowRunResult` (`schemas/workflow.py`) — zero field added, removed, or retyped.
- `capabilities/executor.py` — **zero-line diff**. `CapabilityExecutor` already re-parses
  `task.workflow` fresh on every `execute()` call (`_build_context()`, line 114); it needs no
  code change to observe more current data once that data is committed more often.
- `database/models/editorial_task.py` — no new column, no type change, no migration.
  `workflow: Mapped[dict | None] = mapped_column(JSON, nullable=True)` (line 44) is unchanged.
- `services/workflow_service.py` — `create_task()`, `get_task()`, `_find_active_task()`,
  `_to_read_schema()` are all unaffected; none of them assumes anything about *when*
  `task.workflow` becomes durable mid-run, only about its shape, which is unchanged.
- `_fail()` (`workflows/runner.py:262-288`) — zero-line diff. It already receives the
  accumulated `step_results` list by reference and independently re-serializes and commits the
  full state on failure; Option A does not need to, and does not, touch this method.
- `run()`'s guard semantics (`TaskAlreadyRunningError`/`TaskAlreadyCompletedError`, lines
  114-117) — unchanged. No "resume" verb, status, or code path is added. A crash mid-loop still
  leaves the task `RUNNING` and unresumable via `run()`, exactly as today.
- Retry/iteration semantics (`docs/phase5_workflow_engine_planning.md`'s definitions, restated
  in `workflows/runner.py`'s own module docstring) — unchanged. An "iteration" is still one full
  pass through every not-yet-completed step; a "retry" still never advances `iteration_count`.
- No rollback logic is added anywhere (see §7). No defensive `session.rollback()` call is
  introduced — this remains a distinct, separately-flagged open question (Discovery §8, item 1),
  not bundled into Option A.
- `Capability`/`CapabilityContext`/`CapabilityResult` contracts, `LLMGateway`, `PromptRepository`
  — untouched, per the hard constraints; nothing in this decision requires touching any of them.

---

## 4. Transaction semantics

Each step whose outcome allows the loop to continue (`SUCCESS`, or `SKIPPED` for an optional
step) becomes its own, complete, independent database transaction: the implicit transaction
SQLAlchemy's `AsyncSession` begins after the previous `commit()` covers exactly that one step's
`task.workflow` reassignment, then `await session.commit()` closes it. This is the same
transactional granularity discipline already established in this codebase by
`services/collector.py` (one commit per source) and Phase 9 M3's `services/triage_orchestrator.py`
(one commit per event) — "commit the smallest safely-durable unit of work" — now applied at
"per step that completes or is skipped" granularity instead of "per whole run." No distributed
transaction, no two-phase commit, and no cross-session coordination is introduced; every commit
remains a plain, single-session operation on the one `AsyncSession` `WorkflowRunner.run()`
already owns for the whole call, exactly mirroring how Phase 9 M3's own transaction discipline
was framed for the Triage Orchestrator.

---

## 5. Commit timing

**Exact point**: immediately after `state.completed_steps.append(step.name)` (current line 187),
before the `for` loop's next iteration begins. Not before the step executes (no result exists
yet to persist, so no benefit); not deferred until the loop ends (that is exactly today's
behavior, and exactly the gap being closed).

At that point, immediately before the new commit:
1. `state.step_results = step_results` (sync the in-memory accumulated list into `state`, the
   same assignment the post-loop path already performs at line 191 — just performed once per
   step instead of once at the end).
2. `task.workflow = state.model_dump(mode="json")` (the same serialization already used at
   lines 194 and 284).
3. `await session.commit()`.

`state.current_step` requires no special handling: it is already set to the step's own name at
the top of that iteration (`state.current_step = step.name`, current line 160) before the step
runs, and remains so until the next iteration's own top-of-loop assignment overwrites it. The
per-step commit simply makes that already-designed, already-correct value observable earlier
(mid-run) rather than only at the very end (where it is explicitly reset to `None`, line 190) —
no new meaning is assigned to `current_step`.

`task.status` is **not** touched by the new per-step commit — it remains `RUNNING` (set once, at
`run()`'s own commit, current line 122-123) for every per-step commit; only the terminal commits
(`_execute_steps()`'s post-loop success path, or `_fail()`) ever change `task.status` away from
`RUNNING`.

---

## 6. Failure behavior

Unchanged in every observable respect. A required step's `"FAILED"` outcome (the default, and
the only case reachable by the real `NEWS_ANALYSIS`/`CONTENT_GENERATION` definitions today, since
neither sets `required=False` on any step) takes exactly the same exit it does today: `return
await self._fail(...)` (current lines 169-172), **before** reaching line 187 and therefore before
the new per-step commit point — a required step's own failing attempt is never separately
committed by Option A; it is committed exactly once, by the pre-existing `_fail()` call, exactly
as today.

An optional step's `"FAILED"` outcome (not reachable by any real definition today, but a real,
already-implemented code path, current lines 173-186) appends a `SKIPPED` `WorkflowStepResult`
and *does* fall through to line 187 and the new per-step commit — consistent with treating
`SKIPPED` the same as `SUCCESS` for persistence purposes, since both represent "this step is
finished and the loop is continuing," which is exactly the condition the per-step commit exists
to make durable.

Retry attempts *within* one step (`_run_step()`, current lines 220-260) are **not** individually
committed by Option A — only the step's final outcome (after all attempts are exhausted, or after
the first success) reaches line 187 and the new commit point. `task.retry_count` increments
(line 222) become durable at that same per-step commit, one step later than they occur — an
incidental improvement in durability granularity over today (previously only durable at the
run's single terminal commit), not a new mechanism.

---

## 7. Rollback behavior

Option A introduces **no new rollback logic**, deliberately. It follows the exact existing
pattern: zero `await session.rollback()` calls exist anywhere in `workflows/runner.py` today
(confirmed again on this re-read), and Option A adds none. If the new per-step `commit()` call
itself raises (a genuine DB-level failure — connectivity loss, constraint violation, etc.), that
exception is **not** caught by the new code; it propagates exactly as any other untyped exception
already does in this module today (out through `_run_step`/`_execute_steps`/`run()`'s
`asyncio.wait_for` wrapper — which only catches `TimeoutError` — to the original caller). Adding
defensive rollback-on-untyped-exception is a distinct, separately-flagged hardening question
(Discovery §8, item 1) and is explicitly **not** part of Option A's scope, to keep this decision's
diff to exactly what closes the same-pass `step_results` gap and nothing else.

---

## 8. Compatibility with existing workflows

`NEWS_ANALYSIS` and `CONTENT_GENERATION` (both frozen, all steps `required=True` in both
definitions — confirmed by re-reading `workflows/definitions/news_analysis.py`; no step in
either file overrides `required`) are unaffected in every **final, observable** outcome:
`WorkflowRunResult.status`, `WorkflowRunResult.step_results`, `EditorialTask.status`, and the
final `EditorialTask.workflow` snapshot at run-end are byte-for-byte identical to today's
behavior for any run that does not crash mid-loop. Only the **durability timing** of
intermediate progress changes: a concurrent reader (e.g., `get_task()`, or a future dashboard)
can now observe a `RUNNING` task's `completed_steps`/`step_results` growing step by step, where
today it sees only the pre-run snapshot until the entire run finishes.

**One concrete, minor consequence worth naming explicitly**: for a **one-step** workflow
definition (none exists among real definitions today, but the schema permits
`steps: list[WorkflowStepDefinition] = Field(min_length=1)`), Option A causes **two** commits
instead of one for that single step's successful pass — the new per-step commit (leaving
`status == RUNNING`, that step already reflected) immediately followed by the pre-existing
post-loop commit (finalizing to `status == COMPLETED`). This is a harmless, minor overhead
(one extra commit, same final state), not a correctness issue, but should be named in any
Contract amendment rather than left as a silent side effect.

Every existing test in `tests/test_workflow_runner.py` that asserts on `WorkflowRunResult`/final
`task.workflow`/`task.status` after a *completed* `run()` call is expected to continue passing
unmodified, since none of those final values change under Option A.

---

## 9. Compatibility with Phase 8 Capability Layer

`CapabilityExecutor` (`capabilities/executor.py`) requires **zero** code change (§3) — it already
re-reads `task.workflow` fresh on every `execute()` call; Option A only makes that data more
current for steps still to come in the same pass. `capabilities/registry.py`,
`capabilities/gateway_call.py`, `capabilities/errors.py`, `ScoringCapability`, `QualityCapability`
are all untouched and unaffected.

Their existing tests (`tests/test_scoring_capability.py`, `tests/test_quality_capability.py`,
`tests/test_capability_boot_wiring_e2e.py`, `tests/test_phase8_cross_cutting_regression.py`)
exercise **single-step** synthetic workflows exclusively today. For a single-step workflow,
Option A is a near-no-op from the Capability layer's perspective: that one step's outcome is
committed once by the new per-step point and then re-committed (redundantly but harmlessly, same
data) by the existing post-loop commit, exactly as described in §8's one-step case. No Phase 8
Capability, test, or contract requires any change.

---

## 10. Compatibility with Phase 9 Research/Intelligence

This is the motivating case Option A exists to fix. Under Option A, a synthetic two-step
`research → intelligence` `WorkflowDefinition` run through one `WorkflowRunner.run()` call would,
for the first time, have Intelligence's step correctly observe Research's
`step_results["research"]` — closing exactly the gap Phase 9 M7 discovered and this document's
own Discovery predecessor confirmed independently.

`capabilities/research_capability.py` and `capabilities/intelligence_capability.py` require
**zero** code change — both already read/write through the existing, correct mechanism
(`ResearchCapability` returns its structured output normally; `IntelligenceCapability` already
reads `context.business.workflow_state.step_results.get("research", {})`, per Phase 9 M5). The
bug was never in either Capability; it was entirely in `WorkflowRunner`'s persistence timing
(confirmed by both Discovery and this document).

**Required follow-up, explicitly named, not performed by this document**: Phase 9 M7's own test
`tests/test_phase9_research_intelligence_integration.py::test_both_capabilities_dispatch_in_order_and_synthetic_task_completes`
currently asserts, as a deliberate regression lock, that Intelligence's built prompt says
"Research did not run" — this assertion is only true because Option A does not exist yet. If
Option A is ever implemented, that specific assertion **must** be updated (by whoever implements
Option A, as part of that phase's own test-update responsibility, per Discovery §8 item 4 and
restated here) to assert the corrected, positive propagation instead. The companion test,
`test_step_results_mechanism_surfaces_a_result_already_persisted_before_the_run_began`, is
unaffected either way — it tests the pre-seeded/resumed-task scenario, which remains valid
regardless of whether Option A ships.

---

## Required decisions

### A. After which exact point does a successful step commit?

Immediately after `state.completed_steps.append(step.name)` — current `workflows/runner.py:187`
— for a step whose outcome is `SUCCESS`, or `SKIPPED` (optional-step failure that lets the loop
continue). Not before the step's `_run_step()` call; not deferred to loop-end. See §5 for the
exact three-statement sequence to run at that point.

### B. What happens if commit fails after a successful Capability execution?

The new `await session.commit()` call is not wrapped in any new exception handling. If it
raises, the exception propagates uncaught out of `_execute_steps()`, out of `run()`'s
`asyncio.wait_for` wrapper (which only catches `TimeoutError`), to `run()`'s original caller —
identical treatment to any other untyped exception in this module today (§7). The Capability's
own side effect (its Gateway call) already happened and cannot be undone — this is already true
today for the run's single terminal commit and is not a new risk category, only a higher-
frequency occurrence of an already-accepted one (a commit can now fail at up to N points for an
N-step workflow instead of only at the very end). The task's durable status in this case is
exactly whatever the database itself resolved for that specific commit attempt — ordinary
commit-failure ambiguity, unchanged in kind from today, not specific to Option A.

### C. What happens if the next step fails?

Say step N committed successfully under the new per-step point, and step N+1 (required) then
fails after exhausting its retries. `_execute_steps()` takes exactly the existing, unmodified
`_fail()` path (current lines 169-172), passing the full in-memory `step_results` list — which
now includes both step N's already-committed `SUCCESS` result and step N+1's `FAILED` result.
`_fail()` (unmodified, §3) re-serializes the **entire** `state` (including step N's data, which
is thus committed twice — once by the new per-step point, once more, redundantly, by `_fail()`'s
own commit) and writes `task.status = FAILED`. This redundant re-write is harmless: it is a full
overwrite of `task.workflow` with self-consistent data, not an increment, so there is no
double-application or corruption risk. The end state — `FAILED`, with step N's success and step
N+1's failure both correctly reflected — matches exactly what `_fail()` already produces today
(§2.5 of Discovery), Option A changes only that step N's data was *also* independently durable
one commit earlier.

### D. What state remains visible?

Immediately after step N's per-step commit and before step N+1 begins: `task.status == RUNNING`
(unchanged since `run()`'s own start-of-run commit); `task.workflow.completed_steps` includes
step N (and every earlier step of this pass); `task.workflow.step_results` includes step N's
`WorkflowStepResult` (with `.result` populated for a `SUCCESS`); `task.workflow.current_step ==
step N's name` (per §5, unchanged in meaning, just observable earlier). Any concurrent
reader — a separate session, a different process, `get_task()` — can, for the first time, observe
this genuinely in-progress, per-step snapshot; today such a reader sees only the pre-run snapshot
for the entire duration of a `RUNNING` task.

### E. How does existing `_fail()` behavior interact?

`_fail()` is not modified by Option A (§3, §C above) and requires no interaction logic: it is
simply the terminal commit, and it is self-consistent whether zero, some, or all prior steps in
the pass already received their own per-step commit. Because every commit (per-step or
`_fail()`'s own) writes a **full, independently-valid** `WorkflowExecutionState` snapshot — never
a partial or incremental update — there is no ordering hazard, no merge logic needed, and no
scenario in which `_fail()`'s commit could observe or produce an inconsistent state relative to
the per-step commits that preceded it in the same pass.

### F. What tests prove correctness?

Mandatory, if Option A is implemented (specified here so a future phase does not need to
re-derive this list; none of these are written by this document):

1. **Same-pass propagation (positive fix-confirmation)**: a two-step synthetic workflow
   (mirroring Phase 9 M7's own `_synthetic_research_intelligence_registry()`), run through one
   `WorkflowRunner.run()` call, where the second step's built `CapabilityContext.business.
   workflow_state.step_results` genuinely contains the first step's result — replacing Phase 9
   M7's current regression-lock assertion (§10) with its positive counterpart.
2. **Per-step durability**: after step N's per-step commit, a **second, independent** session
   (own connection, not `WorkflowRunner`'s own) can read `task.workflow` and observe step N's
   result *while* step N+1 is still executing — proven by pausing/monkeypatching step N+1's
   executor, mirroring Phase 9 M3's own transaction-discipline test technique
   (`tests/test_triage_orchestrator_cycle.py`).
3. **Commit-failure propagation (§B)**: a monkeypatched `session.commit()` that raises on its
   Nth invocation (targeting the new per-step commit specifically, not the run-start or
   terminal one) results in that exception propagating out of `run()` uncaught — no silent
   swallow, no partial/successful `WorkflowRunResult` returned.
4. **Step N+1 failure after step N's committed success (§C)**: the final persisted
   `task.workflow`/`WorkflowRunResult` correctly shows step N as `SUCCESS` and step N+1 as
   `FAILED`, and `task.status == FAILED` — proving `_fail()`'s redundant re-write is harmless and
   correct, not merely assumed so.
5. **Retry-count durability under the new cadence**: confirms `task.retry_count` is correctly
   reflected once persisted at the new per-step commit point, guarding the incidental behavior
   change named in Discovery §6.
6. **One-step-workflow double-commit is harmless**: confirms a one-step definition still reaches
   `COMPLETED` with correct final state despite the two-commit sequence named in §8 — a direct,
   executed proof of that named consequence, not left merely described.
7. **Zero regression**: the full, unmodified-in-intent `tests/test_workflow_runner.py` suite
   (full success, required-step failure, optional-step skip, max-iterations, step timeout/retry,
   whole-workflow timeout) continues to pass; likewise `tests/test_capability_boot_wiring_e2e.py`,
   `tests/test_phase8_cross_cutting_regression.py`, and every Phase 9 M0–M7 test suite.
8. **Required Phase 9 test update, named explicitly (§10)**: Phase 9 M7's
   `test_both_capabilities_dispatch_in_order_and_synthetic_task_completes` must be updated to
   assert the corrected propagation instead of the current regression-lock; this is a required
   part of implementing Option A, not optional cleanup.

---

## Hard non-goals (confirmed respected by this document)

Nothing above redesigns `WorkflowRunner`, redesigns any workflow schema, adds a migration, adds a
scheduler, adds durable distributed execution, solves crash recovery, or changes any Capability
contract, `LLMGateway`, or `PromptRepository`. This document adds no code, no test, and no
migration — it is a decision record.

---

PHASE 9.5 DECISION RESOLUTION COMPLETE — WAITING FOR CONTRACT.
