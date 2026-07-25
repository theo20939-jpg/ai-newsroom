# Phase 9.5 — Workflow Engine Hardening Discovery

**Status: exploration only. No production code, test, or migration was modified to produce
this document. No commit was created.**

This document independently re-verifies the limitation Phase 9 M7 discovered (`WorkflowRunner`
does not make an earlier step's result visible to a later step within the same `run()` call),
traces the full Workflow Engine execution lifecycle from source, and evaluates fix options
without implementing any of them, per the Phase 9.5 instructions.

---

## 1. Baseline confirmation

```
HEAD: 9d51a1c5304586bfc30f918ba73b860f8b5826d7

git log --oneline -10:
9d51a1c Implement Phase 9 M7: integration proof and regression checkpoint
882315b Implement Phase 9 M6: capability registration and boot wiring
cc8bb2a Implement Phase 9 M5: intelligence capability
3b94392 Implement Phase 9 M4: research capability
22af66d Implement Phase 9 M3: triage orchestration service and script
15e375d Implement Phase 9 M2: atomic NewsEvent claim and stale-recovery primitives
b19e651 Implement Phase 9 M1: deterministic Triage policy (Freshness + Triage)
75c32ed Implement Phase 9 M0: architecture validator extension
dc35f9f Add Phase 8 governing architecture documents
1813fd9 Implement Phase 8 M8: cross-cutting regression checkpoint

git status --short: only the pre-existing, untracked docs/phase9_*.md audit-trail files
(unchanged by this session). Working tree otherwise clean.
```

Phase 9 M0–M7 commits are all present and this document was produced against that exact state.
Nothing was modified.

---

## 2. Current architecture (as read, with exact citations)

### 2.1 Component map

| File | Role |
|---|---|
| `schemas/workflow.py` | `WorkflowType`, `WorkflowDefinition`/`WorkflowStepDefinition` (static, frozen definitions), `WorkflowExecutionState`/`WorkflowStepResult` (the JSON-serializable runtime snapshot persisted into `EditorialTask.workflow`), `WorkflowRunResult` (return value of `run()`). |
| `workflows/registry.py` | `WorkflowRegistry` — name/version → `WorkflowDefinition`, sealed after `build_registry()`. No DB, no runtime state. |
| `workflows/definitions/news_analysis.py` | The real, frozen `NEWS_ANALYSIS` definition: 4 required steps, `research → intelligence → engagement_analysis → scoring`. |
| `workflows/runner.py` | `WorkflowRunner` — the only component that ever advances `EditorialTask.status` or drives step execution. `StepExecutor` Protocol is its sole seam into Capability-layer code. |
| `services/workflow_service.py` | `create_task()`/`get_task()` — creates the initial `EditorialTask` row (status `CREATED`, empty `step_results`) and reads it back; never changes `status`. |
| `capabilities/executor.py` | `CapabilityExecutor` — implements `StepExecutor`, bridges to `CapabilityRegistry`, builds each step's `CapabilityContext` (including `step_results`) from `EditorialTask.workflow`. |
| `database/models/editorial_task.py` | `EditorialTask.workflow: Mapped[dict | None] = mapped_column(JSON, nullable=True)` — a plain, un-tracked JSON blob column (no SQLAlchemy `MutableDict`/`MutableList` wrapper). |
| `schemas/editorial_task.py` | `EditorialTaskCreate`/`EditorialTaskRead` — DTOs at the `workflow_service` boundary; not involved in step execution. |

### 2.2 Execution lifecycle, traced end to end

1. **Task creation** (`services/workflow_service.py:27-78`): `create_task()` resolves the
   `WorkflowDefinition`, builds a fresh `WorkflowExecutionState(current_step=<first step name>,
   completed_steps=[], iteration_count=0, step_results=[], failure=None)`, and writes it as
   `EditorialTask.workflow` on a new row with `status=CREATED`. One commit
   (`workflow_service.py:71`).

2. **`WorkflowRunner.run(session, task_id)`** (`workflows/runner.py:103-145`):
   - Fetches `task` via `session.get()` (line 111).
   - Guards: `TaskNotFoundError` if missing; `TaskAlreadyRunningError` if `status == RUNNING`;
     `TaskAlreadyCompletedError` if `status` is `COMPLETED` or `FAILED` (lines 112-117). **There
     is no "resume" status or verb** — only `CREATED`/`WAITING` tasks (i.e., anything not
     RUNNING/COMPLETED/FAILED) can enter `run()`.
   - Parses `state = WorkflowExecutionState.model_validate(task.workflow)` (line 119) and
     resolves the `WorkflowDefinition` from the registry (line 120).
   - Sets `task.status = RUNNING` and **commits** (lines 122-123) — this is commit #1, and the
     only durable fact at this point is `status == RUNNING`; `task.workflow` is untouched.
   - If `iteration_count >= max_iterations`, fails immediately (lines 127-131).
   - Otherwise calls `self._execute_steps(...)` wrapped in `asyncio.wait_for(...,
     timeout=definition.timeout_seconds)` (lines 133-136) — the whole-workflow timeout.

3. **`_execute_steps()`** (`workflows/runner.py:147-203`) — runs every **not-yet-completed**
   step (`remaining_steps = [s for s in definition.steps if s.name not in
   state.completed_steps]`, line 157) in a single Python `for` loop, entirely in memory:
   - `step_results: list[WorkflowStepResult] = list(state.step_results)` (line 156) — a **local
     Python list**, seeded from whatever was already in `task.workflow` at the top of `run()`,
     but from this point on it only exists in this method's stack frame.
   - For each step: `outcome = await self._run_step(task, state.workflow_name.value, step,
     step_results)` (line 161) — `step_results` is passed **by reference** and mutated in place
     by `_run_step` (appended to), but this is a plain Python list, not anything backed by the
     database.
   - A required step's `"FAILED"` outcome ends the loop immediately via `self._fail(...)` (lines
     163-172). An optional step's failure appends a `SKIPPED` result and continues (lines
     173-186). Either way, `state.completed_steps.append(step.name)` happens only for a
     successful or skipped-optional step (line 187) — and this mutates `state`, an in-memory
     Pydantic object, not `task.workflow`.
   - **Only after the entire `for` loop finishes successfully** (line 189 onward):
     `state.iteration_count += 1; state.current_step = None; state.step_results = step_results;
     state.failure = None; task.status = TaskStatus.COMPLETED; task.workflow =
     state.model_dump(mode="json")` (lines 189-194), then `await session.commit()` (line 195).
     **This is the only place a successful step's result is ever written to `task.workflow`.**

