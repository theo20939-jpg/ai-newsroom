# Phase 7 Planning Report — AI Integration Layer

No code, no migrations, no changes to Phase 1–6. Analysis and design only. Nothing under `capabilities/`,
`schemas/`, `integrations/llm_gateway/`, `integrations/prompts/`, `services/`, `workflows/`, or
`database/` is modified by producing this document.

**Relationship to prior phases:** Phase 6 (`docs/phase6_architecture_contract.md`) is the binding, approved
contract for the Capability Framework, `LLMGateway` Protocol, `PromptRepository` Protocol, `BudgetGuard`
Protocol, `CostTracker` Protocol, and `AIExecutionMapper` Protocol. This document does not redesign any of
those — every one of Phase 6's ten principles (P1–P10), its forbidden-dependency table, and its canonical
rules (§14) are treated as fixed inputs. Where this document's design touches a Phase 6 boundary closely
enough that a real gap surfaces (§17.5, §22), it is flagged explicitly as a proposed **amendment**, not a
silent redesign, exactly as Amendments A and B were handled in Phase 6 itself.

**Scope of Phase 7:** everything that sits *underneath* `LLMGateway` — the concrete architecture that lets
a `Capability` call the already-approved `LLMGateway` Protocol and have that call actually reach one of
seven providers (OpenAI, Anthropic, Gemini, OpenRouter, Ollama, DeepSeek, Grok), with routing, fallback,
retry, streaming, structured output, tool calling, vision, embeddings, moderation, caching, rate limiting,
and cost accounting all working correctly at 10 providers / 100 models / 50 capabilities / millions of
requests. **No provider SDK is written or wired up in this phase.** Every provider named above is designed
against identically — none gets special-cased in this document.

Sources read directly for this report: `docs/phase6_architecture_contract.md` (binding), `docs/phase6_capability_framework_planning.md`,
`docs/phase6_architecture_review.md`, `docs/07_AI_Architecture_Document.md` §7–§9, `core/config.py`,
`.env.example`, `services/adapter_registry.py` and `services/adapter_keys.py` (explicit-registration
precedent), `capabilities/errors.py`, `capabilities/registry.py`, `tests/fakes/fake_gateway.py`,
`schemas/workflow.py` (`WorkflowRetryPolicy`), `database/models/ai_execution.py` (`AICapability` enum).

---

## 1. Governing principle: everything in this document lives *below* the `LLMGateway` boundary

Phase 6 contract §4 states a binding rule that shapes this entire design: **"One `CapabilityCall` MUST
correspond to exactly one `LLMGateway` method invocation — never a batch of several."** A `Capability`
calls `LLMGateway.generate()` once and gets back one `GenerateResponse`. It has no visibility into how many
HTTP requests, providers, or retries happened to produce that one response.

This means: **routing, fallback, retry, rate limiting, and response caching are entirely internal to the
concrete `LLMGateway` implementation.** They are invisible above the Gateway boundary by construction, not
by convention. A `Capability` never learns that its `generate()` call tried OpenAI, got rate-limited, and
succeeded on the second attempt against Anthropic — it only ever sees one `GenerateResponse` (or one
raised error) and, downstream, one `CapabilityCall`.

**Consequence for naming:** this document calls the concrete, composing implementation of `LLMGateway` the
**Routing Gateway** (working name, not binding — final naming is a Contract-phase decision). Everything
this document designs — Provider Registry, Model Registry, Router, Fallback Chain, Retry Policy, Rate
Limiter, response Cache — is private machinery *inside* the Routing Gateway. None of it is a new public
Protocol a `Capability` depends on, **except** two deliberate, named exceptions: the Tool Executor (§11) and
optionally a moderation composition pattern (§14) — both are things a `Capability` *chooses* to call
explicitly, not things the Gateway does silently on its behalf.

---

## 2. Dependency diagram

```
                                Capability
                                    |
              (injected: LLMGateway, PromptRepository, BudgetGuard, [ToolExecutor])
                                    |
                                    v
                            LLMGateway Protocol                 <-- Phase 6 boundary, unchanged
                                    |
                                    v
   +--------------------------------------------------------------------------+
   |                          Routing Gateway (Phase 7)                       |
   |                                                                          |
   |   GenerateRequest                                                       |
   |        |                                                                |
   |        v                                                                |
   |   Rate Limiter  --(reject: RateLimitExceededError)-->  raised upward    |
   |        |                                                                |
   |        v                                                                |
   |   Response Cache (opt-in) --(hit)--> return cached GenerateResponse     |
   |        |  (miss)                                                       |
   |        v                                                                |
   |   Router                                                                |
   |     - queries Model Registry (capability-flag filter, availability)     |
   |     - queries Provider Registry (is provider enabled/credentialed)      |
   |     - applies RoutingPolicy (best_quality / lowest_cost / fastest /     |
   |       reasoning), advisory preferred_model/preferred_provider hints     |
   |     -> ordered candidate list [(provider_id, model_id), ...]            |
   |        |                                                                |
   |        v                                                                |
   |   Fallback Chain  (bounded attempts, Retry Policy per attempt)          |
   |        |                                                                |
   |        v                                                                |
   |   Provider Adapter (= one LLMGateway implementation, provider-scoped)   |
   |        |                                                                |
   +--------|------------------------------------------------------------------+
            v
      Provider SDK (openai / anthropic / google-genai / requests-to-OpenRouter /
                     ollama-client / deepseek SDK / xai SDK)
            |
            v
      Provider HTTP API
```

**Registries consulted by the Router, both sealed-after-boot, both file/module-sourced (never a database
table — see §18):**

```
Provider Registry: provider_id (str) -> (ProviderDescriptor, ProviderAdapter instance)
Model Registry:    model_id (str)    -> ModelDescriptor { provider_id, capability flags, pricing, context window, availability }
```

**No file under `capabilities/` or `workflows/` gains a new import as a result of this document.** The only
new dependency edges this phase introduces are entirely inside `integrations/llm_gateway/` (the Routing
Gateway depending on its own Provider Registry/Model Registry/Router/Fallback Chain/Rate
Limiter/Cache — all new, all provider-agnostic) and, for §11, a new `ToolExecutor` Protocol a `Capability`
may optionally depend on, parallel to `LLMGateway`/`PromptRepository`/`BudgetGuard`.

---

## 3. Provider abstraction

**Key design decision: a "provider adapter" is not a new Protocol — it is a provider-scoped implementation
of the already-approved `LLMGateway` Protocol.**

Phase 6 contract §12 already anticipates this: *"Adding a new provider: write a provider adapter
implementing `LLMGateway` (or a component the real Gateway delegates to per-provider)."* Reusing the exact
same Protocol for both "the thing a Capability calls" and "the thing that talks to one specific provider's
SDK" means:

- Zero new request/response types. `GenerateRequest`, `EmbedRequest`, etc. are already provider-neutral by
  construction (§7 of the contract) — a provider adapter's only job is translating this shape to/from the
  provider's wire format.
- The Router's dispatch step is trivial: having picked `(provider_id, model_id)`, it calls
  `provider_adapter.generate(request_with_model_pinned)` — the exact same method signature a `Capability`
  itself would call, one layer up.
- Composition is structurally recursive and requires no special-casing: the Routing Gateway *is* an
  `LLMGateway`; each provider adapter it holds *is also* an `LLMGateway`. A test can point a `Capability` at
  a single `ProviderAdapter` directly (bypassing routing entirely) with zero adapter changes.

```python
# integrations/llm_gateway/providers/base.py — no new Protocol; type alias for clarity at call sites
ProviderAdapter = LLMGateway   # a ProviderAdapter is exactly an LLMGateway, scoped to one provider's SDK

# integrations/llm_gateway/providers/openai_adapter.py  (illustrative — not written this phase)
class OpenAIAdapter:
    """Implements LLMGateway. The ONLY file that imports the `openai` package."""
    def __init__(self, api_key: SecretStr, base_url: str | None = None) -> None: ...
    async def generate(self, request: GenerateRequest) -> GenerateResponse: ...
    def generate_stream(self, request: GenerateRequest) -> AsyncIterator[GenerateChunk]: ...
    async def embed(self, request: EmbedRequest) -> EmbedResponse: ...
    async def classify(self, request: ClassifyRequest) -> ClassifyResponse:
        raise UnsupportedGatewayCapabilityError("openai: classify() not offered as a distinct endpoint")
    async def moderate(self, request: ModerateRequest) -> ModerateResponse: ...
    async def rerank(self, request: RerankRequest) -> RerankResponse:
        raise UnsupportedGatewayCapabilityError("openai: no rerank endpoint")
```

**Binding rule this document proposes (carries into the future Contract):** no file outside
`integrations/llm_gateway/providers/<provider>_adapter.py` may import a provider SDK
(`openai`, `anthropic`, `google.generativeai` / `google-genai`, `ollama`, or an OpenRouter/DeepSeek/Grok
HTTP client library), directly or transitively — this widens Phase 6 canonical rule 1
(`capabilities/`, `integrations/llm_gateway/`) to name the specific subdirectory the seven SDKs are
confined to, now that `integrations/llm_gateway/` itself has internal structure. One file per provider,
each independently swappable, independently testable via the fake-provider harness (§19), independently
deletable without touching any other adapter.

