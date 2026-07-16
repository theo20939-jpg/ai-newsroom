# Phase 6 Planning Report — Capability Framework

No code, no migrations, no changes to Phase 1–5. Analysis only.

Sources read directly for this report: `CLAUDE.md`, `docs/02_Project_Rules.md`, `docs/03_System_Architecture.md`, `docs/06_Functional_Specification.md`, `docs/07_AI_Architecture_Document.md`, `docs/10_Claude_Code_Development_Specification.md`, `docs/10_1_MVP_Constraints_Corrections.md`, `docs/11_Prompt_Engineering_Package.md`, `docs/13_Testing_Strategy.md`, `docs/13_1_Final_Corrections_Before_Development.md`, plus the current `workflows/`, `schemas/`, `database/models/ai_execution.py`, `database/models/editorial_task.py`, `database/models/content_draft.py`, `capabilities/` (empty), `integrations/` (no `ai/` subdirectory exists), `prompts/` (does not exist), and `tests/` (no capability/AI/gateway/prompt tests exist yet).

---

## 1. Confirmed requirements (exact document references)

| # | Requirement | Source |
|---|---|---|
| 1 | System is Capability-based, not one large AI agent; each Capability has one function | docs/06 §3.2, docs/07 §2 |
| 2 | "Capability" is the only correct term; "Agent" must not be used | **docs/13_1 §6** (already established in Phase 5) |
| 3 | Seven capabilities exist in the domain model today: Research, Intelligence, Trend, Scoring, Copywriting, Creative, Quality | **`database/models/ai_execution.py`, `AICapability` enum** — already migrated |
| 4 | All AI calls go through a single `LLM Gateway`; no direct provider SDK calls in business logic | docs/07 §7/§9, docs/10 Rule 3, docs/13_1 §7 |
| 5 | Capability responses must be structured JSON, never free text | docs/07 §11, docs/11 §2 Rule 5 |
| 6 | Every Capability response includes a confidence score | docs/11 §2 Rule 3 |
| 7 | Capabilities never call each other directly; they communicate only by reading/writing persisted state (never `A→B→A→B`) | **docs/11 §11** |
| 8 | An agent-round ceiling exists: `MAX_AGENT_ROUNDS = 3` | CLAUDE.md, docs/10_1 §9, docs/10 §8, **docs/11 §12** (fourth independent confirmation of "3") |
| 9 | Prompts are not stored in Python; they are versioned, testable artifacts | docs/07 §10/§23, docs/10 §10, docs/11 §13 |
| 10 | Cost is tracked per call (model, input/output tokens, cost, time) and enforced against daily/monthly limits | docs/10_1 §12, docs/13_1 §9, docs/13 §6 |
| 11 | A Capability does not compute cost itself | **implied by docs/13_1 §9** (`services/cost_tracker.py` owns cost) and reinforced by this task's own instructions |
| 12 | `WorkflowStepDefinition.capability` is a bare string identifier, not a class reference | **`schemas/workflow.py`, already shipped in Phase 5** |
| 13 | `WorkflowRunner` depends only on the `StepExecutor` Protocol (`execute(step) -> dict`); it has zero knowledge of Capability implementations | **`workflows/runner.py`, already shipped in Phase 5** |
| 14 | No dynamic module discovery anywhere in this project's registries — only explicit registration | established precedent: `workflows/registry.py`, `services/adapter_registry.py` |
| 15 | Capability testing is its own dedicated test level, separate from unit/integration/E2E | docs/13 §3 "Level 3: AI Quality Testing", docs/07 §26.2 |
| 16 | Tests must never run against the production database; a separate test database is required | docs/13 §9 (already the working convention since Phase 5's `tests/conftest.py`) |

---

## 2. Document conflicts found

### Conflict A — LLM Gateway method signature disagrees across four sources
- docs/07 §7 "AI Provider Interface": `generate() analyze() summarize() embed()`
- docs/13_1 §7 "LLM Gateway Correction": `generate() analyze() summarize()` (no `embed`)
- docs/10 §6 "PHASE 6": `generate() analyze() summarize() embed()`
- **This task's own instructions, item 12**: `LLMGateway.generate()`, `.embed()`, `.classify()`, `.moderate()` — a different set again (`classify`/`moderate` appear nowhere in any document; `analyze`/`summarize` are absent here)

**Impact**: this determines the entire `LLMGateway` contract surface Capabilities are allowed to call. **Recommended resolution**: treat `analyze()`/`summarize()` (docs-only) as *use cases* built on top of `generate()` (a specific prompt + output schema), not as separate Gateway methods — a Capability that wants "analysis" calls `generate()` with an analysis prompt. Adopt the four methods named directly in this task's instructions (`generate`, `embed`, `classify`, `moderate`) as the Phase 6 contract surface, since it is the most recent, most explicit instruction for this exact deliverable. **Approval required** — this is a real four-way disagreement, not resolved by document priority alone (the current task's instructions aren't a "document" in the priority chain at all, so this is a judgment call, flagged explicitly in §20).

### Conflict B — "Budget Manager" vs. "Cost Tracker"
- docs/06 §6.6 and docs/07 §19 describe a **Budget Manager** sitting between `LLM Gateway` and the AI Provider, deciding model/token/retry budgets per priority
- docs/13_1 §9 names a single module, **`services/cost_tracker.py`**, responsible for counting tokens, counting cost, storing spend, *and* enforcing limits

**Recommended resolution**: `docs/13_1` outranks `docs/06`/`docs/07` per the priority stance established in Phase 5 (§2 of `docs/phase5_workflow_engine_planning.md`). Treat **Cost Tracker** (`services/cost_tracker.py`) as the single authoritative module for both recording *and* limit enforcement; "Budget Manager" is not a separate component. **Approval required**: No — same priority reasoning already accepted for Phase 5.

### Conflict C — Terminology: docs/11 uses "Agent" throughout
docs/11 (Prompt Engineering Package) calls every capability an "Agent" (Research Agent, Intelligence Agent, etc.) end to end — directly contradicting docs/13_1 §6's explicit correction. **Recommended resolution**: same as Phase 5 — docs/13_1 wins; docs/11's *prompt content* (system role, rules, output schemas) remains valid and directly useful, only its "Agent" naming is superseded by "Capability". **Approval required**: No — already-settled precedent.

### Conflict D — Step granularity: docs/11's five agents vs. docs/13_1's four-step slice vs. Phase 5's shipped step names
- docs/11 defines **five** distinct capabilities feeding into scoring: Research, Intelligence, **Trend**, **Engagement Analysis**, Scoring (§3–§7) — Trend and Engagement are separate, each with their own prompt and output schema
- docs/13_1 §11 (11-step pipeline, higher priority) lists only **Research → Intelligence → Engagement Analysis → Scoring** for this slice — no separate Trend step
- **Phase 5's already-shipped `workflows/definitions/news_analysis.py`** (built to match docs/13_1's slice) has exactly these four steps, with `capability="engagement"` for the third one

