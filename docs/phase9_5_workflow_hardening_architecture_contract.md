# Phase 9.5 — Workflow Hardening Architecture Contract Amendment

**Status: frozen amendment specification, revised once in response to
`docs/phase9_5_workflow_hardening_contract_audit.md`'s findings, pending re-audit.** This document
governs exactly one new invariant added to the Phase 5 Workflow Engine's frozen architecture —
per-step persistence inside `WorkflowRunner._execute_steps()`. It does not implement the invariant
(no production code, test, or migration was modified to produce this document; no commit was
created). It is the binding specification a future implementation phase must build against, and
the document a future audit checks that implementation against.

**Revision note**: this Contract was revised once, in response to
`docs/phase9_5_workflow_hardening_contract_audit.md`'s three MAJOR findings (an unstated
`expire_on_commit=False` precondition; an under-specified, false-pass-risking durability test; an
understated false-recovery-guarantee risk) and four MINOR findings (imprecise "redundant"/
"harmless" wording; ambiguous `retry_count` phrasing; a missing `_fail()`/§7 cross-reference; an
unanalyzed timeout-budget interaction). All corrections were applied within §1, §4, §6, §7, §8,
§10, §12, §13, and §14 below. **No correction changes Phase 9.5's scope, the per-step commit
design, any Capability contract, or workflow semantics** — every change is additive precision:
stating explicit preconditions, tightening test requirements, and correcting imprecise wording.

**Source-of-truth order**: this amendment (once approved) > `docs/phase9_5_workflow_hardening_decision_resolution.md`
(the approved decision this amendment codifies verbatim, not reinterprets) >
`docs/phase9_5_workflow_hardening_discovery.md` (the independent root-cause trace both documents
share) > the frozen Phase 5 Workflow Engine contract, Phase 6 Capability Framework contract, and
Phase 7/8/9 contracts, all of which remain in force, unamended, except where this document
explicitly states otherwise below.

**Scope, stated precisely**: this amendment governs exactly one file — `workflows/runner.py` —
and, within it, exactly one method — `WorkflowRunner._execute_steps()`. Every fact below was
re-verified against the current repository (`workflows/runner.py`, `services/workflow_service.py`,
`capabilities/executor.py`, `schemas/workflow.py`, `database/models/editorial_task.py`) at HEAD
`9d51a1c5304586bfc30f918ba73b860f8b5826d7`, confirmed via `git diff --stat` to show zero drift
against the same five files since Phase 9.5's Discovery and Decision Resolution documents were
produced, not copied from those documents without re-checking.

---

## 1. Exact purpose of Phase 9.5

**Binding statement, restated verbatim as required: Phase 9.5 changes persistence timing, not
workflow semantics.**

Phase 9 M7 discovered, and Phase 9.5's Discovery (`docs/phase9_5_workflow_hardening_discovery.md`)
and Decision Resolution (`docs/phase9_5_workflow_hardening_decision_resolution.md`) documents
independently re-verified by direct code trace, that `WorkflowRunner._execute_steps()` persists
`EditorialTask.workflow` only after its entire step loop concludes — either by finishing every
remaining step successfully, or by a required step failing — never mid-loop. Consequently, within
one uninterrupted `WorkflowRunner.run()` call, a later step cannot observe an earlier step's
already-succeeded result via `CapabilityContext.business.workflow_state.step_results`, even
though that step already succeeded moments earlier in the same pass. This contradicts the
intended operating envelope of the already-frozen Phase 6 `step_results` mechanism
(`docs/phase6_architecture_contract.md`, first exercised for real by Phase 9's
`ResearchCapability`/`IntelligenceCapability` pair) for the specific case of two dependent steps
run consecutively within one pass.

Phase 9.5's sole purpose is to close this one, specific gap by making an already-existing
persistence operation happen more frequently — not to redesign the Workflow Engine, not to solve
crash/process-interruption recovery (a distinct, larger, already-disclosed limitation, Contract
§14.1), and not to change what a workflow run produces or means. Every value any caller observes
from a *completed* `run()` call — `WorkflowRunResult`, final `task.status`, final
`task.workflow` — is unchanged by this amendment. Only the *durability timing* of intermediate,
mid-run progress changes.

