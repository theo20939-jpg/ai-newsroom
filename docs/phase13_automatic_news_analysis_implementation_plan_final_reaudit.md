# Phase 13 — Automatic News Analysis Implementation Plan Final Targeted Re-Audit

Scope: this is a **targeted** re-audit of the corrections applied to
`docs/phase13_automatic_news_analysis_implementation_plan.md` in response to
`docs/phase13_automatic_news_analysis_implementation_plan_audit.md` (CRITICAL=0, MAJOR=3, MINOR=2).
Historical findings already resolved are not re-litigated except where independently
re-verified as evidence for the executive verdict. All checks below were performed empirically
against the real, current repository state (models, tests, installed SQLAlchemy, and one
read-only database query) — not by re-reading the Plan's own prose as self-evidence.

No production code, test, or migration file was modified to produce this document. No worker was
started. No OpenAI/LLM call was made. Nothing was committed.

## 1. Executive Verdict

The three original MAJOR findings (F1 eligibility-query syntax, F2 M7 isolation, F3 strict-schema
test scope) and both MINOR findings (F4 mypy precision, F5 mid-batch failure semantics) are
**correctly and completely resolved** in the current Plan revision — verified independently below,
not merely re-read.

However, this re-audit's own independent test-scope recount (§6, Check 12) found **two new,
previously-unreported MAJOR-severity file-scope gaps**, both of the same class the audit process
exists to catch: existing, currently-passing regression tests that hardcode an assumption Phase
13's own M1 milestone (`capabilities/registry.py::build_registry()` registering the literal name
`"engagement"`) mechanically and certainly breaks. Neither file is in the Plan's current §4 file
scope. Both are narrow, single-test corrections — not architecture issues — but until they are in
scope, M1 would break two currently-passing tests, M6's own "zero failures" gate could not be
satisfied, and a fresh autonomous implementer would have to invent an out-of-scope decision to
proceed (violating Check 19's own bar).

**CRITICAL = 0, MAJOR = 2 (both new, neither historical), MINOR = 0 new (one OBSERVATION carried
forward for future tightening). Approval threshold (MAJOR = 0) is not met.**

## 2. Eligibility SQL Verification (Checks 1–3)

Independently re-read `database/models/editorial_task.py` and `database/models/news_event.py`
this session (not trusted from the Plan's own citation):

- `EditorialTask.workflow: Mapped[dict | None] = mapped_column(JSON, nullable=True)` — confirmed
  generic `sqlalchemy.JSON`, not PostgreSQL `JSONB`. This independently reconfirms the Plan's own
  root-cause diagnosis for why `.astext` cannot work.
- `EditorialTask.event_id` is a `ForeignKey("news_events.id")`, matching the Plan's planned
  `.join(NewsEvent, EditorialTask.event_id == NewsEvent.id)` exactly.
- `NewsEvent.published_at` (nullable) and `NewsEvent.collected_at` (`nullable=False`,
  `server_default=func.now()`) match the Plan's `COALESCE` freshness-anchor design exactly — the
  anchor can never be null.

Independently re-executed this session (installed `sqlalchemy==2.0.51`, confirmed via
`import sqlalchemy; sqlalchemy.__version__`):

```
>>> EditorialTask.workflow["workflow_name"].astext
AttributeError: Neither 'BinaryExpression' object nor 'Comparator' object has an
attribute 'astext'
```

**Check 1 (`.astext` invalidity): reconfirmed, independently, this session.**

The Plan's exact planned statement (§9.1, reconstructed verbatim from the Plan and compiled,
without modifying any source file) compiled successfully:

```
SELECT editorial_tasks.id
FROM editorial_tasks JOIN news_events ON editorial_tasks.event_id = news_events.id
WHERE editorial_tasks.status = :status_1
  AND editorial_tasks.workflow[:workflow_1] = :param_1
  AND coalesce(news_events.published_at, news_events.collected_at) >= :coalesce_1
ORDER BY editorial_tasks.created_at ASC, editorial_tasks.id ASC
LIMIT :param_2
```

**Check 2 (compile the exact planned query): PASS.** All six mandatory predicates/clauses named
in Check 2 are present: `status == CREATED`, workflow-name JSON scalar match, the real FK join,
the `COALESCE` freshness comparison, deterministic `ORDER BY`, and SQL-level `LIMIT`.

Additionally, compiled specifically against the `postgresql` dialect (with literal binds, to see
the actual operator chosen — this goes beyond what either the original audit or the Plan itself
recorded, and is new, stronger evidence for this re-audit):

```
CAST((editorial_tasks.workflow ->> 'workflow_name') AS VARCHAR) = 'NEWS_ANALYSIS'
```

This confirms `.as_string()` compiles to Postgres's `->>` (**text**-extraction) operator, not the
`->` (JSON-extraction) operator the retired `cast(workflow['workflow_name'], String)` fallback
used. This is the actual semantic root of the fix, independently confirmed at the operator level,
not merely re-derived from the prior session's row-count evidence — `->>` returns Postgres text
directly (no JSON quoting to strip), so the equality comparison against the plain Python string
`'NEWS_ANALYSIS'` is correct by construction, not by empirical coincidence.

**Check 3 (controlled query semantics, test strategy)**: the Plan's §19 test-plan row for
`tests/test_analysis_worker_cycle.py` (as revised) requires, against controlled test-owned rows: a
`NEWS_ANALYSIS` task found (positive), a `CONTENT_GENERATION`-workflow task excluded (negative,
proves the JSON match is workflow-specific, not a substring/any-match), freshness cutoff
(`>48h` excluded, `<48h` included), batch cap (6+ eligible → exactly 5), and deterministic
ordering. `CREATED`-only filtering (excluding `RUNNING`/`COMPLETED`/`FAILED`) is guaranteed by
construction (a single `==` predicate on an indexed enum column) and is not separately spelled out
as its own named test case in §19/§11 — this is a real but low-severity gap (see §10 OBSERVATIONS,
not a MAJOR/MINOR: the predicate is trivial and directly visible in the frozen query text itself,
unlike the JSON-extraction semantics, which were genuinely non-obvious and empirically wrong twice
before being fixed).

**No implementation ambiguity found in the eligibility query itself. MAJOR-1 (original) remains
fully resolved.**

## 3. Backlog Safety Verification (Check 4)

Re-confirmed from the current Plan text: no startup catch-up mode, no second unfiltered query, no
Python-side filtering fallback, and no automatic stale-`RUNNING` status mutation are proposed
anywhere in the Plan (§9.1's query is the only eligibility-selection code path; §18's Failure
Matrix explicitly documents stale `RUNNING` as "No automatic recovery" — Contract §16, unchanged).

A read-only diagnostic query was re-run this session (no write, no claim) to re-verify the
Plan's own cited backlog figures are still substantively accurate:

```
total_created_news_analysis (all, any age): 4723
fresh_eligible_le48h (using the corrected .as_string() query): 1139
```

The `4723` total matches the Plan's own citation exactly. The fresh-eligible count has drifted
slightly from the Plan's cited `1153` to `1139` (a two-day gap between the original audit and this
re-audit, with the freshness window continuously sliding and no new NEWS_ANALYSIS tasks having
been created in the interim since the Phase 12 collection worker is not currently running) — this
is expected drift, not a discrepancy, and does not change the conclusion: several hundred
uncontrolled, fresh-eligible production tasks exist today, and the Plan's corrected M7 procedure
(§4 below) does not depend on the exact count, only on the qualitative fact that it is greater
than one. Logged as an OBSERVATION (§10), not a finding: a future implementer executing M7 should
re-run this same read-only count at execution time rather than trusting either cited number.

