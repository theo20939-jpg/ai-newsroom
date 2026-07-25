# Phase 13 — Automatic News Analysis Implementation Plan Adversarial Audit

Audit only. The Plan was treated as untrusted; every SQL/syntax claim was independently *executed*
(read-only, against real source and, where safe, the real database) rather than merely reviewed as
prose. No Plan, Contract, source, test, or migration file was modified. No code was implemented, no
worker started, no backlog processed, no live AI call made.

## 1. Executive Verdict

**The Plan is NOT ready.** Three MAJOR findings were confirmed empirically, not merely theorized:
(1) the eligibility query's core JSON-filtering syntax, as literally specified in the Plan — both
the primary syntax and the Plan's own named fallback — does not correctly implement the eligibility
filter (one fails to compile, the other compiles but silently matches **zero** rows against real
data); (2) the M7 live-validation isolation strategy is proven false against the real, current
database state (1153 fresh-eligible `NEWS_ANALYSIS` tasks exist right now, not "at most one"); (3)
the Plan's file scope omits a required, historically-significant existing test file
(`tests/test_openai_strict_schema_compliance.py`) whose hardcoded capability list would silently
exclude `EngagementCapability`'s new prompt from the repository's own centralized defense against
exactly the defect class that caused a real past production incident. Two further MINOR findings are
reported. No CRITICAL issue was found — every failure mode above is caught before or during the
Plan's own M5/M6 gates, not silently reaching production, but each represents a genuine,
implementation-blocking gap in the Plan as written.

## 2. Repository Baseline

- `git rev-parse HEAD` = `e6cf33786cd36eadc438d4b55cfb6d5224ffbcd8`, unchanged.
- `git status --short`: only the same pre-existing, unrelated documentation backlog; zero
  implementation drift; no migration; `worker/analysis_main.py`/`worker/analysis_cycle.py` do not
  exist.

## 3. Exact File Scope Audit

Independently re-derived the minimum required scope, not merely re-reading the Plan's own table:

- `pyproject.toml`: confirmed not required (`"worker"` already packaged since Phase 12).
- `Dockerfile`: confirmed not required (`COPY . .` precedes `pip install .`).
- `worker/__init__.py`: confirmed not required.
- `schemas/capability.py`/another schema file: confirmed not required — `EngagementCapability`'s
  output is a plain `dict` matching `CapabilityResult.structured_output`'s existing, generic shape;
  no new Pydantic schema class is needed, mirroring every other capability.
- **New finding (F3, MAJOR, detailed in §12)**: `tests/test_openai_strict_schema_compliance.py` is
  **missing** from the Plan's file scope (§4) despite requiring a mechanical, mandatory edit.

Every other file in the Plan's §4 table was independently confirmed both necessary and sufficient.

## 4. EngagementCapability Audit

Re-read `capabilities/intelligence_capability.py` in full against the Plan's §7.1 code — the
mirrored shape is faithful: same constructor signature, same `call_generate()` single-call pattern,
same `_floor_validate()` duplication convention (matching the codebase's own explicit,
documented "duplicated intentionally" precedent), same `CapabilityDefinition`/`CapabilityConfig`
shape. **No hidden plumbing found — confirmed sufficient.**

## 5. Atomic Claim / WorkflowRunner Audit

Re-traced the Plan's §8.1 pseudocode line-by-line against current `workflows/runner.py:99-146`.

- **Task load, state semantics, claim, commit ordering**: all correctly sequenced — claim commits
  before `_execute_steps()` begins, matching the existing, unmodified per-step commit discipline
  (Contract §24, re-confirmed unchanged).
- **In-memory ORM sync method**: the Plan specifies direct attribute assignment
  (`task.status = TaskStatus.RUNNING`) for the winner path and `session.refresh(task)` for the loser
  path — both are viable, idiomatic SQLAlchemy patterns for exactly this purpose; **not ambiguous**,
  correctly resolves audit finding N1 from the Contract audit.
