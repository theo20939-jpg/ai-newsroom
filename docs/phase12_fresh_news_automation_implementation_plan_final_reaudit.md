# Phase 12 — Fresh News Automation Implementation Plan Final Targeted Re-Audit

Final targeted re-audit only. No Plan, Contract, source, test, or migration file was modified to
produce this document. Every claim below was independently re-verified against current source this
session, not trusted from the Revision Report or the corrected Plan's own prose.

## 1. Executive Verdict

**The one MAJOR finding and both MINOR findings from the prior Planning Audit are genuinely
resolved — the correct architecture/decision is now frozen in every case.** However, direct
re-verification of the corrected Plan's own new illustrative code and flow diagram (§6.3/§12) against
the actual, real signatures of `independent_session_factory()` and `_load_active_sources()` surfaces
**two new, previously-unexamined precision defects in the correction itself**: (1) the Plan's
pseudocode calls `session_factory=independent_session_factory()` directly four times, but
`independent_session_factory()` returns a **2-tuple** `(engine, session_factory)`, not the factory
alone — passing the tuple where a callable is required would raise `TypeError` at first execution;
(2) the Plan's M4 flow diagram never explicitly states that a **real `NewsSource` database row must
be inserted directly** (via the session factory, independent of the fake `source_pack_loader`) before
`run_collection_cycle()` is called, since `_load_active_sources()` queries `NewsSource` directly from
the database and is not informed by `source_pack_loader()`'s return value at all. Both defects are
narrow, self-evidently fixable by mirroring the exact pattern already proven in
`tests/test_triage_orchestrator_cycle.py`/`real_committed_event()`, and both fail **loudly** at
implementation time (a `TypeError` in the first case, an assertion mismatch on `events_created == 0`
in the second) rather than silently corrupting data or misleading an implementer past the point of
easy correction. Neither reopens the underlying architectural decision (which helper to use, which
rows to track/clean up) — both are classified MINOR. No CRITICAL or MAJOR issue was found. No scope
drift, no reopened prior decision, no violation of the frozen Phase 12 boundary.

## 2. Audit Scope

This audit re-verifies only the three items the correction pass targeted (shared-Postgres isolation
strategy, Windows signal wording, R9 escalation wording), confirms no regression elsewhere, and
performs one final, independent trace of the corrected M4 flow against real source — which is where
the two new MINOR findings originate. Unrelated, already-approved Plan content (milestone order,
collector DI design, worker cycle/cancellation/disabled-mode design, Docker/packaging, DoD mapping)
was spot-checked for regression only, not re-derived from scratch.

## 3. Real Postgres/Test Infrastructure Verification

Independently re-read `tests/conftest.py`, `tests/test_triage_orchestrator_claims.py`,
`tests/test_triage_orchestrator_cycle.py`, `database/session.py`, `core/config.py` directly this
session:
- `database/session.py:8-14` — the production `engine`/`async_session_factory` are built from
  `settings.database_url` at module import time.
- `tests/conftest.py:33` — `_test_engine = create_async_engine(settings.database_url,
  poolclass=NullPool)` — the **same** connection string.
- `tests/test_triage_orchestrator_claims.py:41` — `independent_session_factory()`'s own engine —
  again `create_async_engine(settings.database_url, poolclass=NullPool)`.

**No separate test database exists anywhere in this repository's actual configuration.** The
corrected Plan's §12.0 states this accurately and explicitly ("This repository has no separate test
database... it is `settings.database_url`, the same connection string the real application... uses")
— re-confirmed true, not an overclaim in the other direction either. **Check 1 passes.**

## 4. Session Factory Compatibility

- `independent_session_factory()` (`tests/test_triage_orchestrator_claims.py:38-42`) is defined
  exactly where the Plan cites it, returns `tuple[AsyncEngine, async_sessionmaker[AsyncSession]]`,
  and `tests/test_triage_orchestrator_cycle.py:35-39,53-60` already proves the second element is
  directly consumable by `run_triage_cycle(session_factory=factory)` — the sibling function to
  `run_collection_cycle`, with an identically-typed parameter. **Check 2's core question (can the
  named helper actually be reused as intended) passes** — the helper and the underlying decision are
  correct.