**Historical/stale backlog cannot be selected by construction. No new safety gap found.**

## 4. M7 Exact-Task Isolation Verification (Checks 5–9, 17)

**Check 5**: re-read the Plan's current §14. The `batch_size=1`-alone isolation claim is fully
retracted (no trace of "this is the deterministic isolation mechanism" language remains); the
1153-task finding is cited explicitly, with this re-audit's own updated `1139` figure not yet
reflected (expected — the Plan was corrected before this re-audit ran; not a defect, see §10).
The hard precondition against starting the normal worker while the uncontrolled condition holds is
present and explicit.

**Check 6 (exact-task live path feasibility) — independently re-verified against real source**:
`workflows/runner.py`'s real, current, unmodified `WorkflowRunner.run()` signature is:

```python
async def run(self, session: AsyncSession, task_id: UUID) -> WorkflowRunResult:
```

confirmed to accept an exact `task_id` directly — no batch/selection layer sits between a caller
and this method today, and none needs to be added for M7's corrected procedure. Tracing the exact
path the Plan's §14 describes: `task_id` (operator-recorded, §14 step 1) →
`CapabilityExecutor(session, task_id, capability_registry)` + `WorkflowRunner(executor)`
(constructed directly, exactly as `worker/analysis_cycle.py`'s own §9.2 would, per-task) →
`runner.run(session, task_id)` → the real atomic-claim `UPDATE ... WHERE id = task_id AND status =
'CREATED'` (§8.1, unmodified by this M7 procedure) → the real, unmodified `_execute_steps()` →
persisted `EditorialTask.status`/`workflow` (real, committed, same code as production). This path
requires **zero** new production file, no batch worker, no eligibility query, no new CLI, and no
Contract expansion — `WorkflowRunner.run()`, `CapabilityExecutor`, and
`assemble_ai_integration_layer()` are all already-authorized, already-existing constructs (Contract
§26; `worker/analysis_main.py`/`worker/analysis_cycle.py`, §10.1/§9.2 of the Plan, already build
and use exactly these same objects at startup). **Check 6: PASS — exact-task live execution is
already possible within currently-authorized scope; it is not a pre-live prerequisite requiring
new authorization.**

**Check 7**: the Plan's §14 step 1 requires recording, before any live call: exact `task_id`,
associated `NewsEvent.id`, the freshness timestamp and its value, `status == CREATED`
confirmation, and an explicit written "intended controlled sample" statement. This matches Check 7
exactly, including the optional freshness-eligibility confirmation (the Plan's step 1 records the
freshness timestamp as context, though the corrected procedure does not require the sample to pass
the batch-worker's own eligibility query, since it bypasses that query — this is intentional and
consistent with the Plan's own stated design, not an omission).

**Check 8**: the Plan's §14 explicitly names real `assemble_ai_integration_layer()`, real
`FilePromptRepository`, real `async_session_factory`, real `CapabilityExecutor`, real
`WorkflowRunner` — no fake gateway, no bypass of the atomic claim (the claim happens inside the
unmodified `run()` call, not skipped), no manual status mutation anywhere in the procedure.
**PASS.**

**Check 9**: the Plan explicitly frames this as "a validation procedure using existing primitives,"
run from "a human-supervised Python session (an interactive REPL or a throwaway, uncommitted local
script) — never a new file added to the repository, never committed." No new externally-exposed
command, no persistent operator interface, no architecture drift. **PASS.**

**Check 17 (live cost safety)**: the corrected procedure targets exactly one `task_id`, with no
selection mechanism in play, so the "at most 2" ceiling in the check's own instruction is not
approached — exactly one task is ever claimed by construction. The Plan does **not** explicitly
instruct the operator to stop/disable the batch analysis worker before running M7, but this is
moot given the corrected design: M7 never starts `worker/analysis_main.py` at all (§14's own text:
"The batch worker (`worker/analysis_main.py`) is **not started** for M7."). A genuine remaining
gap: the Plan does not address what happens if the batch worker is *already running in the
background for an unrelated reason* (e.g., a prior, still-live deployment) at the moment M7's
direct invocation executes — in that case, the atomic claim (§8.1) still structurally guarantees
the background worker cannot claim the *same* `task_id` M7 is targeting (only one of two racing
claimants can win), but the background worker could still be concurrently processing *other*,
different fresh-eligible tasks from the 1139-deep pool during M7's own window, which is a true
statement the Plan does not explicitly call out. This does not compromise M7's own isolation (the
one recorded `task_id` is still provably isolated by the atomic claim, regardless of what else is
happening), so it is logged as an OBSERVATION (§10), not a MINOR/MAJOR finding — the Plan should
ideally state explicitly that the batch worker must not be running at all during M7 for a fully
clean validation, but the isolation guarantee for the one sample task does not actually depend on
this.