- **`# type: ignore[attr-defined]` omission (F4, MINOR, detailed in §12)**: the Plan's own §8.1 code
  does not include the type-ignore comment `services/triage_orchestrator.py:67` already needed for
  this exact `result.rowcount` pattern under this project's current SQLAlchemy version's type stubs.

## 6. Real Postgres Concurrency Audit

The Plan's §19 test-plan entry for `tests/test_workflow_runner.py` specifies "two real, concurrent
`asyncio.gather()`'d `run()` calls... via `independent_session_factory()`-backed independent
sessions" — this is a genuine, deterministic technique (not "launch and hope"), directly modeled on
`tests/test_triage_orchestrator_claims.py`'s own already-proven concurrency-test shape for
`_claim_new_event()`, re-confirmed feasible with existing infrastructure (§9's own file scope
correctly includes no new test-helper file, since none is needed). **Sufficient, not vague.**

## 7. Eligibility / Backlog Audit — MAJOR FINDING (F1)

**Independently executed, not merely reviewed**, the Plan's §9.1 query syntax against real source
and the real database:

1. **Primary syntax, `.astext`**: `EditorialTask.workflow['workflow_name'].astext` — executed
   directly: `AttributeError: Neither 'BinaryExpression' object nor 'Comparator' object has an
   attribute 'astext'`. **Does not compile at all.** `.astext` is a PostgreSQL-`JSONB`-specific
   comparator; `EditorialTask.workflow` is declared with the generic `sqlalchemy.JSON` type
   (`database/models/editorial_task.py:44`), which does not expose it.
2. **The Plan's own named fallback, `cast(..., String)`**: compiles successfully
   (`CAST(editorial_tasks.workflow['workflow_name'] AS VARCHAR) = 'NEWS_ANALYSIS'`) — but executed
   against the real database, **matches zero rows** out of the real 4723 `CREATED` `NEWS_ANALYSIS`
   tasks. Root cause, verified: PostgreSQL's `->` operator (which `workflow['workflow_name']`
   compiles to) returns a JSON value, not text — casting a JSON value to `VARCHAR` preserves its
   JSON-quoted representation (`"NEWS_ANALYSIS"`, with literal quote characters), which never equals
   the unquoted comparison string `'NEWS_ANALYSIS'`. Directly confirmed: the same query using
   `'"NEWS_ANALYSIS"'` (quoted) as the comparison value matches all 4723 rows.
3. **Correct syntax, verified empirically**: `EditorialTask.workflow['workflow_name'].as_string() ==
   'NEWS_ANALYSIS'` — SQLAlchemy's generic `JSON` type's own purpose-built text-extraction
   comparator — **correctly matches all 4723 real rows**, and passes `mypy` cleanly (independently
   re-verified this session).

**Consequence, if implemented literally per the Plan as written**: whichever of the Plan's two named
options an implementer chose, the eligibility query would either crash at import/compile time
(`.astext`) or **silently, permanently select zero tasks, forever** (`cast()`) — the single most
important mechanism this entire phase exists to build would be non-functional, and — depending on
test rigor — could plausibly still pass a loosely-written integration test (e.g., one that inserts
its own row and asserts *some* result without cross-checking against the real, pre-existing 4723-row
backlog the way this audit did) before being caught.

- **ID**: F1
- **SEVERITY**: MAJOR
- **PLAN LOCATION**: §9.1 (both the primary `.astext` syntax and the named `cast()` fallback), and
  every place the query is referenced (§4, §9.1, §16, §26 item 3).
- **SOURCE EVIDENCE**: `database/models/editorial_task.py:44` (`workflow: Mapped[dict | None] =
  mapped_column(JSON, ...)`, generic type); empirically executed against `HEAD`'s real schema and
  real data this session (both the failure and the correct fix).
- **PROBLEM**: neither of the Plan's two named query-construction options correctly implements the
  eligibility filter.
