# Phase 10 — Production Content Pipeline Architecture Contract

**Status: frozen amendment specification, revised three times — after the first audit, after the
final re-audit, and after the final re-audit's own re-audit — pending re-audit.** This document
converts `docs/phase10_production_pipeline_discovery.md` and `docs/phase10_decision_resolution.md`
("Decision Resolution") into binding form. No production code, test, or migration was modified to
produce this document; no commit was created. Where this Contract references frozen behavior from
Phase 5, 6, 8, or 9, it cites the exact source rather than restating it as new authority.

**Revision note (post-audit correction pass)**: this Contract was revised after
`docs/phase10_production_content_pipeline_contract_audit.md` found three MAJOR gaps —
`QualityCapability` never consuming `CopywritingCapability`'s output (§5.1, new), an unproven
"proven sufficient" timeout claim (§3, corrected), and unspecified `ContentDraft` transaction
ownership (§7.1, new). This revision applies exactly those three corrections, plus the audit's
explicitly-requested additional items: a frozen `CopywritingCapability` output schema (§5), a
mandatory `ContentDraft` durability test (§12), and an explicit prompt `expected_output` contract
(§6). §2's Phase 10 Boundary, §10's Telegram exclusion, §11's Meme Generation exclusion, and every
scheduler/workflow-engine-redesign exclusion (§2, §9, §13) are unchanged by this revision.

**Revision note 2 (targeted correction after the Final Re-Audit)**: `docs/
phase10_production_content_pipeline_contract_reaudit.md` found one new CRITICAL defect introduced
by revision 1's own stronger §3 wording — "authorizes editing exactly two existing files, no
more" never authorized editing `capabilities/registry.py`, without which `CopywritingCapability`
can never be resolved and `CONTENT_GENERATION` can never reach `COMPLETED` — plus two MINOR
findings. This revision applies exactly those three corrections: §3 now authorizes a narrowly-
scoped, two-line edit to `capabilities/registry.py` and consolidates every new-file authorization
(`capabilities/copywriting_capability.py`, `prompts/copywriting/v1.yaml`, `prompts/quality/v2.yaml`,
`schemas/content_draft.py`, `services/content_draft_service.py`) into one explicit list (corrects
CRITICAL-1); §7.1 explicitly names `schemas/content_draft.py`/`ContentDraftRead` as authorized
(corrects MINOR-1); §7.1/§14 clarify that a `COMPLETED` task with no `ContentDraft` is discoverable
after the fact via a direct, manual query against existing columns, not solely via a log line
(corrects MINOR-2). No architecture, workflow ownership, Capability contract, Telegram exclusion,
meme exclusion, scheduler exclusion, `WorkflowRunner` boundary, or `LLMGateway` design changes.