**M7 (MAJOR-2, original): fully resolved.**

## 5. Strict-Schema Scope Verification (Checks 10–11)

Independently re-read `tests/test_openai_strict_schema_compliance.py` in full this session:

- `_ACTIVE_STRUCTURED_OUTPUT_CAPABILITIES` (lines 44-50) is confirmed hardcoded, 5 tuples
  (scoring/2, quality/3, research/2, intelligence/2, copywriting/2), independently re-stated (not
  imported) from `capabilities/registry.py::build_registry()`, exactly as the Plan describes.
  Confirmed: this list does **not** auto-discover; a 6th capability not added here would silently
  receive zero coverage from `test_active_capability_prompt_is_strict_schema_compliant` (the
  parametrized test at lines 217-235).
- The Plan's revised §4/§7/§19 now authorize exactly one new tuple,
  `("engagement", "1", ENGAGEMENT_CAPABILITY_DEFINITION)`, added to this list — matching the file's
  own established tuple shape (`(CAPABILITY_NAME, PROMPT_VERSION, DEFINITION)`) exactly. No
  existing tuple, assertion, or helper function (`_strict_schema_violations`,
  `_prompt_repository`) is touched.
- The centralized test asserts both `_strict_schema_violations(rendered.output_schema) == []`
  (checks `additionalProperties: false` at every object level, every property present in
  `required`, every array property has an `items` sub-schema — read in full, lines 57-96) and
  `rendered.output_schema.get("required") == definition.expected_output_keys`. The Plan's own
  §7.2 `prompts/engagement/v1.yaml` (`additionalProperties: false`, `required` listing all three
  properties, no array-typed properties) and §7.1's `ENGAGEMENT_CAPABILITY_DEFINITION.
  expected_output_keys = ["engagement_potential_score", "audience_fit", "reasoning"]` are mutually
  consistent and would pass this invariant as specified — verified by direct comparison of the
  Plan's own two artifacts, not merely assumed compatible.

**Check 10/11: PASS. MAJOR-3 (original) remains fully resolved. No conflict between the
engagement-specific unit test (§19, in `tests/test_engagement_capability.py`) and the centralized
invariant — the Plan correctly requires both, not one in place of the other.**

## 6. Test Scope Verification (Check 12) — **source of both new findings**

Re-ran a repository-wide grep independently this session, broader than the prior session's own
grep (which searched only for hardcoded *counts* — "5 registered capabilities", "3 steps"). This
session's grep additionally searched for hardcoded *identity* assumptions about the literal string
`"engagement"` specifically, since that is the exact, frozen `CAPABILITY_NAME` Phase 13 introduces
(Plan §7.1) — a class of hidden coupling the prior grep did not cover.

Two real, currently-passing, pre-existing tests were found that hardcode "engagement" is
**not yet** a registered `Capability`, and would both fail immediately once Phase 13's M1
milestone registers it:

1. `tests/test_phase9_research_intelligence_integration.py`,
   `test_real_news_analysis_still_fails_at_engagement_analysis_step` (lines 376-394, plus its
   preceding "Negative/boundary" section comment, lines 368-373): runs the real, unmodified
   `WorkflowRunner` against a real `NEWS_ANALYSIS` task through the real `build_registry()`, and
   asserts `result.status == "FAILED"` with
   `step_results[2].status == "FAILED"  # "engagement" is not a registered Capability`. Once M1
   registers `"engagement"`, this assertion is no longer true — the third step will no longer fail
   for this reason (its actual outcome depends on the two-response-only `FakeLLMGateway` used by
   this test, which has no third canned response queued for the engagement call — an unrelated,
   incidental behavior, not a deliberate proof of anything Phase 13 needs).
