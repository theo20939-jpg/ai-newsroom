# Phase 6 Architecture Contract — AI Core Specification

**Status: Final design specification. Single source of truth for the AI Core.**

This document supersedes no prior document as a record of what was decided — it is not a revision of
`docs/phase6_capability_framework_planning.md` or `docs/phase6_architecture_review.md`, and neither is
edited by it. It **does** supersede those two documents as the thing future code and future contributors
are validated against: where this document's contracts differ from either planning artifact (see §14 and
the closing decision list), this document governs. No code is written, no existing code is modified, no
migration is created, and nothing is committed as part of producing this document.

This document is normative. "MUST" / "MUST NOT" / "REQUIRED" / "FORBIDDEN" statements are binding on all
future Phase 6+ implementation work. Where a rule is not yet enforced by tooling, it is enforced by code
review against this document.

**Amended 2026-07-15:** two binding amendments are incorporated into this contract — §15 (Amendment A,
the `"engagement"` persistence alias) and §16 (Amendment B, deferral of real `AIExecution` persistence).
Both amendments are part of this document, not a separate one; §5, §9, §10, and §14 below have been edited
in place to stay consistent with them.

---

## 1. AI Core Principles

1. **P1 — Single ingress for AI traffic.** All calls to an AI provider MUST pass through `LLMGateway`. No
   other component may hold a provider SDK client or make an HTTP call to a provider endpoint.
2. **P2 — Workflow knows nothing about AI.** `WorkflowRunner`, `WorkflowRegistry`, and every file under
   `workflows/` MUST NOT import, reference, or depend on `Capability`, `LLMGateway`, `PromptRepository`,
   `CostTracker`, `BudgetGuard`, or any provider SDK. Workflow's only AI-adjacent knowledge is the
   `StepExecutor` Protocol it already depends on.
3. **P3 — Capability knows nothing about providers.** A `Capability` implementation MUST NOT import a
   provider SDK (`openai`, `anthropic`, `google.generativeai`, or equivalent) directly or transitively.
   Its only permitted AI-facing dependencies are `LLMGateway`, `PromptRepository`, and `BudgetGuard`, all
   injected at construction — never self-constructed, never imported as a module-level singleton inside
   `capabilities/`.
4. **P4 — Capabilities never call each other.** A `Capability` MUST NOT invoke another `Capability`
   directly, in-process or otherwise. Capabilities communicate exclusively by reading and writing
   persisted state (`EditorialTask.workflow.step_results`), mediated by `CapabilityExecutor`.
5. **P5 — Cost accounting is centralized and split into two non-overlapping concerns.** Pre-flight budget
   enforcement is owned exclusively by `BudgetGuard`. Post-hoc cost recording is owned exclusively by
   `CostTracker`. Neither may perform the other's job (§9).
6. **P6 — Prompt lifecycle is isolated from prompt lookup.** `PromptRepository` MUST be read-only at
   runtime. Authoring, versioning, and publishing prompts is owned by a separate, offline component this
   document names but does not design (§8).
7. **P7 — Components communicate only through typed contracts.** Every cross-component boundary in this
   document is a Pydantic model or a `Protocol` — never a raw dict, ORM object, or provider-shaped
   payload crossing a boundary.
8. **P8 — No component persists what it does not own.** Only `CapabilityExecutor` (via `CostTracker` for
   cost data) writes to the database on the AI path. `Capability`, `LLMGateway`, `PromptRepository`, and
   `BudgetGuard` implementations MUST NOT hold a database session or issue a query.
9. **P9 — No dynamic discovery.** Every `Capability`, `WorkflowDefinition`, and prompt is registered
   explicitly, at process start, before the relevant registry seals. No component scans the filesystem or
   package index at runtime to discover new capabilities, providers, or prompts.
10. **P10 — Structured output only.** No `Capability` returns free text as its final answer. Every
    `CapabilityResult.structured_output` is a JSON-serializable dict validated, at minimum, against the
    shape declared by the prompt's `output_schema` (§8).

### Forbidden dependency edges

| Edge | Status |
|---|---|
| Workflow → Provider SDK | ❌ FORBIDDEN |
| Workflow → LLM Gateway | ❌ FORBIDDEN |
| Workflow → Capability | ❌ FORBIDDEN (Workflow depends only on `StepExecutor`) |
| Capability → Provider SDK (OpenAI, Anthropic, Gemini, etc.) | ❌ FORBIDDEN |
| Capability → Database / ORM session | ❌ FORBIDDEN |
| Capability → CapabilityExecutor | ❌ FORBIDDEN (no upward dependency) |
| Capability → another Capability | ❌ FORBIDDEN |
| PromptRepository → Provider SDK | ❌ FORBIDDEN |
| PromptRepository → Database | ❌ FORBIDDEN (prompt content is file-based, versioned artifacts, not DB rows) |
| LLM Gateway → Database | ❌ FORBIDDEN |
| LLM Gateway → Workflow / Capability internals | ❌ FORBIDDEN (Gateway has no upward knowledge) |
| BudgetGuard → Provider SDK | ❌ FORBIDDEN |
| BudgetGuard → LLM Gateway | ❌ FORBIDDEN (BudgetGuard is consulted *before* the Gateway call, never wraps or calls it) |
| CostTracker → Provider SDK | ❌ FORBIDDEN |
| CostTracker → Workflow / Capability internals | ❌ FORBIDDEN (CostTracker only ever receives data `CapabilityExecutor` hands it) |
| CapabilityRegistry → Database | ❌ FORBIDDEN (build-time, in-memory only) |

---

## 2. Capability Contract

Five objects make up the Capability contract. Each has exactly one responsibility.

| Object | Responsibility |
|---|---|
| `Capability` | Runs one AI-capability's logic once, given a context, and returns a result. Holds only injected dependencies (`LLMGateway`, `PromptRepository`, `BudgetGuard`) and its own `CapabilityDefinition`. Contains no persistence, no Workflow knowledge, no provider knowledge. |
| `CapabilityContext` | The complete, immutable, read-only input a `Capability.execute()` call receives. Never an ORM object. Never mutated after construction. |
| `CapabilityResult` | The complete, immutable output of one `Capability.execute()` call — structured answer, zero-or-more AI call records, timing, and chaining data. Never a bare string, never partially populated by convention. |
| `CapabilityDefinition` | The static, versioned declaration of a capability's identity and constraints (name, version, required context, expected output keys, config). Registered once, at process start. |
| `CapabilityConfiguration` (`CapabilityConfig`) | The tunable, non-identity part of a `CapabilityDefinition` — timeouts, retry counts, advisory model preference. Provider-agnostic; no provider-specific validation. |