- **However**, the corrected Plan's own illustrative code does not correctly consume this return
  value — see Finding P-1 (§13) below. This is a defect in the Plan's *illustration* of the decision,
  not in the decision itself.
- `tests/__init__.py` does not exist (confirmed via directory glob) — yet
  `tests/test_triage_orchestrator_cycle.py` already does `from tests.test_triage_orchestrator_claims
  import (independent_session_factory, real_committed_event)` **today, in already-existing,
  presumably-passing code** — proving this repository's pytest configuration supports
  cross-test-module imports via implicit namespace packages (PEP 420), with no `tests/__init__.py`
  required. **Check 3 passes**: the Plan's import strategy is not brittle — it is already
  operational, proven by existing code, not merely asserted.

## 5. Test-Owned Data Isolation

- Uniqueness (`NewsSource.name = f"phase12-integration-test-{uuid4()}"`, prefixed `external_id`s)
  re-confirmed structurally collision-proof: `_compute_hash(source_id, external_id)`
  (`services/collector.py:173-179`) hashes the newly-generated, guaranteed-unique `NewsSource.id`
  together with the external id — collision with real production data is not merely unlikely, it is
  structurally impossible regardless of the external-id prefix chosen.
- The dedup proof's reuse of the identical `external_id` across poll 1/poll 2 is correctly required,
  not incidental — re-confirmed against `services/deduplication.py`'s exact-hash keying.
- No unrelated dev row can be selected/deleted: every cleanup/pollution-check query the Plan
  describes is scoped to the test-run's own generated unique name/ids, never a table-wide predicate.

**Check 5 passes. No finding.**

## 6. FK Cleanup Verification

Independently re-read `database/models/news_event.py`, `database/models/editorial_task.py`,
`database/models/news_source.py`, and grepped `services/collector.py`/`services/triage_orchestrator
.py`/`services/workflow_service.py` for every `session.add(...)` call:
- `services/collector.py:164` — `session.add(event)` — the **only** row `run_collection_cycle()`
  ever adds is a `NewsEvent`.
- `services/workflow_service.py:70` — `session.add(task)` — the **only** row `create_task()`
  (reached via `run_triage_cycle()`) ever adds is an `EditorialTask`.
- No `ContentDraft`, `AIExecution`, or any other model is written by either function — **independently
  ruled out from source, not merely asserted from the Plan's own claim.**
- FK chain re-confirmed: `EditorialTask.event_id → ForeignKey("news_events.id")`,
  `NewsEvent.source_id → ForeignKey("sources.id")` (`NewsSource.__tablename__ == "sources"`). The
  Plan's frozen cleanup order (`EditorialTask` → `NewsEvent` → `NewsSource`) is the correct,
  complete, children-first order — no additional dependent table exists that this test path could
  populate and the Plan's cleanup would miss.

**Check 6 passes — no missing FK-blocked table. No MAJOR.** (The one related gap found this session —
that the Plan never states a `NewsSource` row must itself be explicitly inserted — is a *completeness*
issue in the flow narrative, not a *cleanup-order* defect; the frozen cleanup order already correctly
includes `NewsSource` as the final row to delete. See Finding P-2, §13.)

## 7. Failure-Safe Cleanup

Re-read §12.0's "Failure-safe cleanup, mandatory" paragraph: requires `try/finally` (or equivalent
guaranteed pytest fixture teardown), explicitly states cleanup must run regardless of which
assertion (collection, persistence, triage, dedup) fails, and explicitly forbids conditioning
cleanup on prior assertions having passed. This directly satisfies all four scenarios the audit
brief names. **Check 7 passes. No finding.**

## 8. Offline Integration Feasibility

Reconstructed the full frozen flow (§12.1) against real source, independently:
1. Insert a real, uniquely-named `NewsSource` (via the session factory directly — required, see
   Finding P-2).
