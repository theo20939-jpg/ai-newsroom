# Phase 10 — Implementation Plan Audit

**Status: audit document. Does not modify the Implementation Plan, the Architecture Contract,
production code, tests, or migrations.** Independent, adversarial audit of
`docs/phase10_implementation_plan.md` against the frozen, approved Architecture Contract
(`docs/phase10_production_content_pipeline_architecture_contract.md`, revision 3, "PASS 3",
approved in `docs/phase10_final_architecture_reaudit.md`) and live repository source. The Plan is
treated as fully untrusted, including citations it re-states from the Contract or from its own
prior drafting — every line-number and function-signature claim relied upon for a finding below was
independently re-read this session. This is a readiness determination for *implementation*, not an
improvement exercise: the Plan is approved unless a defect would genuinely prevent implementation
from safely beginning.

---

# Executive Summary

The Implementation Plan is sound and implementable. Its authorized file scope is identical,
file-for-file, to the Contract's own §3 list — independently re-derived, not copied — and every
milestone's dependency ordering is correct with no circular or inverted dependency. The Milestone 0
readiness checklist's claims were independently re-verified against live source and all 11 hold.

One MAJOR finding was identified: Milestone 4's `scripts/run_content_generation.py` code sketch
unconditionally calls `assemble_ai_integration_layer(settings, prompt_repository)` inside the
function the Plan's own Verification Plan says must be "invoked directly... against fakes" (per
Contract §12's CLI tests) — but `assemble_ai_integration_layer()` always constructs a *real*
`RoutingGateway`/provider adapter stack; no existing test anywhere in this repository calls it with
a fake `LLMGateway`, and no codebase precedent injects one through it. As sketched, the function
cannot be unit-tested against fakes the way the Plan itself requires. This does not block
Milestones 0–3, does not require any unauthorized file, and does not require reopening the
Contract — it is fixable by adding one injectable parameter, mirroring an already-established
codebase pattern (`services/triage_orchestrator.py:223`'s `session_factory` injection) applied to
the capability registry construction, exactly as every existing Research/Intelligence integration
test already does by hand-constructing `CapabilityExecutor`/`WorkflowRunner` instead of going
through `assemble_ai_integration_layer()`. One MINOR citation-precision finding was also identified
(Definition of Done item 9's section citation).

**Verdict: PHASE 10 IMPLEMENTATION PLAN APPROVED.**

---

# Verified Milestones

**Milestone 0 — Repository Preparation.** All 11 checklist rows independently re-verified against
live source this session (not re-read from the Plan's own citations): `workflows/runner.py:157`'s
generic step iteration, `capabilities/executor.py:125-134`'s full-history `step_results` dict
comprehension (confirmed `quality`'s context will contain `research`+`intelligence`+`copywriting`
simultaneously), `capabilities/executor.py:80-83`'s `resolve_ai_capability()` dispatch with
`capabilities/capability_mapping.py:22` already mapping `"copywriting"` (confirmed present today,
not added by Phase 10), `capabilities/registry.py:77-113`'s register/resolve/seal mechanics,
`workflows/registry.py:74-87`'s `build_registry()` registering the same mutated
`content_generation.DEFINITION` module object at import time (confirmed: no separate
re-registration step exists), `integrations/prompts/file_repository.py:105-121`'s directory/glob
auto-discovery, `integrations/llm_gateway/boot.py:143-148`'s `assemble_ai_integration_layer()`
signature (confirmed to already accept an injected `prompt_repository`) and its confirmed
zero-production-call-site status today, `database/session.py:14`'s `expire_on_commit=False`,
`database/models/content_draft.py:23-48` plus its `database/models/__init__.py:3,17` export,
`schemas/editorial_task.py:26-42`'s `EditorialTaskRead` DTO pattern, and
`services/budget_guard.py:46,66`'s `RedisBudgetGuard` class-based service precedent. All 11 hold
exactly as the Plan states. Objective, dependencies (none — this is verification only), and
completion criterion ("every row READY, no file written") are all correct and achievable.

**Milestone 1 — `CopywritingCapability`.** Structurally verified against
`capabilities/quality_capability.py`, `capabilities/research_capability.py`, and
`capabilities/intelligence_capability.py` line-by-line: constructor shape, `_floor_validate()`
duplication convention, `_build_request()`/`execute()` control-flow shape, and the forbidden-import
list are all accurately mirrored. The `prompts/copywriting/v1.yaml` sketch's `output_schema`
matches Contract §5's frozen schema verbatim and its `required` list equals
`expected_output_keys` exactly, per Contract §6's binding rule. Dependencies (Milestone 0 only) are
correct — nothing in this milestone imports `capabilities/registry.py` or any other
not-yet-authorized file. Completion criteria and verification assignment (Contract §12 Capability
tests) are correct and sufficient for this milestone's own scope.

**Milestone 2 — Workflow Integration.** The `capabilities/registry.py` two-line diff is verified
character-for-character consistent with the file's real current state
(`registry.py:133-138` — confirmed the four existing `register()` calls sit at exactly lines
134-137, matching both the Plan's and the Contract's own citation). The
`workflows/definitions/content_generation.py` diff (4 steps, `timeout_seconds=120`) matches
Contract §3 exactly; the Plan's claim that `expected_output` is never read by `WorkflowRunner` was
independently re-checked (`workflows/runner.py` — confirmed no reference to
`WorkflowDefinition.expected_output` anywhere in the file). The `QualityCapability` amendment plan
(one additional `step_results.get("copywriting", {})` read, one `PROMPT_VERSION` bump) matches
Contract §5.1 exactly, and `prompts/quality/v2.yaml`'s `output_schema` is verified identical to
`v1`'s. Dependency on Milestone 1 (registry.py's new import) is correctly stated and necessary — not
inverted. Completion criteria and verification assignment (Contract §12 QualityCapability adaptation
+ Registry resolution tests) are correct.

**Milestone 3 — `ContentDraft`.** `schemas/content_draft.py`'s sketch correctly mirrors
`schemas/editorial_task.py:26-42`'s `EditorialTaskRead` pattern (`ConfigDict(frozen=True,
extra="forbid")`, plain field list). The `hashtags: list[str] | None` typing on a `JSON` column was
independently checked for a mismatch — none exists (`database/models/content_draft.py:40`, a `JSON`
column accepts a Python list with no translation). `services/content_draft_service.py`'s sketch
correctly implements Contract §7.1's session-reuse, single-commit, and uncaught-propagation
requirements; its addition of `await self._session.refresh(draft)` after the commit is sound and
arguably necessary (not a Contract violation — it does not add a second commit): `ContentDraft.
created_at`/`updated_at` are `server_default=func.now()` values that, under `expire_on_commit=False`,
are not otherwise populated back onto the Python object after `commit()`, and the `ContentDraftRead`
DTO's `created_at`/`updated_at` fields need real values. Correctly identified as independent of
Milestones 1–2 (no dependency on Copywriting's code, only on frozen `ContentDraft`/`WorkflowRunResult`
shapes). Completion criteria and verification assignment (Contract §12 ContentDraft tests, including
the mandatory independent-connection durability test) are correct; the cited precedent
(`tests/test_workflow_runner_per_step_persistence.py`, confirmed to import
`independent_session_factory`/`real_committed_event` from `tests/test_triage_orchestrator_claims.py`
at line 41) is real and accurately described.

**Milestone 4 — Manual CLI Trigger.** See MAJOR-1 below for the one real defect found in this
milestone. Everything else in it is verified sound: the constructor signatures used in the sketch
(`CapabilityExecutor(session, task_id, registry)`, `WorkflowRunner(executor)`,
`workflow_service.create_task(session, command)`, `assemble_ai_integration_layer(settings,
prompt_repository)` returning an `AIIntegrationLayer` with a real `capability_registry` field) were
all independently checked against live source and are accurate — `AIIntegrationLayer`'s field is
in fact named `capability_registry` (`integrations/llm_gateway/boot.py:132`), and
`TaskPriority.B` is a real, valid enum member (`database/models/editorial_task.py:13-19`). The
three-outcome logging distinction correctly implements Contract §9/§7.1. The "first production
caller" framing is correctly carried forward from the Final Architecture Re-Audit's own MINOR
finding, not glossed over.

---

# Verified Implementation Order

The 7-step sequence was traced for inversion/circularity — none found:

1. `capabilities/copywriting_capability.py` + prompt — correctly has zero dependency on any other
   Phase 10 file.
2. `schemas/content_draft.py` — correctly has zero dependency on step 1; independently confirmed
   buildable in parallel.
3. `capabilities/registry.py` — correctly depends on step 1 (it imports from
   `copywriting_capability.py`; the reverse import never happens — no existing Capability imports
   `capabilities.registry`, confirmed by pattern across all four existing Capabilities, so no import
   cycle is possible here either).
4. `workflows/definitions/content_generation.py` — correctly has no *code* dependency on step 3;
   grouping it alongside step 3 for milestone-level sequencing is a reasonable, non-blocking choice.
5. `capabilities/quality_capability.py` + `prompts/quality/v2.yaml` — correctly has no import
   dependency on step 1 (`QualityCapability` MUST NOT import `copywriting_capability`, and its
   sketch does not); depends only on Contract §5's already-frozen key names, not on step 1's code
   existing.
6. `services/content_draft_service.py` — correctly depends on step 2 (`ContentDraftRead` import).
7. `scripts/run_content_generation.py` — correctly depends on all of 1, 3, 4, 5, 6.

No hidden prerequisite was found beyond what the Plan already states. Registry timing was traced
concretely: `workflows/registry.py`'s module-level `registry = build_registry()`
(`workflows/registry.py:87`) runs once at import time and registers the same
`content_generation.DEFINITION` object Milestone 2 edits in place — confirmed there is no second,
separate registration call to add or forget, exactly as Milestone 0's row 5 claims. Prompt-loading
timing is safe: `FilePromptRepository` performs its directory scan at construction time inside
Milestone 4's script, by which point both new prompt files (created in Milestones 1 and 2) already
exist on disk. Persistence timing (session reuse, `expire_on_commit=False`) is correctly sequenced
after `WorkflowRunner.run()`'s own commit, per Contract §7.1. CLI timing is correctly last, gated on
every other file existing.

---

# Verified File Scope

Independently re-derived, not copied from the Plan or the Contract, by tracing what the full
Research → Intelligence → Copywriting → Quality → ContentDraft → CLI chain actually requires:

**Existing files requiring an edit (3):** `workflows/definitions/content_generation.py`,
`capabilities/quality_capability.py`, `capabilities/registry.py`.

**New files required (6):** `capabilities/copywriting_capability.py`, `prompts/copywriting/v1.yaml`,
`prompts/quality/v2.yaml`, `schemas/content_draft.py`, `services/content_draft_service.py`,
`scripts/run_content_generation.py`.

**Hidden-integration-point search, confirmed clear:** `capabilities/__init__.py`,
`schemas/__init__.py`, `services/__init__.py`, and `scripts/__init__.py` are all docstring-only —
none maintains an explicit re-export list (unlike `database/models/__init__.py`, which does, and
already exports `ContentDraft`) — so no package `__init__.py` requires editing for any of the six
new files; every existing Capability is already imported by fully-qualified module path elsewhere
in this codebase (e.g. `capabilities/registry.py`'s own imports), not through package-level
re-export, so this is consistent with established convention, not a gap. `capabilities/
capability_mapping.py` already maps `"copywriting"` (confirmed, line 22) and needs no edit.
`workflows/registry.py` needs no edit (confirmed above). No CLI-framework registration file, no
settings/config file, and no dependency-injection container file exists in this codebase requiring
an entry for a new script or Capability — `scripts/run_triage.py` and the four existing Capabilities
all needed zero such registration beyond what the Plan already lists for Copywriting/Quality/the
registry.

This list is **identical** to both the Plan's own §1 and the Contract's own §3 authorized-file
list. **SUFFICIENT and COMPLETE** — no unnecessary file is included, and no required file is
missing.

---

# Findings

## CRITICAL

None.

## MAJOR

### MAJOR-1 — Milestone 4's code sketch has no fake-injection seam, contradicting its own Verification Plan's "against fakes" requirement

**Location**: Plan §6 ("Milestone 4 — Manual CLI Trigger," the `run_content_generation_for_event()`
sketch) vs. Plan §10 ("Milestone 4 — Manual CLI... Unit verification: ... invoked directly against
fakes... creates, runs, and persists a `ContentDraft` successfully against fakes").

**Evidence**: the sketched `run_content_generation_for_event()` unconditionally calls
`ai_layer = assemble_ai_integration_layer(settings, prompt_repository)` with no parameter allowing a
caller to substitute a fake `LLMGateway` or a pre-built `CapabilityRegistry`. Independently confirmed
this session: `assemble_ai_integration_layer()` always constructs a real `RoutingGateway` over real
provider adapters (`integrations/llm_gateway/boot.py`) — there is no injection point for a
`FakeLLMGateway` anywhere in its signature (`settings`, `prompt_repository`, `redis_client` only).
Every test in this repository that exercises the real Research→Intelligence chain against a fake or
sequenced-fake provider — `tests/test_phase9_research_intelligence_integration.py`'s
`test_both_capabilities_dispatch_in_order_and_synthetic_task_completes` (line 183) and
`test_both_capabilities_dispatch_through_a_real_routing_gateway_and_complete` (line 284) — does so by
hand-constructing `capability_registry = build_registry(gateway, prompt_repository, ...)` directly
with a `FakeLLMGateway`/`_SequencedFakeProviderAdapter`, then `CapabilityExecutor(db_session, task.id,
capability_registry)` directly, **never** calling `assemble_ai_integration_layer()`. Confirmed no
test anywhere in this repository calls `assemble_ai_integration_layer()` with anything other than a
real `Settings(enabled_providers=["openai"], ...)` block (`tests/test_capability_boot_wiring_e2e.py`,
line ~237-247). The codebase's own established injectability precedent for this exact problem
(`services/triage_orchestrator.py:222-224`, `session_factory: async_sessionmaker[AsyncSession] =
async_session_factory`) is not applied to the AI-layer construction in the Plan's sketch, and the
Plan's sketch does not parameterize `async_session_factory` either — unlike `run_triage_cycle()`'s
own precedent.

**Impact**: if implemented exactly as sketched, `run_content_generation_for_event()` cannot be
"invoked directly... against fakes" the way Plan §10 (and Contract §12's CLI tests) requires,
without either (a) monkeypatching `integrations.llm_gateway.boot.assemble_ai_integration_layer`
itself — fragile and inconsistent with this codebase's dependency-injection convention — or (b) the
test constructing a real `enabled_providers=["openai"]` `Settings` and relying on
`test_capability_boot_wiring_e2e.py`'s own (presumably network-mocked) pattern, which is a
materially heavier and differently-shaped test than "against fakes" implies for every other
Capability/workflow test in this Contract.

**Why this does not block implementation**: it affects only Milestone 4, not Milestones 0–3; no
unauthorized file is needed to fix it; no Contract text is violated by fixing it (Contract §9 fixes
the script's *behavior*, not its exact internal signature — accepting an optional injected
`capability_registry`/`ai_layer` parameter with a real-construction default is the same shape as
`session_factory`'s own precedent, not a new pattern). This is a plan-precision gap the implementer
should resolve when writing Milestone 4, not a defect requiring the Plan itself to be revised before
implementation starts.

**Suggested correction, non-blocking**: when Milestone 4 is implemented, give
`run_content_generation_for_event()` (or an inner layer of it) an injectable `capability_registry:
CapabilityRegistry | None = None` (or equivalent) parameter defaulting to the real
`assemble_ai_integration_layer(...)`-constructed one, mirroring `session_factory`'s existing
injection shape — allowing the CLI test to pass a hand-built `build_registry(FakeLLMGateway(...),
...)` registry exactly as `tests/test_phase9_research_intelligence_integration.py` already does.

## MINOR

### MINOR-1 — Definition of Done item 9 misattributes the M0 smoke test's section

**Location**: Plan §11, item 9 ("Contract §8's M0 live smoke test succeeds exactly once...").

**Evidence**: Contract §8 itself never uses "M0" terminology — it describes "exactly one manual,
out-of-band live smoke test" without a milestone label. The "M0" label is Decision Resolution
§13's own milestone name, referenced *inside* Contract §3 ("Actual sufficiency is deferred entirely
to Decision Resolution §13's own M0 smoke test..."), not inside Contract §8. The underlying
requirement is correctly described; only the section attribution is imprecise.

**Correction, non-blocking**: item 9 should read "Decision Resolution §13's M0 smoke test (Contract
§8, §3) succeeds..." or similar. Does not affect what must actually be done or verified.

## OBSERVATIONS

- **OBS-1**: the Plan's Risk table (§9) does not list the MAJOR-1 testability gap above as its own
  risk row. Not required for approval (it is now captured as a Finding, which is a stronger signal
  than a Risk-table entry), but a future revision could fold it in as an R8 for completeness.
- **OBS-2**: `services/content_draft_service.py`'s sketch's `session.refresh(draft)` call after
  `commit()` is a correct, likely-necessary addition (to populate `server_default`-backed
  `created_at`/`updated_at` under `expire_on_commit=False`) and does not violate Contract §7.1's
  "exactly one commit" boundary — refresh performs a `SELECT`, not a second commit. Worth an
  implementer's awareness, not a defect.
- **OBS-3**: the Plan correctly declines to freeze `TaskPriority.B` as the CLI's default priority,
  explicitly naming it a non-frozen implementation choice — consistent with the Contract, which only
  fixes `required_input=["event_id"]`. No action needed.
- **OBS-4**: `workflow_service.create_task()`'s real failure modes (`NewsEventNotFoundError`,
  `DuplicateActiveTaskError`, per `services/workflow_service.py:34-51`) are correctly left
  unenumerated in the Plan's "Failure handling" prose, which generically describes "an unhandled
  exception... is allowed to propagate and crash the script loudly" — consistent with Contract §9's
  intent and `scripts/run_triage.py`'s own no-top-level-try/except precedent, independently
  confirmed by direct read of `scripts/run_triage.py` this session (11 lines, no exception handling
  at all). Not a gap.

---

# Implementation Readiness Score

**9 / 10** — the Plan's file scope, dependency ordering, and per-milestone detail are all
independently verified correct and complete; the one MAJOR finding is real but narrowly scoped to a
single milestone's code sketch, does not require touching any unauthorized file or reopening the
Contract, and has an obvious, already-precedented fix an implementer will naturally apply. The one
MINOR finding is a citation-attribution nit with no effect on required work. Nothing found here
would cause implementation to go astray if Milestone 4 is built with ordinary care.

---

# Final Verdict

PHASE 10 IMPLEMENTATION PLAN APPROVED