```python
class Capability(Protocol):
    """One AI-capability module. See P3/P4. Never calls a provider SDK.
    Never calls another Capability. Communicates only through CapabilityContext
    (in) and CapabilityResult (out)."""

    async def execute(self, context: "CapabilityContext") -> "CapabilityResult":
        """Run once. Raises only CapabilityError subtypes (§5's error hierarchy
        reference) - never a bare Exception."""
        ...
```

---

## 3. CapabilityContext

**Decision: `CapabilityContext` remains a single immutable object, internally composed of three nested,
frozen sub-models.** This is the permanent contract — not a placeholder pending a future 3-parameter
split.

Rationale: every capability that exists, and every capability planned for the next several dozen, runs as
a Workflow step over Workflow-supplied runtime metadata (`attempt`, `iteration_count`). A 3-parameter
split at the `Capability.execute()` call site earns its cost only once a capability exists that has no
Workflow step wrapping it at all — no such capability is in scope for Phase 6. Splitting now would add
call-site complexity to solve a problem nothing in this system yet has. Nesting the same three groupings
*inside* one object costs nothing today and makes a future full split a mechanical extraction (each
sub-model becomes its own top-level parameter) rather than a rewrite of every `Capability` implementation's
field access.

```python
class BusinessContext(BaseModel):
    """Domain data the capability operates on. Read-only snapshots, never ORM objects."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    news_event: NewsEventSnapshot
    workflow_state: WorkflowExecutionStateSnapshot
    language: str = "en"
    audience: str | None = None
    brand_voice: dict[str, Any] | None = None


class RuntimeContext(BaseModel):
    """Metadata owned by CapabilityExecutor/WorkflowRunner - never set by the capability itself."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID
    event_id: UUID
    capability_name: str
    priority: TaskPriority
    attempt: int
    iteration_count: int


class ExecutionContext(BaseModel):
    """Advisory Gateway-routing hints. LLMGateway makes the final model/provider choice."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    preferred_model: str | None = None
    preferred_provider: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None


class CapabilityContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    business: BusinessContext
    runtime: RuntimeContext
    execution: ExecutionContext
```

**Rule:** a `Capability` MUST treat every field of `CapabilityContext` (and its nested sub-models) as
read-only. `CapabilityContext` MUST NOT be reused or mutated across attempts — `CapabilityExecutor`
constructs a fresh one per attempt (§5).

---

## 4. CapabilityResult

**`CapabilityResult` MUST NOT assume exactly one AI call happened.** It MUST support zero AI calls (a
purely deterministic or rule-based capability), one AI call (today's common case), and many AI calls (a
tool-calling, planning, or ensemble capability making several internal `LLMGateway` calls before
returning). This is a change from the scalar `model_used` / `prompt_name` / `prompt_version` / `usage`
fields proposed in the Phase 6 planning document (§7 of that document) and confirmed as insufficient in
the architecture review (§3 of that review). This section is the permanent, binding replacement.

```python
class CapabilityUsage(BaseModel):
    """Token or unit cost of one AI interaction. Fields are optional, not
    zero-defaulted, so a non-token-billed call (e.g. a flat-rate search API)
    is representable without a hack."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    units: int | None = Field(default=None, ge=0)      # e.g. images generated, search queries issued
    unit_type: str | None = None                        # opaque to the framework - "image", "search_query", ...


class CapabilityCall(BaseModel):
    """Everything required to reconstruct one AI interaction that occurred
    while producing a CapabilityResult. One CapabilityCall MUST correspond to
    exactly one LLMGateway method invocation - never a batch of several."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: UUID
    sequence: int = Field(ge=0)                  # order within this CapabilityResult, 0-based
    gateway_method: Literal["generate", "generate_stream", "embed", "classify", "moderate", "rerank"]
    status: Literal["SUCCESS", "FAILED"]

    model_used: str | None                        # None only if status == "FAILED" before a model was selected
    provider: str | None = None                    # opaque audit label (e.g. "anthropic") - never a type dependency
    prompt_name: str | None = None
    prompt_version: str | None = None

    usage: CapabilityUsage

    started_at: datetime
    finished_at: datetime
    duration_seconds: float

    error: str | None = None                       # short message only if status == "FAILED" - never a stack trace


class CapabilityResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["SUCCESS", "FAILED"]
    structured_output: dict[str, Any] | None
    confidence: int | None = Field(default=None, ge=0, le=100)

    calls: list[CapabilityCall] = Field(default_factory=list)   # empty list is valid - zero AI calls

    started_at: datetime
    finished_at: datetime
    duration_seconds: float

    metadata: dict[str, Any] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)
    next_context: dict[str, Any] | None = None
```

**Binding rules:**

- `CapabilityResult` MUST NOT carry a top-level `model_used`, `prompt_name`, `prompt_version`, or `usage`
  field. Any caller needing an aggregate (total tokens, "the" model used) MUST derive it by iterating
  `calls` — aggregation is a read, not a stored field, so there is exactly one source of truth.
- `structured_output` for binary or large-output capability types (image generation, embeddings, and
  similar) MUST contain a reference (object-storage URL, artifact ID) — never inlined bytes or a large
  vector payload treated as loggable text.
- `logs` MUST NOT contain full request or response payloads — short, structured trace lines only.
- `calls` being empty (`[]`) is valid and MUST be handled as a normal case, not an error — it represents a
  capability that made zero AI calls (e.g. a deterministic validation/aggregation step).

---

## 5. CapabilityExecutor Contract

`CapabilityExecutor` is the **only** bridge between `workflows.runner.StepExecutor` and the Capability
Framework. It implements `StepExecutor.execute(step: WorkflowStepDefinition) -> dict[str, Any]` exactly as
declared in Phase 5 — **no change to that Protocol's signature.**

