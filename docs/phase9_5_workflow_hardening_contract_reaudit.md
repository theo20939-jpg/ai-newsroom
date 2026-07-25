# Phase 9.5 — Workflow Hardening Contract Final Re-Audit

**Status: audit only. `docs/phase9_5_workflow_hardening_architecture_contract.md`, all production
code, and all tests were left unmodified. No implementation was created. No commit was made.**

The revised Contract was again treated as untrusted. Every citation, and every claim the previous
audit flagged as corrected, was independently re-derived from the current repository, not
accepted from either the Contract's or the previous audit's own text. `git rev-parse HEAD` =
`9d51a1c5304586bfc30f918ba73b860f8b5826d7`, `git status --short` shows no drift beyond the
pre-existing untracked `docs/phase9_*.md` audit-trail files.

---

## 1. Executive summary

All three MAJOR findings from `docs/phase9_5_workflow_hardening_contract_audit.md` are
**correctly and thoroughly fixed**, with citations re-verified accurate against fresh reads of
every source file. Two pieces of evidence independently strengthen this re-audit's confidence
beyond the original audit's own verification:

- `tests/conftest.py`'s own module docstring (lines 3-10) states, in the codebase's own words,
  that its `db_session` fixture's inner `commit()` calls "only commit a SAVEPOINT — nothing a
  test does is ever actually persisted, regardless of how many times the code under test calls
  `commit()`." This is a direct, first-party confirmation of MAJOR-2's root cause, independent of
  anything either audit previously inferred.
- `tests/test_triage_orchestrator_claims.py:42` — the exact Phase 9 M2 precedent the revised
  Contract's §12 item 2 now mandates — already constructs its independent-connection sessions
  with `expire_on_commit=False` explicitly set, confirming the required test technique is
  self-consistent with MAJOR-1's fix, not merely adjacent to it.

All four MINOR findings from the previous audit are also correctly addressed. This re-audit found
no CRITICAL or MAJOR issues, either pre-existing or newly introduced by the revision. Two new
MINOR/OBSERVATION-level completeness points were found (a citation-coverage gap that names two of
three relevant `expire_on_commit` sites, and an unaddressed nuance about out-of-band manual
task-status resets) — neither is a functional defect, and neither invalidates any claim the
Contract makes.

**Verdict: PHASE 9.5 CONTRACT APPROVED.**

---

## 2. Previous findings verification

### MAJOR-1 — `expire_on_commit=False` dependency

**Correctly stated.** §4's new paragraphs state the dependency explicitly, cite it precisely, and
bound the claim correctly:

- Citation `database/session.py:14` re-verified: `async_session_factory =
  async_sessionmaker(engine, expire_on_commit=False)` — exact match.
- Citation `tests/conftest.py:65` re-verified: `bind=connection,
  join_transaction_mode="create_savepoint", expire_on_commit=False` — exact match.