**Impact**: `AICapability` (the already-migrated DB enum) has `TREND` but **no `ENGAGEMENT` value at all**. Phase 5's shipped step name `"engagement"` therefore has no matching `AICapability` member to persist against once a real Capability tries to write an `AIExecution` row for it. This does not block Phase 6 (a framework produces no real executions to persist), but it is a real, concrete gap that must be resolved before any future phase implements a real Engagement-related Capability. See §15 and §20 (Open Question 1) for the three resolution options and my recommendation.

### Conflict E — Phase numbering: this task vs. docs/10
docs/10 §6 splits this exact work across two phases: **"PHASE 6: AI Infrastructure"** (LLM Gateway only) and **"PHASE 7: First AI Capability"** (a real, working Research Capability with a real model call). This task explicitly asks for the generic Capability *framework* (contract/context/result/registry/executor/errors) **plus** LLM Gateway *contracts only*, with **no real provider calls at all** — which doesn't map onto either docs/10 phase individually; it's the shared scaffolding underneath both, done once, with concrete implementations deferred. This mirrors the Phase 5 precedent (docs/10's phase label didn't match exactly either, and was treated as an evolution of the plan, not a contradiction requiring a stop). **Approval required**: No — treated as informational, matching the accepted Phase 5 precedent for phase-numbering drift.

---

## 3. Recommended conflict resolutions (summary)

| Conflict | Resolution | Needs approval |
|---|---|---|
| A — Gateway method names | Adopt `generate`/`embed`/`classify`/`moderate`; treat `analyze`/`summarize` as prompt-level use cases of `generate` | **Yes** |
| B — Budget Manager vs. Cost Tracker | Cost Tracker (`services/cost_tracker.py`) is the single authoritative module | No (precedent) |
| C — "Agent" vs. "Capability" | "Capability" wins; docs/11 prompt content still usable | No (precedent) |
| D — Missing `ENGAGEMENT` capability value | See §15/§20 — three options, recommendation given, **decision deferred to you** | **Yes** |
| E — Phase-numbering mismatch with docs/10 | Informational only, not a blocker | No (precedent) |

