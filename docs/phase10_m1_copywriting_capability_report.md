# Phase 10 — Milestone M1 Report
## CopywritingCapability

**Status: implementation report.** Records what M1 actually built, against the frozen Architecture
Contract (`docs/phase10_production_content_pipeline_architecture_contract.md`, revision 3) and the
frozen Implementation Plan (`docs/phase10_implementation_plan.md`, Milestone 1). M0's prerequisites
(`docs/phase10_m0_repository_preparation_report.md`) were re-confirmed, not re-derived, before
writing code. No M2/M3/M4 work was started.

---

## 1. Implementation Summary

`CopywritingCapability` is implemented as an ordinary Phase 8 `Capability`, structurally identical
to `ResearchCapability`/`IntelligenceCapability`/`QualityCapability`:

- `CAPABILITY_NAME = "copywriting"`, `PROMPT_VERSION = "1"`.
- `COPYWRITING_CAPABILITY_DEFINITION`: `required_context=["news_event"]`,
  `expected_output_keys=["title", "body", "hashtags"]`, `config=CapabilityConfig(timeout_seconds=
  30)` — reusing the same `30` every existing `CapabilityDefinition` in this codebase already uses.
- `__init__(self, gateway: LLMGateway, prompt_repository: PromptRepository) -> None` — byte-identical
  shape to the three existing Capabilities; no `BudgetGuard`, no `CostTracker`.
- `_floor_validate()` — duplicated verbatim, per this codebase's established per-Capability
  convention (not factored into a shared helper, matching every existing Capability's own
  docstring rationale).
- `_format_research_context()` / `_format_intelligence_context()` — two small helpers, each
  mirroring `IntelligenceCapability._format_research_facts()`'s exact shape, including its
  "did not run" degradation branch when the corresponding `step_results` key is empty.
- `_build_request()` — reads `context.business.news_event.title`/`.category` only (never
  `.content`), plus `context.business.workflow_state.step_results.get("research", {})` and
  `.get("intelligence", {})`, and returns a `GenerateRequest` with `response_mode="json_schema"`,
  `response_schema=prompt.output_schema` — identical shape to every existing `_build_request()`.
- `execute()` — resolve prompt → build request → `call_generate()` → on error, log then raise → on
  success, `_floor_validate()` then raise `ValidationCapabilityError` or return
  `CapabilityResult(status="SUCCESS", ...)`. Copied line-for-line in control flow from
  `quality_capability.py`/`intelligence_capability.py`, with **zero deviation**.
- No import of `capabilities.research_capability` / `capabilities.intelligence_capability` /
  `database.session` / `sqlalchemy` / anything under `bot/` / any provider SDK.

`prompts/copywriting/v1.yaml` follows `prompts/quality/v1.yaml`'s exact top-level shape
(`name`/`version`/`system`/`rules`/`output_schema`). `output_schema.required` is exactly
`["title", "body", "hashtags"]`, matching `COPYWRITING_CAPABILITY_DEFINITION.expected_output_keys`
one-for-one, per Contract §6's binding matching rule.

---

## 2. Exact Files Changed

**Production files created** (both explicitly authorized by Contract §3):
- `capabilities/copywriting_capability.py` (new)
- `prompts/copywriting/v1.yaml` (new)

**Production files modified**: none.

**Test files created**:
- `tests/test_copywriting_capability.py` (new) — required by Contract §12's "Capability tests"
  list, assigned to Milestone 1 by the Implementation Plan §10.

**Docs files created**:
- `docs/phase10_m1_copywriting_capability_report.md` (this report).

No file outside this list was created or modified during M1.

---

## 3. Contract Requirements Implemented

Every item in Contract §5 ("CopywritingCapability Contract"):
- **Input, frozen**: reads exactly `step_results.get("research", {})` /
  `.get("intelligence", {})`, plus `news_event` title/category only — confirmed in
  `_build_request()`.
- **Output schema, frozen, binding**: `expected_output_keys = ["title", "body", "hashtags"]`;
  `prompts/copywriting/v1.yaml`'s `output_schema` matches exactly.
- **Forbidden, binding**: no import of Research/Intelligence Capabilities, no database session, no
  Telegram/`bot/` import, no forked execution/retry/error-translation logic — `call_generate()`,
  `CapabilityResult`/`CapabilityError`, and `PromptRepository.resolve()` are used exactly as every
  other Capability already uses them.

Contract §6 ("Prompt Ownership"): all prompt content lives in `prompts/copywriting/v1.yaml`;
`capabilities/copywriting_capability.py` contains zero embedded prompt strings;
`output_schema.required` equals `expected_output_keys` exactly.

