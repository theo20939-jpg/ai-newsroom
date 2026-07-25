# Phase 9 Implementation Planning — Final Adversarial Audit

**Status: audit document. NOT a specification. NOT binding. AUDIT ONLY** — no modification was made
to `docs/phase9_research_intelligence_planning.md`, the Contract, production code, or any migration.
The Planning document is treated as untrusted; every claim it makes about repository structure,
existing precedent, or safety was independently re-verified this pass by reading the actual source
files (`services/collector.py` in full, `capabilities/executor.py` in full,
`schemas/workflow.py`'s `WorkflowType` enum, `tests/test_capability_boot_wiring_e2e.py`,
`tests/test_phase8_cross_cutting_regression.py`, `.env.example`, `tests/conftest.py`'s fixtures, and
`database/migrations`/`alembic.ini`'s existence), not trusted from the Planning document's own
citations.

---

## 1. Executive Summary

The Plan's overall shape is sound: eight milestones, dependency-correct, contract-traceable, no
scope leakage, no premature workflow-completion claim, no invented architecture. Every specific
repository citation the Plan makes was independently re-checked and found accurate — `create_task()`
has zero other callers, `capability-isolation` genuinely needs no extension, `capability_mapping.py`
needs zero change, `boot.py` needs zero change, the `db_session` fixture genuinely cannot serve
M2's concurrency tests, `.env.example`'s commenting convention is real.

However, this audit found **two genuine MAJOR gaps in transaction/session-boundary specification**
that the Plan's own prose does not resolve, and that are exactly the class of ambiguity capable of
producing an unsafe or Contract-inconsistent implementation:

1. **M3 never specifies when to commit the claim/ownership-acquisition relative to `create_task()`'s
   own internal commit**, and its stated intent to "mirror `services/collector.py`'s per-source
   isolation" — literally read — would commit once per *event* (mirroring collector.py's
   once-per-*source* granularity), which is the wrong granularity: the Contract's own repeated
   phrase "the claim (already committed in step 1)" (§7.5, §7.6) requires the claim to be committed
   **before** Triage/`create_task()` run, not bundled with them.
2. **The `stale_processing_threshold_seconds` config field has no positivity validation specified**,
   despite the Contract explicitly freezing "a staleness guard MUST exist... its existence and
   positivity are not [configuration]" (§22) as architecture-critical — as written, an operator
   setting this to `0` (or a negative value) via environment variable would silently disable the
   entire staleness protection this Contract's last two revision rounds were built around.

Neither finding invalidates the Plan's architecture or milestone sequencing — both are precise,
narrow, cheaply-correctable additions to M3's and M2's own text, not a redesign. Three further
MINOR findings and two OBSERVATIONs are recorded below. No CRITICAL finding: the fundamental
concurrency primitives (M2), the Research→Intelligence handoff (verified against real
`capabilities/executor.py` code), and the overall boundary are all sound and implementable as
designed.

---

## 2. Contract Coverage Matrix

Every implementation-relevant MUST/MUST NOT in the Contract, mapped to its primary implementing
milestone and, where relevant, its later integration/regression proof.

