# Phase 9.5 — Workflow Hardening Planning Adversarial Audit

**Status: audit only. `docs/phase9_5_workflow_hardening_planning.md`, all production code, and all
tests were left unmodified. No implementation was created. No commit was made.**

The planning document was treated as untrusted throughout. Every citation, milestone claim, and
rollback-safety statement was independently re-derived from the current repository and from the
approved Contract/Re-Audit, not accepted from the plan's own text. `git rev-parse HEAD` =
`9d51a1c5304586bfc30f918ba73b860f8b5826d7`, `git status --short` shows no drift beyond the
pre-existing, untracked `docs/phase9_*.md` files.

---

## 1. Executive summary

The plan's contract compliance, implementation scope, and testing strategy are all sound and
accurately grounded in the approved Contract — every Contract §12 test item is covered somewhere
in the plan, no future-phase work is pulled forward, and no hidden architecture is introduced.

However, this audit found **one concrete, verified, MAJOR defect in the milestone
decomposition**: the M1/M2 split, as specified, leaves an existing, currently-passing test
(`tests/test_phase9_research_intelligence_integration.py::
test_both_capabilities_dispatch_in_order_and_synthetic_task_completes`) **broken between M1's
commit and M2's commit** — M1's own code change is precisely what falsifies that test's existing
assertions, but M1's own Definition of Done explicitly excludes running that test file, and M1's
rollback-safety section makes a factually incorrect claim that the test "continues to pass either
way." This is directly verifiable, not speculative (see §3 below). It also surfaces a secondary,
compounding internal inconsistency: M1's own listed verification commands include a full-suite
`pytest` run that would, if actually executed, reveal the break — contradicting M1's own DoD text,
which defers full-suite verification to M2.

This is a real, fixable planning defect, not a defect in the Contract or in the underlying
technical approach. **Verdict: corrections required before this plan is ready to execute.**

---

## 2. Contract compliance

- Every milestone implements only Contract-approved changes — confirmed. M1's implementation
  scope is exactly the Contract §3-§4 invariant at the Contract's own cited line 187 insertion
  point (re-verified fresh against `workflows/runner.py:187` — exact match). M2 makes no
  production-code change at all.
- No milestone introduces new architecture — confirmed. No new class, protocol, table, or
  abstraction appears anywhere in the plan; every file touched is either the one authorized
  production file or a test file.
- **"Phase 9.5 changes persistence timing, not workflow semantics" remains true** — confirmed
  throughout. Every test the plan specifies (same-pass propagation, subsequent-step failure,
  retry-count durability, one-step double-commit, commit-failure propagation, independent-
  connection durability) verifies *when* state becomes durable/visible, never changes *what* a
  workflow run produces or means. No test or implementation-scope bullet anywhere implies a
  workflow-semantics change.

---

## 3. Milestone review