2. `tests/test_phase10_capability_registration.py`,
   `test_unregistered_capability_still_raises_unknown_capability_error` (lines 72-87): asserts
   `pytest.raises(UnknownCapabilityError)` for **both** `registry.resolve("engagement")` (line 84)
   and `registry.resolve("no_such_capability")` (line 87). The first assertion becomes false the
   moment M1 registers `"engagement"`; the second remains valid and must be preserved.

Both are **certain**, not speculative — verified by reading the exact assertion text, not by
searching for a suggestive comment. Neither file is anywhere in the Plan's current §4 file scope.
Confirmed no other test in the repository asserts `"engagement"` is unregistered (full-repository
grep for the literal string `"engagement"` returned exactly 6 hits total: the two above, the
`resolve_ai_capability("engagement") == AICapability.INTELLIGENCE` mapping test in
`tests/test_capability_mapping.py:29` — unaffected, this maps a cost-accounting bucket independent
of registry state, and if anything corroborates that `"engagement"` was already anticipated as a
real future capability name — and `tests/test_ai_execution_mapper.py:48`'s
`test_resolves_the_engagement_alias_through_the_centralized_mapping`, which exercises the same
cost-mapping function and is likewise unaffected by registry state).

A secondary, non-blocking coupling risk was also traced and is worth recording precisely so a
future implementer does not reintroduce it: `tests/test_phase9_cross_cutting_regression.py`'s
`test_no_phase9_test_pairs_real_news_analysis_with_completed_status` (lines 64-84) is a
static-file-scan meta-test that flags any `test_phase9_*.py` file containing all three of
`"NEWS_ANALYSIS"`, `'"COMPLETED"'`, and `"status =="`, **except** if the literal function name
`test_real_news_analysis_still_fails_at_engagement_analysis_step` also appears in that file's text
(a name-string sentinel, not a structural exception). Independently confirmed by grep: the token
`"NEWS_ANALYSIS"` appears in `tests/test_phase9_research_intelligence_integration.py` **only**
inside the one test/comment identified in finding 1 above (its section-4 comment, line 369, and
the test body itself, line 385) — nowhere else in that file. This means a **full removal** of that
test function and its section comment (the correction this re-audit recommends, not a partial edit
that keeps the function name while changing its body) removes the `"NEWS_ANALYSIS"` token from the
file entirely, so the meta-test's `"NEWS_ANALYSIS" in text` precondition becomes false and it does
not flag the file — no edit to `tests/test_phase9_cross_cutting_regression.py` is mechanically
required. A future implementer who instead edits the test's *body* while keeping its *name*, or
who partially edits it, could trip this meta-test; the required-correction wording below is
written to avoid that trap explicitly.