2. Fake `source_pack_loader`/`adapter_resolver_factory` → real `run_collection_cycle()` →
   `_load_active_sources()` finds the inserted `NewsSource` (query, not `source_pack_loader`-driven)
   → `FakeAdapterRegistry.resolve()` returns the fake adapter unconditionally (re-confirmed: neither
   `_load_active_sources` nor `_process_source` performs any check beyond `registry.resolve(source)
   is not None`) → `FakeSourceAdapter.fetch()` returns canned items with zero network I/O → real
   `_process_item()`/dedup → committed `NewsEvent` rows.
3. Real `run_triage_cycle(session_factory=...)` → committed `EditorialTask(NEWS_ANALYSIS, CREATED)`
   rows.
4. Second poll, same identities → dedup proof.
5. Zero-rows assertions for `AIExecution`/`ContentDraft` — re-confirmed feasible and correctly scoped
   (§6 above).
6. `finally` cleanup, then pollution check.

**Feasible end-to-end against current source**, modulo the two illustrative-code precision fixes
(Findings P-1/P-2) that a competent implementer would need to apply while actually writing runnable
code — neither requires inventing new architecture, both are derivable from source already cited
elsewhere in the same Plan. Network-free, credential-free (beyond the shared `settings.database_url`
every existing test already uses), no `WorkflowRunner`, no `EngagementCapability` execution, no
`CONTENT_GENERATION`, no `ContentDraft`, no public publishing — all independently re-confirmed.

## 9. Pollution Gate Verification

Re-read M5 item 16 (new): requires re-querying `settings.database_url` for the test run's own unique
`NewsSource.name` prefix after the integration test completes, fails the gate if any row remains, and
explicitly requires manual investigation (never a blanket delete) if triggered. Correctly scoped to
test-owned identifiers, never a whole-table emptiness assertion. **Check 9 passes — pollution cannot
silently pass M5.**

## 10. Windows Precision Verification

Re-read the corrected §10.3 code comment and prose in full: the guard now states only that
`NotImplementedError` is caught narrowly (this call only, never a broad `except Exception`/
`BaseException`), that failure to register does not crash the worker, and explicitly disclaims any
guarantee about Windows Ctrl+C/interrupt timing during a long, timer-free await — while correctly
affirming Linux/Docker is the actual, fully-supported, verified-at-M6 production target. **No
overclaim remains. Check 12 passes.**

## 11. R9 Escalation Verification

Re-read the corrected R9 row in full: explicitly splits into (A) a defect caused by M1's own new DI
code — fixed within M1's already-authorized narrow scope, no escalation — and (B) a genuine
pre-existing collector defect outside that scope — STOP, report as a blocker, do not autonomously
broaden scope. No ambiguity remains that could be read as "fix whatever M4 finds." **Check 13
passes.**

## 12. File Scope / Non-Regression

Re-read §3 (Exact File Scope), §4 (Dependency Graph), §16 (Dependency-Ordered Sequence) — all
byte-for-byte unchanged from the version this audit's own predecessor approved of on every point
except the targeted corrections. The corrected DB-isolation strategy requires **no** new file: it
reuses `independent_session_factory()` by import (already-proven cross-module pattern, §4 above), no
new `conftest.py` fixture, no new `tests/fakes/__init__.py` (already exists), no production DB
change. **Check 14/15 pass — no scope drift, no secretly-required unauthorized file.**

## 13. Findings

### CRITICAL

None.

### MAJOR

None.

### MINOR

**P-1 — `independent_session_factory()`'s tuple return value is not unpacked in the Plan's
illustrative code.**
- **PLAN LOCATION**: §6.3 (line ~190), §12.1's flow diagram (lines ~640, ~645), §12.2's prose (line
  ~670) — four occurrences of `session_factory=independent_session_factory()`.
- **SOURCE EVIDENCE**: `tests/test_triage_orchestrator_claims.py:38-42` —
  `independent_session_factory() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]`; the
  callable factory is the **second** element, not the return value itself.