**Is the M1/M2 split correct?** The *rationale* for the split (isolating the highest-scrutiny
independent-connection proof, mirroring Phase 9 M2/M3's own precedent) is sound and well-cited.
The *sequencing* is not: M1 is specified to land, as its own complete commit, without updating
the one existing test the Contract itself (§11) names as depending on M1's own change. Traced
directly:

1. M1's Implementation scope (bullet 4) inserts the exact commit-point code at
   `workflows/runner.py:187` — re-verified correct.
2. `tests/test_phase9_research_intelligence_integration.py` lines 196-200 (re-read fresh) assert,
   in the pre-existing, currently-passing regression-lock test:
   ```python
   assert "did not run" in intelligence_request_text.lower()
   ...
   assert fact not in intelligence_request_text  # for every canonical fact
   ```
3. Once M1's code exists, these assertions become **false** — Intelligence's built prompt will
   genuinely contain Research's facts and will not say "did not run." This is the exact,
   intentional effect M1 is built to produce (Contract §11's own framing: "true only because this
   amendment is not yet implemented").
4. M1's own bullet 5 ("Explicitly out of scope") explicitly defers this exact test's update to M2.
   M1's own bullet 7 ("Definition of Done") requires only `tests/test_workflow_runner.py` to pass
   — it does not require `tests/test_phase9_research_intelligence_integration.py` to be run or to
   pass.
5. M1's own bullet 10 ("Rollback safety") states: *"Phase 9 M7's own test suite continues to pass
   either way — it currently asserts the pre-amendment behavior, and only M2 flips that
   assertion."* This claim is **incorrect** for the forward direction (M1 applied, M2 not yet
   applied) — in that state, the test does *not* continue to pass; it fails, per step 3 above. The
   claim is only true for the trivial case of M1 never being applied at all, which is not the
   scenario "rollback safety between milestone commits" is meant to describe.

**Compounding internal inconsistency**: M1's own bullet 8 ("Verification commands") lists
`pytest --tb=short -q` — an unrestricted, full-suite run — which, if actually executed as the
milestone's own checklist instructs, *would* surface this exact failure before a commit is made.
This directly contradicts bullet 7's stated position that "the full, repository-wide regression
sweep is M2's job." The plan does not resolve which of these two statements governs: if bullet 8
is followed literally, the problem is caught (accidentally, not by design) and M1 cannot honestly
be marked complete without either fixing the test or reconsidering the split; if bullet 7 is
followed literally (only `tests/test_workflow_runner.py` required), the problem ships.

**Are dependencies explicit?** Yes — M2 correctly declares its dependency on M1 in the milestone
table and dependency graph, and the reasoning given (durability proof needs M1's code to exist;
the M7 assertion "only becomes true" once M1 ships) is accurate as far as it goes. What it misses
is that "the assertion only becomes *correct* after M1" is not the same claim as "the *old*
assertion is safe to leave *failing* between M1 and M2" — the plan conflates these two.

**Is any required work missing?** No. All 8 Contract §12 test items are covered somewhere across
M1+M2 — this is a sequencing defect, not an omission.

**Is any future-phase work pulled forward?** No. Confirmed clean — no `EngagementAnalysisCapability`,
no scheduler, no crash recovery, no new `WorkflowType`, nothing beyond Contract scope appears
anywhere in either milestone.

---

## 4. Testing review

- Tests specified genuinely prove the Contract's claims — re-checked each of M1's five tests and
  M2's durability test against the exact Contract section each cites; all match.
- No false-positive test design was found. In particular, M2's durability test correctly avoids
  the `db_session` fixture (re-confirmed via a fresh read of `tests/conftest.py`'s own docstring:
  "nothing a test does is ever actually persisted, regardless of how many times... `commit()`")
  and correctly cites `tests/test_triage_orchestrator_claims.py:42`'s working precedent
  (`async_sessionmaker(engine, expire_on_commit=False)` against a real, `NullPool`-based engine) —
  re-verified this precedent exists exactly as described.
- Commit visibility (M2's durability test) is proven via a sound, precedented technique
  (monkeypatch the second step to perform the independent read as its own first action, ensuring
  deterministic ordering within one event loop — no race condition, since both sessions operate
  within the same async test function/event loop).
- Commit-failure semantics (M1's test) are specified at an appropriate level of detail, consistent
  with the Contract §7/§12 item 3 requirement, targeting the new per-step commit specifically
  rather than the run-start or terminal commits.
- The one genuine testing-strategy gap is the sequencing issue in §3 above — not a defect in any
  individual test's design, but in which milestone's DoD is required to include which test.

---

## 5. Rollback review

- M1 can revert independently in the strict code sense (reverting the one insertion returns
  `workflows/runner.py` to its exact prior state) — this part of the claim is accurate.
- M2 correctly depends on M1 — confirmed, and M2's own asymmetric rollback note (reverting M1
  after M2 exists requires reverting M2's test changes together with it) is accurate and clearly
  stated.
- **The rollback-safety statement that is inaccurate** is specifically M1 §10's claim that "Phase
  9 M7's own test suite continues to pass either way" in the forward (not-reverted) direction
  between M1 and M2 — see §3 above for the direct, line-cited proof this is false.

---

## 6. Findings by severity

### CRITICAL
None.

### MAJOR

**MAJOR-1 — M1/M2 sequencing leaves an existing, named test broken between commits, and the plan
contains an incorrect factual claim about it.** M1's own code change falsifies
`tests/test_phase9_research_intelligence_integration.py:196-200`'s existing assertions (verified
directly, not inferred), M1's own Definition of Done does not require that file to be run or to
pass, and M1's own rollback-safety text incorrectly states the test "continues to pass either
way." A commit made strictly per M1's stated DoD would leave the repository's test suite in a
known-broken state until M2 lands — a state this project's own established discipline (every
Phase 8/Phase 9 milestone required a full, passing suite at each commit checkpoint) does not
otherwise tolerate anywhere else in this codebase's history. Compounded by an internal
inconsistency between M1's bullet 7 (defers full-suite checking to M2) and bullet 8 (lists a
full-suite command that would catch the problem if actually run).

