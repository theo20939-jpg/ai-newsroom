# Phase 10 — Milestone 0: Repository Preparation Report

**Status: verification report only. Zero production code, test, prompt, or migration changes were
made to produce this document.** Verifies the repository's current readiness for Phase 10
implementation, per the frozen Architecture Contract (`docs/
phase10_production_content_pipeline_architecture_contract.md`, revision 3, PASS 3, approved) and
the frozen Implementation Plan (`docs/phase10_implementation_plan.md`, approved,
9/10). Every item below was independently re-read against live repository source this session — no
claim from the Contract, the Plan, or any prior audit was taken on faith.

---

## Verification Results

### 1. WorkflowRunner

**READY.** `workflows/runner.py` exists and is stable. Its step loop is generic — `_execute_steps()`
computes `remaining_steps = [s for s in definition.steps if s.name not in state.completed_steps]`
(`workflows/runner.py:157`) with no hardcoded step count and no `if step.name == ...`/`match
capability:` branching anywhere in the file (confirmed by full read). Per-step persistence commits
`task.workflow` (`state.step_results`, `state.completed_steps`) after every `SUCCESS`/`SKIPPED` step,
before the next step starts (`workflows/runner.py:189-199`). Two independent timeout boundaries exist
exactly as the Contract describes: the whole-workflow `asyncio.wait_for(self._execute_steps(...),
timeout=definition.timeout_seconds)` (`workflows/runner.py:134-136`) and each step attempt's own
`asyncio.wait_for(self._executor.execute(step), timeout=step.timeout_seconds)`
(`workflows/runner.py:239`). Nothing in this file is authorized for editing by the Contract (§3), and
nothing needs to be.

### 2. CapabilityExecutor

**READY.** `capabilities/executor.py` implements the `StepExecutor` Protocol exactly as described.
`_build_context()` (`capabilities/executor.py:111-147`) builds `step_results` from **all** prior
`SUCCESS` steps, not merely the immediately-preceding one: `step_results={r.step_name: r.result for r
in state.step_results if r.status == "SUCCESS" and r.result is not None}`
(`capabilities/executor.py:129-133`) — a dict comprehension over the full `state.step_results` list.
Once `research`, `intelligence`, and `copywriting` have all run, `quality`'s context will contain all
three simultaneously. `execute()` (`capabilities/executor.py:59-109`) returns
`result.structured_output or {}` — a `dict[str, Any]`, matching the `StepExecutor` Protocol's
declared return type — and the class holds a read-only database session (used only to re-fetch
`EditorialTask`/`NewsEvent`, never to write), exactly as Amendment B (Phase 6 Contract §16) requires
(confirmed by the module's own docstring, lines 10-13, and by the absence of any `session.add()`/
`session.commit()` call anywhere in the file). Nothing here is authorized for editing, and nothing
needs to be.

### 3. CapabilityRegistry

**READY.** `capabilities/registry.py::build_registry()` currently registers exactly four
Capabilities — `SCORING_CAPABILITY_DEFINITION`/`ScoringCapability`,
`QUALITY_CAPABILITY_DEFINITION`/`QualityCapability`, `RESEARCH_CAPABILITY_DEFINITION`/
`ResearchCapability`, `INTELLIGENCE_CAPABILITY_DEFINITION`/`IntelligenceCapability`
(`capabilities/registry.py:134-137`), followed by `registry.seal()` (`:138`). The Contract's/Plan's
two-line addition point is valid against the file exactly as it exists today: one import line
alongside the existing four Capability imports (`capabilities/registry.py:50-53`) and one
`registry.register(...)` call alongside the four existing calls (`:134-137`), before `seal()`. The
`register()`/`resolve()`/`seal()` mechanics themselves (`:77-113`) are simple, dict-backed, and
require no change for a fifth registration to work.

### 4. Prompt Loader

**READY.** `FilePromptRepository.__init__` (`integrations/prompts/file_repository.py:105-121`)
iterates `root.iterdir()` for name-subdirectories and `name_dir.glob("v*.yaml")` for version files
within each, parsing the version number from the filename and validating each file's declared
`name`/`version` against its directory/filename at construction time (fail-loud, `PromptContentError`
— confirmed by direct read of `_load_rendered_prompt()`, `:75-96`). Adding `prompts/copywriting/
v1.yaml` (a new name-directory) or `prompts/quality/v2.yaml` (a new version file inside an existing
name-directory) requires zero change to this file — both are exactly the shapes this constructor
already discovers automatically. `resolve()` (`:123-134`) is a pure in-memory dict lookup, unaffected.

### 5. LLM Gateway

