# Phase 9.5 — Workflow Hardening Contract Adversarial Audit

**Status: audit only. `docs/phase9_5_workflow_hardening_architecture_contract.md`, all production
code, and all tests were left unmodified. No implementation was created. No commit was made.**

The Contract was treated as untrusted throughout. Every cited line number, every claim about
`capabilities/executor.py`/`schemas/workflow.py`/`schemas/capability.py`/`database/models/editorial_task.py`
being "zero-diff," and every claim about session/transaction behavior was independently
re-derived from the current repository, not accepted from the Contract's own text. `git rev-parse
HEAD` = `9d51a1c5304586bfc30f918ba73b860f8b5826d7`, `git status --short` shows no drift beyond the
pre-existing, untracked `docs/phase9_5_*.md`/`docs/phase9_*.md` audit-trail files this session's
own prior turns produced.

**One material discovery this audit made that no prior Phase 9.5 document checked**: the
Contract's entire safety argument for reading `task.workflow`/`task.retry_count` immediately
after a new per-step `commit()` — within the same session, on the very next line of code —
implicitly depends on the async session factory being configured with `expire_on_commit=False`.
Under SQLAlchemy's actual default (`expire_on_commit=True`), every ORM attribute on `task` would
be marked expired after each commit, and a plain (non-`await`ed) attribute access on an expired
object inside an `AsyncSession` context raises `sqlalchemy.exc.MissingGreenlet` — a well-known
async-SQLAlchemy hazard. This was verified directly:

```
database/session.py:14:  async_session_factory = async_sessionmaker(engine, expire_on_commit=False)
tests/conftest.py:65:    bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
```

Both the production session factory and the test `db_session` fixture already set
`expire_on_commit=False`, so **the Contract's mechanism is sound as specified** — nothing is
currently broken. But the Contract never states, cites, or verifies this precondition anywhere,
despite the entire amendment's safety resting on it. See MAJOR-1.

---

## 1. Summary

The Contract correctly identifies the exact commit insertion point, correctly scopes the
SUCCESS/SKIPPED boundary, correctly confirms `CapabilityExecutor`/`_fail()`/the Phase 8 Capability
contract require zero code change, and its core technical claim — that per-step persistence
closes the Research→Intelligence same-pass gap — was independently re-traced and confirmed true,
conditioned on the now-verified `expire_on_commit=False` setting. No CRITICAL defect was found:
the mechanism as specified is safe, minimal, and does what it claims.

However, three MAJOR gaps were found, each mapping directly to an explicitly-requested audit
dimension (ORM session/`expire_on_commit` assumptions; testing completeness; false recovery
guarantees), plus several MINOR wording/completeness issues. None invalidate the Contract's
technical approach, but each represents a real risk to correctness-in-practice if a future
implementer works from this document alone without the gaps closed. **Verdict: corrections
required before this Contract is truly ready to freeze.**

---

## 2. Findings by severity

### CRITICAL

None found.

### MAJOR

**MAJOR-1 — Unstated, load-bearing `expire_on_commit=False` precondition.**
The Contract's §4/§5/§9 claims (that a per-step commit does not disrupt subsequent same-session
reads/writes — e.g. `task.retry_count += 1` in the very next step's `_run_step()` call, or
`CapabilityExecutor._build_context()`'s `task.workflow` read moments later) are correct **only**
because `database/session.py:14` and `tests/conftest.py:65` both set `expire_on_commit=False`.
Verified independently, both hold true today. If this setting were ever changed — e.g. "cleaned
up" to SQLAlchemy's own default (`expire_on_commit=True`) by someone unaware Phase 9.5's
mechanism depends on it — every per-step commit would immediately break the very next same-session
attribute access with `sqlalchemy.exc.MissingGreenlet`, a runtime error with no compile-time
signal, in both `WorkflowRunner` itself (`task.retry_count`) and `CapabilityExecutor`
(`task.workflow`). This is exactly the "ORM session problems / expire_on_commit assumptions" risk
category this audit was explicitly asked to check for, and no Phase 9.5 document (Discovery,
Decision Resolution, or this Contract) mentions it.

**MAJOR-2 — §12 test #2's methodology is under-specified and risks a false pass.**
§12 item 2 ("Per-step durability... a second, independent database session (separate
connection)...") is directionally correct in wording but does not name the required
implementation technique. The standard `db_session` fixture (`tests/conftest.py:60-66`) uses
`join_transaction_mode="create_savepoint"` — a SAVEPOINT nested inside one shared, uncommitted
outer transaction on **one physical connection**, rolled back entirely at test teardown. This is
precisely the limitation Phase 9's own M2/M3 planning already identified and solved with a
dedicated two-independent-connection test helper (`tests/test_triage_orchestrator_claims.py`/
`tests/test_triage_orchestrator_cycle.py`), because savepoint-level writes on one shared
connection ARE trivially visible to another session sharing that same connection/transaction —
proving nothing about genuine cross-connection durability. If a future implementer reaches for
two `db_session`-fixture-derived sessions (the natural, easiest default), this test would give a
**false pass**: it would appear to prove mid-run durability while actually only proving
same-transaction visibility, which was never in question. This directly matches the audit's
"testing completeness... actually proving the contract" dimension.

**MAJOR-3 — Understated "false recovery guarantee" risk.**
§1 and §13 correctly state crash recovery is out of scope and unsolved, and correctly forbid
changing `run()`'s `TaskAlreadyRunningError` guard. But per-step persistence creates a **new**,
previously-impossible observable state: a `RUNNING` task with genuinely durable, partial
`step_results`/`completed_steps` that *looks* like resumable progress but is not resumable through
any code path this amendment or the existing codebase provides. The Contract states the
non-goal but never explicitly warns that this new, more-informative RUNNING state **must not be
interpreted or built upon as if resumable** — a real, concrete instance of the audit's own named
"false recovery guarantees" risk category. A future engineer or operator seeing this durable
partial progress for the first time could reasonably infer resumability now exists and build
tooling on that false premise.

### MINOR

**MINOR-1 — §10's "two commits of identical, redundant data" both overstates and under-generalizes.**
The per-step commit and the terminal (post-loop) commit are not identical: the terminal commit
additionally sets `task.status = COMPLETED`, `state.current_step = None`, and
`state.iteration_count += 1` — none of which any per-step commit ever writes. Only
`step_results`/`completed_steps` are genuinely duplicated across the two. Separately, §10 frames
this "extra commit" as specific to one-step workflows, when in fact **every** successful N-step
run gets exactly one such additional, partially-redundant terminal commit beyond its N per-step
commits (N+1 total, not N) — the one-step case is simply the N=1 instance of a general pattern
the Contract never states generally.

**MINOR-2 — §6's "one step later than they occur" phrasing is ambiguous.**
Could be misread as "step N's `retry_count` increments become durable at step N+1's commit"
(incorrect). The intended, and actually correct, meaning — confirmed by code trace — is "durable
together with that same step N's own final-outcome commit, after step N's own retries complete,
not per individual attempt." The phrase should be reworded to remove the "one step later"
framing entirely.

**MINOR-3 — §8's scope vs. §7's is not cross-referenced.**
§8 ("Interaction with `_fail()`") only discusses the case where `_fail()` is eventually called (a
typed, required-step failure). It does not note that a **later** step raising an *untyped*
exception bypasses `_fail()` entirely and propagates uncaught (per §7) — leaving the task
`RUNNING`, with whatever per-step commits already happened as the last durable state. This is not
a new defect (identical to pre-existing, pre-Phase-9.5 behavior for an untyped exception at any
step), but §8's title could mislead a reader into thinking it covers every post-per-step-commit
failure mode, when the untyped-exception subset is really governed by §7 with no cross-reference
between the two.

**MINOR-4 — Per-step commit latency vs. `WorkflowDefinition.timeout_seconds` is never analyzed.**
Each new commit executes after `_run_step()`'s own per-step `wait_for(..., timeout=
step.timeout_seconds)` block has already closed, so it is not charged against a step's own
timeout — but it **is** charged against the outer, whole-workflow `asyncio.wait_for(...,
timeout=definition.timeout_seconds)` (`workflows/runner.py:134-136`), since the commit runs
inside `_execute_steps()`. At realistic scale (a handful of extra DB round-trips against a
60–120s budget) this is very likely negligible, but the Contract's own §6-inherited risk list
("worth measuring") never connects that measurement need specifically to timeout-budget
consumption, and Phase 8's contract rule (`docs/phase8_capability_contract.md:94`, "a Capability
MUST complete within the timeout WorkflowRunner already enforces") makes this the one place a
Phase 8 compatibility claim is not fully substantiated by analysis, only by informal expectation.

### OBSERVATION

**OBSERVATION-1** — The pre-existing, unrelated TOCTOU race in `run()`'s own RUNNING-transition
check-then-commit (`workflows/runner.py:114-123` — not an atomic conditional `UPDATE`, unlike
Phase 9's own `NewsEvent` claim mechanism) is untouched and not worsened by this amendment.
Correctly out of scope; noted only for completeness, since the audit asked about concurrency.

**OBSERVATION-2** — `step_results`, now committed more frequently, can contain multiple
`WorkflowStepResult` entries for the same `step_name` if that step itself retried (one `FAILED`
per failed attempt, one final outcome). `CapabilityExecutor`'s dict-comprehension read
(`capabilities/executor.py:129-133`, filtering to `status == "SUCCESS"`) correctly collapses this
to at most one entry per step name — verified, no ambiguity introduced for a later step's read.

**OBSERVATION-3** — §9's "zero-line diff for `capabilities/executor.py`" and §10's "zero Phase 8
contract change" claims were independently re-verified against fresh reads of
`capabilities/executor.py` and `schemas/capability.py` and hold up exactly as stated.

---

## 3. Contract sections affected

| Finding | Section(s) |
|---|---|
| MAJOR-1 | §4, §5, §7, §9 (implicit precondition), §14 (should become a canonical rule) |
| MAJOR-2 | §12 item 2 |
| MAJOR-3 | §1, §13 |
| MINOR-1 | §10 |
| MINOR-2 | §6 |
| MINOR-3 | §7, §8 |
| MINOR-4 | §6, §10 (Phase 8 compatibility claim) |
| OBSERVATION-1/2/3 | §7 (implicit), §9, §10 (confirmatory, no change needed) |

---

## 4. Required corrections

1. Add an explicit precondition statement (new short subsection, or an addition to §4) citing
   `database/session.py:14` and `tests/conftest.py:65` by name, stating that this amendment's
   safety depends on `expire_on_commit=False` remaining set on any session `WorkflowRunner.run()`
   is invoked with, and add this as a new canonical rule in §14.
2. Rewrite §12 item 2 to explicitly require the same two-independent-connection test helper
   pattern already established in `tests/test_triage_orchestrator_claims.py`/
   `tests/test_triage_orchestrator_cycle.py` (Phase 9 M2/M3), by name, and explicitly state that
   the standard `db_session` fixture is **not** sufficient for this specific test, citing its
   `join_transaction_mode="create_savepoint"` behavior as the reason.
3. Add an explicit warning (near §1 or §13) that per-step-persisted partial progress on an
   interrupted `RUNNING` task remains permanently non-resumable through any existing or
   Phase-9.5-provided code path, and MUST NOT be interpreted, documented, or built upon as
   partial-progress-that-can-continue.
4. Correct §10's "identical, redundant data" phrasing to note the terminal commit's genuinely new
   fields (`status`, `current_step`, `iteration_count`), and generalize the "extra commit"
   consequence to the N-step case (N+1 total commits for any successful N-step run), not only
   the one-step example.
5. Reword §6's "one step later than they occur" to state plainly that a step's own retry
   increments become durable together with that same step's own final-outcome commit.
6. Add one cross-referencing sentence to §8 (or §7) noting that an untyped exception in a later
   step bypasses `_fail()` entirely, per §7, regardless of how many earlier per-step commits
   already occurred.
7. (Optional, minor) Add one sentence acknowledging the per-step-commit-latency-vs-whole-workflow-
   timeout interaction explicitly, even if only to state it is expected to be negligible at
   realistic scale.

---

## 5. Final verdict

PHASE 9.5 CONTRACT NOT READY — CORRECTIONS REQUIRED
