# Phase 9.5 — Workflow Hardening Implementation Planning

## 1. Planning status / authority

**Status: implementation plan. Not a specification.** This document does not redefine, loosen, or
reinterpret any rule in `docs/phase9_5_workflow_hardening_architecture_contract.md` ("the
Contract"), approved per `docs/phase9_5_workflow_hardening_contract_reaudit.md`'s verdict
(**PHASE 9.5 CONTRACT APPROVED**, 0 CRITICAL, 0 MAJOR findings). Where this plan makes a choice
the Contract left as implementation detail (test file names, exact milestone split), that choice
is derived from an existing repository pattern — Phase 9's own M2/M3 precedent for separating
concurrency-proof work from composition work — never invented from nothing.

**Source-of-truth order**: frozen Phase 5/6/7/8/9 contracts > the Contract (this amendment) >
this plan. This plan implements nothing itself; it stops after planning, per instruction.

**Binding restatement, preserved verbatim throughout this plan, per instruction: Phase 9.5
changes persistence timing, not workflow semantics.** Every milestone below changes only *when*
an already-existing persistence operation happens inside `workflows/runner.py`, never *what* a
workflow run produces, means, or guarantees beyond that timing.

**Revision note**: this plan was revised once, in response to
`docs/phase9_5_workflow_hardening_planning_audit.md`'s one MAJOR finding — the M1/M2 split left
`tests/test_phase9_research_intelligence_integration.py`'s existing regression-lock test broken
between commits, since M1's own code change invalidates its assertions but M1's Definition of
Done/rollback-safety text neither required updating it nor accurately described the consequence —
and two MINOR findings (Contract-coverage list drift once §11 moves milestones; an unstated
`expire_on_commit` requirement for M2's own test-local sessionmaker). The required Phase 9 M7
regression-lock test-assertion update (Contract §11) now happens in M1, in the same commit as the
code change that requires it; M2 no longer touches that file. Milestone count, architecture, the
Contract, scope, and production design are all unchanged.

---

## 2. Current repository baseline (re-verified fresh, not assumed)

Re-read immediately before drafting this plan, confirmed unchanged since the Contract and
Re-Audit (`git diff --stat` against all five clean):

| File | Confirmed state relevant to this plan |
|---|---|
| `workflows/runner.py` | `_execute_steps()` (lines 147-203) reassigns `task.workflow` and commits at exactly one site today (lines 191-195, post-loop success), plus `_fail()` (lines 262-288, unmodified by this plan). `state.completed_steps.append(step.name)` at line 187 is the exact insertion point the Contract (§4) specifies. Zero `session.rollback()` calls exist anywhere in the file. |
| `services/workflow_service.py` | `create_task()`/`get_task()`/`_find_active_task()`/`_to_read_schema()` — none require any change; none assume anything about mid-run commit timing. |
| `capabilities/executor.py` | `CapabilityExecutor._build_context()` (lines 111-147) already re-parses `task.workflow` fresh on every step call — zero code change needed, confirmed by the Contract (§9) and independently re-verified by both audits. |
| `schemas/workflow.py` | `WorkflowExecutionState`/`WorkflowStepResult`/`WorkflowRunResult` shapes are exactly what this plan's new commit point serializes — no field addition, no shape change. |
| `database/models/editorial_task.py` | `EditorialTask.workflow: Mapped[dict | None] = mapped_column(JSON, nullable=True)` (line 44) — no migration, no column change. |
| `database/session.py:14` | `async_session_factory = async_sessionmaker(engine, expire_on_commit=False)` — the production precondition the Contract's §4/§14 rule 9 depends on. Confirmed present. |
| `tests/conftest.py:60-66` | `db_session` fixture: `expire_on_commit=False`, `join_transaction_mode="create_savepoint"` — confirmed by the fixture's own docstring to make inner `commit()` calls SAVEPOINT-only, never actually persisted; **insufficient** for the Contract's §12 item 2 durability proof, exactly as both audits established. |
| `tests/test_triage_orchestrator_claims.py:42` | The exact, already-working two-independent-connection precedent (`async_sessionmaker(engine, expire_on_commit=False)` against a real, `NullPool`-based engine) this plan's M2 durability test must mirror, per Contract §12 item 2. |
| `tests/test_phase9_research_intelligence_integration.py` | Contains the one existing test the Contract (§11, §12 item 8) requires this plan to update: `test_both_capabilities_dispatch_in_order_and_synthetic_task_completes`'s regression-lock assertion ("Research did not run"), which becomes false once M1 ships. |

No other file requires inspection — the Contract's own scope statement ("exactly one file... exactly
one method") is confirmed accurate by this re-read.

---

## 3. Frozen Phase 9.5 boundary (restated for milestone-scoping reference only)

**IN**: the exact per-step persistence invariant (Contract §3-§4); the tests Contract §12 requires
(all 8 items); the one required update to Phase 9 M7's regression-lock test (Contract §11).

**OUT** (no milestone below touches any of these, per the Contract's §13 and this task's own hard
constraints): any redesign of `WorkflowRunner`, `WorkflowDefinition`, `WorkflowStepDefinition`,
`WorkflowExecutionState`, `WorkflowStepResult`, or `WorkflowRunResult`; any database migration or
schema change; any new persistence model, table, or column; any scheduler or production
automation; crash/process-interruption recovery or a "resume engine" of any kind; any change to
the `Capability` Protocol, `CapabilityContext`/`CapabilityResult`/`CapabilityCall` shapes, or any
registered Capability; any change to `LLMGateway` or `PromptRepository`; rollback handling for
untyped exceptions (a distinct, separately-tracked hardening question the Contract explicitly
defers, §7).

---

## 4. Dependency graph

```
M1  Per-step persistence implementation + core behavioral tests +
    Research/Intelligence regression update
      |
      v
M2  Independent-connection durability proof + full-suite regression checkpoint
```

**Why this ordering is dependency-correct**: M2's durability test proves that M1's own commit
point is genuinely visible cross-connection — it cannot be written or meaningfully run before M1's
code exists. The required Phase 9 M7 test update (Contract §11) is bundled into M1 itself, not
M2 — since M1's own code change is what invalidates that test's existing assertion, the update
belongs in the same commit as the change that causes it, leaving no commit at which the
repository's test suite is knowingly broken. M2's full-suite zero-regression sweep is, by
definition, a check against the completed change, not something that can run first. Two
milestones, not more: the Contract's own scope ("exactly one
file, exactly one method") does not justify further splitting, but the Contract's §12 item 2 test
is deliberately isolated into its own milestone for the same reason Phase 9 M2 isolated its
concurrency proofs from M3's composition work — "the highest-scrutiny part... gets its own
milestone specifically so its concurrency proof is not diluted by unrelated... code in the same
review" (`docs/phase9_research_intelligence_planning.md`, M2's own stated rationale, reused here
verbatim in spirit).

---

## 5. Milestone overview table

| # | Title | Depends on | Primary files | Contract sections |
|---|---|---|---|---|
| M1 | Per-step persistence implementation + core behavioral tests + Research/Intelligence regression update | — | `workflows/runner.py`, `tests/test_workflow_runner_per_step_persistence.py`, `tests/test_phase9_research_intelligence_integration.py` | §3, §4, §5, §6, §7, §8, §11, §14 rules 1-9 |
| M2 | Independent-connection durability proof + full-suite regression checkpoint | M1 | `tests/test_workflow_runner_per_step_persistence.py` | §9, §10, §12, §14 rule 10 |

2 milestones total.

---

## 6. Detailed milestones

### M1 — Per-step persistence implementation + core behavioral tests + Research/Intelligence regression update

**1. Goal**: implement the Contract's §3 invariant at its exact §4 commit point inside
`WorkflowRunner._execute_steps()`, and prove the behaviors provable with the repository's already-
established, standard test patterns — no specialized cross-connection infrastructure required for
this milestone.

**2. Contract coverage**: §3 (the invariant itself), §4 (exact commit point, `expire_on_commit`
precondition), §5 (success-path behavior), §6 (failure-path behavior, retry-count preservation),
§7 (commit failure semantics), §8 (`_fail()` interaction), §11 (the required Phase 9 M7
regression-lock test update, moved into this milestone — see Implementation scope), §14
rules 1-9.

**3. Files**:
- Production: `workflows/runner.py` (the single insertion described in Implementation scope
  below — no other line in this file changes).
- Tests: `tests/test_workflow_runner_per_step_persistence.py` (new),
  `tests/test_phase9_research_intelligence_integration.py` (one required assertion update — see
  Implementation scope).
- Docs/config: none.

**4. Implementation scope**: inside `_execute_steps()`, immediately after
`state.completed_steps.append(step.name)` (current line 187) and before the `for` loop's next
iteration, insert exactly:

```python
state.step_results = step_results
task.workflow = state.model_dump(mode="json")
await session.commit()
```

At the same indentation as line 187 (inside the `for` loop, not inside the preceding `if
outcome == "FAILED":` block) — so it executes for a `SUCCESS` outcome and for a `SKIPPED`
optional-step outcome, and is never reached for a required step's failing outcome (which already
exits via the existing, unmodified `return await self._fail(...)` at line 169 before reaching
line 187). No other line in `_execute_steps()`, `_run_step()`, `_fail()`, or `run()` changes. No
new import is required (`state`, `task`, `session` are already in scope in this method).