4. **`_run_step()`** (`workflows/runner.py:205-260`) — attempts one step up to
   `step.max_attempts`:
   - Calls `await asyncio.wait_for(self._executor.execute(step), timeout=step.timeout_seconds)`
     (line 227). **`self._executor.execute(step)` receives only the `WorkflowStepDefinition` —
     no `state`, no `step_results`, no `task`** (confirmed: the `StepExecutor` Protocol,
     `workflows/runner.py:64-80`, declares `execute(self, step: WorkflowStepDefinition) ->
     dict[str, Any]` — a single argument).
   - On `PermanentStepFailureError`: appends a `FAILED` `WorkflowStepResult` to the (in-memory)
     `step_results` list and returns `"FAILED"` immediately, no retry (lines 233-240).
   - On `StepExecutionError`/`StepTimeoutError`: appends a `FAILED` result; retries unless
     `attempt == step.max_attempts`, in which case returns `"FAILED"` (lines 241-250).
   - On success: appends a `SUCCESS` result (with `result=<the dict the executor returned>`) and
     returns `"SUCCESS"` (lines 251-258).
   - `task.retry_count += 1` is incremented in-memory on each retry attempt (line 222) but, like
     `step_results`, is not committed until the run's single terminal commit.
   - **`task.workflow` is never referenced anywhere in `_run_step()`.**