**Revision note 3 (targeted correction after the Final Re-Audit's own re-audit)**: `docs/
phase10_production_content_pipeline_contract_reaudit_final.md` found revision 2 had relocated, not
eliminated, the CRITICAL pattern: §9 requires `scripts/run_content_generation.py` as the MVP
trigger, but §3's "exhaustive" new-file list never named it, so the Contract simultaneously
required and forbade the one file that invokes the whole pipeline. Plus two MINOR findings. This
revision applies exactly those three corrections: §3's new-file list now includes
`scripts/run_content_generation.py` (corrects CRITICAL-1); §7.1's discoverability clarification is
rewritten to describe the real schema — `workflow_type` lives inside `EditorialTask.workflow`'s JSON
payload (`workflow_name` key), not a dedicated column, and `ContentDraft.task_id` carries no
explicit index — while still requiring no migration (corrects MINOR-1); §12 adds an explicit test
obligation for `CapabilityRegistry.resolve("copywriting")` and for unchanged unknown-capability
behavior (corrects MINOR-2). No architecture, workflow ownership, Capability contract, Telegram
exclusion, meme exclusion, scheduler exclusion, `WorkflowRunner` boundary, or `LLMGateway` design
changes; no additional script or broadened CLI scope is introduced.

**Source-of-truth order**: this Contract (once approved) > `docs/phase10_decision_resolution.md`
(the approved decisions this Contract codifies, not reinterprets) >
`docs/phase10_production_pipeline_discovery.md` (the evidence both documents share) > the frozen
Phase 5/6/7/8/9/9.5 contracts, all of which remain in force, unamended, except where this document
explicitly states a narrow, specific amendment below.

Every statement is tagged **FACT** (repository evidence), **INFERENCE** (reasoned conclusion),
**DECISION** (frozen, binding choice), **RECOMMENDATION** (non-binding), or **OPEN QUESTION**.

---

## 1. Purpose

**FACT**: Phase 9 delivered `ResearchCapability`/`IntelligenceCapability`, communicating only via
`step_results` (Phase 9 Contract §9.1). Phase 9.5 made that mechanism reliable within one
uninterrupted `WorkflowRunner.run()` call by committing each step's outcome immediately after it
succeeds (`workflows/runner.py:189-199`). **FACT**: `workflows/definitions/content_generation.py`
already declares `WorkflowType.CONTENT_GENERATION` with steps `copywriting` → `quality`
(`capability="copywriting"`/`capability="quality"`); `quality` is already implemented
(`QualityCapability`, `CAPABILITY_NAME = "quality"`); `copywriting` has no implementation
anywhere in this repository. **FACT**: `QualityCapability._build_request()`
(`capabilities/quality_capability.py:81-108`) builds its request from `news_event.title`/
`category`/`summary` only — it does not read `step_results` at all, confirmed by direct read, and
confirmed by its own prompt content (`prompts/quality/v1.yaml:4-7`). §5.1 corrects this.

**DECISION — why Phase 10 exists**: to deliver the first Capability-driven content-generation
pipeline that reaches `TaskStatus.COMPLETED` for real, using entirely existing mechanisms
(the Capability pattern, `step_results`, `LLMGateway`) plus exactly one new Capability
(`CopywritingCapability`), one narrowly-scoped, explicitly-authorized adaptation to the existing
`QualityCapability` so it actually reviews Copywriting's output (§5.1), and one new persistence
component (`ContentDraftService`, §7.1).

**DECISION — what Phase 10 explicitly does not solve** (full list, §13): Telegram publishing,
meme generation of any kind, image generation, a scheduler, crash recovery, workflow-engine
redesign, or a second LLM provider. Phase 10 produces a persisted, reviewable `ContentDraft` row
and stops there.

---

## 2. Phase 10 Boundary

**DECISION — IN SCOPE**:
- Production LLM provider verification (configuration + one manual, out-of-band live smoke test).
- `CopywritingCapability` (a new, ordinary Phase 8 Capability).
- `CONTENT_GENERATION` workflow definition expansion (§3).
- `ContentDraft` lifecycle service (§7).
- A manual CLI trigger (§9).

**DECISION — OUT OF SCOPE, binding**:
- Telegram publishing (§10).
- Any scheduler or automatic-execution mechanism.
- Automatic publishing of any kind.
- Meme generation, in any form (§11).
- Image generation, in any form.
- A second LLM provider (Anthropic/Gemini/other).
- Any `WorkflowRunner`/`WorkflowExecutor`/`CapabilityExecutor` redesign.
- Crash recovery or a resume mechanism.

---

## 3. Workflow Decision

**FACT**: the current, frozen `CONTENT_GENERATION` definition
(`workflows/definitions/content_generation.py:15-31`) is:

```python
DEFINITION = WorkflowDefinition(
    name=WorkflowType.CONTENT_GENERATION,
    version=1,
    steps=[
        WorkflowStepDefinition(name="copywriting", capability="copywriting", timeout_seconds=30),
        WorkflowStepDefinition(name="quality", capability="quality", timeout_seconds=30),
    ],
    max_iterations=3,
    retry_policy=WorkflowRetryPolicy(max_attempts=3, retry_delay_seconds=0,
                                      retryable_error_types=["StepExecutionError"]),
    timeout_seconds=60,
    required_input=["event_id"],
    expected_output=["draft_content", "quality_report"],
)
```

**DECISION, binding**: `CONTENT_GENERATION`'s `steps` list is amended to four steps, in this exact
order:

```python
steps=[
    WorkflowStepDefinition(name="research", capability="research", timeout_seconds=30),
    WorkflowStepDefinition(name="intelligence", capability="intelligence", timeout_seconds=30),
    WorkflowStepDefinition(name="copywriting", capability="copywriting", timeout_seconds=30),
    WorkflowStepDefinition(name="quality", capability="quality", timeout_seconds=30),
]
```

reusing the already-registered `ResearchCapability`/`IntelligenceCapability` (`capability=
"research"`/`"intelligence"`, matching `CAPABILITY_NAME` exactly as verified against
`capabilities/research_capability.py:36` and `capabilities/intelligence_capability.py:35`) with
**zero code change to either**.

**DECISION, binding — no new timeout value is introduced** (corrects MAJOR-2 of the Contract
Audit): `CONTENT_GENERATION`'s workflow-level `timeout_seconds` changes from `60` to `120` — this
is a **reuse of an already-existing, already-declared configuration value**, not a number derived
for this Contract. `120` is the exact `timeout_seconds` this codebase's only other 4-step
`WorkflowDefinition` (`NEWS_ANALYSIS`, `workflows/definitions/news_analysis.py:31`) already carries,
unmodified, today. Each individual step's `timeout_seconds=30` is likewise unchanged — the same
per-step value every `WorkflowStepDefinition` in this codebase already uses (`news_analysis.py`,
the prior 2-step `content_generation.py`, and every `CapabilityConfig(timeout_seconds=30)` on every
existing `CapabilityDefinition`). Phase 10 introduces **zero** new timeout mechanism and **zero**
new timeout values — only an already-existing number applied to a step count this workflow now
shares with `NEWS_ANALYSIS`.

**Correction to the prior draft of this Contract, binding**: the earlier claim that `120`s was
"already proven sufficient for a 4-step AI chain" is withdrawn. `NEWS_ANALYSIS` has never reached
`TaskStatus.COMPLETED` in this codebase — its `engagement` step names a capability
(`capability="engagement"`) that `capabilities/registry.py::build_registry()` never registers, so it
fails with `UnknownCapabilityError` every time it is run (independently confirmed by
`docs/phase9_9_5_completion_report.md` §9 item 3). Reusing `120` here is an act of configuration
consistency — the same number this repository already applies to its only other 4-step chain — not
an empirical performance claim; this Contract makes no claim that `120`s is sufficient for four live
OpenAI calls. Actual sufficiency is deferred entirely to Decision Resolution §13's own M0 smoke test
and ordinary production observation once M0-M4 are implemented; if it proves insufficient, adjusting
a single integer is a configuration change, not an architectural one, and does not require reopening
this Contract.

`WorkflowRunner`'s timeout *behavior* is unchanged by this Contract in every respect: the
whole-workflow `asyncio.wait_for` wrapper (`workflows/runner.py:134-136`) and each step attempt's
own fresh `timeout_seconds` budget (`workflows/runner.py:239`, governed by
`WorkflowStepDefinition.max_attempts`, default `3`, itself unchanged) both continue to work exactly
as they do today — only the two already-existing numeric values above are reused for two additional
steps.

**DECISION, binding — corrects CRITICAL-1 of the Final Re-Audit — this Contract authorizes editing
exactly three existing files, no more**:
(1) `workflows/definitions/content_generation.py` (`steps` list and `timeout_seconds` only —
`max_iterations`, `retry_policy`, `required_input`, `version` are unchanged; `expected_output` MAY
be extended to name `research`/`intelligence`'s contribution, implementation detail, not frozen
here); (2) `capabilities/quality_capability.py`, narrowly, exactly as §5.1 specifies (its
`_build_request()` function and its `PROMPT_VERSION` constant only — its `__init__`, its
`execute()` control flow, its Gateway-call/validation/error-handling logic, and its
`QUALITY_CAPABILITY_DEFINITION` are all otherwise unchanged); and (3) `capabilities/registry.py`,
narrowly, exactly two lines added to `build_registry()` — one new import line
(`from capabilities.copywriting_capability import COPYWRITING_CAPABILITY_DEFINITION,
CopywritingCapability`) and one new `registry.register(COPYWRITING_CAPABILITY_DEFINITION,
CopywritingCapability(gateway, prompt_repository))` call, placed alongside the four existing
`register()` calls (`capabilities/registry.py:134-137`) — mirroring that exact, already-established
pattern with zero other change to the file (its `CapabilityRegistry` class, its `Capability`
Protocol, its `seal()` call, and every existing `register()` call are byte-for-byte unchanged).
Without this third file, `CapabilityRegistry.resolve("copywriting")` always raises
`UnknownCapabilityError` and `CONTENT_GENERATION` can never reach `TaskStatus.COMPLETED` —
`docs/phase10_decision_resolution.md`'s own M2 milestone row (line 290) already named this
registration as required; this correction brings §3 back into agreement with it.

**DECISION, binding — new files this Contract authorizes creating** (distinct from the three-file
edit list above; equally binding and equally exhaustive — no other new production file is
authorized):
- `capabilities/copywriting_capability.py` (§5) — `CopywritingCapability`'s implementation.
- `prompts/copywriting/v1.yaml` (§5, §6) — its prompt content, per §6's prompt-ownership rule.
- `prompts/quality/v2.yaml` (§5.1, §6) — the amended Quality prompt version (`prompts/quality/
  v1.yaml` is unmodified, not newly created).
- `schemas/content_draft.py` (§7.1, corrects MINOR-1 of the Final Re-Audit) — houses
  `ContentDraftRead`, the DTO §7.1's `create_from_result()` already names as its return type,
  mirroring `schemas/editorial_task.py`'s existing DTO pattern.
- `services/content_draft_service.py` (§7) — `ContentDraftService`'s implementation.
- `scripts/run_content_generation.py` (§9, corrects CRITICAL-1 of the Final Re-Audit's own
  re-audit) — the manual MVP trigger §9 already requires and describes in full; named here
  explicitly so §3's new-file list is actually exhaustive, not merely §9's own unlisted
  precondition. Authorizes exactly the script §9 specifies — a manual, one-shot CLI entry point,
  mirroring `scripts/run_triage.py`'s shape — and nothing broader: no scheduler, no daemon, no
  Telegram publisher, no background orchestration, no additional script.

No other production file — existing or new — is authorized for editing or creation by this
Contract. The following remain **byte-for-byte unchanged**, and no section of this Contract
authorizes touching them: `workflows/runner.py` (`WorkflowRunner`, including Phase 9.5's own
per-step persistence invariant), `capabilities/executor.py` (`CapabilityExecutor`),
`TaskStatus`/`EditorialTask` lifecycle semantics (`database/models/editorial_task.py`),
`workflows/registry.py`'s registration mechanics, every part of `capabilities/quality_capability.py`
not explicitly named in §5.1, and every part of `capabilities/registry.py` other than the two lines
named above.

---

## 4. Workflow Ownership Rule

**DECISION, binding**: `research`, `intelligence`, `copywriting`, and `quality` are four steps of
**one** `EditorialTask` (one `WorkflowExecutionState`, one `task.workflow` JSON blob) when that
task's `workflow_type == WorkflowType.CONTENT_GENERATION`. They MUST NOT create, read, or write
any *other* `EditorialTask` row. They MUST NOT communicate through any database table — no new
table, no cross-task query. They MUST communicate exclusively through
`context.business.workflow_state.step_results`, exactly as Phase 9 Contract §9.1 already
established and Phase 9.5 §3-§4 made reliably available within one uninterrupted `run()` call.

**DECISION, restated for clarity**: a `NEWS_ANALYSIS` task and a `CONTENT_GENERATION` task for the
same `NewsEvent` remain two fully independent `EditorialTask` rows (confirmed:
`_find_active_task()`, `services/workflow_service.py:89-106`, enforces uniqueness per
`(event_id, workflow_type)`, not per event alone). `CONTENT_GENERATION`'s own `research`/
`intelligence` steps run **independently** of any `NEWS_ANALYSIS` task that may or may not exist
for the same event — this Contract does not introduce, and explicitly forbids introducing, any
mechanism for one to read the other's data (see §14's named risk on duplicate Gateway calls).

---

## 5. CopywritingCapability Contract

**DECISION — Input, frozen**: `CopywritingCapability` reads exactly
`context.business.workflow_state.step_results.get("research", {})` and
`context.business.workflow_state.step_results.get("intelligence", {})` — the exact, already-
established key names. It additionally reads `context.business.news_event` (title/category only,
never re-deriving facts from raw content — mirroring `IntelligenceCapability`'s own "MUST NOT
re-extract" discipline, Phase 9 Contract §9).

**DECISION — Output schema, frozen, binding** (corrects the prior draft, which left this as
"implementation detail" — now resolved per the Contract Audit's explicit request):
`CopywritingCapability`'s `CapabilityDefinition.expected_output_keys` is exactly `["title", "body",
"hashtags"]`, and its resolved prompt's `output_schema` (`prompts/copywriting/v1.yaml`, §6) is
exactly:

```yaml
output_schema:
  type: object
  properties:
    title:
      type: string
    body:
      type: string
    hashtags:
      type: array
  required:
    - title
    - body
    - hashtags
```

chosen to map directly, with no translation logic, onto `ContentDraft`'s own existing columns
(`title`, `body`, `hashtags`) — `ContentDraftService` (§7.1) copies these three keys verbatim. This
shape is validated at runtime by the same `_floor_validate()` floor every existing Capability
already applies (required-key presence + declared-type check, e.g.
`capabilities/research_capability.py:57-82`'s pattern, duplicated per-Capability by established
convention) — no new validation mechanism is introduced.

**DECISION — Forbidden, binding** (restating Phase 6/8's already-frozen rules, specialized to this
Capability, no exception):
- MUST NOT import `capabilities/research_capability.py` or `capabilities/intelligence_capability.py`
  — verified mechanically via the same AST-based import check `IntelligenceCapability`'s own Phase
  9 test already established (`tests/test_intelligence_capability.py::
  test_non_coupling_never_imports_research_capability`), reused for Copywriting against both names.
- MUST NOT hold a database session or import `database.session`/`sqlalchemy` (Phase 6 P8, already
  mechanically enforced by `scripts/validate_architecture.py`'s `capability-isolation` rule for
  any new file under `capabilities/`, zero validator change needed).
- MUST NOT call Telegram, `bot/`, or any external service other than through `LLMGateway`.
- MUST use the existing `capabilities/gateway_call.py::call_generate()` mechanism, the existing
  `CapabilityResult`/`CapabilityError` shapes, and `PromptRepository.resolve()` — no forked
  execution, retry, or error-translation rule (Phase 8 contract §11, unchanged, cited not
  reopened).

### 5.1 QualityCapability Adaptation (the second, and only other, authorized Capability amendment)

**DECISION, binding — corrects MAJOR-1 of the Contract Audit**: `QualityCapability`, as it exists
today, never reads `context.business.workflow_state.step_results` at all — confirmed directly
(`capabilities/quality_capability.py:81-108`) and confirmed by its own prompt content
(`prompts/quality/v1.yaml:4-7`, "Given a news event's title, category, and summary..."). Reusing it
"unmodified," as the prior draft of this Contract stated, would place `quality` last in the chain
without it ever reviewing what `copywriting` produced. This Contract corrects that: `quality`'s
role in the `CONTENT_GENERATION` chain is to gate the generated draft, and `QualityCapability` is
amended, narrowly, to do that — while preserving Phase 8's Capability architecture without
exception.

**Scope of the amendment, binding, nothing more than this**:
- `capabilities/quality_capability.py::_build_request()` is amended to additionally read
  `context.business.workflow_state.step_results.get("copywriting", {})` and format its `title`/
  `body`/`hashtags` (§5's frozen output schema) into the same `context_text` block the function
  already builds from `news_event` fields — mirroring exactly how
  `IntelligenceCapability._build_request()` (`capabilities/intelligence_capability.py:93-106`)
  already formats `step_results["research"]` into its own `context_text`. No existing
  `NewsEvent`-reading behavior is removed — `quality` continues to see `title`/`category`/`summary`
  too, so it can still flag a poor underlying event, exactly as it does today.
- `capabilities/quality_capability.py::PROMPT_VERSION` changes from `"1"` to `"2"`, resolving a new
  `prompts/quality/v2.yaml` (§6) whose `system`/`rules` text is rewritten to instruct the model to
  assess the **generated draft** (when present) against basic editorial quality standards, not
  merely the raw event. `prompts/quality/v1.yaml` is left in place, untouched, immutable — Phase 6
  §8's prompt-versioning discipline (never delete or mutate a published version) applies exactly as
  it does to every other prompt in this repository.
- `QUALITY_CAPABILITY_DEFINITION`'s `expected_output_keys` (`["passed", "issues"]`) and
  `prompts/quality/v2.yaml`'s `output_schema` are **unchanged** from `v1`'s shape — only what
  `_build_request()` assembles changes, not what `QualityCapability` returns. `ContentDraftService`
  (§7.1) does not depend on Quality's output shape changing.
- Nothing else in `capabilities/quality_capability.py` changes: `__init__(gateway,
  prompt_repository)`, `execute()`'s control flow, its `call_generate()` usage, its
  `_floor_validate()` floor, its `CapabilityResult` construction, and its error handling are
  **byte-for-byte identical** to today. No new dependency, no new constructor parameter, no new
  Capability-Protocol method. This is a change to what one existing method reads and which prompt
  version it resolves — not a redesign of `QualityCapability`, and not a redesign of the Capability
  pattern itself (Phase 8 §2/§4.2 continue to hold without exception).
- `QualityCapability` still MUST NOT import `capabilities/copywriting_capability.py` — it reads
  Copywriting's output exclusively via `step_results["copywriting"]`, identically to how
  `IntelligenceCapability` already reads `step_results["research"]` without importing
  `ResearchCapability`. The AST-based non-coupling test technique (§5, §12) is extended to cover
  this pair too.

**Why this is authorized here, explicitly, and not left implicit**: Decision Resolution §13's M2
milestone table named "Any change to Research/Intelligence/Quality" as explicitly excluded from
that document's own scope. This Contract, once approved, sits above Decision Resolution in this
document's own source-of-truth order (see header) specifically so a narrow, load-bearing correction
like this one can be made deliberately, in binding form, rather than by silent omission — which is
exactly the gap the Contract Audit's MAJOR-1 finding identified. This paragraph is that deliberate
correction, not an unscoped reopening: everything else Decision Resolution §13 excluded from M2 (any
change to Research or Intelligence, any `WorkflowRunner`/`WorkflowType` change) remains excluded.

---

## 6. Prompt Ownership

**DECISION, binding**: all of `CopywritingCapability`'s prompt content (system text, rules,
`output_schema`) lives in `prompts/copywriting/v1.yaml`, matching the unbroken, already-verified
precedent of `prompts/research/v1.yaml`, `prompts/intelligence/v1.yaml`,
`prompts/scoring/v1.yaml`, and `prompts/quality/v1.yaml` (all four read and confirmed this
session). `capabilities/copywriting_capability.py` MUST contain **zero** embedded prompt strings
— only request-assembly and execution logic (`_build_request()`, `execute()`), exactly mirroring
every existing Capability's `_build_request()` shape.

**DECISION, binding — prompt `expected_output` contract** (added per the Contract Audit's explicit
request): every prompt's `output_schema` (the `RenderedPrompt.output_schema` field
`FilePromptRepository` loads verbatim from YAML, `integrations/prompts/protocol.py:12-18`) is the
single source of truth for what a Capability's `_floor_validate()` enforces, and MUST match its
`CapabilityDefinition.expected_output_keys` one-for-one — the YAML `output_schema`'s `required` list
MUST equal `expected_output_keys` exactly, the same convention every existing prompt
(`prompts/research/v1.yaml`, `prompts/intelligence/v1.yaml`, `prompts/quality/v1.yaml`) already
follows. §5's frozen `output_schema` for `prompts/copywriting/v1.yaml` is a binding instance of this
rule, not an exception to it.

**DECISION, binding — the second, `quality`-owned prompt version**: `prompts/quality/v2.yaml` is
added (§5.1); `prompts/quality/v1.yaml` is left in place, unmodified, per Phase 6 §8's
prompt-immutability rule. `QualityCapability`'s own `PROMPT_VERSION` constant is the only thing that
changes to point at it — `FilePromptRepository` requires no code change to discover a new version
file (`integrations/prompts/file_repository.py:109-121`'s directory/glob discovery already handles
it automatically).

---

## 7. ContentDraft Lifecycle

**FACT**: `database/models/content_draft.py` already defines `ContentDraft` with `task_id` (FK),
`type` (`ContentType`: `POST`, `SHORT`, `ANALYSIS`, `MEME`, `VIDEO_SCRIPT`), `title`, `body`,
`hashtags` (JSON), `version` (int, default 1), `status` (free-text, no constrained enum — per the
model's own comment, "not enumerated in the project documentation").

**DECISION, binding — who creates it**: Capabilities MUST NOT create, update, or hold any
reference to a `ContentDraft` row (Phase 6 P1/P4, restated, no exception for this Capability).
`WorkflowRunner` never writes a `ContentDraft` row — `workflows/runner.py` has no reference to
`ContentDraft` anywhere, and this Contract does not add one (§3's byte-for-byte-unchanged list).
`CapabilityExecutor` never writes a `ContentDraft` row either — `capabilities/executor.py` remains
strictly a `StepExecutor` bridge that returns a `dict[str, Any]` to `WorkflowRunner`
(`capabilities/executor.py:59-109`) and holds its database session read-only, exactly as Amendment B
(Phase 6 Contract §16) already requires; this Contract adds no write path to it. The only component
ever authorized to create a `ContentDraft` row is `ContentDraftService` (§7.1) — named explicitly,
replacing the prior draft's looser "a new function in `services/content_draft_service.py`" language.

### 7.1 ContentDraftService — ownership, session, and commit boundary (corrects MAJOR-3 of the Contract Audit)

**DECISION, binding — corrects MINOR-1 of the Final Re-Audit**: `schemas/content_draft.py`
(housing `ContentDraftRead`) is an explicitly authorized new file, per §3's new-file list — named
here directly, not merely implied by this section's own return-type reference, mirroring
`schemas/editorial_task.py`'s existing DTO pattern.

**DECISION, binding**: `ContentDraftService` is a class in `services/content_draft_service.py`,
constructed as `ContentDraftService(session: AsyncSession)`, with one public method:
`async def create_from_result(self, task_id: UUID, result: WorkflowRunResult) -> ContentDraftRead`.
It is called **after** `WorkflowRunner.run()` returns a `COMPLETED` `WorkflowRunResult` — never
before, never for a `FAILED` result — reading `result.step_results`'s `"copywriting"` entry (§5's
frozen output schema) already in hand.

**DECISION, binding — session ownership**: `ContentDraftService` is constructed with the **same
`AsyncSession`** the caller already used for `WorkflowRunner.run()` — constructor injection, exactly
the existing convention `workflow_service.create_task(session, ...)` and `WorkflowRunner.run(session,
task_id)` already both use. It does **not** open a new session or a new connection. This is safe
specifically because of Phase 9.5's own already-established precondition, `expire_on_commit=False`
(`database/session.py:14`, `tests/conftest.py:65`): a session remains fully usable for a new
`session.add()`/`await session.commit()` immediately after an earlier, unrelated commit on the same
session has already closed — the identical precondition Phase 9.5's own per-step persistence
mechanism depends on, restated here rather than silently assumed a second time.

**DECISION, binding — commit boundary**: `ContentDraftService.create_from_result()` owns its own,
single, deterministic commit — it calls `session.add(ContentDraft(...))` followed by exactly one
`await session.commit()`, and nothing else in this Contract commits on its behalf. This is a
**separate transaction** from whichever transaction `WorkflowRunner.run()`'s own final commit
(`workflows/runner.py:207`, already durable, already closed) belonged to — the two are sequential,
not atomic with each other.

**DECISION, binding — failure/rollback semantics, deterministic, not hidden**: if
`ContentDraftService.create_from_result()`'s own commit fails, that failure is atomic and
deterministic for its own write only — no partial `ContentDraft` row is ever left committed (the one
`session.add()` + one `session.commit()` pair either both take effect or neither does, ordinary
SQLAlchemy/Postgres transaction semantics, nothing new introduced). The exception propagates
uncaught to the caller (§9's CLI trigger) — `ContentDraftService` MUST NOT swallow it. This Contract
explicitly does **not** promise that a `ContentDraftService` failure rolls back the task's own
already-committed `TaskStatus.COMPLETED` state — that commit (`workflows/runner.py:207`) happened in
an earlier, already-closed transaction and cannot be retroactively undone. A task that reaches
`COMPLETED` with no corresponding `ContentDraft` row is therefore a real, reachable state under this
design (e.g., a transient DB error between the two calls); it MUST be detectable — the CLI trigger
(§9) MUST log and surface this case distinctly from a clean success, never silently succeed — and its
recovery (a re-run, a repair script, or an alert) is explicitly out of scope for Phase 10 (§13),
named here as an accepted, disclosed gap, not an unstated one.

**Clarification, binding — corrects MINOR-1 of the Final Re-Audit's own re-audit — post-hoc
discoverability, described against the real schema**: the CLI's log line is not this gap's only
detection path, but the query concept must be stated accurately. `EditorialTask` has no dedicated
`workflow_type` column: `_find_active_task()` (`services/workflow_service.py:89-106`) matches
`workflow_type` against the `workflow_name` key inside `EditorialTask.workflow`'s JSON payload
("`workflow_type` is matched against the JSON snapshot's `workflow_name` field, since
`EditorialTask` has no dedicated column for it"), an unindexed `JSON` column
(`database/models/editorial_task.py:44`). `EditorialTask.status`, by contrast, **is** a dedicated,
indexed column (`database/models/editorial_task.py:45-46`, `index=True`). `ContentDraft.task_id`
is an ordinary `ForeignKey` column (`database/models/content_draft.py:34-36`) with no explicit
index declared. Given this, a `COMPLETED` `CONTENT_GENERATION` task with no `ContentDraft` row is
still discoverable later, by anyone with database access, via a direct query with no new mechanism
required — conceptually: `EditorialTask` rows where `status = COMPLETED` (using the indexed column)
**and** `workflow->>'workflow_name' = 'CONTENT_GENERATION'` (a JSON-field filter, the same
`workflow_name` key `_find_active_task()` already reads), LEFT JOINed against `ContentDraft` on
`task_id`, filtered to `ContentDraft.id IS NULL`. This requires zero new code, table, column, index,
or migration — every field the query touches already exists exactly as described, and it is
available today, ad hoc, exactly as any other production debugging query already is; it is simply
not index-accelerated on the JSON-field predicate, an acceptable cost for a manual, infrequent
diagnostic query, not a production hot path. This Contract does not schedule, automate, or build
tooling around that query (no scheduler, no monitoring, no recovery engine — §13 unchanged);
running it is manual and out of scope for Phase 10 to formalize, same as recovery itself.

**Architecture, frozen**:
```
WorkflowRunner.run(session, task_id) -> WorkflowRunResult (COMPLETED)   [session's own commit, already durable]
      |
      v
ContentDraftService(session).create_from_result(task_id, result)        [same session, new commit]
      |
      v
ContentDraft row
```

**DECISION — statuses this phase writes, frozen**: Phase 10 writes exactly one status value,
`"draft"`, and never transitions a `ContentDraft` row to any other status — no review/approval/
publish workflow exists yet (that is future, out-of-scope work, §10). `version` is always `1`
(Phase 10 never regenerates or re-versions a draft). `type` is always `ContentType.POST` — `MEME`,
`SHORT`, `ANALYSIS`, `VIDEO_SCRIPT` are explicitly out of scope (§13); `ContentType.MEME`'s mere
existence on the enum does not authorize writing it. `title`/`body`/`hashtags` are copied verbatim
from `result.step_results`'s `"copywriting"` entry's `title`/`body`/`hashtags` keys (§5's frozen
output schema) — `ContentDraftService` performs no reformatting, truncation, or validation beyond
what `CopywritingCapability`'s own floor-validation (§5) already guaranteed before this step's
result was ever persisted.

**DECISION, binding**: no migration. `ContentDraft`'s existing columns and `ContentType` enum are
used exactly as they exist today — confirmed sufficient for this phase's needs (§7's FACT above).

---

## 8. LLM Provider Usage

**DECISION, binding**: production API usage continues through the existing, frozen `LLMGateway`
Protocol, `RoutingGateway`, `FallbackPolicy`, `RoutingEngine`, and `ProviderRegistry` exactly as
they exist today (`integrations/llm_gateway/`, unmodified). `OpenAIAdapter`
(`integrations/llm_gateway/providers/openai_adapter.py`) — already code-complete for `generate()`
— requires no code change.

**DECISION — what Phase 10 changes**: production environment configuration only —
`Settings.enabled_providers` includes `"openai"`, `Settings.openai_api_key` holds a real
credential, Redis/Postgres are confirmed provisioned in the target environment — plus exactly one
manual, out-of-band live smoke test proving `RoutingGateway.generate()` succeeds against the real
API. This smoke test MUST NOT be added to the automated test suite, matching this repository's
unbroken no-real-network-call testing discipline (Phase 7 §15.5, cited, unchanged).

**DECISION — what Phase 10 does NOT change**: the `LLMGateway` Protocol shape, `RoutingEngine`'s
selection logic, `FallbackPolicy`, any provider adapter file, `integrations/llm_gateway/models/
catalog.py`, `BudgetGuard`/`CostTracker`'s own logic (both already wired; Phase 10 verifies they
are active, builds nothing new), or `enabled_providers`' set beyond adding `"openai"` (no second
provider, §2).

---

## 9. Trigger Architecture

**DECISION, binding — MVP trigger**: `scripts/run_content_generation.py`, mirroring
`scripts/run_triage.py`'s exact, already-proven shape: `setup_logging()` plus exactly one
`services/`-layer async call that, within one script-level session scope, creates a
`CONTENT_GENERATION` task, runs it via `WorkflowRunner.run(session, task_id)`, and then — using that
same `session` (§7.1) — invokes `ContentDraftService(session).create_from_result(task_id, result)`
on a `COMPLETED` result. Per §7.1's disclosed failure semantics, this caller MUST distinguish and
log three outcomes distinctly: (a) full success (`ContentDraft` created), (b) task `FAILED` (no
`ContentDraft` attempted), and (c) task `COMPLETED` but `ContentDraftService` raised (a detectable,
surfaced gap, not a silent partial success).

**DECISION, binding — explicitly forbidden**: no scheduler, cron, or timer of any kind; no
Telegram admin command wiring (`bot/` is untouched by this Contract); no automatic-execution path.
A human or an external process invokes this script manually — exactly `scripts/run_triage.py`'s
own current, unscheduled production status (Phase 9 Contract §7.4, cited precedent).

---

## 10. Telegram Boundary

**DECISION, binding**: Telegram publishing is entirely out of scope for Phase 10 (§2, §13). No
file under `bot/` is touched; no `integrations/telegram/` directory is created.

**DECISION — future architecture, conceptual only, not designed or authorized for implementation
by this Contract**:
```
ContentDraft
      |
      v
PublisherService   (future phase)
      |
      v
Telegram integration   (future phase)
```
`PublisherService` would be a `services/`-layer component (never a Capability — Phase 6 forbids a
Capability calling any external service directly), the structural, opposite-direction analog of
`services/collector.py`'s existing inbound role. This Contract does not authorize building it.

---

## 11. Meme Generation Boundary

**DECISION, binding**: meme generation — both opportunity-detection and image-rendering halves —
is explicitly out of scope for Phase 10, deferred to its own, future, separate phase.

**Why, restated from Discovery §8 and Decision Resolution §12**:
- **Image generation problem**: `LLMGateway.generate()` (`integrations/llm_gateway/protocol.py:
  60-95`) is chat/completion-shaped. `ContentPart.artifact_ref` and `GenerateRequest.modalities`
  are used today for image **input** (vision) only — confirmed via
  `openai_adapter.py::_translate_content_part` (`"input_image"`), never image **output**. No
  `generate_image()` or equivalent method exists on the Protocol.
- **`LLMGateway` limitation, binding consequence**: adding image-output capability would require
  either amending the frozen Phase 6 `LLMGateway` Protocol (its own, separate contract-amendment
  process, not authorized here) or building a deliberately parallel, non-`LLMGateway` integration
  — a decision this Contract does not make, matching Decision Resolution §12's own explicit
  deferral.
- **Separate pipeline needed**: actual image rendering (provider SDK for image models, binary
  artifact handling, storage) is a materially different technical problem from text generation;
  conflating it with `CopywritingCapability`'s text-only delivery would violate the
  smallest-correct-phase discipline this Contract and its predecessor documents establish.

---

## 12. Testing Requirements

Binding minimums for whichever future implementation phase builds against this Contract (none
written by this document):

**Capability tests** (`CopywritingCapability`, mirroring `tests/test_research_capability.py`/
`tests/test_intelligence_capability.py`'s exact conventions):
- Happy path against `FakeLLMGateway` + `FakePromptRepository`, asserting the returned
  `structured_output` matches the frozen output schema (§5) exactly — `title`/`body`/`hashtags`.
- `PromptRepository.resolve()` usage — the built request's system/rules text comes from the
  resolved prompt, never embedded Python strings.
- `call_generate()` usage — the centralized Gateway-call mechanism, not reimplemented.
- Structured-output validation-floor enforcement — a malformed response raises
  `ValidationCapabilityError`.
- `GatewayError` → `CapabilityError` translation, exercised via `FakeLLMGateway.generate_error()`.
- The non-coupling AST-based import check (§5): `CopywritingCapability` MUST NOT import
  `research_capability`/`intelligence_capability`.

**QualityCapability adaptation tests** (§5.1, new — mandatory, since §5.1 amends existing,
previously-tested behavior):
- `QualityCapability`'s built request, given a non-empty `step_results["copywriting"]`, contains
  the copywriting draft's `title`/`body`/`hashtags` content — the same "prove data flowed"
  discipline applied below to Research→Intelligence, applied here to Copywriting→Quality.
- `QualityCapability`'s built request, given an *empty* `step_results["copywriting"]` (e.g. a
  hand-constructed `CapabilityContext` simulating Quality run outside the `CONTENT_GENERATION`
  chain), still succeeds and still includes `news_event.title`/`category`/`summary` — §5.1's "no
  existing NewsEvent-reading behavior is removed" guarantee, regression-tested explicitly.
- `PROMPT_VERSION` resolves `"2"`; `prompts/quality/v1.yaml` is untouched on disk and still
  independently resolvable by an explicit `resolve("quality", "1")` call — proving v1 was not
  deleted or mutated, only superseded as the default.
- The non-coupling AST-based import check is extended: `QualityCapability` MUST NOT import
  `copywriting_capability`.
- `QUALITY_CAPABILITY_DEFINITION.expected_output_keys` and `prompts/quality/v2.yaml`'s
  `output_schema` are asserted identical to `v1`'s — proving the amendment changed only the input
  side, not the output contract.

**Registry resolution tests** (§3, new — corrects MINOR-2 of the Final Re-Audit's own re-audit;
previously only implied transitively through the full-chain workflow test below, now an explicit,
direct proof obligation):
- After `build_registry()` runs with `capabilities/registry.py`'s two-line addition (§3) in place,
  `CapabilityRegistry.resolve("copywriting")` returns the registered
  `(COPYWRITING_CAPABILITY_DEFINITION, CopywritingCapability(...))` pair directly — asserted without
  going through a full workflow run, the same direct-`resolve()` technique already used for the four
  pre-existing registrations.
- Unknown-capability behavior is unchanged by this addition: `CapabilityRegistry.resolve()` called
  with a name no `build_registry()` call ever registers (e.g. `"engagement"`, already unregistered
  today, §3) still raises `UnknownCapabilityError` — proving the two-line registry addition is
  purely additive and does not alter `resolve()`'s or `register()`'s existing behavior for any other
  name.

**Workflow tests** (mirroring `tests/test_phase9_research_intelligence_integration.py`'s
established technique):
- `research → intelligence → copywriting → quality` executes in that exact order through the
  real, unmodified `WorkflowRunner`/`CapabilityExecutor`/`CapabilityRegistry`, reaching
  `TaskStatus.COMPLETED`.
- `step_results` propagation is proven by inspecting `CopywritingCapability`'s actually-built
  request content for Research's/Intelligence's facts, and `QualityCapability`'s actually-built
  request content for Copywriting's draft — not merely asserting a `SUCCESS` status (the same
  "prove data flowed" discipline Phase 9 M7 and Phase 9.5 M1 both already established, now applied
  to the full four-step chain).

**ContentDraft tests**:
- A `ContentDraft` row is created only after a `COMPLETED` `WorkflowRunResult` — never on a
  `FAILED` run, never mid-run.
- A dedicated check (mirroring the architecture validator's own named-file pattern) confirms no
  file under `capabilities/` imports `database.models.content_draft.ContentDraft` — no Capability
  ever creates a draft, proven mechanically, not merely asserted in prose.
- **Mandatory durability test (added per the Contract Audit's explicit request, corrects
  MINOR-2)**: a `ContentDraft` row created by `ContentDraftService.create_from_result()` is proven
  durable to a genuinely independent database connection — not merely visible within the producing
  session. This MUST reuse the exact `independent_session_factory()`/`real_committed_event()`-style
  technique already established in `tests/test_triage_orchestrator_claims.py` and reused in
  `tests/test_workflow_runner_per_step_persistence.py` (Phase 9.5 M2's own precedent) — the standard
  `db_session` fixture's SAVEPOINT-based semantics MUST NOT be relied upon for this specific test,
  for the same false-pass reason Phase 9.5 Contract Audit MAJOR-2 already established.
- A test proving `ContentDraftService`'s session-reuse claim (§7.1): given a session that has
  already been used for a prior, committed `WorkflowRunner.run()` call, a subsequent
  `ContentDraftService(session).create_from_result(...)` call on that same session succeeds and
  commits — proving the `expire_on_commit=False` precondition (§7.1) actually holds, not merely
  assuming it by analogy to Phase 9.5.

**CLI tests**:
- `scripts/run_content_generation.py`'s underlying `services/`-layer function, invoked directly
  (mirroring how `services.triage_orchestrator.run_triage_cycle()` is tested, not the thin script
  wrapper itself), creates, runs, and persists a `ContentDraft` successfully against fakes.
- The three-outcome distinction §9 mandates (clean success / task `FAILED` / task `COMPLETED` with
  `ContentDraftService` failure) is exercised and asserted distinctly — not collapsed into a single
  pass/fail check.

---

## 13. Non-Goals

Phase 10 does NOT deliver:

1. Telegram publishing of any kind.
2. Meme generation, in any form (opportunity detection or image rendering).
3. Image generation of any kind.
4. A scheduler or any automatic-execution mechanism.
5. Analytics of any kind (engagement, performance, or otherwise).
6. A user-facing product surface (no new bot command, no new API endpoint, no new UI).
7. A second LLM provider.
8. Any `WorkflowRunner`/`CapabilityExecutor`/`WorkflowExecutor` redesign.
9. Crash recovery or a resume mechanism (Phase 9.5's own disclosed limitation, unchanged).
10. `ContentDraft` review/approval/publish status transitions (only `"draft"` is ever written).

---

## 14. Risks

- **Workflow-definition expansion risk** (§3): editing `content_generation.py`'s step list is a
  change to a Phase 5 workflow *definition* file. This Contract's position, stated explicitly and
  not left implicit, is that a definition's step list is pipeline-shape configuration, distinct
  from `WorkflowRunner`'s frozen engine mechanics — but it is still a real, narrow amendment this
  Contract must, and does, explicitly authorize (§3), not a change any future phase should assume
  pre-approved by analogy.
- **API cost**: real, billed API calls become possible once `enabled_providers` includes
  `"openai"` in production. `BudgetGuard`/`CostTracker` already exist and mitigate this, but Phase
  10 adds no new cost-control mechanism (§8) — a misconfiguration risk is operational, not
  architectural, but named here for visibility.
- **Prompt quality**: `CopywritingCapability`'s and the amended `QualityCapability`'s prompts are
  both unproven against the live API until the M0 smoke test and a real M1 run both occur; content
  quality is not something an automated test can fully verify (§12's tests prove *mechanism*, not
  *editorial quality*).
- **Timeout budget is reused, not validated** (§3, corrected): `120`s for the whole workflow is the
  same number `NEWS_ANALYSIS` already declares, not a value independently proven sufficient for four
  live OpenAI calls — `NEWS_ANALYSIS` itself has never completed in this codebase. If it proves too
  tight in practice, adjusting it is a configuration change, not a reason to reopen this Contract.
- **`ContentDraft` ownership discipline**: the `ContentDraftService` boundary (§7, §7.1) must not be
  bypassed by a future change that lets a Capability or `CapabilityExecutor` write directly — the
  mechanical test in §12 exists specifically to catch this class of drift early.
- **`COMPLETED` task with no `ContentDraft` is a reachable, disclosed gap** (§7.1): if
  `ContentDraftService.create_from_result()` fails after `WorkflowRunner.run()` has already
  committed `TaskStatus.COMPLETED`, that completion is not retroactively rolled back. §9 requires
  the CLI trigger to detect and surface this case distinctly at the time it happens; it also remains
  discoverable after the fact via a direct query against existing, accurately-described columns
  (§7.1) — no scheduler or monitoring is added to automate that discovery. Its recovery (re-run,
  repair script, alert) is explicitly out of scope for Phase 10 (§13).
- **Duplicate Research/Intelligence Gateway calls** (§4): a `NewsEvent` with both an active
  `NEWS_ANALYSIS` task and an active `CONTENT_GENERATION` task would run Research/Intelligence
  independently, twice, for the same event — a real cost/consistency risk this Contract discloses
  but does not resolve (Decision Resolution §14/§15, carried forward as an open question, not
  silently accepted as fine).

---

## 15. Acceptance Checklist

Self-audited before this Contract is submitted for review:

1. **Phase 5 not violated** — confirmed: `workflows/runner.py`'s engine mechanics (including Phase
   9.5's per-step persistence invariant) are untouched (§3); only one workflow *definition* file's
   step list and timeout change, explicitly authorized, not a redesign; the reused `120`s/`30`s
   timeout values are not a new mechanism (§3, corrected).
2. **Phase 8 Capability rules preserved** — confirmed: `CopywritingCapability` accepts exactly
   `(gateway, prompt_repository)`, uses `call_generate()`, returns `CapabilityResult`, owns no
   infrastructure (§5); `QualityCapability`'s amendment (§5.1) touches only `_build_request()` and
   `PROMPT_VERSION` — its constructor, control flow, and error handling are byte-for-byte unchanged,
   so Phase 8 §2/§4.2 hold without exception for both Capabilities.
3. **Phase 9 `step_results` architecture preserved** — confirmed: Copywriting reads
   `step_results["research"]`/`step_results["intelligence"]`, and the amended `QualityCapability`
   reads `step_results["copywriting"]`, exactly as Intelligence already reads Research's output; no
   new propagation mechanism introduced anywhere (§4, §5, §5.1).
4. **No direct Capability coupling** — confirmed: `CopywritingCapability` MUST NOT import either
   `ResearchCapability` or `IntelligenceCapability`; the amended `QualityCapability` MUST NOT import
   `CopywritingCapability` — both mechanically enforced (§5, §5.1).
5. **No migrations unless approved** — confirmed: none authorized; `ContentDraft` used exactly
   as-is (§7).
6. **No Telegram coupling** — confirmed: `bot/` untouched; no Capability or service calls Telegram
   (§10).
7. **No meme-generation leakage** — confirmed: `ContentType.MEME` is never written by any Phase 10
   code path; only `ContentType.POST` (§7, §13).
8. **`ContentDraft` transaction ownership is explicit, not assumed** — confirmed: `ContentDraftService`
   (§7.1) names its session (the same one `WorkflowRunner.run()` used), its commit boundary (its own,
   separate, single commit), and its failure semantics (deterministic for its own write; the task's
   already-committed `COMPLETED` status is not retroactively rolled back, and this gap must be
   surfaced, not hidden, by the CLI trigger) — corrects MAJOR-3 of the Contract Audit.
9. **`QualityCapability` amendment is narrowly scoped, explicitly authorized, and does not redesign
   the Capability pattern** — confirmed (§5.1): one method's input-assembly and one prompt-version
   constant change; everything else about `QualityCapability`'s shape, and about the Capability
   Protocol itself, is untouched — corrects MAJOR-1 of the Contract Audit.
10. **A `ContentDraft` durability test is mandatory, not merely recommended** — confirmed (§12):
    reuses the Phase 9.5 M2 independent-connection technique, explicitly forbidding the
    `db_session` fixture for this specific test — corrects MINOR-2 of the Contract Audit.
11. **`CopywritingCapability` is actually resolvable at runtime** — confirmed (§3): `capabilities/
    registry.py` is explicitly, narrowly authorized for a two-line edit registering
    `CopywritingCapability`, mirroring its four existing `register()` calls exactly — corrects
    CRITICAL-1 of the Final Re-Audit.
12. **Every new file this Contract requires is explicitly authorized, not implied** — confirmed
    (§3): `capabilities/copywriting_capability.py`, `prompts/copywriting/v1.yaml`,
    `prompts/quality/v2.yaml`, `schemas/content_draft.py`, and `services/content_draft_service.py`
    are named in one exhaustive list; no other new file is authorized — corrects CRITICAL-1 and
    MINOR-1 of the Final Re-Audit.
13. **A `COMPLETED` task with no `ContentDraft` is discoverable, not just logged** — confirmed
    (§7.1, §14): a direct query against existing, unmodified columns finds this state after the
    fact, with no new mechanism, scheduler, or recovery engine introduced — corrects MINOR-2 of the
    Final Re-Audit.
14. **The MVP CLI trigger is authorized to exist** — confirmed (§3, §9): `scripts/
    run_content_generation.py` is named in §3's new-file list, resolving the contradiction where §9
    required a file §3 did not authorize — corrects CRITICAL-1 of the Final Re-Audit's own
    re-audit. No scheduler, daemon, or additional script is authorized alongside it.
15. **The `ContentDraft` discoverability query is described against the real schema** — confirmed
    (§7.1): `workflow_type` is named as living inside `EditorialTask.workflow`'s JSON payload (the
    `workflow_name` key), not a dedicated indexed column; `ContentDraft.task_id` is named as an
    ordinary, unindexed `ForeignKey` column — no fabricated index or column is claimed, and no
    migration is introduced — corrects MINOR-1 of the Final Re-Audit's own re-audit.
16. **Registry resolution has its own direct test obligation** — confirmed (§12): `CapabilityRegistry.
    resolve("copywriting")` succeeding, and `resolve()` on an unregistered name still raising
    `UnknownCapabilityError`, are both named explicitly, not left to transitive inference from the
    full-chain workflow test — corrects MINOR-2 of the Final Re-Audit's own re-audit.
17. **No production code, test, or migration was modified to produce this document** — confirmed
    (`git status --short` shows only modified/new, untracked documentation throughout this
    correction pass).

---

PHASE 10 CONTRACT REVISED (TARGETED CORRECTION, PASS 3) — READY FOR RE-AUDIT