- The consequence claimed (`sqlalchemy.exc.MissingGreenlet` on expired-attribute access in an
  async context without this setting) is stated as a conditional consequence ("Without this
  setting... would mark... would raise"), not asserted as a live bug — this avoids overclaiming;
  the Contract does not claim the codebase is currently broken, only that it depends on a
  currently-true, previously-unstated condition.
- The "architectural change requiring re-evaluation" rule and the Definition-of-Done verification
  requirement are both present and correctly scoped to *future* implementation, not retroactively
  applied to this document itself.

**Bounded correctly?** Yes. The dependency is scoped to "any session `WorkflowRunner.run()` is
invoked with" — accurate, since `run()` accepts an injected `AsyncSession` rather than hardcoding
a factory, so the precondition genuinely does need to hold for whatever session a caller supplies,
not merely for the one named production factory. No overclaim, no underclaim.

**Verdict: CONFIRMED FIXED, no residual issue.**

### MAJOR-2 — Independent-connection durability testing

**Correctly stated and now the strongest-evidenced item in the Contract.** §12 item 2:

- Explicitly prohibits the standard `db_session` fixture for this specific test — confirmed
  necessary by `tests/conftest.py`'s own docstring, quoted above, which states in first-party
  terms that its `commit()` calls are savepoint-only and never actually persisted to the shared
  database regardless of call count.
- Names the required technique (`tests/test_triage_orchestrator_claims.py`/
  `tests/test_triage_orchestrator_cycle.py`'s two-independent-connection pattern, built against
  `tests.conftest._test_engine`) — re-verified this pattern exists and is exactly as described:
  `tests/test_triage_orchestrator_claims.py:42` constructs `async_sessionmaker(engine,
  expire_on_commit=False)` against a real engine, matching both the "genuinely independent
  connection" requirement and (incidentally, favorably) the `expire_on_commit=False` requirement
  from MAJOR-1 in the same call.
- This matches Phase 9 M2/M3 precedent exactly, as claimed — not a paraphrase or approximation.

**Verdict: CONFIRMED FIXED, evidence stronger than the original audit established.**

### MAJOR-3 — Persistence vs. recovery limitation

**Correctly stated, and the separation the audit asked for is present.** Re-reading §1, §13, and
§14 rule 8 together:

- **Visibility** is defined precisely: "a durable, mid-run record of which steps have already
  succeeded, and their results" (§1).
- **Persistence** (the mechanism itself) is described throughout §3-§10 without conflating it with
  recoverability anywhere — re-checked every section for language that could be read as implying
  otherwise; none found.
- **Crash recovery** and **resume semantics** are both explicitly named and explicitly disclaimed,
  twice in binding language (§1's full paragraph, §13's cross-referencing bullet) and once more in
  the consolidated Canonical Rules (§14 rule 8) — no hidden or implied recovery claim was found
  anywhere in the document, including in the newly-added §4 (`expire_on_commit`) and §12 item 2
  (independent-connection testing) material, both of which this re-audit scrutinized specifically
  for language that could be misread as a durability-implies-recoverability claim. None was found;
  both sections stay strictly scoped to correctness/visibility, not resumability.

**One genuine nuance this re-audit found, not covered by either version of the Contract** — see
New Findings, MINOR-B below. It does not weaken the "no hidden recovery claim" conclusion above;
it is a completeness point about a scenario neither the original Contract nor its revision
considered, not a false statement either version makes.

**Verdict: CONFIRMED FIXED, no hidden recovery claim found; one adjacent nuance newly noted
(non-blocking).**

---

## 3. New findings

**MINOR-A — §4's `expire_on_commit` precondition paragraph cites two of three relevant
configuration sites.** It correctly cites `database/session.py:14` and `tests/conftest.py:65`,
but does not extend the same explicit citation to the *third* code path implied by §12 item 2's
own requirement: the test-local `async_sessionmaker` a future implementer will construct to
satisfy the independent-connection durability test. This is not a live risk — the mandated
precedent (`tests/test_triage_orchestrator_claims.py:42`) already sets `expire_on_commit=False`
correctly, confirmed directly above — but the Contract's own precondition statement doesn't say
so explicitly, leaving a small gap where a future implementer who builds a *new* test-local
sessionmaker without copying the precedent literally could, in principle, omit it. A one-sentence
addition to §4 noting that any test-local session construction required by §12 item 2 must also
carry `expire_on_commit=False`, citing the precedent's own line, would close this fully — but its
absence today is a completeness note, not a defect, since the Contract already mandates following
that exact, already-correct precedent.

**MINOR-B — Out-of-band manual task-status intervention is not addressed by the visibility/resume
distinction.** §1/§13's disclaimer is scoped to "no code path this amendment or the existing
codebase provides" — accurate as stated. This re-audit specifically probed the adjacent, unstated
scenario: an operator manually resetting a stuck `RUNNING` task's `status` via a direct database
write (bypassing `run()`'s guards entirely, not a codebase-provided code path) and re-invoking
`run()`. Because `_execute_steps()`'s `remaining_steps` filter already correctly skips any step
already present in `completed_steps`, and per-step persistence now makes `completed_steps`
genuinely accurate mid-run, such a manual intervention would — as an incidental, not
code-provided, consequence of this amendment — behave *more safely* under Phase 9.5 than it would
today (today, a manually-reset task would re-run every step from scratch, including ones that had
already succeeded, since `completed_steps` was never durably accurate before this amendment). This
is not a new recovery mechanism, is not implied anywhere in the Contract's text, and is not a
false claim — the Contract's "no code path... provides" wording is technically precise and remains
true — but it is a real, adversarially-found nuance that a fully rigorous future audit (or a
reader building an operational runbook) might reasonably want the Contract to acknowledge
explicitly, given how much scrutiny MAJOR-3 already received. Recommended, non-blocking: a
one-sentence note that manual, out-of-band status intervention is outside this document's scope
entirely and is not evaluated, endorsed, or disclaimed by it either way.

**OBSERVATION-1** — §1, §13, and §14 rule 8 all restate the visibility-not-resume limitation.
Confirmed these three statements are word-for-word *consistent* with each other (no drift, no
contradiction) and that §13/§14's versions are explicit cross-references back to §1, not
independent restatements that could diverge over a future edit. This matches the established
"Canonical Rules as consolidation, not new authority" pattern already used in Phase 9's own main
contract (`docs/phase9_research_intelligence_architecture_contract.md` §21). Not a defect.

**OBSERVATION-2** — §4's new architectural-dependency paragraph contains one awkwardly-ordered
sentence ("Verified today in both places this amendment's mandated tests (§12) will run against
already set it: ...") — grammatically parseable, unambiguous in meaning, cosmetic only.

**OBSERVATION-3** — No hidden schema change, no hidden `WorkflowRunner` redesign, and no new
duplicated *rule* (as opposed to the intentional, cross-referenced restatement noted in
OBSERVATION-1) was found anywhere in the revision. Every edit traced in the diff between the
original and revised Contract text is either (a) a new, additive paragraph appended after
existing, unmodified text, or (b) a wording correction within an existing paragraph that does not
change the paragraph's binding content — confirmed by re-reading §3/§4's core invariant and
commit-point definition, which is byte-for-byte unchanged from the pre-revision version.

**OBSERVATION-4** — Every citation re-checked in this pass (`workflows/runner.py` line numbers
114-117, 122-123, 134-136, 147-203, 156, 157, 160, 187, 189-195, 205-260, 220-260, 227, 262-288;
`capabilities/executor.py` 59-109, 111-147, 114, 129-134; `schemas/workflow.py`'s field
definitions; `database/models/editorial_task.py:44`; `docs/phase8_capability_contract.md:94`)
matches the current repository exactly. No stale or drifted citation was found.

---

## 4. Severity classification

| Severity | Count | Items |
|---|---|---|
| CRITICAL | 0 | — |
| MAJOR | 0 | — |
| MINOR | 2 | MINOR-A (citation coverage), MINOR-B (out-of-band intervention nuance) |
| OBSERVATION | 4 | OBSERVATION-1 (consistent restatement), OBSERVATION-2 (grammar), OBSERVATION-3 (no hidden redesign/schema change), OBSERVATION-4 (citation accuracy sweep) |

Neither MINOR item blocks approval: both are completeness refinements to an already-correct,
already-safe specification, not corrections to a wrong or incomplete rule. Recommended (not
required) for a future, even-more-polished revision: fold MINOR-A and MINOR-B into §4/§1
respectively as one sentence each, at the next natural opportunity this document is touched.

---

## 5. Final verdict

PHASE 9.5 CONTRACT APPROVED
