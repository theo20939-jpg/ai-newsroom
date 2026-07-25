# Phase 13 — M1 Milestone Report: EngagementCapability

## Status: GREEN

## Files changed (all within authorized §4 scope)

**Production (new)**: `capabilities/engagement_capability.py`, `prompts/engagement/v1.yaml`
**Production (modified, narrow)**: `capabilities/registry.py` (one import + one registration line)
**Tests (new)**: `tests/test_engagement_capability.py`
**Tests (modified)**: `tests/test_capability_registry.py` (append), `tests/test_openai_strict_schema_compliance.py` (append), `tests/test_phase9_research_intelligence_integration.py` (replace one obsolete test), `tests/test_phase10_capability_registration.py` (replace one assertion pair, add one test), `tests/test_phase9_cross_cutting_regression.py` (one-line sentinel substitution)

## Implementation-time finding (caught before landing, fixed within M1's own scope)

The Plan's §7.4 pseudocode, as literally drafted during planning, queued only 3 fake LLM
responses and asserted a 3-entry `step_results` list. Re-reading `workflows/definitions/
news_analysis.py` directly during M0/M1 revealed `NEWS_ANALYSIS` actually has **four**
capability-backed steps (`research`, `intelligence`, `engagement_analysis`, `scoring` — the
`scoring` step was already registered via `ScoringCapability` since Phase 8, `required=True` by
default), not three. Once `engagement_analysis` succeeds, the workflow now proceeds to and
requires a successful `scoring` step to reach `COMPLETED`. Fixed by queuing a 4th canonical
`{"score": 85, "rationale": "Broadly relevant."}` fake response (mirroring this repository's own
established scoring-fixture convention) and asserting all four step results. This is a narrow
implementation bug inside the approved design, not an architecture change — fixed autonomously
per the authorized fix policy.

A second, self-inflicted issue was caught and fixed during the sentinel RED/GREEN proof: the
first draft of the new replacement test's own section comment referenced the old, removed test's
name in prose ("supersedes the removed `test_real_news_analysis_still_fails_...`"), which
accidentally left the old sentinel string in the file text — this initially prevented the RED
proof from reproducing (the meta-test's old-sentinel exemption still matched). Corrected by
rewording the comment to not literally include the old function name; RED then reproduced exactly
as predicted.

## M1 Regression Matrix (§7.6) — all 8 rows green

1. EngagementCapability unit tests: `tests/test_engagement_capability.py` — 14 tests, all pass.
2. `CapabilityRegistry` resolves `"engagement"`: `tests/test_capability_registry.py::test_build_registry_resolves_engagement_once_registered`, `tests/test_phase10_capability_registration.py::test_build_registry_resolves_engagement_directly` — pass.
3. Genuinely-unknown capability still raises `UnknownCapabilityError`: `tests/test_phase10_capability_registration.py::test_unregistered_capability_still_raises_unknown_capability_error` (now using `"definitely_unregistered_capability"`) — pass.
4. Real `NEWS_ANALYSIS` no longer fails merely because `engagement_analysis` is unregistered: `tests/test_phase9_research_intelligence_integration.py::test_real_news_analysis_now_completes_through_engagement_analysis` — pass, `COMPLETED`, all 4 steps `SUCCESS`.
5. Existing Research/Intelligence behavior unchanged: `tests/test_phase9_research_intelligence_integration.py`'s other 3 tests, plus the full, unmodified `tests/test_workflow_runner.py` (12 tests) — all pass.
6. Strict-schema centralized compliance includes the new prompt: `tests/test_openai_strict_schema_compliance.py` — all pass, including the new `("engagement", "1", ...)` parametrization.
7. No `CONTENT_GENERATION` regression: `tests/test_phase10_workflow_integration.py` — all pass.
8. Phase 9 cross-cutting meta-test sentinel migration: `tests/test_phase9_cross_cutting_regression.py` — RED/GREEN-A/GREEN-B proof performed live (below), final state green.

## RED/GREEN sentinel proof (§7.7), performed live this milestone

- **RED**: with the sentinel temporarily reverted to the old name and the new positive test
  present, `pytest tests/test_phase9_cross_cutting_regression.py::test_no_phase9_test_pairs_
  real_news_analysis_with_completed_status` — **FAILED** (`offending_files ==
  ['test_phase9_research_intelligence_integration.py']`), confirming the problem is real.
- **GREEN A**: sentinel corrected to the new name — same test **PASSED**.
- **GREEN B**: a temporary, uncommitted file `tests/test_phase9_zz_scratch_sentinel_check.py`
  containing the forbidden `NEWS_ANALYSIS`+`COMPLETED`+`status ==` combination under an
  unauthorized name was added — the meta-test correctly **FAILED**, flagging it. The file was
  then deleted; `git status --short tests/test_phase9_zz_scratch_sentinel_check.py` confirms no
  trace remains.

## Full validation run this milestone

- `pytest tests/test_engagement_capability.py tests/test_capability_registry.py
  tests/test_openai_strict_schema_compliance.py
  tests/test_phase9_research_intelligence_integration.py
  tests/test_phase10_capability_registration.py tests/test_phase9_cross_cutting_regression.py`
  — **47 passed**.
- `pytest tests/test_phase10_workflow_integration.py tests/test_workflow_runner.py` — **13
  passed** (CONTENT_GENERATION + existing atomic-claim-adjacent suite, unaffected).
- `ruff check` on all 8 M1-touched files — **all checks passed**.
- `mypy` on the 2 changed/new production files — **no issues found**.
- `python -m scripts.validate_architecture` — **0 violations**.

## Deviations from the Plan

One: the §7.4 pseudocode's fake-response count/assertions were corrected from 3 to 4 steps
(documented above) — a mechanical bug-fix, not a design change; the Plan's own semantic intent
(prove all engagement-and-beyond steps succeed, `COMPLETED`) is fully preserved and, if anything,
more completely proven than the original 3-step draft would have been.

M1 complete. Continuing to M2.