**`CapabilityExecutor` MUST:**

1. Be constructed fresh per `(session, task_id, registry)`, immediately before the matching
   `WorkflowRunner.run()` call, using the same session and task_id (constructor injection — zero changes
   to `workflows/runner.py`, `workflows/registry.py`, or `schemas/workflow.py`).
2. Re-fetch the live `EditorialTask` via its own `session` on every `execute(step)` call, and fetch the
   associated `NewsEvent` via `task.event_id`.
3. Build a `CapabilityContext` (§3) from the fetched rows plus the incoming `step`.
4. Resolve `(CapabilityDefinition, Capability)` from `self._registry` by `step.capability`.
5. Map `step.capability` (a bare string) to the corresponding `AICapability` enum value before any
   persistence write — using the canonical mapping table in §10. Raise `CapabilityConfigurationError` if
   no mapping exists.
6. Invoke `await capability.execute(context)` exactly once per `execute(step)` call. `CapabilityExecutor`
   MUST NOT retry a `Capability` internally — step-level retry remains `WorkflowRunner`'s exclusive
   responsibility, unchanged from Phase 5.
7. **[Amended by Amendment B, §16] MUST NOT persist any `AIExecution` row in Phase 6.** `CapabilityExecutor`
   MAY validate, via `AIExecutionMapper` (§10.1), that a `SUCCESS`-status `CapabilityCall` maps cleanly to
   the row shape `AIExecution` would eventually store — but MUST NOT perform the write. Real per-call
   persistence, for both successful and failed/partial calls, is deferred to the future real Gateway/Cost
   Tracker phase (§16).
8. MUST NOT compute cost itself. In a future phase, the actual write (usage → cost → row) is delegated to
   `CostTracker` (§9) via the `AIExecutionMapper` boundary (§10.1) — neither is invoked by
   `CapabilityExecutor` in Phase 6.
9. On `result.status == "FAILED"`, raise the `workflows.errors` type dictated by the specific
   `CapabilityError` subtype the `Capability` raised (mapping table unchanged from the Phase 6 planning
   document §13).
10. On `result.status == "SUCCESS"`, return `result.structured_output` (or `{}` if `None`) to satisfy the
    `StepExecutor` contract.

**`CapabilityExecutor` MUST NOT:**

- Call `LLMGateway`, `BudgetGuard`, or `PromptRepository` directly. It only ever calls `Capability.execute()`
  and `CostTracker`.
- Perform budget enforcement. That is exclusively `BudgetGuard`'s responsibility, invoked from inside the
  `Capability`'s own call path (§9), not from `CapabilityExecutor`.
- Mutate `WorkflowStepDefinition`, `WorkflowExecutionState`, or any Phase 5 schema.
- Retry a `Capability` call internally, or preserve partial state across `execute(step)` invocations — each
  call to `execute(step)` is independent; a `Capability` MUST behave correctly when re-invoked fresh.
- Import a provider SDK, directly or transitively.
- Write an `AIExecution` row, call `CostTracker`'s write path, or otherwise persist AI-call data to the
  database in Phase 6 (Amendment B, §16). The only permitted database activity is the `EditorialTask`/
  `NewsEvent` read-fetch (§5, rule 2) and, optionally, the read-only `AIExecutionMapper` validation
  (§10.1) — neither of which is a write.

**Timeout boundary (unchanged from the Phase 6 planning document):** `WorkflowRunner` already wraps
`self._executor.execute(step)` in `asyncio.wait_for(..., timeout=step.timeout_seconds)`.
`CapabilityExecutor.execute()` therefore requires no timeout of its own. A `Capability` MAY additionally
enforce its own finer-grained `CapabilityConfig.timeout_seconds` around its internal Gateway calls — a
third, independent, nested timeout boundary. Nothing in the framework enforces
`CapabilityConfig.timeout_seconds < WorkflowStepDefinition.timeout_seconds`; a `Capability` implementation
MUST set its own value smaller than its owning step's timeout by convention, not by an enforced
constraint.

---

## 6. Capability Registry

`CapabilityRegistry` is the single, in-memory, explicit-registration-only resolver from a capability name
to its `(CapabilityDefinition, Capability)` pair. This contract is designed to remain correct at 30–50
capabilities without change. Plugin loading is explicitly not designed here (§13).

**Registration rules:**

- `register(definition, capability)` MUST raise `DuplicateCapabilityRegistrationError` if `definition.name`
  is already registered — regardless of `definition.version`. Exactly one version of a given name may be
  registered at a time (identical constraint to `WorkflowRegistry`, an accepted Phase 5 precedent, not a
  new restriction).
- `register()` MUST raise `CapabilityRegistryAlreadySealedError` once `seal()` has been called. No
  registration may occur after boot.
- `seal()` is REQUIRED before the registry is handed to any `CapabilityExecutor`. `build_registry()` MUST
  call `seal()` before returning.

**Lookup rules:**

- `resolve(name: str) -> tuple[CapabilityDefinition, Capability]` MUST raise `UnknownCapabilityError` for
  an unregistered name. `resolve()` MUST behave identically before and after sealing (read-only regardless
  of seal state).
- `resolve()` MUST NOT perform I/O, database access, or network calls.

**Versioning rules:**

- `CapabilityDefinition.version` is a required, monotonically-increasing integer. There is no
  version-negotiated lookup (`resolve()` takes only a name) — a new version of a capability REQUIRES
  replacing the prior registration at process start, not coexisting with it at runtime.

**Scalability to 30–50 capabilities:**

- The `register`/`resolve`/`seal` contract is discovery-mechanism-agnostic: `build_registry()` may grow
  from explicit imports to iterating a declared list, or (in a future, separately-approved phase) an
  `entry_points`-based plugin scan — without changing `CapabilityRegistry`'s own methods.
- **Known, accepted limitation, not fixed by this document:** `CapabilityDefinition.name` is a flat,
  un-namespaced string, identical in shape to the already-shipped `WorkflowStepDefinition.capability`
  (Phase 5). At 30–50 in-house, single-organization capabilities this carries negligible collision risk.
  Any future move to namespaced identifiers (e.g. for third-party or installable capabilities) REQUIRES a
  coordinated change to both `CapabilityDefinition.name` and `WorkflowStepDefinition.capability` — this is
  explicitly out of scope for Phase 6 (§13) and is recorded here so it is a planned cost, not a surprise.