---

## 4. Exact Phase 6 scope

Comparing the four options against the highest-priority documentation and this task's own explicit constraints ("no real API calls," "do not design provider implementations yet"):

- **A. Capability Framework only** — covers items 1–10, 13–14 of the brief, but leaves item 11 ("Boundary between Capability Framework and the future LLM Gateway") undefined as a contract, only as a vague future dependency. Under-scopes what was asked.
- **B. LLM Gateway only** — doesn't match; the overwhelming majority of this task's 17 numbered requirements are about the Capability side, not the Gateway.
- **C. Capability Framework + provider-neutral LLM Gateway contracts, no provider implementations** — matches the brief precisely: full Capability contract/context/result/registry/executor/errors/config design, **plus** a defined (but unimplemented) `LLMGateway` Protocol that Capabilities are allowed to depend on, with zero real HTTP calls to any provider.
- **D. Something else** — no higher-priority document describes a materially different scope for "design the Capability system so it never needs to be redesigned"; docs/07 §22 (AI Runtime Architecture) and docs/11 together describe exactly the C-shaped boundary (Capability → LLM Gateway → Provider, with Capability never touching a provider directly).

**Determination: Option C.** Capability Framework, fully designed, plus LLM Gateway contracts (`generate`/`embed`/`classify`/`moderate` — see Conflict A) with no provider implementation, no prompt file content, and no real Capability implementation (Research/Intelligence/etc. remain unimplemented placeholders in this phase, exactly as `workflows/definitions/` and `DeterministicPlaceholderExecutor` were in Phase 5).

---

## 5. Capability Contract

```python
class Capability(Protocol):
    """One AI-capability module. Never calls a provider SDK directly - only
    LLMGateway. Never calls another Capability directly - communicates only
    through persisted CapabilityContext/Result data (docs/11 §11)."""

    async def execute(self, context: "CapabilityContext") -> "CapabilityResult":
        """Run this capability once and return a structured result.

        Raises RetryableCapabilityError / PermanentCapabilityError /
        ValidationCapabilityError / CapabilityTimeoutError /
        CapabilityConfigurationError - never a bare Exception.
        """
        ...
```

No provider SDK import, no `openai`/`anthropic`/`google.generativeai` import, anywhere near this Protocol or its implementations. A `Capability` is a plain object holding at most a reference to `LLMGateway` (injected, never constructed internally) and its own `CapabilityDefinition`.

---

## 6. CapabilityContext

Full proposed composition, derived from docs/07 §22.1/§22.2 (Context Manager), docs/06 §7 (per-capability inputs), and the practical need to avoid a second database round trip inside the Capability itself:

```python
class CapabilityContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Identity
    task_id: UUID
    event_id: UUID
    capability_name: str            # matches WorkflowStepDefinition.capability, e.g. "research"

    # Domain data (read-only snapshots, never ORM objects - see §11)
    news_event: NewsEventSnapshot   # title, content, url, category, published_at, source metadata
    workflow_state: WorkflowExecutionStateSnapshot  # prior completed_steps + their step_results, for chaining

    # Runtime metadata
    priority: TaskPriority          # from EditorialTask - governs model/budget routing (docs/07 §8/§24)
    attempt: int                    # which attempt of this step this is (1-based)
    iteration_count: int            # workflow-level iteration counter, read-only

    # Editorial/user settings (docs/06 §6.6 Brand Voice, docs/11 §2 Rule 4)
    language: str = "en"
    audience: str | None = None
    brand_voice: dict[str, Any] | None = None

    # Model preference (advisory only - LLM Gateway makes the final choice, docs/07 §9)
    preferred_model: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
```

`news_event`/`workflow_state` are **snapshots** (their own small Pydantic models), not the SQLAlchemy `NewsEvent`/`EditorialTask` rows — no ORM object crosses into a Capability, matching the boundary rule already used for `WorkflowService`/`WorkflowRunner` in Phase 5.

---

## 7. CapabilityResult

Not a string — a full structure, matching this task's own example plus the metrics needed for §14/§15:

```python
class CapabilityResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["SUCCESS", "FAILED"]
    structured_output: dict[str, Any] | None   # the capability's actual JSON answer
    confidence: int | None = Field(default=None, ge=0, le=100)  # docs/11 §2 Rule 3

    usage: "CapabilityUsage"                   # tokens only - see §14; no cost field, see §15
    model_used: str | None                     # which model the Gateway actually picked
    prompt_name: str
    prompt_version: str                        # see §12

    started_at: datetime
    finished_at: datetime
    duration_seconds: float

    metadata: dict[str, Any] = Field(default_factory=dict)   # free-form, capability-specific extras
    logs: list[str] = Field(default_factory=list)            # short, structured trace lines - never full payloads

    next_context: dict[str, Any] | None = None  # data explicitly meant to feed the *next* step's context (docs/11 §11: via persisted state, not a direct call)
```