**Binding limitation, stated explicitly, not merely implied (corrects Audit MAJOR-3)**: per-step
persistence provides *visibility* of successful progress — a durable, mid-run record of which
steps have already succeeded, and their results — and nothing more. It does **NOT** provide
workflow resume, crash recovery, or automatic continuation of an interrupted run. A `RUNNING`
task whose per-step progress is now durably visible remains exactly as permanently non-resumable
as it was before this amendment: `run()`'s `TaskAlreadyRunningError` guard (§13) still
unconditionally rejects it, and no code path this amendment or the existing codebase provides can
continue it. This document, any implementation of it, and any documentation derived from it MUST
NOT describe, imply, or be built upon as if this newly-visible partial progress means a workflow
can "continue where it left off" — that capability does not exist and is not created by this
amendment.

---

## 2. Existing workflow execution model (frozen, cited, unchanged by this amendment)

Restated for this amendment's own completeness, not reopened:

1. **Task creation** (`services/workflow_service.py:53-71`, unmodified by this amendment):
   `create_task()` writes an initial `WorkflowExecutionState` (`current_step=<first step>`,
   `completed_steps=[]`, `step_results=[]`) as `EditorialTask.workflow`, `status=CREATED`. One
   commit.
2. **`WorkflowRunner.run()`** (`workflows/runner.py:103-145`, unmodified by this amendment):
   guards against re-entering a `RUNNING`/`COMPLETED`/`FAILED` task (lines 114-117); sets
   `status=RUNNING` and commits (lines 122-123); delegates to `_execute_steps()` under a
   whole-workflow timeout.
3. **`_execute_steps()`** (`workflows/runner.py:147-203`, **amended by this document** — see §3):
   loops over `remaining_steps` (steps not already in `completed_steps`), accumulating
   `step_results` in a local, in-memory Python list (line 156), calling `_run_step()` per step
   (line 161). Today, `task.workflow` is reassigned and committed exactly once, after the entire
   loop finishes successfully (lines 189-195).
4. **`_run_step()`** (`workflows/runner.py:205-260`, unmodified by this amendment): attempts one
   step up to `max_attempts`, appending a `WorkflowStepResult` to the (in-memory) `step_results`
   list per attempt; never touches `task.workflow`; calls `self._executor.execute(step)` with
   only the `WorkflowStepDefinition` as its argument (line 227) — the `StepExecutor` Protocol's
   frozen signature (`workflows/runner.py:71`).
5. **`_fail()`** (`workflows/runner.py:262-288`, unmodified by this amendment): the other site
   that reassigns `task.workflow` and commits, on a required step's failure or a whole-workflow
   timeout/max-iterations condition.
6. **`CapabilityExecutor._build_context()`** (`capabilities/executor.py:111-134`, unmodified by
   this amendment): re-parses `task.workflow` fresh on every step, building
   `step_results={r.step_name: r.result for r in state.step_results if r.status == "SUCCESS"
   and r.result is not None}` for the `CapabilityContext` a Capability receives.

**The verified root cause, unchanged from Discovery/Decision Resolution**: `task.workflow` is
reassigned at exactly three sites system-wide — task creation, `_execute_steps()`'s post-loop
success path, and `_fail()` — never mid-loop. `CapabilityExecutor` has no other channel to
`WorkflowRunner`'s in-memory, not-yet-persisted `step_results` (`_run_step()` passes only `step`
into `StepExecutor.execute()`), so a later step in the same pass cannot see an earlier step's
result until that entire pass has already ended.

---

## 3. New per-step persistence invariant (binding, the amendment itself)

**Rule, binding, frozen upon approval of this document**: within `WorkflowRunner._execute_steps()`'s
loop, immediately after a step's outcome allows the loop to continue to the next step (`SUCCESS`,
or `SKIPPED` — an optional step's exhausted failure), `EditorialTask.workflow` MUST be reassigned
to a fresh, complete `WorkflowExecutionState` snapshot reflecting that step's outcome, and that
reassignment MUST be committed, before the loop proceeds to attempt the next step.

This is the **only** new rule this amendment introduces. It does not add a new field to
`WorkflowExecutionState`/`WorkflowStepResult`/`EditorialTask`, does not change the *meaning* of
any existing field, and does not alter the shape of the JSON persisted into `EditorialTask.workflow`
— it changes only the *frequency* at which the already-existing snapshot-and-commit operation
(identical in shape to the operation already performed at `workflows/runner.py:191-195` and
`262-285`) occurs.

---

## 4. Exact commit point