---

## 7. LLM Gateway Contract

`LLMGateway` is the **only** thing a `Capability` may call for AI inference (P1, P3). This is an interface
only — no provider implementation exists in Phase 6, and none of these types encode a provider-specific
shape (no `openai.ChatCompletion`, no Anthropic message-block format). Every request/response type below is
provider-neutral by construction: fields are generic (`messages`, `tools`, `usage`) and a provider adapter
(built in a later phase) is solely responsible for translating to/from this shape.

```python
class ContentPart(BaseModel):
    """One piece of a message - text or a reference to a non-text artifact.
    Binary content is never inlined; multimodal input/output is always a
    reference (URI/artifact id), never raw bytes in this contract."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["text", "artifact_ref"]
    text: str | None = None
    artifact_ref: str | None = None      # e.g. object-storage URI
    mime_type: str | None = None         # required when type == "artifact_ref"


class Message(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    role: Literal["system", "user", "assistant", "tool"]
    content: list[ContentPart]


class ToolDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    description: str
    parameters_schema: dict[str, Any]     # JSON Schema for the tool's arguments


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    arguments: dict[str, Any]


class GenerateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    messages: list[Message]
    preferred_model: str | None = None
    preferred_provider: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None

    tools: list[ToolDefinition] | None = None
    tool_choice: Literal["auto", "none", "required"] | None = None

    response_mode: Literal["text", "json_schema"] = "text"
    response_schema: dict[str, Any] | None = None    # REQUIRED when response_mode == "json_schema"

    modalities: list[Literal["text", "image", "audio"]] = Field(default_factory=lambda: ["text"])
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    uri: str
    mime_type: str


class GenerateResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str | None
    structured_output: dict[str, Any] | None
    tool_calls: list[ToolCall] | None = None
    artifacts: list[ArtifactRef] | None = None        # non-text outputs (e.g. generated images)
    finish_reason: Literal["stop", "tool_calls", "length", "content_filter"]
    model_used: str
    usage: CapabilityUsage


class GenerateChunk(BaseModel):
    """One increment of a streamed generate() call."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    delta_text: str | None = None
    delta_tool_call: ToolCall | None = None
    is_final: bool = False
    usage: CapabilityUsage | None = None              # populated only on the final chunk


class EmbedRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    inputs: list[str] = Field(min_length=1)
    preferred_model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbedResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    vectors: list[list[float]]
    model_used: str
    usage: CapabilityUsage


class ClassifyRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    input: str
    labels: list[str] = Field(min_length=1)
    preferred_model: str | None = None


class ClassificationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    label: str
    score: float = Field(ge=0, le=1)


class ClassifyResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    results: list[ClassificationResult]
    model_used: str
    usage: CapabilityUsage


class ModerateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    input: str
    preferred_model: str | None = None


class ModerationCategory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    category: str
    flagged: bool
    score: float = Field(ge=0, le=1)


class ModerateResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    flagged: bool
    categories: list[ModerationCategory]
    model_used: str
    usage: CapabilityUsage


class RerankRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    query: str
    documents: list[str] = Field(min_length=1)
    top_n: int | None = Field(default=None, ge=1)
    preferred_model: str | None = None


class RerankResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    index: int = Field(ge=0)         # index into the original `documents` list
    score: float


class RerankResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    results: list[RerankResult]
    model_used: str
    usage: CapabilityUsage


class LLMGateway(Protocol):
    """The ONLY thing a Capability may call for AI inference. Unimplemented
    in Phase 6 - contract only. No provider-specific parameter anywhere in
    this Protocol or its request/response types."""

    async def generate(self, request: GenerateRequest) -> GenerateResponse: ...
    def generate_stream(self, request: GenerateRequest) -> AsyncIterator[GenerateChunk]: ...
    async def embed(self, request: EmbedRequest) -> EmbedResponse: ...
    async def classify(self, request: ClassifyRequest) -> ClassifyResponse: ...
    async def moderate(self, request: ModerateRequest) -> ModerateResponse: ...
    async def rerank(self, request: RerankRequest) -> RerankResponse: ...
```

**Binding rules:**

- A provider implementation MAY decline to support a given method (e.g. no moderation endpoint) by raising
  `UnsupportedGatewayCapabilityError` — this is a provider-routing concern, not a reason to change this
  Protocol.
- No request or response type above may gain a provider-specific field (e.g. an OpenAI `logprobs` flag or
  an Anthropic-only `thinking` parameter). Provider-specific behavior is configured on the provider adapter
  side, in a later phase, never on these contracts.
- `preferred_model` / `preferred_provider` are advisory only; `LLMGateway` makes the final routing decision.

---

## 8. Prompt Repository Contract

**Ownership:** prompt *content* (system role, rules, output schema — docs/07 §10/§23's
`SYSTEM ROLE + CONTEXT + TASK + RULES + OUTPUT FORMAT` shape) is authored and versioned as files under
`prompts/`, outside Python. `PromptRepository` is a **pure lookup contract** over already-published prompt
artifacts. It owns nothing about how a prompt is authored, tested, or promoted.

**Prompt lifecycle (authoring → validation → publishing → deprecation) is owned by a separate component
this document names but does not design: the Prompt Publisher.** Building the Prompt Publisher is out of
scope for Phase 6 (§13). `PromptRepository` MUST NOT gain a `register`, `update`, `publish`, or `rollback`
method under any circumstance — if prompt lifecycle needs a home, it is a new component, never
`PromptRepository`.

```python
class RenderedPrompt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    version: str
    system: str
    rules: list[str]
    output_schema: dict[str, Any]


class PromptRepository(Protocol):
    def resolve(self, name: str, version: str | None = None) -> RenderedPrompt:
        """version=None returns the latest published version. Pure lookup -
        no validation logic here; validation happens at publish time, before
        a prompt is available to resolve() at all."""
        ...
```

**Binding rules:**