`next_context` is deliberately a plain JSON dict, not another `CapabilityContext` — it becomes part of the next step's `workflow_state` snapshot once `CapabilityExecutor` persists it into `EditorialTask.workflow.step_results[i].result` (the exact same JSON-serializable field Phase 5 already writes to).

---

## 8. CapabilityDefinition and configuration

Mirrors `WorkflowDefinition`/`WorkflowStepDefinition` deliberately, for consistency with the already-approved Phase 5 pattern:

```python
class CapabilityConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    timeout_seconds: int = Field(ge=1)          # capability-internal timeout - see the 3-boundary note in §10
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_delay_seconds: float = Field(default=0, ge=0)   # logged only in this phase, same rule as WorkflowRetryPolicy
    preferred_model: str | None = None          # advisory - no provider name validation here (provider-agnostic)
    max_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    allow_stream: bool = False
    allow_tools: bool = False


class CapabilityDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str                       # matches WorkflowStepDefinition.capability, e.g. "research"
    version: int = Field(ge=1)       # integer, matching WorkflowDefinition.version's Phase-5-fix rationale
    config: CapabilityConfig
    required_context: list[str]     # e.g. ["news_event"] - documents what CapabilityContext fields must be populated
    expected_output_keys: list[str] # e.g. ["summary", "key_facts", "confidence"]
```

No `preferred_model` value is validated against a provider ("gpt-4", "claude-sonnet", etc.) — that string is opaque to the Capability Framework; only `LLMGateway` (unimplemented in this phase) would ever interpret it. This is what keeps Capability provider-agnostic per the framework's hardest rule (§16 of the brief).

---

## 9. Immutable CapabilityRegistry

Identical shape to the already-approved-and-shipped `WorkflowRegistry` (`workflows/registry.py`), including the sealing fix from the last review round:

```python
class CapabilityRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, CapabilityDefinition] = {}
        self._capabilities: dict[str, Capability] = {}
        self._sealed = False

    def register(self, definition: CapabilityDefinition, capability: Capability) -> None:
        if self._sealed:
            raise CapabilityRegistryAlreadySealedError(...)
        if definition.name in self._definitions:
            raise DuplicateCapabilityRegistrationError(...)
        self._definitions[definition.name] = definition
        self._capabilities[definition.name] = capability

    def seal(self) -> None: ...

    def resolve(self, name: str) -> tuple[CapabilityDefinition, Capability]:
        # raises UnknownCapabilityError if name not registered
        ...
```

`build_registry()` registers whatever concrete `Capability` implementations exist **at import time only**, then calls `seal()` before returning the module-level singleton — exactly the Phase 5 pattern. In this phase, no concrete `Capability` implementation exists yet (Research/Intelligence/etc. are all future work), so the real registry Phase 6 ships would be **empty but sealed** — analogous to how Phase 5 shipped `DAILY_DIGEST` as "declared but not registered."

---

## 10. CapabilityExecutor ↔ existing StepExecutor Protocol

This is the single most important integration point, and it surfaces a real constraint that must be resolved deliberately, not silently.

**The constraint**: `workflows/runner.py`'s `StepExecutor.execute(self, step: WorkflowStepDefinition) -> dict[str, Any]` receives **only** the step definition — no `task_id`, no `session`, no `WorkflowExecutionState`. A real Capability needs the actual `NewsEvent` content and prior step results, none of which this signature carries.

**Two ways to reconcile this without violating "do not modify WorkflowRunner provider-specifically":**