**Provider count is not privileged.** OpenAI/Anthropic/Gemini being "the big three" earns them no special
path through the Router, the Fallback Chain, or the Rate Limiter — every provider is one row in the
Provider Registry and N rows in the Model Registry, full stop. This is what makes "10 providers" (§21) a
non-event architecturally: it's 3 more rows, not a new code path.

---

## 4. Provider Registry

Mirrors the already-established sealed, explicit-registration pattern (`WorkflowRegistry`,
`CapabilityRegistry`, `services/adapter_registry.py`'s `AdapterRegistry`) exactly — no new registration
philosophy invented for Phase 7.

```python
class ProviderDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_id: str                 # "openai" | "anthropic" | "gemini" | "openrouter" |
                                      # "ollama" | "deepseek" | "grok" — opaque string, not an enum
                                      # (adding provider #8 must never require a schema/migration change)
    display_name: str
    requires_credential: bool = True # False for a fully local provider (e.g. Ollama with no API key)
    base_url: str | None = None      # override point for self-hosted / OpenRouter-style proxies


class ProviderRegistry:
    def __init__(self) -> None:
        self._descriptors: dict[str, ProviderDescriptor] = {}
        self._adapters: dict[str, ProviderAdapter] = {}
        self._sealed = False

    def register(self, descriptor: ProviderDescriptor, adapter: ProviderAdapter) -> None:
        # raises ProviderRegistryAlreadySealedError / DuplicateProviderRegistrationError
        ...

    def seal(self) -> None: ...

    def resolve(self, provider_id: str) -> ProviderAdapter:
        # raises UnknownProviderError
        ...

    def is_enabled(self, provider_id: str) -> bool:
        # a provider is registered *only if* enabled + credentialed at boot (see §18) -
        # this method exists so the Router can filter without a try/except UnknownProviderError
        ...
```

**How providers register:** at process start, `build_provider_registry(settings: Settings) -> ProviderRegistry`
iterates a fixed, explicit list of known provider factories (seven today), constructs each adapter **only
if** its feature flag is enabled and its required credential is present (§18), registers it, then seals.
An explicitly disabled or uncredentialed provider is simply **absent** from the registry — never registered
with a broken/unusable adapter. This keeps `resolve()` total-for-registered-providers and lets the Router
use `is_enabled()` as a cheap pre-filter, consistent with P9 (no dynamic discovery — the set of active
providers is fixed for the life of the process).

**How providers are selected:** the Provider Registry itself never selects anything — selection is the
Router's job (§6), informed by the Model Registry. The Provider Registry answers exactly one question:
*"given a provider_id, hand me the adapter (or tell me it doesn't exist/isn't enabled)."*

**How providers expose capabilities:** a provider does **not** self-report capabilities at runtime (no
"call the API and ask what models/features it supports" — that would violate P9 and make boot
non-deterministic, network-dependent, and untestable offline). Capability exposure is entirely the Model
Registry's job (§5) — a provider's capabilities are exactly the union of its registered models' capability
flags. `ProviderAdapter.generate()` etc. raising `UnsupportedGatewayCapabilityError` for a method it can't
back (already an approved Phase 6 rule) is the only *runtime* signal of a capability gap, and it should be
rare — most gaps should already be knowable statically from the Model Registry so the Router never routes
into a call destined to fail this way.

---

## 5. Model Registry

```python
class ModelDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str                    # "gpt-5" | "gpt-5-mini" | "claude-opus-4-8" | "claude-sonnet-5" |
                                      # "gemini-2.5-pro" | "gemini-2.5-flash" | "deepseek-chat" | ... -
                                      # opaque string, never validated against a closed enum anywhere
    provider_id: str                 # FK into Provider Registry, in-memory only - not a DB constraint
    display_name: str

    context_window_tokens: int = Field(ge=1)
    max_output_tokens: int | None = None

    supports_tools: bool = False
    supports_streaming: bool = False
    supports_vision: bool = False
    supports_structured_output: bool = False
    supports_embeddings: bool = False       # True only for embedding-purpose models
    reasoning_tier: Literal["none", "standard", "extended"] = "none"  # drives the "reasoning" routing objective (§6)

    input_price_per_million: Decimal | None = None    # None only for a genuinely free local model
    output_price_per_million: Decimal | None = None
    pricing_currency: str = "USD"

    availability: Literal["ga", "beta", "deprecated", "unavailable"] = "ga"
    # "deprecated": Router still selects it if explicitly preferred_model'd, but never a default candidate
    # "unavailable": excluded from every routing decision, kept in the registry only for audit/log readability
```

**How models are described:** entirely as data, in a single explicit, versioned, code-reviewed source
(§18) — never inferred from a provider's live model-listing endpoint. This mirrors `PromptRepository`'s
file-based, non-database ownership of prompt content (Phase 6 contract §8) and directly avoids the closed
`AICapability`-enum trap the Phase 6 review (Q6) flagged for *capabilities*: **`model_id` is a bare string
end to end, in the Model Registry, in `GenerateRequest.preferred_model`, and in `CapabilityCall.model_used`
— it is never backed by a database enum, so adding model #101 is a one-line registry entry, never a
migration.**

**Model Registry, like Provider Registry, is sealed-after-boot, dict-keyed, O(1) lookup:**

```python
class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ModelDescriptor] = {}
        self._by_provider: dict[str, list[str]] = defaultdict(list)   # provider_id -> [model_id, ...]
        self._sealed = False

    def register(self, model: ModelDescriptor) -> None: ...   # raises if sealed / duplicate model_id
    def seal(self) -> None: ...
    def resolve(self, model_id: str) -> ModelDescriptor: ...  # raises UnknownModelError
    def filter(self, *, requires_tools: bool = False, requires_vision: bool = False,
               requires_streaming: bool = False, requires_structured_output: bool = False,
               availability: set[Literal["ga", "beta"]] | None = None) -> list[ModelDescriptor]:
        """Pure in-memory filter - the Router's primary query. No I/O."""
        ...
```

**Decoupling business logic from providers:** nothing above `ModelRegistry.filter()` ever branches on
`provider_id == "openai"` or similar. Every routing, fallback, and rate-limiting decision in this document
is expressed purely in terms of `ModelDescriptor` fields (capability flags, price, availability,
`reasoning_tier`) — never a provider name. A `Capability` never sees a `ModelDescriptor` at all; it only
ever supplies advisory hints (`preferred_model`, `preferred_provider`) on `GenerateRequest`/`ExecutionContext`,
exactly as already contracted in Phase 6.

**Pricing — a real coupling with `CostTracker`, flagged for resolution (§17.5):** Phase 6 contract §9 says
`CostTracker` "computes `Decimal` cost from **its own** model-price table." This document's `ModelDescriptor`
also needs pricing, for the `lowest_cost` routing objective (§6) — a model can't be ranked by cost without
knowing its price. Maintaining two independently-updated price tables (one in Model Registry, one inside
`CostTracker`) is a drift risk with real financial consequences (routing decisions and billed cost using
different numbers for the same model). **Recommendation (Open Question 1, §25): the Model Registry becomes
the single source of truth for pricing; `CostTracker` reads `ModelDescriptor.input_price_per_million` /
`output_price_per_million` via the Model Registry rather than owning a separate table.** This does not
change *who writes cost* (still exclusively `CostTracker`, per Phase 6 P5) — only *where the price number
comes from*. Proposed as an amendment to Phase 6 contract §9's wording, not a redesign of `CostTracker`'s
role.

---

## 6. Routing

```python
class RoutingObjective(str, Enum):
    BEST_QUALITY = "best_quality"   # highest-capability model among candidates (provider-agnostic quality tier)
    LOWEST_COST = "lowest_cost"     # cheapest model satisfying hard requirements
    FASTEST = "fastest"             # lowest observed p50 latency (see §6.1 - requires runtime telemetry)
    REASONING = "reasoning"         # prefer reasoning_tier == "extended"


class RoutingCriteria(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gateway_method: Literal["generate", "generate_stream", "embed", "classify", "moderate", "rerank"]
    capability_name: str             # for rate limiting (§16) and audit logging - opaque, no branching on it
    priority: TaskPriority           # already exists on EditorialTask/CapabilityContext.runtime

    requires_tools: bool = False
    requires_vision: bool = False
    requires_streaming: bool = False
    requires_structured_output: bool = False

    preferred_model: str | None = None     # advisory - Phase 6 rule: never a hard requirement
    preferred_provider: str | None = None  # advisory

    objective: RoutingObjective = RoutingObjective.BEST_QUALITY
    cost_ceiling: Decimal | None = None    # optional hard cap - see §7's fallback-cost tension


class RoutingPolicy(Protocol):
    def rank(self, candidates: list[ModelDescriptor], criteria: RoutingCriteria) -> list[ModelDescriptor]:
        """Return candidates ordered best-first. Pure function - no I/O, no provider calls."""
        ...
```

**Routing algorithm (inside the Routing Gateway, before any provider is touched):**

1. **Hard filter** — `ModelRegistry.filter(requires_tools=..., requires_vision=..., ..., availability={"ga"})`
   removes every model that cannot structurally satisfy the request. This is not a ranking step; a model
   missing `supports_vision` when `requires_vision=True` is never a candidate, regardless of objective.
2. **Provider-enabled filter** — drop any candidate whose `provider_id` is not `ProviderRegistry.is_enabled()`.
3. **Preferred-hint reordering** — if `preferred_model` (or `preferred_provider`) names a surviving
   candidate, move it to the front. This is advisory, not a filter — per Phase 6 contract §7's binding rule
   ("`preferred_model`/`preferred_provider` are advisory only"), an unavailable/incapable preferred model is
   silently skipped, never an error.
4. **Objective ranking** — the remaining candidates are handed to the registered `RoutingPolicy` for
   `criteria.objective` (§6.2), which sorts by its own metric (price, quality tier, latency, reasoning tier).
5. **Result: an ordered candidate list.** This *is* the Fallback Chain's attempt order (§7) — routing and
   fallback share one data structure; there is no separate "pick one, then separately compute a fallback
   list" step.

### 6.1 "Fastest" and "best_quality" need a metric, not just a label

`lowest_cost` and `reasoning` are answerable purely from static `ModelDescriptor` fields. `fastest` and
`best_quality` are not — "fastest" requires *observed* latency (a static "provider X is fast" label goes
stale the moment a provider degrades), and "best_quality" requires a quality ranking that isn't a single
scalar on `ModelDescriptor` today. Two honest options, not resolved in this document:

- **Static quality tier** — add a `quality_tier: int` field to `ModelDescriptor` (curated, code-reviewed,
  updated manually as models are added/retired) — cheap, deterministic, but goes stale without maintenance
  discipline, same risk class as pricing (§5).
- **Latency-informed `fastest`** — the Routing Gateway maintains a small in-memory (or Redis-backed, for
  cross-process consistency at scale — see §21) rolling p50-latency-per-model sample, updated after every
  real call, consulted only by the `fastest` objective. This is the only routing objective in this document
  that requires runtime state rather than pure static-data ranking — flagged as added complexity, not
  assumed away.

**Recommendation:** ship `quality_tier` as a static field now (cheap, matches every other `ModelDescriptor`
field's ownership model); defer latency-informed `fastest` to when a concrete capability actually needs it
— until then, `fastest` degrades gracefully to "cheapest among the top quality tier," which is a reasonable
default, not a broken one.

### 6.2 Extensibility

`RoutingObjective` is a fixed enum above for concreteness, but the real extension point is a **Routing
Policy Registry** — the same explicit-registration-then-seal pattern as every other registry in this
system:

```python
class RoutingPolicyRegistry:
    def register(self, objective: str, policy: RoutingPolicy) -> None: ...
    def seal(self) -> None: ...
    def resolve(self, objective: str) -> RoutingPolicy: ...  # raises UnknownRoutingObjectiveError
```

Adding a new objective (e.g. "prefer\_provider\_diversity", "cheapest\_with\_min\_quality\_tier") is a new
`RoutingPolicy` implementation registered here — zero changes to the Router itself, to `RoutingCriteria`'s
shape (beyond widening the string, not the enum, if this is adopted), or to any `Capability`. This is the
same extensibility shape Phase 6 contract §12 already promises for capabilities and providers.

---

## 7. Fallback strategy

The Fallback Chain consumes the Router's ordered candidate list and the failure taxonomy below. It is
**entirely internal to the Routing Gateway** (§1) — a `Capability` calls `generate()` once; the Fallback
Chain may make several real HTTP attempts before that one call returns.

| Trigger | Fallback behavior |
|---|---|
| Provider auth failure (bad/expired credential) | Skip to next candidate immediately. Also mark this provider `unhealthy` for the remainder of the process (in-memory flag, not persisted) so subsequent calls don't retry a permanently broken credential — but do **not** deregister it (registries are sealed; a restart is required to actually fix a bad credential, consistent with P9). |
| Model unavailable (provider returns "model not found" / decommissioned) | Skip to next candidate. Log at WARNING — this indicates the Model Registry is stale (§18) and needs a data update, not a code fix. |
| Rate limited (429 / provider-specific equivalent) | Skip to next candidate immediately for *this* call. Independently, the Rate Limiter (§16) should already have prevented most of these — a 429 reaching the Fallback Chain at all indicates the Rate Limiter's local view of provider capacity is stale/wrong, worth a metric, not a bug by itself (external actors share provider capacity in ways this system can't fully predict). |
| Timeout | Skip to next candidate. The provider-adapter-level HTTP timeout is a *fourth*, innermost timeout boundary, nested inside the three already established by Phase 6 contract §5 (workflow / step / capability-internal) — see §8. |
| Moderation block (provider refuses to generate due to content policy) | **Do NOT fall back to a different model for the same input.** A different provider is very unlikely to have a materially different content policy for genuinely disallowed content, and silently retrying disallowed content against provider after provider is the wrong default behavior for a system that also has its own `moderate()` primitive (§14). Surface immediately as `PermanentCapabilityError`-mapped (a Gateway-level `ContentModerationBlockedError`), no further candidates tried. |
| Budget exceeded mid-fallback | **Should not happen** under normal operation — `BudgetGuard` runs once, pre-flight, before `LLMGateway.generate()` is even called (Phase 6 contract §9's fixed pipeline order). But an *internal* fallback to a pricier model could silently exceed what `BudgetGuard` authorized for the originally-intended model. Resolved by constraint, not by a runtime budget re-check (§7.1). |
| Structured-output / schema mismatch | Not a *provider* failure — handled by the schema-retry loop (§10), one layer up from the Fallback Chain, against the *same* candidate first, before falling back to a different model. |

**Bounded attempts, always.** `max_fallback_attempts` (default: 3, configurable per `RoutingCriteria` or a
global Gateway setting) caps how many candidates the Fallback Chain will try, regardless of how many
survived the Router's filter. Exhausting the bound raises `AllProvidersFailedError` (an `LLMGateway`-level
exception the `Capability` maps to `RetryableCapabilityError` or `PermanentCapabilityError` depending on
whether *every* failure in the chain was itself retryable-flavored — see §8's interaction rule).

### 7.1 The fallback-cost tension (real, not hypothetical)

If `Capability` calls `BudgetGuard.check(capability_name, priority, estimated_usage_for_model_A)` and it
passes, then `LLMGateway.generate()` internally falls back from model A to pricier model C, the already-passed
budget check no longer reflects the call actually made. Two resolutions considered:

- **(a) Cost-non-increasing fallback (recommended default).** The Fallback Chain's candidate order, after
  Router ranking, is additionally constrained so no fallback candidate has a materially higher estimated
  cost than the first (preferred) candidate — cheap, purely structural, needs no new cross-layer call.
  `RoutingCriteria.cost_ceiling` (§6) is exactly this constraint made explicit and capability-settable.
- **(b) Re-invoke `BudgetGuard` per fallback attempt.** Rejected as a default: it would require the Routing
  Gateway to hold a `BudgetGuard` dependency, which inverts Phase 6's fixed pipeline direction
  (`Capability → BudgetGuard → LLMGateway`, never `LLMGateway → BudgetGuard`) and turns a pre-flight,
  single-invocation check into a reentrant one — a materially bigger change to Phase 6's contract than this
  document is scoped to propose unilaterally.

**Recommendation: (a).** Flagged as Open Question 2 (§25) since it does constrain what "best_quality
fallback" can do (a much better but pricier model is never used as a silent fallback) — an explicit,
capability-visible `cost_ceiling` override exists for the rare case where that tradeoff is wanted.

---

## 8. Retry policy

**Four independent, nested boundaries now exist end-to-end** (Phase 6 contract §5 already established the
first three; this document adds the fourth, entirely inside the Gateway):

```
WorkflowDefinition.timeout_seconds        (whole workflow)
  -> WorkflowStepDefinition.timeout_seconds  (one step, enforced by WorkflowRunner - Phase 5)
     -> CapabilityConfig.timeout_seconds       (one Capability.execute() call, self-enforced - Phase 6)
        -> provider-adapter HTTP timeout          (one real HTTP attempt - Phase 7, NEW, innermost)
```

**Ownership:**

- **Workflow-level retry** (`WorkflowRetryPolicy.max_attempts`, `schemas/workflow.py`) — owned by
  `WorkflowRunner`, retries an entire step (i.e., a fresh `Capability.execute()` call) on
  `RetryableCapabilityError`. Unchanged by this document.
- **Gateway-internal retry** (NEW, this document) — owned by the Routing Gateway, operates *within* a
  single `LLMGateway.generate()` call, across Fallback Chain candidates (§7) and, optionally, a small number
  of same-candidate retries for a transient per-attempt failure (e.g. one immediate retry on a connection
  reset, before moving to the next candidate) — bounded by a small, fixed `max_same_candidate_retries`
  (recommended default: 1), never a large number, and never for permanent-flavored failures (auth, content
  moderation).

**Backoff.** Gateway-internal retries use short, capped exponential backoff (recommended: base 250ms, cap
2s, full jitter) — deliberately much shorter than `WorkflowRetryPolicy.retry_delay_seconds`, because a
Gateway-internal retry is trying a *different, already-available* candidate (or the same candidate once,
immediately) within the bounds of a single Capability-internal timeout window, not waiting out an external
condition across a whole new step attempt.

**Interaction with Workflow retry — the multiplication risk, named explicitly.** If Workflow retries a step
3 times, and each `Capability.execute()` call lets the Gateway try up to 3 fallback candidates, worst case
is up to 9 real provider HTTP attempts for one logical step — before even counting same-candidate retries.
This is **not a bug**, but it must be a *known, bounded* number, not an accident:

**Binding rule this document proposes:** `WorkflowRetryPolicy.max_attempts × max_fallback_attempts ×
(1 + max_same_candidate_retries)` is the hard ceiling on real provider calls per step, and this product
MUST be treated as a reviewed, visible number (e.g. surfaced in logs/metrics per step), not left as an
emergent property nobody computed. At the recommended defaults (3 × 3 × 2 = 18), this is acceptable; a
future capability author raising any one of these numbers should see the product, not just their own
change.

**Idempotency.** `generate()`/`embed()`/`classify()`/`moderate()`/`rerank()` calls are not required to be
byte-identical on retry (temperature > 0 sampling is expected to vary) — Phase 6's existing rule that
"`Capability.execute()` is called fresh on retry; no partial internal state is preserved" (Phase 6 review
§5, point 2) already covers this at the Capability level, and this document extends the same rule one layer
down: **a Gateway-internal retry/fallback attempt is always a fresh request; nothing about a failed attempt
is reused by the next one.** This is safe for pure-generation calls. **Tool-calling loops are the one place
this safety doesn't automatically hold** (§11) — a tool with a side effect (e.g. "send an email",
"create a record") executed once, followed by a Gateway-level retry of the *generate* call that requested
it, must not re-execute the tool. This is named as a Tool Executor responsibility, not a Gateway one (§11),
because the Gateway has no visibility into tool semantics at all — it only ever sees `ToolCall`/`ToolDefinition`
as opaque data.

---

## 9. Streaming architecture

`generate_stream(request) -> AsyncIterator[GenerateChunk]` already exists in the Phase 6 `LLMGateway`
Protocol contract (§7) — this document designs how it fits without breaking synchronous capabilities, not a
new contract.

**Does not touch synchronous capabilities at all.** `generate_stream` is a separate method from `generate`
— a `Capability` that never calls it is entirely unaffected; nothing about adding streaming support to the
Routing Gateway changes `generate()`'s behavior, return type, or timing characteristics for any existing or
future non-streaming capability.

**Provider-adapter obligation:** every `ProviderAdapter` MUST implement `generate_stream` by translating the
provider's native streaming wire format (SSE, chunked JSON, or provider-SDK stream object) into
`GenerateChunk` — the same provider-neutral shape regardless of provider. A provider with no streaming
support raises `UnsupportedGatewayCapabilityError`, exactly as an unsupported `classify`/`moderate` does
today.

**Routing Gateway obligation:** `generate_stream` goes through the **same** Router + hard-filter step as
`generate` (`requires_streaming=True` added to `RoutingCriteria` — a candidate lacking
`supports_streaming` is filtered out before the first chunk is ever requested), but **fallback across
providers mid-stream is explicitly out of scope for Phase 7.** Once the first chunk has been emitted to the
caller, switching providers mid-stream would require either buffering everything so far (defeating the
purpose of streaming) or handing the caller a discontinuous stream (silently wrong). **Rule: if a stream
fails after emitting at least one non-final chunk, the Gateway MUST raise (never fall back) — the caller
sees a failed `generate_stream` call, same as any other retryable failure, and Workflow-level retry (a fresh
`Capability.execute()`) is the correct recovery path, not an in-flight Gateway-internal fallback.** Fallback
*before* the first chunk (a connection failure before any data arrives) is allowed and behaves like `generate`'s
Fallback Chain.

**How a streamed call becomes one `CapabilityCall`:** a `Capability` that consumes `generate_stream`
accumulates chunks itself (text concatenation, final `usage` from the last chunk per
`GenerateChunk.is_final`/`usage` — already contracted) and constructs exactly one `CapabilityCall` from the
completed stream, identical in shape to a non-streamed call's record — `gateway_method: "generate_stream"`
already exists as a valid `CapabilityCall.gateway_method` literal (Phase 6 contract §4). No schema change
required here; this section only documents the *behavior*, which the existing contract already accommodates.

**Non-goal, restated from Phase 6 §13:** streaming to a live UI (a transport from `generate_stream` to an
actual user-facing surface) remains explicitly out of scope — this section designs `generate_stream` as a
Gateway-internal primitive a `Capability` may consume, not an end-to-end UI feature.

---

## 10. Structured outputs

Phase 6's `GenerateRequest` already carries `response_mode: Literal["text", "json_schema"]` and
`response_schema: dict[str, Any] | None` (§7 of the contract). This document designs the retry-on-mismatch
loop and clarifies validation ownership — no new fields.

**Two independent layers of "structured," not to be confused:**

1. **Provider-native JSON mode** — when `response_mode == "json_schema"`, each `ProviderAdapter` MUST use
   the provider's native structured-output mechanism if one exists (OpenAI/Gemini JSON schema mode,
   Anthropic tool-forced JSON, etc.) rather than a bare "please respond in JSON" prompt instruction — this
   is a provider-adapter implementation obligation, invisible above the Gateway boundary, and explicitly
   **not** something the Router or Fallback Chain reasons about (a candidate lacking native JSON mode is
   filtered by `requires_structured_output` in `ModelDescriptor.supports_structured_output`, same as any
   other hard capability requirement).
