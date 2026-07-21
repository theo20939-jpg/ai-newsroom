# Phase 10 — Milestone M4 Report
## Manual Content Generation CLI

**Status: implementation report.** Records what M4 actually built, against the frozen Architecture
Contract (`docs/phase10_production_content_pipeline_architecture_contract.md`, revision 3) and the
frozen Implementation Plan (`docs/phase10_implementation_plan.md`, Milestone 4). M3's output
(`docs/phase10_m3_content_draft_report.md`) was treated as accepted and re-verified against current
repository source, not re-derived from scratch. This is the final implementation milestone of
Phase 10 — a separate Final Implementation Verification follows, per instruction, before Phase 10
can be declared complete.

---

## 1. Implementation Summary

`scripts/run_content_generation.py` is now implemented: a manual, single-event CLI trigger that
composes the already-built production abstractions (`WorkflowRunner`, `CapabilityExecutor`,
`CapabilityRegistry`, `ContentDraftService`) into one orchestration function,
`run_content_generation_for_event()`, plus a ~10-line `main()`/CLI wrapper mirroring
`scripts/run_triage.py`'s own shape.

Unlike `scripts/run_triage.py` (whose `services.triage_orchestrator.run_triage_cycle()` has "no
`LLMGateway`, no Capability layer, no provider SDK"), this script is this repository's first
production caller of `assemble_ai_integration_layer()` — confirmed once more this session (grep for
call sites found only test files before this change). The orchestration function never duplicates
`WorkflowRunner`'s step loop, never invokes a Capability directly, and never writes a `ContentDraft`
row itself — every one of Contract §9's requirements is satisfied by composition alone.

**Beyond the frozen Plan's own code sketch** (`docs/phase10_implementation_plan.md:444-524`), two
deliberate, minimal additions were made, both explicitly authorized by prior process artifacts:
1. An injectable `capability_registry: CapabilityRegistry | None = None` parameter (Implementation
   Advisory, `docs/phase10_implementation_advisory.md` §3) — production default unchanged
   (`assemble_ai_integration_layer()` still runs when omitted).
2. An injectable `session_factory: async_sessionmaker[AsyncSession] = async_session_factory`
   parameter, mirroring `services/triage_orchestrator.py::run_triage_cycle()`'s own, already-
   established default-parameter DI shape exactly (this milestone's own Step 1/Step 3 instructions
   explicitly named this file as the precedent to follow) — production default unchanged.
3. The function now returns a small, frozen `ContentGenerationOutcome` dataclass (`task_id`,
   `workflow_status`, `content_draft`) instead of `None`, so the three-outcome distinction Contract
   §9 requires is directly inspectable by both the CLI and tests, not only visible via log lines —
   this milestone's own Step 2 item 6 required "a useful result suitable for CLI output/testing,"
   which `None` cannot provide.

Neither addition introduces a new file, a new abstraction category, a container, or a provider
factory — both are one-line default-parameter additions, matching this codebase's own established
style exactly.

---

## 2. Exact Files Changed

**Production files created** (the one file authorized by Contract §3):
- `scripts/run_content_generation.py`

**Production files modified**: none.

**Test files created**:
- `tests/test_run_content_generation.py` (6 tests) — required by Contract §12's "CLI tests" list,
  assigned to Milestone 4 by the Implementation Plan §10.

**Docs files created**:
- `docs/phase10_m4_manual_cli_report.md` (this report).

No file outside this list was created or modified during M4. No M1/M2/M3 file was touched.

---

## 3. CLI Interface

```
python -m scripts.run_content_generation <event_id>
```
One positional argument: `event_id` (a `UUID` string) — the only `required_input` the
`CONTENT_GENERATION` `WorkflowDefinition` declares (`workflows/definitions/content_generation.py`,
unchanged by this milestone). No batch mode, no scheduler flag, no Telegram trigger, no retry flag,
no provider-selection flag, no dry-run framework, no interactive UI — exactly the manual,
single-event trigger Step 8 requires, nothing more.

`main()` (10 lines): `setup_logging()` → parse `sys.argv[1]` as a `UUID` → await
`run_content_generation_for_event(event_id)`. No top-level `try/except` — mirrors
`scripts/run_triage.py`'s own precedent exactly.

---

## 4. `run_content_generation_for_event()` Behavior

```python
async def run_content_generation_for_event(
    event_id: UUID,
    *,
    priority: TaskPriority = TaskPriority.B,
    capability_registry: CapabilityRegistry | None = None,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
) -> ContentGenerationOutcome:
```

1. Resolves `registry` — the injected `capability_registry`, or (production default) builds the
   real AI integration layer via `assemble_ai_integration_layer(settings, FilePromptRepository(...))`
   and takes its `.capability_registry`.
2. Opens one session from `session_factory`.
3. `workflow_service.create_task(session, EditorialTaskCreate(event_id, CONTENT_GENERATION,
   priority))` — this call's own existing, internal `session.get(NewsEvent, ...)` check is what
   satisfies "obtain/load the target NewsEvent" (Step 2 item 1); no second, redundant lookup was
   added, per "do not duplicate... logic."
4. `CapabilityExecutor(session, task.id, registry)` + `WorkflowRunner(executor)` (default,
   unmodified `WorkflowRegistry` — resolves the real `CONTENT_GENERATION` definition) →
   `runner.run(session, task.id)`.
5. Three-outcome branch (Contract §9), each returning a distinct `ContentGenerationOutcome`:
   - `result.status != "COMPLETED"` → logged (`content_generation_task_failed`), `content_draft=None`.
   - `result.status == "COMPLETED"` and `ContentDraftService(session).create_from_result()` raises →
     caught, logged at `exception` level (`content_generation_completed_but_draft_persistence_
     failed`), `content_draft=None` — never swallowed silently, never re-raised past this one
     documented boundary.
   - Full success → logged (`content_generation_succeeded`), `content_draft` populated.

No Research/Intelligence/Copywriting/Quality Capability is invoked directly anywhere in this
function; no `ContentDraft` ORM row is constructed directly; the workflow's step loop is never
reimplemented.

---

## 5. Dependency Injection Design

Two constructor-style, keyword-only default parameters, both following this codebase's own,
already-established DI convention (`services/triage_orchestrator.py::run_triage_cycle()`'s
`session_factory` parameter, re-verified this session as the precedent):

| Parameter | Production default | Test override |
|---|---|---|
| `capability_registry` | `None` → built via `assemble_ai_integration_layer()` | a `build_registry()`-constructed registry backed by `FakeLLMGateway` |
| `session_factory` | `database.session.async_session_factory` (real, pooled engine) | `tests.test_triage_orchestrator_claims.independent_session_factory()` (fresh, `NullPool` engine per test) |

No new DI framework, no container abstraction, no provider factory redesign, and no new production
file was introduced — both parameters are plain Python default arguments on one existing function
signature.

---

## 6. Production Bootstrap Behavior

When `capability_registry` is omitted, the function calls `assemble_ai_integration_layer(settings,
FilePromptRepository(_PROMPTS_ROOT))` exactly once and uses its `.capability_registry` — no
provider config, gateway routing, retry policy, or provider registration is reconstructed manually;
every one of those is already assembled inside `assemble_ai_integration_layer()` itself (unmodified,
`integrations/llm_gateway/boot.py`). `AIIntegrationLayer`'s actual return contract
(`.gateway`/`.capability_registry`/`.cost_tracker`, `integrations/llm_gateway/boot.py:122-133`) was
inspected directly before use — `.capability_registry` is the only attribute this script reads.

Proven directly, not merely asserted: `test_default_path_uses_the_production_bootstrap` monkeypatches
`assemble_ai_integration_layer` to a call-counting stub and confirms it fires exactly once when no
registry is injected; `test_injected_registry_execution_never_calls_the_real_bootstrap` monkeypatches
it to raise `AssertionError` if called, and confirms the injected-registry path never triggers it.

---

## 7. Workflow Execution Path

`WorkflowRunner(executor)` is constructed with **no** explicit `registry=` argument, so it resolves
its `WorkflowRegistry` default, `workflows.registry.registry` — the real, sealed, module-level
singleton that already contains the amended, 4-step `CONTENT_GENERATION` definition (Milestone 2).
No step list is hard-coded in this script; no second `WorkflowDefinition` copy exists anywhere in
`scripts/run_content_generation.py`. Confirmed directly by the end-to-end test's step-order
assertions and by direct read of the file (no `WorkflowStepDefinition`/`WorkflowDefinition` import
appears in it at all).

---

## 8. ContentDraft Persistence Path

`ContentDraftService(session).create_from_result(task.id, result)` — the only call in this file that
touches `ContentDraft`, and it is never constructed, never `session.add()`-ed, and never
field-mapped directly here. `services/content_draft_service.py` (M3, unmodified) owns all of that.
Persistence is attempted **only** inside the `result.status == "COMPLETED"` branch — never for a
`FAILED` result, never for a hypothetical mid-run result (which cannot exist, per M3's own report
§8/M2's `WorkflowRunner.run()` semantics).

---

## 9. Failure Semantics

| Case | Handling |
|---|---|
| `NewsEvent` not found | `workflow_service.create_task()`'s own `NewsEventNotFoundError` propagates uncaught — no top-level `try/except` in this script, matching `scripts/run_triage.py`'s own precedent and this codebase's "fail loud" boot discipline. |
| Workflow failure (any step) | Surfaces as `result.status == "FAILED"` — `WorkflowRunner.run()` (frozen, unmodified) never raises for this; handled by the three-outcome branch, logged, `content_draft=None`. |
| Workflow timeout | Same mechanism as workflow failure — `WorkflowTimeoutError` is caught inside `WorkflowRunner.run()` itself and surfaces as `result.status == "FAILED"`, never propagates to this script. |
| Capability failure | Same mechanism — surfaces as a `FAILED` step within `result.step_results`, then `result.status == "FAILED"`. |
| Missing/invalid Copywriting result on an (unreachable in practice) malformed `COMPLETED` result | `ContentDraftService`'s own `_copywriting_output()` guard (M3) raises `ValueError`; this script's `try/except Exception` around the `create_from_result()` call catches it, logs `content_generation_completed_but_draft_persistence_failed`, returns `content_draft=None` — never a script crash, never a silently-created wrong draft. |
| `ContentDraftService` persistence failure (any cause) | Same handling as the row above — the general case this script's one `try/except` boundary exists for. |

No failure is silently marked as success anywhere in this file — confirmed by direct read (the only
`try/except` in the entire script is the one documented boundary above).

---

## 10. Tests Added/Modified

**`tests/test_run_content_generation.py`** (6 new tests, zero existing tests modified):

1. `test_injected_registry_execution_never_calls_the_real_bootstrap` — items 1/2.
2. `test_default_path_uses_the_production_bootstrap` — item 3.
3. `test_content_generation_end_to_end_persists_exactly_one_content_draft` — items 4/5/6, and
   the Step 10 end-to-end proof.
4. `test_failed_workflow_does_not_persist_a_content_draft` — item 7.
5. `test_persistence_failure_surfaces_as_distinct_outcome_not_a_crash` — item 8, reinterpreted
   precisely (see §11 below — the real chain cannot itself produce a `COMPLETED` result missing
   `"copywriting"`, since it is a required step; this test exercises the general persistence-failure
   branch the same guard protects, via a monkeypatched `ContentDraftService.create_from_result`).
6. `test_news_event_not_found_raises` — item 9.

Item 10 ("CLI argument parsing/entrypoint behavior matches repository convention") is satisfied by
**not** writing a test for `main()` — confirmed this is the actual repository convention: no
existing script's `main()`/CLI wrapper is unit-tested anywhere in this codebase (grep found zero
such tests for `scripts/run_triage.py` either). Adding one for this script would deviate from, not
match, the established convention. Item 11 (no live external API call) is satisfied throughout: every
test either injects a `FakeLLMGateway`-backed registry or monkeypatches
`assemble_ai_integration_layer` itself to a non-network stub.

Every DB-touching test uses `tests.test_triage_orchestrator_claims.independent_session_factory()`/
`real_committed_event()` (never the `db_session` fixture), since
`run_content_generation_for_event()` opens its own session via an injected `session_factory`
callable — a sessionmaker, not an already-open session instance, which `db_session` cannot supply.

---

## 11. End-to-End Proof

`test_content_generation_end_to_end_persists_exactly_one_content_draft` runs the full, real chain
through `run_content_generation_for_event()` itself (not a hand-assembled `WorkflowRunner`/
`CapabilityExecutor` pair, as M2's own test used) — real `WorkflowRunner`, real
`CapabilityExecutor`, the real `CapabilityRegistry` interface (a `build_registry()`-constructed
instance), the real, production `CONTENT_GENERATION` definition (via `WorkflowRunner`'s default
registry), and the real `ContentDraftService` — with only `FakeLLMGateway` standing in for the
network.

Proven: `NewsEvent → EditorialTask → research → intelligence → copywriting → quality → COMPLETED →
ContentDraft`, with the persisted draft's `task_id`, `title`, `body`, `hashtags`, `version`, and
`status` all asserted correct, the `EditorialTask.event_id` association confirmed, and exactly one
`ContentDraft` row confirmed present via a direct query. No live provider was invoked — this is not
claimed as a live-provider production smoke (that remains Step 11/item 9 below, explicitly deferred).

---

## 12. Focused Validation

```
tests/test_run_content_generation.py ......... 6 passed
```
Plus, run together with every Phase 10 M1-M3 test file: **39/39 passed**, zero modification
required to any pre-existing test.

---

## 13. Full Regression Results

```
python -m pytest -q
707 passed in 337.09s (0:05:37)
```
707 = the 701 baseline from the M3 report plus the 6 new tests this milestone added. Zero
failures, zero regressions.

---

## 14. Ruff Result

```
python -m ruff check .
All checks passed!
```

---

## 15. Mypy Result

```
python -m mypy scripts/run_content_generation.py tests/test_run_content_generation.py
Success: no issues found in 2 source files
```

---

## 16. Architecture Validator Result

```
python -m scripts.validate_architecture
validate_architecture: clean - 0 forbidden-dependency violations under C:\Users\Theodor\ai-newsroom
```

---

## 17. Live Smoke Result

**Not executed, deliberately.** Contract §8's M0 smoke test ("exactly one manual, out-of-band live
call proving `RoutingGateway.generate()` succeeds against the real OpenAI API") is explicitly
manual and explicitly forbidden from the automated test suite (Contract §8, Phase 7 §15.5's
no-real-network-call discipline). This implementation session has no real OpenAI credentials
configured for this purpose, and per this milestone's own Step 11 instruction, no fake test is
substituted and reported as a live smoke. This remains outstanding — to be run manually, by a human,
against a real, provisioned environment, before Phase 10's Definition of Done item 9 can be checked
off (see §19 below).

---

## 18. Scope Audit

`git diff --name-only` (tracked files modified) — **identical to M2's and M3's own list, unchanged
by M4**:
```
capabilities/quality_capability.py
capabilities/registry.py
tests/test_quality_capability.py
workflows/definitions/content_generation.py
```
Zero additional tracked files modified by M4.

`git status --short` (new files, M4-relevant subset):
```
?? scripts/run_content_generation.py
?? tests/test_run_content_generation.py
?? docs/phase10_m4_manual_cli_report.md
```
Exactly the one Contract §3-authorized new production file, one new test file, and this report.

Every M1 file (`capabilities/copywriting_capability.py`, `prompts/copywriting/`, its test file and
report), M2 file (`prompts/quality/v2.yaml`, its two test files and report), and M3 file
(`schemas/content_draft.py`, `services/content_draft_service.py`, its test file and report) appears
unchanged in `git status` and was not modified. Every other untracked entry is a pre-existing Phase
9/9.5/10 process document from earlier sessions, unrelated to and untouched by M4.

**Verified**: M4 production changes are limited to exactly `scripts/run_content_generation.py` —
the authorized scope, no more, no less. No unauthorized production file was required.

---

## 19. Self-Audit Answers

1. **Does `run_content_generation_for_event()` support injected test dependencies?** Yes —
   `capability_registry` and `session_factory`, both keyword-only, both defaulting to production
   behavior.
2. **Can tests execute without constructing real AI providers?** Yes — confirmed directly via a
   monkeypatch that would fail the test if `assemble_ai_integration_layer()` were ever called.
3. **Does default behavior still use production AI bootstrap?** Yes — confirmed directly via a
   call-counting stub.
4. **Is the real `CONTENT_GENERATION` workflow definition used rather than duplicated?** Yes — no
   `WorkflowDefinition`/`WorkflowStepDefinition` is constructed anywhere in this script;
   `WorkflowRunner`'s default registry is used unmodified.
5. **Does successful execution persist `ContentDraft` through `ContentDraftService`?** Yes — the
   only `ContentDraft`-touching call in the file.
6. **Does failed execution create zero drafts?** Yes — confirmed directly.
7. **Does missing Copywriting output fail loudly?** Yes — at the `ContentDraftService` boundary
   (M3), surfaced by this script as a distinct, logged, non-crashing outcome (never silently
   swallowed, never a false success).
8. **Does one successful invocation create exactly one draft?** Yes — confirmed directly via a
   row-count query.
9. **Was any unauthorized production file modified?** No — scope audit confirms exactly the one
   authorized new file, zero existing-file modifications.
10. **Was any scheduler, Telegram, meme/image, analytics, workflow redesign, Gateway redesign, or
    migration introduced?** No — none of these appear anywhere in M4's diff.
11. **Did the frozen Contract or Plan change?** No —
    `docs/phase10_production_content_pipeline_architecture_contract.md` and
    `docs/phase10_implementation_plan.md` were not modified (confirmed via `git status`: both still
    untracked/unchanged, not `M`).
12. **Is Phase 10 now functionally complete according to the approved Definition of Done?**
    **Not yet.** Of the Implementation Plan's 11 Definition-of-Done criteria (§11): items 1-8 and 11
    are satisfied by M1-M4's implementation and the regression proof recorded across all four
    milestone reports (four-step `COMPLETED` chain; independently-durable `ContentDraft`; every
    Contract §12 test exists and passes; exactly the 9 authorized files were touched; the
    `QualityCapability` amendment is byte-for-byte scoped; `prompts/quality/v1.yaml` is unmodified
    and independently resolvable; every mechanical non-coupling/isolation check passes; no
    migration was created; no unauthorized file exists anywhere in the four milestones' combined
    diff). Items **9** (the real, manual, out-of-band OpenAI live smoke test) and **10** (a full
    manual run of `scripts/run_content_generation.py` against a real, provisioned environment and a
    real `event_id`) are explicitly **outstanding** — both require a human operator with real
    credentials in a real environment, neither of which this implementation session has or should
    fake. Per this milestone's own closing instruction, Phase 10 is not declared fully complete
    here; a separate Final Implementation Verification follows.

No defect was discovered requiring a stop.

---

## 20. Remaining Limitations

- **Definition-of-Done items 9/10 outstanding** (§19 item 12) — the two manual, real-environment
  steps this implementation session cannot and must not simulate.
- **Commit-failure path remains untested at the `ContentDraftService` layer** (already disclosed by
  M3's own report, unchanged) — this script's own `except Exception` around
  `create_from_result()` is proven to catch and correctly log/report *a* failure
  (`test_persistence_failure_surfaces_as_distinct_outcome_not_a_crash`, via a monkeypatched raise),
  but not specifically a real Postgres commit failure, for the same reason M3 gave: forcing one
  against a healthy test database would not prove anything about the real commit path.
- **No idempotency mechanism** (already disclosed by M3, unchanged) — calling
  `run_content_generation_for_event()` twice for the same `event_id` would hit
  `workflow_service.create_task()`'s own existing `DuplicateActiveTaskError` guard (Phase 5,
  unmodified) only while the first task remains `CREATED`/`RUNNING`; once it reaches a terminal
  status, a second call creates a second, independent `EditorialTask` and (if successful) a second
  `ContentDraft` — this is pre-existing Phase 5 behavior, not something Phase 10 changes or was ever
  asked to change.
- Every other limitation already disclosed by M0/M1/M2/M3 (the timeout-reuse-not-validation
  disclosure, the duplicate Research/Intelligence Gateway-call risk for events with both an active
  `NEWS_ANALYSIS` and `CONTENT_GENERATION` task) remains unchanged and is not repeated here.

---

## Final Verdict

M4 COMPLETE — PHASE 10 IMPLEMENTATION READY FOR FINAL VERIFICATION
