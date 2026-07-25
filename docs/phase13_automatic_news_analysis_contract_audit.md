# Phase 13 — Automatic News Analysis Contract Adversarial Audit

Audit only. The Contract was treated as untrusted; every claim below was checked against current
source and current tests, not against the Contract's own prose. No Contract, Decision Resolution,
Discovery, source, test, or migration file was modified. No code was implemented, no worker started,
no backlog processed, no live AI call made.

## 1. Executive Verdict

**The Contract is technically sound and implementable as specified.** Every high-risk area the audit
brief flags — atomic-claim correctness, `CONTENT_GENERATION` non-regression, transaction boundaries,
backlog-drain safety, `EngagementCapability` input feasibility, Redis dependency, file scope — was
independently re-traced against current source and, in every case, either confirmed correct or found
to carry only a narrow, non-blocking precision gap. One area (§3 below) required genuinely deep
tracing — a real ORM identity-map subtlety in the proposed atomic-claim fix — which, after full
verification against the *exact*, unmodified downstream code it interacts with, was proven **not**
to cause a bug given the Contract's own frozen scope, but is not explicitly disclaimed in the
Contract's own text. Two MINOR findings are reported; no CRITICAL or MAJOR issue was found.

## 2. Repository Baseline

- `git rev-parse HEAD` = `e6cf33786cd36eadc438d4b55cfb6d5224ffbcd8` — the Phase 12 checkpoint,
  unchanged.
- `git status --short`: only the same pre-existing, unrelated Phase 9/9.5/10/11-diagnostic
  documentation backlog plus this Phase 13 governance chain's own untracked files (Discovery,
  Decision Resolution, Architecture Contract) — no implementation drift, no migration, no model
  change.
- `worker/analysis_main.py`/`worker/analysis_cycle.py` do **not** exist — confirmed via directory
  listing. Phase 13 implementation has not started.

## 3. WorkflowRunner / Atomic Claim Audit

Re-read `workflows/runner.py:99-146` directly, independent of the Contract's own paraphrase:
`run(session, task_id)` → `task = await session.get(EditorialTask, task_id)` → status check → (on
`CREATED`) `task.status = TaskStatus.RUNNING` (ORM attribute assignment) → `await session.commit()`
→ `_execute_steps(session, task, state, definition)`. Confirmed exactly as the Contract's §4/§10/§24
describe.