**Required, same-commit test update (moved from M2 per Planning Audit MAJOR-1)**: this code
change immediately changes same-pass Research→Intelligence behavior — Intelligence's built prompt
will, for the first time, genuinely contain Research's facts within one uninterrupted `run()`
call. `tests/test_phase9_research_intelligence_integration.py::
test_both_capabilities_dispatch_in_order_and_synthetic_task_completes` currently asserts the
*opposite*, pre-amendment behavior as a deliberate regression lock (Contract §11): its own lines
196-200 assert `"did not run" in intelligence_request_text.lower()` and that every canonical fact
is `not in intelligence_request_text`. Both assertions become false the moment this milestone's
code exists. **This milestone MUST update that specific test, in the same commit as the code
change, to assert the corrected, positive propagation instead — the repository MUST NOT pass
through any commit state in which this code change exists but that test's assertions do not match
it.** No other line in that file changes; the companion test
(`test_step_results_mechanism_surfaces_a_result_already_persisted_before_the_run_began`) is
unaffected and requires no change (Contract §11).

**5. Explicitly out of scope**: the independent-connection durability test (Contract §12 item 2 —
M2's job, deliberately isolated per §4 of this plan, since it requires specialized cross-connection
infrastructure this milestone's own tests do not); any change to `capabilities/executor.py`,
`services/workflow_service.py`, `schemas/workflow.py`, or `database/models/editorial_task.py` (the
Contract requires, and this milestone confirms, zero-line diffs for all four); any rollback-on-
untyped-exception handling (Contract §7, explicitly deferred); any change to `_fail()`'s own code
(zero-line diff, Contract §8); any change to `capabilities/research_capability.py` or
`capabilities/intelligence_capability.py` (Contract §11 confirms both require zero code change —
only the one existing test's assertion is updated, not the Capabilities themselves).

**6. Tests required** (integration-tier, real Postgres via the standard `db_session` fixture —
sufficient for every test in this milestone since none requires genuine cross-connection
visibility):
- **Same-pass propagation** (Contract §12 item 1): a two-step synthetic `WorkflowDefinition`
  (mirroring Phase 9 M7's own `_synthetic_research_intelligence_registry()` shape, reusable or
  re-derived locally), run through one `WorkflowRunner.run()` call, proving the second step's
  built `CapabilityContext.business.workflow_state.step_results` genuinely contains the first
  step's result — the direct, positive fix-confirmation this whole amendment exists to produce.
- **Required Phase 9 M7 test update, in the same commit as the code change** (Contract §11, §12
  item 8 — moved into this milestone per Planning Audit MAJOR-1): update
  `tests/test_phase9_research_intelligence_integration.py::
  test_both_capabilities_dispatch_in_order_and_synthetic_task_completes` to assert the corrected,
  positive `step_results` propagation, then run it and confirm it passes with the new expectation
  — not merely applied, verified. Also re-run
  `test_step_results_mechanism_surfaces_a_result_already_persisted_before_the_run_began`
  unmodified and confirm it still passes, directly proving Contract §11's "unaffected either way"
  claim rather than merely trusting it.
- **Subsequent-step failure after a committed success** (Contract §12 item 4): a two-step
  definition where step 1 succeeds and step 2 (required) fails; assert the final persisted state
  and `WorkflowRunResult` correctly show step 1 `SUCCESS` / step 2 `FAILED`, `task.status ==
  FAILED` — proving `_fail()`'s bounded re-persistence of already-durable step 1 data is correct
  (Contract §8).
- **Retry-count durability** (Contract §12 item 5): a step that fails once (retryable) then
  succeeds; assert `task.retry_count` is correctly durable after that step's own per-step commit,
  confirming retry_count's preserved, unmodified increment logic (Contract §6) is unaffected by
  the new commit cadence.
- **One-step-workflow's bounded double-commit is correct** (Contract §12 item 6): a one-step
  definition still reaches `COMPLETED` with correct final state despite the two-commit sequence
  (the N=1 instance of the Contract §10 general N+1-commit pattern) — assert final state
  correctness, not merely that no exception was raised.
- **Commit-failure propagation** (Contract §12 item 3, §7): a monkeypatched `session.commit()`
  that raises on its Nth invocation (targeting the new per-step commit specifically, distinct from
  the run-start commit and any terminal commit) results in that exception propagating uncaught out
  of `run()`, with no silent swallow and no partial-success `WorkflowRunResult` returned. This
  does not require a genuinely independent connection — a single `db_session`-backed session with
  a monkeypatched `commit` method is sufficient and matches the existing monkeypatch-based test
  technique already established in this codebase (e.g. Phase 9 M3's own transaction-discipline
  tests).
- Regression, scoped to this milestone: `tests/test_workflow_runner.py` (Phase 5's own suite —
  full success, required-step failure, optional-step skip, max-iterations, step timeout/retry,
  whole-workflow timeout) **and** `tests/test_phase9_research_intelligence_integration.py` (both
  tests in that file, per the bullet above) re-run and confirmed passing — this milestone's own
  Definition of Done requires both directly-affected suites to be clean before this milestone's
  commit; the *formal, documented* full, repository-wide zero-regression sweep across every other
  Phase 8/9 suite remains M2's job (Contract §12 item 7).

**7. Definition of Done**: all tests in bullet 6 pass against the real dev Postgres database,
**including the updated** `tests/test_phase9_research_intelligence_integration.py::
test_both_capabilities_dispatch_in_order_and_synthetic_task_completes` assertion — this milestone
is not complete, and MUST NOT be committed, while that test still asserts the pre-amendment
behavior; the exact insertion described in Implementation scope is the only change to
`workflows/runner.py` (confirmed by `git diff --stat` showing a small, expected line count); the
diff to `tests/test_phase9_research_intelligence_integration.py` is exactly the one assertion
change described above, confirmed via `git diff` showing a small, expected change and no other
line touched; `python -m scripts.validate_architecture` exits 0 (no existing rule scopes to
`workflows/runner.py` by name, so this confirms no accidental new violation); `tests/
test_workflow_runner.py` passes unmodified. **At no point does this milestone's own commit
checkpoint leave any existing test asserting behavior the code no longer produces** — this is the
specific defect (Planning Audit MAJOR-1) this Definition of Done exists to prevent, not merely
describe.

**8. Verification commands**:
```
pytest tests/test_workflow_runner_per_step_persistence.py -v
pytest tests/test_workflow_runner.py -v
pytest tests/test_phase9_research_intelligence_integration.py -v
pytest --tb=short -q   # whole-repo sanity check; the formal, documented zero-regression
                        # checkpoint (Contract §12 item 7) remains M2's own deliverable
ruff check workflows/runner.py tests/test_workflow_runner_per_step_persistence.py tests/test_phase9_research_intelligence_integration.py
mypy workflows/runner.py tests/test_workflow_runner_per_step_persistence.py
python -m scripts.validate_architecture
git diff --stat workflows/runner.py tests/test_phase9_research_intelligence_integration.py
```

**9. Commit checkpoint**: "Implement Phase 9.5 M1: per-step workflow state persistence and
Research/Intelligence regression update."

**10. Rollback safety**: fully independent and safely revertible in isolation, and — corrected
from the previous revision's inaccurate claim (Planning Audit MAJOR-1) — genuinely
self-consistent at every point, not merely "either way." Because this milestone now updates
`tests/test_phase9_research_intelligence_integration.py`'s regression-lock assertion in the
*same* commit as the code change that invalidates it, there is no commit state in this
milestone's history where the code exists but the test still asserts the old, now-false
behavior. Reverting this milestone's commit (the `workflows/runner.py` insertion together with
the `tests/test_phase9_research_intelligence_integration.py` assertion update) atomically
restores both to their exact pre-Phase-9.5 state — the test correctly reverts to asserting the
pre-amendment behavior at the same moment the code stops producing the amended behavior. Safe to
revert at any point before M2 begins; reverting after M2 exists additionally requires reverting
M2's own independent-connection durability test (see M2's own rollback note), since that test
exercises M1's commit point directly.