**READY.** `integrations/llm_gateway/boot.py::assemble_ai_integration_layer(settings: Settings,
prompt_repository: PromptRepository, *, redis_client: Redis | None = None) -> AIIntegrationLayer`
(`:143-148`) is code-complete: it builds the model/provider registries, validates cross-registry
consistency, constructs the `RoutingGateway`/`FallbackPolicy`/`RoutingEngine` stack, calls
`build_registry(gateway, prompt_repository, budget_guard, tool_registry)` (`:215`), and returns an
`AIIntegrationLayer(gateway=..., capability_registry=..., cost_tracker=...)` (`:217-219`) — a frozen
dataclass with exactly those three fields (`:121-133`). `OpenAIAdapter`
(`integrations/llm_gateway/providers/openai_adapter.py`) is already referenced by
`_build_provider_factories()` (`boot.py:136-140`) as the sole onboarded provider. No code change is
needed — only configuration (`Settings.enabled_providers` including `"openai"`,
`Settings.openai_api_key`), per Contract §8.

**One fact worth stating precisely for M4 readiness** (out of scope for M0 itself, but verified here
since M0's own checklist calls for it): `assemble_ai_integration_layer()` has **never been called
from production code** in this repository. An exhaustive repository-wide search found it referenced
only in its own definition (`integrations/llm_gateway/boot.py`), two docstring mentions in
`integrations/llm_gateway/errors.py:136` and `integrations/llm_gateway/providers/
openai_adapter.py:363` (neither is a call), and four **test** files: `tests/test_boot_assembly.py`,
`tests/test_capability_boot_wiring_e2e.py`, `tests/test_phase8_cross_cutting_regression.py`,
`tests/test_phase9_cross_cutting_regression.py`. `scripts/run_content_generation.py` (Milestone 4)
will be this repository's first production caller. This is not a blocker — every component the
function assembles is independently proven and unmodified, and `tests/
test_capability_boot_wiring_e2e.py:246-250` already proves the exact call shape end-to-end
(`assemble_ai_integration_layer(_boot_settings(), _prompt_repository(), redis_client=redis_client)`
→ `layer.capability_registry.resolve(...)`) against a fake provider adapter. This is Risk R1 in the
Implementation Plan (§9) and the subject of the non-blocking Implementation Advisory (`docs/
phase10_implementation_advisory.md`) — both already correctly account for it. Recorded here as a
confirmed fact, not a new finding.

### 6. Database Session

**READY.** `database/session.py:14`: `async_session_factory = async_sessionmaker(engine,
expire_on_commit=False)`. This is the exact precondition `ContentDraftService`'s same-session-reuse
design (Contract §7.1) depends on — already true today, requires no change.

### 7. ContentDraft persistence prerequisites

**READY.** `database/models/content_draft.py:23-48` defines `ContentDraft` with `task_id` (FK to
`editorial_tasks.id`, `:34-36`), `type` (`ContentType` enum: `POST`, `SHORT`, `ANALYSIS`, `MEME`,
`VIDEO_SCRIPT`, `:13-20`), `title`/`body` (`Text`, nullable), `hashtags` (`JSON`, nullable),
`version` (`Integer`, default `1`), `status` (`String`, free-text, nullable), plus `created_at`/
`updated_at`. Already exported from `database/models/__init__.py:3` (import) and `:17` (`__all__`).
No migration is needed — every column Phase 10 writes (`task_id`, `type=POST`, `title`, `body`,
`hashtags`, `version=1`, `status="draft"`) already exists exactly as the Contract's §7 FACT states.

One pre-existing, harmless imprecision, noted for completeness and not a blocker: the model's own
`Mapped[dict | None]` type hint on `hashtags` (`:40`) says `dict`, while Phase 10 will store a JSON
**array** (a Python `list`) there, matching `CopywritingCapability`'s frozen `hashtags: type: array`
output schema (Contract §5). This is a static type-hint imprecision only — `sqlalchemy`'s `JSON`
column type stores any JSON-serializable Python value at runtime regardless of the `Mapped[]`
annotation, so a `list` value round-trips correctly. The Implementation Plan's own
`schemas/content_draft.py` sketch already correctly types `ContentDraftRead.hashtags` as `list[str] |
None` (Milestone 3) and explicitly explains why there is no real mismatch — this was already handled
correctly, not overlooked.

### 8. Workflow definition loading

**READY.** `workflows/definitions/content_generation.py:15-31` currently declares the 2-step
`CONTENT_GENERATION` definition exactly as Contract §3's FACT states (`steps=[copywriting, quality]`,
`timeout_seconds=60`) — confirmed by direct read, byte-for-byte. `workflows/registry.py:74-87`
(`build_registry()`) registers `content_generation.DEFINITION` — the same module-level object
Milestone 2 will edit in place — at import time (`registry = build_registry()`, `:87`), so editing
`DEFINITION.steps`/`timeout_seconds` inside `content_generation.py` is sufficient; there is no
separate re-registration step to perform. `workflows/registry.py`'s registration mechanics (`register
()`/`seal()`/`resolve()`, `:37-71`) are simple and require no change, matching Contract §3's
byte-for-byte-unchanged list.

### 9. Capability registration mechanism

**READY.** Covered concretely under item 3 above; `capabilities/registry.py`'s `register()`/`seal()`/
`resolve()` mechanics (`:77-113`) are plain, dict-backed, and identical in shape for a fifth
registration as for the existing four — no special-casing exists anywhere that would need to change.

### 10. Current prompt versioning mechanism

**READY.** The `PROMPT_VERSION`-constant-plus-`resolve(CAPABILITY_NAME, PROMPT_VERSION)` convention
is confirmed live in `capabilities/quality_capability.py:33` (`PROMPT_VERSION = "1"`) and `:123`
(`self._prompt_repository.resolve(CAPABILITY_NAME, PROMPT_VERSION)`). Also confirmed:
`capabilities/capability_mapping.py:22` already maps `"copywriting": AICapability.COPYWRITING` —
present in this repository today, not something Phase 10 needs to add (`CapabilityExecutor.execute()`
calls `resolve_ai_capability(step.capability)` at `capabilities/executor.py:81`, which would raise
`CapabilityConfigurationError` → `PermanentStepFailureError` if this mapping were missing; it is not
missing). Phase 6 §8's "never delete or mutate a published version" discipline is upheld structurally
— `FilePromptRepository` (item 4 above) has no mutating method at all (confirmed: only `__init__` and
`resolve()` exist on the class), so `prompts/quality/v1.yaml` cannot be silently overwritten by any
code path even after `prompts/quality/v2.yaml` is added; it remains independently resolvable via an
explicit `resolve("quality", "1")` call for as long as the file remains on disk.

### 11. Manual CLI execution prerequisites

**READY**, with one fact recorded (not a blocker) — see item 5 above for the
`assemble_ai_integration_layer()` first-production-caller detail. Additional confirmations:
`scripts/run_triage.py:1-24` is a ~20-line wrapper containing no AI/Capability-layer code — its own
module docstring states it "contains no orchestration logic itself," confirming it is a shape
precedent for a thin entry point, not a precedent that `scripts/run_content_generation.py` can be
equally thin (the latter must additionally assemble the AI integration layer, which
`scripts/run_triage.py`'s target, `services.triage_orchestrator.run_triage_cycle()`, never touches).
`services/workflow_service.py::create_task(session: AsyncSession, command: EditorialTaskCreate,
registry: WorkflowRegistry = default_registry) -> EditorialTaskRead` (`:27-31`) exists and matches
the Implementation Plan's Milestone 4 sketch exactly — a default-registry keyword argument, session
passed explicitly, and returns a Pydantic `EditorialTaskRead`, never a raw ORM object. The DTO pattern
`schemas/content_draft.py` will mirror is confirmed live and accurate:
`schemas/editorial_task.py:26-42`'s `EditorialTaskRead` (`model_config = ConfigDict(frozen=True,
extra="forbid")`, plain field list). The class-based service precedent `services/
content_draft_service.py` will mirror is confirmed live: `services/budget_guard.py:46-...`
(`RedisBudgetGuard`) is a class with `__init__` storing injected dependencies, one public async
method — an existing, real pattern, not invented for Phase 10.

---

## Discovered Risks

No new risk was discovered beyond what the Contract (§14) and Implementation Plan (§9) already
disclose. One fact is worth restating precisely here since M0's own checklist calls for verifying
"manual CLI execution prerequisites": `assemble_ai_integration_layer()` has zero production call
sites today (item 5/11 above). This is already named as Risk R1 in the Implementation Plan and
already has a non-blocking Implementation Advisory addressing it (optional dependency injection for
testability, mirroring `run_triage_cycle()`'s `session_factory` default-parameter precedent). It does
not block M0, and does not block Milestones 1-3, which have no dependency on it.

## Repository Blockers

**None.** No missing dependency, no hidden architectural issue, no unauthorized file already present,
and no implementation blocker was found across any of the 11 verification items.

---

## Git Verification

```
$ git status --short
?? docs/phase10_m0_repository_preparation_report.md
```

Confirmed: no production code changed, no test changed, no prompt changed, no migration changed. This
report is the only new file this session produced.

---

M0 PASSED — READY FOR M1
