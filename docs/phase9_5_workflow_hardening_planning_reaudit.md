# Phase 9.5 — Workflow Hardening Planning Final Re-Audit

**Status: audit only. `docs/phase9_5_workflow_hardening_planning.md`, all production code, and all
tests were left unmodified. No implementation was created. No commit was made.**

The corrected planning document was again treated as untrusted. Every citation, milestone claim,
and rollback-safety statement was independently re-derived from the current repository and from
the approved Contract/Re-Audit, not accepted from the plan's or the prior audit's own text.
`git rev-parse HEAD` = `9d51a1c5304586bfc30f918ba73b860f8b5826d7`, `git status --short` shows no
drift beyond the pre-existing untracked `docs/phase9_*.md` files.

---

## 1. Executive Summary

The corrected plan fully and correctly resolves the previous audit's one MAJOR finding: the
required Phase 9 M7 regression-lock test update is now bundled into M1, in the same commit as the
code change that invalidates it, closing the "broken window between commits" defect completely.
Both prior MINOR findings are also addressed. This re-audit independently re-verified the
central claim (that `test_both_capabilities_dispatch_in_order_and_synthetic_task_completes`'s
lines 196-200 would break under M1 alone) directly against the current test file and confirms the
plan's citation is exact. No new CRITICAL, MAJOR, or MINOR issue was found in this pass. One
sub-MINOR, non-blocking phrasing note is recorded as an OBSERVATION.

**Verdict: PHASE 9.5 PLANNING APPROVED.**

---

## 2. Previous MAJOR Finding Verification

**Original finding**: M1's own code change invalidates `tests/test_phase9_research_intelligence_integration.py`'s
existing regression-lock assertion, but the test update was scheduled into M2, leaving a
known-broken test between M1's commit and M2's commit; M1's own Definition of Done did not
require the file to pass, and its rollback-safety text incorrectly claimed the test "continues to
pass either way."

**Verification, this pass**:
- Re-read `tests/test_phase9_research_intelligence_integration.py:195-200` fresh: confirms
  `assert "did not run" in intelligence_request_text.lower()` and `assert fact not in
  intelligence_request_text` for every canonical fact — exact match to the plan's own citation
  (plan cites lines 196-200 for the two assertion statements; the `intelligence_request_text`
  assignment itself is line 195, immediately before). The plan's factual basis is accurate.
- M1 §3 (Files) now lists `tests/test_phase9_research_intelligence_integration.py` as a file M1
  changes — confirmed present.