5. **`_fail()`** (`workflows/runner.py:262-288`) — the other (and only other) site that writes
   `task.workflow`: `state.step_results = step_results; state.failure = {...}; task.status =
   TaskStatus.FAILED; task.workflow = state.model_dump(mode="json")`, then `await
   session.commit()`. Called from `_execute_steps()` (required-step failure), and from `run()`
   itself (max-iterations-exceeded, or the outer `asyncio.wait_for` timing out).

6. **`CapabilityExecutor.execute(step)`** (`capabilities/executor.py:59-109`) — the real
   `StepExecutor` implementation used once real Capabilities exist (Phase 6+, and now Phase 9's
   `research`/`intelligence`):
   - Re-fetches `task = await self._session.get(EditorialTask, self._task_id)` (line 69) — same
     `AsyncSession` object `WorkflowRunner` holds (constructor-injected once per `run()`, per
     `docs/phase6_architecture_contract.md` §5 rule 1 and this file's own module docstring:
     "zero changes to workflows/runner.py... constructor injection"). SQLAlchemy's identity map
     means this returns the *same Python `EditorialTask` object* WorkflowRunner is holding — but
     its `.workflow` attribute *value* is whatever it was last **assigned**, which (per steps 3–5
     above) only happens at run-start (from `create_task()`/a prior run) or at run-end.
   - `_build_context()` (lines 111-147): `state = WorkflowExecutionState.model_validate(
     task.workflow)` (line 114) — a **fresh parse of the ORM attribute**, then builds
     `step_results={r.step_name: r.result for r in state.step_results if r.status == "SUCCESS"
     and r.result is not None}` (lines 129-133) for the `CapabilityContext` a Capability receives.

### 2.3 Transaction boundaries / commit points (exhaustive)

`grep -n "commit\|task.workflow" workflows/runner.py` yields exactly:

```
119:  state = WorkflowExecutionState.model_validate(task.workflow)   # read
123:  await session.commit()                                        # RUNNING transition only
194:  task.workflow = state.model_dump(mode="json")                 # write — success, end of loop
195:  await session.commit()
284:  task.workflow = state.model_dump(mode="json")                 # write — failure
285:  await session.commit()
```

Plus one write at task creation (`services/workflow_service.py:66`, before any `run()` call).
**`task.workflow` is written at exactly three points in the whole system, and never mid-loop.**

### 2.4 Rollback behavior

No `await session.rollback()` call exists anywhere in `workflows/runner.py` (confirmed by
reading the entire file). Every reachable failure the module itself anticipates
(`StepExecutionError`, `StepTimeoutError`, `PermanentStepFailureError` at the step level;
`MaxIterationsExceededError`, `WorkflowTimeoutError` at the run level) is converted into a
`_fail()` call, which **commits** a `FAILED` state rather than rolling anything back. An
unanticipated exception (anything not in that typed set) is not caught here at all — it
propagates to the caller with whatever was mutated on the session left as-is; `WorkflowRunner`
performs no defensive rollback for that case.

### 2.5 Failure / retry semantics