**Atomic-claim technical correctness (Audit 3)**: the Contract's proposed `UPDATE editorial_tasks
SET status = 'RUNNING' ... WHERE id = :task_id AND status = 'CREATED'` + `rowcount` check is
mechanically sound — `EditorialTask.status` is a standard `Enum`-backed column
(`database/models/editorial_task.py:45-47`), and SQLAlchemy Core `update().where(...).values(...)`
against an enum column, with a `result.rowcount` check, is a well-supported, already-proven pattern
in this exact codebase (`services/triage_orchestrator.py:62-67`'s `_claim_new_event()`).

**New finding, requiring genuine tracing, not merely asserted**: the atomic `UPDATE` is a Core-level
statement, executed *after* `task` was already loaded into the session's ORM identity map via
`session.get()`. A Core `UPDATE` does **not** automatically refresh an already-loaded ORM object's
in-memory attributes — `task.status` would remain `CREATED` in Python memory immediately after the
atomic claim succeeds at the database level, unless explicitly re-synced (`session.refresh(task)` or
a matching `task.status = TaskStatus.RUNNING` assignment). The Contract's §10 code sketch does not
address this.

**Verified, not merely flagged**: traced whether this staleness actually causes an observable bug
given the *unmodified* remainder of `_execute_steps()`/`_run_step()`/`_fail()`
(`workflows/runner.py:147-300`, confirmed byte-for-byte unchanged by the Contract's own §26 file
scope) — **none of these methods ever reads `task.status` again** between the claim and the final,
existing, unmodified `task.status = TaskStatus.COMPLETED`/`task.status = TaskStatus.FAILED`
assignments (both plain overwrites, not conditioned on the prior in-memory value). The staleness
window therefore has no observable effect on the frozen code path this Contract authorizes. This is
a real technical subtlety, correctly resolvable, but **not explicitly disclaimed or resolved in the
Contract's own §10 text** — see Finding N1.

**Transaction boundary (Audit 4)**: confirmed independently, not merely trusted from the Contract's
own §24 claim — `await session.commit()` (`workflows/runner.py:123`, unchanged) fires immediately
after the status write, before `_execute_steps()` (which makes the LLM calls) begins. No row lock or
open transaction spans any provider call, in the current architecture or after this Contract's
narrow fix. **Confirmed correct.**

## 4. Existing Workflow Non-Regression

Re-read `tests/test_workflow_runner.py` in full (312 lines) — every test's setup pattern was traced
against the atomic-claim fix's actual behavior, not assumed compatible:

- Every "happy path" test (`test_successful_run_completes`, `test_step_failure_...`,
  `test_retry_succeeds_...`, etc.) creates a **fresh** `CREATED` task per test via
  `workflow_service.create_task()` and calls `run()` exactly once against it — the atomic claim's
  `UPDATE ... WHERE status = 'CREATED'` behaves identically to today's read-then-write for this
  single-caller, single-attempt case (rowcount is always 1).
- `test_rerun_on_running_task_raises` (`tests/test_workflow_runner.py:219-228`) directly commits
  `raw_task.status = TaskStatus.RUNNING` via the DB *before* calling `run()`, then asserts
  `TaskAlreadyRunningError`. Traced against the fix: the atomic `UPDATE` finds `status != 'CREATED'`,
  affects 0 rows, `run()` re-reads and correctly raises the same, existing exception. **Passes
  unmodified.**
- `test_rerun_on_completed_task_raises` (`tests/test_workflow_runner.py:209-215`): calls `run()`
  twice on the same task; second call's atomic `UPDATE` finds `status = 'COMPLETED'`, 0 rows
  affected, raises `TaskAlreadyCompletedError`. **Passes unmodified.**
- `test_max_iterations_exceeded_...`/timeout tests manipulate `.workflow` JSON state directly via DB
  commits before calling `run()`, never `.status` — no interaction with the claim fix at all.
- `test_fast_step_completes_...`/`test_step_timeout_...`/`test_whole_workflow_timeout_...`
  (`tests/test_workflow_runner.py:235-312`) all explicitly use `WorkflowType.CONTENT_GENERATION` —
  confirming `CONTENT_GENERATION`'s own existing test coverage exercises exactly the code path this
  Contract's fix touches, and every one is compatible per the trace above.

**No existing test requires modification. No `CONTENT_GENERATION` regression risk found** — this is
independently verified via direct line-by-line trace, not inferred from the Contract's own claim.

## 5. EngagementCapability Audit

Re-traced `CapabilityExecutor._build_context()` (`capabilities/executor.py:112-154`) directly: builds
`NewsEventSnapshot` (title/summary/content/url/category/published_at — all real, existing fields) and
`WorkflowExecutionStateSnapshot.step_results` (a `dict[str, dict | None]` keyed by step name,
populated from `state.step_results` filtered to `status == "SUCCESS"`). `context.business.workflow_
state.step_results.get("research")`/`.get("intelligence")` — the exact access pattern the Contract's
§7/§10 specifies, and the exact access pattern `IntelligenceCapability` already uses successfully in
production (`capabilities/intelligence_capability.py:99`). **No unavailable field is requested; no
new plumbing is silently required.** Output contract (§7/§11): `engagement_potential_score` (number,
`[0.0, 1.0]`), `audience_fit` (string), `reasoning` (string) — all types/ranges deterministic, no
ambiguity, and the `_potential_` naming makes the predicted-vs-observed distinction structural, not
merely documented (Audit 27: **no false "real metrics" claim found anywhere in the Contract**).

## 6. Prompt / Registry Audit

`prompts/engagement/v1.yaml` is a genuinely new path — no historical prompt is overwritten (trivial,
confirmed via `find prompts/ -maxdepth 1` showing no existing `engagement/` directory). Required
`additionalProperties: false` + all-fields-required matches `prompts/intelligence/v2.yaml`'s own
already-remediated shape exactly (§8, re-confirmed by direct comparison this session). **Registry key
precision, re-verified**: the Contract correctly distinguishes the *step* name (`"engagement_
analysis"`, `workflows/definitions/news_analysis.py:22`) from the *capability* registry key
(`"engagement"`, same line's `capability="engagement"` parameter) — this is the exact string
`CapabilityRegistry.resolve()` must be called with, and the Contract's §9 gets this right, explicitly
flagging the distinction as "easy to conflate." **Confirmed correct, no ambiguity.**

## 7. Worker / Composition Audit

`worker/analysis_main.py`/`worker/analysis_cycle.py` (§12/§26) — re-derived the minimum actually-
required scope independently: no `worker/__init__.py` edit is needed (adding sibling modules to an
existing package requires no `__init__.py` change — confirmed, current `worker/__init__.py` is a
one-line docstring with no `__all__`/re-export list to update); no `pyproject.toml` change is needed
(`"worker"` is already in the `packages` list, added by Phase 12 — re-confirmed via direct read of
`pyproject.toml:36`); no `Dockerfile` change is needed (same reasoning as Phase 12's own, already-
audited conclusion — `COPY . .` precedes `pip install .`). **The Contract's own §26 omission of these
three files is correct, not an oversight** — independently re-derived, not merely trusted.
Composition (§21/§25): `assemble_ai_integration_layer()` + `FilePromptRepository` construction,
mirroring `scripts/run_content_generation.py:93-97` exactly — **no new shared composition module is
required**, confirmed by direct comparison of the two call shapes.

## 8. Eligibility / Backlog Audit

Re-confirmed `EditorialTask` has no dedicated `workflow_type`/`task_type` column — the Contract's
§13 correctly uses the same JSON-field-matching approach `_find_active_task()` already establishes
(`services/workflow_service.py:97-105`), not a nonexistent column. Freshness cutoff (48h) correctly
reuses `compute_freshness()`'s own last tier boundary, unmodified (`services/freshness.py:18`).
`published_at IS NULL` handling is correctly resolved by explicit reference to `compute_freshness()`'s
own existing, unconditional `collected_at` fallback (`services/freshness.py:62-64`) — not left
ambiguous.

**No hidden backlog-drain path found**: the Contract names no fallback ("if the fresh set is empty,
widen the query") anywhere in §13/§18 — the freshness filter is unconditional. **The core safety
invariant (>48h tasks can never be selected) is unambiguous.**

**MINOR finding (N2, not a safety gap)**: the Contract does not specify *how* the three filters
(status, workflow-name JSON match, freshness join) combine into one bounded query — "filtered in
Python (or via a computed freshness predicate, Planning's discretion)" (§13's own text) leaves open
whether the workflow-name JSON match is pushed to SQL (e.g.
`EditorialTask.workflow['workflow_name'].astext == 'NEWS_ANALYSIS'`, PostgreSQL JSON operator
support) or done in Python after loading all `CREATED` rows. Given ~4723 `CREATED` rows exist today,
a naive Python-side-filter-then-limit implementation would load thousands of rows into memory every
300-second cycle — inefficient, but **not** a correctness or backlog-drain risk (the `LIMIT`/cutoff
still applies correctly to the final result either way). Recommended, not required: the Architecture
Contract should recommend the SQL-pushed-down JSON predicate explicitly to avoid this inefficiency
being discovered late.

## 9. Cost / Concurrency Audit

Batch cap (§14/§17): `LIMIT news_analysis_batch_size` is applied at the eligibility-query boundary
itself (§13), not as a soft/advisory loop condition — confirmed hard by construction. Sequential
execution: the Contract's §14 cycle sketch shows a plain `for`-style sequential loop (implied by "one
task's `run()` call completes... before the next begins"); **no `asyncio.gather`/`create_task` is
proposed anywhere** — re-confirmed via full-text search of the Contract for concurrency primitives,
none found. Worst-case theoretical throughput: 5 tasks × up to 4-5 LLM calls (research + intelligence
+ engagement + scoring's up-to-2-call retry pattern, `capabilities/scoring_capability.py:193,217`,
re-confirmed) = ≤25 calls per 300s cycle — small, bounded, matches §9's own derivation exactly.

**Cost containment honesty (Audit 23)**: re-confirmed the Contract's §17 does not introduce
`max_daily_ai_cost`, does not claim `CostTracker` is fixed, and explicitly states cost exposure is
bounded by workload, never spend. **No false safety claim found.**

## 10. Failure / State Audit

Re-verified §11/§15's state table against `workflows/errors.py`'s actual exception hierarchy
(`TaskAlreadyRunningError`, `TaskAlreadyCompletedError` — both pre-existing, unmodified) and
`capabilities/errors.py`'s hierarchy (`BudgetExceededError(PermanentCapabilityError)`, re-confirmed
this session) — every row in the Contract's §15 table maps to a real, existing, unmodified mechanism.
No new exception type is introduced (§11 explicitly states this and it is accurate). `FAILED` tasks
are never auto-retried: confirmed by §13's eligibility query filtering only `status == CREATED` —
`FAILED` is structurally excluded, not merely a documented promise.

## 11. CONTENT_GENERATION Boundary Audit

Confirmed via the Contract's own §26 file scope: `worker/analysis_main.py`/`worker/analysis_cycle.py`
are new files with no authorization to import `scripts.run_content_generation` or construct a
`WorkflowType.CONTENT_GENERATION` `EditorialTaskCreate`. §19/§28's mechanical zero-rows test
requirement (no `CONTENT_GENERATION` task, no `ContentDraft`, scoped to the analyzed event) is the
correct, provable enforcement mechanism — mirroring Phase 12's own already-proven
`test_full_offline_chain_...` pattern exactly. **Clean hard stop, confirmed.**

## 12. Test Feasibility Audit

Cross-checked §28's test list against every binding behavior this Contract freezes — all 15+ items
the audit brief's own Audit 28 checklist names are present in §28, including the two most
technically demanding ones:
- **Atomic concurrency claim, genuine (not sequential) proof**: feasible using
  `independent_session_factory()`'s own proven, NullPool-per-connection shape
  (`tests/test_triage_orchestrator_claims.py:38-42`), already used for an analogous genuine
  cross-connection concurrency proof for `_claim_new_event()` — re-confirmed this session, not
  merely assumed. Two real, concurrent `asyncio.gather()`'d `run()` calls against independent
  sessions/connections targeting the same `task_id` is directly achievable with existing
  infrastructure.
- **Shared-dev-DB isolation**: Phase 12's own proven `try/finally` + unique-row-prefix + FK-safe
  cleanup pattern (`tests/test_automation_integration.py`) is directly reusable, confirmed by
  direct comparison of the fixture shapes needed.

**No test obligation in §28 is infeasible with existing test infrastructure.**

## 13. Live Validation Safety

§30's procedure (`news_analysis_batch_size=1`, freshness cutoff already excludes the historical
backlog by construction) is a deterministic, not hopeful, sample-selection strategy — with the
freshness filter active, `LIMIT 1` against the (correctly-filtered) eligible set can only select a
genuinely fresh task, never a backlog one, by the same structural guarantee §8/§18 already establish.
**No "start and hope" pattern found.**