- `resolve()` MUST be side-effect-free and MUST NOT perform network calls.
- A given `(name, version)` MUST resolve to the same `RenderedPrompt` forever — immutability of published
  versions is what makes `AIExecution.prompt_version` a trustworthy audit pointer (§10) and what makes
  prompt regression tests (docs/13 Level 3) meaningful against production content.
- Validation (schema conformance, prompt-quality gates) happens in the Prompt Publisher, at publish time —
  never inside `PromptRepository.resolve()`.
- `Capability` fills the `CONTEXT`/`TASK` blocks itself from `CapabilityContext` and hands the assembled
  `Message` list to `LLMGateway.generate()`; `PromptRepository` never sees `CapabilityContext`.

---

## 9. Cost Tracking Contract

**Permanent execution order, binding for every AI call:**

```
Workflow
  └─ Capability
       └─ Budget Guard        (pre-flight, READ-ONLY check — may reject before any provider call)
            └─ LLM Gateway
                 └─ Provider
                      └─ Usage returned (CapabilityUsage)
       └─ Cost Tracker         (post-hoc — WRITE-ONLY: cost computation + ledger update)
            └─ AIExecution persistence
```

**Stage responsibilities:**

| Stage | Responsibility | Forbidden |
|---|---|---|
| **Capability** | Constructs `CapabilityContext`-derived Gateway requests; calls `BudgetGuard.check(...)` before each `LLMGateway` call it intends to make; assembles `CapabilityCall`/`CapabilityResult` from the Gateway's response and usage. | MUST NOT compute cost. MUST NOT write to the database. |
| **BudgetGuard** | Read-only pre-flight check: given `(capability_name, priority, estimated_usage)`, consults already-recorded spend (written exclusively by `CostTracker`) and either allows or raises `BudgetExceededError` (a `PermanentCapabilityError` subtype — non-retryable). | MUST NOT write spend data. MUST NOT call `LLMGateway` or a provider. MUST NOT be skipped by a `Capability` that intends to make a Gateway call. |
| **LLM Gateway** | Executes the call against a provider, returns a response plus `CapabilityUsage`. | MUST NOT touch the database. MUST NOT know about budgets or cost. |
| **Cost Tracker** | Given a completed `CapabilityCall` (model, usage), computes `Decimal` cost from its own model-price table and writes the `AIExecution` row (§10) via `CapabilityExecutor`. Owns enforcement of hard limits going forward (rejecting the *next* call once a limit is crossed) by making the up-to-date ledger available to `BudgetGuard`. | MUST NOT perform pre-flight checks itself (that is `BudgetGuard`'s exclusive job). MUST NOT call a provider. |

**Binding rule (P5, restated precisely): budget checking and cost recording MUST remain two separate
components with two separate responsibilities — one read-only and pre-flight, one write-only and
post-hoc. No future change may merge them into a single "Cost Tracker does both" component.** This
explicitly refines the Phase 6 planning document's Conflict B resolution (which collapsed the
`docs/06`/`docs/07` "Budget Manager" into a single `services/cost_tracker.py`). `BudgetGuard` is
reinstated here as a distinct, narrowly-scoped component — read-only, pre-flight only — precisely because
collapsing the two made the invocation point of budget enforcement undefined (identified as the most
consequential open coupling in `docs/phase6_architecture_review.md` §9). `CostTracker` retains exclusive
ownership of writing cost data; it does not gain enforcement authority over an in-flight call.

**Phase 6 deferral (Amendment B, §16):** the permanent design above — one `AIExecution` row per
`CapabilityCall`, written via `CostTracker`, regardless of `CapabilityResult.status` — is the target
architecture, not what Phase 6 implements. In Phase 6, `CapabilityExecutor` does not call `CostTracker` at
all. It only validates the `AIExecutionMapper` mapping boundary (§10.1) against `SUCCESS`-status calls, and
persists nothing. `BudgetGuard` and `CostTracker` are defined in Phase 6 as Protocols only, exercised in
tests against fakes — neither has a real implementation, real ledger, or real database write in this
phase.

---

## 10. AIExecution Contract

**Phase 6 status (Amendment B, §16): this section is a compatibility review, not a persistence
implementation.** No component built in Phase 6 writes an `AIExecution` row. The field-by-field mapping
below documents what a `CapabilityCall` *would* map to and is validated for `SUCCESS`-status calls only via
`AIExecutionMapper` (§10.1) — it is not exercised as a real write anywhere in Phase 6.

Field-by-field validity review, no migration proposed:

| Field | Current shape | Remains valid? | Notes |
|---|---|---|---|
| `id` | UUID PK | Yes | No change. |
| `task_id` | UUID, FK to `editorial_tasks.id`, `NOT NULL` | **Valid for Phase 6, not future-proof.** | Every capability registered in Phase 6 runs as a Workflow step over an `EditorialTask`; the constraint holds today. It does not hold once any capability runs outside a Workflow (§13 non-goal for now — no such capability is being built in Phase 6). Flagged for future evolution, not fixed now. |
| `capability` | `AICapability` enum, 7 fixed values | **Valid for Phase 6, not future-proof.** | Closed DB enum requires a migration per new capability name and is fundamentally incompatible with any future installable-capability model (§13 non-goal). Not changed in this document. |
| `model` | `str` | Yes | Maps from `CapabilityCall.model_used`. |
| `prompt_version` | `str \| None` | Yes | Maps from `CapabilityCall.prompt_version`. |
| `input_tokens` / `output_tokens` | `int`, `NOT NULL` | **Requires a mapping rule, not a migration.** | `CapabilityUsage.input_tokens`/`output_tokens` are now optional (§4, for non-token-billed calls). `CostTracker` MUST write `0` when a `CapabilityCall`'s usage has no token count, and MUST record the actual unit count (`units`/`unit_type`) inside the existing `response` JSON column's metadata rather than in these two columns. This is a mapping convention, not a schema change. |
| `cost` | `Decimal`, `NOT NULL` | Yes | Computed by `CostTracker` from `usage` + `model_used`; never written by `Capability` or `CapabilityExecutor` directly. |
| `response` | JSON, nullable | Yes | Maps from the relevant slice of `structured_output` / `CapabilityCall` metadata. Long-term note (not acted on now): unconditionally inlining large structured outputs (e.g. embeddings vectors, image artifact metadata) into an audit-log table conflates "audit trail" with "output storage" — worth revisiting once volume makes this concrete, out of scope for Phase 6. |
| `created_at` / `updated_at` | server-managed | Yes | No change. |