### MINOR

**MINOR-1** — M2's bullet 2 ("Contract coverage") lists §9-§12 broadly; given MAJOR-1's fix will
likely move the §11 test-update item into M1, the Contract-coverage lists for both milestones will
need a corresponding, mechanical adjustment (not a new defect, a direct consequence of MAJOR-1's
required correction).

**MINOR-2** — The plan's §2 baseline table description of `tests/conftest.py:60-66` and its own
later citation of `tests/triage_orchestrator_claims.py:42` are both accurate, but the plan does
not explicitly note (as the Contract's own §4/§14 rule 9 does) that any *new* test-local
`async_sessionmaker` M2's durability test constructs must itself carry `expire_on_commit=False` —
it is implied by "mirror the precedent exactly" but not stated as its own explicit checklist item
the way the Contract states it. Low risk, since the mandated precedent already gets this right,
but worth one explicit sentence for a future implementer who does not follow the precedent
literally.

### OBSERVATION

**OBSERVATION-1** — Every code-line citation checked in this pass (`workflows/runner.py:187`,
`:147-203`, `:262-288`; `capabilities/executor.py:111-147`, `:114`; `database/session.py:14`;
`tests/conftest.py:60-66`, `:65`; `tests/test_triage_orchestrator_claims.py:42`;
`tests/test_phase9_research_intelligence_integration.py:196-200`) matches the current repository
exactly. No stale or drifted citation was found anywhere in the plan.

**OBSERVATION-2** — The plan's explicit non-goals sections in both milestones correctly and
completely restate every hard constraint from this task's own instructions (no redesign, no
migration, no schema change, no scheduler, no crash recovery, no Capability/Gateway change) —
confirmed present and accurately scoped in both M1 and M2.

**OBSERVATION-3** — Phase 8/9 compatibility claims (Capability contracts unchanged, Gateway/
PromptRepository untouched, Research→Intelligence propagation improvement correctly described)
were independently re-verified and hold — `capabilities/research_capability.py` and
`capabilities/intelligence_capability.py` are correctly stated as needing zero code change, and no
milestone touches either file.

---

## 7. Required corrections

1. **Resolve MAJOR-1**: move the required Phase 9 M7 regression-lock test-assertion update
   (Contract §11) from M2 into M1's own scope — it is a direct, mechanical, non-concurrency-related
   consequence of M1's own code change and belongs in the same commit that causes it, not in the
   separately-motivated concurrency-proof milestone. Concretely: add
   `tests/test_phase9_research_intelligence_integration.py` to M1's "Files" (Tests) list; move the
   "Required Phase 9 M7 test update" bullet from M2's "Tests required" into M1's; add that file to
   M1's Definition of Done and Verification commands; remove the now-incorrect "continues to pass
   either way" claim from M1's Rollback safety section and replace it with an accurate statement
   (the test's assertion is updated together with the code change, in the same commit, so no
   broken-window state ever exists). M2 keeps only the independent-connection durability proof and
   the full-suite zero-regression sweep — its own rationale (isolating the highest-scrutiny
   concurrency proof) is undiminished by this move.
2. Update M1/M2's "Contract coverage" lines to reflect §11 moving to M1 (MINOR-1).
3. (Optional, minor) Add one explicit sentence to M2's Implementation scope stating that the new
   test-local `async_sessionmaker` must itself carry `expire_on_commit=False`, citing
   `tests/test_triage_orchestrator_claims.py:42` as the reason (MINOR-2).

No correction requires reconsidering the two-milestone structure itself, the Contract, or the
underlying per-step-persistence design — all are sound. This is a scheduling fix within an
otherwise-correct plan.

---

## 8. Final verdict

PHASE 9.5 PLANNING NOT READY — CORRECTIONS REQUIRED