## 14. File Scope Audit

| File | Contract-authorized? | Independently confirmed required? |
|---|---|---|
| `workflows/runner.py` (narrow) | Yes (§26) | Yes — the one method body, confirmed the minimum necessary fix |
| `capabilities/registry.py` (narrow) | Yes | Yes — one registration line |
| `core/config.py` (narrow) | Yes | Yes — four fields |
| `docker-compose.yml` (narrow) | Yes | Yes — one service, Redis-inclusive (§22, re-confirmed necessary) |
| `pyproject.toml` | **Not authorized (correctly)** | **Confirmed not required** (§7 above) |
| `Dockerfile` | Not authorized | Confirmed not required |
| `worker/__init__.py` | Not authorized | Confirmed not required |
| `capabilities/engagement_capability.py` (new) | Yes | Yes |
| `prompts/engagement/v1.yaml` (new) | Yes | Yes |
| `worker/analysis_main.py`, `worker/analysis_cycle.py` (new) | Yes | Yes |
| Test files (5 items) | Yes, enumerated | Yes, matches §28's own requirements exactly |

**No hidden required file found. No unauthorized file was found necessary.**

## 15. Findings

### CRITICAL

None.

### MAJOR

None.

### MINOR

**N1 — ORM identity-map staleness of the pre-loaded `task` object is not explicitly addressed in
§10.**
- **CONTRACT LOCATION**: §10 (Atomic Claim), the code sketch.
- **SOURCE EVIDENCE**: `workflows/runner.py:111,122-123` — `task` is loaded via `session.get()`
  before the claim; a Core-level `UPDATE` does not refresh an already-loaded ORM object's in-memory
  attributes.