**Fields identified as needing future evolution (explicitly not migrated now):**

1. **Execution grouping.** `AIExecution` has no column linking multiple rows produced by the same
   `CapabilityResult` (i.e. the same step execution, multiple `CapabilityCall`s). Until a future migration
   adds a grouping key (e.g. `execution_group_id`), rows from one multi-call `CapabilityResult` are only
   inferable by `(task_id, capability, created_at proximity)` — sufficient for Phase 6 (where no
   multi-call capability exists yet) but not a permanent answer.
2. **`capability` as a closed enum vs. `CapabilityRegistry`'s open namespace** — see above; the two systems
   are independent sources of truth for "what capabilities exist," kept in sync only by manual migration
   discipline (Conflict D of the Phase 6 planning document, restated here as a permanent known limitation,
   not resolved).
3. **`capability_definition_version`** — `AIExecution` records `prompt_version` but not which
   `CapabilityDefinition.version` produced the row. Additive, non-urgent.

**Temporary persistence alias for the one confirmed gap (Conflict D) — Amendment A, §15:** the Workflow
step name `"engagement"` (`workflows/definitions/news_analysis.py`, already shipped) has no corresponding
`AICapability` enum value. Per this document, `"engagement"` maps to `AICapability.INTELLIGENCE` **only as
a temporary persistence alias**, not as a redefinition of Engagement as Intelligence — it exists solely
because the currently-migrated `AICapability` enum has no `ENGAGEMENT` value. It MUST live in exactly one
centralized mapping; no adapter, `CapabilityExecutor`, or `Capability` implementation may hardcode it
independently; and it MUST be reconsidered before any real Engagement Capability is implemented. No
migration is introduced in Phase 6 to resolve this gap. See §15 for the complete, binding conditions.

---

### 10.1 AIExecutionMapper Protocol (Amendment B, §16)

Phase 6 defines a provider-neutral mapping boundary between `CapabilityCall` (§4 — the complete, permanent,
in-memory contract a `Capability` already produces) and the `AIExecution` row shape above, **without
writing any row.** This gives the mapping logic exactly one home, makes it unit-testable against fakes, and
leaves it ready to be wired to a real write path once a future phase reviews the `AIExecution` schema
against real provider responses (real error shapes, real request IDs, real partial-failure modes).

```python
class AIExecutionMapperResult(BaseModel):
    """The AIExecution row shape one CapabilityCall would produce. Never written
    to the database in Phase 6 - this is the mapping's output, not a persisted row."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID
    capability: str              # AICapability enum *value* - via the centralized alias mapping (§15)
    model: str | None
    prompt_version: str | None
    input_tokens: int
    output_tokens: int
    cost: Decimal | None         # None in Phase 6 - CostTracker's price table is never invoked
    response: dict[str, Any] | None


class AIExecutionMappingError(Exception):
    """Raised when a CapabilityCall cannot be mapped - e.g. status != SUCCESS
    in Phase 6, where only successful-call compatibility is validated."""


class AIExecutionMapper(Protocol):
    """Provider-neutral mapping boundary from CapabilityCall -> AIExecution row
    shape. Implemented in Phase 6 for validation only - never invoked to perform
    a real database write. CapabilityExecutor MUST NOT write AIExecution rows in
    Phase 6 (Amendment B, §16)."""

    def to_execution_row(
        self, task_id: UUID, capability_name: str, call: "CapabilityCall"
    ) -> AIExecutionMapperResult:
        """Maps one CapabilityCall to the row shape it would produce.

        MUST raise AIExecutionMappingError if call.status != "SUCCESS" - Phase 6
        validates compatibility for successful calls only (§16); mapping the
        complete failed/partial-call contract (status/error/provider/request-id)
        is deferred to the future real Gateway/Cost Tracker phase.
        """
        ...
```

**Binding rules:**

- `AIExecutionMapper` MUST NOT hold a database session and MUST NOT perform I/O — a pure mapping function,
  exactly like `PromptRepository.resolve()` is a pure lookup.
- `CapabilityExecutor` MAY call `AIExecutionMapper.to_execution_row()` to validate that a `SUCCESS`-status
  `CapabilityCall` maps cleanly, but MUST NOT persist the result anywhere in Phase 6.
- `AIExecutionMapper` existing in Phase 6 MUST NOT be read as evidence that Phase 6 persists `AIExecution`
  rows — it validates compatibility only (§16).
- The `capability` field's alias resolution (e.g. `"engagement"` → `AICapability.INTELLIGENCE`) MUST go
  through the single centralized mapping named in §15 — `AIExecutionMapper` MUST NOT hardcode its own copy
  of that alias.

---

## 11. Component Boundaries

| Boundary | Direction | Mediated by | Notes |
|---|---|---|---|
| Workflow ↔ Capability | Workflow → Capability only, indirectly | `StepExecutor` Protocol, implemented by `CapabilityExecutor` | Workflow never learns a `Capability` exists. |
| Capability ↔ LLM Gateway | Capability → Gateway only | `LLMGateway` Protocol, injected | Gateway never learns which `Capability` called it. |
| Capability ↔ Prompt Repository | Capability → PromptRepository only | `PromptRepository` Protocol, injected | Read-only; `CapabilityContext` never crosses into `PromptRepository`. |
| Capability ↔ Budget Guard | Capability → BudgetGuard only | `BudgetGuard` Protocol, injected | Pre-flight only; see §9. |
| Capability ↔ Workflow's execution state | Capability reads only | `WorkflowExecutionStateSnapshot` inside `CapabilityContext.business` | The **one deliberate, named exception** to "Capability knows nothing about Workflow" — required by P4 (capabilities chain only through persisted state). One-directional and read-only; Workflow never reads anything Capability-shaped. |
| CapabilityExecutor ↔ Persistence | CapabilityExecutor → DB only | Direct session use (task/event fetch), `CostTracker` (AIExecution write) | Only component on the AI path holding a live DB session. |
| Cost Tracker ↔ AIExecution | CostTracker → DB only | Direct write, invoked by `CapabilityExecutor` | No other component writes `AIExecution` rows. |
| Cost Tracker ↔ Budget Guard | CostTracker → ledger, BudgetGuard reads ledger | Shared, `CostTracker`-owned spend ledger | The only coupling between the two; strictly read (`BudgetGuard`) vs. write (`CostTracker`), never both directions. |