| Contract requirement | Primary owner | Integration/regression proof | Gap? |
|---|---|---|---|
| P1 (Triage deterministic, no LLM/registry) | M1 | M0 (validator), M7 (regression) | None |
| P2 (Triage ≠ Final Ranking) | M1 (scope) | — | None (design-level, not independently testable; correctly out-of-scope by omission) |
| P3 (Triage doesn't require Research/Intelligence output) | M1 (function signature excludes them) | — | None |
| P4 (Research/Intelligence = ordinary Phase 8 Capabilities) | M4, M5 | M6, M7 | None |
| P5/P6 (no provider-specific/SDK logic) | M0 (validator, pre-existing `provider-sdk-confinement`) | M4, M5 | None |
| P7 (no second Workflow Engine) | M3 (explicit "out of scope") | — | None |
| P8 (no new DB model/migration) | M2, M3 DoD (`git status` migration check) | M7 (repo-wide `git diff` scope check) | None |
| P9 (no clustering/embeddings/Opportunity Score/EngagementAnalysis/Final Ranking) | M1, M4, M5 (all explicitly exclude) | §16 of this audit (scope-leakage search) | None |
| P10 (frozen `NEWS_ANALYSIS`/`WorkflowRunner`/`WorkflowRegistry` unchanged, **no new `WorkflowType` member**) | M7 (uses a synthetic definition) | — | **MINOR — M7 does not name which existing `WorkflowType` it reuses, nor explicitly restate the "no new enum member" prohibition inline (§11, §18 below)** |
| P11 (no fake `engagement_analysis`/`scoring` registration) | M6 (explicit "out of scope") | M7 (negative test) | None |
| P12 (future-compatible with `EngagementAnalysisCapability`/Final Scoring) | — | — | **OBSERVATION — no milestone explicitly verifies this; satisfied by design (M4/M5 follow Phase 8's own extensible pattern) but not independently tested anywhere** |
| §2.1/§2.2 (Freshness/Triage tables: pure, no DB, no side effects) | M1 | M0 (validator) | None |
| §2.3 (Orchestrator table) | M2 (primitives) + M3 (composition) | — | None (ownership split correct, see §7 of this audit) |
| §3 (deterministic Triage, closed signal list, ordinal mapping) | M1 | — | None |
| §4 (No-Hard-Drop) | M1 (unit), M3 (end-to-end) | M7 | None |
| §5.1 (Freshness invariants 1-7) | M1 | — | None |
| §5.2 (tier boundaries/weights = config) | M1 (§17 Product Configuration) | — | None |
| §6 rule 1/4 (reliability read, null default) | M1 | — | None |
| §6 rule 2/3 (**MUST NOT** compute dynamic/historical authority or derive it from engagement/clustering) | M1 (structurally — Triage takes only a scalar `reliability_score`, has no DB access to compute history) | — | **OBSERVATION — no explicit negative test states this; structurally prevented by M1's no-DB-access design (arguably a stronger guarantee than a test), not a real gap** |
| §7.1 (precedent) | M3 | — | None |
| §7.2 step 1 (atomic claim, both branches) | M2 | M3 | None |
| §7.2 steps 2-3 (Triage call, `create_task()` call, ordering) | M3 | — | **See MAJOR finding 1 (commit timing) — the *ordering* is correctly specified; the *transaction discipline* around it is not** |
| §7.3 (precise responsibility answers) | M2 + M3 | — | None |
| §7.4 (production scheduling deferred) | M3 (explicit "out of scope") | — | None |
| §7.5 (concurrency guarantee, `create_task()` outcome handling, "claim already committed in step 1") | M2 (guarantee) + M3 (outcome handling) | — | **MAJOR finding 1 — the "already committed in step 1" premise is not enforced by any explicit instruction in M3** |
| §7.6 (staleness eligibility, atomic CAS, at-most-one-winner, healthy-worker safety, operational constraint) | M2 | M3 | **MAJOR finding 2 (positivity of the threshold) is adjacent — the *mechanism* is correctly planned; the *configuration guard* around it is not** |
| §8 (`ResearchCapability` full contract) | M4 | M7 | None |
| §9 (`IntelligenceCapability` full contract) | M5 | M7 | None |
| §9.1 (`step_results` mechanism, no direct import) | M5 (consumption) | M7 (real proof) | None — independently re-verified against `capabilities/executor.py` (§13 of this audit) |
| §10 (Research/Intelligence remain distinct, call-cardinality not frozen) | M4, M5 (distinct files/registrations) | — | None |
| §11 (full Phase 8 execution/error-model compliance) | M4, M5 | — | None |
| §12 (registration constraints) | M6 | — | None |
| §13 (workflow compatibility, allowed proofs, real-`NEWS_ANALYSIS`-forbidden) | M7 | — | Same MINOR as P10 above (which `WorkflowType` M7's synthetic proof reuses) |
| §14 (persistence mapping table) | M3 (Triage), M4/M5 (`CapabilityResult`) | — | None |
| §14.1 (crash/restart disclosure, 7 points) | M7 (explicit non-claim) | — | None |
| §15 (Triage-explanation logging, recovery-acquisition logging, Capability observability reuse) | M3 (first two bullets), M4/M5 (reused chain) | M7 | None |
| §16 (full testing-requirements section) | M1, M2, M3, M4, M5 | M7 | None — every listed sub-requirement traced to a specific test in the relevant milestone |
| §17 (forbidden dependency edges) | M0 (Triage/Orchestrator rows) + pre-existing `capability-isolation` (Capability rows) | — | None |
| §18 (failure semantics table) | M2 (claim/recovery-failure rows), M3 (loading/Triage/create_task rows) | — | Same as §7.5 MAJOR finding |
| §19 (extension rules) | — | — | Same OBSERVATION as P12 |
| §20 (non-goals, 19 items) | All milestones' "explicitly out of scope" sections | §16 of this audit | None |
| §21 (15 canonical rules) | Distributed across M1-M7 (traced individually; all 15 map cleanly) | — | None |
| §22 (open/provisional items) | M1 (Freshness/reliability config), M2 (staleness threshold) | §14 of this audit | MAJOR finding 2 |
| §23 (20-item acceptance checklist) | — | M7 (explicit self-audit re-run against implemented code) | None — correctly deferred to M7 as a final check, not re-litigated earlier |

**No load-bearing requirement was found with zero implementation owner.** The two MAJOR findings are
under-specification within an already-correctly-assigned milestone, not missing ownership. No
duplicated ownership was found. No milestone implements behavior the Contract does not require (see
§16 of this audit, Scope Leakage — clean).

---

## 3. Milestone Dependency / Sequencing Audit

Independently re-derived, not merely re-read from the Plan's own §5:

- **M0 → M1/M2**: correct. M0's three new rules apply to file *paths*; the AST scanner
  (`_iter_python_files`) simply finds no matching file before M1/M2 create them — confirmed by
  reading `find_violations()`'s implementation — so M0 has no runtime dependency on M1/M2 existing.
- **M1 ⊥ M2** (mutually independent): confirmed correct. M1 imports nothing from M2; M2 imports
  `NewsEvent`/`EventStatus`/`EditorialTask`/`_find_active_task` — none of which come from M1.
- **M3 needs M1 + M2**: confirmed — M3 is the first point `decide_triage()` (M1) and
  `_claim_new_event`/`_acquire_recovery_ownership`/`_select_recovery_candidates` (M2) are called
  together.
- **M4 ⊥ M1/M2/M3**: confirmed by re-reading `capabilities/scoring_capability.py` and
  `capabilities/quality_capability.py` — neither imports anything from `services/`. `ResearchCapability`
  has the same shape; no functional dependency exists.
- **M5 depends on M4 "by convention only"**: confirmed accurate — re-read §9.1's binding rule (no
  direct import) and `capabilities/capability_mapping.py`; nothing forces M5 to be built after M4
  except the Plan's own choice to mirror Phase 8's one-Capability-at-a-time practice. Correctly
  caveated in the Plan's own text, not overstated.
- **M6 needs M4 + M5**: confirmed — `build_registry()`'s body needs both `CapabilityDefinition`
  objects to import.
- **M7 needs M6**: confirmed — a `CapabilityRegistry.resolve("research"/"intelligence")` call
  (needed for the `RoutingGateway`+`FakeProviderAdapter` variant) requires both to be registered.

**No undeclared dependency found.** The one place a dependency is easy to mis-state — whether M3
also implicitly depends on `capabilities/` existing (it does not; M3's synthetic proof of the claim
mechanism uses `create_task()` only, never a `Capability`) — was checked directly against M3's own
file list and confirmed clean.

---

## 4. M0 Audit

Re-inspected `scripts/validate_architecture.py` in full and re-derived each new rule's necessity
independently, per the seven questions posed.

1. **Boundary enforced**: Freshness/Triage/Orchestrator's §2.5 "Must NOT depend on" columns —
   confirmed these have **no existing validator coverage** (only named-file rules exist today —
   `budget-guard-isolation`, `cost-tracker-isolation`, etc. — none targets a `services/`-prefixed
   file by name yet, since none of today's `services/*.py` files needed this kind of isolation
   rule before).
2. **Already enforced by an existing rule?** No, for all three new rules — independently confirmed
   by re-reading the full `RULES` tuple; `capability-isolation` only applies under `capabilities/`;
   `provider-sdk-confinement` is the one *partial* overlap (it already blocks provider SDK imports
   repo-wide, including in `services/triage_orchestrator.py`) — the Plan's own text acknowledges this
   overlap explicitly ("already covered repo-wide by `provider-sdk-confinement`, but listed here too
   for a same-rule, single-message developer experience") — this is a **deliberate, disclosed,
   minor redundancy for error-message locality**, not an accidental one, and does not violate the
   "don't invent redundant rules" instruction, since the *primary* new coverage (Gateway/Capability
   imports) is genuinely new.
3. **Operates on real package structure?** Yes — `services/freshness.py`, `services/triage.py`,
   `services/triage_orchestrator.py` are exactly the file paths M1/M2/M3 create; `_under()`'s
   string-prefix matching works identically to every existing named-file rule.
4. **False-positive risk against legitimate infrastructure?** Checked directly: the one real risk
   the Plan itself identifies and defuses — `services/triage_orchestrator.py` importing
   `services.workflow_service` and `schemas.workflow` — is correctly **excluded** from the forbidden
   list (confirmed the Plan's own forbidden-prefix list for `triage-orchestrator-isolation` omits
   both). No other false-positive path was found: Freshness/Triage need nothing beyond stdlib +
   `services.freshness`/`database.models.editorial_task.TaskPriority`, both correctly unforbidden.
5. **Exclusion-list precision**: N/A for these three (they are `_under()`, single-file rules, not
   `_under_excluding()` multi-file rules) — correctly the simpler predicate, matching
   `budget-guard-isolation`'s own shape exactly, not over-engineered.
6. **Mechanically enforceable through imports?** Yes for all three — every forbidden dependency
   (`integrations.llm_gateway`, `capabilities.registry`, `capabilities.executor`, `sqlalchemy`,
   `database.session`, `workflows`) is import-based, exactly what the AST scanner checks.
7. **Meaningful protection vs. redundant machinery?** Meaningful — re-confirmed by constructing the
   counterfactual: without M0, nothing in the current toolchain would catch
   `services/triage.py` accidentally importing `integrations.llm_gateway` (an easy mistake if a
   future contributor tries to make Triage "smarter" by calling an LLM directly, exactly the failure
   mode P1 forbids) until a human reviewer noticed in code review. This is real, not symmetry-for-
   symmetry's-sake — the Plan's own summary line ("`capability-isolation` already covers new
   Capability files with zero validator change") is accurate but describes a **different, already-
   solved** problem (Capability isolation) than the one M0 actually solves (Triage/Orchestrator
   isolation, which the Contract's own §17 header explicitly flags as unsolved). **M0 is
   necessary and correctly scoped — not recommended for removal or shrinking.**

One refinement worth naming (not blocking): the `triage-orchestrator-isolation` rule's forbidden
list enumerates four specific `capabilities.*` sub-modules by name
(`capabilities.registry`/`.executor`/`.research_capability`/`.intelligence_capability`) rather than
a single blanket `capabilities.` prefix, even though the Orchestrator has no legitimate need for
*any* `capabilities/` import. A blanket prefix would be simpler, lower-maintenance, and would
automatically catch a hypothetical future Capability file the enumerated list doesn't yet name.
**MINOR** — the enumerated form is not wrong (it matches the granularity of existing rules like
`budget-guard-isolation`, which also enumerates rather than blankets), just slightly more
maintenance-prone than necessary.

---

## 5. M1 Audit

Re-checked the full requirements list against M1's "Implementation scope"/"Tests required":

| Requirement | Covered? |
|---|---|
| Explicit `reference_now` | Yes — `compute_freshness`/`decide_triage` both take it as a required parameter |
| `published_at` fallback to `collected_at` | Yes, flagged in `FreshnessResult` |
| Freshness semantics (tiers, weights) | Yes, module constants |
| `reliability_score` read + null policy | Yes |
| Configurable freshness boundaries/weights | Yes, correctly PRODUCT CONFIGURATION per §17 |
| Configurable priority thresholds | Yes, correctly PRODUCT CONFIGURATION |
| Explicit `S > A > B > C` ordering | Yes — `TASK_PRIORITY_ORDINAL`, with both a positive proof and the documented negative (`S < A` is `False`) test |
| No lexical/native enum comparison | Yes — explicit prohibition restated, testable via the negative test |
| Deterministic output | Yes, explicit determinism test |
| No hard drop | Yes, explicit parametrized test |
| Every valid input → existing `TaskPriority` | Yes |
| Future timestamps | Yes — clamped to zero, no raise |
| Exact-boundary behavior | **Not explicitly listed for M1** — §5.1 rule 4's "negative age clamped to zero" is tested, but M1's own tests list does not separately test an exact-zero-age boundary case (e.g. `published_at == reference_now` exactly) the way M2 explicitly tests the staleness threshold's exact boundary. **MINOR** — a reasonable edge case to add, not a functional gap (zero age is well-defined either way: it is simply the freshest tier, no ambiguity exists the way there was for the strict-inequality staleness threshold). |
| Timezone behavior | Yes — naive input raises `ValueError` |

**No requirement deferred to M3.** Cross-checked directly: M3's own "Implementation scope" only
*calls* `decide_triage()`; it implements none of the above itself.

**Import boundary check** (re-verified against M0's proposed `triage-purity`/`freshness-purity`
rules, not just described): `services/freshness.py` imports nothing beyond the stdlib per the Plan's
own text — correct, zero DB/Gateway/Capability import. `services/triage.py` imports
`services.freshness` + `database.models.editorial_task.TaskPriority` only — correct, no DB session,
no `WorkflowService`, no `LLMGateway`, no Capability layer, no provider SDK. Confirmed clean against
every item the audit instructions ask to check.

One combined-score/threshold detail is deliberately left unspecified (no literal weight numbers or
cutoff values are given anywhere in the Plan) — this is **correct, not a gap**: Contract §5.2/§22
explicitly classify these exact values as PRODUCT CONFIGURATION, not something the Contract (or a
plan built to implement it) is meant to freeze. Flagging this as a defect would contradict the
Contract's own delegation.

---

## 6. M2 Audit

This is the highest-scrutiny milestone, audited transaction boundary by transaction boundary.

**Primitives vs. orchestration policy**: confirmed M2 implements *only* the three atomic functions
(`_claim_new_event`, `_select_recovery_candidates`, `_acquire_recovery_ownership`) with no Triage
call, no `create_task()` call, no script entry point — clean separation, matching the Plan's own
stated goal.

**Concurrency evidence, checked against the eleven specific items requested**:

| Required evidence | Present in M2's test list? |
|---|---|
| Two independent sessions/connections competing for `NEW` | Yes, explicit |
| Exactly one normal claimant wins | Yes |
| Two independent sessions competing for the same stale `PROCESSING` event | Yes, explicit |
| Exactly one recovery claimant wins | Yes |
| Stale CAS loser cannot proceed | Yes ("loser never proceeds") |
| `updated_at` CAS semantics against real DB behavior | Yes — and independently re-verifiable: this exact mechanism was empirically proven against the real dev Postgres database during the Contract's own drafting (a disposable script, deleted afterward, per `docs/phase9_research_intelligence_architecture_contract.md` §7.6's own citation) — M2's planned tests are a *codified, permanent* version of that one-off proof, not a new, unverified claim |
| Active task blocks recovery | Yes |
| Fresh `PROCESSING` cannot recover | Yes |
| Exact threshold cannot recover | Yes, explicitly constructed (not approximated) |
| Future `updated_at` cannot recover | Yes |
| Two independent sessions, not sequential simulation | Yes — the Plan explicitly rejects the shared, single-connection `db_session` fixture for exactly this reason, correctly citing why (SAVEPOINT-mode sharing one physical connection cannot model two genuinely concurrent transactions) |

**Transaction boundaries — the one area requiring correction**: M2 itself is precise and correct —
"Commits are the caller's responsibility (M3)" is explicitly, correctly stated, and each of M2's own
*tests* commits explicitly per attempt (confirmed: "row's `status` is `PROCESSING` **after commit**"
appears in M2's own positive-test description). **The gap is not in M2 — it is that M2 correctly
defers the commit decision to M3, and M3 never actually makes that decision explicit** (see §8 of
this audit, MAJOR finding 1).

**API ergonomics** (the specific "does the API make it easy to ignore rowcount/ownership outcome"
question): `_claim_new_event`/`_acquire_recovery_ownership` return a plain `bool`, which a careless
future caller could technically ignore. This is **not flagged as a defect**: the Contract's own
framing explicitly treats a lost race as "not an error" (§18), so a boolean return is the *more*
Contract-faithful design than an exception would be (an exception implies an error condition, which
this explicitly is not) — using `bool` return values here, combined with M3's own described
"attempts the matching M2 primitive... on a lost race (`False`), skip silently" handling, is correct
and appropriately matches the Contract's own semantic classification. **OBSERVATION only.**

---

## 7. M2/M3 Boundary Audit

Ownership, checked item by item, against §2.3/§7 of the Contract and the Plan's own file
assignments:

| Responsibility | Sole owner | Duplicated anywhere? |
|---|---|---|
| Querying `NEW`/stale candidates | M2 (`_select_recovery_candidates` + a `NEW`-status query M3 composes) | No |
| Atomic claim | M2 (`_claim_new_event`) | No |
| Stale-eligibility calculation | M2 (embedded in `_select_recovery_candidates`'s filter) | No |
| Active-task lookup | M2, via the reused, unmodified `_find_active_task()` — never reimplemented | No |
| Recovery CAS | M2 (`_acquire_recovery_ownership`) | No |
| Triage calculation | M1 (`decide_triage`), called by M3 | No |
| `create_task()` | `services/workflow_service.py` (frozen, Phase 5), called by M3 | No |
| Status semantics | `EventStatus` enum (frozen), transitioned only by M2's primitives, called by M3 | No |
| **Commit/rollback** | **Ambiguous** — M2 explicitly declines ownership ("caller's responsibility"); M3's text describes call *ordering* but never states *when* to commit or that a `session.rollback()` call is required on the "any other exception" path | **See MAJOR finding 1, immediately below** |

**MAJOR FINDING 1 — commit/rollback discipline is the one responsibility this Plan does not
unambiguously assign, and the ambiguity is safety-relevant, not stylistic.**

Traced mechanically against the real `services/collector.py` (re-read in full this pass, not
assumed): collector.py commits **once per source**, after that source's *entire* item loop
completes (`await session.commit()` at the end of `_process_source()`), and calls
**`await session.rollback()`** explicitly in the per-source `except Exception` handler before
continuing to the next source. M3's own text says it "mirrors `services/collector.py`'s own
per-source try/except isolation" for its per-event failure handling — but never states the
**per-*claim*** commit collector.py's own pattern would imply if mirrored at the correct
granularity, and never mentions the `session.rollback()` call at all.

Why this matters concretely: `services/workflow_service.py::create_task()` (re-read in full this
pass) commits internally **only on its own success path** (line 71). If `create_task()` raises
before reaching that line (a `DuplicateActiveTaskError`, or any other exception), and M3's own
per-event step 1 claim/CAS was never independently committed, then:
- If M3's loop shares one session across the whole batch (the `session_factory` parameter's
  signature suggests exactly this, mirroring collector.py's single-`async with`-block shape) and
  does not commit after step 1, the still-uncommitted claim sits inside the session's open
  transaction. A later event's `create_task()` success would then commit **that earlier event's
  claim too**, as an accidental side effect of an unrelated event's success (both are in the same
  transaction) — or, if no later event ever succeeds, the earlier claim is silently discarded when
  the `async with` block exits without commit, never having existed durably at all.
- If M3's exception handler does not call `session.rollback()` before continuing (mirroring
  collector.py's actual line, not just its "isolation" framing), a genuine SQL-level failure would
  leave the session in Postgres's `InFailedSqlTransaction` state, and **every subsequent event in
  the same batch would then fail too** — a direct, mechanical contradiction of the Contract's own
  batch-isolation requirement (§18: "other events in the same batch are unaffected") and of M3's own
  planned "Batch isolation" test, which could not actually pass under this reading.
- Separately, the Contract's own repeated phrase — "the claim (**already committed** in step 1)"
  (§7.5), and §7.6's residual-state reasoning, which depends on the claim being a durable fact
  independent of what happens in steps 2-4 — is only true if step 1's commit happens **before**
  step 2 begins. M3's planned tests (e.g. "any other exception → ... event left `PROCESSING`")
  **require** this specific behavior to be observable, but nothing in M3's text instructs an
  implementer to produce it.

**Required correction** (small, precise, not a redesign): M3's "Implementation scope" must state
explicitly: (a) `await session.commit()` immediately after a successful claim/CAS (step 1), before
Triage or `create_task()` runs for that event; (b) `await session.rollback()` in the "any other
exception" branch, before the loop continues to the next event — mirroring `services/collector.py`'s
actual `_process_source()`/outer-`except`-handler pattern **at the per-claim granularity**, not the
per-event-batch granularity the Plan's prose currently implies by analogy alone.

---

## 8. M3 Audit

Mechanically traced both paths against the corrected (per §7 above) transaction model.

**Normal path**: candidate (`NEW`) → claim (commit immediately, per the required correction) →
Triage (pure, in-memory) → `create_task()` (its own internal commit on success) → resulting state
`PROCESSING` + `CREATED` task. Correct once §7's correction is applied.

**Recovery path**: candidate (stale `PROCESSING`, no active task, past threshold) → active-task
re-check (embedded in `_select_recovery_candidates`, and again, structurally, inside
`create_task()`'s own `_find_active_task()` call) → staleness (embedded in the same selection query)
→ recovery-ownership CAS (commit immediately, same correction) → Triage → `create_task()`
reconciliation → resulting state.

**Partial-failure matrix, checked against the seven states the audit specifies**:

| State | Plan's handling | Verdict |
|---|---|---|
| A. Claim loses (rowcount 0) | Skip silently, no error, no commit needed (nothing changed) | Correct |
| B. Source-loading fails | Falls under "any other exception" — event left `PROCESSING`, no task, recoverable once stale | Correct **once the rollback correction (§7) is applied** — without it, this could cascade into subsequent events' processing |
| C. Triage fails | Explicitly noted as structurally impossible for well-formed input (§2.1/§2.2's own "MUST NOT raise" contract) — if it somehow did, same handling as B | Correct |
| D. `create_task()` fails (non-duplicate) | Same as B | Correct **once corrected** |
| E. `DuplicateActiveTaskError` | Explicitly handled — "not a failure," logged at `info`, loop continues | Correct |
| F. Crash after claim, before task creation | This is precisely the residual state §7.6/§7.5 describe — **only reachable as described if the claim was independently committed (§7's finding)**; otherwise a process crash mid-transaction would simply lose the uncommitted claim entirely (arguably *safer*, but not what the Contract's text, or M3's own planned tests, describe) | **Depends on the §7 correction** |
| G. Rerun after residual `PROCESSING` | Handled by the staleness-gated recovery path, M2+M3 composed | Correct |

**Primary concurrency guard**: confirmed the Plan does **not** rely on `create_task()`'s own
`DuplicateActiveTaskError` check as the primary guard — `NewsEvent` ownership (the claim/CAS) is
explicitly primary throughout M2/M3's text, and M3's §7.5 outcome-handling correctly frames
`DuplicateActiveTaskError` as secondary/self-healing. **Confirmed correct, matching the Contract's
own §7.5 "Explicit distinction, binding" framing exactly.**

**"All Phase 9 task creation occurs only after successful ownership acquisition"**: confirmed
**explicit** in M3's step ordering (step 1 must succeed before steps 2-3 run) — this requirement is
met. Not flagged.

---

## 9. M4 Audit

Re-checked against `capabilities/scoring_capability.py`'s real, current implementation (not a
description of it).

- `__init__(gateway, prompt_repository)` only — matches exactly.
- `call_generate()` reuse — matches (`ScoringCapability`'s own use of it was re-read as the direct
  template).
- `PromptRepository.resolve()` — matches.
- Structured-output validation floor — the Plan correctly reuses the existing floor concept without
  reimplementing `_floor_validate`-equivalent logic from scratch (implied by "validates the
  structured-output floor" citing §9.1 of the frozen Phase 8 contract, not a new mechanism).
- `CapabilityResult` shape — matches `schemas/capability.py`.
- "Research" scoped correctly to supplied-context analysis only — §8's binding scope clarification
  is restated verbatim in M4's implementation scope, and a dedicated "scope-honesty" test is
  explicitly planned (not merely implied) to guard against silent scope creep toward
  verification/browsing language leaking into the prompt.
- No web browsing, external search, vector DB, embeddings, autonomous agents, direct Source/DB
  access anywhere in M4's implementation or test scope — confirmed clean.
- Output schema (`facts`/`confidence`/`gaps`) is a minimal, direct instantiation of §8's frozen
  conceptual shape — **appropriately sized**: not over-designed (no nested taxonomy, no confidence
  breakdown per fact), and sufficient for M5 to consume (M5's own plan explicitly reads `facts`).

**No finding.**

---

## 10. M5 Audit

- Separate file from Research — confirmed (`capabilities/intelligence_capability.py`).
- No direct import of `ResearchCapability` — confirmed, and **uniquely among all milestones**, M5
  plans a *mechanical*, executable test for this (a static/`ast`-based or plain-text check that the
  import never appears) rather than relying on manual review — this is a stronger guarantee than the
  Contract text alone provides and a genuinely good addition.
- Consumes Research output only through `step_results` — confirmed against the real
  `capabilities/executor.py` (§13 below).
- Adds synthesis beyond Research (significance/angle/audience/recommendation vs. Research's bare
  facts) — confirmed, output shapes are meaningfully distinct.
- Does not become Engagement Analysis or Final Ranking — explicitly excluded in M5's scope.
- Ordinary Phase 8 mechanics — same construction shape as M4, confirmed.

**"Tested BEFORE M6 registration, using realistic Research-shaped context"**: M5's positive test
uses a "populated `step_results["research"]`" fixture. **MINOR finding**: the Plan does not state
that this fixture's shape must be drawn from, or verified against, M4's *actual* `structured_output`
shape — M4's own "Runtime evidence" section anticipates this exact risk ("to confirm the concrete
shape matches what M5 will need to read... a direct, verifiable link to M5's dependency") but the
verification method described is a **manual, printed-output comparison across two separate
milestones**, not an automated, shared fixture or contract test. A shape drift between M4's real
output and M5's test-only assumption would not be caught by either milestone's own test suite — only
by M7's full integration proof, which does exercise both for real. **Not blocking** (M7 closes the
gap at the latest reasonable point), but tightening M5's test to explicitly import/reuse a shared
fixture value (or directly reference M4's `RESEARCH_CAPABILITY_DEFINITION`/output constant) would
close it earlier and more cheaply.

---

## 11. M6 Audit

- `"research"`/`"intelligence"` capability names checked against `workflows/definitions/news_analysis.py`
  (re-read fresh this pass): `WorkflowStepDefinition(name="research", capability="research", ...)`
  and the `"intelligence"` step — both match exactly, confirmed **not** merely asserted.
- No `engagement_analysis` fake registered — confirmed, explicit "out of scope."
- `ScoringCapability`/`QualityCapability` registrations remain intact — M6's diff is additive only
  (two new imports, two new `register()` calls); nothing existing is touched, confirmed against the
  real `capabilities/registry.py`'s current four-line `build_registry()` body.
- No registry redesign, no boot-sequence redesign — confirmed against `integrations/llm_gateway/boot.py`,
  re-read in full: `assemble_ai_integration_layer()`'s call to `build_registry(...)` is already
  generic and needs zero change, exactly as the Plan claims.
- No `NEWS_ANALYSIS == COMPLETED` claim — explicit, checked prohibition in M6's own text, plus a
  planned repo-wide grep review as a concrete verification step (not merely a promise).

**No finding.**

---

## 12. M7 Audit

Verifies the boundary — not more, not less — checked against the exact three sub-lists the audit
requests:

**Triage side**: deterministic policy (M1's own tests, not re-tested here — correctly not
duplicated), priority mapping (same), normal/stale ownership (M2's own tests, not re-tested here —
M7 correctly states it does not repeat M2/M3's concurrency proofs), task creation, rerun safety (M3's
own tests). M7 itself adds no new Triage-side test — **correct**, since M3 already owns this proof
and re-testing it in M7 would be redundant, not additive.

**Capability side**: Research reachable via `CapabilityExecutor` — yes, via the synthetic-workflow
proof. Intelligence reachable via `CapabilityExecutor` — yes, same proof. Realistic Research-shaped
data feeding Intelligence through approved context semantics — yes, and this is the one place M7
**does** independently re-verify the M4→M5 shape link the §10 MINOR finding above flags as otherwise
only manually checked — closing that gap at the latest possible point, as noted there.

**Boundary**: no full `NEWS_ANALYSIS` completion claim (explicit, plus a negative test proving the
real definition still ends `FAILED` at `engagement_analysis`); no `EngagementAnalysisCapability`; no
Final Ranking enhancement; no production scheduler — all confirmed absent from M7's scope.

**Runtime/concurrency evidence vs. unit-test aggregation**: M7's own "Runtime evidence" section
requires the actual `step_results` dict to be printed/observed, not only asserted, and requires a
real, full-repository `pytest`/`ruff`/`mypy` run with output compared against a captured baseline —
this is genuine runtime evidence, not merely more unit tests. **No new concurrency evidence is
added by M7**, which is correct per the Plan's own reasoning (M2/M3 already own that proof) — flagged
here only to confirm this is a deliberate, justified omission, not an oversight.

**One MINOR finding, specific to M7**: the synthetic `WorkflowDefinition`'s `WorkflowType` is never
named. Cross-referenced against the actual precedent, `tests/test_capability_boot_wiring_e2e.py`
(re-read this pass): that existing test reuses the **already-defined** `WorkflowType.CONTENT_GENERATION`
enum member with a *locally constructed* `WorkflowDefinition`/`WorkflowRegistry` (never touching the
real global registry or the real `content_generation.py` definition) — it does **not** invent a new
enum member. `schemas/workflow.py`'s `WorkflowType` also has an unused-for-real-definitions member,
`DAILY_DIGEST` ("never registered in `WorkflowRegistry`... resolving it raises
`UnknownWorkflowTypeError`" per its own docstring — i.e., available and unambiguous for a synthetic
test's local reuse). Contract **P10 explicitly, bindingly forbids "no new `WorkflowType` enum
member"** — this is not a minor style question, it is a specific, named Contract prohibition. M7's
text never states which of the two reusable existing members it will use, nor restates P10's
prohibition inline the way M6 restates §12's "no completion claim" prohibition inline. A fresh
implementer unfamiliar with `test_capability_boot_wiring_e2e.py`'s specific trick could plausibly
add a new member (e.g. a hypothetical `WorkflowType.PHASE9_SYNTHETIC`) to make the synthetic
definition "cleaner," directly violating P10. **MINOR** (not MAJOR): the precedent is real, findable,
and already used elsewhere in this exact codebase, and P10 itself is unambiguous and already stated
in the Contract — but the Plan should have closed this specific loophole explicitly, the way it did
for other similarly-tempting shortcuts (M6's inline restatement of "no completion claim" is the
model to follow here too).

---

## 13. Research → Intelligence Handoff Audit

Traced against `schemas/capability.py`, `capabilities/executor.py`, and `workflows/runner.py`
directly (all re-read in full this pass, not assumed from either the Plan or the Contract).

1. **Exact field carrying prior Research output**: `CapabilityContext.business.workflow_state.step_results:
   dict[str, dict[str, Any]]` (`schemas/capability.py`'s `WorkflowExecutionStateSnapshot`),
   populated by `CapabilityExecutor._build_context()` from
   `{r.step_name: r.result for r in state.step_results if r.status == "SUCCESS" and r.result is not
   None}` — keyed by the **step's `name`** (not its `capability` field). For `research`/
   `intelligence`, both are declared with `name == capability` in
   `workflows/definitions/news_analysis.py` (`WorkflowStepDefinition(name="research",
   capability="research", ...)`), so `step_results["research"]` is unambiguous either way — **no
   discrepancy found**, but this is worth stating precisely since the two fields are not always
   identical in general (they happen to coincide only because this specific definition chose matching
   names).
2. **Shape Intelligence expects**: `context.business.workflow_state.step_results.get("research", {})`
   — a plain `dict[str, Any]`, matching M4's planned `structured_output` shape
   (`{"facts": [...], "confidence": ..., "gaps": [...]}`) exactly.
3. **Who constructs the context**: `CapabilityExecutor._build_context()`, frozen Phase 6/7/8
   machinery — Phase 9 does not construct it, does not need to, and the Plan never attempts to.
4. **Does M5's test use the same shape M7 uses?** Not automatically (§10's MINOR finding) — M7's
   real, end-to-end proof will use whatever M4 genuinely produces; M5's own unit test uses a
   hand-built fixture that *should* match but is not mechanically pinned to M4's real output.
5. **Does the Plan invent a second handoff mechanism?** No — confirmed by grep-equivalent review of
   every M4/M5/M7 section: the only field ever referenced for cross-step data is
   `workflow_state.step_results`, consistently, everywhere. No parallel context object, no
   direct-call shortcut, no new schema field.
6. **Is the non-crash-durable limitation preserved?** Yes — M7 explicitly limits its proof to one
   uninterrupted `run()` call and explicitly excludes crash/restart simulation; §14.1's disclosure is
   referenced, not reopened, anywhere in the Plan.

**The handoff can be constructed exactly as planned using current schemas — no MAJOR or CRITICAL
finding here.** The one MINOR (shape-pinning between M4 and M5) is already recorded under M5/M7
above, not duplicated as a separate finding.

---

## 14. Configuration Audit

| Value | Milestone | Location | Validation | Deterministic default | Tests |
|---|---|---|---|---|---|
| Freshness tier boundaries | M1 | Module constant, `services/freshness.py` | N/A (fixed tuple in code, not env-parsed) | Yes, six fixed windows | Yes |
| Freshness tier weights | M1 | Module constant | N/A | Yes, monotonic placeholders | Yes (indirectly, via priority-tier tests) |
| `reliability_score` null default | M1 | Module constant, `services/triage.py` | N/A | Yes, `0.5` | Yes, explicit null-input test |
| S/A/B/C combined-score thresholds | M1 | Module constant | N/A | Yes, unspecified literal values (correctly left to implementation, §5 of this audit) | Yes, via the every-tier-reachable test |
| `stale_processing_threshold_seconds` | M2 | `core/config.py` `Settings` field, env-overridable | **None specified** | `900` | Indirectly (via the exact-threshold and future-timestamp tests, which fix the value in the *test*, not the *field*) |

**MAJOR FINDING 2 — no positivity/non-zero validation is specified for
`stale_processing_threshold_seconds`.**

Contract §7.6 rule 5: "The staleness threshold itself is a positive, non-zero, configured
duration... Its *existence* as a required, non-bypassable guard is frozen; its *exact value* is
product configuration." Contract §22's "Frozen, not provisional" paragraph restates this: "the
requirement that a staleness guard MUST gate recovery eligibility (its exact duration is
configuration, but its **existence and positivity are not**)." This is explicit, binding, frozen
architecture — not a stylistic nicety.

The Plan's own field declaration is `stale_processing_threshold_seconds: int = 900` — a plain `int`
with no lower-bound constraint mentioned anywhere in M2's text (no `Field(gt=0)`, no boot-time
assertion, no runtime guard in `_select_recovery_candidates`). Re-checked `core/config.py`'s existing
conventions for a comparable precedent: numeric fields there (`max_daily_ai_cost: float | None`) have
no positivity constraint either, but none of those gate an architecture-critical safety invariant the
way this one does — the closer precedent is `redis_unavailable_policy`'s own deliberate
no-default-until-explicitly-set design, cited by the Plan itself, which exists specifically to
prevent a dangerous silent default.

**Concrete risk**: an operator (or a misconfigured `.env`) setting
`STALE_PROCESSING_THRESHOLD_SECONDS=0` (or a negative integer — `int` accepts it, `pydantic-settings`
would not reject it without an explicit constraint) would make `reference_now - updated_at > 0`
trivially true for **any** `PROCESSING`+no-active-task event, **immediately** — collapsing the entire
staleness gate this Contract's second and third revision rounds were specifically built to add,
silently, with no boot-time error and no test in this Plan that would catch it (M2's tests fix
the threshold value themselves; none tests the field's own boundary enforcement).

**Required correction**: add an explicit positivity constraint to the `Settings` field
(`Field(gt=0)`, matching Pydantic's own idiom already used elsewhere in this same file for
`priority: Mapped[TaskPriority]`-adjacent constraints in other models, e.g.
`schemas/source_definition.py`'s `Field(ge=0.0, le=1.0)` precedent), and add one explicit test to M2
proving a zero/negative configured value is rejected at construction time, not silently accepted.

**No other configurable value in this table can disable an architecture invariant.** Re-checked
each: `TASK_PRIORITY_ORDINAL` is a hardcoded module dict, not sourced from any config mechanism —
cannot be reconfigured away. Triage's allowed-signal set is a fixed function signature — no config
path exists to inject a forbidden extra signal (confirmed: `decide_triage()`'s parameters are the
complete, closed list; there is no `**kwargs`-style escape hatch anywhere in the Plan's described
API). **Only the staleness threshold has this gap.**

---

## 15. Testing / Verification Audit

Every milestone's §8 (Verification commands) was checked for the eight required categories (focused
pytest, full pytest, ruff, milestone-scoped mypy, repo-wide mypy baseline, architecture validation,
runtime evidence, migration check):

- All eight appear, in some form, across M0-M7's individual sections and §8's cross-milestone
  summary. The repo-wide mypy baseline comparison is correctly deferred to be *captured* before M0
  and *compared* only at M7 — avoiding the wasteful "re-run the full baseline eight times" pattern
  while still closing the loop once, exactly matching the stated "zero regression from the previous
  approved checkpoint" bar (§8 of the Plan) rather than a hardcoded test count. **Confirmed no
  milestone hardcodes a future total test count** — explicitly and correctly stated as a rule in the
  Plan's own §8.
- Provider/network independence: M4/M5's tests are explicitly unit-tier, `FakeLLMGateway`-only;
  M2/M3's are explicitly integration-tier against the real Postgres dev DB (never a real network
  call or real provider) — correctly classified throughout, matching Phase 7/8's own established
  discipline.
- Concurrency evidence requiring real DB transaction/session behavior (not mocks): confirmed present
  exactly where needed (M2, M3) and correctly absent where not needed (M1, M4, M5 — pure functions
  and stateless Capabilities respectively, where a mock is sufficient and a DB test would add no
  signal).

**No finding beyond what is already captured under the M2/M3 transaction-boundary MAJOR finding
above** — the testing *strategy* is sound; the one place a *test* could not actually pass as
currently planned is the batch-isolation test under the uncorrected transaction model (§7/§8 of this
audit), not a gap in the testing strategy itself.

---

## 16. Commit / Rollback Audit

Files touched by more than one milestone, checked directly against the Plan's own §3 (Files) lists
across all eight milestones:

- `services/triage_orchestrator.py`: **M2 and M3**. Explicitly acknowledged in both milestones' own
  §10 (Rollback safety) sections — M2 states reverting it after M3 exists would break M3; M3 states
  it depends on M1+M2. **This is exactly the disclosure the audit instructions require ("rollback
  notes must acknowledge when isolated revert safety ends") — correctly present, not missing.**
- `core/config.py`: **M2 only** (adds `stale_processing_threshold_seconds`) — no overlap with any
  other milestone's config changes.
- `capabilities/registry.py`: **M6 only**, a pre-existing file with pre-Phase-9 history — correctly
  flagged in the Plan's own §9 as "the one milestone that changes a file with a pre-existing
  history," with an explicit, small, isolated diff description.
- `tests/conftest.py`: potentially touched by **M2** (if a new fixture/helper for two-connection
  tests is added there rather than kept local to the test file) — the Plan defers this exact choice
  to implementation time ("a small, local, test-file-scoped helper (or a new fixture in
  `tests/conftest.py`)") without committing to which. **MINOR**: if a shared fixture is added to
  `tests/conftest.py`, this creates a third multi-milestone-adjacent file (M2 modifies a file every
  other milestone's tests also depend on via `import`) — worth resolving definitively (prefer a
  test-file-local helper, avoiding `conftest.py` churn) rather than left open, though the risk is
  low regardless of which choice is made (an additive fixture doesn't threaten existing fixtures).
- Shared fakes (`tests/fakes/*`): confirmed **zero modification** planned by any milestone — M2 of
  the Plan's own Repository Baseline table states this explicitly ("all directly reusable... with
  zero modification"), independently re-confirmed by checking that no milestone's "Files" section
  lists any file under `tests/fakes/`.
- Architecture validator tests (`tests/test_validate_architecture.py`): **M0 only**.

**Each milestone is a coherent, single-purpose commit boundary.** No milestone silently depends on
uncommitted state from a sibling milestone beyond what's explicitly declared in the dependency graph.

---

## 17. Scope Leakage Audit

Searched the full Plan text for every item on the audit's forbidden list:
`EngagementAnalysisCapability`, final Scoring enhancement, Opportunity Score, clustering, embeddings,
vector DB, true novelty, engagement collection, source reputation learning, web browsing, autonomous
research agents, workflow redesign, scheduler, automatic production scheduling, per-step durable
workflow checkpointing, new DB model/migration, `FAILED`/`COMPLETED` lifecycle redesign.

**Every one of these appears in the Plan only inside an "explicitly out of scope"/"Deferred Work"
list, never inside an "Implementation scope" section.** Independently re-confirmed for the two items
most likely to leak by accident: (1) production scheduling — `scripts/run_triage.py` is explicitly
scoped as script-only, with §7.4's deferral restated in M3's own "out of scope" list and again in
§10 (Deferred Work); (2) the `FAILED`/`COMPLETED` lifecycle gap — confirmed §4 of the Plan records it
as deferred technical debt, confirmed no milestone's implementation scope touches
`_find_active_task()`, confirmed a fresh repo-wide grep (re-run this pass, matching the Plan's own
claim) still shows zero production `WorkflowRunner.run()` call sites.

**No finding. Clean.**

---

## 18. Implementation Readiness

Could a fresh session implement M0-M7 from this Plan without inventing an architecture decision?
**Mostly yes** — the two MAJOR findings above are the specific exceptions:

- **Transaction/session boundaries** (§7/§8 of this audit): the one place a fresh implementer would
  have to invent a decision the Plan doesn't make for them, and where two plausible inventions
  diverge in actual safety (one Contract-compliant, one not).
- **Configuration validation** (§14 of this audit): the one place a fresh implementer could
  reasonably read the Plan literally (`int = 900`, no constraint mentioned) and produce an
  under-validated field, silently violating a frozen Contract invariant.
- **`WorkflowType` reuse for M7's synthetic definition** (§12 of this audit): a real but narrow gap,
  with an unambiguous, easily-discoverable existing precedent (`CONTENT_GENERATION`/`DAILY_DIGEST`)
  and an already-explicit Contract prohibition (P10) that would likely catch a wrong choice in
  review even without the Plan spelling it out — lower risk than the two MAJOR items, correctly
  MINOR.
- **M4→M5 output-shape pinning** (§10/§12/§13 of this audit): would be caught at latest by M7;
  correctly MINOR, not blocking.

Every other category the audit asks about — exact ownership, APIs between M1/M2/M3 (beyond the
commit-timing gap), configuration mechanism placement (beyond the missing constraint), Research
output shape, Intelligence input shape, registration names, runtime-proof boundary — was checked and
found unambiguous enough to guarantee compatible implementations. **Ordinary implementation freedom**
(exact file layout already chosen, exact field names already chosen, exact test names left open) is
correctly not penalized here.

---

## 19. Findings by Severity

**CRITICAL**: None.

**MAJOR**:
1. **M3 does not specify commit/rollback discipline around the claim/ownership-acquisition step**,
   and its stated intent to mirror `services/collector.py`'s isolation pattern, read literally,
   would apply the wrong granularity (per-event instead of per-claim), risking a batch-isolation
   violation and contradicting the Contract's own "claim already committed in step 1" framing (§7,
   §8 of this audit).
2. **`stale_processing_threshold_seconds` has no positivity/non-zero validation specified**, despite
   the Contract explicitly freezing this as a non-configurable-away architecture invariant (§14 of
   this audit).

**MINOR**:
1. M7 does not name which existing `WorkflowType` its synthetic definition reuses, nor restate
   Contract P10's "no new enum member" prohibition inline, despite a clear, findable, already-used
   precedent in this exact codebase (§12, §18 of this audit).
2. M4's real `structured_output` shape and M5's test fixture shape are linked only by a manual,
   cross-milestone "printed evidence" comparison, not an automated/shared check — closed only at M7
   (§10, §13 of this audit).
3. `tests/conftest.py` vs. a test-file-local helper for M2's two-connection concurrency tests is left
   an open implementation choice that, if resolved toward `conftest.py`, creates a third
   multi-milestone-adjacent file not otherwise flagged (§16 of this audit).
4. M0's `triage-orchestrator-isolation` rule enumerates four `capabilities.*` sub-modules by name
   rather than a single blanket `capabilities.` prefix, which would be simpler and would
   automatically cover any future capability file (§4 of this audit).
5. M1 does not explicitly test the exact-zero-age Freshness boundary the way M2 explicitly tests the
   staleness threshold's exact boundary (§5 of this audit).

**OBSERVATION**:
1. Contract P12/§19 (future compatibility with `EngagementAnalysisCapability`/Final Scoring) has no
   explicit milestone owner or verification step — satisfied by design (M4/M5 follow Phase 8's
   extensible pattern) but not independently tested anywhere (§2 of this audit).
2. Contract §6 rules 2-3 (no dynamic/historical authority score) have no explicit negative test, but
   are structurally prevented by Triage's no-DB-access design — arguably a stronger guarantee than a
   test would provide (§2, §5 of this audit).

---

## 20. Required Planning Corrections

Both MAJOR findings have small, precise, non-redesigning corrections available — neither requires
reopening the milestone sequence, the Component Model, or any Contract-level decision:

1. Add an explicit paragraph to M3's "Implementation scope" (§7 above): commit immediately after a
   successful claim/CAS, before Triage/`create_task()` run for that event; call
   `await session.rollback()` in the "any other exception" branch before continuing the loop —
   citing `services/collector.py`'s actual `_process_source()`/outer-`except` pattern at the correct
   (per-claim, not per-event-batch) granularity.
2. Add an explicit constraint to M2's `core/config.py` field description (§14 above):
   `stale_processing_threshold_seconds: int = Field(gt=0, default=900)` (or equivalent), plus one
   test proving a zero/negative configured value is rejected.

The MINOR findings are recommended, not required, before implementation begins; none blocks a
correct implementation on its own.

---

## 21. Scores

| Dimension | Score /10 | Basis |
|---|---|---|
| Contract Coverage | 9 | Every load-bearing requirement has a clear owner (§2 of this audit); docked one point for P12/§19 having no explicit verification step |
| Milestone Quality | 8 | Each milestone is independently reviewable, testable, and narrow; docked for the two MAJOR under-specifications found within otherwise well-scoped milestones |
| Sequencing | 10 | Every dependency independently re-derived and confirmed correct; no undeclared dependency found (§3 of this audit) |
| Concurrency Safety | 6 | The underlying primitives (M2) are correct and empirically grounded; docked significantly for the commit/rollback ambiguity (§7/§8), which is exactly the class of gap this Contract's entire revision history was built to eliminate, now reappearing one layer up at the planning stage |
| Capability Design | 10 | M4/M5 verified line-for-line against real Phase 8 precedent; no finding |
| Configuration Safety | 6 | One architecture-critical invariant (staleness positivity) has no enforcement path specified (§14); every other configurable value correctly cannot disable an invariant |
| Testing Strategy | 9 | Comprehensive, correctly tiered, correctly avoids hardcoded test counts; docked one point for the cross-milestone shape-pinning reliance on manual verification (§10/§13) |
| Scope Discipline | 10 | Exhaustive search found zero leakage anywhere (§17) |
| Rollback Safety | 9 | Multi-milestone file overlaps correctly identified and disclosed; docked slightly for the undecided `conftest.py` placement question (§16) |
| Implementation Readiness | 7 | Two MAJOR, safety-relevant ambiguities remain that a fresh implementation could plausibly get wrong in a Contract-violating direction; everything else is unambiguous |

**Overall (evidence-weighted): 8.1/10.**

---

## 22. Final Verdict

**PHASE 9 PLAN NOT READY — CORRECTIONS REQUIRED**

The Plan's architecture, milestone boundaries, dependency ordering, Capability design, and scope
discipline are all sound and were independently re-verified against the real repository, not merely
re-read from the Plan's own citations. No CRITICAL finding exists, and neither MAJOR finding requires
reopening any milestone's scope, file list, or sequencing — both are narrow, mechanical additions to
already-correct milestones (M2's config field, M3's transaction-boundary paragraph).

However, two MAJOR findings are genuinely safety-relevant and directly analogous to the exact class
of gap this Contract's own multi-round revision history (three prior audits, two revisions) was
built to eliminate at the architecture level: an under-specified transaction boundary that could
silently violate the Contract's own "claim already committed in step 1" premise and batch-isolation
requirement, and a missing positivity guard on the one configuration value capable of disabling an
entire, hard-won safety mechanism if misconfigured. Per this engagement's own established standard —
close every real gap before freezing, rather than accept "unlikely" — both must be corrected in the
Planning document's text before M0 begins. Both corrections are small and precisely scoped (§20
above); once applied, this Plan is ready for implementation without further architectural review.
