# Phase 10 — Implementation Plan

**Status: planning document. Does not modify the Architecture Contract, production code, tests, or
migrations.** Plans execution of `docs/phase10_production_content_pipeline_architecture_contract.md`
(revision 3, "PASS 3" — **frozen**, approved in `docs/phase10_final_architecture_reaudit.md`,
verdict `PHASE 10 CONTRACT APPROVED`, 9/10). This document does not reopen, reinterpret, or extend
any architecture decision the Contract already made. It sequences the Contract's own 9-file
authorized scope into milestones, specifies per-file implementation detail consistent with that
scope, and assigns the Contract's own §12 test obligations to milestones — it invents no new test
obligation and authorizes no file the Contract does not already authorize.

**Source-of-truth order, unchanged**: the Contract > `docs/phase10_decision_resolution.md` >
`docs/phase10_production_pipeline_discovery.md` > the frozen Phase 5/6/7/8/9/9.5 contracts. Where
this plan cites repository evidence, it was independently re-read this session, not copied from an
earlier document's word.

---

## 1. Authorized Implementation Scope (restated, not re-derived)

Per Contract §3, exhaustive:

**Existing files to edit (3):**
1. `workflows/definitions/content_generation.py`
2. `capabilities/quality_capability.py`
3. `capabilities/registry.py`

**New files to create (6):**
4. `capabilities/copywriting_capability.py`
5. `prompts/copywriting/v1.yaml`
6. `prompts/quality/v2.yaml`
7. `schemas/content_draft.py`
8. `services/content_draft_service.py`
9. `scripts/run_content_generation.py`

No other production file may be touched. `workflows/runner.py`, `capabilities/executor.py`,
`workflows/registry.py`, `capabilities/capability_mapping.py`, `integrations/llm_gateway/boot.py`,
`integrations/prompts/file_repository.py`, and `database/models/*` are all confirmed (§2 below)
to need **zero** change and remain byte-for-byte unchanged.

---

## 2. Milestone 0 — Repository Preparation (no code changes)

Verification checklist only. No file is written in this milestone; its sole output is a confirmed
"go" for Milestones 1–4. Each item below was independently re-read this session, not assumed.

| # | Component | Evidence | Status |
|---|---|---|---|
| 1 | `WorkflowRunner`'s step loop already supports an arbitrary step count | `workflows/runner.py:157` (`remaining_steps = [s for s in definition.steps if s.name not in state.completed_steps]`) iterates `definition.steps` generically — no hardcoded step count, no `if step.name == ...` branch anywhere in the file. Per-step persistence (`workflows/runner.py:189-199`) commits `task.workflow` after every `SUCCESS`/`SKIPPED` step, before the next one starts. | READY, zero change needed |
| 2 | `CapabilityExecutor` builds `step_results` from **all** prior `SUCCESS` steps, not just the immediately-preceding one | `capabilities/executor.py:125-134` (`_build_context`): `step_results={r.step_name: r.result for r in state.step_results if r.status == "SUCCESS" and r.result is not None}` — a dict comprehension over the full `state.step_results` list, keyed by step name. `quality`'s context will therefore contain `research`, `intelligence`, **and** `copywriting`'s outputs simultaneously once all three have run. | READY, zero change needed |
| 3 | `CapabilityExecutor.execute()` resolves the capability-name → `AICapability` mapping before dispatch | `capabilities/executor.py:80-83` calls `resolve_ai_capability(step.capability)`, raising `PermanentStepFailureError` if unmapped. `capabilities/capability_mapping.py:22` already maps `"copywriting": AICapability.COPYWRITING` — **confirmed present today, not something Phase 10 adds.** | READY, zero change needed (confirmed, not merely assumed) |
| 4 | `CapabilityRegistry.register()`/`.resolve()`/`.seal()` mechanics | `capabilities/registry.py:77-113` — plain dict-backed, sealed-after-boot, `UnknownCapabilityError` on miss. Milestone 2 adds exactly one `register()` call; the class itself is untouched. | READY, mechanics unchanged |
| 5 | `workflows/registry.py` re-registers `content_generation.DEFINITION` automatically | `workflows/registry.py:81-87`: `registry = build_registry()` runs once at import time and calls `registry.register(content_generation.DEFINITION)` — the **same module-level object** Milestone 2 edits in place. Editing `DEFINITION.steps`/`timeout_seconds` inside `content_generation.py` is sufficient; there is no separate re-registration step to perform or forget. | READY, zero change needed beyond the one authorized file |
| 6 | `FilePromptRepository` auto-discovers new prompt files with zero code change | `integrations/prompts/file_repository.py:109-121`: constructor iterates `root.iterdir()` for name-directories and `name_dir.glob("v*.yaml")` for version files. Adding `prompts/copywriting/v1.yaml` or `prompts/quality/v2.yaml` requires no change to this file — confirmed by direct read of the glob/iterdir logic, not merely cited. | READY, zero change needed |
| 7 | `assemble_ai_integration_layer()` already accepts an injected `PromptRepository` | `integrations/llm_gateway/boot.py:143-148`: signature is `assemble_ai_integration_layer(settings: Settings, prompt_repository: PromptRepository, *, redis_client: Redis | None = None) -> AIIntegrationLayer`. Returns `AIIntegrationLayer(gateway, capability_registry, cost_tracker)` (`boot.py:121-133, 217-219`), calling `build_registry(gateway, prompt_repository, budget_guard, tool_registry)` internally (`boot.py:215`). **Confirmed**: zero production code path calls this function today — every call site found is a test file (`tests/test_boot_assembly.py`, `tests/test_capability_boot_wiring_e2e.py`, `tests/test_phase8_cross_cutting_regression.py`, `tests/test_phase9_cross_cutting_regression.py`). Milestone 4's script is this repository's **first production caller** — flagged as Risk R1 (§7 below), not a blocker. | READY as infrastructure; **first production use**, not "already proven in production" |
| 8 | Database session: `expire_on_commit=False` | `database/session.py:14`: `async_session_factory = async_sessionmaker(engine, expire_on_commit=False)`. This is the precondition `ContentDraftService`'s same-session reuse (Contract §7.1) depends on — already true today, no change needed. | READY, zero change needed |
| 9 | `ContentDraft` model and its export | `database/models/content_draft.py:23-48` (`task_id` FK, `type`, `title`, `body`, `hashtags` JSON, `version`, `status` free-text). Already exported: `database/models/__init__.py:3,17`. No migration authorized or needed (Contract §7, confirmed sufficient). | READY, zero change needed |
| 10 | DTO pattern to mirror for `schemas/content_draft.py` | `schemas/editorial_task.py:26-42` (`EditorialTaskRead`: `model_config = ConfigDict(frozen=True, extra="forbid")`, plain field list, no ORM object crosses the boundary). | READY, pattern confirmed, no change needed to the file being mirrored |
| 11 | Class-based service precedent for `ContentDraftService` | `services/budget_guard.py:46-107` (`RedisBudgetGuard`): a class with `__init__(self, ...)` storing injected dependencies as private attributes, one public async method. Confirms `ContentDraftService` as a class is not an invented pattern in a codebase where `services/workflow_service.py` otherwise uses plain functions — both patterns have precedent, and Contract §7.1 already decided which one applies here. | READY, pattern confirmed |