**No hidden coupling remains** beyond the one named exception above (Capability reading
`WorkflowExecutionStateSnapshot`), which is required by P4 and is now explicit rather than implicit.

**Phase 6 note (Amendment B, §16):** the "CapabilityExecutor ↔ Persistence" and "Cost Tracker ↔
AIExecution" rows above describe the permanent target architecture. In Phase 6, `CapabilityExecutor` holds
a live DB session only for the `EditorialTask`/`NewsEvent` read-fetch — it performs no `AIExecution` write,
and `CostTracker` performs no write either, since neither is invoked for that purpose in this phase.

---

## 12. Extension Rules

- **Adding a new capability:** write a `Capability` implementation plus a `CapabilityDefinition`; register
  both in `capabilities/registry.py`'s `build_registry()` before `seal()`; add the matching `AICapability`
  enum value via migration if it will persist `AIExecution` rows (§10). Requires **zero** changes to
  `workflows/`, `LLMGateway`, `PromptRepository`, `BudgetGuard`, or `CostTracker`.
- **Adding a new provider:** write a provider adapter implementing `LLMGateway` (or a component the real
  Gateway delegates to per-provider); register it in the Gateway's own provider-routing table. Requires
  **zero** changes to any `Capability`, to `CapabilityContext`/`CapabilityResult`, or to any Gateway
  request/response type in §7 — the whole point of the provider-neutral contract is that no provider
  addition ever touches it.
- **Adding a new prompt package:** add versioned prompt files under `prompts/`; run them through the Prompt
  Publisher's validation/publish step (§8, component not yet built). Requires zero changes to
  `PromptRepository`'s contract or to any `Capability` that already resolves prompts by name.
- **Adding a new model** (new model string from an existing provider): no code change anywhere in this
  architecture — `preferred_model` is an opaque string; the Gateway's provider adapter is the only place
  a model identifier is interpreted, and adding a supported model there requires no contract change.

None of the four extension paths above require touching `WorkflowRunner`, `WorkflowRegistry`,
`CapabilityRegistry`'s method signatures, or any Protocol defined in this document.

---

## 13. Explicit Non-Goals

The following are intentionally **not** solved by this contract and MUST NOT be designed into Phase 6
implementation work under this document. Each belongs to a later, separately-approved phase:

- **Memory** (long-term or cross-execution capability memory beyond `EditorialTask.workflow.step_results`).
- **RAG** (retrieval-augmented generation pipelines; `embed`/`rerank` exist in the Gateway contract as
  primitives, but no retrieval orchestration is designed here).
- **Agent orchestration** / multi-agent coordination beyond the existing `MAX_AGENT_ROUNDS` Workflow-level
  ceiling.
- **Long-running or continuous monitoring capabilities** (Q10.3 of the architecture review) — a capability
  with no discrete start/end does not fit `Capability.execute() -> CapabilityResult` and MUST NOT be forced
  into it; it belongs outside the Capability Framework entirely, as a scheduled process that creates
  discrete `EditorialTask`s.
- **Background autonomous agents** operating without a Workflow-issued task.
- **Plugin marketplace / installable third-party capabilities** — §4/§6/§10 name the specific,
  currently-accepted gaps (namespacing, closed `AICapability` enum) that block this; none are closed here.
- **Distributed execution** of a single capability across multiple processes/machines.
- **Human-in-the-loop / suspend-resume approval workflows** (Q10.2 of the architecture review) — a
  capability that suspends for arbitrary wall-clock time cannot fit inside `Capability.execute()`'s bounded
  async call or `WorkflowRunner`'s per-step timeout; this requires a new Workflow step type, not an
  extension of `Capability`.
- **Multi-event capabilities** (digest/clustering capabilities spanning many `NewsEvent`s in one execution,
  Q10.1 of the architecture review) — blocked by `EditorialTask.event_id` being a single foreign key
  (already correctly deferred at the `DAILY_DIGEST` Workflow level in Phase 5); `CapabilityContext.business.news_event`
  remains singular in this document for the same reason.
- **Streaming to a live UI** — `generate_stream`/`GenerateChunk` exist in the Gateway contract as a
  primitive (§7) but no consumer, transport, or UI-facing streaming path is designed here.

---

## 14. Canonical Rules

These rules are mandatory for all Phase 6+ implementation and are the checklist future code review
validates against.

1. No file under `capabilities/` or `integrations/llm_gateway/` imports a provider SDK, directly or
   transitively.
2. No file under `workflows/` imports anything from `capabilities/`, `integrations/llm_gateway/`,
   `integrations/prompts/`, or a provider SDK.
3. `Capability.execute(context: CapabilityContext) -> CapabilityResult` is the only method the `Capability`
   Protocol defines. `CapabilityContext` is composed of `business` / `runtime` / `execution` sub-models
   (§3) — no flat top-level fields are added back.
4. `CapabilityResult` exposes `calls: list[CapabilityCall]` and no top-level `model_used` / `prompt_name` /
   `prompt_version` / `usage` field. An empty `calls` list is valid.
5. `CapabilityRegistry` and `WorkflowRegistry` remain sealed-after-boot, explicit-registration-only,
   single-version-per-name. No dynamic discovery is added without a separate, dedicated approval.
6. `LLMGateway`'s request/response types (§7) never gain a provider-specific field. New capabilities
   (moderation, reranking, multimodal, etc.) are expressed as new methods or new optional fields on
   existing provider-neutral types — never as a provider-shaped escape hatch.
7. `PromptRepository` exposes `resolve()` only. No mutating method is ever added to it; prompt lifecycle
   lives in a separate, not-yet-built Prompt Publisher.
8. Budget checking (`BudgetGuard`, pre-flight, read-only) and cost recording (`CostTracker`, post-hoc,
   write-only) remain two separate components. Neither is merged into the other.