- **Retry** = repeated attempts at *one* step, bounded by that step's own `max_attempts`,
  tracked via `task.retry_count` (a column, but only durable at the run's terminal commit) —
  never advances `iteration_count`.
- **Iteration** = one full pass through every not-yet-completed step of the definition, counted
  only when that pass finishes. A required step's exhausted-retry failure ends the run
  immediately (`FAILED`) — it does not consume another iteration or get retried at the iteration
  level.
- A `FAILED` or `COMPLETED` task is **terminal** — `run()` unconditionally rejects both via
  `TaskAlreadyCompletedError` (lines 116-117). There is no "resume from failure" verb anywhere
  in the inspected files.

---

## 3. Independent verification of the Phase 9 finding

Answering the seven questions directly, from the trace above (not merely re-citing the prior
report):

**1. Where is `EditorialTask.workflow` mutated?**
Exactly three sites, all full-object reassignments (never in-place dict mutation, which
wouldn't be tracked anyway since the column has no `Mutable*` wrapper — see §2.1):
`services/workflow_service.py:66` (creation), `workflows/runner.py:194` (success, post-loop),
`workflows/runner.py:284` (failure, in `_fail()`).

**2. When is it persisted?**
Only when one of those three assignments is followed by `await session.commit()` — which, for
the two `runner.py` sites, happens only *after* `_execute_steps()`'s entire `for` loop over
`remaining_steps` has finished (success) or a step has permanently failed (failure). There is no
per-step, mid-loop commit.

**3. When does `CapabilityExecutor` build `CapabilityContext`?**
Once per step, inside `execute(step)` (`capabilities/executor.py:59`), called from
`WorkflowRunner._run_step()` (`workflows/runner.py:227`) — i.e., once per attempt of each step,
during the loop, **before** that step's own result (success or failure) has been persisted, and
necessarily before any *later* step's turn.

**4. Can step N read step N-1 output during the same run?**
**No**, if steps N-1 and N are both un-completed at the start of the same `_execute_steps()`
pass (the normal case for a freshly-created, multi-step task). `CapabilityExecutor` re-parses
`task.workflow`, which has not been reassigned since before the pass began — regardless of
whether step N-1 already succeeded moments earlier in the same loop. Verified independently by
re-tracing `_run_step()`'s call signature (§2.2 point 4: only `step` is passed to
`self._executor.execute(step)`) and by the fact that only 3 write-sites exist for
`task.workflow`, none of them mid-loop. This matches Phase 9 M7's empirical test observation
(`tests/test_phase9_research_intelligence_integration.py`).

**5. Can a resumed workflow read previous outputs?**
Only if `task.workflow.completed_steps`/`step_results` already reflects those steps **before**
`run()` is called, **and** `task.status` is something other than RUNNING/COMPLETED/FAILED (so
`run()`'s guards don't reject it). Mechanically, `CapabilityExecutor`'s read path works
correctly given such pre-existing state (proven by Phase 9 M7's mechanism-verification test,
which seeds it directly). But **no code path in this codebase produces that pre-existing state
as a normal consequence of running a multi-step workflow** — `_execute_steps()` always runs
every remaining step to either full completion or failure in one pass; there is no "pause after
one step, remain resumable" behavior today. So this is a real capability of the read side, not a
currently-reachable production behavior.

**6. What happens after a failed step?**
If required (the default, and true of every step in the real `NEWS_ANALYSIS`/
`CONTENT_GENERATION` definitions — no step in either file overrides `required`): `_fail()` is
called with the full in-memory `step_results` list, which **does** include any earlier steps in
the *same* pass that already succeeded (because it's the same Python list, accumulated by
reference) — so the persisted `FAILED` snapshot correctly shows "steps 1..k-1 succeeded, step k
failed." `task.status` becomes `FAILED`, terminal. If not required: a `SKIPPED`
`WorkflowStepResult` is appended and the loop continues to the next step in the *same* pass
(`workflows/runner.py:173-186`) — not reachable today since no real definition sets
`required=False`.

**7. What happens after process interruption?**
If the crash is after the `RUNNING` commit (line 123) but before the loop finishes: `status ==
RUNNING` is durable, `task.workflow` still holds its pre-run value (no step results persisted at
all, not even ones that had already succeeded), and the task can **never be re-submitted** to
`run()` — `TaskAlreadyRunningError` is unconditional for any `RUNNING` task (line 114-115). There
is no other code path (no cron, no reaper, no manual-reset endpoint) in the inspected files that
clears a stuck `RUNNING` status. This matches, and generalizes, what
`docs/phase9_research_intelligence_architecture_contract.md` §14.1 already documented
specifically for the Research→Intelligence handoff — the trace here confirms it is a property of
`WorkflowRunner` itself, for any multi-step definition, not something specific to Phase 9's two
Capabilities.

**Conclusion**: the Phase 9 M7 report's finding is confirmed, independently, by direct code
trace (not merely by re-running its tests). The root cause is precisely located: `task.workflow`
is reassigned only twice in `workflows/runner.py`, both after the entire step loop for a pass
concludes, never mid-loop — and `CapabilityExecutor` has no channel to WorkflowRunner's
in-memory, not-yet-persisted `step_results` other than re-reading that same, stale
`task.workflow`.

---

## 4. Fix options

### Option A — Persist workflow state after every successful step

Move the existing `state.step_results = step_results; task.workflow =
state.model_dump(mode="json")` + commit pattern (already used at the loop's end and in
`_fail()`) to run **once per step**, inside the `for step in remaining_steps:` loop, immediately
after each step's outcome (success, or skipped-optional) is known — before proceeding to the
next step.

- **Architectural impact**: small and fully localized to `_execute_steps()`'s loop body in
  `workflows/runner.py`. No change to `StepExecutor`'s Protocol signature, `WorkflowDefinition`/
  `WorkflowStepDefinition`/`WorkflowExecutionState`/`WorkflowStepResult`/`WorkflowRunResult`
  shapes, `CapabilityExecutor`, or any Capability-layer file. `CapabilityExecutor` needs **zero**
  code change — it already re-parses `task.workflow` fresh on every call; it would simply start
  observing up-to-date data.
- **Compatibility impact**: none for any existing consumer of `task.workflow`'s shape
  (`services/workflow_service.py`'s `_find_active_task`/`_to_read_schema`, every existing test
  that inspects `WorkflowRunResult`/`task.workflow`). Increases commit frequency from
  once-per-run to once-per-step — the same "commit the smallest safely-durable unit" discipline
  already established in this codebase by `services/collector.py` (per-source) and Phase 9 M3's
  `services/triage_orchestrator.py` (per-event), so it is not a novel transaction pattern here.
- **Migration requirement**: none. `EditorialTask.workflow`'s column type and the
  `WorkflowExecutionState` shape are unchanged — only the timing of an already-existing
  assignment+commit.
- **Rollback complexity**: low. A pure code revert of the loop-body change; no data format
  change to undo, so reverting doesn't corrupt any row written under the new discipline (it's
  the same JSON shape, just written more often).