**Binding, precise location**: immediately after `state.completed_steps.append(step.name)`
(current `workflows/runner.py:187`), before the `for step in remaining_steps:` loop's next
iteration begins. Not before `_run_step()` is called for that step (no result yet exists to
persist); not deferred to the loop's end (that is exactly the behavior this amendment corrects).

At that exact point, three statements execute, in order — the same three operations already
used at the post-loop success site and in `_fail()`, performed once per qualifying step instead
of once per run:

```
state.step_results = step_results
task.workflow = state.model_dump(mode="json")
await session.commit()
```

`state.current_step` requires no new handling: it is already assigned `step.name` at the top of
that same iteration (`workflows/runner.py:160`, unmodified) before the step runs, and this
amendment does not change when or how it is next reassigned (at the top of the following
iteration, or to `None` at the very end of a successful pass, line 190). The new commit simply
makes this already-correct, already-existing value observable mid-run rather than only at
run-end — no new meaning is introduced for `current_step`.

`task.status` is **not** touched by this new commit — it remains whatever `run()`'s own earlier
commit set it to (`RUNNING`, per `workflows/runner.py:122-123`, unmodified) for every per-step
commit under this amendment. Only the pre-existing terminal commits (the post-loop success path,
or `_fail()`) may change `task.status` away from `RUNNING`.

**Binding architectural dependency, verified, not assumed (corrects Audit MAJOR-1)**: every claim
in this document that a per-step commit does not disrupt subsequent same-session attribute access
— §5's `task.workflow` read moments later in `CapabilityExecutor._build_context()`; §6's
`task.retry_count += 1` in the very next step's `_run_step()` call — depends on the session
`WorkflowRunner.run()` is invoked with being configured with `expire_on_commit=False`. Verified
directly, both places this amendment's mandated tests (§12) will run against already set it:
`database/session.py:14` (`async_session_factory = async_sessionmaker(engine,
expire_on_commit=False)`) and `tests/conftest.py:65` (the `db_session` fixture's own
`expire_on_commit=False`). Without this setting, SQLAlchemy's own default
(`expire_on_commit=True`) would mark every ORM attribute on `task` expired after each commit, and
a plain, non-`await`ed attribute access on an expired object inside an `AsyncSession` context
raises `sqlalchemy.exc.MissingGreenlet` — a runtime failure with no compile-time signal.

**Binding rule**: changing `expire_on_commit` behavior for any session `WorkflowRunner`/
`CapabilityExecutor` may be invoked with is an **architectural change to this amendment's own
safety precondition**, not a routine session-configuration tweak — it MUST NOT be made without
first re-evaluating this amendment's correctness against the new configuration.

**Verification requirement**: whichever future phase implements this amendment MUST include, as
part of its own Definition of Done, a direct, explicit confirmation — not merely an inherited
assumption — that `expire_on_commit=False` holds for both `database/session.py`'s
`async_session_factory` and `tests/conftest.py`'s `db_session` fixture at implementation time, and
MUST re-run this confirmation if either configuration is ever touched in the future.

---

## 5. Success-path behavior

A step whose `_run_step()` outcome is `"SUCCESS"` reaches `state.completed_steps.append(step.name)`
(line 187) exactly as today, then — under this amendment — immediately triggers the §4 commit
before the loop's next iteration. `task.workflow` becomes durable, mid-run, showing this step
(and every earlier step of the same pass) as complete, with its `result` populated. No other
behavior changes: the step's own retry/attempt logic inside `_run_step()` is unaffected; only
what happens *after* `_run_step()` returns `"SUCCESS"` and control returns to the loop body is
amended.

---

## 6. Failure-path behavior

**Required step, failed (the default; the only case reachable by the real, frozen
`NEWS_ANALYSIS`/`CONTENT_GENERATION` definitions today — neither sets `required=False` on any
step)**: `_execute_steps()` calls `self._fail(...)` (`workflows/runner.py:169-172`, unmodified)
**before** reaching line 187 — this amendment's new commit point is never reached for a required
step's own failing outcome. The failing step is committed exactly once, by the pre-existing,
unmodified `_fail()` call, exactly as today.

**Optional step, failed** (not reachable by any real definition today, but a real, already-
implemented, frozen code path — `workflows/runner.py:173-186`): a `SKIPPED` `WorkflowStepResult`
is appended and the loop *does* fall through to line 187 and this amendment's new commit point —
an optional step's `SKIPPED` outcome is treated identically to `SUCCESS` for persistence
purposes, since both represent "this step is finished and the loop continues," the exact
condition this amendment's invariant (§3) is defined over.