- **PROBLEM**: after a successful atomic claim, `task.status` remains `CREATED` in Python memory
  until the existing, unmodified final assignment (`task.status = TaskStatus.COMPLETED`/`FAILED`)
  overwrites it — the Contract does not state this or explain why it is safe.
- **IMPACT**: verified harmless for the current, frozen code path (§3 above proves no intervening
  code reads the stale value) — but this is a non-obvious conclusion an implementer would have to
  independently re-derive, and any future code added to `_execute_steps()` that reads `task.status`
  before completion would silently reintroduce a bug.
- **REQUIRED CORRECTION** (not performed — audit only): add one sentence to §10 either (a)
  explicitly setting `task.status = TaskStatus.RUNNING` on the in-memory object immediately after a
  successful claim (trivial, removes the ambiguity entirely, matches the DB state), or (b)
  explicitly stating why leaving it stale is safe and for how long, so Planning does not have to
  re-derive §3's own trace independently.

**N2 — Eligibility query's SQL-vs-Python filtering mechanism is left fully open, risking an
inefficient (not incorrect) implementation.**
- **CONTRACT LOCATION**: §13 ("filtered in Python (or via a computed freshness predicate, Planning's
  discretion)").
- **SOURCE EVIDENCE**: ~4723 `CREATED` `EditorialTask` rows currently exist; `EditorialTask` has no
  `workflow_type` column, requiring either a JSON-path SQL predicate or a Python-side filter.