- **Phase 5/6/7/8 contract impact**: this **does** edit `workflows/runner.py`, a frozen Phase 5
  file — it would need a scoped Contract amendment authorizing exactly this change (commit
  cadence inside one method), not a broader reopening of the Workflow Engine contract. It leaves
  every other Phase 5/6/7/8 guarantee (`StepExecutor` Protocol shape, `CapabilityExecutor`'s
  "zero changes needed" claim, `WorkflowRunResult`'s shape, no new `WorkflowType`, no migration)
  fully intact.
- **Noteworthy side effect, not a target**: per-step commits also make `task.retry_count`
  increments durable per-attempt rather than only at run-end — an incidental, almost certainly
  harmless (arguably more accurate) observability improvement, but should be called out
  explicitly rather than left as a silent side effect if this option is ever implemented.
- **What this option does *not* fix**: crash/interruption recovery. A crash mid-loop still
  leaves the task `RUNNING` and unresumable via `run()`'s existing guards (§3, question 7) — this
  option only makes *already-committed* step results visible to steps still to come in that
  *same*, uninterrupted pass; it does not add a resume verb or change the RUNNING-guard
  semantics.

### Option B — Pass in-memory accumulated state directly into the next step's context

Extend `StepExecutor.execute()`'s signature (or add a new method) so `WorkflowRunner` passes the
in-memory `step_results` list (or a derived snapshot) directly into each call, bypassing
`task.workflow` entirely for the same-pass case.

- **Architectural impact**: larger than Option A. Directly changes the frozen `StepExecutor`
  Protocol (`workflows/runner.py:64-80`) — every implementation (today:
  `DeterministicPlaceholderExecutor`, `CapabilityExecutor`, and any test-local `StepExecutor`)
  must be updated to match the new signature. `CapabilityExecutor._build_context()` would need a
  second source of `step_results` (the passed-in argument) alongside its existing DB-backed read,
  requiring reconciliation logic that doesn't exist today.
- **Compatibility impact**: directly violates `capabilities/executor.py`'s own documented,
  frozen guarantee ("zero changes to workflows/runner.py... constructor injection", citing Phase
  6 §5 rule 1) — this option requires exactly the kind of `StepExecutor`-boundary change that
  guarantee was written to prevent. It also does **not** improve the crash/resume case at all
  (in-memory state is still lost on interruption), while introducing a second, divergent
  `step_results` source that must be kept consistent with the DB-backed one.
- **Migration requirement**: none.
- **Rollback complexity**: medium — a Protocol signature change touches every implementation,
  not one method body.
- **Phase 5/6/7/8 contract impact**: directly edits the frozen `StepExecutor` Protocol and
  breaks a specifically-cited Phase 6 "zero change" guarantee, for a narrower benefit than
  Option A (same-pass only, no crash-recovery improvement, and no schema/persistence benefit
  either).

### Option C — Introduce a workflow execution state object

Formalize a new, shared, in-memory (and possibly self-persisting) "live execution state" object
that both `WorkflowRunner` and `CapabilityExecutor` hold a reference to for the duration of one
`run()` call, replacing today's "each independently re-derives state from `task.workflow`"
design.

- **Architectural impact**: the largest of the three narrower options — this introduces a new
  abstraction into the frozen Workflow Engine/Capability Framework boundary, which is exactly the
  kind of "second orchestration/state concept" the general instructions warn against ("this is
  NOT permission to redesign Workflow Engine") and which Phase 9's own Contract P7 forbids by the
  same logic for a different component. It would require re-wiring how `CapabilityExecutor` is
  constructed (today: `(session, task_id, registry)`, independently self-sufficient) to instead
  receive or reference this new object.
- **Compatibility impact**: high — every caller that constructs `WorkflowRunner`/
  `CapabilityExecutor` (all of `tests/test_workflow_runner.py`,
  `tests/test_capability_boot_wiring_e2e.py`, `tests/test_phase8_cross_cutting_regression.py`,
  every Phase 9 M2/M3/M7 test, any future scheduler) needs updating.
- **Migration requirement**: none *strictly* required for the in-memory-only version, but if this
  object is also asked to solve crash-recovery (a natural next ask once it exists), it would need
  its own persistence — scope creep past what this discovery phase or its stated constraints
  authorize.
- **Rollback complexity**: high.
- **Phase 5/6/7/8 contract impact**: effectively a partial redesign of the Workflow
  Engine/Capability Framework composition — explicitly out of scope per the hard constraints.

### Option D — Redesign workflow persistence

E.g., a normalized per-step-result table, event-sourced step log, or checkpointing mechanism
replacing the single-JSON-blob-per-task model.

- **Architectural impact**: largest by far. New database model(s), almost certainly a migration,
  and changed read/write patterns throughout `workflow_service.py`, `WorkflowRunner`, and
  `CapabilityExecutor`.
- **Compatibility impact**: highest — every consumer of `EditorialTask.workflow`'s current JSON
  shape breaks or needs a compatibility shim.
- **Migration requirement**: almost certainly yes.
- **Rollback complexity**: highest — schema migrations are the hardest class of change to safely
  revert once real data exists.
- **Phase 5/6/7/8 contract impact**: a genuine redesign of a frozen contract area — explicitly
  forbidden by the hard constraints ("do not redesign workflow definitions", "add migrations
  unless absolutely unavoidable", "prefer smallest correction").

### Comparison summary

| | Schema/migration | Protocol change | New abstraction | Frozen-file edit | Fixes same-pass gap | Fixes crash/resume |
|---|---|---|---|---|---|---|
| A | No | No | No | Yes (`runner.py`, localized) | Yes | No |
| B | No | Yes (`StepExecutor`) | No | Yes (larger surface) | Yes | No |
| C | No (in-memory) / maybe (if persisted) | Yes (construction wiring) | Yes | Yes (broad) | Yes | Only if persisted (out of scope) |
| D | Yes | Yes | Yes | Yes (broad) | Yes | Yes (potentially) |

---

## 5. Recommended minimal fix

**Option A.** It is the only option that closes the specific, verified gap (same-pass
`step_results` visibility) without touching the `StepExecutor` Protocol, without a new
abstraction, without a migration, and with a diff contained entirely inside
`_execute_steps()`'s loop body in `workflows/runner.py`. It requires a narrow, explicit Contract
amendment authorizing that one, specific edit to a frozen Phase 5 file — it does not require, and
should not be bundled with, any broader Workflow Engine redesign.

It deliberately does **not** fix crash/process-interruption recovery (§3, question 7) — that
remains the pre-existing, already-disclosed limitation (Contract §14.1), and closing it would
require at least evaluating a "resume" verb and re-examining the RUNNING-guard semantics, which
is out of this discovery's scope and arguably adjacent to Option D territory, not Option A.

---

## 6. Risks (of Option A, if a future phase implements it)

- **Increased commit volume**: one commit per step instead of one per run — for
  `NEWS_ANALYSIS`'s 4 steps, up to 4x the commits per task. Likely immaterial at current scale,
  but worth measuring, mirroring Phase 9 M3's own precedent of measuring real commit-path latency
  before finalizing a similar change.
- **Partial-run visibility**: a task now durably shows `RUNNING` with some steps already
  reflected in `task.workflow` mid-run, where today it shows either the pre-run snapshot or the
  final one. Any code that reads `task.workflow` for a `RUNNING` task (e.g.,
  `_to_read_schema`'s `current_step` derivation) would start seeing more granular, and more
  accurate, in-progress state — should be treated as a positive side effect, not silently.
- **Retry-count durability change**: `task.retry_count` becomes durable per-attempt rather than
  only at run-end — needs an explicit test (§6 below) to confirm no existing assertion relies on
  the old, coarser timing.
- **No change to the crash/resume story**: implementers and reviewers must not conflate "fixes
  the same-pass gap" with "fixes crash recovery" — they are different problems; Option A solves
  only the first.

---

## 7. Non-goals (restated, matching the hard constraints)

This document, and any future implementation of Option A, does **not**:
- redesign Capability architecture, add new Capability abstractions, change `LLMGateway`, or
  change `PromptRepository`;
- add a scheduler;
- add a database migration (Option A requires none; Options C/D might, and are not recommended);
- redesign `WorkflowDefinition`/`WorkflowStepDefinition` or add a new `WorkflowType`;
- fix crash/process-interruption recovery (a distinct, larger problem — see §5, §6);
- fix `_find_active_task()`'s `CREATED`/`RUNNING`-only lifecycle definition (Phase 9's own
  Limitation B, unrelated to this finding).

---

## 8. Open questions (for whoever decides on implementation)

1. Should Option A's per-step commit include a rollback (`await session.rollback()`) on an
   *unexpected* (non-typed) exception between steps, closing the "no rollback anywhere in this
   module" gap noted in §2.4 — or is that a separate hardening concern from step_results
   visibility specifically?
2. Should the Contract amendment authorizing Option A also formally document (not fix) the
   crash/resume limitation as a distinct, still-open item, so it isn't rediscovered again in a
   later phase?
3. Is per-step commit frequency acceptable for `CONTENT_GENERATION`/`NEWS_ANALYSIS` at expected
   production task volume, or does it warrant a batching compromise (e.g., commit every step but
   only `flush()` — deferring the actual `COMMIT` — for the common single-transaction-latency
   case)? This is a product/ops question, not an architectural one, but affects Option A's exact
   implementation shape.
4. Once Option A exists, should Phase 9's own M7 tests be revisited to *assert* live,
   same-pass `step_results` propagation (replacing the current regression-lock that documents the
   *absence* of that behavior) — presumably yes, but that is implementation work for whichever
   phase actually lands Option A, not this discovery phase.

---

PHASE 9.5 DISCOVERY COMPLETE — WAITING FOR DECISION.