9. `CapabilityExecutor` is the only component that translates `CapabilityError` subtypes into
   `workflows.errors` types. In Phase 6, `CapabilityExecutor` is the only AI-path component holding a live
   database session, and that session is used only for the `EditorialTask`/`NewsEvent` read-fetch — it MUST
   NOT write an `AIExecution` row (Amendment B, §16); `CostTracker`'s write path is a Protocol only in
   Phase 6, never invoked for a real write.
10. The `"engagement"` → `AICapability.INTELLIGENCE` mapping is a temporary persistence alias only
    (Amendment A, §15) — not a redefinition of Engagement as Intelligence, centralized in one mapping, never
    hardcoded independently by any adapter/executor/capability, and reconsidered before any real Engagement
    Capability is implemented. No migration is introduced in Phase 6 to resolve it.
11. Every new `Capability` added at 8, 20, or 50 capabilities registers through the same
    `CapabilityRegistry.register()` call used today — no capability count threshold triggers a different
    registration mechanism without a separate architecture decision.
12. Nothing in §13's non-goal list is implemented as a side effect of building an in-scope Phase 6
    capability. A capability that appears to require a non-goal (e.g. multi-event input, suspend/resume)
    is out of scope until the relevant non-goal is separately resolved.
13. Phase 6 MUST NOT persist real `AIExecution` rows (Amendment B, §16). `CapabilityExecutor` validates the
    `AIExecutionMapper` (§10.1) mapping boundary against `SUCCESS`-status `CapabilityCall`s only; actual
    per-call persistence — for both successful and failed/partial calls — is deferred to the future real
    Gateway/Cost Tracker phase. Runtime validation in Phase 6 MUST use fake capabilities and fake gateway
    contracts only, and MUST prove zero `AIExecution` rows are created.

---

## 15. Amendment A — Engagement Persistence Alias (Binding)

**Status: approved amendment, binding on this contract exactly as §§1–14 above.**

The mapping `"engagement" -> AICapability.INTELLIGENCE` (§10) is approved **only** as a temporary
persistence alias, not as a permanent taxonomy decision. This amendment exists because the Workflow step
name `"engagement"` (`workflows/definitions/news_analysis.py`, already shipped in Phase 5) has no
corresponding value in the already-migrated `AICapability` enum, and Phase 6 introduces no migration to add
one.

**Binding conditions, all of which apply simultaneously:**

1. This alias does **not** redefine Engagement as Intelligence. Engagement and Intelligence remain distinct
   Capabilities conceptually; the alias is a persistence-layer stopgap, not a statement that the two are
   the same thing.
2. It exists solely because the current, already-migrated `AICapability` enum has no `ENGAGEMENT` value —
   nothing more. It is a workaround for a schema gap, not a design preference.
3. It MUST be reconsidered before any real Engagement Capability is implemented. Whoever implements a real
   Engagement Capability MUST revisit this alias as a first step, not inherit it silently.
4. It MUST live in exactly one centralized mapping — a single lookup table or function, referenced by name
   from every call site that needs it. There is exactly one source of truth for this mapping.
5. No adapter, `CapabilityExecutor`, or `Capability` implementation may hardcode this alias independently.
   Any code that needs to know what `"engagement"` persists as MUST call the centralized mapping, never
   duplicate the literal `AICapability.INTELLIGENCE` value inline.
6. No migration is introduced in Phase 6 as a result of this amendment.

This amendment supersedes the original §10/§14 phrasing ("canonical, binding mapping — not an open option")
to the extent that phrasing implied a permanent taxonomy decision. The mapping is still binding and still
canonical *as an alias* — but is now explicitly conditional on points 1–6 above, and §10/§14 have been
edited in place to reflect that.

---

## 16. Amendment B — AIExecution Persistence Deferral (Binding)

**Status: approved amendment, binding on this contract exactly as §§1–14 above.**

Phase 6 MUST NOT claim, imply, or implement that it writes one `AIExecution` row per `CapabilityCall`. The
current `AIExecution` model (§10) cannot fully represent every failed or partial call, because it provides
no complete call-status/error/provider/request-id contract — only `model`, `prompt_version`, token counts,
`cost`, and a `response` JSON blob. Persisting real rows against this schema now would either silently drop
information (a failed call with no `model_used`, no request id, no structured error) or force a shape the
schema was never reviewed against.

**Phase 6 therefore MUST:**

1. Define `CapabilityCall` (§4) and its complete in-memory contract. This document already does this in
   §4; no further change to that section is required by this amendment.
2. Define a provider-neutral `AIExecutionMapper` Protocol (§10.1) as the mapping boundary between
   `CapabilityCall` and the `AIExecution` row shape — a pure function, no I/O, no database session.
3. Validate compatibility for **successful** calls only (`CapabilityCall.status == "SUCCESS"`). Mapping the
   complete failed/partial-call contract (status, error, provider, request-id) is explicitly deferred,
   because that contract does not exist yet in a form the current `AIExecution` schema was designed
   against.
4. **Not** persist real `AIExecution` rows. No component built or invoked in Phase 6 writes to the
   `ai_executions` table.
5. **Not** create a migration.
6. Defer actual per-call persistence — for both successful and failed calls — to the future real
   Gateway/Cost Tracker phase, where the `AIExecution` schema requirements can be reviewed against real
   provider responses (real error shapes, real request IDs, real partial-failure modes) instead of being
   guessed at now.

**Consequently, `CapabilityExecutor` in Phase 6 MUST NOT write `AIExecution` rows.** This supersedes the
original §5 rule 7 text ("persist one `AIExecution` row per entry in `result.calls`"), which has been struck
and replaced in place. `CostTracker`'s write path (§9) is defined as a Protocol but is never invoked by
`CapabilityExecutor` in Phase 6.

**Runtime validation MUST use fake capabilities and fake gateway contracts only.** No real `AIExecution`
persistence is exercised, validated, or claimed to work end-to-end by any Phase 6 test or runtime
validation script. Runtime validation proves `CapabilityExecutor` is a drop-in `StepExecutor` and that zero
`AIExecution` rows are created — not that persistence works.

---

*End of specification.*