**Option 1 (recommended) — constructor injection, zero changes to `workflows/`:**
```python
class CapabilityExecutor:
    """Implements workflows.runner.StepExecutor. Constructed fresh per
    (session, task_id) pair, immediately before WorkflowRunner.run() is
    called with the same session and task_id."""

    def __init__(self, session: AsyncSession, task_id: UUID, registry: CapabilityRegistry) -> None:
        self._session = session
        self._task_id = task_id
        self._registry = registry

    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        # 1. Re-fetch EditorialTask via self._session (same identity map WorkflowRunner
        #    is already using - reads its live, in-progress `workflow` JSON, including
        #    whatever earlier steps in *this same run* already completed).
        # 2. Fetch NewsEvent via task.event_id.
        # 3. Build CapabilityContext from both, plus `step`.
        # 4. definition, capability = self._registry.resolve(step.capability)
        # 5. result = await capability.execute(context)
        # 6. On result.status == "FAILED": raise StepExecutionError or
        #    PermanentStepFailureError depending on the capability error type (see §13).
        # 7. On success: persist an AIExecution row (see §15), return result.structured_output.
        ...
```
This requires **zero changes** to `workflows/runner.py`, `workflows/registry.py`, or `schemas/workflow.py` — `WorkflowRunner(executor=CapabilityExecutor(session, task_id, capability_registry))` is constructed by whatever future orchestration code processes one task, exactly parallel to how every Phase 5 test already constructs a fresh executor per task. `WorkflowRunner` never learns anything new; it just receives a different `StepExecutor` implementation, satisfying the Protocol exactly as declared today.

**Option 2 (alternative, requires a generic — not provider-specific — Protocol change):** widen `StepExecutor.execute(self, step, context: StepExecutionContext)` where `StepExecutionContext` carries only what `WorkflowRunner` already holds in memory (`task_id`, the live `WorkflowExecutionState`) — still zero knowledge of AI/providers/capabilities inside `workflows/`, but it is a signature change to a Phase 5 file.

**Recommendation: Option 1.** It fully satisfies "no changes to Phase 1–5" (not just "no provider-specific changes"), and costs nothing architecturally — the constructor already has everything the executor needs. Flagged in §20 for explicit approval since it's a real design fork, not a detail.

**Timeout note**: `WorkflowRunner` already wraps `self._executor.execute(step)` in `asyncio.wait_for(..., timeout=step.timeout_seconds)` (Phase 5, already shipped). `CapabilityExecutor.execute()` therefore does **not** need its own step-level timeout — but `Capability.execute(context)` internally may still enforce its **own**, finer-grained timeout (`CapabilityConfig.timeout_seconds`) around just the `LLMGateway` call, distinct from and nested inside the Workflow step timeout. This gives **three** independent timeout boundaries end to end: whole-workflow (`WorkflowDefinition.timeout_seconds`) → step (`WorkflowStepDefinition.timeout_seconds`, enforced by `WorkflowRunner`) → capability-internal (`CapabilityConfig.timeout_seconds`, enforced by the Capability itself around its Gateway call). Each is a real, separate number; a capability-internal timeout should normally be set smaller than its enclosing step's timeout, but nothing in this design enforces that relationship automatically — worth flagging as an open question (§20).

---

## 11. Boundary: Capability Framework ↔ future LLM Gateway

```python
class LLMGateway(Protocol):
    """The ONLY thing a Capability may call for AI inference. Unimplemented
    in Phase 6 - contract only, no provider, no real HTTP call."""

    async def generate(self, request: "GenerateRequest") -> "GenerateResponse": ...
    async def embed(self, request: "EmbedRequest") -> "EmbedResponse": ...
    async def classify(self, request: "ClassifyRequest") -> "ClassifyResponse": ...
    async def moderate(self, request: "ModerateRequest") -> "ModerateResponse": ...
```

Every one of `GenerateRequest`/`EmbedRequest`/`ClassifyRequest`/`ModerateRequest` carries only provider-agnostic fields (`prompt` or `messages`, `preferred_model`, `max_tokens`, `temperature`, `metadata`) — never an `openai.ChatCompletion`-shaped payload or an Anthropic-specific message block. `GenerateResponse` etc. carry `text`/`structured_output`, `model_used`, `usage` (tokens) — the same `CapabilityUsage` shape as `CapabilityResult.usage` (§14), so a Capability can pass the Gateway's usage straight through without reshaping it.

A `Capability` implementation depends **only** on this Protocol (injected at construction, same pattern as `CapabilityExecutor`/`WorkflowRunner`) — never on a concrete Gateway class, and never on `core.config.settings.openai_api_key`/`anthropic_api_key` directly. The real `LLMGateway` implementation, provider registration, and API-key wiring are explicitly **out of scope for Phase 6** and for this planning document.

---

## 12. Boundary: Capability Framework ↔ Prompt System