**Milestone 0 completion criterion**: every row above is READY. All 11 are READY as of this plan.
**No file is created or edited in this milestone.**

---

## 3. Milestone 1 — `CopywritingCapability`

**Objective**: implement the one new Capability the Contract authorizes, structurally identical to
`ResearchCapability`/`IntelligenceCapability`/`QualityCapability`.

**Files involved**: `capabilities/copywriting_capability.py` (new), `prompts/copywriting/v1.yaml`
(new).

**Dependencies**: Milestone 0 only (buildable and unit-testable against fakes with zero dependency
on Milestone 2's registry/workflow wiring — mirrors Decision Resolution §13's M0/M1 "no dependency
on each other" note for the M0-smoke-test/M1-Capability pair, restated here for M1 against M2).

**Plan, `capabilities/copywriting_capability.py`**:

- `CAPABILITY_NAME = "copywriting"`, `PROMPT_VERSION = "1"`.
- `COPYWRITING_CAPABILITY_DEFINITION = CapabilityDefinition(name=CAPABILITY_NAME, version=1,
  config=CapabilityConfig(timeout_seconds=30), required_context=["news_event"],
  expected_output_keys=["title", "body", "hashtags"])` — the `timeout_seconds=30` value matches
  every existing `CapabilityDefinition` in this codebase (`schemas/capability_definition.py:11-24`
  confirms `CapabilityConfig` shape; `research_capability.py:39-45`, `intelligence_capability.py:
  38-44`, `quality_capability.py:35-41` all use `timeout_seconds=30` identically) — reused, not a
  new number, consistent with Contract §3's timeout-reuse discipline.
- `__init__(self, gateway: LLMGateway, prompt_repository: PromptRepository) -> None`, storing
  `self._gateway`/`self._prompt_repository` only — byte-identical to
  `QualityCapability.__init__`/`ResearchCapability.__init__`/`IntelligenceCapability.__init__`
  (`quality_capability.py:116-118`, `research_capability.py:121-123`,
  `intelligence_capability.py:135-137`).
- `_floor_validate(structured_output, output_schema)`: the exact same function body duplicated
  verbatim into this file, per this codebase's own established, deliberate convention (every one
  of the four existing Capabilities carries its own copy — see each file's module docstring citing
  "§19.2 Q1: validation-strategy sharing is deliberately left unresolved").
- `_format_research_facts(research_output)`-equivalent helper(s): mirror
  `intelligence_capability.py:84-90`'s `_format_research_facts()` exactly in shape — two small
  private functions, `_format_research_context(step_results.get("research", {}))` and
  `_format_intelligence_context(step_results.get("intelligence", {}))` (or one combined formatter;
  implementation detail, not frozen by the Contract), each returning a `"(... did not run ...)"`
  placeholder string when the corresponding `step_results` key is empty — mirroring
  `_format_research_facts`'s own empty-input branch (`intelligence_capability.py:85-86`) exactly,
  so `CopywritingCapability` degrades the same way `IntelligenceCapability` already does if run
  outside the real chain.
