# Phase 10 — Milestone M2 Report
## Workflow Integration

**Status: implementation report.** Records what M2 actually built, against the frozen Architecture
Contract (`docs/phase10_production_content_pipeline_architecture_contract.md`, revision 3) and the
frozen Implementation Plan (`docs/phase10_implementation_plan.md`, Milestone 2). M1's output
(`docs/phase10_m1_copywriting_capability_report.md`) was treated as accepted and re-verified
against current repository source, not re-derived from scratch. No M3/M4 work was started.

---

## 1. Implementation Summary

`CopywritingCapability` (built in M1) is now registered, wired into the real
`CONTENT_GENERATION` workflow, and actually consumed by an amended `QualityCapability`:

- `capabilities/registry.py`: two lines added to `build_registry()` — one import, one
  `registry.register(...)` call — registering `CopywritingCapability` exactly as the four
  existing Capabilities are registered. Nothing else in the file changed.
- `workflows/definitions/content_generation.py`: `steps` expanded from 2 to 4
  (`research → intelligence → copywriting → quality`); `timeout_seconds` changed from `60` to
  `120` (the same value `NEWS_ANALYSIS` already declares for its own 4-step chain — reused, not
  new). `max_iterations`, `retry_policy`, `required_input` unchanged. `expected_output` extended
  to name Research's/Intelligence's contribution (an explicitly non-frozen implementation
  detail per Contract §3). The module docstring was corrected to describe the real 4-step chain
  instead of the stale 2-step description it carried from Phase 7.
- `capabilities/quality_capability.py`: `_build_request()` now additionally reads
  `context.business.workflow_state.step_results.get("copywriting", {})` via a new
  `_format_copywriting_draft()` helper (mirroring `IntelligenceCapability`'s
  `_format_research_facts()` shape and its "did not run" degradation exactly), and formats it
  into the same `context_text` block already built from `news_event` fields — the existing
  `news_event` lines are not removed. `PROMPT_VERSION` changed from `"1"` to `"2"`. Nothing else
  in the file changed: `__init__`, `execute()`'s control flow, `_floor_validate()`,
  `QUALITY_CAPABILITY_DEFINITION` (including `expected_output_keys=["passed", "issues"]`) are
  byte-for-byte unchanged.
- `prompts/quality/v2.yaml` (new): `output_schema` identical to v1's (`passed`/`issues`, both
  required); `system`/`rules` rewritten to instruct the model to assess the generated draft when
  present, falling back to the raw event when absent. `prompts/quality/v1.yaml` is untouched on
  disk (confirmed by `git status` showing no modification to it, and by a new test that resolves
  both versions and confirms their `system` text differs).

---

## 2. Exact Files Changed

**Production files modified** (all four explicitly authorized by Contract §3):
- `capabilities/registry.py`
- `workflows/definitions/content_generation.py`
- `capabilities/quality_capability.py`

**Production files created** (explicitly authorized by Contract §3):
- `prompts/quality/v2.yaml`

**Test files modified**:
- `tests/test_quality_capability.py` — one mechanical fix (see §7) plus six new tests for the
  amendment.

**Test files created**:
- `tests/test_phase10_capability_registration.py` — registry resolution tests.
- `tests/test_phase10_workflow_integration.py` — the four-step runtime/integration proof.

**Docs files created**:
- `docs/phase10_m2_workflow_integration_report.md` (this report).