Per docs/07 §10/§23 and docs/11 §13: a prompt is `SYSTEM ROLE + CONTEXT + TASK + RULES + OUTPUT FORMAT`, stored outside Python, versioned, and looked up by `(name, version)`. Proposed contract (definition only, no real prompt files created in this phase — `prompts/` does not exist yet and this task doesn't create it):

```python
class PromptRepository(Protocol):
    def resolve(self, name: str, version: str | None = None) -> "RenderedPrompt":
        """version=None returns the latest registered version."""
        ...


class RenderedPrompt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    version: str
    system: str
    rules: list[str]
    output_schema: dict[str, Any]   # JSON Schema the Capability expects the Gateway response to satisfy
```

A `Capability` asks its `PromptRepository` for a `RenderedPrompt` by name (matching `CapabilityDefinition.name`), fills in the `CONTEXT`/`TASK` blocks itself from `CapabilityContext`, and hands the assembled text/messages to `LLMGateway.generate()`. The Capability Framework defines this **lookup contract** only; the actual prompt storage format (`.yaml` per docs/07 §23.1/docs/11 §15), the `prompts/` directory, and prompt testing (docs/07 §26.3) are out of scope for Phase 6.

---

## 13. Error hierarchy

Mirrors the Phase 5 `workflows/errors.py` pattern exactly, and maps cleanly onto `StepExecutionError`/`PermanentStepFailureError` at the `CapabilityExecutor` boundary:

```
CapabilityError
    CapabilityConfigurationError      # bad CapabilityDefinition/config - never retried, config bug
    ValidationCapabilityError         # Gateway response failed output-schema validation - not retried (bad prompt/model behavior)
    RetryableCapabilityError          # transient (rate limit, transient provider error) - CapabilityExecutor maps -> StepExecutionError
    PermanentCapabilityError          # non-retryable business failure - CapabilityExecutor maps -> PermanentStepFailureError
    CapabilityTimeoutError            # capability-internal timeout (see the 3-boundary note in §10) - treated as retryable by default
```

`CapabilityExecutor` is the **only** place that translates this hierarchy into the Phase 5 `workflows.errors` hierarchy — `Capability` implementations never import `workflows.errors` directly, keeping the two error worlds decoupled (a future non-Workflow caller of a Capability, if one ever exists, wouldn't need to know about Workflow-specific error types).

---

## 14. Usage, metrics, and cost-data contracts

```python
class CapabilityUsage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
```

Deliberately **no cost field anywhere in the Capability Framework** — per this task's own instruction (item 15) and docs/13_1 §9, only the Cost Tracker (`services/cost_tracker.py`, not built in this phase) turns `CapabilityUsage` + `model_used` into an actual `Decimal` cost, using its own model-price table. `CapabilityResult` carries `usage`, `model_used`, `started_at`/`finished_at`/`duration_seconds`, `retry_count` (tracked by `CapabilityExecutor`, not the Capability itself, mirroring how Phase 5's `WorkflowRunner` — not the Capability/executor — owns `EditorialTask.retry_count`) — everything Cost Tracker and `AIExecution` persistence need, nothing they don't.

---

## 15. AIExecution compatibility — field by field

| Field | Current model | Phase 6 mapping | Compatible? |
|---|---|---|---|
| `id` | `UUID`, PK | n/a | Yes |
| `task_id` | `UUID`, FK → `editorial_tasks.id` | `CapabilityContext.task_id` | Yes |
| `capability` | `AICapability` enum (7 fixed values, no `ENGAGEMENT`) | `CapabilityDefinition.name` / `step.capability` **must map onto one of the 7 enum values** | **Gap — see below** |
| `model` | `str` | `CapabilityResult.model_used` | Yes |
| `prompt_version` | `str \| None` | `CapabilityResult.prompt_version` | Yes |
| `input_tokens`/`output_tokens` | `int` | `CapabilityResult.usage.*` | Yes |
| `cost` | `Decimal` | Computed by Cost Tracker from `usage` + `model_used` — **not** written by the Capability or `CapabilityExecutor` directly | Yes, once Cost Tracker exists |
| `response` | `JSON, nullable` | `CapabilityResult.structured_output` | Yes |
| `created_at`/`updated_at` | server-managed | n/a | Yes |

**The one real gap**: Phase 5's shipped `news_analysis.py` step uses `capability="engagement"`, which has no corresponding `AICapability` member. This is not a Phase 6 blocker (Phase 6 persists nothing — no real Capability runs yet), but it must be resolved before any real Engagement-related Capability writes its first `AIExecution` row. Three options, presented for your decision (not decided here):
1. Persist "engagement" analysis under `AICapability.INTELLIGENCE` (docs/06 §7.2's "Audience Relevance Analysis" sub-function is conceptually adjacent) — no migration, immediate, slightly blurs the taxonomy.
2. Add an `ENGAGEMENT` value to `AICapability` in a future migration — cleanest long-term, requires a migration (out of scope for approval right now).
3. Leave `workflows/definitions/news_analysis.py`'s step unpersisted-as-`AIExecution` entirely (its result still flows through `EditorialTask.workflow.step_results`, just never gets its own `ai_executions` row) — avoids both a migration and a taxonomy compromise, at the cost of losing per-step cost/metrics visibility for that one step specifically.

My recommendation, if forced to pick a default now: **option 1** (map to `INTELLIGENCE`) — cheapest, reversible, no migration, and the two capabilities' inputs (news content + audience angle) already overlap conceptually per docs/06.

---

## 16. Is a migration required for Phase 6?

**No.** Phase 6, scoped as approved in §4 (Option C), creates zero new database-persisting behavior — no real Capability ever executes, so no `AIExecution` row is ever written by anything built in this phase. `AIExecution`'s schema is otherwise fully sufficient for everything `CapabilityResult`/§14 need. The one gap found (§15) only becomes relevant once a *future* phase implements a real Capability that needs to persist against the `engagement` step name specifically — and even then, options 1 and 3 above avoid a migration entirely.

---

## 17. Proposed file tree (nothing created yet — for approval)

```
capabilities/
    __init__.py
    errors.py              # CapabilityError hierarchy (§13)
    registry.py             # CapabilityRegistry, build_registry() (§9) - ships empty-but-sealed in Phase 6
    executor.py             # CapabilityExecutor, implementing workflows.runner.StepExecutor (§10)

schemas/
    capability.py            # CapabilityContext, CapabilityResult, CapabilityUsage,
                              # NewsEventSnapshot, WorkflowExecutionStateSnapshot (§6, §7, §14)
    capability_definition.py  # CapabilityDefinition, CapabilityConfig (§8)

integrations/
    llm_gateway/
        __init__.py
        protocol.py           # LLMGateway Protocol + Generate/Embed/Classify/ModerateRequest/Response (§11)
                                # NO provider implementation, NO real HTTP call

integrations/
    prompts/
        __init__.py
        protocol.py           # PromptRepository Protocol + RenderedPrompt (§12) - NO prompt files, NO prompts/ dir

tests/
    test_capability_registry.py
    test_capability_executor.py
    test_capability_schemas.py
    test_llm_gateway_protocol.py     # contract/shape tests only - no real network
```

**Nothing under `workflows/`, `database/`, `services/` (existing files) changes.** `prompts/` (the actual content directory from docs/07 §23.1/docs/11 §15) is **not created** in this phase — only its lookup *contract* is defined, under `integrations/prompts/`.

---

## 18. Test plan

**Unit** (no database, no network): `CapabilityRegistry` (register/duplicate/unknown/seal, mirroring `test_workflow_registry.py` exactly); Pydantic schema boundary + `extra="forbid"` rejection for every schema in §6–§8, §11, §12, §14 (mirroring `test_workflow_schemas.py`); error-hierarchy identity checks (§13).

**Integration** (real Postgres, transactional rollback, same `tests/conftest.py` fixture Phase 5 already introduced): `CapabilityExecutor` constructed against a real `EditorialTask`/`NewsEvent`, driven by a **fake** `Capability` implementation (no LLM Gateway, no network) that returns a deterministic `CapabilityResult` — proving the `StepExecutor` contract is satisfied end to end (a `WorkflowRunner(executor=CapabilityExecutor(...))` run completes exactly as any other Phase 5 `StepExecutor` would).

**Fake Gateway**: a `FakeLLMGateway` implementing the `LLMGateway` Protocol with deterministic, hardcoded responses — used by capability-level tests once real capabilities exist (not in this phase, since none are built yet) and by the contract tests here to prove the Protocol shape is implementable at all.

**Deterministic executor tests**: retryable vs. permanent vs. validation vs. timeout `CapabilityError` subtypes each map to the correct `workflows.errors` type at the `CapabilityExecutor` boundary (§13) — the single highest-value test in this phase, since it's the actual bridge Phase 7+ will depend on.

**Regression**: full existing 129-test suite unaffected; `ruff`/`mypy` clean on every new file; diff confirms zero changes under `workflows/`, `database/models/`, `database/migrations/`, `services/collector.py`, `services/workflow_service.py`, `integrations/sources/`.

---

## 19. Runtime validation plan (no real AI calls)

Using the real Postgres pattern established in Phase 5 (rolled-back transaction, real `NewsEvent`/`EditorialTask`):

1. Register a fake `Capability` (deterministic, in-memory) in a throwaway sealed `CapabilityRegistry`.
2. Construct `WorkflowRunner(executor=CapabilityExecutor(session, task_id, that_registry))` and `run()` it against a real `EditorialTask` created via the existing `WorkflowService.create_task()`.
3. Confirm the run completes exactly as a Phase 5 `DeterministicPlaceholderExecutor`-driven run would (`CREATED → RUNNING → COMPLETED`), proving `CapabilityExecutor` is a drop-in `StepExecutor`.
4. Confirm a fake `RetryableCapabilityError` from the fake Capability is correctly retried at the step level (same `retry_count` semantics as Phase 5) and a fake `PermanentCapabilityError` fails the task immediately, with zero retries.
5. Confirm no `openai`/`anthropic`/network call occurs anywhere (no such import exists in this phase's code at all — verifiable by `grep`, not just by inspection).
6. Roll back the transaction; confirm zero residue via a direct follow-up query, exactly as the last two Phase 5 validation rounds did.

---

## 20. Open questions requiring your decision

1. **`CapabilityExecutor` context strategy** (§10): constructor-injection (recommended, zero Phase 1–5 changes) vs. a generic `StepExecutionContext` Protocol widening (also zero-AI-knowledge, but touches a Phase 5 file). **Recommended: constructor-injection.**
2. **LLM Gateway method set** (Conflict A): `generate`/`embed`/`classify`/`moderate` (this task's wording) vs. `generate`/`analyze`/`summarize`/`embed` (docs/07, docs/10). **Recommended: this task's four methods, treating `analyze`/`summarize` as prompt-level use cases of `generate`.**
3. **The missing `ENGAGEMENT` AICapability value** (§15): map to `INTELLIGENCE` now (no migration) / add a migration later / never persist that one step's `AIExecution` row. **Recommended: map to `INTELLIGENCE` for now.**
4. **Capability-internal timeout vs. step timeout relationship** (§10): should `CapabilityConfig.timeout_seconds` be required to be strictly smaller than the owning `WorkflowStepDefinition.timeout_seconds`, or left as two independent numbers with no enforced relationship? **No recommendation yet — genuinely open.**
5. **Where retry_count for capability-internal retries is tracked**: does a `RetryableCapabilityError` retried *inside* a Capability (e.g., the Gateway call itself retried once before the Capability gives up and returns `FAILED`) count toward `EditorialTask.retry_count` at all, given that counter currently only increments for *step*-level retries (Phase 5)? **Recommended: no — `EditorialTask.retry_count` stays step-level only; any capability-internal retry attempts are visible only in `CapabilityResult.metadata`/`logs`, never double-counted into the Workflow-level counter.**
6. **`prompts/` directory and real prompt content**: entirely deferred past this phase per §4/§12 — confirm this is acceptable, or should Phase 6 also stub an empty `prompts/` directory structure (no content) for forward compatibility?

---

## 21. Recommended canonical rules (Phase 6)

| Rule | Value |
|---|---|
| Phase 6 scope | Option C: Capability Framework + LLM Gateway contracts, no provider implementation, no real Capability implementation |
| `Capability.execute()` signature | `execute(context: CapabilityContext) -> CapabilityResult` |
| `CapabilityContext`/`CapabilityResult`/etc. | All `extra="forbid"`; frozen except none needed to be mutable (unlike `WorkflowExecutionState`, nothing here is mutated in place) |
| `CapabilityDefinition.version` | Integer, matching the `WorkflowDefinition.version` fix |
| `CapabilityRegistry` | Immutable after `seal()`, identical pattern to `WorkflowRegistry`; ships empty-but-sealed in Phase 6 |
| `CapabilityExecutor` ↔ `StepExecutor` | Constructor-injection (session, task_id, registry) — zero changes to `workflows/` |
| Cost | Never computed inside a Capability; `CapabilityResult.usage` carries tokens only |
| LLM Gateway methods | `generate`, `embed`, `classify`, `moderate` (pending approval — Open Question 2) |
| Error mapping at the `CapabilityExecutor` boundary | `RetryableCapabilityError`→`StepExecutionError`; `PermanentCapabilityError`/`ValidationCapabilityError`/`CapabilityConfigurationError`→`PermanentStepFailureError`; `CapabilityTimeoutError`→retryable by default |
| Provider isolation | No `openai`/`anthropic`/`gemini`/`grok`/`deepseek`/`ollama` import anywhere in `capabilities/` or `integrations/llm_gateway/` |
| Migration | None required for Phase 6 itself |

**No code, migrations, or Phase 1–5 changes have been made. Waiting for your approval on the open questions in §20 (especially Open Questions 1–3) before writing any implementation.**
