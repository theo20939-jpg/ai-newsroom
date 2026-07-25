# Phase 13 — M2 Milestone Report: WorkflowRunner Atomic Claim

## Status: GREEN

## Files changed (within authorized §4 scope, narrow)

`workflows/runner.py` — `run()` method body only (former lines 111-123): replaced the
read-then-write `CREATED→RUNNING` transition with an atomic conditional `UPDATE ... WHERE
status = 'CREATED'`, rowcount check, `session.refresh()` on loss, explicit in-memory sync on win.
Added exactly one new import (`from sqlalchemy import update`). No other method
(`_execute_steps`, `_run_step`, `_fail`) touched — byte-for-byte unchanged, confirmed by diff.

`tests/test_workflow_runner.py` — append only, two new tests added at the end of the file, using
a new module-local `_independent_session_factory()`/`_real_committed_created_task()` helper pair
(mirroring `tests/test_triage_orchestrator_claims.py`'s own already-proven pattern). Zero existing
test line modified.

## Transaction semantics, as implemented

Atomic claim commits *before* any capability/LLM code is reached (the claim's `await session.
commit()` happens immediately after the `UPDATE`, structurally before `WorkflowExecutionState.
model_validate()` or `_execute_steps()`). No row lock/claim transaction is held across a provider
call. The loser's raise (`TaskAlreadyRunningError`/`TaskAlreadyCompletedError`) happens before any
capability code path is reached — proven directly by the new concurrency test's call-count spy,
not merely asserted.

## Real Postgres concurrency proof

`test_atomic_claim_exactly_one_winner_under_real_concurrency` and `test_atomic_claim_loser_never_
marked_failed`: two fully independent `AsyncEngine`/session pairs (real Postgres, `NullPool`), a
real committed `NewsSource`+`NewsEvent`+`EditorialTask(CREATED)`, `asyncio.gather()` racing two
`WorkflowRunner.run()` calls against the same `task_id`. Assertions: exactly one of the two
outcomes is `COMPLETED` and the other is the loser's caught exception; the winner's spy
`StepExecutor` was called exactly once, the loser's exactly zero times (`sorted([winner_calls,
loser_calls]) == [0, 1]`, invariant regardless of which local variable actually won); the final
persisted task status is `COMPLETED`, never `FAILED`. Re-run 5 consecutive times — deterministic,
zero flakiness. DB pollution check after the full suite run: zero leftover `claim-test-*` rows.

## Validation run this milestone

- `pytest tests/test_workflow_runner.py` — **14 passed** (12 original + 2 new, zero existing
  test line modified, zero regression).
- `pytest tests/test_phase10_workflow_integration.py` — **1 passed** (`CONTENT_GENERATION`
  non-regression re-confirmed after the atomic-claim change).
- `ruff check tests/test_workflow_runner.py` — all checks passed.
- `mypy workflows/runner.py` — no issues found (the `# type: ignore[attr-defined]` on
  `claim_result.rowcount` is the only, precedented, targeted ignore — no other line required
  one).
- `python -m scripts.validate_architecture` — 0 violations.

## Typing

`claim_result.rowcount != 1  # type: ignore[attr-defined]` — the sole ignore in this diff,
matching the exact precedent at `services/triage_orchestrator.py:67`. No other line in the diff
required an ignore; no speculative ignore was added.

## Deviations from the Plan

None. The implementation matches §8.1's pseudocode exactly.

M2 complete. Continuing to M3.