**MAJOR (new) — see §10 for exact IDs and required corrections.**

Re-verified the Plan's own already-corrected count (§28: 8 production + 8 test = 16) against §4's
table row-for-row — internally consistent as stated. This re-audit's new findings would raise the
test-file total to 10 once incorporated (two more narrow, append/remove-only edits) — not
recalculated in this document, since fixing counts is a Plan-correction action, out of scope for
this audit-only session.

## 7. Mypy / Failure-Semantics Precision (Checks 13–14)

**Check 13**: `services/triage_orchestrator.py:67` re-read directly this session:
`return result.rowcount == 1  # type: ignore[attr-defined]  # CursorResult at runtime for an
UPDATE; Result[Any]'s stub doesn't expose it statically`. The Plan's §8.1 now carries the
byte-identical `# type: ignore[attr-defined]` annotation on its own analogous `claim_result.
rowcount` line, with an explanatory paragraph citing this exact precedent, and an explicit
instruction against broader ignores, mypy relaxation, or unnecessary model-typing changes. No
global relaxation was found anywhere in the Plan. **PASS.**

**Check 14**: the Plan's §18 now contains an explicit "Mid-batch failure semantics" subsection
distinguishing PER-TASK WORKFLOW FAILURE (task #2 fails, becomes `FAILED`, logged, tasks #3-#5
still attempted, no refill, cycle does not abort) from CYCLE-LEVEL INFRASTRUCTURE FAILURE (aborts
the remaining cycle, caught by `worker/analysis_main.py`'s outer `except Exception`, per §10.1,
unchanged). This matches the expected frozen behavior specified in the correction task exactly,
including "total selected candidates remains ≤5" and "no ambiguity." **PASS.**

## 8. Atomic-Claim Non-Regression (Check 15)

Re-read the real, current, unmodified `workflows/runner.py` this session. Confirmed the Plan's
§8.1 target — "the `run()` method body only (lines 111-123 of the current file)" — matches the
real file's current line numbers exactly (`task = await session.get(...)` at line 111 through
`await session.commit()` at line 123). The Plan's diff replaces exactly this span with the atomic
`UPDATE ... WHERE status = 'CREATED'` + explicit in-memory sync; every other method
(`_execute_steps`, `_run_step`, `_fail`) is untouched by the Plan, confirmed by direct comparison
against the real file's current content (lines 147-301), not merely trusted from the Plan's own
claim. The commit-before-any-LLM-call invariant, the loser's zero-AI-call guarantee (the atomic
`UPDATE` happens before any capability/LLM code is reached), and `RUNNING`/`COMPLETED`/`FAILED`
semantics are all unchanged by this revision relative to the previously-audited version of the
Plan. **No regression introduced by the correction pass itself.**