2. **`Capability`-side Pydantic validation against the prompt's `output_schema`** — this is `Capability`'s
   job, not the Gateway's, per Phase 6 contract P10 ("Structured output only") and §8 (`RenderedPrompt.output_schema`).
   The Gateway getting a syntactically valid JSON object back from the provider does not guarantee it
   matches the *specific* schema a `Capability`'s prompt declared — provider JSON mode typically only
   guarantees "valid JSON," not "matches this exact Pydantic model."

**Retry-on-schema-mismatch — owned by `Capability`, not the Gateway, bounded and small.** When
`GenerateResponse.structured_output` fails the `Capability`'s own Pydantic validation, the recommended
pattern is: **one** immediate re-`generate()` call, with the schema-violation error appended to the prompt's
`TASK`/`RULES` block (a well-established prompting technique — "your last response failed validation with
error X, fix and retry"), against the **same** resolved model (no re-routing) — then, on a second failure,
raise `ValidationCapabilityError` (already an existing, non-retried Phase 6 error type). This keeps the
retry-on-mismatch loop entirely inside `Capability.execute()`, using the already-injected `LLMGateway`
exactly as any other call — **no new Gateway method, no new Protocol.** It also means this retry produces
a **second** `CapabilityCall` entry in `CapabilityResult.calls` (Phase 6 already supports a list, not a
scalar, for exactly this reason — Phase 6 contract §4) — visible, auditable, not hidden.

**Why this doesn't belong inside the Gateway:** the Gateway has no knowledge of what schema a `Capability`
expects (`response_schema` is passed in per-request, but the Gateway doesn't own comparing the *result* to
it beyond what the provider's own JSON-mode validation does) — and per P3/P1, a `Capability` is the only
component that knows its own prompt's `output_schema`. Pushing the retry loop into the Gateway would require
the Gateway to understand `Capability`-specific schemas, which it must not (P3).

---

## 11. Tool calling

**Architecture only, per the brief — no tool implementation.** Phase 6's `LLMGateway` contract already
carries `ToolDefinition`/`ToolCall`/`tools`/`tool_choice`/`tool_calls` (§7) — this section designs how tool
*execution* (actually running the function a `ToolCall` names) integrates with `CapabilityExecutor`,
building directly on the finding already reached in Phase 6's own review (§5 of
`docs/phase6_architecture_review.md`): *"Tool calls sit below `Capability`, between `Capability` and
`LLMGateway`... `CapabilityExecutor` never needs to know tool calls exist, provided `CapabilityResult` can
represent a multi-call execution faithfully."* That finding is already satisfied by Phase 6's shipped
`calls: list[CapabilityCall]` design — this document just names the missing piece: **who runs the tool.**

```python
class ToolExecutionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tool_call: ToolCall              # from LLMGateway's contract - name + arguments, already exists

class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["SUCCESS", "FAILED"]
    output: dict[str, Any] | None    # fed back to the model as the next turn's tool-result message
    error: str | None = None

class ToolExecutor(Protocol):
    """Injected into a Capability exactly like LLMGateway/PromptRepository/BudgetGuard.
    Never called by CapabilityExecutor, LLMGateway, or a ProviderAdapter - those three
    only ever see ToolDefinition/ToolCall as opaque data, per P3/P1."""
    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult: ...
```

**Where the tool-use loop lives: inside `Capability.execute()`, not `CapabilityExecutor`.** A
tool-calling `Capability` implementation does, in its own `execute()` method: call `LLMGateway.generate()`
with `tools=[...]` → if `GenerateResponse.tool_calls` is non-empty, call the injected `ToolExecutor.execute()`
for each → append the results as new `Message`s with `role="tool"` → call `generate()` again → repeat until
`finish_reason == "stop"` or a capability-owned round ceiling is hit (reusing the existing
`MAX_AGENT_ROUNDS` precedent, Phase 6 non-goals §13, already an accepted system-wide ceiling concept — this
document does not introduce a second, competing ceiling). Every `generate()` call in this loop becomes its
own `CapabilityCall` entry — this is exactly the "4 Gateway calls, 2 cheap + 2 synthesis" scenario Phase 6's
own review anticipated when it redesigned `CapabilityResult.calls` as a list (§3 of that review). No further
schema change is needed here either.

**Tool Registry — explicit registration, sealed after boot, same pattern as everything else:**

```python
class ToolRegistry:
    def register(self, definition: ToolDefinition, executor: ToolExecutor) -> None: ...
    def seal(self) -> None: ...
    def resolve(self, name: str) -> tuple[ToolDefinition, ToolExecutor]: ...  # raises UnknownToolError
```

A `Capability` is constructed with a (possibly empty) list of tools it's allowed to use, resolved from the
Tool Registry at boot — consistent with P9. A tool implementation MUST NOT import a provider SDK (same
isolation rule as everything else) and MUST NOT call another `Capability` (P4 extends unchanged: a tool is
not a backdoor around "capabilities never call each other").

**Idempotency (carried over from §8):** a tool with side effects is the one place in this whole document
where "retry the generate call" and "re-run the tool" must not be conflated. **Rule proposed here:** if a
Gateway-internal retry/fallback (§7/§8) occurs *before* a `ToolExecutor.execute()` call for a given
`ToolCall` has completed, no special handling is needed (nothing side-effecting happened yet). If a retry is
ever triggered *after* a tool already executed (e.g. the *next* `generate()` call in the loop fails and
Workflow retries the whole step from scratch), the **entire `Capability.execute()` call restarts fresh**
(Phase 6's existing "no partial internal state preserved across attempts" rule) — meaning a
side-effecting tool from the *previous, discarded* attempt may have already run. **This is a real,
named risk, not resolved by this document — see Critical Risk 1 (§23).** The honest mitigation available
today, without new infrastructure, is a convention: tools with irreversible side effects should be written
to be idempotent themselves (e.g. keyed by a request id derivable from `CapabilityContext`, so a duplicate
call is a safe no-op) — but nothing in the framework enforces this, and it's an open question whether it
should (§25, Open Question 3).

---

## 12. Vision

**Architecture only — no image/PDF processing pipeline is built.** Phase 6's `ContentPart` (§7 of the
contract) already supports `type: Literal["text", "artifact_ref"]` with `mime_type` — this is deliberately
generic enough to cover images and PDFs today with **zero schema change**:

- **Images** — `ContentPart(type="artifact_ref", artifact_ref="<object-storage-uri>", mime_type="image/png")`.
  A `Capability` requiring vision sets `requires_vision=True` in its routing hint (surfaced through
  `ExecutionContext` → `RoutingCriteria`, §6); the Router's hard filter on `ModelDescriptor.supports_vision`
  guarantees only a vision-capable model is ever selected.
- **PDFs** — same `ContentPart` shape, `mime_type="application/pdf"`. Whether a given provider accepts a PDF
  natively (some do) or requires client-side pre-processing (rasterize to images, extract text) is entirely
  a **provider-adapter-internal** concern (§3) — invisible above the Gateway boundary. This document does
  not decide *how* each adapter handles PDFs; that's an implementation detail deferred to when each real
  adapter is built, not an architecture decision.
- **Future audio** — `GenerateRequest.modalities` already includes `"audio"` as a valid list member (Phase 6
  contract §7). Audio *input* fits the existing `ContentPart(type="artifact_ref", mime_type="audio/...")`
  shape with zero change. Audio *output* (a model that speaks its answer) does not fit today's
  `GenerateResponse.text: str | None` cleanly — it would need `GenerateResponse.artifacts` (already exists,
  §7 of the contract, "non-text outputs e.g. generated images") to also legitimately carry an audio
  artifact. **No schema change needed** — `artifacts: list[ArtifactRef]` is already modality-agnostic
  (`ArtifactRef.mime_type` disambiguates); this document just confirms audio output is representable as-is.
- **Future video** — same reasoning as audio: input via `ContentPart`, output via `ArtifactRef`. `modalities`
  would need `"video"` added to its `Literal` — a one-line, additive, non-breaking widening when a real
  capability needs it, exactly the kind of change Phase 6 contract §14 rule 6 explicitly allows
  ("new optional fields on existing provider-neutral types — never a provider-shaped escape hatch").

**No new Gateway method for any of the above.** Vision, PDF, audio, and video all route through the same
`generate()`/`generate_stream()` methods, differentiated only by `ContentPart.mime_type` on the way in and
`ArtifactRef.mime_type` on the way out — the multimodal shape Phase 6 already committed to ("Binary content
is never inlined... always a reference") is sufficient for all four without modification.

---

## 13. Embeddings

**Ownership:** `LLMGateway.embed()` already exists (Phase 6 contract §7) as a Gateway method any
`Capability` may call directly — there is no dedicated "Embedding Capability" mandated by this document,
and none is required; embeddings are a primitive, not a capability, exactly like `generate()` is not itself
a capability. A future capability (e.g. deduplication, semantic search, RAG retrieval — RAG orchestration
itself remains a named Phase 6 non-goal, §13 of the contract) would call `embed()` the same way any
`Capability` calls `generate()` today.

**Caching — safe to be far more aggressive than response caching (§15).** Unlike `generate()`, `embed()` is
(for a fixed provider model version) deterministic — the same input text and the same `model_used` always
produce the same vector. This makes an **Embedding Cache** low-risk by construction, unlike a `generate()`
response cache, where creative/varying output is often the *point*. Recommended design: a `CacheStore`
(§15) keyed by `(model_id, sha256(input_text))`, TTL-free (or a very long TTL, since a given model version's
embeddings never change) — invalidated only by a model version bump (a new `model_id`, since model
identifiers here are opaque strings, a provider retiring/replacing an embedding model naturally produces a
new cache key, not a stale hit).

**Future vector DB integration — named, not designed.** A `VectorStore` Protocol (`upsert(vectors, metadata)`,
`search(query_vector, top_k) -> list[Match]`) is the natural future boundary, parallel in spirit to
`PromptRepository` — a pure lookup/write contract a `Capability` would depend on, entirely separate from
`LLMGateway.embed()` itself (Gateway produces vectors; a separate, not-yet-designed component stores and
searches them). **Explicitly out of scope for Phase 7** — named here only so it isn't rediscovered as a
surprise dependency once a real RAG-adjacent capability is proposed, mirroring how Phase 6 named the Prompt
Publisher without designing it.

---

## 14. Moderation

`LLMGateway.moderate()` already exists (Phase 6 contract §7) as a distinct, explicit method. This document
recommends **explicit composition by the `Capability`, not silent Gateway-side gating**, as the Phase 7
default — for the same reason streaming and structured-output retries stay `Capability`-owned: the Gateway
must not make policy decisions on a `Capability`'s behalf (P3 — a Gateway that decided *whether* to
moderate would be making an editorial/business-logic decision, which belongs above the Gateway boundary).

**Pre-generation:** a `Capability` that needs input moderation calls `LLMGateway.moderate(input)` itself,
inspects `ModerateResponse.flagged`, and decides whether to proceed to `generate()` — two ordinary Gateway
calls, composed in `Capability.execute()`, each producing its own `CapabilityCall` entry (already supported,
§4 of the contract).

**Post-generation:** identical pattern, `moderate()` called on the `GenerateResponse.text`/`structured_output`
before the `Capability` treats it as final.

**Provider-independent, by construction, not by extra design:** `moderate()` is already one of the six
provider-neutral `LLMGateway` methods — a provider lacking a moderation endpoint raises
`UnsupportedGatewayCapabilityError` (already an approved Phase 6 pattern), and the Router can route a
`moderate()` call to a *different* provider than the one handling `generate()` for the same
`Capability` invocation (e.g. always route moderation to whichever provider has the cheapest/fastest
moderation endpoint, independent of which model is generating) — this falls out of the existing
per-`gateway_method` routing criteria (§6) with no special-casing.

**Deferred, optional convenience (not designed, explicitly named as future scope):** an inline
`GenerateRequest.moderate_input: bool` / `moderate_output: bool` flag that makes the Gateway compose the two
calls internally is *conceivable* but deliberately not proposed as part of Phase 7's design — it would blur
the "one `CapabilityCall` per `LLMGateway` invocation" rule (§1) by making a single `generate()` call
internally perform two provider round-trips, complicating cost/usage attribution. Left as a named,
deferred idea (§24), not a decision.

---

## 15. Caching

Three distinct caches, three distinct ownership boundaries, deliberately not merged into one "AI cache"
concept:

| Cache | What it keys on | Owner | Default | Risk if wrong |
|---|---|---|---|---|
| **Response cache** | `sha256(canonical GenerateRequest JSON)` — messages, model, temperature, tools, everything that affects output | Routing Gateway, internal, opt-in only | **OFF.** A `Capability` opts in via a new, additive, optional `GenerateRequest.cache_policy: Literal["none", "read_write"] = "none"` field | Silently stale/repeated output for a `Capability` that expected fresh generation (most capabilities, most of the time) |
| **Embedding cache** | `(model_id, sha256(input_text))` | Routing Gateway, internal, default-ON (§13) | **ON** by default — low risk given embeddings are deterministic per model version | Near-zero, given the determinism argument in §13 |
| **Prompt cache** (provider-native, e.g. Anthropic `cache_control` breakpoints, OpenAI prompt caching) | Provider-specific mechanism — a request-shape optimization, not a separate value cache | Individual `ProviderAdapter`, entirely internal, invisible above the Gateway boundary | Adapter's own choice, per provider capability | None visible above the boundary — this is a cost/latency optimization on the *provider's* side of an already-issued call, not a correctness concern for this document |

**Ownership boundary, stated as a rule:** only the Routing Gateway (for response/embedding cache) and
individual `ProviderAdapter`s (for provider-native prompt caching) may hold a `CacheStore` dependency.
Neither `Capability` nor `CapabilityExecutor` ever touches a cache directly — a `Capability` only ever
expresses intent (`cache_policy` on the request), never manages cache state itself. This mirrors the same
boundary discipline Phase 6 already applies to cost (`Capability` never computes cost, only expresses usage)
and budget (`Capability` calls `BudgetGuard`, never manages the ledger itself).

**Backing store:** `core/redis.py` already exists and is already the project's shared cache/session
backend — reusing it (rather than introducing a second caching technology) keeps the response and
embedding caches consistent across horizontally-scaled worker processes, which matters directly for §21
(millions of requests, necessarily multi-process).

```python
class CacheStore(Protocol):
    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, ttl_seconds: int | None = None) -> None: ...
```

A `RedisCacheStore` implementation is the obvious default; the Protocol exists so tests can use an
in-memory fake (§19) without a real Redis instance, same pattern as every other Protocol in this document.

---

## 16. Rate limiting

A `RateLimiter` sits inside the Routing Gateway, consulted **before** dispatch to a `ProviderAdapter`
(§2's diagram) — the earliest point at which the resolved `(provider_id, model_id, capability_name)` triple
is known.

```python
class RateLimitKey(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    provider_id: str
    model_id: str | None = None       # None = provider-wide limit
    capability_name: str | None = None
    tenant_id: str | None = None      # not populated today - see below

class RateLimiter(Protocol):
    async def acquire(self, key: RateLimitKey) -> None:
        """Blocks (bounded by the Capability-internal timeout, §8) or raises
        RateLimitExceededError if the limit is already exhausted and blocking
        would exceed the caller's remaining timeout budget."""
        ...
```

**Four independently-configurable limit dimensions**, matching the brief exactly:

- **Per provider** — respects the provider's actual published rate limit (requests/min, tokens/min) —
  necessary regardless of anything else, since exceeding it produces the 429s the Fallback Chain (§7) has
  to handle reactively; a working limiter reduces how often that reactive path is even needed.
- **Per model** — some providers rate-limit specific models more tightly than their account-wide limit
  (common for newer/high-demand models) — a separate token bucket keyed by `(provider_id, model_id)`.
- **Per tenant** — **not populated in this system today** (no multi-tenant concept exists anywhere in
  Phase 1–6). `RateLimitKey.tenant_id` exists as a **forward-compatible, currently-unused** field —
  named now so the limiter's key shape doesn't need to change when multi-tenancy is eventually introduced,
  consistent with how `preferred_provider` was added ahead of need in Phase 6's own review (§8, gap 1).
  **Explicitly not implemented or enforced in Phase 7** — an unused field, not a feature.
- **Per capability** — protects shared provider quota from being monopolized by one high-volume capability
  (e.g. a bulk-scoring capability starving a low-volume, latency-sensitive one) — keyed by
  `(provider_id, capability_name)`, using `CapabilityContext.runtime.capability_name`, already available
  at the Gateway call site via `RoutingCriteria.capability_name` (§6).

**Implementation shape:** token-bucket per key, backed by Redis (§15's `core/redis.py`) for cross-process
consistency — an in-process-only limiter would under-count real usage the moment this system runs more than
one worker, which it already does or soon will (§21). `RateLimitExceededError` maps to
`RetryableCapabilityError` at the `Capability`/`CapabilityExecutor` boundary — a rate-limit rejection is, by
definition, a transient condition.

---

## 17. Cost accounting

Interaction with the already-approved Phase 6 components, restated precisely for the Phase 7 boundary:

### 17.1 What crosses the boundary

`GenerateResponse.usage` (a `CapabilityUsage`) is the **only** thing the Routing Gateway hands back across
the `LLMGateway` boundary for cost purposes — it must reflect the actual, final, successful attempt's usage,
never a sum across internal fallback/retry attempts and never an attempt that ultimately failed. This is
already implied by Phase 6's existing "one `CapabilityCall` per `LLMGateway` invocation" rule (§1) and
requires no schema change — only a behavioral commitment from the Routing Gateway implementation.

### 17.2 The "shadow cost" of failed internal attempts — a real risk, named explicitly

A Fallback Chain attempt that fails *after* a provider has already generated (and billed) some tokens — a
timeout that occurs mid-generation, for instance — has a real cost that never reaches `CostTracker`, because
`CostTracker` only ever sees the usage of the *final, successful* `CapabilityCall` (§17.1). This is
**Critical Risk 2** (§23), not resolved by this document. The honest options:

- Accept the gap — failed-attempt cost is real but typically small relative to successful-call cost, and
  most provider APIs don't bill genuinely failed requests anyway (this varies by provider and failure mode,
  which is itself part of the risk — the assumption isn't verified here).
- Add a separate, Gateway-owned **attempt telemetry** sink (distinct from `CapabilityCall`, never persisted
  as `AIExecution`, purely for cost-leakage observability) that records every attempt's usage, even failed
  ones — additive, doesn't touch the `CapabilityCall`/`AIExecution` contract at all, purely an internal
  Gateway observability concern. **Recommended if/when real spend data shows this matters** — not built
  speculatively now.

### 17.3 `BudgetGuard` timing, unaffected

`BudgetGuard.check()` still runs exactly once, pre-flight, before `LLMGateway.generate()` is called — Phase
6's pipeline order is unchanged by anything in this document. §7.1 already addresses the one real tension
this introduces (fallback potentially selecting a pricier-than-checked model) via the cost-non-increasing
fallback constraint, not via a Gateway-side `BudgetGuard` re-check.

### 17.4 `AIExecutionMapper` / future `AIExecution` persistence, unaffected

Nothing in this document changes the `AIExecutionMapper` boundary (Phase 6 contract §10.1) or reopens
Amendment B's persistence deferral. A `CapabilityCall` produced via Gateway routing/fallback/streaming/tool
calls is shape-identical to one produced by a hypothetical single-provider, no-routing Gateway — routing
existing "under the hood" doesn't change what `CapabilityCall` looks like at all.

### 17.5 Pricing source of truth (restated from §5)

`CostTracker`'s "own model-price table" (Phase 6 contract §9) should become a read of `ModelRegistry`'s
pricing fields rather than an independently maintained table — see §5's recommendation and Open Question 1
(§25). This is the one place this document proposes touching Phase 6 contract wording, and only its
wording about *where the price number lives*, not `CostTracker`'s ownership of *writing* cost.

---

## 18. Configuration

**Provider credentials.** `core/config.py`'s flat `openai_api_key` / `anthropic_api_key` fields (already
present, currently unused/reserved) do not scale cleanly to seven-plus providers as individual
`Settings` attributes — not because seven fields is unmanageable, but because each new provider currently
requires a `core/config.py` edit, which is a Phase-1-established file this document would rather extend
additively than keep hand-editing per provider. Recommended shape:

```python
# core/config.py - additive fields only, illustrative, not to be edited by this planning-only document
openai_api_key: SecretStr | None = None
anthropic_api_key: SecretStr | None = None       # already exists
gemini_api_key: SecretStr | None = None
openrouter_api_key: SecretStr | None = None
ollama_base_url: str | None = None               # no key - local
deepseek_api_key: SecretStr | None = None
grok_api_key: SecretStr | None = None

enabled_providers: list[str] = Field(default_factory=list)   # explicit opt-in, e.g. ["anthropic", "openai"]
```

Each is `SecretStr | None`, matching the existing `openai_api_key`/`anthropic_api_key` precedent exactly —
**no new configuration *pattern*, only more fields of the same kind.** `.env.example` gains one commented
block per provider, following the existing "AI Layer - reserved for a future phase" section's style.

**How providers are enabled.** A provider is registered into the Provider Registry (§4) at boot **if and
only if** its `provider_id` appears in `enabled_providers` **and** its required credential is present
(`requires_credential=False` providers like a local Ollama only need the flag). This makes "enabled" a
single, explicit, boot-time decision — never a runtime toggle, consistent with P9. Flipping a provider on/off
requires a config change and a process restart, exactly like every other sealed-registry change in this
system (Phase 6 review §4's explicit acceptance: "install the package, restart the process is consistent
with this project's existing no dynamic discovery rule, not a limitation the plugin future needs to
remove").

**How models are configured.** Via a single, explicit, code-reviewed source — recommended as a Python
module (`integrations/llm_gateway/models.py`, a flat list of `ModelDescriptor` literals, mirroring
`workflows/definitions/`'s pattern of declarative-Python-as-config) rather than a YAML file, because model
capability flags benefit from static type-checking (a typo'd `Literal` value fails `mypy`/import time, not
silently at runtime) more than prompt content does. This is a genuine, named departure from
`PromptRepository`'s file-based-non-Python approach (§8 of the Phase 6 contract) — flagged as Open Question
4 (§25), not asserted as obviously correct.

**Feature flags.** Two kinds, kept distinct: (1) **provider-level** (`enabled_providers`, above — coarse,
boot-time, security/cost-relevant) and (2) **behavioral defaults** (default `RoutingObjective`, response-cache
default policy, `max_fallback_attempts`, `max_same_candidate_retries`) — recommended as `Settings` fields
with sane defaults, overridable per-request via `RoutingCriteria`/`GenerateRequest` fields already designed
above, never requiring a code change to adjust system-wide behavior.

---

## 19. Testing strategy

Mirrors the already-established Phase 6 pattern (`tests/fakes/fake_gateway.py`, `tests/fakes/fake_capability.py`)
exactly — no new testing philosophy, more fakes at a new layer.

**Fake provider.** `tests/fakes/fake_provider_adapter.py` (new) — a `FakeProviderAdapter` implementing the
same `LLMGateway`-shaped interface as any real adapter (§3), with **configurable failure injection**:
constructed with a scripted sequence of responses/exceptions (`[success, RateLimitExceededError, success,
...]`) so Router/Fallback Chain/Retry Policy logic can be tested deterministically against multiple fake
providers without any network — this is the piece Phase 6's `FakeLLMGateway` alone can't exercise, since it
sits *above* routing entirely (§1). Two or three `FakeProviderAdapter` instances, registered into a real
`ProviderRegistry`, are sufficient to test every row of §7's failure-trigger table.

**Fake model.** `ModelDescriptor` test fixtures — no fakes needed beyond ordinary Pydantic instances, since
`ModelDescriptor` has no behavior, only data. A `tests/fakes/fake_models.py` module of a handful of
representative descriptors (one per capability-flag combination worth testing) is enough to exercise the
Router's `filter()`/ranking logic.

**Deterministic responses.** Every `FakeProviderAdapter` response is hardcoded/scripted, never randomly
generated — matching `FakeLLMGateway`'s existing style exactly (`"fake response"`, `model_used="fake-model-v1"`).

**Provider contract tests.** A single **shared, abstract test suite** (`tests/contract/test_provider_adapter_contract.py`,
new) that every real `ProviderAdapter` implementation — once built in a future phase — must pass:
Protocol-shape conformance (every method callable with valid requests, correct response types),
`UnsupportedGatewayCapabilityError` raised (not silently no-op'd) for genuinely unsupported methods,
`generate_stream` yields at least one `is_final=True` chunk with `usage` populated, and
`response_mode="json_schema"` requests actually invoke the provider's native JSON mode where the adapter
claims to support it. This is explicitly **designed now, exercised later** — no real provider adapter exists
yet (out of scope for Phase 7, same as Phase 6 shipped zero real capabilities), but the contract test suite
being designed alongside the architecture (rather than retrofitted once seven adapters already exist,
inconsistently) is the whole point of naming it here.

**Regression.** Full existing test suite (Phase 1–6) unaffected — nothing under `capabilities/`,
`workflows/`, `database/models/`, `services/` (existing files) changes as a result of this document; the
same `ruff`/`mypy`-clean, zero-network-in-unit-tests discipline already established continues unchanged.

---

## 20. Failure analysis

Every failure mode named in the brief, plus the additional modes this design surfaces, with explicit
recovery ownership:

| # | Failure mode | Recovery owner | Outcome |
|---|---|---|---|
| 1 | Provider auth failure | Fallback Chain (§7) — skip candidate, mark unhealthy for process lifetime | Next candidate tried; if all fail, `AllProvidersFailedError` |
| 2 | Model unavailable / decommissioned | Fallback Chain (§7) | Skip candidate; log stale-registry warning |
| 3 | Rate limited (429) | Rate Limiter (§16) prevents most; Fallback Chain handles any that occur anyway | Skip candidate; retryable upward |
| 4 | Timeout (network / provider slow) | Provider-adapter HTTP timeout (innermost boundary, §8); Fallback Chain | Skip candidate |
| 5 | Content moderation block | Fallback Chain (§7) — deliberately does NOT fall back | `PermanentCapabilityError`-mapped `ContentModerationBlockedError`, no further attempts |
| 6 | Budget exceeded (pre-flight) | `BudgetGuard` (Phase 6, unchanged) | Rejected before Gateway is ever called; `BudgetExceededError` |
| 7 | Budget exceeded mid-fallback (pricier candidate) | Constrained away by cost-non-increasing fallback (§7.1) | Not reachable under the recommended default |
| 8 | Structured-output schema mismatch | `Capability` (§10) — one bounded retry, same model | `ValidationCapabilityError` on second failure |
| 9 | Tool call references an unregistered tool | `ToolExecutor`/`ToolRegistry` (§11) — `UnknownToolError` | Surfaces to `Capability`, which decides retry vs. fail |
| 10 | Tool execution itself fails (the tool's own logic errors) | `ToolExecutor` implementation (§11) — returns `ToolExecutionResult(status="FAILED")`, never raises past its own boundary | `Capability` decides whether to feed the failure back to the model as a tool-result message or abort |
| 11 | Streaming connection drops mid-stream (after ≥1 chunk) | Raises upward, no Gateway-internal fallback (§9) | `RetryableCapabilityError`; Workflow-level retry re-runs the whole step |
| 12 | Streaming connection drops before any chunk | Fallback Chain, same as `generate()` (§9) | Skip candidate |
| 13 | Embedding cache returns a stale vector after a silent provider model behavior change (same `model_id`, provider changed weights server-side without a version bump) | Nobody — named as an accepted risk, not mitigated | Possible, rare, provider-side data-quality issue outside this system's control |
| 14 | Response cache hit for a `Capability` that mutated its own cache-key-relevant state without it appearing in the request (e.g. a hidden non-determinism source) | `Capability` author, by only opting into `cache_policy="read_write"` when output is genuinely a pure function of the request | Requires correct opt-in discipline; not automatically safe |
| 15 | Rate limiter's Redis backend unavailable | Rate Limiter — fails open or closed? **Open Question 5 (§25)**, not resolved here | Undecided — flagged, not silently defaulted |
| 16 | Provider Registry / Model Registry has zero enabled providers/models at boot (misconfiguration) | Boot-time validation, `build_provider_registry`/`build_model_registry` | Should fail fast at process start, not at first `generate()` call — a `ProviderRegistry`/`ModelRegistry` sanity check belongs in the same boot sequence that already seals `CapabilityRegistry`/`WorkflowRegistry` |
| 17 | `AllProvidersFailedError` (every Fallback Chain candidate exhausted) | `Capability`/`CapabilityExecutor` boundary | Mapped to `RetryableCapabilityError` if every underlying failure was itself retryable-flavored, else `PermanentCapabilityError` — mixed-flavor exhaustion defaults to retryable (favors giving Workflow-level retry a chance rather than failing permanently on an ambiguous mix) |
| 18 | Provider SDK raises an exception type this design didn't anticipate | `ProviderAdapter` implementation — MUST catch and translate to one of this document's typed exceptions, never let a raw SDK exception cross the `LLMGateway` boundary | Adapter bug if it leaks — same discipline Phase 6 already requires of `Capability` ("never a bare Exception") |
| 19 | Two providers' Model Registry entries silently drift out of sync with reality (a model's actual context window changes) | Nobody automatically — Model Registry is static, code-reviewed data (§18) | Accepted risk of the file-based approach, same class of risk `PromptRepository` already accepts for prompt content |

---

## 21. Scalability

**10 providers, 100 models:** every registry (`ProviderRegistry`, `ModelRegistry`) is a dict — O(1)
lookup, O(n) full scan only for `ModelRegistry.filter()`, and n=100 is trivially fast in-process (no
measurable cost even scanned linearly per request; an index-by-capability-flag optimization is possible
later but not required at this scale — flagged as premature optimization if built now).

**50 capabilities:** capabilities don't interact with this layer's scale at all — every `Capability` is
just a `RoutingCriteria.capability_name` string used for rate-limiting/audit keys (§16); adding capability
#50 costs nothing here, exactly as Phase 6 already established for the Capability Registry itself.

**Millions of requests:** the two components that do NOT scale for free are the **Rate Limiter** and the
**Response/Embedding Cache** — both MUST be backed by Redis (§15, §16), not in-process memory, the moment
this system runs more than one worker process (which it will, well before "millions of requests" is
reached). This is stated as a hard requirement, not a nice-to-have: an in-process rate limiter across N
worker processes under-counts true request volume by a factor of N, silently defeating the entire point of
having one.

**Connection reuse.** Each `ProviderAdapter` MUST hold and reuse a persistent HTTP client (connection
pooling) across calls, constructed once at Provider Registry build time, never per-request — a
per-request client would dominate latency at high request volume through repeated TLS handshake overhead.
This is an implementation detail of each adapter, not a Gateway-level concern, but named here because it's
the kind of detail that's cheap to get right now and expensive to retrofit across seven adapters later.

**Async throughout, unchanged.** Every method in this document's Protocols (`LLMGateway`, `ToolExecutor`,
`RateLimiter`, `CacheStore`) is `async` — consistent with the entire codebase's existing `asyncio` usage;
no blocking I/O is introduced anywhere in this design.

---

## 22. Future compatibility

| Future need | How this design accommodates it |
|---|---|
| **Local models** (Ollama) | Just another `ProviderAdapter`, `requires_credential=False`, `$0` pricing in its models' `ModelDescriptor` entries — zero special-casing anywhere (§3, §18) |
| **Hosted APIs** (the other six) | Identical treatment — no provider is architecturally distinguished from any other |
| **MCP (Model Context Protocol)** | A future `ToolExecutor` implementation can be MCP-client-backed — `ToolDefinition`/`ToolCall` (already provider-neutral, Phase 6 §7) are a natural fit for MCP's own tool-schema shape. **No `ToolExecutor` Protocol change required** — MCP becomes one more way to populate the Tool Registry (§11), not a new integration point |
| **Tool ecosystems generally** | Tool Registry (§11) is explicit-registration/sealed, same extensibility shape as every other registry in this system — adding tool #50 costs nothing structurally |
| **Multi-agent workflows** | Explicitly remains a Phase 6 non-goal (§13 of the contract, unchanged) — nothing in this document reopens it. The tool-calling loop design (§11) stays *inside* one `Capability`, not across multiple cooperating capabilities |
| **Batch inference** | Not designed this phase — the natural extension point is a future `generate_batch(requests: list[GenerateRequest]) -> list[GenerateResponse]` method (or provider-level batch API, adapter-internal) added additively to `LLMGateway`, since Phase 6 canonical rule 6 already permits new methods. Named as a future non-goal, not designed further here |
| **Async/job-polling inference** (submit now, poll later — some providers' batch/async APIs work this way) | Does not fit today's `await generate()` shape at all — would need a new `GenerateJob`/poll pattern (`submit() -> job_id`, `poll(job_id) -> GenerateResponse | None`). Explicitly named as a real future non-goal requiring new Protocol design, not assumed solvable by anything in this document |
| **Provider hot swap** | **Named tension, not fully satisfied.** "Hot swap" (zero-downtime provider change with no restart) conflicts with the sealed-registry, no-dynamic-discovery principle (P9) this entire system is built on. What this design actually provides is **fast, safe, config-only provider changes requiring a process restart** — consistent with every other registry in this codebase, but genuinely not "hot" in the zero-downtime sense the term usually implies. Flagged explicitly as Open Question 6 (§25): is restart-required swap acceptable as "hot swap" for this system's purposes, or does true zero-downtime swapping need a different mechanism (e.g. blue-green process deployment, which is an infra concern, not an application-architecture one)? |

---

## 23. Critical risks

1. **Tool-calling idempotency under retry (§11, §8).** A side-effecting tool executed during a
   `Capability.execute()` attempt that is later discarded (Workflow-level retry restarts the whole
   capability fresh) may have already run its side effect once, with no framework-level dedup. Real risk
   the moment the first side-effecting tool is built; not resolved by this document (Open Question 3, §25).
2. **Shadow cost of failed internal fallback attempts (§17.2).** Real provider spend from failed
   Gateway-internal attempts may never reach `CostTracker`/`BudgetGuard`, meaning actual spend could exceed
   what the system believes it spent. Severity depends on how often providers bill failed/partial
   generations — unverified in this document.
3. **Two independently-maintained sources of model pricing (§5, §17.5)** if the recommended consolidation
   (Model Registry as single source of truth) is not adopted before `CostTracker` is actually built —
   drift between routing decisions and billed cost is a correctness bug with financial impact, not a
   cosmetic one.
4. **Static Model Registry going stale (§18, failure #19).** Every model's capability flags, context
   window, and pricing are hand-maintained data. A provider silently changing a model's behavior (context
   window increase, price change, deprecation) is invisible to this system until someone updates the
   registry — no automated verification against live provider metadata is designed in this document.
5. **Retry-multiplication ceiling (§8) is a design recommendation, not an enforced constraint.** Nothing in
   this document's Protocols *mechanically* prevents a future capability author from setting
   `WorkflowRetryPolicy.max_attempts=10` and a Gateway config of `max_fallback_attempts=10`, producing 100+
   real provider calls for one logical step. The "treat the product as a reviewed number" rule (§8) is a
   process discipline, not a code-enforced ceiling.

---

## 24. Technical debt intentionally deferred

- **Latency-informed `fastest` routing (§6.1)** — ships as "cheapest within top quality tier" until real
  latency telemetry exists; genuinely stale the moment provider performance characteristics shift.
- **Inline Gateway-side moderation composition (§14)** — `moderate_input`/`moderate_output` convenience
  flags are named but not designed; explicit two-call composition is the only supported pattern for now.
- **Vector DB integration (§13)** — `VectorStore` Protocol is named, not designed; no capability depends on
  it yet.
- **Batch and async/job-polling inference (§22)** — both require new Protocol shapes not designed here;
  today's `generate()` is strictly synchronous request/response.
- **Provider-native prompt caching (§15)** — left entirely to individual adapter discretion; no
  cross-provider consistency guarantee or shared abstraction for it.
- **Attempt-level cost telemetry (§17.2)** — the "shadow cost" mitigation is named but not built; deferred
  until real spend data justifies the added complexity.
- **True zero-downtime provider hot-swap (§22)** — this design provides restart-based swap only.
- **Model Registry staleness verification** — no automated check against live provider metadata; entirely
  manual, code-reviewed maintenance, same risk class already accepted for prompt content (Phase 6) and now
  extended to model metadata.

---

## 25. Open questions requiring your decision

1. **Pricing source of truth (§5, §17.5):** should `ModelRegistry` become the single source of truth for
   model pricing, with `CostTracker` reading from it (proposed amendment to Phase 6 contract §9's wording),
   or should the two remain independently maintained? **Recommended: consolidate into `ModelRegistry`.**
2. **Fallback-cost constraint (§7.1):** cost-non-increasing fallback by default, with an explicit
   `cost_ceiling` override, vs. a full `BudgetGuard` re-check per fallback attempt (bigger change to Phase
   6's fixed pipeline order). **Recommended: cost-non-increasing fallback by default.**
3. **Tool-call idempotency (§11, §23 Risk 1):** should the framework provide any dedup/idempotency-key
   mechanism for side-effecting tools, or remain a pure convention left to each tool implementation?
   **No recommendation yet — genuinely open, and the highest-severity open question in this document.**
4. **Model configuration format (§18):** a typed Python module (recommended, for `mypy`-checked capability
   flags) vs. a YAML/file-based format matching `PromptRepository`'s precedent (consistency with the
   established non-Python-config pattern, at the cost of losing static type checking). **Leaning Python
   module; flagged since it's a real departure from the `PromptRepository` precedent.**
5. **Rate limiter fail-open vs. fail-closed (§20, failure #15):** if the Redis backend the Rate Limiter
   depends on is unavailable, should calls proceed unthrottled (fail-open — availability-favoring, risks a
   provider-side rate-limit storm) or be rejected (fail-closed — safety-favoring, turns a Redis outage into
   a full AI-layer outage)? **No recommendation yet — genuinely open, a real availability-vs-safety
   tradeoff.**
6. **"Provider hot swap" definition (§22):** is restart-required, config-only provider swapping an
   acceptable reading of "hot swap" for this system (consistent with every other sealed registry), or is
   true zero-downtime swapping a real requirement needing additional (likely infra-level, not
   application-architecture-level) design? **Recommended: accept restart-required swap as sufficient,
   consistent with P9 — but this is a definitional question worth an explicit yes, not an assumed one.**
7. **Streaming mid-stream failure semantics (§9):** confirmed as "raise, never fall back, once ≥1 chunk has
   been emitted" — please confirm this is the intended tradeoff (correctness/no-discontinuous-stream over
   resilience) rather than, e.g., a client-side buffering strategy that could in principle allow fallback
   at the cost of losing streaming's latency benefit entirely for the first attempt.

---

**No code, migrations, or Phase 1–6 changes have been made. Waiting for your review of §25's open questions
(especially Open Questions 1–3) before the stress-test review (`docs/phase7_architecture_review.md`) is
treated as final, and before any Architecture Contract is drafted.**