- `_build_request(context, prompt) -> GenerateRequest`: reads `context.business.news_event.title`/
  `.category` (never `.content`, mirroring `IntelligenceCapability`'s own "never re-extract facts
  from raw content" discipline, Contract §5's binding input rule), plus
  `context.business.workflow_state.step_results.get("research", {})` and
  `.get("intelligence", {})` (Contract §5's frozen key names — exactly
  `ResearchCapability`/`IntelligenceCapability`'s own `CAPABILITY_NAME` values, reused unmodified).
  Assembles `system_text`/`context_text`/`task_text` and returns a `GenerateRequest` with
  `response_mode="json_schema"`, `response_schema=prompt.output_schema` — identical shape to every
  existing `_build_request()` (`quality_capability.py:81-108`,
  `intelligence_capability.py:93-126`).
- `execute(self, context) -> CapabilityResult`: `started_at` → resolve prompt via
  `self._prompt_repository.resolve(CAPABILITY_NAME, PROMPT_VERSION)` → `_build_request()` → `await
  call_generate(self._gateway, request, runtime=context.runtime, sequence=0)` → on
  `outcome.error is not None`, log then `raise outcome.error` → `_floor_validate()` → raise
  `ValidationCapabilityError` on violation → return `CapabilityResult(status="SUCCESS",
  structured_output=..., calls=[outcome.call], started_at=..., finished_at=..., duration_seconds=
  ...)`. This control-flow sequence is copied line-for-line in shape from
  `quality_capability.py:120-161` — **zero deviation**, per Contract §5's "MUST use the existing
  `call_generate()` mechanism... no forked execution, retry, or error-translation rule."
- **Forbidden** (Contract §5, restated as an implementation constraint, not re-decided here): no
  `import capabilities.research_capability` / `capabilities.intelligence_capability`; no
  `import database.session` / `sqlalchemy`; no import of anything under `bot/`; no direct provider
  SDK import.

**Plan, `prompts/copywriting/v1.yaml`** (mirrors `prompts/quality/v1.yaml`'s exact top-level shape —
`name`/`version`/`system`/`rules`/`output_schema`, confirmed by direct read of that file):

```yaml
name: copywriting
version: "1"
system: >
  You are a copywriting assistant for an AI-driven news editorial pipeline. Given a news event's
  title and category, plus Research's extracted facts and Intelligence's editorial judgment, write
  a short social-ready post: a title, a body, and a small set of hashtags.
rules:
  - Base the draft only on the given title/category and the supplied Research/Intelligence output
    - never invent facts not present in either.
  - Keep the title concise and the body suitable for a short social post.
  - Hashtags must be relevant to the event's category and content, no more than a handful.
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

`output_schema.required` (`title`, `body`, `hashtags`) equals `expected_output_keys` exactly, per
Contract §6's binding prompt/Capability-definition matching rule — this YAML is the binding instance
of that rule, not drafted independently of it.

**Expected output** (structured, at runtime): `{"title": "...", "body": "...", "hashtags":
["...", ...]}`.

**Completion criteria**: `capabilities/copywriting_capability.py` exists, imports nothing forbidden,
and structurally matches the four-existing-Capability shape; `prompts/copywriting/v1.yaml` exists,
loads without `PromptContentError` via `FilePromptRepository`, and its `output_schema.required`
matches `COPYWRITING_CAPABILITY_DEFINITION.expected_output_keys` exactly.

**Verification required**: Contract §12's "Capability tests" list, assigned to this milestone (see
§8 below) — happy path, `PromptRepository.resolve()` usage, `call_generate()` usage, floor-validation
enforcement, `GatewayError` translation, AST-based non-coupling check.

---

## 4. Milestone 2 — Workflow Integration

**Objective**: make the four-step chain real and completable, and make `QualityCapability` actually
review `CopywritingCapability`'s output.

**Files involved**: `capabilities/registry.py` (edit), `workflows/definitions/content_generation.py`
(edit), `capabilities/quality_capability.py` (edit), `prompts/quality/v2.yaml` (new).

**Dependencies**: Milestone 1 must be complete first — `capabilities/registry.py`'s new line
imports `COPYWRITING_CAPABILITY_DEFINITION`/`CopywritingCapability` from
`capabilities/copywriting_capability.py`, which must exist.

**Plan, `capabilities/registry.py`** (exactly two lines, per Contract §3):

```python
from capabilities.copywriting_capability import COPYWRITING_CAPABILITY_DEFINITION, CopywritingCapability
```

added to the import block (`registry.py:50-53`, alongside the other three Capability imports), and

```python
registry.register(COPYWRITING_CAPABILITY_DEFINITION, CopywritingCapability(gateway, prompt_repository))
```

added inside `build_registry()` (`registry.py:133-138`), alongside the four existing `register()`
calls, before `registry.seal()`. Nothing else in this file changes — its class definitions, its
`Protocol`, its docstring, and every other `register()` call are byte-for-byte unchanged, per
Contract §3's explicit constraint.

**Plan, `workflows/definitions/content_generation.py`** (diff, per Contract §3's frozen §3 text):

```python
steps=[
    WorkflowStepDefinition(name="copywriting", capability="copywriting", timeout_seconds=30),
    WorkflowStepDefinition(name="quality", capability="quality", timeout_seconds=30),
],
...
timeout_seconds=60,
```

becomes

```python
steps=[
    WorkflowStepDefinition(name="research", capability="research", timeout_seconds=30),
    WorkflowStepDefinition(name="intelligence", capability="intelligence", timeout_seconds=30),
    WorkflowStepDefinition(name="copywriting", capability="copywriting", timeout_seconds=30),
    WorkflowStepDefinition(name="quality", capability="quality", timeout_seconds=30),
],
...
timeout_seconds=120,
```

`max_iterations`, `retry_policy`, `required_input` are unchanged. `expected_output` MAY be extended
to name Research/Intelligence's contribution (Contract §3 explicitly leaves this as an
implementation detail, not frozen) — e.g. `["research_summary", "intelligence_report",
"draft_content", "quality_report"]`; this plan recommends making the change for documentation
accuracy but it is not load-bearing for any runtime behavior (`expected_output` is not read by
`WorkflowRunner` anywhere — confirmed no reference to `WorkflowDefinition.expected_output` exists in
`workflows/runner.py`).

**Plan, `capabilities/quality_capability.py`** (per Contract §5.1, the second and only other
authorized Capability amendment):

- `_build_request()` gains one additional read: `copywriting_output =
  context.business.workflow_state.step_results.get("copywriting", {})`, formatted via a new small
  helper (e.g. `_format_copywriting_draft(copywriting_output)`, mirroring
  `intelligence_capability.py:84-90`'s `_format_research_facts()` shape and its
  empty-input-safe branch exactly) into the existing `context_text` block, appended after the
  current `news_event`-derived lines (`quality_capability.py:86-91`). The existing
  `news_event.title`/`category`/`summary` lines are **not removed** — `quality` still sees the raw
  event too, per Contract §5.1's explicit "no existing NewsEvent-reading behavior is removed"
  guarantee.
- `PROMPT_VERSION = "1"` → `PROMPT_VERSION = "2"` (one constant, one line).
- Nothing else in this file changes: `__init__`, `execute()`'s control flow, `_floor_validate()`,
  `CapabilityResult` construction, `QUALITY_CAPABILITY_DEFINITION` (including its
  `expected_output_keys=["passed", "issues"]`, unchanged) are byte-for-byte identical to today, per
  Contract §5.1's explicit, itemized "nothing else changes" list.
- `QualityCapability` still MUST NOT import `capabilities.copywriting_capability` — it reads
  Copywriting's output exclusively through `step_results["copywriting"]`.

**Plan, `prompts/quality/v2.yaml`** (new; `prompts/quality/v1.yaml` is left in place, untouched):

```yaml
name: quality
version: "2"
system: >
  You are an editorial quality-check assistant for an AI-driven news editorial pipeline. Given a
  news event's title, category, and summary, and — when present — a generated draft (title, body,
  hashtags), you assess whether the draft (or, absent one, the underlying event) meets basic
  editorial quality standards and list any issues found.
rules:
  - When a generated draft is present, assess the draft itself against basic editorial quality
    standards - clarity, absence of factual overreach beyond the given event, and internal
    consistency between title, body, and hashtags.
  - When no draft is present, fall back to assessing the underlying event exactly as v1 did:
    flag missing or vague titles, missing summaries, and factual-sounding claims with no
    supporting detail.
  - Do not invent issues that are not actually present.
  - Keep each issue description under 30 words.
output_schema:
  type: object
  properties:
    passed:
      type: boolean
    issues:
      type: array
  required:
    - passed
    - issues
```

`output_schema` is **identical** to `prompts/quality/v1.yaml`'s (`passed`/`issues`, both required) —
Contract §5.1 is explicit that only the input side changes, never the output contract.

**Completion criteria**: `build_registry()` runs without error and its resulting
`CapabilityRegistry.resolve("copywriting")` returns the registered pair; the workflow definition
declares four steps in the exact order `research → intelligence → copywriting → quality` with
`timeout_seconds=120`; `QualityCapability`'s `_build_request()` includes Copywriting's draft content
in its assembled `context_text` when `step_results["copywriting"]` is non-empty, and still includes
`news_event` fields regardless.

**Verification required**: Contract §12's "QualityCapability adaptation tests" and "Registry
resolution tests" lists, assigned to this milestone (§8 below).

---

## 5. Milestone 3 — `ContentDraft`

**Objective**: give the pipeline a persistence boundary that turns a `COMPLETED` `WorkflowRunResult`
into a durable, reviewable `ContentDraft` row.

**Files involved**: `schemas/content_draft.py` (new), `services/content_draft_service.py` (new).

**Dependencies**: none on Milestones 1–2's Capability/prompt content — this milestone only needs
`WorkflowRunResult`'s shape (`schemas/workflow.py`, frozen since Phase 5) and `ContentDraft`'s model
(frozen since before Phase 10). It could technically be built in parallel with Milestones 1–2; it is
sequenced after them here only because Milestone 4 needs all three.

**Plan, `schemas/content_draft.py`** (mirrors `schemas/editorial_task.py:26-42`'s `EditorialTaskRead`
pattern exactly — confirmed by direct re-read, per Contract §7.1's explicit MINOR-1 correction):

```python
"""Pydantic read contract for ContentDraft (Phase 10)."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from database.models.content_draft import ContentType


class ContentDraftRead(BaseModel):
    """Returned by ContentDraftService.create_from_result() - never a raw ORM object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    task_id: UUID
    type: ContentType
    title: str | None
    body: str | None
    hashtags: list[str] | None
    version: int
    status: str | None
    created_at: datetime
    updated_at: datetime
```

`hashtags: list[str] | None` (not `dict`) — matches `CopywritingCapability`'s frozen output schema
(`hashtags: type: array`, Contract §5) even though the underlying column is `JSON` (which stores a
Python list without translation, confirmed against `database/models/content_draft.py:40`); no type
mismatch.

**Plan, `services/content_draft_service.py`** (class-based, per Contract §7.1, mirroring
`services/budget_guard.py:46-107`'s `RedisBudgetGuard` constructor-injection shape):

```python
"""ContentDraftService: the only component authorized to create a ContentDraft row (Phase 10,
docs/phase10_production_content_pipeline_architecture_contract.md §7/§7.1)."""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft import ContentDraft, ContentType
from schemas.content_draft import ContentDraftRead
from schemas.workflow import WorkflowRunResult


class ContentDraftService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_from_result(self, task_id: UUID, result: WorkflowRunResult) -> ContentDraftRead:
        copywriting_output = result.step_results_by_name()["copywriting"]  # or equivalent lookup
        draft = ContentDraft(
            task_id=task_id,
            type=ContentType.POST,
            title=copywriting_output["title"],
            body=copywriting_output["body"],
            hashtags=copywriting_output["hashtags"],
            version=1,
            status="draft",
        )
        self._session.add(draft)
        await self._session.commit()
        await self._session.refresh(draft)
        return _to_read_schema(draft)
```

(`step_results_by_name()`/exact lookup helper: `WorkflowRunResult.step_results` is a
`list[WorkflowStepResult]`, per `schemas/workflow.py`; the caller must locate the entry with
`step_name == "copywriting"` and read its `.result` dict — the exact lookup expression is an
implementation detail for the implementer to write against the real `WorkflowStepResult` shape,
not frozen by the Contract, which only fixes *which* three keys are copied verbatim and that no
reformatting occurs.) `_to_read_schema()` mirrors `services/workflow_service.py:109-121`'s identical
helper shape.

- **Session ownership**: constructor-injected, the same `AsyncSession` the caller already used for
  `WorkflowRunner.run()` — never a new session, never a new connection (Contract §7.1).
- **Commit boundary**: exactly one `session.add()` + one `await session.commit()` — a separate
  transaction from `WorkflowRunner.run()`'s own already-closed final commit
  (`workflows/runner.py:207`).
- **Failure semantics**: no `try/except` around the commit — a failure propagates uncaught to the
  caller (Milestone 4's CLI script), which MUST NOT swallow it (Contract §7.1).
- Capabilities and `CapabilityExecutor` never import this file, and this file never appears under
  `capabilities/` — the mechanical import check in Contract §12's "ContentDraft tests" proves this
  in the test phase, not here.

**Completion criteria**: `ContentDraftService(session).create_from_result(task_id, result)` given a
`COMPLETED` `WorkflowRunResult` produces exactly one `ContentDraft` row with `type=POST`, `version=1`,
`status="draft"`, and `title`/`body`/`hashtags` copied verbatim from `step_results["copywriting"]`.

**Verification required**: Contract §12's "ContentDraft tests" list, assigned to this milestone
(§8 below) — including the mandatory independent-connection durability test and the session-reuse
proof.

---

## 6. Milestone 4 — Manual CLI Trigger

**Objective**: the one component that actually invokes the full chain end-to-end and makes Phase 10
observable in a real environment.

**Files involved**: `scripts/run_content_generation.py` (new).

**Dependencies**: Milestones 1, 2, and 3 all complete — this script imports
`capabilities.registry.build_registry` (indirectly, via `assemble_ai_integration_layer`),
`workflows.definitions.content_generation` (indirectly, via the sealed `WorkflowRegistry`),
`services.content_draft_service.ContentDraftService`, and `schemas.content_draft.ContentDraftRead`
(indirectly, via `ContentDraftService`'s return type).

**Important correction to naive `scripts/run_triage.py` mirroring** (per
`docs/phase10_final_architecture_reaudit.md`'s MINOR-1 finding, independently re-confirmed this
session): `scripts/run_triage.py` (`scripts/run_triage.py:1-25`) is a ~20-line wrapper around
exactly one `services.triage_orchestrator.run_triage_cycle()` call — that orchestrator's own module
docstring states it has "no `LLMGateway`, no Capability layer, no provider SDK"
(`services/triage_orchestrator.py:1-13`). `scripts/run_content_generation.py` cannot be that thin:
it must assemble the real AI integration layer, something no production code path in this
repository has done before. The good news, independently confirmed: every piece this needs already
exists, unmodified, and a proven test-only pattern already models the exact assembly
(`tests/test_capability_boot_wiring_e2e.py:55-68`, `tests/test_phase9_research_intelligence_
integration.py:111-122` both construct `FilePromptRepository(Path(__file__).resolve().parent.parent
/ "prompts")` then call `assemble_ai_integration_layer(settings, prompt_repository)`).

**Plan, execution path**:

```python
"""Entry point for running one CONTENT_GENERATION cycle for a given event.

Launch with:
    python -m scripts.run_content_generation <event_id>

Unlike scripts/run_triage.py, this script is this repository's first production caller of
assemble_ai_integration_layer() - it assembles the real AI integration layer (LLMGateway,
CapabilityRegistry) itself, mirroring the pattern already proven in
tests/test_capability_boot_wiring_e2e.py and tests/test_phase9_research_intelligence_integration.py.
No scheduler, cron, or automatic-execution path - a human or an external process invokes this
manually (Contract §9).
"""
import asyncio
import logging
import sys
from pathlib import Path
from uuid import UUID

from core.config import settings
from core.logging import setup_logging
from database.models.editorial_task import TaskPriority, TaskStatus
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.prompts.file_repository import FilePromptRepository
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services import workflow_service
from services.content_draft_service import ContentDraftService
from capabilities.executor import CapabilityExecutor
from workflows.runner import WorkflowRunner

logger = logging.getLogger(__name__)

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


async def run_content_generation_for_event(event_id: UUID) -> None:
    prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
    ai_layer = assemble_ai_integration_layer(settings, prompt_repository)

    async with async_session_factory() as session:
        task = await workflow_service.create_task(
            session,
            EditorialTaskCreate(
                event_id=event_id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B
            ),
        )
        executor = CapabilityExecutor(session, task.id, ai_layer.capability_registry)
        runner = WorkflowRunner(executor)
        result = await runner.run(session, task.id)

        if result.status != "COMPLETED":
            logger.error("content_generation_task_failed", extra={"task_id": str(task.id)})
            return

        try:
            draft = await ContentDraftService(session).create_from_result(task.id, result)
        except Exception:
            logger.exception(
                "content_generation_completed_but_draft_persistence_failed",
                extra={"task_id": str(task.id)},
            )
            return

        logger.info(
            "content_generation_succeeded", extra={"task_id": str(task.id), "draft_id": str(draft.id)}
        )


async def main() -> None:
    setup_logging()
    event_id = UUID(sys.argv[1])
    await run_content_generation_for_event(event_id)


if __name__ == "__main__":
    asyncio.run(main())
```

(`TaskPriority.B` as a placeholder default priority — the Contract does not fix which priority the
CLI trigger uses, since `required_input=["event_id"]` is the only frozen input; an implementer may
expose it as a second CLI argument instead. Not a frozen detail.)

**Inputs**: one `event_id` (`UUID`), supplied as a CLI argument — the only `required_input` the
`CONTENT_GENERATION` `WorkflowDefinition` declares (`workflows/definitions/content_generation.py:29`,
unchanged by Milestone 2).

**Outputs / the three-outcome distinction** (Contract §9, binding, restated as an implementation
requirement, not re-decided here):
1. **Full success**: `WorkflowRunResult.status == "COMPLETED"` and `ContentDraftService.
   create_from_result()` returns — logged distinctly (e.g. `content_generation_succeeded`), draft
   id included.
2. **Task `FAILED`**: `WorkflowRunResult.status == "FAILED"` — `ContentDraftService` is never
   invoked; logged distinctly (e.g. `content_generation_task_failed`).
3. **Task `COMPLETED` but `ContentDraftService` raises**: the disclosed, accepted gap (Contract
   §7.1) — logged distinctly and loudly (e.g. `content_generation_completed_but_draft_persistence_
   failed`, at `ERROR`/`exception` level, including `task_id` so the direct query in Contract
   §7.1's discoverability clarification can find it later), never silently swallowed.

**Failure handling**: the script itself does not need its own top-level `try/except` — an
unhandled exception from `assemble_ai_integration_layer()` (e.g. misconfigured `enabled_providers`),
`workflow_service.create_task()` (e.g. `DuplicateActiveTaskError`), or `runner.run()` (e.g.
`TaskAlreadyRunningError`) is allowed to propagate and crash the script loudly — consistent with
`scripts/run_triage.py`'s own precedent of no top-level exception handling, and with this
codebase's "fail loud, not silently degrade" boot discipline (`integrations/llm_gateway/boot.py`'s
own docstring, `RegistryConsistencyError`/`MissingRedisFailurePolicyError` precedent). Only the
Contract §7.1-disclosed `ContentDraftService` failure gets an explicit `try/except`, because that
one case must be *distinguished* from the other two outcomes, not merely allowed to crash.

**Completion criteria**: running the script against a real, provisioned Postgres/Redis and a real
`event_id` with `enabled_providers=["openai"]` configured produces either a persisted `ContentDraft`
row (outcome 1) or one of the two distinctly-logged non-success outcomes (2/3) — never a silent
no-op, never an unhandled crash that obscures which of the three outcomes occurred.

**Verification required**: Contract §12's "CLI tests" list, assigned to this milestone (§8 below) —
exercised against the underlying `run_content_generation_for_event()` function with fakes, not the
thin script wrapper, mirroring how `triage_orchestrator.run_triage_cycle()` is tested today.

---

## 7. Per-File Summary

| File | Purpose | Reason for modification | Dependencies | Risk | Verification required |
|---|---|---|---|---|---|
| `capabilities/copywriting_capability.py` (new) | The new Capability that drafts `title`/`body`/`hashtags` from Research+Intelligence output. | Phase 10's core deliverable (Contract §1, §5). | `capabilities/gateway_call.py`, `integrations/llm_gateway/protocol.py`, `integrations/prompts/protocol.py`, `schemas/capability*.py` — all frozen, unmodified. | **Low** — structurally identical to 3 already-proven Capabilities; no new pattern. | Contract §12 Capability tests. |
| `prompts/copywriting/v1.yaml` (new) | Copywriting's prompt content and output schema. | Phase 6 §8's prompt-ownership rule (no embedded prompt strings in Capability code). | `integrations/prompts/file_repository.py` (read-only consumer, unmodified). | **Low** — static content, auto-discovered. | `output_schema.required == expected_output_keys` (Contract §6); loads without `PromptContentError`. |
| `capabilities/registry.py` (edit) | Registers `CopywritingCapability` so it is resolvable at runtime. | Without this, `resolve("copywriting")` always raises `UnknownCapabilityError` (Contract §3, corrects the Final Re-Audit's CRITICAL-1). | `capabilities/copywriting_capability.py` must exist first. | **Low** — exactly 2 lines, mirrors 4 existing calls. | Contract §12 Registry resolution tests. |
| `workflows/definitions/content_generation.py` (edit) | Expands the step chain to 4 steps and the workflow timeout to 120s. | Makes `CONTENT_GENERATION` reach `COMPLETED` for real (Contract §3, §1). | None beyond `schemas/workflow.py` (frozen). | **Medium** — a Phase 5 workflow *definition* file edit; Contract §14 names this explicitly as a real, narrow amendment, not pre-approved by analogy. | Contract §12 Workflow tests (full-chain completion + `step_results` propagation proof). |
| `capabilities/quality_capability.py` (edit) | Makes `QualityCapability` actually review the generated draft. | Without this, `quality` runs last but never reads Copywriting's output (Contract §5.1, corrects the Contract Audit's MAJOR-1). | `prompts/quality/v2.yaml` must exist for `PROMPT_VERSION="2"` to resolve. | **Low-Medium** — touches existing, previously-tested code; scope is explicitly one method + one constant, mechanically checkable against the "byte-for-byte unchanged" list. | Contract §12 QualityCapability adaptation tests (both non-empty and empty `step_results["copywriting"]` cases). |
| `prompts/quality/v2.yaml` (new) | The amended Quality prompt version. | Phase 6 §8's prompt-immutability rule — `v1.yaml` cannot be mutated, so a new version is required. | `integrations/prompts/file_repository.py` (read-only consumer). | **Low** — `output_schema` identical to `v1`, only prose text changes. | `output_schema` asserted identical to `v1`'s (Contract §12); `v1.yaml` independently still resolvable. |
| `schemas/content_draft.py` (new) | `ContentDraftRead` DTO — the only representation of a `ContentDraft` that crosses a service boundary. | Contract §7.1, corrects the Final Re-Audit's MINOR-1 (explicit authorization). | `database/models/content_draft.py` (frozen, read-only `ContentType` import). | **Low** — pure DTO, mirrors an existing pattern exactly. | Type-checks against `ContentDraft`'s real columns; no migration implied. |
| `services/content_draft_service.py` (new) | The only component authorized to create a `ContentDraft` row. | Closes Decision Resolution §8's "who writes it" open question (Contract §7). | `schemas/content_draft.py` (must exist first), `schemas/workflow.py` (frozen). | **Medium** — owns a real commit boundary and Contract §7.1's disclosed failure-mode; the mechanical "no Capability creates a draft" test exists specifically to catch drift here. | Contract §12 ContentDraft tests, including the mandatory independent-connection durability test. |
| `scripts/run_content_generation.py` (new) | The manual CLI trigger — the only thing that invokes the full chain. | Closes Decision Resolution's "inert code" risk; Contract §9. Corrects the Final Re-Audit's own re-audit CRITICAL-1 (§3 now authorizes this file). | All 8 files above, plus `integrations/llm_gateway/boot.py`'s `assemble_ai_integration_layer()` (frozen, unmodified, first production caller — Risk R1, §8 below). | **Medium** — first production assembly of the AI integration layer; every component it calls is already proven, but this exact composition has only run inside tests until now. | Contract §12 CLI tests, exercised against the underlying function, not the script wrapper. |

---

## 8. Implementation Order

Every step depends only on previously completed steps. Steps within the same numbered group have no
dependency on each other and may proceed in any order (or in parallel, if more than one implementer
is available) — later groups strictly require all of an earlier group to be complete.

1. **`capabilities/copywriting_capability.py` + `prompts/copywriting/v1.yaml`** (Milestone 1) — no
   dependency on any other Phase 10 file; buildable and unit-testable against `FakeLLMGateway`/
   `FakePromptRepository` in isolation.
2. **`schemas/content_draft.py`** (Milestone 3, first half) — no dependency on step 1; depends only
   on the frozen `ContentDraft` model. Listed here (rather than after step 1) because it has no
   dependency on Copywriting's implementation at all and can proceed in parallel with step 1.
3. **`capabilities/registry.py`** (Milestone 2) — depends on step 1 (imports
   `COPYWRITING_CAPABILITY_DEFINITION`/`CopywritingCapability`).
4. **`workflows/definitions/content_generation.py`** (Milestone 2) — no code dependency on step 3,
   but grouped with it since both are required before any real end-to-end workflow test can run;
   depends only on frozen `schemas/workflow.py`.
5. **`capabilities/quality_capability.py` + `prompts/quality/v2.yaml`** (Milestone 2) — depends on
   Contract §5's frozen Copywriting output schema (already fixed by the Contract, not by step 1's
   code) for what keys to format; does not import `copywriting_capability.py` itself, so it has no
   hard code dependency on step 1 completing, but is sequenced after steps 3–4 so the full chain is
   registrable and runnable for its own regression tests (proving `v1.yaml` remains resolvable
   alongside the new chain).
6. **`services/content_draft_service.py`** (Milestone 3, second half) — depends on step 2
   (`schemas/content_draft.py` must exist for `ContentDraftRead`).
7. **`scripts/run_content_generation.py`** (Milestone 4) — depends on steps 1, 3, 4, 5, and 6 all
   being complete: it is the only file that imports across every other authorized file's public
   surface.

This groups into the same four Contract-facing milestones (M1 → M2 → M3 → M4 are strictly
sequential at the milestone level, matching Decision Resolution §13's own dependency table), while
recording that `schemas/content_draft.py` (step 2) has no real dependency on Milestone 1 and could
be built first, in parallel, if convenient.

---

## 9. Risks

| # | Risk | Cause | Impact | Mitigation |
|---|---|---|---|---|
| R1 | `scripts/run_content_generation.py` is the first production code to call `assemble_ai_integration_layer()`/construct a real `FilePromptRepository`. | No production call site has ever existed for this function before Phase 10 (confirmed: every call site found is a test file). | If the composition has a subtle issue only exercised by test fakes today, it surfaces first in this script, not earlier. | Every component the composition uses (`assemble_ai_integration_layer()`, `FilePromptRepository`, `build_registry()`, `CapabilityExecutor`, `WorkflowRunner`) is already-existing, unmodified, individually-tested code; `tests/test_capability_boot_wiring_e2e.py` and `tests/test_phase9_research_intelligence_integration.py` already prove the exact same composition end-to-end (with a `FakeProviderAdapter` instead of the real OpenAI adapter) — Milestone 4's CLI tests (§12) exercise the identical composition against fakes before the M0 live smoke test (Contract §8) is ever run. |
| R2 | Workflow-definition expansion risk (Contract §14, restated). | Editing `content_generation.py`'s step list is a change to a Phase 5 workflow *definition* file. | Could be mistaken for a precedent that any future phase may edit a workflow definition without explicit Contract authorization. | The Contract explicitly, narrowly authorizes exactly this one file's `steps`/`timeout_seconds` fields (§3) — this plan does not extend that authorization, and no future phase should assume it pre-approved by analogy (Contract §14's own explicit caveat). |
| R3 | Timeout budget reused, not validated (Contract §3, §14). | `120`s for the 4-step workflow is `NEWS_ANALYSIS`'s already-existing value, not empirically proven sufficient for four live OpenAI calls — `NEWS_ANALYSIS` itself has never completed in this codebase. | `CONTENT_GENERATION` could hit `WorkflowTimeoutError` in production even though every step behaves correctly. | Contract §8's M0 live smoke test surfaces this before real production traffic; if `120`s proves insufficient, adjusting the single integer is a configuration change, not a reason to reopen the Contract (Contract §3, §14). |
| R4 | API cost exposure. | Real, billed OpenAI calls become possible once `enabled_providers` includes `"openai"` in production (Contract §8). | Misconfiguration (e.g. no `max_daily_ai_cost` ceiling set) could allow unexpectedly large spend. | `BudgetGuard`/`CostTracker` already exist and are wired into `assemble_ai_integration_layer()` (`boot.py:185-186`) — Phase 10 adds no new cost-control mechanism and verifies these are active in the target environment as part of Milestone 0/M0, per Contract §8. |
| R5 | `ContentDraft` ownership discipline drift. | A future change could let a Capability or `CapabilityExecutor` write a `ContentDraft` row directly, bypassing `ContentDraftService`. | Would violate Contract §7's "only `ContentDraftService` creates a `ContentDraft` row" rule, undetected until manual review. | Contract §12's mechanical "no file under `capabilities/` imports `database.models.content_draft.ContentDraft`" test (assigned to Milestone 3, §10 below) catches this class of drift at test time, not merely by code review. |
| R6 | `COMPLETED` task with no `ContentDraft` is a reachable, disclosed gap (Contract §7.1). | If `ContentDraftService.create_from_result()`'s commit fails after `WorkflowRunner.run()` already committed `TaskStatus.COMPLETED`, that completion cannot be retroactively rolled back (two separate, sequential transactions). | An `EditorialTask` can end up `COMPLETED` with no corresponding `ContentDraft` row — a real, accepted gap, not a bug to "fix" in Phase 10. | Milestone 4's CLI script MUST distinguish and loudly log this exact outcome (§6 above, Contract §9); the gap remains discoverable after the fact via the direct query Contract §7.1 describes against existing, accurately-described columns. Recovery (re-run, repair script, alert) is explicitly out of scope for Phase 10 (Contract §13). |
| R7 | Duplicate Research/Intelligence Gateway calls (Contract §4, §14). | A `NewsEvent` with both an active `NEWS_ANALYSIS` task and an active `CONTENT_GENERATION` task runs Research/Intelligence independently, twice, for the same event — `_find_active_task()` (`services/workflow_service.py:89-106`) enforces uniqueness per `(event_id, workflow_type)`, not per event alone. | Real, duplicated API cost and possible inconsistency (two independent Research/Intelligence runs for the same event could disagree). | Explicitly disclosed, not resolved, by the Contract (§4, §14) — out of scope for Phase 10 to de-duplicate; this plan does not introduce a fix, matching the Contract's own scope boundary. Operationally, avoid triggering `CONTENT_GENERATION` for an event that already has an active `NEWS_ANALYSIS` task, until a future phase addresses this. |

---

## 10. Verification Plan

Grounded entirely in Contract §12's own testing requirements (no new test obligation is invented
here — this section only sequences and assigns §12's existing list to milestones).

### Milestone 1 — `CopywritingCapability`

- **Unit verification**: Contract §12 "Capability tests" — happy path against
  `FakeLLMGateway`/`FakePromptRepository` asserting `structured_output` matches
  `title`/`body`/`hashtags` exactly; `PromptRepository.resolve()` usage; `call_generate()` usage;
  floor-validation enforcement (`ValidationCapabilityError` on malformed response);
  `GatewayError`→`CapabilityError` translation via `FakeLLMGateway.generate_error()`; AST-based
  non-coupling check (`CopywritingCapability` MUST NOT import `research_capability`/
  `intelligence_capability`).
- **Integration verification**: none required at this milestone in isolation — deferred to
  Milestone 2's Workflow tests, which prove `CopywritingCapability` inside the real chain.
- **Manual verification**: none required at this milestone.
- **Completion evidence**: all Milestone 1 unit tests pass; the AST-based import check passes.

### Milestone 2 — Workflow Integration

- **Unit verification**: Contract §12 "QualityCapability adaptation tests" (built request contains
  Copywriting's content when `step_results["copywriting"]` is non-empty; still succeeds and still
  includes `news_event` fields when it is empty; `PROMPT_VERSION` resolves `"2"`; `v1.yaml` remains
  independently resolvable; non-coupling check extended; `expected_output_keys`/`output_schema`
  identical to `v1`'s) and "Registry resolution tests" (`resolve("copywriting")` succeeds directly;
  `resolve()` on an unregistered name still raises `UnknownCapabilityError`).
- **Integration verification**: Contract §12 "Workflow tests" — `research → intelligence →
  copywriting → quality` executes in that exact order through the real, unmodified
  `WorkflowRunner`/`CapabilityExecutor`/`CapabilityRegistry`, reaching `TaskStatus.COMPLETED`;
  `step_results` propagation proven by inspecting `CopywritingCapability`'s and
  `QualityCapability`'s actually-built request content, not merely asserting `SUCCESS`.
- **Manual verification**: none required at this milestone (the M0 live-API smoke test, Contract §8,
  is independent of this milestone's own correctness and may run before or after it).
- **Completion evidence**: all Milestone 2 unit and integration tests pass; the full four-step chain
  reaches `TaskStatus.COMPLETED` against fakes.

### Milestone 3 — `ContentDraft`

- **Unit verification**: Contract §12 "ContentDraft tests" — a row is created only after a
  `COMPLETED` result, never on `FAILED`, never mid-run; the mechanical "no file under
  `capabilities/` imports `ContentDraft`" check; the session-reuse proof (a session already used for
  a prior committed `WorkflowRunner.run()` call still succeeds for a subsequent
  `ContentDraftService(session).create_from_result(...)` call).
- **Integration verification**: the mandatory durability test — a `ContentDraft` row is proven
  durable to a genuinely independent database connection, reusing the exact
  `independent_session_factory()`/`real_committed_event()`-style technique already established in
  `tests/test_triage_orchestrator_claims.py` and `tests/test_workflow_runner_per_step_persistence.py`
  — the standard `db_session` fixture MUST NOT be relied upon for this one test.
- **Manual verification**: none required at this milestone.
- **Completion evidence**: all Milestone 3 unit and integration tests pass, including the
  independent-connection durability test.

### Milestone 4 — Manual CLI

- **Unit verification**: Contract §12 "CLI tests" — the underlying `run_content_generation_for_
  event()` function (not the thin script wrapper), invoked directly against fakes, creates, runs,
  and persists a `ContentDraft` successfully; the three-outcome distinction (clean success / task
  `FAILED` / task `COMPLETED` with `ContentDraftService` failure) is exercised and asserted
  distinctly, not collapsed into one pass/fail check.
- **Integration verification**: the full chain (Milestone 2's integration test technique) exercised
  once more end-to-end through the actual script's underlying function, proving the real
  `assemble_ai_integration_layer()`/`FilePromptRepository`/`build_registry()` composition (not just
  a hand-assembled `CapabilityRegistry` in a test helper) reaches `COMPLETED` and persists a draft.
- **Manual verification**: Contract §8's M0 smoke test — exactly one manual, out-of-band, live call
  proving `RoutingGateway.generate()` succeeds against the real OpenAI API; **MUST NOT** be added to
  the automated suite (Phase 7 §15.5's no-real-network-call discipline, unchanged). A full manual run
  of `scripts/run_content_generation.py` against a real, provisioned environment and a real
  `event_id`, confirming a `ContentDraft` row is actually persisted and visible via a direct
  database query.
- **Completion evidence**: all Milestone 4 unit and integration tests pass; the M0 live smoke test
  succeeds; one full manual CLI run against a real environment produces an observable `ContentDraft`
  row.

---

## 11. Definition of Done

Phase 10 is **COMPLETE** only when every one of the following holds, derived directly from the
Contract (no criterion invented beyond it):

1. `CONTENT_GENERATION` reaches `TaskStatus.COMPLETED` for real, via the four-step
   `research → intelligence → copywriting → quality` chain, through the real, unmodified
   `WorkflowRunner`/`CapabilityExecutor`/`CapabilityRegistry` (Contract §1, §3, §12).
2. A `ContentDraft` row is durably persisted from a `COMPLETED` run's `step_results["copywriting"]`,
   proven via a genuinely independent database connection, not merely visible within the producing
   session (Contract §7.1, §12).
3. Every test named in Contract §12 exists and passes: Capability tests, QualityCapability
   adaptation tests, Registry resolution tests, Workflow tests, ContentDraft tests (including the
   mandatory durability test), and CLI tests.
4. Exactly the 9 files in this plan's §1 were touched — no unauthorized production file was created
   or edited (verifiable via `git status`/`git diff --stat` against the pre-implementation baseline).
5. `capabilities/quality_capability.py`'s amendment is confirmed byte-for-byte scoped to
   `_build_request()` and `PROMPT_VERSION` only — its `__init__`, `execute()` control flow,
   `_floor_validate()`, `CapabilityResult` construction, and `QUALITY_CAPABILITY_DEFINITION` are
   unchanged (Contract §5.1, §15 item 9).
6. `prompts/quality/v1.yaml` remains on disk, unmodified, and independently resolvable via an
   explicit `resolve("quality", "1")` call — proving it was superseded as the default, not deleted or
   mutated (Contract §5.1, §12).
7. The mechanical non-coupling checks pass: `CopywritingCapability` never imports
   `research_capability`/`intelligence_capability`; `QualityCapability` never imports
   `copywriting_capability`; no file under `capabilities/` imports
   `database.models.content_draft.ContentDraft` (Contract §5, §5.1, §7, §12).
8. No migration was created; `ContentDraft`'s existing columns and `ContentType` enum are used
   exactly as they exist today (Contract §7).
9. Contract §8's M0 live smoke test succeeds exactly once, manually, out-of-band — proving
   `RoutingGateway.generate()` works against the real OpenAI API — and is never added to the
   automated test suite (Contract §8).
10. A full manual run of `scripts/run_content_generation.py` against a real, provisioned environment
    produces an observable `ContentDraft` row for a real `event_id`, and the three-outcome logging
    distinction (success / task `FAILED` / task `COMPLETED` with `ContentDraftService` failure) is
    confirmed to actually fire correctly for at least the success case (Contract §9).
11. No file outside this plan's authorized 9-file list was created, edited, or deleted; `bot/`,
    `integrations/telegram/`, `workflows/runner.py`, `capabilities/executor.py`,
    `database/models/editorial_task.py`, and `workflows/registry.py` remain byte-for-byte unchanged
    (Contract §3, §10, §15).

---

## 12. Out of Scope (re-confirmed, not re-decided)

Phase 10 does **NOT** include any of the following — each already excluded by the Contract, restated
here only so this plan cannot be read as silently reopening them:

- **Telegram publishing**, in any form — Contract §2 ("OUT OF SCOPE, binding"), §10 (`bot/` untouched,
  no `integrations/telegram/` directory), §13 item 1.
- **Meme generation**, both opportunity-detection and image-rendering halves — Contract §2, §11 (full
  reasoning: `LLMGateway.generate()` has no image-output method today), §13 item 2.
- **Image generation**, of any kind — Contract §2, §11, §13 item 3.
- **A scheduler or any automatic-execution mechanism** — Contract §2, §9 ("explicitly forbidden: no
  scheduler, cron, or timer of any kind"), §13 item 4.
- **Analytics**, of any kind (engagement, performance, or otherwise) — Contract §13 item 5.
- **Workflow-engine redesign** — Contract §2 ("Any `WorkflowRunner`/`WorkflowExecutor`/
  `CapabilityExecutor` redesign"), §13 item 8; only one workflow *definition* file's step list and
  timeout are edited, an explicitly-authorized, narrow amendment (§3), not an engine change.
- **`LLMGateway` redesign** — Contract §8 ("what Phase 10 does NOT change": Protocol shape, routing
  logic, `FallbackPolicy`, any provider adapter, `enabled_providers` beyond adding `"openai"`).
- **Database migration** — Contract §7 ("no migration... `ContentDraft`'s existing columns and
  `ContentType` enum are used exactly as they exist today"), §13 item 10 (only `"draft"` status is
  ever written; no review/approval/publish transitions).
- **A second LLM provider** — Contract §2, §8, §13 item 7.
- **Crash recovery or a resume mechanism** — Contract §2, §13 item 9 (Phase 9.5's own disclosed
  limitation, unchanged).

---

PHASE 10 IMPLEMENTATION PLAN COMPLETE — READY FOR PLANNING AUDIT