Implementation Plan §3 (Milestone 1) — every named component (`CAPABILITY_NAME`, `PROMPT_VERSION`,
`COPYWRITING_CAPABILITY_DEFINITION`, `_floor_validate`, the two context-formatting helpers,
`_build_request`, `execute`) implemented exactly as planned, with no deviation from the plan's own
code sketch.

---

## 4. Tests Added

`tests/test_copywriting_capability.py`, 11 tests, mirroring
`tests/test_research_capability.py`/`tests/test_intelligence_capability.py`'s exact conventions
(`FakeLLMGateway` + `FakePromptRepository`, no real network call):

1. `test_execute_full_shape_end_to_end_reflects_upstream_output_in_prompt` — happy path; asserts
   `structured_output` matches `title`/`body`/`hashtags` exactly; proves Research's facts AND
   Intelligence's judgment both actually flowed into the built request text (not merely that the
   step ran).
2. `test_missing_step_results_does_not_raise` — empty `step_results` still succeeds; the built
   request states "did not run" rather than fabricating facts.
3. `test_validation_failure_raises_validation_capability_error_not_silent_success` — malformed
   response (`title` only) raises `ValidationCapabilityError`.
4. `test_construction_accepts_only_gateway_and_prompt_repository` — constructor signature check.
5. `test_repeated_execute_calls_produce_independent_uncontaminated_results` — no shared mutable
   state across calls.
6. `test_gateway_errors_are_translated_never_escape_raw` (parametrized, 4 cases) — every
   `GatewayError` is translated to the correct `CapabilityError` subtype, never escapes raw.
7. `test_failed_capability_call_is_preserved_via_logging_before_raising` — failed
   `CapabilityCall` is logged before the exception crosses `execute()`'s boundary.
8. `test_non_coupling_never_imports_research_or_intelligence_capability` — AST-based mechanical
   check (mirrors `test_intelligence_capability.py`'s own technique) that
   `capabilities/copywriting_capability.py` imports neither `research_capability` nor
   `intelligence_capability`.

This is the complete Contract §12 "Capability tests" list, applied to Copywriting. No test exceeds
Milestone 1's scope — no registry, no workflow, no `ContentDraft`, no CLI test was added.

---

## 5. Validation Results

- `python -m pytest tests/test_copywriting_capability.py -v` — **11 passed**.
- `python -m pytest` (full suite) — **684 passed**, 0 failed, 0 regressions.
- `python -m ruff check capabilities/copywriting_capability.py tests/test_copywriting_capability.py`
  — **All checks passed**.
- `python -m mypy capabilities/copywriting_capability.py` — **Success: no issues found**.
- `python -m mypy tests/test_copywriting_capability.py` — **Success: no issues found**.
- `python scripts/validate_architecture.py` — **clean: 0 forbidden-dependency violations**.

---

## 6. Deviations

None. Implementation matches the Contract and the Implementation Plan's Milestone 1 section exactly
— no redesign, no additional mandatory output field, no Telegram-specific formatting, no publishing
logic, no image/meme behavior.

---

## 7. Remaining Work — Explicitly Deferred

Not started in M1, per instruction:

- **M2 (Workflow Integration)**: `capabilities/registry.py`'s two-line registration,
  `workflows/definitions/content_generation.py`'s steps/timeout diff, `QualityCapability`'s
  `_build_request()` amendment, `prompts/quality/v2.yaml`. `CopywritingCapability` is **not yet
  registered** in `CapabilityRegistry` — `CapabilityRegistry.resolve("copywriting")` still raises
  `UnknownCapabilityError` today, exactly as before this milestone. This is expected and correct
  for M1's own scope.
- **M3 (ContentDraft)**: `schemas/content_draft.py`, `services/content_draft_service.py`.
- **M4 (Manual CLI)**: `scripts/run_content_generation.py`.

---

## 8. Git Scope Verification

`git status --short` (relevant lines only):
```
?? capabilities/copywriting_capability.py
?? prompts/copywriting/
?? tests/test_copywriting_capability.py
?? docs/phase10_m1_copywriting_capability_report.md
```
(All other untracked entries are pre-existing Phase 9/9.5/10 process documents from earlier in
this effort, unrelated to and untouched by M1.)

`git diff --name-only` — **empty**: no previously-tracked file was modified.

**Production files created**: `capabilities/copywriting_capability.py`, `prompts/copywriting/v1.yaml`
— both explicitly authorized by Contract §3. **Production files modified**: none. **Test files
created**: `tests/test_copywriting_capability.py`. **Docs files created**: this report. No
unauthorized production file was required or touched. No migration was created.

---

## Final Verdict

M1 PASSED — READY FOR REVIEW