## 9. File-Scope Non-Regression (Check 16)

Production/runtime file count is unchanged by the correction pass: 4 new + 4 modified = 8,
verified against §4's table. The corrected M7 procedure (§14) introduces no new production file —
confirmed directly in §6/Check 6 above by tracing that `WorkflowRunner.run()` already accepts an
exact `task_id`. No CLI script, API endpoint, `pyproject.toml` change, schema change, or migration
is required by the correction. **PASS for the correction's own production-file impact.** (The two
new MAJOR findings in §6 are test-file, not production-file, additions — they do not implicate
Check 16's production-file guarantee.)

## 10. Findings

### CRITICAL

None.

### MAJOR

**ID: RA-1**
**SEVERITY: MAJOR**
**PLAN LOCATION**: §4 (Exact File Scope) — no row exists for
`tests/test_phase9_research_intelligence_integration.py`.
**SOURCE EVIDENCE**: `tests/test_phase9_research_intelligence_integration.py:376-394` —
`test_real_news_analysis_still_fails_at_engagement_analysis_step` asserts
`result.status == "FAILED"` and `step_results[2].status == "FAILED"  # "engagement" is not a
registered Capability` for a real `NEWS_ANALYSIS` task run through the real, unmodified
`WorkflowRunner`/`build_registry()`. Re-read directly this session; not inferred from a comment.
**PROBLEM**: Phase 13's own M1 milestone registers `"engagement"` in `build_registry()` (Plan
§7.3). This test's entire premise — that `"engagement"` is unregistered — becomes false the moment
M1 ships, and its hardcoded assertion will fail.
**IMPACT**: A currently-passing regression test breaks as a direct, certain, mechanical
consequence of Phase 13's own new code, immediately at M1. M6's own gate ("Full pytest... zero
failures", §12 item 1) cannot be satisfied without addressing this, blocking the entire Plan's own
readiness criteria. A fresh autonomous implementer following only the current Plan would either be
blocked at M1's own regression check or would have to invent an out-of-scope decision about how to
handle this test — violating Check 19's own bar for autonomous determinism.
**REQUIRED CORRECTION**: Add `tests/test_phase9_research_intelligence_integration.py` to §4 as a
narrow MODIFY (remove-only) edit, scoped to M1: remove the `test_real_news_analysis_still_fails_
at_engagement_analysis_step` function **and** its preceding section-4 comment block (lines
368-394) in full — not a partial edit that retains the function name while changing its body (see
§6's meta-test coupling note: a full removal, which also removes the file's only two occurrences
of the literal token `"NEWS_ANALYSIS"`, requires no companion edit to
`tests/test_phase9_cross_cutting_regression.py`'s own static-scan meta-test). Justification for
the removal (to be stated in the Plan, not invented ad hoc by the implementer): this negative-
boundary test is superseded by Phase 13's own new positive completion proof
(`tests/test_news_analysis_integration.py`, Plan §11) — the boundary it tested (engagement
unregistered) no longer exists once Phase 13 ships, by design. No other assertion in this file is
authorized to change.

**ID: RA-2**
**SEVERITY: MAJOR**
**PLAN LOCATION**: §4 (Exact File Scope) — no row exists for
`tests/test_phase10_capability_registration.py`.
**SOURCE EVIDENCE**: `tests/test_phase10_capability_registration.py:72-87` —
`test_unregistered_capability_still_raises_unknown_capability_error` asserts
`pytest.raises(UnknownCapabilityError): registry.resolve("engagement")` (line 83-84), with an
explicit docstring citing `"engagement"` as "the same real, already-unregistered name Contract §3
itself cites." Re-read directly this session.
**PROBLEM**: Identical root cause to RA-1 — M1 registers `"engagement"`, so
`registry.resolve("engagement")` will no longer raise `UnknownCapabilityError`.
**IMPACT**: Same class as RA-1 — a currently-passing test breaks certainly and mechanically at M1;
blocks M6's own gate.
**REQUIRED CORRECTION**: Add `tests/test_phase10_capability_registration.py` to §4 as a narrow
MODIFY (append/edit-only) edit, scoped to M1: remove only the
`registry.resolve("engagement")`/`pytest.raises(UnknownCapabilityError)` pair (lines 83-84) from
`test_unregistered_capability_still_raises_unknown_capability_error`, **preserving** the function,
its docstring's still-true remaining claim, and the second assertion
(`registry.resolve("no_such_capability")` still raises `UnknownCapabilityError`, lines 86-87)
unchanged. The docstring's specific sentence naming `"engagement"` as "the same real,
already-unregistered name" must be updated (it is no longer true after M1) without weakening the
test's remaining, still-valid assertion. No other test in this file (`test_build_registry_
resolves_copywriting_directly`, `test_build_registry_resolves_all_five_capabilities`) is
authorized to change or be renamed to "six" — that remains out of Phase 13's frozen scope per the
Contract (registering a 6th capability does not obligate renumbering an unrelated Phase 10 test
name).

### MINOR

None new. (All MINOR findings from the original audit — F4 mypy precision, F5 mid-batch failure —
are confirmed resolved, §7.)

### OBSERVATIONS

**RA-O1**: The Plan's M7 procedure (§14) does not explicitly state that the batch analysis worker
must not be running (for any unrelated reason) concurrently with the M7 direct-invocation
procedure. The one-sample isolation guarantee itself does not depend on this (the atomic claim
still structurally protects the one recorded `task_id`), but stating it explicitly would remove
all ambiguity for an operator running M7 in an environment where a worker might already be up.
Non-blocking; recommended for the next Plan pass.

**RA-O2**: The Plan's §14/§26 R9 cite the historical `1153` fresh-eligible-task count from the
original audit session. An independent read-only recount this session found `1139` — expected
drift over the elapsed time between sessions, not a discrepancy, and the corrected M7 procedure
does not depend on the exact figure. Recommend a future Plan pass note that this number should be
re-verified at actual M7 execution time rather than trusted from either cited snapshot.

**RA-O3**: No explicit test case in §11/§19 directly proves that a `RUNNING`/`COMPLETED`/`FAILED`
`NEWS_ANALYSIS` task is excluded by the eligibility query, distinct from the already-planned
freshness/workflow-type/batch-cap tests. The exclusion is guaranteed by construction (a single
`status == CREATED` equality predicate, visible directly in the frozen query text, §9.1) and is
categorically lower-risk than the JSON-extraction semantics that were twice empirically wrong
before being fixed — not elevated to MINOR. Recommended as a cheap addition for completeness only.

**RA-O4**: `tests/test_phase9_cross_cutting_regression.py::test_full_boot_sequence_resolves_all_
four_capabilities` (and its file header's "resolves all four registered Capabilities") already
does not check `CopywritingCapability` (the 5th, pre-existing capability) today, independent of
Phase 13 — a pre-existing gap, not caused by this Plan's own new code. Per the Plan's own
Autonomous Stop Rules (§25: "a real, pre-existing (non-Phase-13-caused) defect is discovered... fix
only if directly caused by this Plan's own new code... otherwise escalate"), this is correctly out
of scope and requires no Phase 13 action. Recorded only so a future implementer does not confuse
it with RA-1/RA-2, which *are* Phase-13-caused.

## 11. Readiness Score

**6/10.** Every historical finding (3 MAJOR + 2 MINOR) is genuinely, verifiably resolved — the
eligibility query is now correct and independently re-compiled clean against the real dialect, the
M7 procedure is now a sound, already-authorized direct-invocation design with no new production
surface, the strict-schema coverage gap is closed, and both precision fixes are exact and
precedented. The score is held below approval solely by two newly-discovered MAJOR findings (RA-1,
RA-2) that are narrow, mechanical, single-test corrections with clearly specified fixes — not a
sign of a deeper architectural problem, but real enough to certainly break M1/M6 if left
unaddressed, and therefore not waivable.

## 12. Final Verdict

**Git status** (`git status --short`, read-only, run this session): only untracked Phase 9/9.5/10
governance-backlog files and untracked Phase 13 governance documents (Discovery, Decision
Resolution, Architecture Contract, Contract Audit, Implementation Plan, Implementation Plan Audit,
and this new final-re-audit file) appear. No source file, test file, or migration is modified.
Nothing staged. Nothing committed.

PHASE 13 IMPLEMENTATION PLAN NOT READY — CORRECTIONS REQUIRED