No file outside this list was created or modified during M2. `capabilities/copywriting_capability.py`
and `prompts/copywriting/v1.yaml` (M1's files) were re-verified against current source but **not
modified** — no M1 defect was discovered.

---

## 3. Registry Integration

`capabilities/registry.py`'s `build_registry()` diff (exactly two lines, per Contract §3):

```python
from capabilities.copywriting_capability import COPYWRITING_CAPABILITY_DEFINITION, CopywritingCapability
```
added to the import block, and
```python
registry.register(COPYWRITING_CAPABILITY_DEFINITION, CopywritingCapability(gateway, prompt_repository))
```
added inside `build_registry()`, alongside the four existing `register()` calls, before
`registry.seal()`.

**Verified**: `CapabilityRegistry.resolve("copywriting")` now returns
`(COPYWRITING_CAPABILITY_DEFINITION, CopywritingCapability(...))`
(`tests/test_phase10_capability_registration.py::test_build_registry_resolves_copywriting_directly`).
Negative behavior preserved: `resolve("engagement")` and `resolve("no_such_capability")` both
still raise `UnknownCapabilityError`
(`test_unregistered_capability_still_raises_unknown_capability_error`). All five Capabilities
coexist in one sealed registry (`test_build_registry_resolves_all_five_capabilities`).

---

## 4. Workflow Definition — Before/After

Before:
```python
steps=[
    WorkflowStepDefinition(name="copywriting", capability="copywriting", timeout_seconds=30),
    WorkflowStepDefinition(name="quality", capability="quality", timeout_seconds=30),
],
...
timeout_seconds=60,
expected_output=["draft_content", "quality_report"],
```

After:
```python
steps=[
    WorkflowStepDefinition(name="research", capability="research", timeout_seconds=30),
    WorkflowStepDefinition(name="intelligence", capability="intelligence", timeout_seconds=30),
    WorkflowStepDefinition(name="copywriting", capability="copywriting", timeout_seconds=30),
    WorkflowStepDefinition(name="quality", capability="quality", timeout_seconds=30),
],
...
timeout_seconds=120,
expected_output=["research_summary", "intelligence_report", "draft_content", "quality_report"],
```

`max_iterations=3`, `retry_policy` (unchanged: `max_attempts=3, retry_delay_seconds=0,
retryable_error_types=["StepExecutionError"]`), and `required_input=["event_id"]` are all
unchanged, exactly as Contract §3 requires.

---

## 5. QualityCapability Amendment

- New helper `_format_copywriting_draft(copywriting_output)`: returns a "did not run" placeholder
  when empty, otherwise formats `title`/`body`/`hashtags`.
- `_build_request()` reads `context.business.workflow_state.step_results.get("copywriting", {})`
  and appends the formatted draft to `context_text`, after the existing `news_event`-derived
  lines (not replacing them).
- `PROMPT_VERSION = "1"` → `PROMPT_VERSION = "2"`.
- `__init__`, `execute()`'s control flow, `_floor_validate()`, `CapabilityResult` construction,
  and `QUALITY_CAPABILITY_DEFINITION` are byte-for-byte unchanged.
- `QualityCapability` still does not import `capabilities.copywriting_capability` anywhere
  (mechanically verified, §7).

---

## 6. Prompt v2 Details

`prompts/quality/v2.yaml`: `name: quality`, `version: "2"`. `output_schema` is **identical** to
v1's (`passed: boolean`, `issues: array`, both required) — confirmed programmatically
(`test_expected_output_keys_and_v2_schema_identical_to_v1`) that `v1.output_schema ==
v2.output_schema` and that `v2.output_schema["required"] ==
QUALITY_CAPABILITY_DEFINITION.expected_output_keys` exactly. `system`/`rules` differ from v1's
(confirmed distinct, not a duplicate) to instruct draft-aware assessment. `prompts/quality/v1.yaml`
is unmodified on disk and still independently resolvable via `resolve("quality", "1")`.

---

## 7. Tests Added/Modified

**One existing-test modification, documented per instruction** (`tests/test_quality_capability.py`):
`_prompt_repository()`'s registered `RenderedPrompt.version` changed from `"1"` to `"2"`. This is
a **direct, mechanical consequence** of the frozen Contract's own `PROMPT_VERSION` bump (§5.1) —
`QualityCapability.execute()` now calls `resolve(CAPABILITY_NAME, "2")` unconditionally, so the
fake must have a version `"2"` entry to resolve against. No assertion was weakened: all three
previously-failing tests (`test_execute_full_shape_end_to_end`,
`test_validation_failure_raises_validation_capability_error_not_silent_success`,
`test_repeated_execute_calls_produce_independent_uncontaminated_results`) assert exactly what they
asserted before this change.

**New tests, `tests/test_quality_capability.py`** (6, Contract §12 "QualityCapability adaptation
tests"):
1. `test_built_request_includes_copywriting_draft_when_present` — built request contains
   Copywriting's `title`/`body`/`hashtags` when `step_results["copywriting"]` is non-empty.
2. `test_built_request_still_includes_news_event_fields_when_copywriting_absent` — empty
   `step_results` still succeeds and still includes `news_event.title`/`category`/`summary`.
3. `test_prompt_version_resolves_to_2` — `PROMPT_VERSION == "2"`.
4. `test_v1_prompt_remains_on_disk_and_still_independently_resolvable` — real
   `FilePromptRepository` resolves both `"1"` and `"2"`, with genuinely different `system` text.
5. `test_expected_output_keys_and_v2_schema_identical_to_v1` — output contract unchanged.
6. `test_non_coupling_never_imports_copywriting_capability` — AST-based mechanical check.

**New file, `tests/test_phase10_capability_registration.py`** (3, Contract §12 "Registry
resolution tests"):
1. `test_build_registry_resolves_copywriting_directly`
2. `test_build_registry_resolves_all_five_capabilities`
3. `test_unregistered_capability_still_raises_unknown_capability_error`

**New file, `tests/test_phase10_workflow_integration.py`** (1, Contract §12 "Workflow tests" — the
Step 8 runtime/integration proof, detailed in §13 below):
1. `test_content_generation_reaches_completed_in_exact_step_order`

No test exceeds M2's scope — no `ContentDraft`, no CLI test was added.

---

## 8. Focused Test Results

```
tests/test_quality_capability.py ................ 11 passed
tests/test_phase10_capability_registration.py .... 3 passed
tests/test_phase10_workflow_integration.py ....... 1 passed
tests/test_copywriting_capability.py ............. 11 passed  (M1 regression check)
```
26/26 passed.

Additionally re-ran, unmodified, all pre-existing tests identified in Step 1 as potentially
affected: `test_phase9_capability_registration.py`, `test_workflow_registry.py`,
`test_capability_registry.py`, `test_phase8_cross_cutting_regression.py`,
`test_phase9_cross_cutting_regression.py`, `test_phase9_research_intelligence_integration.py`,
`test_capability_boot_wiring_e2e.py`, `test_capability_testing_convention.py` — all 46 tests
passed with **zero further modification** required beyond the one documented mechanical fix in §7.

Phase 9.5 WorkflowRunner persistence regression (`tests/test_workflow_runner_per_step_persistence.py`)
— all 6 tests passed, unmodified.

---

## 9. Full Regression Results

```
python -m pytest -q
694 passed in 365.65s (0:06:05)
```
694 = the 684 baseline from the M1 report plus the 10 new tests this milestone added (6 in
`test_quality_capability.py` + 3 in `test_phase10_capability_registration.py` + 1 in
`test_phase10_workflow_integration.py`). Zero failures, zero regressions.

---

## 10. Ruff Result

```
python -m ruff check .
All checks passed!
```

---

## 11. Mypy Result

```
python -m mypy capabilities/registry.py capabilities/quality_capability.py workflows/definitions/content_generation.py
Success: no issues found in 3 source files

python -m mypy tests/test_quality_capability.py tests/test_phase10_capability_registration.py tests/test_phase10_workflow_integration.py
Success: no issues found in 3 source files
```
(Two `dict[str, object]` type annotations were added to test-local dict literals to satisfy
mypy's invariant-dict-argument checking — a type-annotation-only change, no behavior change.)

---

## 12. Architecture Validator Result

```
python scripts/validate_architecture.py
validate_architecture: clean - 0 forbidden-dependency violations under C:\Users\Theodor\ai-newsroom

python -m scripts.validate_architecture
validate_architecture: clean - 0 forbidden-dependency violations under C:\Users\Theodor\ai-newsroom
```
Both invocation forms confirmed clean.

---

## 13. Four-Step Runtime/Integration Proof

`tests/test_phase10_workflow_integration.py::test_content_generation_reaches_completed_in_exact_step_order`
runs the **real, production** `WorkflowType.CONTENT_GENERATION` definition (as amended by this
milestone) through the **real, unmodified** `WorkflowRunner`, `CapabilityExecutor`, and
`CapabilityRegistry` (via `build_registry()`), against the real, default `workflows.registry.registry`
singleton — not a synthetic `WorkflowType`. Only `FakeLLMGateway` stands in for the network; no
live external LLM API is used.

Proven, with concrete assertions against each step's actually-built request text (not merely a
`SUCCESS`/`COMPLETED` status check):

1. **Research output is available to Intelligence** — Intelligence's built request
   (`gateway.received_requests[1]`) contains every fact from `CANONICAL_RESEARCH_OUTPUT`, and does
   not say "did not run."
2. **Upstream results are available to Copywriting as defined by its contract** — Copywriting's
   built request (`received_requests[2]`) contains Research's facts AND Intelligence's `angle`/
   `recommendation`.
3. **Copywriting output is available to Quality in the same uninterrupted workflow execution** —
   Quality's built request (`received_requests[3]`) contains Copywriting's `title`/`body`.
4. **Quality actually receives/evaluates the generated Copywriting content** — same assertion as
   (3), plus confirmation Quality does not fall back to its "did not run" branch.
5. **The workflow reaches `COMPLETED` when all four capabilities succeed** — `result.status ==
   "COMPLETED"`, step order is exactly `["research", "intelligence", "copywriting", "quality"]`,
   all four `step_results` entries are `SUCCESS` with the expected structured output.

This proof does **not** claim `ContentDraft` persistence — no `ContentDraft` row is created or
referenced anywhere in this test or in any M2 production file. That remains M3's responsibility.

---

## 14. Scope Audit

`git diff --name-only` (tracked files modified):
```
capabilities/quality_capability.py
capabilities/registry.py
tests/test_quality_capability.py
workflows/definitions/content_generation.py
```
Exactly three of the four Contract §3-authorized existing files, plus the one test file modified
for the documented mechanical reason (§7). No other tracked file was touched.

`git status --short` (new files, M2-relevant subset):
```
?? prompts/quality/v2.yaml
?? tests/test_phase10_capability_registration.py
?? tests/test_phase10_workflow_integration.py
?? docs/phase10_m2_workflow_integration_report.md
```
`prompts/quality/v2.yaml` is the one authorized new production file. The two new test files and
this report are the only other additions.

M1's own files (`capabilities/copywriting_capability.py`, `prompts/copywriting/`,
`tests/test_copywriting_capability.py`, `docs/phase10_m1_copywriting_capability_report.md`) appear
unchanged in `git status` and were not modified. Every other untracked entry is a pre-existing
Phase 9/9.5/10 process document from earlier sessions, unrelated to and untouched by M2.

**Verified**: M2 production changes are limited to exactly `workflows/definitions/
content_generation.py`, `capabilities/quality_capability.py`, `capabilities/registry.py`, and
`prompts/quality/v2.yaml` — the authorized scope, no more, no less. No unauthorized production
file was required.

---

## 15. Self-Audit Answers

1. **Can `CapabilityRegistry.resolve("copywriting")` now succeed?** Yes — confirmed directly.
2. **Does an unknown capability still fail correctly?** Yes — `"engagement"` and
   `"no_such_capability"` both still raise `UnknownCapabilityError`.
3. **Is `CONTENT_GENERATION` exactly `research → intelligence → copywriting → quality`?** Yes —
   declared in the definition and proven by the integration test's step-order assertion.
4. **Does `QualityCapability` actually read `step_results["copywriting"]`?** Yes — proven both in
   isolation (unit test) and inside the real four-step chain (integration test).
5. **Does Quality use v2 while v1 remains untouched?** Yes — `PROMPT_VERSION == "2"`;
   `prompts/quality/v1.yaml` is unmodified on disk and independently resolvable, with genuinely
   different content from v2.
6. **Does same-pass `step_results` propagation work across all four steps?** Yes — proven for
   every adjacent pair (Research→Intelligence, Research/Intelligence→Copywriting,
   Copywriting→Quality) within one uninterrupted `WorkflowRunner.run()` call.
7. **Can the four-step workflow reach `COMPLETED` using the real internal execution stack with
   fakes?** Yes — `result.status == "COMPLETED"`, real `WorkflowRunner`/`CapabilityExecutor`/
   `CapabilityRegistry`, `FakeLLMGateway` only.
8. **Did M2 modify any unauthorized production file?** No — scope audit confirms exactly the four
   authorized files.
9. **Did M2 introduce any migration, scheduler, Telegram, meme/image, `ContentDraft`, or CLI
   work?** No — none of these appear anywhere in M2's diff.
10. **Did any frozen architecture contract change?** No —
    `docs/phase10_production_content_pipeline_architecture_contract.md` was not modified (confirmed
    via `git status`: still untracked/unchanged, not `M`).

No defect was discovered requiring a stop.

---

## 16. Deferred Work — Explicitly Deferred to M3/M4

- **M3 (`ContentDraft`)**: `schemas/content_draft.py`, `services/content_draft_service.py`. No
  `ContentDraft` row is created anywhere by M2; the mechanical "no file under `capabilities/`
  imports `ContentDraft`" check remains M3's own test obligation.
- **M4 (Manual CLI)**: `scripts/run_content_generation.py`. Not started.

---

## 17. Discovered Limitations

None beyond what M0 and M1 already disclosed. No genuine M1 defect was found during M2's
pre-implementation re-verification (Step 1) or afterward — `capabilities/copywriting_capability.py`
and `prompts/copywriting/v1.yaml` were re-read and re-confirmed correct, unmodified.

---

## Commit Discipline

Per instruction, M2 is **not** automatically committed. Neither the frozen Architecture Contract
nor the frozen Implementation Plan mandates a git commit per milestone — no such requirement was
found in either document. The exact M2-scoped staged set, if a commit is later requested, would be:

```
capabilities/quality_capability.py          (modified)
capabilities/registry.py                    (modified)
workflows/definitions/content_generation.py (modified)
tests/test_quality_capability.py            (modified)
prompts/quality/v2.yaml                     (new)
tests/test_phase10_capability_registration.py (new)
tests/test_phase10_workflow_integration.py    (new)
docs/phase10_m2_workflow_integration_report.md (new)
```
No unrelated/untracked Phase 10 documentation from earlier sessions would be staged alongside it.

---

## Final Verdict

M2 COMPLETE — READY FOR REVIEW