- **IMPACT**: silent, complete non-functionality of the entire automatic-execution mechanism if the
  `cast()` fallback is chosen (the more likely choice, since it compiles without error).
- **REQUIRED CORRECTION** (not performed — audit only): replace both named options in §9.1 with the
  single, verified-correct `EditorialTask.workflow['workflow_name'].as_string() ==
  WorkflowType.NEWS_ANALYSIS.value` — remove the `.astext`/`cast()` ambiguity entirely, since a
  single correct option now exists and is confirmed compatible with both runtime execution and
  `mypy`.

**Freshness anchor / NULL / timezone handling (Audit 14, unaffected by F1)**: `COALESCE(NewsEvent.
published_at, NewsEvent.collected_at)` — independently re-confirmed correct: `collected_at` is
`nullable=False` with a `server_default`, both columns are `DateTime(timezone=True)` (genuine
`timestamptz`), and the comparison uses a timezone-aware Python `datetime` — no naive/aware mismatch,
no null-comparison risk. **Correct, no finding.**

**Backlog-drain safety (Audit 15/16)**: the *architectural* invariant (no fallback-to-all-CREATED
path, hard `LIMIT`, freshness predicate present) is correctly frozen and, once F1 is corrected,
genuinely enforced at the SQL level. **F1 is a syntax-correctness defect in expressing this
invariant, not a defect in the invariant itself.**

## 8. Worker / Runtime Audit

- **Boot composition (Audit 21)**: `assemble_ai_integration_layer()` + `FilePromptRepository`,
  constructed once at startup inside `_run_enabled_loop()` — re-confirmed this is called **only**
  when enabled, never in the disabled branch (`worker/analysis_main.py`'s `main()`, §10.1 of the
  Plan) — directly answering Audit 24's own question ("does `analysis_main` assemble LLM/Redis
  before checking enabled?"): **no**, confirmed correct by direct code trace, not assumed.
- **Redis dependency (Audit 22)**: re-confirmed necessary and correctly included in the Plan's
  §10.3 Docker service — same reasoning already independently verified in the Contract audit,
  re-checked here for consistency, unchanged.
- **Sequential execution (Audit 17)**: `worker/analysis_cycle.py`'s §9.2 loop contains no
  `asyncio.gather`/`create_task` — confirmed by direct reading of the Plan's own full code listing.
- **Configuration (Audit 23)**: all 4 fields match the Contract exactly; `max_daily_ai_cost`
  confirmed absent.

## 9. Cost / Failure Audit