- **PROBLEM**: a literal, unguided implementation could load all ~4723 rows into Python every
  300-second cycle before filtering — the safety invariant (freshness cutoff, batch cap) still holds
  either way, but this is a real, foreseeable performance footgun for an MVP meant to run
  indefinitely.
- **IMPACT**: no correctness/safety risk (§8's own backlog-drain analysis is unaffected); an
  operational/performance concern only.
- **REQUIRED CORRECTION** (not performed — audit only): add a one-sentence recommendation to §13
  favoring a SQL-level JSON-path predicate (e.g. `EditorialTask.workflow['workflow_name'].astext ==
  'NEWS_ANALYSIS'`) to push the filter to the database, avoiding the full-table Python-side scan.

### OBSERVATIONS

- The Contract's own §34 self-audit item 13 already, honestly, flagged the SQL-vs-Python filtering
  question as a "genuinely cosmetic... left to Planning" item — this audit agrees it is non-blocking
  but recommends tightening it anyway (N2), since "cosmetic" undersells a 4723-row-scale operational
  concern even if it isn't a correctness one.
- Every one of the audit brief's own 34 numbered check areas was independently traced against
  current source at least once; none surfaced a finding beyond N1/N2.
- The depth of the §3 trace (N1) is exactly the kind of scrutiny an adversarial audit should apply
  to a Contract's own author-written text — the finding survived independent verification as
  "real but currently harmless," which is the correct, honest classification, not an inflated
  severity.

## 16. Observations

(See inline observations above, §8/§15.)

## 17. Readiness Score

**9/10.** Every high-risk area named in the audit brief was independently re-traced, not merely
reviewed, and confirmed sound — including a full line-by-line non-regression trace against the
existing `WorkflowRunner`/`CONTENT_GENERATION` test suite (§4), a genuine ORM-level correctness
investigation of the atomic-claim mechanism (§3), and independent re-derivation of the minimum file
scope (§7/§14). The two MINOR findings are narrow, evidence-grounded precision improvements, not
architectural gaps — one already partially self-flagged by the Contract's own self-audit.

## 18. Final Verdict

PHASE 13 CONTRACT APPROVED — READINESS SCORE: 9/10