**Individual retry attempts within one step** (`_run_step()`, `workflows/runner.py:220-260`,
unmodified) are **not** separately committed by this amendment — only a step's final outcome,
after all attempts are exhausted or the first success occurs, reaches line 187 and the new commit
point. `task.retry_count`'s increment logic (`workflows/runner.py:222`) is **entirely unmodified**
by this amendment — `retry_count` is preserved exactly as-is, not redesigned, redefined, or given
any new meaning; this amendment changes nothing about what it counts or how it is incremented.
Only its *durability timing* changes: all of a given step's own retry increments, accumulated in
memory across that step's own attempts, become durable together — at that **same** step's own
final-outcome commit, not per individual attempt, and not deferred to a later step's commit or
the run's terminal commit. This is an incidental durability-granularity improvement over today
(previously durable only at the run's single terminal commit), not a new mechanism this amendment
introduces on purpose.

---

## 7. Commit failure semantics

**Binding**: this amendment introduces **no new exception handling** around the new commit. If
the new `await session.commit()` call itself raises (a genuine database-level failure), that
exception **MUST** propagate uncaught, exactly as every other untyped exception already does in
`workflows/runner.py` today (confirmed: zero `await session.rollback()` calls exist anywhere in
this file, and this amendment adds none) — out through `_execute_steps()`, out through `run()`'s
`asyncio.wait_for` wrapper (which catches only `TimeoutError`), to `run()`'s original caller.

This is not a new risk category: a commit could already fail at the run's single terminal commit
today; this amendment only means a commit can now fail at up to N points for an N-step workflow
instead of only at the very end. The Capability's own side effect (its Gateway call) already
happened by this point and cannot be undone by this amendment or by today's code — unchanged in
kind from the existing, single-terminal-commit risk profile. Adding defensive
rollback-on-untyped-exception handling is explicitly **out of scope** for this amendment (a
distinct hardening question, recorded but not resolved by Phase 9.5's Discovery, §8 item 1) —
this amendment's diff is limited to exactly the new commit point described in §3-§4, nothing more.

**Cross-reference, explicit (corrects Audit MINOR-3)**: this section governs the *new per-step
commit itself* failing. See §8 for the distinct case of a **typed** failure in a later step,
after one or more earlier per-step commits already succeeded — that case routes through the
existing, unmodified `_fail()`. An **untyped** exception in a later step, as described in this
section, bypasses `_fail()` entirely and propagates uncaught exactly as described above,
regardless of how many per-step commits already occurred earlier in the same pass — §8 does not
cover this case, only the typed-failure one.

---

## 8. Interaction with `_fail()`

**`_fail()` (`workflows/runner.py:262-288`) is unmodified by this amendment — zero-line diff.**
It already receives the accumulated `step_results` list by reference and independently
re-serializes and commits the **full** `WorkflowExecutionState` on failure — including any
earlier steps of the same pass that already received their own per-step commit under this
amendment. This is a **bounded, self-consistent re-persistence**, precisely characterized: every
commit under this amendment (per-step or `_fail()`'s own) writes a complete, independently-valid
snapshot — never a partial or delta update — so re-writing already-durable step data changes
nothing about its correctness; it is written again, in full, as part of the terminal record, not
merged, incremented, or reconciled against what was already committed. There is no ordering
hazard and no merge logic required: `_fail()` is simply the terminal commit, correct and
self-consistent regardless of how many per-step commits preceded it in the same pass. See §7 for
the distinct case of an untyped exception in a later step, which bypasses `_fail()` entirely
regardless of how many earlier per-step commits already occurred.

---

## 9. Interaction with `CapabilityExecutor`

**`capabilities/executor.py` requires zero code change under this amendment.** `CapabilityExecutor`
already re-parses `task.workflow` fresh on every `execute()` call (`_build_context()`,
`capabilities/executor.py:114`) — this amendment changes only how current that data is by the
time a later step reads it. No change to `CapabilityExecutor`'s constructor, its `execute()`
method's control flow, its error translation (`RetryableCapabilityError` →
`StepExecutionError`, etc., lines 96-101), or its `_build_context()` snapshot-building logic
(lines 111-147) is required or authorized by this amendment.

---

## 10. Interaction with the Phase 8 Capability contract

**No Phase 8 Capability contract rule is amended, reopened, or requires re-verification.** The
`Capability` Protocol, `CapabilityContext`/`CapabilityResult`/`CapabilityCall` shapes, the
centralized `call_generate()` Gateway-call mechanism, `PromptRepository.resolve()`, and every
existing registered Capability (`ScoringCapability`, `QualityCapability`, and Phase 9's
`ResearchCapability`/`IntelligenceCapability`) are untouched. Their existing tests
(`tests/test_scoring_capability.py`, `tests/test_quality_capability.py`,
`tests/test_capability_boot_wiring_e2e.py`, `tests/test_phase8_cross_cutting_regression.py`),
which exercise **single-step** synthetic workflows exclusively, are affected only incidentally.

**Precise, bounded persistence consequence, stated generally, not only for the one-step case
(corrects Audit MINOR-1)**: every successful N-step run under this amendment produces N per-step
commits plus the one, pre-existing terminal (post-loop) commit — **N+1 total commits, not N**.
The terminal commit is **not identical** to the last step's own per-step commit: it additionally
sets `task.status = TaskStatus.COMPLETED`, `state.current_step = None`, and
`state.iteration_count += 1`, none of which any per-step commit ever writes. Only
`step_results`/`completed_steps` are genuinely duplicated between a step's own per-step commit
and the terminal commit that immediately follows it when that step is the pass's last. A
one-step workflow (Decision Resolution §8) is simply the N=1 instance of this same general
pattern (2 total commits) — not a case unique to one-step definitions. This is a bounded,
deterministic, known persistence overhead, not an unbounded or unpredictable one, and not a
behavior change any existing assertion depends on.

**Timeout behavior is unchanged (corrects Audit MINOR-4)**:
`WorkflowStepDefinition.timeout_seconds`'s per-step enforcement (`_run_step()`'s own
`asyncio.wait_for(..., timeout=step.timeout_seconds)`, `workflows/runner.py:227`) and
`WorkflowDefinition.timeout_seconds`'s whole-workflow enforcement (`run()`'s outer
`asyncio.wait_for`, `workflows/runner.py:134-136`) are both unmodified by this amendment — neither
boundary's enforcement mechanism changes. The new per-step commit executes after a step's own
`wait_for` block has already closed, so it is never charged against that step's own
`timeout_seconds`; it does execute inside the outer, whole-workflow `wait_for`, adding a bounded,
small amount of additional latency (a handful of extra DB round-trips) to the existing overall
budget — the enforcement mechanism itself is untouched, only its already-existing budget is spent
marginally faster. This satisfies Phase 8's contract requirement
(`docs/phase8_capability_contract.md:94`) that a Capability complete within the timeout
`WorkflowRunner` already enforces, since that enforcement is unchanged.

