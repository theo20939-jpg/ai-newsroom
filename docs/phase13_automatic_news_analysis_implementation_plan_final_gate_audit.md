# Phase 13 — Final Implementation Readiness Gate Audit

Last gate before autonomous M0→M6 implementation. This audit does not redo the broad architectural
review already performed across three prior audit passes (Implementation Plan Audit: F1-F5;
Final Re-Audit: RA-1/RA-2; Test-Scope Final Re-Audit: TS-1) — every one of those findings is
re-confirmed resolved below by direct evidence, not re-litigated from scratch. This audit's own
independent contribution is the set of gates not yet empirically exercised in any prior pass:
Docker/packaging (Gate 12), the concurrency test's actual determinism mechanism (Gate 7), and
`AIExecution`-row cleanup applicability (Gate 13). No Plan, Contract, source, test, or migration
file was modified. No worker started, no live API call made, nothing committed.

## 1. Executive Verdict

**CRITICAL = 0, MAJOR = 0.** Every one of the 20 gates below passes on direct, re-verified
evidence — re-reading real source (`Dockerfile`, `pyproject.toml`, `tests/test_triage_orchestrator_
claims.py`, `database/models/ai_execution.py`, `capabilities/gateway_call.py`,
`tests/test_phase9_research_intelligence_integration.py`), not merely re-trusting the Plan's own
prose. A fresh autonomous implementation session can execute M0→M6 exactly from the current Plan
without inventing a substantive decision, touching an unplanned file, or predictably breaking an
existing test. Two OBSERVATIONS are recorded for optional future polish; neither blocks approval.

**PHASE 13 IMPLEMENTATION PLAN APPROVED — READINESS SCORE: 9/10.**

## 2. Exact Implementation Scope (Gate 1)

Independently re-derived from §4's table, not from §28's arithmetic:

**Production/runtime — 8 files, matches exactly:**
- NEW: `capabilities/engagement_capability.py`, `worker/analysis_main.py`,
  `worker/analysis_cycle.py`, `prompts/engagement/v1.yaml`
- MODIFIED: `workflows/runner.py`, `capabilities/registry.py`, `core/config.py`,
  `docker-compose.yml`

**Tests — 11 files, matches exactly, every path individually re-read against §4's table this
session:**
1. `tests/test_engagement_capability.py` — NEW
2. `tests/test_workflow_runner.py` — MODIFY (append only)
3. `tests/test_analysis_worker_cycle.py` — NEW
4. `tests/test_analysis_worker_main.py` — NEW
5. `tests/test_settings_phase7.py` — MODIFY (append only)
6. `tests/test_news_analysis_integration.py` — NEW
7. `tests/test_capability_registry.py` — MODIFY (append only)
8. `tests/test_openai_strict_schema_compliance.py` — MODIFY (append only)
9. `tests/test_phase9_research_intelligence_integration.py` — MODIFY (narrow)
10. `tests/test_phase10_capability_registration.py` — MODIFY (narrow)
11. `tests/test_phase9_cross_cutting_regression.py` — MODIFY (narrow, one-line sentinel swap)

4 new (1, 3, 4, 6) + 7 modified (2, 5, 7, 8, 9, 10, 11) = **11.** 8 + 11 = **19.** No 20th
implementation file found anywhere in this session's own re-derivation. **Gate 1: PASS.**

## 3. Engagement Registration / Test Impact (Gate 2, Gate 3)

Final repository-wide grep this session for `engagement`, `engagement_analysis`,
`EngagementCapability`, `UnknownCapabilityError`, `NEWS_ANALYSIS`, registry-resolution/hardcoded-set
patterns, and expected-workflow-failure assertions confirms the same result as the prior two audit
passes, with no drift: every mechanically-affected test is one of the 11 files in §2 above. No new
candidate found. This is the third independent search across three separate audit sessions
converging on the same, closed set — strong confirmation, not merely repetition.

**Gate 3 (meta-test)**: re-confirmed `tests/test_phase9_cross_cutting_regression.py:81`'s planned
change is exactly `"test_real_news_analysis_still_fails_at_engagement_analysis_step"` →
`"test_real_news_analysis_now_completes_through_engagement_analysis"` (§7.7), one line, nothing
else in the file. §7.7's own text explicitly states the scan structure (glob every
`test_phase9_*.py`, three-token trigger, single-sentinel exemption) is unchanged — only the
exempted name changes — and requires a GREEN-B proof (a temporary, uncommitted throwaway file with
the same trigger under a *different* name must still be flagged and rejected) specifically to
demonstrate the fix doesn't broaden protection. No other meta-test/static-scan dependency was
found: a repository-wide grep for `.glob(` across all of `tests/` (re-run this session, not
inherited) returns exactly two hits — `tests/test_content_draft_service.py` (scans
`capabilities/*.py` for a `ContentDraft` import; `EngagementCapability` does not import it,
unaffected) and the one file already in scope. **Gate 2/3: PASS.**