- M1 §4 (Implementation scope) now contains a dedicated paragraph ("Required, same-commit test
  update") stating, in binding language, that the repository "MUST NOT pass through any commit
  state in which this code change exists but that test's assertions do not match it" — confirmed
  present and correctly scoped to *this* commit, not a future one.
- M1 §6 (Tests required) now includes "Required Phase 9 M7 test update, in the same commit as the
  code change" as its own bullet — confirmed present, correctly cites Contract §11 and §12 item 8.
- M1 §7 (Definition of Done) now explicitly requires the updated assertion to pass and states "this
  milestone is not complete, and MUST NOT be committed, while that test still asserts the
  pre-amendment behavior" — confirmed present, unambiguous.
- M1 §8 (Verification commands) now includes `pytest tests/test_phase9_research_intelligence_integration.py -v`
  as its own line, separate from the full-suite sanity check — confirmed present.
- M1 §10 (Rollback safety) no longer contains the false "continues to pass either way" claim;
  re-read in full, it now states the test is updated "in the *same* commit as the code change that
  invalidates it," so "there is no commit state in this milestone's history where the code exists
  but the test still asserts the old, now-false behavior" — confirmed accurate and consistent with
  every other section.

**The secondary, compounding issue** (M1's bullet 7 deferring full-suite checking to M2 while
bullet 8 listed a full-suite command that would contradict that deferral) is also resolved: bullet
8's full-suite `pytest` line now carries an inline comment clarifying it is a "whole-repo sanity
check," while the *formal, documented* zero-regression checkpoint (Contract §12 item 7) remains
explicitly assigned to M2 — the two bullets no longer disagree about what M1 requires versus what
M1 additionally recommends running.

**Verdict on this finding: CORRECTLY AND FULLY RESOLVED. No residual issue found.**

---

## 3. Milestone Review

**M1 ownership** (audit dimension 1): confirmed — the assertion update is correctly assigned to
M1, is directly and explicitly tied to M1's own production change (with exact line citations),
appears in M1's Definition of Done as a blocking requirement, and M1's verification commands are
now internally consistent (bullet 7 and bullet 8 agree). Re-tracing the control flow in
`workflows/runner.py` once more (fresh read, lines 147-203) confirms the insertion point (line
187) and the causal chain to the test breakage are both accurately described.

**M2 scope** (audit dimension 2): confirmed — M2's Tests required (bullet 6) contains exactly two
items: the independent-connection durability/visibility proof (Contract §12 item 2) and the full
repository regression sweep (Contract §12 item 7). No remaining reference anywhere in M2 assigns
it responsibility for editing the Phase 9 integration test — bullet 3 (Files), bullet 4
(Implementation scope), and bullet 5 (Explicitly out of scope) all explicitly and consistently
state M1 already handled it. M2's bullet 8 includes `git diff
tests/test_phase9_research_intelligence_integration.py` with an "expect no output" comment — a
directly verifiable, self-checking claim, not merely an assertion. M2's rollback statement (bullet
10) is accurate: it correctly notes M2 owns only the durability test's own revert consequence and
explicitly disclaims any responsibility for the M7 file.

**Milestone boundaries** (audit dimension 3): no hidden dependency beyond the declared one (M2
depends on M1) was found. M1 is confirmed independently committable — its own DoD and rollback
sections are self-contained and no longer reference M2 for correctness, only for the *additional*
durability proof and formal full-suite sign-off, which are legitimately separate deliverables. M2
cannot be mistaken for a production-implementation milestone: its Files/Implementation scope
bullets explicitly state "Production: none" and "no production code" in the same sentence,
twice. No future workflow-engine work (crash recovery, resume, scheduler, redesign) appears
anywhere in either milestone — re-confirmed by a full re-read of both milestones' "Explicitly out
of scope" sections and the shared §3 boundary statement.

---

## 4. Testing Review

- Every test specified still correctly maps to its Contract §12 citation; re-checked all eight
  items are covered, now correctly distributed (seven items — 1, 3, 4, 5, 6, plus the moved item 8
  — under M1; items 2 and 7 under M2).
- The independent-connection requirement for M2's durability test is unchanged and still explicit
  (`tests.conftest._test_engine`, `async_sessionmaker(engine, expire_on_commit=False)`, never
  `db_session`) — re-verified against fresh reads of `database/session.py:14` and
  `tests/conftest.py:60-68`, both matching the plan's citations exactly.
- The savepoint-fixture prohibition for the durability proof remains explicit and, as of this
  revision, also carries the `expire_on_commit=False`-for-the-test-local-sessionmaker clarification
  requested as MINOR-2 in the prior audit — confirmed present in M2 §4.
- The existing Phase 9 regression expectation (`test_both_capabilities_dispatch_in_order_and_synthetic_task_completes`)
  is now correctly scheduled to be updated in M1, verified via direct re-citation against the real
  file, not merely asserted.

No test-design defect, false-positive risk, or forbidden-infrastructure requirement was found in
this pass beyond what the prior audit already covered and this revision already fixed.

---

## 5. Rollback Review

- M1's rollback description is accurate: reverting M1 atomically restores both
  `workflows/runner.py` and the test assertion to their pre-Phase-9.5 state, with no intermediate
  inconsistent state ever having existed in git history.
- M2's rollback description is accurate: test-only, zero production impact, and its one
  asymmetric dependency (M2's durability test needs M1's code to remain meaningful) is stated
  plainly and correctly, with no overreach into claiming responsibility for the M7 file it no
  longer touches.
- No rollback statement assumes a *future* milestone (there are only two, and neither's rollback
  text references any milestone beyond M1/M2). The document's own final §8 (Rollback strategy)
  synthesizes both correctly: M1 alone is self-consistent; M1+M2 together revert as a unit with
  each file's restoration correctly attributed to the milestone that would need to revert it.

---

## 6. New Findings

### CRITICAL
None.

### MAJOR
None.

### MINOR
None.

### OBSERVATION

**OBSERVATION-1** — §2's repository-baseline table row for
`tests/test_phase9_research_intelligence_integration.py` (line 49) still reads "...which becomes
false once M1 ships" without explicitly naming that M1 itself is what closes that gap in the same
sentence (the fact stated is true and is exactly the premise for M1 bundling the fix, but the
sentence predates the correction's framing and reads slightly disconnected from the rest of the
document's now-explicit "M1 owns this" language elsewhere). Purely a phrasing polish; not a
factual error, not a contradiction with any other section, and not something a future implementer
could misread given how explicitly every other section (§4, §5, §6, §7, §10 of M1) already states
M1's ownership. No correction required.

**OBSERVATION-2** — Confirmed, via direct repo-wide grep, that no stale instance of the previous,
incorrect "continues to pass either way" framing survives anywhere in the document. The three
remaining occurrences of the phrase "either way" all correctly refer to the distinct, genuinely
unaffected companion test
(`test_step_results_mechanism_surfaces_a_result_already_persisted_before_the_run_began`), not the
regression-lock test this audit cycle was about.

**OBSERVATION-3** — Milestone table, dependency-graph ASCII diagram, and both `###` section
headers are now fully consistent with each other (all four locations name identical milestone
titles) — this was itself a gap in the immediately-prior revision, now closed.

---

## 7. Final Verdict

PHASE 9.5 PLANNING APPROVED