---

## 11. Interaction with the Phase 9 Research/Intelligence flow

This is the motivating case this amendment exists to address. Under this amendment, a synthetic
two-step `research → intelligence` `WorkflowDefinition`, run through one `WorkflowRunner.run()`
call, results in Intelligence's step observing Research's `step_results["research"]` for the
first time — closing exactly the gap Phase 9 M7 discovered and Phase 9.5's Discovery/Decision
Resolution documents independently confirmed by code trace.

**`capabilities/research_capability.py` and `capabilities/intelligence_capability.py` require
zero code change.** Neither was ever the source of the gap; both already read/write through the
correct, existing mechanism (`docs/phase9_research_intelligence_architecture_contract.md` §8,
§9, §9.1, unamended).

**Required consequence for existing Phase 9 tests, named explicitly and binding on whichever
phase implements this amendment**: Phase 9 M7's
`tests/test_phase9_research_intelligence_integration.py::test_both_capabilities_dispatch_in_order_and_synthetic_task_completes`
currently asserts, as a deliberate regression lock, that Intelligence's built prompt states
"Research did not run" — true only because this amendment is not yet implemented. **Whichever
future phase implements this amendment MUST update that specific assertion** to assert the
corrected, positive propagation instead, as part of that phase's own implementation and test
work — this amendment document does not perform that update itself.
`test_step_results_mechanism_surfaces_a_result_already_persisted_before_the_run_began` (the
companion test proving the mechanism's read-side wiring given pre-seeded state) is unaffected
either way and requires no change.

---

## 12. Testing requirements

Binding minimums for whichever future phase implements this amendment (none written by this
document):

1. **Same-pass propagation (positive fix-confirmation)**: a two-step synthetic workflow run
   through one `WorkflowRunner.run()` call, proving the second step's `CapabilityContext.
   business.workflow_state.step_results` genuinely contains the first step's result.
2. **Per-step durability (corrects Audit MAJOR-2, binding on implementation)**: a step's
   committed result MUST be observable, mid-run, by a second session on a **genuinely independent
   database connection** while a later step in the same pass is still executing. This test MUST
   NOT use the standard `db_session` fixture (`tests/conftest.py:60-66`) on both sides — its
   `join_transaction_mode="create_savepoint"` binds it to one shared, uncommitted outer
   transaction on one physical connection, and a savepoint-level write is trivially visible to
   another session sharing that same connection/transaction regardless of genuine cross-connection
   durability, which would make this test pass without proving anything. Savepoint-based fixtures
   are insufficient for this proof. This test MUST use the same two-independent-connection test
   helper pattern already established in `tests/test_triage_orchestrator_claims.py`/
   `tests/test_triage_orchestrator_cycle.py` (Phase 9 M2/M3), built against the real test engine
   (`tests.conftest._test_engine`), not the single-connection `db_session` fixture.
3. **Commit-failure propagation** (§7): a commit failure at the new per-step commit point
   propagates uncaught out of `run()`, with no silent swallow and no partial-success
   `WorkflowRunResult` returned.
4. **Subsequent-step failure after a committed success** (§8): the final persisted state and
   `WorkflowRunResult` correctly reflect an earlier step's `SUCCESS` and a later step's `FAILED`,
   with `task.status == FAILED` — a direct, executed proof that `_fail()`'s bounded re-persistence
   of already-durable step data is correct.
5. **Retry-count durability** under the new per-step commit cadence (§6).
6. **One-step-workflow's bounded double-commit is correct** (§10): a one-step definition still
   reaches `COMPLETED` with correct final state despite the two-commit sequence (the N=1 instance
   of the general N+1-commit pattern).
7. **Zero regression**: the full, unmodified-in-intent `tests/test_workflow_runner.py` suite
   (full success, required-step failure, optional-step skip, max-iterations, step timeout/retry,
   whole-workflow timeout), plus `tests/test_capability_boot_wiring_e2e.py`,
   `tests/test_phase8_cross_cutting_regression.py`, and every Phase 9 M0–M7 test suite, continue
   to pass.
8. **Required Phase 9 M7 test update** (§11): the specific regression-lock assertion named above
   must be updated to assert the corrected behavior — a mandatory part of implementing this
   amendment, not optional follow-up.

---

## 13. Forbidden / non-goals (hard constraints, binding)

This amendment, and any implementation of it, MUST NOT:

- Redesign `WorkflowRunner`, `WorkflowDefinition`, `WorkflowStepDefinition`,
  `WorkflowExecutionState`, `WorkflowStepResult`, or `WorkflowRunResult`.
- Introduce a database schema change or a migration. `EditorialTask.workflow`'s column type
  (`Mapped[dict | None] = mapped_column(JSON, nullable=True)`, `database/models/editorial_task.py:44`)
  is unchanged.
- Introduce a new persistence model, table, or column.
- Add a scheduler, cron, or any production automation for `WorkflowRunner`.
- Solve crash/process-interruption recovery, add a "resume" verb, or change `run()`'s
  `TaskAlreadyRunningError`/`TaskAlreadyCompletedError` guard semantics
  (`workflows/runner.py:114-117`). Per-step persistence provides *visibility* of successful
  progress only — it MUST NOT be described, implied, or relied upon as workflow resume, crash
  recovery, or automatic continuation of an interrupted run (see §1's explicit limitation).
- Introduce a distributed transaction, two-phase commit, or cross-session coordination
  mechanism. Every commit under this amendment remains a plain, single-session operation on the
  one `AsyncSession` `WorkflowRunner.run()` already owns for the whole call.
- Change the `Capability` Protocol, `CapabilityContext`/`CapabilityResult`/`CapabilityCall`
  shapes, or any registered Capability's contract.
- Change `LLMGateway`, `PromptRepository`, or any Phase 7 AI Integration Layer component.
- Add rollback handling for untyped exceptions (§7) — a distinct, separately-tracked hardening
  question, not part of this amendment's scope.

---

## 14. Canonical rules

1. **Phase 9.5 changes persistence timing, not workflow semantics.**
2. `EditorialTask.workflow` MUST be reassigned and committed once per step whose outcome allows
   `_execute_steps()`'s loop to continue (`SUCCESS`, or `SKIPPED`), immediately after
   `state.completed_steps.append(step.name)`, before the next step is attempted.
3. A required step's failure MUST continue to route through the existing, unmodified `_fail()`
   path, never through the new per-step commit point.
4. No new field, table, column, or migration is introduced. The JSON shape persisted into
   `EditorialTask.workflow` is unchanged.
5. `CapabilityExecutor`, the `StepExecutor` Protocol, and every Phase 8/9 Capability require zero
   code change to remain compliant with this amendment.
6. No rollback logic is added; a commit failure at the new commit point propagates uncaught,
   identically to every other untyped exception in `workflows/runner.py` today.
7. `_fail()` remains unmodified; its full re-persistence of already-committed step data is a
   bounded, deterministic, self-consistent overwrite, not an increment — never a correctness risk.
8. This amendment does not authorize, imply, or provide crash/process-interruption recovery,
   workflow resume, or automatic continuation — it provides visibility of successful progress
   only.
9. This amendment's safety depends on `expire_on_commit=False` remaining set on any session
   `WorkflowRunner`/`CapabilityExecutor` is invoked with (`database/session.py:14`,
   `tests/conftest.py:65`); changing that setting is an architectural change requiring
   re-evaluation of this amendment, not a routine tweak.
10. Any test proving mid-run persistence durability MUST use genuinely independent database
    connections; the single-connection, savepoint-based `db_session` fixture is insufficient for
    that specific proof.

---

## 15. Acceptance checklist (self-audited before this revision is submitted for re-audit)

1. Purpose stated exactly as required — confirmed (§1, verbatim "Phase 9.5 changes persistence
   timing, not workflow semantics").
2. Existing execution model cited with exact line numbers, re-verified against HEAD
   `9d51a1c` with zero drift — confirmed (§2, preamble).
3. Every one of the twelve required contract sections is present — confirmed (§1-§12 map 1:1 to
   the twelve requested items).
4. Every hard constraint is restated as a binding prohibition, not merely implied — confirmed
   (§13).
5. No schema, migration, Protocol, Capability-contract, Gateway, or PromptRepository change is
   authorized anywhere in this document — confirmed by re-reading §3-§13.
6. `_fail()` and `CapabilityExecutor` are explicitly confirmed zero-diff, not merely assumed —
   confirmed (§8, §9).
7. The one required, binding Phase 9 test-update consequence is named explicitly, not left
   implicit — confirmed (§11, §12 item 8).
8. No production code, test, or migration was modified to produce this document; no commit was
   created — confirmed (`git status --short` / `git rev-parse HEAD` unchanged throughout Phase
   9.5's Discovery, Decision Resolution, this Contract, and this revision).
9. **MAJOR-1 corrected**: the `expire_on_commit=False` precondition is now stated explicitly,
   cited against both `database/session.py:14` and `tests/conftest.py:65`, bound by an
   architectural-change rule, and given a verification requirement — confirmed (§4, §14 rule 9).
10. **MAJOR-2 corrected**: §12 item 2 now mandates genuinely independent database connections,
    explicitly forbids the savepoint-based `db_session` fixture for this proof, and names the
    required Phase 9 M2/M3 test-helper precedent — confirmed (§12, §14 rule 10).
11. **MAJOR-3 corrected**: an explicit, binding limitation stating per-step persistence provides
    visibility only — not resume, crash recovery, or automatic continuation — is present in both
    §1 and §13 — confirmed.
12. **All four MINOR findings corrected**: "harmless"/"redundant"/"identical" wording replaced
    with precise, bounded-persistence language and generalized beyond the one-step case (§8, §10);
    `retry_count` explicitly stated as preserved, not redesigned (§6); §7/§8 explicitly
    cross-reference each other's scope (§7, §8); timeout enforcement explicitly stated as
    unchanged (§10) — confirmed.
13. No correction altered Phase 9.5's scope, the per-step commit design (§3, §4 unchanged in
    substance), any Capability contract, or workflow semantics — confirmed by re-reading every
    edited section against the original commit-point/invariant definition in §3-§4, which is
    untouched.

---

PHASE 9.5 CONTRACT REVISION COMPLETE — READY FOR RE-AUDIT
