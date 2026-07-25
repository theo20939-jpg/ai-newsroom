# Phase 13 — Final Test-Scope Completeness Re-Audit

Narrow, targeted re-audit of `docs/phase13_automatic_news_analysis_implementation_plan.md`'s
Correction Pass 2 (which added `tests/test_phase9_research_intelligence_integration.py` and
`tests/test_phase10_capability_registration.py` to scope, resolving Final Re-Audit findings RA-1
and RA-2). Does not re-audit the whole architecture — only the completeness of the test-scope
correction and its own second-order effects. All source files below were re-read directly this
session, not trusted from any prior report. No Plan, Contract, source, test, or migration file was
modified. No worker started, no live API call made, nothing committed.

## 1. Executive Verdict

RA-1 and RA-2 are correctly identified and correctly designed (Checks 1-2: PASS). The exact
test-file count (10) and production-file count (8) are both independently re-verified and correct
(Checks 6-7: PASS). Strict-schema coverage remains intact and non-regressed (Check 5: PASS). All
previously-fixed MAJOR/MINOR findings remain resolved with no textual regression (Check 9: PASS).

However, Check 3 (meta-test/sentinel impact) found that the Plan's own §7.4 replacement design —
which Correction Pass 2 explicitly required to "prove final task reaches COMPLETED when all fake
outputs are valid" — reintroduces, in a **new** function, the exact three-token combination
(`"NEWS_ANALYSIS"`, `'"COMPLETED"'`, `"status =="`) that
`tests/test_phase9_cross_cutting_regression.py::test_no_phase9_test_pairs_real_news_analysis_
with_completed_status` static-scans for and flags — and the Plan's own removal of the old test
function (§4/§7.4's own "remove... in full") simultaneously deletes that meta-test's only
whitelist marker for this file. This is a real, mechanical, certain test failure, not
speculative: verified by literal substring simulation against the Plan's own planned code text,
below. `tests/test_phase9_cross_cutting_regression.py` is not currently in the Plan's file scope.

This is a direct second-order consequence of the immediately-prior correction pass, of the exact
same class (RA-1/RA-2) it was meant to fully close out — a third file in the same dependency
chain, one level removed. **CRITICAL = 0, MAJOR = 1 (new). Approval threshold (MAJOR = 0) is not
met.**

## 2. Phase 9 Test Verification (Check 1)

Re-read `tests/test_phase9_research_intelligence_integration.py:368-394` directly this session.
Confirmed byte-for-byte identical to the Plan's own citation: `test_real_news_analysis_still_
fails_at_engagement_analysis_step` runs the real `NEWS_ANALYSIS` `WorkflowDefinition` through the
real, unmodified `WorkflowRunner`/`build_registry()`, asserting `result.status == "FAILED"` and
`step_results[2].status == "FAILED"  # "engagement" is not a registered Capability`. This
genuinely becomes false the instant M1 registers `"engagement"` — reconfirmed, not merely
re-trusted.

The Plan's §7.4 replacement (`test_real_news_analysis_now_completes_through_engagement_analysis`)
correctly preserves and extends the original integration value: real `NEWS_ANALYSIS`, real
`WorkflowRunner`, real `CapabilityExecutor`, real `CapabilityRegistry` via `build_registry()`, a
controlled `FakeLLMGateway` boundary (three queued responses, one per capability-backed step).
It proves, exactly as required: (1) all 3 steps execute in order
(`["research", "intelligence", "engagement_analysis"]`); (2) `EngagementCapability` resolves and
executes successfully (`step_results[2].status == "SUCCESS"`); (3) upstream propagation
(an explicit "did not run" absence check on Engagement's own request text, mirroring this file's
own established pattern for the Research→Intelligence propagation proof); (4) the task reaches
`COMPLETED` with valid fake outputs. **Design: PASS.**

**Hidden string-sentinel/meta-test impact**: found — see §4 (Check 3) below. This is the one
genuine gap in an otherwise sound replacement design.

## 3. Phase 10 Test Verification (Check 2)

Re-read `tests/test_phase10_capability_registration.py` in full directly this session (88 lines).
Confirmed: `test_unregistered_capability_still_raises_unknown_capability_error` (lines 72-87)
genuinely uses `"engagement"` (line 84) as its intentionally-unregistered example, with a
docstring explicitly citing Contract §3's own use of that name. This genuinely becomes stale after
Phase 13 registration — reconfirmed.

The Plan's §7.5 replacement preserves both required invariants without weakening either:
- **Invariant A** (engagement now resolves): a new, separate test,
  `test_build_registry_resolves_engagement_directly`, proves
  `registry.resolve(ENGAGEMENT_CAPABILITY_NAME)` succeeds and returns an `EngagementCapability`
  instance — mirrors the file's own existing `test_build_registry_resolves_copywriting_directly`
  pattern exactly. (This revision's own text also now specifies the exact required import,
  `from capabilities.engagement_capability import CAPABILITY_NAME as
  ENGAGEMENT_CAPABILITY_NAME`, matching this file's own established per-capability aliasing
  convention — verified against the real file's own import block, lines 15-22.)
- **Invariant B** (genuinely-unknown names still raise): the same test function is retained, only
  its `"engagement"` case is swapped for `"definitely_unregistered_capability"` — a real,
  independently-verified precedent already used in this exact repository for this exact situation
  (`tests/test_boot_assembly.py:61-66`, re-read this session, confirmed: "'research' was an
  unregistered-name example when this test was written; Phase 9 M6 legitimately registers it...
  so a genuinely-unregistered name is used here instead"). The `"no_such_capability"` case and
  every other test in the file (`test_build_registry_resolves_copywriting_directly`,
  `test_build_registry_resolves_all_five_capabilities`) are explicitly untouched, and the Plan
  explicitly forbids renaming the latter to "six" or adding `EngagementCapability` to its loop —
  correctly out of scope.

No assertion weakening. No skip/xfail anywhere in the design. **PASS.**

## 4. Meta-Test / Sentinel Verification (Check 3) — **source of the new finding**

Re-read `tests/test_phase9_cross_cutting_regression.py` in full directly this session (85 lines).
`test_no_phase9_test_pairs_real_news_analysis_with_completed_status` (lines 64-84) globs every
`test_phase9_*.py` file (excluding itself), and flags (`offending_files.append`) any file whose
raw text contains all three of `"NEWS_ANALYSIS"`, `'"COMPLETED"'`, and `"status =="`, **unless**
the literal string `"test_real_news_analysis_still_fails_at_engagement_analysis_step"` also
appears in that file's text (line 81). The final assertion is `assert offending_files == []`.

Grepped the repository this session for every reference to the sentinel function name and for the
three trigger tokens together — confirmed the sentinel string's only purpose anywhere in the
repository is this one whitelist check (`tests/test_phase9_cross_cutting_regression.py:81`); it
is not referenced, imported, or asserted against anywhere else.

**The Plan's own two changes to `tests/test_phase9_research_intelligence_integration.py`, applied
together, trip this meta-test**:

1. §4/§7.4 requires *full removal* of `test_real_news_analysis_still_fails_at_engagement_analysis_
   step` and its section comment — this deletes the file's only occurrence of the whitelist
   sentinel string, `"test_real_news_analysis_still_fails_at_engagement_analysis_step"`.
2. §7.4's own replacement, `test_real_news_analysis_now_completes_through_engagement_analysis`, is
   explicitly required (by this same correction pass) to prove the task "reaches `COMPLETED` when
   all fake outputs are valid" — its planned code (reproduced verbatim in the Plan) contains
   `workflow_type=WorkflowType.NEWS_ANALYSIS` and `assert result.status == "COMPLETED"`.

Simulated the meta-test's own three-token check directly against the Plan's own planned
replacement source text (not against a hypothetical — the Plan's §7.4 code block itself):

- `"NEWS_ANALYSIS" in text` → **True** (`WorkflowType.NEWS_ANALYSIS`, present as a literal
  case-sensitive substring inside `WorkflowType.NEWS_ANALYSIS`).
- `'"COMPLETED"' in text` → **True** (`assert result.status == "COMPLETED"` contains the literal
  quoted substring).
- `"status ==" in text` → **True** (`result.status ==` contains it).
- `"test_real_news_analysis_still_fails_at_engagement_analysis_step" not in text` → **True**,
  because the Plan's own §4/§7.4 requires this exact string's sole occurrence (the old function
  name) to be deleted, not retained.

All four conditions the meta-test checks resolve to exactly the values that cause
`offending_files.append("test_phase9_research_intelligence_integration.py")`, and therefore
`assert offending_files == []` **fails**.

This was previously analyzed in the Final Re-Audit (RA-1 finding, §6) — but that analysis
correctly modeled only a *pure deletion* (no replacement, or a replacement that does not itself
claim `COMPLETED`), and concluded no companion edit was mechanically required. Correction Pass 2
then added the requirement that the replacement *must* prove `COMPLETED` (a genuinely correct and
necessary requirement in its own right — the whole point of the replacement is to be a positive
completion proof) — which is precisely the change that reintroduces the trigger condition the
original RA-1 analysis had ruled out. This is not a flaw in either individual correction; it is an
emergent interaction between them that neither correction pass's own scope required it to check
in isolation.

**This is a MAJOR finding (Check 3's own pre-stated bar: "If another test will fail mechanically:
MAJOR").**

## 5. Broad Test Impact Search (Check 4)

Independently re-grepped the entire `tests/` directory (not scoped to `test_phase9_*`/
`test_phase10_*`) this session for: `engagement`, `engagement_analysis`, `EngagementCapability`,
`UnknownCapabilityError`, `NEWS_ANALYSIS`, hardcoded capability-count/registry-key-set patterns
(`.keys()`, `set(...) ==`, `all_capabilities`, `registered_names`), and workflow step-count/order
assertions.

| Hit | Classification | Reason |
|---|---|---|
| `tests/test_phase9_research_intelligence_integration.py::test_real_news_analysis_still_fails_at_engagement_analysis_step` | **AFFECTED** | RA-1, already in scope (§4/§7.4) |
| `tests/test_phase10_capability_registration.py::test_unregistered_capability_still_raises_unknown_capability_error` | **AFFECTED** | RA-2, already in scope (§4/§7.5) |
| `tests/test_phase9_cross_cutting_regression.py::test_no_phase9_test_pairs_real_news_analysis_with_completed_status` | **AFFECTED (new, TS-1)** | Meta-test tripped by the interaction of §7.4's own two required changes — see §4 above. Not currently in scope. |
| `tests/test_boot_assembly.py:65`, `tests/test_capability_boot_wiring_e2e.py:162` | UNAFFECTED | Both already use safe, genuinely-unregistered placeholder names (`"definitely_unregistered_capability"`, `"no_such_capability"`), re-confirmed this session — never `"engagement"` |
| `tests/test_capability_mapping.py:29`, `tests/test_ai_execution_mapper.py:48` | UNAFFECTED | Both exercise `resolve_ai_capability("engagement") == AICapability.INTELLIGENCE`, an unrelated cost-accounting bucket mapping independent of `CapabilityRegistry` state |
| `tests/test_phase9_research_intelligence_integration.py::test_both_capabilities_dispatch_in_order_and_synthetic_task_completes` (`["research", "intelligence"]`, line 197) | UNAFFECTED | Uses a synthetic 2-step `workflow_registry` (`_synthetic_research_intelligence_registry()`) that never declares an `engagement_analysis` step at all, with `workflow_type=WorkflowType.DAILY_DIGEST` used only as a task-type label — re-confirmed this session |
| `tests/test_phase10_workflow_integration.py::test_content_generation_reaches_completed_in_exact_step_order` | UNAFFECTED | Tests `WorkflowType.CONTENT_GENERATION`, not `NEWS_ANALYSIS` — re-confirmed this session |
| `tests/test_phase9_cross_cutting_regression.py::test_full_boot_sequence_resolves_all_four_capabilities` | UNAFFECTED (pre-existing, out of scope) | Does not enumerate `CopywritingCapability` either — a pre-existing, non-Phase-13-caused gap (§25's own "escalate, don't fix" rule), unrelated to `EngagementCapability` |
| `tests/test_capability_registry.py:64,96`, `tests/test_capability_errors.py:37`, `tests/test_phase9_capability_registration.py:95`, `tests/test_quality_capability.py:180` (`UnknownCapabilityError` hits) | UNAFFECTED | None use `"engagement"` as their example name — re-checked each site this session |
| Registry key-set / capability-count hardcoding search (`.keys()`, `set(...) ==`, etc.) | UNAFFECTED | No hit anywhere in `tests/` enumerates or counts `CapabilityRegistry`'s registered names as a set/list assertion |

**No 12th affected file found. TS-1 (§4 above) is the only new finding from this broader search —
every other candidate is either already in scope (RA-1/RA-2) or independently confirmed
unaffected.**

## 6. Strict-Schema Coverage (Check 5)

Re-confirmed `tests/test_openai_strict_schema_compliance.py` remains in the Plan's file scope
(§4, §7 target-files list, §19), with the same, unchanged, single-tuple addition
(`("engagement", "1", ENGAGEMENT_CAPABILITY_DEFINITION)`) to `_ACTIVE_STRUCTURED_OUTPUT_
CAPABILITIES`, unaffected by Correction Pass 2's own changes (which only touched the two
capability-registration-adjacent files, not this one). **No regression from the previous
correction. PASS.**

## 7. Exact File Scope (Check 6, Check 7)

**Test files — independently re-derived from §4's table, all 10 listed by exact path:**

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

Count: 4 new (1, 3, 4, 6) + 6 modified (2, 5, 7, 8, 9, 10) = **10, matches the Plan's claimed
count exactly, path-for-path.** §28's own arithmetic is internally consistent with §4's table.
**Check 6: PASS on the claimed count** — but see §10/TS-1: the count is *complete relative to
what the Plan currently authorizes*, while itself missing one more required file
(`tests/test_phase9_cross_cutting_regression.py`) uncovered by this audit — so the true required
count, once TS-1 is corrected, is 11, not 10. This is reported as MAJOR in §10, not as a
"count/path mismatch" under Check 6's own MAJOR/MINOR split, since the omission's root cause is a
missing file, not an arithmetic error in tallying the currently-listed ones.

**Production/runtime — independently re-derived from §4's table**: `capabilities/engagement_
capability.py` (new), `worker/analysis_main.py` (new), `worker/analysis_cycle.py` (new),
`prompts/engagement/v1.yaml` (new) = 4 new; `workflows/runner.py`, `capabilities/registry.py`,
`core/config.py`, `docker-compose.yml` = 4 modified. **4 + 4 = 8, matches exactly. No new
production file was made necessary by the test corrections in Correction Pass 2 (RA-1/RA-2 were,
and TS-1 below is, entirely test-file scoped). Check 7: PASS, no regression.**

## 8. M1 Atomicity (Check 8)

Re-read §7's binding "M1 atomic test ownership" rule and §7.6's Regression Matrix. Confirmed all
eight items Check 8 lists are named: `EngagementCapability`, the prompt, the registration,
`tests/test_engagement_capability.py`, the registry positive/unknown-name tests (§7.5), the
centralized strict-schema registration, and both the Phase 9 (§7.4) and Phase 10 (§7.5)
stale-expectation replacements — all required to land together, with an explicit prohibition on
any "registration lands, tests fixed later" ordering. §12's M6 gate independently re-runs both
files, focused, before the full suite.

**Gap**: this atomicity rule, as currently written, does not include
`tests/test_phase9_cross_cutting_regression.py` — because that file is not yet in scope at all
(TS-1). Once TS-1 is corrected, the same atomicity rule must be extended to cover it (M1 cannot be
"done" while the meta-test is red either). Logged here as a direct consequence of TS-1, not scored
as a second, separate finding.

## 9. Previous-Fix Non-Regression (Check 9)

Narrow textual re-check only, as instructed (not a full empirical re-derivation, since Checks 1-3
of the Final Re-Audit already did that empirically and nothing in Correction Pass 2 touched
§8.1/§9.1/§14):

- `.as_string()` remains the sole frozen JSON-scalar syntax in the live query (§9.1, line
  `EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value`);
  `.astext`/`cast(..., String)` appear only inside the retired RED-proof narrative, not as
  implementation guidance — confirmed by direct grep this session. **Unchanged.**
- SQL-side 48h freshness filtering, deterministic `ORDER BY`, and `LIMIT settings.news_analysis_
  batch_size` remain present and unchanged in §9.1. **Unchanged.**
- The exact-task M7 procedure (§14) and its "the batch worker... is **not started** for M7"
  clause, and the explicit BLOCKED fallback, remain present and textually unchanged by Correction
  Pass 2 (which touched only §1, §4, §7, §7.4-§7.6, §12, §19, §26, §28, §29 — never §14).
  **Unchanged.**
- `tests/test_openai_strict_schema_compliance.py` remains in scope (§6 above). **Unchanged.**

**No regression found in any previously-fixed finding. PASS.**

## 10. Findings

### CRITICAL

None.

### MAJOR

**ID: TS-1**
**SEVERITY: MAJOR**
**PLAN LOCATION**: §4 (Exact File Scope) — no row exists for
`tests/test_phase9_cross_cutting_regression.py`; §7.4 (the replacement test design that triggers
this, as currently written).
**SOURCE EVIDENCE**: `tests/test_phase9_cross_cutting_regression.py:64-84`,
`test_no_phase9_test_pairs_real_news_analysis_with_completed_status` — re-read in full this
session. Flags any `test_phase9_*.py` file (other than itself) whose text contains
`"NEWS_ANALYSIS"`, `'"COMPLETED"'`, and `"status =="` together, unless the literal string
`"test_real_news_analysis_still_fails_at_engagement_analysis_step"` also appears in that file.
Cross-checked against the Plan's own §4/§7.4 text (this session, not hypothetical): §4 requires
full removal of that exact sentinel string (with its test function); §7.4's own replacement code,
quoted verbatim in the Plan, contains `workflow_type=WorkflowType.NEWS_ANALYSIS` and
`assert result.status == "COMPLETED"`.
**PROBLEM**: Once M1's §7.4 correction lands as currently specified, `tests/test_phase9_research_
intelligence_integration.py`'s file text satisfies all three of the meta-test's trigger
conditions, and no longer contains the one string that would exempt it — a direct, mechanical,
certain consequence of combining §4's "remove in full" instruction with §7.4's own
completion-proof requirement, neither of which is wrong in isolation.
**IMPACT**: `tests/test_phase9_cross_cutting_regression.py::test_no_phase9_test_pairs_real_news_
analysis_with_completed_status` fails the instant M1's §7.4 correction lands — a third,
previously-unlisted, currently-passing test breaks as a mechanical consequence of Phase 13's own
new code, for exactly the same underlying reason class as RA-1/RA-2. M1's own Regression Matrix
(§7.6) does not currently check this file, so M1 could be declared "done" (all seven §7.6 rows
green) while this eighth, unlisted obligation is red — and M6's own gate (full pytest, zero
failures) would then fail. A fresh autonomous implementer following only the current Plan would
hit this exactly at M1, with no scoped instruction for how to resolve it — reintroducing the same
class of undocumented-decision risk RA-1/RA-2 were meant to close out.
**REQUIRED CORRECTION**: Add `tests/test_phase9_cross_cutting_regression.py` to §4 as a narrow
MODIFY edit, scoped to M1, updating exactly the whitelist condition at line 81 (currently
`if "test_real_news_analysis_still_fails_at_engagement_analysis_step" not in text:`) to reference
the new, positive replacement test's own name instead (`test_real_news_analysis_now_completes_
through_engagement_analysis`) — the same fragile-but-already-established name-string-sentinel
mechanism this file already uses, extended by one name swap, not redesigned. No other line, and no
other test in this file (`test_full_boot_sequence_resolves_all_four_capabilities`), is authorized
to change. §7.6's M1 Regression Matrix and §12's M6 focused-regression list must both be extended
to include this file, mirroring exactly how RA-1/RA-2 were incorporated. §28's exact file counts
must be recalculated once this is added (test-file total would become 11, not 10; grand total 19,
not 18) — not performed in this audit-only session.

### MINOR

None new.

### OBSERVATIONS

**TS-O1**: The docstring `test_no_phase9_test_pairs_real_news_analysis_with_completed_status`
would carry after a minimal name-swap fix would still describe a Phase-9-era rule ("no test
*added by Phase 9*... may assert NEWS_ANALYSIS reaches COMPLETED") that is now, in spirit,
superseded by Phase 13's own intentional, correct exception. The minimal required correction
(swap the whitelisted name) does not require rewriting this docstring for TS-1 to be resolved, but
a future implementer should consider a short docstring note acknowledging Phase 13 as the second,
now-intentional exception, for readability. Non-blocking.

**TS-O2**: This is the second time in three consecutive audit passes that a fix for one
mechanically-broken test has, on its own follow-up audit, been found to mechanically break a
different, adjacent test (RA-1's own fix triggering TS-1). This suggests the underlying class of
risk — string/name-based static sentinels scanning sibling test files — is not yet exhaustively
enumerated by a single grep pass. Recommended, but not required for approval: once TS-1 is
corrected, run one more targeted grep specifically for any *other* static-scan/meta-test file in
`tests/` that inspects sibling file text for name-based sentinels (not just
`test_phase9_cross_cutting_regression.py`), to positively rule out a fourth instance before
declaring the chain closed. Not elevated to a finding here because no such fourth file was found in
this session's own Check 4 broad search — the concern is about audit process thoroughness, not a
concrete, located defect.

## 11. Readiness Score

**7/10.** Both RA-1/RA-2 corrections are verified sound and complete for what they directly touch;
the test-file and production-file counts are independently re-derived and exactly match the Plan's
own claims; no previously-fixed finding has regressed. The score is held below approval by exactly
one new, real, mechanically-certain MAJOR finding (TS-1) — a second-order consequence of the RA-1
fix, narrow in scope (one line in one file, a name swap using an already-established pattern in
the same codebase) but not optional, since M6's own "zero failures" gate cannot be satisfied while
it exists.

## 12. Final Verdict

**Git status** (`git status --short`, read-only, run this session): only untracked, pre-existing
Phase 9/9.5/10/11 governance-backlog files, the untracked Phase 13 governance chain (Discovery,
Decision Resolution, Architecture Contract, Contract Audit, Implementation Plan, Implementation
Plan Audit, Final Re-Audit, and this new test-scope final re-audit file) appear. No source file,
test file, or migration is modified. Nothing staged. Nothing committed.

PHASE 13 IMPLEMENTATION PLAN NOT READY — CORRECTIONS REQUIRED