## 4. M1 Atomic Green Check (Gate 4)

§7's binding rule and §7.6's 8-row Regression Matrix jointly enumerate exactly the nine items Gate
4 lists (grouped as 8 rows, since row 2 covers both the registry-append and the Phase-10 positive
test together — audited by semantic ownership, not bullet-count, per Gate 4's own instruction):
`EngagementCapability`, the prompt, the registration, `tests/test_engagement_capability.py`, the
registry tests (both files), the strict-schema addition, the Phase 9 replacement (§7.4), the Phase
10 replacement (§7.5), and the Phase 9 cross-cutting sentinel migration (§7.7) — all nine
substantive items are present, none omitted. §7's own text is explicit: "there is no authorized
'registration/replacement lands, dependent tests fixed later' ordering, at any depth" — covering
not just the direct registration→test coupling but the second-order §7.4→§7.7 coupling discovered
in the prior audit pass. **No authorized intermediate checkpoint leaves a stale test red. Gate 4:
PASS.**

## 5. Atomic Claim / Concurrency Gate (Gate 6, Gate 7)

**Gate 6**: §8.1's diff, re-read this session, specifies exactly the required chain: `session.get()`
→ atomic conditional `UPDATE ... WHERE id = task_id AND status = 'CREATED'` → `await session.
commit()` → `rowcount` check → on loss, `session.refresh(task)` + raise the correct exception
*before* `WorkflowExecutionState.model_validate()` or any capability code is reached → on win,
explicit in-memory `task.status = TaskStatus.RUNNING` sync. The loser's raise happens structurally
before `_execute_steps()` is ever called, so zero LLM/capability calls are possible for the loser,
and the loser is never marked `FAILED` (it raises `TaskAlreadyRunningError`/`TaskAlreadyCompletedError`,
caught and treated as "not fatal, cycle continues" by §9.2 — never a `FAILED` transition). §8.2
explicitly re-derives why this is race-safe under real Postgres row-locking, reusing (not
reinventing) `services/triage_orchestrator.py::_claim_new_event()`'s already-shipped pattern.
`CONTENT_GENERATION` compatibility is proven by the full, unmodified `tests/test_workflow_
runner.py` suite continuing to pass (§19, §22). No unresolved ORM decision — MINOR-1's
`# type: ignore[attr-defined]` precision is precedented and exact (§8.1). **PASS.**

**Gate 7**: independently re-read `tests/test_triage_orchestrator_claims.py:149-156` this session
— the exact precedent the Plan's own §19/§20 cite for its new atomic-claim concurrency test. It
uses a plain `await asyncio.gather(_attempt(), _attempt())` against two independent sessions, real
Postgres, the same test-owned row, with **no explicit barrier or semaphore**, asserting
`sorted(results) == [False, True]` (exactly one True) plus a follow-up query confirming the row's
final state. This is an already-shipped, currently-passing test in this exact codebase — direct
proof that this technique is sufficient in practice, not merely asserted to be. The reason no
artificial barrier is needed: the invariant under test ("exactly one wins, the loser is rejected
before doing anything else") holds under real Postgres row-level locking *regardless of which
coroutine the OS/event-loop happens to schedule first* — determinism of the *outcome invariant*
does not require determinism of *which side wins*. `run()`'s own first statement,
`await session.get(EditorialTask, task_id)` (line 111), is itself an await point, so
`asyncio.gather()`'s natural cooperative interleaving already produces genuine overlapping access
from two separate DB connections by the time either reaches its own atomic `UPDATE` — no
implementation invention is required; the Plan directs the implementer to an exact, working,
already-proven template to copy, exactly as §7.1 does for `EngagementCapability` itself
("mirrors `intelligence_capability.py`"). **PASS — not a MAJOR gap; the "controlled
synchronization" Gate 7 asks for is provided by real Postgres locking, not by artificial Python
scheduling control, and this is independently verified against a real, currently-shipped
precedent, not merely asserted.**

## 6. Eligibility / Backlog Gate (Gate 8, Gate 9)

**Gate 8**: re-confirmed via direct grep this session — `.as_string()` remains the sole live
syntax in §9.1's actual query code (`EditorialTask.workflow["workflow_name"].as_string() ==
WorkflowType.NEWS_ANALYSIS.value`); `.astext`/`cast(..., String)` appear only inside the retired
RED-proof narrative. `status == CREATED`, the workflow-name match, `COALESCE(published_at,
collected_at) >= cutoff`, `ORDER BY created_at ASC, id ASC`, and `LIMIT settings.news_analysis_
batch_size` are all present in the one, single, SQL-side query — no Python-side scan, no
unfiltered fallback query exists anywhere in §9.1/§9.2. No prior empirical finding here has
regressed (unchanged since the Test-Scope Final Re-Audit's own last confirmation; this section of
the Plan was untouched by Correction Pass 3). **PASS.**

**Gate 9**: no catch-up mode, no all-CREATED fallback, no stale-task mutation, and no
freshness-bypassing startup sweep exist anywhere in §9.1/§9.2/§10.1 — the single eligibility query
is the only selection mechanism, and it is unconditionally freshness-bounded. Historical backlog
(4723 total `NEWS_ANALYSIS` tasks, of which several hundred are currently fresh-eligible per the
Final Re-Audit's own read-only diagnostic) becomes processable only once `news_analysis_enabled`
is manually flipped to `true` and the poll loop runs — never automatically or retroactively. **PASS.**

## 7. Worker / Runtime Gate (Gate 11, Gate 12, Gate 15)

**Gate 11**: `news_analysis_enabled: bool = False` (§10.2) — disabled by default, re-confirmed.
§10.1's `main()` checks this flag before entering `_run_enabled_loop()`; when disabled, it awaits
`asyncio.Event().wait()` forever (never polls, never queries, never processes) and remains
cancellation-safe (`except asyncio.CancelledError: ... raise`, mirroring `worker/main.py`'s own
already-proven Phase 12 pattern exactly). §10.1's own text explicitly notes the AI integration
layer (`assemble_ai_integration_layer()`, which does perform Redis/provider initialization) is
constructed once, unconditionally, at startup, *before* the enabled/disabled branch — meaning
disabled mode does **not** avoid this one-time boot cost, but it also performs no live provider
call at boot (assembly ≠ invocation) and never queries/claims/processes any task while disabled.
This matches Phase 12's own already-shipped worker startup shape exactly (not a new pattern). No
restart loop is introduced. **PASS**, with a note that "no unnecessary live provider
initialization" (as the gate's own optional check phrases it) is satisfied in the
no-live-call sense but not in the zero-boot-cost sense — the Plan does not claim otherwise, and
this matches the already-shipped Phase 12 precedent, so it is not a new gap.

**Gate 12**: independently re-read `Dockerfile` and `pyproject.toml` this session (not trusted
from the Plan's own §4 claim). `Dockerfile:8`, `COPY . .`, copies the entire repository tree
(including `prompts/`) into the image — `prompts/engagement/v1.yaml` requires no Dockerfile
change, confirmed directly, not inferred. `pyproject.toml:36`, `packages = [..., "capabilities",
..., "worker"]` — both `capabilities` and `worker` are already-listed top-level packages; a new
`.py` file added under either directory (`capabilities/engagement_capability.py`, `worker/
analysis_main.py`, `worker/analysis_cycle.py`) is automatically included by standard setuptools
package-directory semantics, requiring no `pyproject.toml` edit — confirmed directly. Redis and
Postgres `depends_on` entries are both present in §10.3's planned `docker-compose.yml` service
addition, re-confirmed. **No hidden 20th file. PASS.**

**Gate 15**: §10.3's "Mandatory Docker validation safety rule" and §24's repeated restatement both
explicitly prohibit plain `docker compose config` and mandate `--quiet`/`--services` only,
re-citing the real Phase 12 M3 incident by name. Unchanged by any correction pass. **PASS.**

## 8. Test / Cleanup Gate (Gate 13)

Re-derived the exact set of row types Phase 13's own M5 test (§11) could commit: test-owned
`NewsSource`, `NewsEvent`, `EditorialTask` — explicitly enumerated in §11's own text, mirroring
Phase 12's already-proven `tests/test_automation_integration.py` fixture pattern (unique-name
markers, FK-safe `try/finally`, no rollback-only isolation, no table-wide delete — all restated in
§20).

**`AIExecution` cleanup, independently checked this session (not previously verified in any prior
audit pass)**: `database/models/ai_execution.py` confirms an `ai_executions` table exists, but
`capabilities/gateway_call.py` (the shared `call_generate()` helper every Capability, including
`EngagementCapability`, routes through) contains no reference to `AIExecution` — and the existing,
currently-passing `tests/test_phase9_research_intelligence_integration.py`, which already exercises
real Research/Intelligence capability calls through `FakeLLMGateway` via this exact same
`call_generate()` path, contains zero references to `AIExecution` or any need to clean one up. This
confirms the `FakeLLMGateway`-backed test tier (which is what M0-M6's entire test suite uses,
including M5) does not write `ai_executions` rows at all — this table is written elsewhere (a
cost-tracking/routing-layer concern, consistent with the Decision Resolution's own separately-
documented finding that `CostTracker.record()` is never called in production), not by the
Capability-execution path this Plan's own tests exercise. §11's own cleanup enumeration is
therefore complete as written; no omission. **PASS.**

## 9. M6 Regression Gate (Gate 10, Gate 14)

**Gate 10**: batch cap 5 (`LIMIT settings.news_analysis_batch_size`, §9.1), sequential execution
(no `asyncio.gather` in §9.2's `for` loop, explicit), no refill after a lost claim/failure (§9.2's
own "exactly the originally-selected candidates are attempted — never more" clause), per-task
failure vs. cycle-level infrastructure failure explicitly distinguished with no ambiguity (§18's
dedicated subsection, resolving MINOR-2), no automatic `FAILED` retry (§18's closing line, plus
the eligibility query's own `status == CREATED` exclusion), no automatic stale-`RUNNING` recovery
(§18's own row, Contract §16, explicitly accepted, monitored manually). **PASS.**

**Gate 14**: §12's M6 gate, re-read this session, explicitly runs three **focused** regressions —
`tests/test_phase9_research_intelligence_integration.py`, `tests/test_phase10_capability_
registration.py`, `tests/test_phase9_cross_cutting_regression.py` — each as its own named `pytest`
invocation, *before* the full-suite step, with an explicit statement that M6 cannot pass while any
is red even if the full suite happens to pass. The full-suite step (item 1) explicitly states it
"includes, and does not merely subsume" the three focused runs. `EngagementCapability`,
`CapabilityRegistry`, strict-schema compliance, and the analysis cycle/worker/settings tests are
all covered by the full-suite run and by their own per-file entries in §19's Test Plan; the atomic
claim/concurrency test is covered by the full, unmodified `tests/test_workflow_runner.py` re-run
(§19/§22). Items 2-9 of §12 (ruff, targeted mypy, architecture validator, migration audit, git
scope audit, DB pollution audit, `CONTENT_GENERATION`-boundary grep) are all present and unchanged.
No known currently-passing test is left unaccounted for by this gate structure. **PASS.**

## 10. M7 Hard-Stop Verification (Gate 16, Gate 17)

**Gate 16**: §13's "STOP Gate Before Live Validation" is unconditional and unchanged by any
correction pass — M0-M6 contains zero live LLM/API execution anywhere (`FakeLLMGateway` is the
only gateway used in every automated test, re-confirmed via §19's own table, "No live OpenAI call
anywhere in the automated suite," §19's closing line). §14/§25 both independently restate "M7
always requires explicit, separate human authorization — no exception, regardless of how green
M0-M6 are." The 1153/1139-fresh-eligible-task backlog reality is explicitly cited as the reason
the normal batch worker must not be started for M7 (§14) — and since the normal worker is likewise
never started anywhere in M0-M6 (only constructed and tested with a fake gateway), this same
protection trivially extends to the whole M0-M6 phase: no path in M0-M6 processes any of the 1153+
tasks with a real provider. **PASS.**

**Gate 17**: §14's corrected procedure (Correction Pass 1, unmodified since) does not use the
normal batch worker's eligibility-query selection for M7 at all — it directly invokes the
already-authorized `WorkflowRunner.run(session, task_id)` (confirmed exact-task-capable by direct
signature inspection in the Final Re-Audit's own Check 6, re-cited here, not re-derived) against
one pre-recorded, human-verified `task_id`, records `NewsEvent` id/freshness/status before any live
call, and verifies only that one task's `CREATED→RUNNING→COMPLETED/FAILED` transition afterward.
No new CLI/API/product entry point is introduced (§14's own explicit "no new production file,
script, or CLI is introduced" clause, re-confirmed present). This gate checks completeness only —
M7 was not executed, and no live call was made, in producing this audit. **PASS.**

## 11. Architecture Boundary Verification (Gate 18, Gate 19, Gate 20)

**Gate 18**: §3's Implementation Boundary diagram terminates at "`NEWS_ANALYSIS COMPLETED / FAILED`
→ STOP," restated at §3's closing line ("No automatic `CONTENT_GENERATION`. No `ContentDraft`. No
migration.") and proven three ways at §22 (mechanical grep, zero-rows DB assertion, full
unmodified `test_workflow_runner.py` suite). No Telegram delivery, image discovery, or publication
logic appears anywhere in the Plan's file scope (§4) — none of these systems' files are touched.
**PASS.**

**Gate 19**: no `alembic/versions/` file appears in §4's file scope; §12 item 6 explicitly audits
for this ("no new file under `alembic/versions/`... re-confirmed unchanged"); `EngagementCapability`
persists its output through the pre-existing, generic `EditorialTask.workflow` JSON column (no new
column, no new table, no enum change) — the same mechanism every other existing Capability already
uses. No engagement metric (real Telegram/HN views, forwards, reactions) is persisted anywhere —
`EngagementCapability`'s own docstring (§7.1) explicitly disclaims this, and Discovery §7's own
finding (no such metric is available or persisted anywhere in this codebase) remains unchanged.
**PASS.**

**Gate 20**: the Plan's own §25 "Autonomous Stop Rules" section, re-read this session,
already states rules materially identical to this gate's own list: STOP on a Contract/source
contradiction, a required migration, an unproven concurrency claim, a `test_workflow_runner.py`
regression, a secret exposure, a file outside §4's exhaustive scope, a pre-existing unrelated
defect (escalate, don't fix), or any step requiring a live API call before M7. No conflict found
between this gate's own stop conditions and §25's existing text — they describe the same
boundaries in different words. **PASS.**

## 12. Findings

### CRITICAL

None.

### MAJOR

None.

### MINOR

None new. (All prior MINOR findings — F4, F5 — remain resolved, re-confirmed in §5/§9 above.)

### OBSERVATIONS

**FG-O1**: Gate 11's own optional sub-check ("disabled mode should not unnecessarily perform live
provider/Redis initialization if Plan freezes otherwise") is not fully satisfied in the strictest
possible reading — `assemble_ai_integration_layer()` is constructed unconditionally at startup
even when `news_analysis_enabled=False`, per §10.1's own explicit design note. This exactly mirrors
Phase 12's own already-shipped `worker/main.py` startup shape (not a new pattern introduced by
Phase 13), performs no live provider *call* (only assembly/wiring), and the Plan does not claim
otherwise. Non-blocking; recorded for completeness since Gate 11 explicitly asked the question.

**FG-O2**: this is the fourth consecutive audit pass in this chain (Implementation Plan Audit →
Final Re-Audit → Test-Scope Final Re-Audit → this Gate Audit) and the first to find zero new
MAJOR findings. Given the pattern of the prior three passes (each correction fixing one issue
occasionally surfacing exactly one new, adjacent, second-order issue), this session performed one
additional targeted search specifically for a *third-order* effect of the TS-1 fix (e.g., another
meta-test that might itself reference `test_phase9_cross_cutting_regression.py`'s own test names)
and found none — no file anywhere in the repository references
`test_no_phase9_test_pairs_real_news_analysis_with_completed_status` by name outside its own file.
Recorded as a closure note, not a finding: the chain is verified terminated at this depth.

## 13. Readiness Score

**9/10.** All 20 gates pass on independently re-verified evidence, including three previously
unexamined areas (Docker/packaging via direct `Dockerfile`/`pyproject.toml` inspection, the
concurrency test's real determinism mechanism via direct inspection of its already-shipped
precedent, and `AIExecution`-cleanup applicability via direct source tracing). The score is held
at 9 rather than 10 only because of FG-O1 — a fully-correct-per-precedent but not maximally-tight
disabled-mode boot behavior — which is explicitly a carried-over, pre-existing pattern from
Phase 12, not a defect this Plan introduces, and does not itself block implementation.

## 14. Final Verdict

**Git status** (`git status --short`, read-only, run this session): only untracked, pre-existing
Phase 9/9.5/10/11 governance-backlog files and the full untracked Phase 13 governance chain
(Discovery, Decision Resolution, Architecture Contract, Contract Audit, Implementation Plan, and
all four Implementation Plan audits including this new gate-audit file) appear. No source file,
test file, or migration is modified. Nothing staged. Nothing committed.

PHASE 13 IMPLEMENTATION PLAN APPROVED — READINESS SCORE: 9/10