- **PROBLEM**: as written, `session_factory=independent_session_factory()` passes a 2-tuple to a
  parameter that `run_collection_cycle()`/`run_triage_cycle()` invoke as `session_factory()` —
  `tuple` objects are not callable.
- **IMPACT**: fails loudly (`TypeError`) at first actual test execution, not silently — low
  real-world risk, but the Plan's own illustration is not directly runnable as shown, and repeating
  the bare call four times (rather than once, in a fixture) would also create multiple undisposed
  engines if copied literally.
- **REQUIRED CORRECTION** (not performed — audit only): show `engine, session_factory =
  independent_session_factory()` unpacked once (ideally inside a single pytest fixture, `yield
  session_factory`, `await engine.dispose()` at teardown — mirroring
  `tests/test_triage_orchestrator_cycle.py::factory`'s own exact shape), with the **same** resulting
  `session_factory` object passed to both `run_collection_cycle()` and `run_triage_cycle()` calls.

**P-2 — The M4 flow never states that a real `NewsSource` row must be inserted directly.**
- **PLAN LOCATION**: §12.1's flow diagram — "unique test-owned SourceDefinition/NewsSource" is
  written as a single combined bullet, without stating the `NewsSource` half must be a real,
  separately-inserted database row via the session factory.
- **SOURCE EVIDENCE**: `services/collector.py:81-85` (`_load_active_sources`) queries `NewsSource`
  directly from the database (`select(NewsSource).where(NewsSource.active.is_(True))`) — it does not
  consult `source_pack_loader()`'s returned `SourceDefinition` list at all for source enumeration;
  that list only feeds `adapter_resolver_factory(definitions)`, and the Plan's own fake
  `adapter_resolver_factory` (§7) ignores its `definitions` argument entirely.
- **PROBLEM**: an implementer who inserts only a fake `SourceDefinition` (via `source_pack_loader`)
  without also directly inserting a real `NewsSource` row would get zero sources processed.
- **IMPACT**: fails loudly (the Plan's own planned `events_created == 2`/`tasks_created >= 2`
  assertions would read `0`), not silently — but costs an implementer a debugging detour the Plan
  could have prevented by stating it explicitly, exactly as `tests/test_triage_orchestrator_claims
  .py::real_committed_event()` already demonstrates the correct insert-a-`NewsSource`-first pattern.
- **REQUIRED CORRECTION** (not performed — audit only): add one explicit sentence to §12.1 stating
  the test must insert a real `NewsSource(name=..., type=..., active=True)` row via
  `session_factory()` directly (mirroring `real_committed_event()`'s own first step), independent of
  and prior to invoking `run_collection_cycle()` — the fake `source_pack_loader`'s return value
  matters only for satisfying the DI seam's type signature in this particular test, not for source
  enumeration.

### OBSERVATIONS

- Both P-1 and P-2 are defects in the *correction pass's own new illustrative code*, not
  regressions of anything the first Planning Audit already approved — worth noting as a pattern:
  precision corrections that introduce new pseudocode are exactly where a final re-audit earns its
  keep, and this pass caught both before implementation.
- Every one of the three originally-targeted items (shared-Postgres reality, Windows wording, R9
  escalation) is resolved cleanly with no trace of the original imprecision remaining.
- No previously-approved Plan section (milestone order, collector DI design, worker cycle,
  cancellation semantics, disabled mode, config, Docker/packaging, DoD mapping, out-of-scope list)
  shows any regression.

## 14. Readiness Score

**8/10.** Both targeted corrections (shared-Postgres isolation, Windows wording) and the R9
escalation fix are genuinely and precisely resolved. Two new MINOR precision defects were found in
the correction's own illustrative code — both fail loudly at implementation time, both have an
obvious, source-derivable fix, and neither reopens an architectural decision. Given MINOR findings
do not gate approval per this audit's own stated bar (CRITICAL=0, MAJOR=0), and every substantive
architecture/decision question this Plan needed to answer is now answered without requiring a fresh
implementation session to invent anything, the Plan is approved.

## 15. Final Verdict

PHASE 12 IMPLEMENTATION PLAN APPROVED — READINESS SCORE: 8/10