**Per-task failure isolation within a batch (Audit 18) — MINOR FINDING (F5)**: re-traced §9.2's loop
precisely. An *ordinary* task failure (a capability/step error) is correctly handled —
`WorkflowRunner.run()` never raises for this case, it returns a `WorkflowRunResult` with
`status="FAILED"`, and the loop naturally proceeds to the next `task_id`. However, an *unexpected*
exception during a mid-batch task (e.g., a transient DB error unrelated to claim-loss) is **not**
caught by the loop's own narrow `except (TaskAlreadyRunningError, TaskAlreadyCompletedError)`/
`except TaskNotFoundError` clauses — it would propagate out of `run_analysis_cycle()` entirely,
aborting the remainder of that cycle's batch, to be caught only by `worker/analysis_main.py`'s outer
`except Exception` (deferring the untouched remaining tasks to the next cycle, 300s later). This is
a **safe** outcome (no double-execution, no data loss, no corruption — re-confirmed against the
Contract's own frozen semantics) but the Plan's §18 Failure Matrix does not explicitly state it,
leaving Audit 18's own question ("does per-task failure allow later selected tasks to continue?")
answered only for the *ordinary*-failure case, not the *unexpected*-exception case.

- **ID**: F5
- **SEVERITY**: MINOR
- **PLAN LOCATION**: §9.2 (code), §18 (Failure Matrix table).
- **PROBLEM**: the Failure Matrix's "Cycle-level DB query failure" row only covers the eligibility
  query itself, not a mid-batch, per-task unexpected exception.
- **IMPACT**: none on correctness (already safe by the existing exception-propagation structure);
  purely a documentation-completeness gap.
- **REQUIRED CORRECTION** (not performed — audit only): add one row to §18: "Unexpected exception
  during task N of a batch (not claim-loss) → propagates out of the cycle, remaining batch members
  deferred to next cycle (300s later); no data loss, no double-execution."

**Cost-exposure math (Audit 26)**: re-derived independently — `batch_size=5` × `poll_interval=300s`
structurally permits up to `5 × (86400/300) = 1440` task-attempts/day at the *ceiling* (ignoring that
sequential execution with real LLM latency makes this ceiling practically unreachable — a full batch
of 5, each with up to 4-5 sequential real LLM calls at up to 30s timeout each, could itself approach
or exceed 300s, naturally self-limiting cadence, exactly as Contract §14's own "cycle duration +
interval" model discloses). The Plan does not claim otherwise anywhere — re-confirmed no misleading
cost-safety claim exists.

**Stale `RUNNING` monitoring (Audit 20)**: the Plan's §18/§26 (via Contract §16) names an explicit
1-hour age threshold in the monitoring query — not left as "list all RUNNING tasks" with no
threshold. **Sufficient.**

## 10. Integration / Cleanup Audit

Re-traced the exact FK tree the M5 integration test (§11 of the Plan) would create:
`NewsSource → NewsEvent → EditorialTask` — re-confirmed (via the same FK re-derivation already
performed in the Contract audit) that neither `AIExecution` nor `ContentDraft` nor any other table is
ever written by `run()`'s own capability-execution path for `NEWS_ANALYSIS` (only `EditorialTask.
workflow`/`.status` are mutated) — the Plan's own reuse of Phase 12's proven
`try/finally`+unique-name-prefix cleanup pattern is structurally sufficient; no additional child
table needs cleanup.

## 11. M7 Live Validation Safety Audit — MAJOR FINDING (F2)

**Directly challenged and empirically tested**, per this audit's own explicit instruction not to
accept "the historical backlog is old" as sufficient proof. Queried the real, current database (read-
only): **1153 `NEWS_ANALYSIS` `CREATED` tasks are currently within the 48-hour freshness window** —
not zero, not one, **1153**. This is a direct, current, empirical consequence of Phase 12's own
successful M6 live run (which collected genuinely fresh news) still being within its freshness
window at the time of this audit.

**The Plan's §14 step 2 ("confirm... that at least one genuinely fresh... task exists") does not
establish what it claims to establish.** With 1153 candidates and the frozen `ORDER BY created_at
ASC, id ASC` + `LIMIT 1` rule, the query deterministically selects the **oldest** of those 1153 real
production tasks — which the operator has almost certainly never inspected, did not insert, and may
know nothing about. This conflates two genuinely different guarantees: "the historical (>48h)
backlog cannot be selected" (true, and sufficient for automated-cycle safety) versus "a specific,
known, intended task is what gets observed during a human live-acceptance procedure" (false, as
written).

- **ID**: F2
- **SEVERITY**: MAJOR
- **PLAN LOCATION**: §14 (M7 procedure), step 2.
- **SOURCE EVIDENCE**: live, read-only query this session — 1153 fresh-eligible `NEWS_ANALYSIS`
  `CREATED` tasks currently exist (re-derived using the *corrected*, F1-fixed query syntax, to
  ensure this count itself is accurate).
- **PROBLEM**: `batch_size=1` + the freshness cutoff alone does not guarantee the operator's
  *intended* task is what gets processed — it guarantees only that *some* real, fresh, but possibly
  unrelated production task is processed.
- **IMPACT**: a human running M7 today, following the Plan exactly, would very likely observe an
  arbitrary pre-existing production task being analyzed — not a controlled sample they specifically
  identified — undermining the "tiny controlled sample" premise the Contract itself requires (§30).
  Not a safety/cost risk (still bounded to 1 task, still real, still legitimate production data), but
  a **procedural correctness failure** of the validation's own claimed methodology.
- **REQUIRED CORRECTION** (not performed — audit only): before starting the worker, the operator
  must run the *exact*, corrected (§9.1/F1) eligibility query directly, read-only, and record the
  **specific `task_id`** it would return (the query is fully deterministic given a frozen ordering
  rule — this requires no new mechanism, tag, or production behavior change, only doing the
  verification the Plan currently skips). That specific, now-known `task_id` — not "whichever task
  happens to be selected" — becomes the one being observed. If the operator wants to validate a
  *specific*, self-inserted event instead, that requires either (a) accepting that it will only be
  selected once it becomes the single oldest eligible task (impractical, given 1153 competitors), or
  (b) a deliberately-scoped, separately-authorized one-shot invocation bypassing the general
  eligibility query for this one validation run — a decision this Plan does not currently offer and
  would need to make explicitly if "observe a specific, operator-chosen event" (rather than
  "observe whatever the real pipeline would naturally process next") is actually the intended goal.

## 12. Test Scope Audit — MAJOR FINDING (F3)

Independently grepped for hardcoded capability/registry lists beyond what the Plan's own §19 "grep
performed this session" claim covered (`tests/test_capability_registry.py`,
`tests/test_registry_consistency.py`, `tests/test_workflow_schemas.py`,
`tests/test_workflow_registry.py`) — **found one the Plan's own search missed**:
`tests/test_openai_strict_schema_compliance.py:44-50` defines `_ACTIVE_STRUCTURED_OUTPUT_
CAPABILITIES`, a **hardcoded, 5-entry list** (one tuple per currently-registered capability), used
to parametrize `test_active_capability_prompt_is_strict_schema_compliant` — the repository's own
centralized, dedicated test proving every active capability's prompt is OpenAI strict-mode
compliant. This file's own docstring explicitly ties its existence to a **real, historical
production incident** (a live OpenAI 400 error, `docs/phase10_live_production_validation.md`) this
exact mechanism was built to prevent from recurring.

**This list does not auto-discover new capabilities.** Without an explicit 6th tuple added for
`EngagementCapability`, its new prompt (§7.2 of the Plan) would **never** be checked by this specific,
centralized, historically-significant test — only by the Plan's own separate, per-capability
schema-invariant test inside `tests/test_engagement_capability.py` (§19), which duplicates but does
not integrate with the established, global mechanism.

- **ID**: F3
- **SEVERITY**: MAJOR
- **PLAN LOCATION**: §4 (Exact File Scope table — this file is absent), §19 (Test Plan — same
  absence), §27's own "grep performed this session" claim (incomplete search).
- **SOURCE EVIDENCE**: `tests/test_openai_strict_schema_compliance.py:44-50` (the hardcoded list),
  `:217-235` (the parametrized test consuming it).
- **PROBLEM**: a required, mechanical, low-risk existing-test-file edit is missing from the Plan's
  file scope.
- **IMPACT**: `EngagementCapability`'s prompt would not be covered by the repository's own strongest,
  most relevant safeguard against the exact defect class most likely to cause a real M7 (or later,
  live production) failure — redundant, weaker coverage exists via the Plan's own new test, but the
  established, centralized mechanism is left blind to this one new prompt.
- **REQUIRED CORRECTION** (not performed — audit only): add `tests/test_openai_strict_schema_
  compliance.py` to §4 as a narrow, append-only edit (add one tuple:
  `(EngagementCapability.CAPABILITY_NAME, EngagementCapability.PROMPT_VERSION,
  ENGAGEMENT_CAPABILITY_DEFINITION)` to `_ACTIVE_STRUCTURED_OUTPUT_CAPABILITIES`), and add it to
  §19's Test Plan table and §27's file-count reconciliation.

## 13. Milestone / Stop-Rule Audit

- **Milestone order (Audit 36)**: M1-before-M2 ordering and its stated rationale (§5 of the Plan)
  were independently re-derived and found sound in the Contract audit; re-confirmed here — no new
  concern.
- **Autonomous stop rules (Audit 37)**: §25 of the Plan explicitly requires stopping for existing-
  test regression, unexpected files, migrations, untestable concurrency, pre-existing out-of-scope
  defects, secret exposure, and any live-API need before M7 — matches the audit brief's own
  requirement, no gap found. **Given F1/F2/F3 above, a rigorous autonomous implementation session
  following M5's own integration test (§11 item 3, which asserts the eligible task IS found) would
  likely have self-detected F1 — the eligibility test would fail loudly with the `cast()` fallback —
  satisfying the Plan's own stop-rule discipline even without this audit. This is a genuine
  mitigating factor, not a reason to waive the finding, since it would still cost real implementation
  time to rediscover.**

## 14. Findings

### CRITICAL

None.

### MAJOR

**F1** — Eligibility query syntax (both named options) is non-functional; correct syntax verified.
See §7 for full detail.

**F2** — M7 live-validation isolation claim is false against real, current data (1153 fresh-eligible
tasks exist, not ≤1); the Plan's own stated mechanism does not establish what it claims. See §11 for
full detail.

**F3** — `tests/test_openai_strict_schema_compliance.py`'s hardcoded capability list is missing from
file scope; `EngagementCapability`'s prompt would not be covered by the repository's own centralized,
historically-motivated strict-schema safeguard. See §12 for full detail.

### MINOR

**F4** — `workflows/runner.py`'s planned atomic-claim code omits the `# type: ignore[attr-defined]`
annotation the exact same `result.rowcount` pattern already needs elsewhere in this codebase
(`services/triage_orchestrator.py:67`) under the current SQLAlchemy version's type stubs — would
likely cause a `mypy` failure at M6's own gate if copied literally without this precedented fix.
Correction: add the same type-ignore comment, matching the existing precedent.

**F5** — The Failure Matrix (§18) does not explicitly state the mid-batch unexpected-exception case
(distinct from ordinary per-task failure or claim-loss) — already safe by the existing exception-
propagation structure, but undocumented. See §9 for full detail.

### OBSERVATIONS

- F1 and F2 are both the kind of finding that only surfaces under genuine empirical verification —
  this audit deliberately executed the Plan's own code/queries against real source and real data
  rather than reviewing them as prose, which is what caught both.
- F3 demonstrates the value of searching beyond the Plan's own self-reported "grep performed this
  session" claim — the Plan's own search was reasonable but incomplete, and this audit's broader
  search closed the gap.
- Every other audit area (Audits 3-5, 8, 10, 17, 19-26, 29, 31-32, 34-37) was independently
  re-verified and found sound — the Plan's overall architecture, milestone ordering, and
  Contract-fidelity are strong; the findings here are concentrated in three specific, narrow,
  fixable spots, not systemic.

## 15. Observations

(See inline observations above, §13/§14.)

## 16. Readiness Score

**5/10.** The Plan's architecture, milestone sequencing, and Contract-fidelity are sound, and two of
the three MAJOR findings (F1, F3) are narrow, mechanically fixable corrections once identified. The
third (F2) requires a genuine procedural correction to the M7 methodology, not just a syntax fix, but
does not reopen any architectural decision. None of the three findings implicates the Contract itself
— all are Plan-level (implementation-detail) gaps. Given three MAJOR findings against this audit's
own explicit CRITICAL=0/MAJOR=0 bar, approval cannot be granted as written.

## 17. Final Verdict

PHASE 13 IMPLEMENTATION PLAN NOT READY — CORRECTIONS REQUIRED