---

### M2 — Independent-connection durability proof + full-suite regression checkpoint

**1. Goal**: prove the one behavior M1 deliberately did not prove — that a step's per-step commit
is durable to a genuinely independent database connection while a later step in the same pass is
still executing (Contract §12 item 2, the highest-scrutiny test in this amendment) — and run the
full, repository-wide zero-regression sweep (Contract §12 item 7). The required Phase 9 M7
regression-lock test update (Contract §11) is **not** this milestone's job — it is bundled into
M1 itself, in the same commit as the code change that invalidates it (Planning Audit MAJOR-1).

**2. Contract coverage**: §9 (confirms, does not re-litigate, `CapabilityExecutor`'s zero-diff
status), §10 (confirms, does not re-litigate, the Phase 8 Capability contract's zero-diff status
and the N+1-commit/timeout-unchanged consequences), §12 items 2 and 7, §14 rule 10. (§11 and §12
item 8 — the Phase 9 M7 regression-lock test update — are M1's responsibility, not this
milestone's; see M1 §4/§6.)

**3. Files**:
- Production: none (M1 already made the only production-code change this amendment authorizes).
- Tests: `tests/test_workflow_runner_per_step_persistence.py` (extended with the durability test
  below only — M1 already updated `tests/test_phase9_research_intelligence_integration.py`; this
  milestone does not touch it again).
- Docs/config: none.

**4. Implementation scope**: no production code. One test-only change:
- Add the independent-connection durability test to
  `tests/test_workflow_runner_per_step_persistence.py`, built exactly per the
  `tests/test_triage_orchestrator_claims.py:42` precedent (`async_sessionmaker(engine,
  expire_on_commit=False)` against a real, `NullPool`-based engine mirroring
  `tests.conftest._test_engine` — never the standard `db_session` fixture for this specific test,
  per Contract §12 item 2 and §14 rule 10). This test-local sessionmaker must itself carry
  `expire_on_commit=False`, exactly as the cited precedent already does.

The Phase 9 M7 regression-lock test update (Contract §11) is **not** performed by this
milestone — it was already completed, in the same commit as the code change that required it, by
M1 (see M1 §4). This milestone's own tests only re-run it, unmodified, as part of its full-suite
regression sweep (bullet 6 below).

**5. Explicitly out of scope**: any further change to `workflows/runner.py` (M1 already completed
the entire production-code change this amendment authorizes); any change to
`tests/test_phase9_research_intelligence_integration.py` of any kind (M1 already made the one
required assertion update in the same commit as the code change; this milestone only re-runs that
file, unmodified, as part of its regression sweep — see bullet 4); any change to
`capabilities/research_capability.py` or `capabilities/intelligence_capability.py` (Contract §11
confirms both require zero code change — this milestone verifies, does not alter, that claim);
any change to `tests/test_step_results_mechanism_surfaces_a_result_already_persisted_before_the_run_began`
(Contract §11 confirms it is unaffected either way and requires no change); any new architecture-
validator rule (no new file is introduced under a name any existing rule would need to cover).

**6. Tests required** (integration-tier, real Postgres, genuinely independent connections for the
durability test specifically):
- **Per-step durability via independent connection** (Contract §12 item 2, the primary deliverable
  of this milestone): using the M2/M3-precedent `async_sessionmaker` pattern, one session runs a
  two-step synthetic workflow through `WorkflowRunner.run()`; a **second, fully independent**
  session (separate physical connection) reads `task.workflow` immediately after the first step's
  per-step commit and *before* the second step has been given a chance to run (achieved by
  monkeypatching the second step's executor to perform the independent-connection read as its own
  first action, mirroring Phase 9 M3's own "committed before Triage executes" test technique) —
  asserting the first step's result is durably visible to the second connection at that point.
- **Zero regression, full repository sweep** (Contract §12 item 7): the entire test suite —
  `tests/test_workflow_runner.py`, `tests/test_capability_boot_wiring_e2e.py`,
  `tests/test_phase8_cross_cutting_regression.py`, every Phase 9 M0-M7 suite (including M1's own
  already-updated `tests/test_phase9_research_intelligence_integration.py` and its companion
  test, both re-run here unmodified as part of this sweep, not edited), and both of this
  amendment's own test files — run together, with the same pass count as the pre-Phase-9.5
  baseline plus exactly this amendment's own new tests, zero unexplained failures elsewhere. Any
  pre-existing, already-known baseline gap (none currently known) would be identified by name and
  confirmed pre-existing, never silently "fixed" as a side effect of this milestone.

**7. Definition of Done**: every test in bullet 6 passes; the durability test's independent-
connection technique is confirmed, by direct code review, to never use the standard `db_session`
fixture on either side; `git diff --stat` for this milestone shows changes confined to
`tests/test_workflow_runner_per_step_persistence.py` only — no line of
`tests/test_phase9_research_intelligence_integration.py` changes in this milestone (that update
already happened in M1); full-suite `pytest` shows the pre-Phase-9.5 baseline count plus exactly
this amendment's new tests (M1's and M2's combined); `ruff`/`mypy`/`python -m
scripts.validate_architecture` all clean repo-wide (or, if a pre-existing baseline gap is found,
it is identified by name and confirmed pre-existing, never silently patched inside this
milestone's own commit); a final self-audit against the Contract's §15 acceptance checklist
confirms every item still holds against the **implemented** code, not just the Contract's own
text.

**8. Verification commands**:
```
pytest tests/test_workflow_runner_per_step_persistence.py -v
pytest --tb=short -q
ruff check .
mypy .
python -m scripts.validate_architecture
git diff --stat tests/test_workflow_runner_per_step_persistence.py
git diff tests/test_phase9_research_intelligence_integration.py   # expect no output — confirms
                                                                     # this milestone leaves it
                                                                     # untouched (M1 already
                                                                     # updated and committed it)
```

**9. Commit checkpoint**: "Implement Phase 9.5 M2: independent-connection durability proof and
full regression checkpoint."

**10. Rollback safety**: test-only milestone — no production-file changes, so reverting it in
isolation has zero impact on M1's own correctness, and M1 remains fully self-consistent without
M2 (see M1 §10 — M1 no longer depends on M2 to remain internally consistent, since M1 now bundles
its own required test update). **Asymmetric note, stated explicitly**: reverting M1 *after* M2
exists requires also reverting M2's own new durability test, since that test exercises M1's
per-step commit point directly and would fail (or become meaningless) against reverted code. M2
does not touch `tests/test_phase9_research_intelligence_integration.py` at all (M1 already
handled it), so no additional file needs reverting on that account.

---

## 7. Cross-milestone verification strategy

Every milestone's own §8 (Verification commands) is authoritative for that milestone. Across both:
no test in either milestone requires a migration, a new architecture-validator rule, a scheduler,
or any infrastructure beyond what Phase 9 M2/M3 already established and proved working
(`tests.conftest._test_engine`, the `async_sessionmaker(engine, expire_on_commit=False)` pattern,
monkeypatch-based commit-failure/step-pausing techniques). M2's full-suite sweep is the single
point at which the entire, two-milestone change is confirmed regression-free against the
pre-Phase-9.5 baseline, mirroring the discipline Phase 8 M8 and Phase 9 M7 each used as their own
final cross-cutting checkpoint.

## 8. Rollback strategy

M1 alone: fully, independently revertible at any point — M1 now bundles both the code change and
its required test-assertion update in one commit, so reverting M1 alone restores
`workflows/runner.py` and `tests/test_phase9_research_intelligence_integration.py`'s
regression-lock assertion to their exact pre-Phase-9.5 state together, with no intermediate,
inconsistent commit state ever having existed. M1 + M2: revertible together as one unit; M2's own
durability-test addition to `tests/test_workflow_runner_per_step_persistence.py` is not
independently meaningful without M1's code change in place (see M2 §10's asymmetric note) — a
revert of this amendment, if ever needed, reverts both milestones' commits together, restoring
`workflows/runner.py`, deleting `tests/test_workflow_runner_per_step_persistence.py`, and
restoring `tests/test_phase9_research_intelligence_integration.py`'s regression-lock assertion —
the first two via M2's revert, the third via M1's own revert. No migration exists to revert; no
schema state to reconcile.

---

PHASE 9.5 PLANNING REVISION COMPLETE — READY FOR RE-AUDIT
