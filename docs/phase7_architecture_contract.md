# Phase 7 Architecture Contract — AI Integration Layer Specification

**Status: Final design specification. Single source of truth for the AI Integration Layer.**

This document supersedes no prior document as a record of what was decided — it is not a revision of
`docs/phase7_ai_integration_layer_planning.md`, `docs/phase7_principal_architect_review.md`,
`docs/phase7_consistency_review.md`, or `docs/phase7_ai_integration_layer_planning_v2.md`, and none of them
is edited by it. It **does** supersede all four as the thing future code and future contributors are
validated against. `docs/phase7_ai_integration_layer_planning_v2.md` is the frozen design baseline this
contract converts into binding form; the other three remain historical context explaining *why* specific
decisions were made, not *what* is currently required. Where this document's wording differs from any of
the four, this document governs.

This document is normative. "MUST" / "MUST NOT" / "REQUIRED" / "FORBIDDEN" statements are binding on all
Phase 7 implementation work. Where a rule is not yet enforced by tooling, it is enforced by code review
against this document. No code is written, no existing code is modified, no migration is created, and
nothing is committed as part of producing this document.

This contract extends `docs/phase6_architecture_contract.md` — it does not replace it. Every principle
(P1–P10), forbidden edge, and canonical rule in the Phase 6 contract remains binding and unchanged, with
exactly one exception: **Amendment C (§25 below)**, which relocates `BudgetGuard`'s invocation from
`Capability` to the Routing Gateway. No other Phase 6 contract text is touched.

---

## 1. AI Integration Layer Principles

These extend Phase 6 contract §1's P1–P10 (all unchanged) with the principles specific to everything that
sits below `LLMGateway`.

1. **P11 — Provider isolation.** No file outside `integrations/llm_gateway/providers/<provider>_adapter.py`
   MUST import a provider SDK (`openai`, `anthropic`, `google-genai`, `ollama`, or an
   OpenRouter/DeepSeek/Grok client library), directly or transitively. This widens Phase 6 canonical rule 1
   to name the specific subdirectory the seven SDKs are confined to.
2. **P12 — Provider adapter recursion.** A `ProviderAdapter` is not a distinct Protocol — it MUST be exactly
   an `LLMGateway` implementation, scoped to one provider's SDK. No file may define a second, parallel
   "provider adapter" interface.
3. **P13 — Single composition root.** The concrete `LLMGateway` implementation (the "Routing Gateway," §18)
   is the only component permitted to hold references to every other component named in §18's table. No
   other component's dependencies MAY exceed what its own §18 row grants it.
4. **P14 — Invisible machinery.** Routing, fallback, retry, rate limiting, response caching, cost estimation,
   and budget approval MUST remain entirely internal to the Routing Gateway. A `Capability` observes only a
   `GenerateResponse` (or a raised error) and, downstream, exactly one `CapabilityCall` per `LLMGateway`
   method invocation — Phase 6 contract §4's binding rule, unchanged and now extended to every mechanism this
   contract adds.
5. **P15 — Cache precedes cost.** A cache hit MUST be served without invoking `CostEstimator` or
   `BudgetGuard`. Cost estimation and budget approval occur only on a cache miss.
6. **P16 — Gateway-invoked budget enforcement (Amendment C, §25).** `BudgetGuard.check()` MUST be invoked by
   the Routing Gateway, once per fallback candidate, on a cache miss, immediately before that candidate is
   dispatched — never by `Capability`, and never once per logical call.
7. **P17 — Pure routing.** `RoutingPolicy.rank()` MUST perform no I/O and MUST NOT read external mutable
   state directly. Every input it needs MUST arrive as one of its three parameters
   (`candidates`, `criteria`, `telemetry`). `WeightedSplitPolicy` (§4.6) is the sole named exception to
   *determinism* — it MUST NOT become an exception to *purity* (no I/O, no external state read).
8. **P18 — Sealed registries, extended.** `ProviderRegistry`, `ModelRegistry`, `ToolRegistry`, and
   `RoutingPolicyRegistry` MUST be explicit-registration-only and sealed-after-boot — extending Phase 6 P9
   to every registry this layer introduces. No registry MUST support live/hot reload.
9. **P19 — Redis-backed runtime state.** `ProviderHealthStore`, `RateLimiter`'s buckets, `CacheCoordinator`'s
   backing store, `LatencyTracker`, and `CostTracker`'s spend ledger MUST be cross-process-consistent —
   never process-local only — at any deployment running more than one worker process.
10. **P20 — Typed failure classification.** Every dispatch failure inside `FallbackPolicy`'s loop MUST
    classify to exactly one `FailureClass` value (`TRANSIENT` or `PERMANENT_INCOMPATIBLE`, §5.2) before any
    fallback decision is made.
11. **P21 — No silent capability claims.** `ModelDescriptor` capability flags MUST be human-reviewed at
    registration time (mandatory, §3) and MAY additionally be behaviorally verified by
    `CapabilityNegotiator` (opt-in, §17). `RoutingEngine` MUST NOT trust a claimed flag beyond what its own
    hard filter already checks.

### Forbidden dependency edges (extends Phase 6 contract §1's table)

| Edge | Status |
|---|---|
| Any file outside `integrations/llm_gateway/providers/` → a provider SDK | ❌ FORBIDDEN |
| `ProviderAdapter` → `ProviderRegistry` / `ModelRegistry` / `RoutingEngine` / `BudgetGuard` / `CostTracker` / another `ProviderAdapter` | ❌ FORBIDDEN |
| `RoutingEngine` → `ProviderAdapter` (direct dispatch) | ❌ FORBIDDEN (dispatch is `FallbackPolicy`'s exclusive job) |
| `RoutingEngine` / `RoutingPolicy` → `BudgetGuard` / `CostTracker` | ❌ FORBIDDEN |
| `RoutingPolicy` → any I/O, or a read of external mutable state | ❌ FORBIDDEN (P17) |
| `CacheCoordinator` → `BudgetGuard` / `CostTracker` | ❌ FORBIDDEN |
| `BudgetGuard` → `LLMGateway` / `ProviderAdapter` | ❌ FORBIDDEN (unchanged from Phase 6; the new edge is `FallbackPolicy → BudgetGuard`, never the reverse) |
| `CostEstimator` → `CostTracker` | ❌ FORBIDDEN (an estimator never reads actuals) |
| `CostTracker` → `BudgetGuard` / `LLMGateway` / `ProviderAdapter` | ❌ FORBIDDEN |
| `CapabilityNegotiator` → `RoutingEngine` / `BudgetGuard` / `CostTracker` | ❌ FORBIDDEN (runs once, at boot, outside the request path) |
| `LLMGateway` implementation boundary → `Capability` / `CapabilityExecutor` / `Workflow` | ❌ FORBIDDEN (no upward knowledge, Phase 6 P1 unchanged) |
| `ProviderHealthStore` / `LatencyTracker` → `ModelRegistry` / `ProviderRegistry` content | ❌ FORBIDDEN (keyed by opaque strings only) |
| `Capability` → `BudgetGuard` | ❌ FORBIDDEN (Amendment C, §25 — this edge existed under Phase 6 and is now retired) |
| `ProviderRegistry` → `ModelRegistry` / `RoutingEngine` / any Capability-layer component | ❌ FORBIDDEN (mirrors §18's `ProviderRegistry` row) |
| `ModelRegistry` → `ProviderRegistry` (beyond an opaque string) / any runtime component | ❌ FORBIDDEN (mirrors §18's `ModelRegistry` row) |
| `RateLimiter` → `ModelRegistry` / `ProviderRegistry` (beyond opaque strings) | ❌ FORBIDDEN (mirrors §18's `RateLimiter` row) |
| `PricingCatalog` → `CostTracker` / `BudgetGuard` / `CostEstimator` | ❌ FORBIDDEN (mirrors §18's `PricingCatalog` row) |
| `FallbackPolicy` → `CostTracker` (other than post-hoc recording) / `Capability` / `CapabilityExecutor` | ❌ FORBIDDEN (mirrors §18's `FallbackPolicy` row) |

---

## 2. Provider Abstraction and Provider Registry

```python
# integrations/llm_gateway/providers/base.py — no new Protocol; type alias for clarity at call sites
ProviderAdapter = LLMGateway   # a ProviderAdapter IS an LLMGateway, scoped to one provider's SDK


class ProviderDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_id: str                 # "openai" | "anthropic" | "gemini" | "openrouter" |
                                      # "ollama" | "deepseek" | "grok" - opaque string, never an enum
    display_name: str
    requires_credential: bool = True # False only for a fully local provider requiring no API key
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

    def is_enabled(self, provider_id: str) -> bool: ...
```

**Binding rules:**

1. A provider adapter MUST implement the `LLMGateway` Protocol exactly as defined in Phase 6 contract §7,
   with no provider-specific field added to any request/response type it consumes or produces.
2. `build_provider_registry(settings: Settings) -> ProviderRegistry` MUST construct one adapter per provider
   that is **both** named in `Settings.enabled_providers` **and** has its required credential present
   (`ProviderCredential`, §17); it MUST register each, then seal. A provider absent from
   `enabled_providers`, or missing its credential, MUST NOT be registered at all — never registered with a
   broken adapter.
3. `build_provider_registry()` MUST raise at boot if `enabled_providers` names a `provider_id` with no
   matching factory entry — never silently skip it.
4. `resolve()` MUST be total for every registered provider and raise `UnknownProviderError` otherwise.
   `is_enabled()` MUST exist as a non-raising pre-filter for `RoutingEngine`'s use.
5. **Minimum onboarding bar:** a provider adapter MUST implement `generate()`. Every other `LLMGateway`
   method MAY raise `UnsupportedGatewayCapabilityError` until implemented — this alone is sufficient for the
   adapter to be registered and enabled.
6. A registered `ProviderAdapter` MUST hold and reuse a persistent HTTP client (connection pooling),
   constructed once when the adapter is built — never a new client per request.
7. Every `ProviderAdapter` MUST catch and translate every provider SDK exception to this contract's typed
   exception hierarchy (§6, §20) before it crosses the `LLMGateway` boundary — a raw SDK exception MUST NEVER
   propagate past the adapter. In doing so, the adapter MUST strip/redact any header or field matching a
   known credential pattern (`Authorization`, `api-key`, `x-api-key`, or the adapter's own known credential
   field names) from the logged representation — never rely on the SDK's default `__str__`/`__repr__`.
8. Any `ProviderAdapter` whose underlying call path is not itself async-non-blocking (an in-process,
   synchronous local-inference-library binding) MUST execute that call via `asyncio.to_thread()` or a
   dedicated, bounded thread/process pool — never call blocking code directly inside an `async def`. Ollama
   accessed over its own local HTTP server is exempt — that path is pure async HTTP.
9. Every `ProviderAdapter` method MUST let `asyncio.CancelledError` propagate — no bare `except Exception`
   may catch it — and MUST actually abort the underlying connection where the wrapped SDK supports it. For
   SDKs that cannot abort an in-flight request server-side, the resulting shadow-cost exposure is a named,
   accepted limitation (§15.6), not a defect to be silently worked around.

---

## 3. Model Registry

```python
class PricingTier(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    condition: Literal["standard", "cached_input", "batch"] = "standard"
    input_price_per_million: Decimal
    output_price_per_million: Decimal


class ModelDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str                    # opaque string, never validated against a closed enum anywhere
    provider_id: str                 # FK into ProviderRegistry, in-memory only - never a DB constraint
    display_name: str

    context_window_tokens: int = Field(ge=1)
    max_output_tokens: int | None = None

    supports_tools: bool = False
    supports_streaming: bool = False
    supports_vision: bool = False
    supports_structured_output: bool = False
    supports_embeddings: bool = False
    embedding_dimension: int | None = None       # required (non-None) when supports_embeddings=True
    max_images_per_request: int | None = None    # None = no declared limit
    max_file_size_mb: float | None = None
    max_pdf_pages: int | None = None
    reasoning_tier: Literal["none", "standard", "extended"] = "none"
    quality_tier: int = Field(default=0)         # static, curated, code-reviewed; higher = better

    pricing_tiers: list[PricingTier] = Field(min_length=1)   # "standard" tier is REQUIRED
    pricing_currency: str = "USD"

    availability: Literal["ga", "beta", "deprecated", "unavailable"] = "ga"
    deprecation_note: str | None = None           # set when availability transitions to "deprecated"
    replacement_model_id: str | None = None       # set when availability transitions to "deprecated"


class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ModelDescriptor] = {}
        self._by_provider: dict[str, list[str]] = defaultdict(list)
        self._sealed = False

    def register(self, model: ModelDescriptor) -> None: ...   # raises if sealed / duplicate model_id
    def seal(self) -> None: ...
    def resolve(self, model_id: str) -> ModelDescriptor: ...  # raises UnknownModelError
    def filter(self, *, requires_tools: bool = False, requires_vision: bool = False,
               requires_streaming: bool = False, requires_structured_output: bool = False,
               availability: set[Literal["ga", "beta"]] | None = None) -> list[ModelDescriptor]:
        """Pure in-memory filter - the RoutingEngine's primary query. No I/O."""
        ...
```

**Binding rules:**

1. `model_id` MUST remain a bare, opaque string end to end — in `ModelRegistry`, in
   `GenerateRequest.preferred_model`, and in `CapabilityCall.model_used` — never backed by a database enum.
   Adding model #101 MUST be a one-line registry entry, never a migration.
2. `ModelRegistry` MUST be built from a single, explicit, code-reviewed, statically-typed Python module —
   never inferred from a provider's live model-listing endpoint, never a database table.
3. `pricing_tiers` MUST contain a `"standard"` entry; `"cached_input"` and `"batch"` entries are optional and
   MUST NOT be automatically invoked by anything in this contract's scope (§15.4).
4. `embedding_dimension` MUST be non-`None` whenever `supports_embeddings=True`.
5. `filter()` MUST remain a pure, in-memory, O(n) operation with no I/O — the Router's primary query at every
   scale named in §21.
6. `ModelRegistry.register()` MUST raise if `seal()` has already been called; `register()` and `resolve()`
   MUST behave identically whether or not the registry is sealed with respect to their own logic (only
   mutation is blocked post-seal).
7. **Boot-time cross-registry validation is REQUIRED:** after `ProviderRegistry` and `ModelRegistry` both
   seal, the boot sequence MUST confirm every `ModelDescriptor.provider_id` resolves in `ProviderRegistry`;
   a mismatch MUST raise `RegistryConsistencyError` and the process MUST fail to start.
8. Model registration REQUIRES a human code-review confirming capability flags match the provider's
   documented support — the mandatory gate that precedes `CapabilityNegotiator`'s optional, boot-time
   behavioral gate (§17).
9. Model deprecation (`availability = "deprecated"`) REQUIRES setting `deprecation_note` and
   `replacement_model_id` in the same change. A `deprecated` model MUST remain selectable only via an
   explicit `preferred_model` hint — never a default candidate under any `RoutingObjective`.

---

## 4. Routing

### 4.1 `RoutingCriteria` and `RoutingObjective`

```python
class RoutingObjective(str, Enum):
    BEST_QUALITY = "best_quality"
    LOWEST_COST = "lowest_cost"
    FASTEST = "fastest"
    REASONING = "reasoning"


class RoutingCriteria(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gateway_method: Literal["generate", "generate_stream", "embed", "classify", "moderate", "rerank"]
    capability_name: str
    priority: TaskPriority

    requires_tools: bool = False
    requires_vision: bool = False
    requires_streaming: bool = False
    requires_structured_output: bool = False
    input_image_count: int = 0
    input_pdf_page_count: int = 0

    preferred_model: str | None = None
    preferred_provider: str | None = None
    excluded_providers: list[str] = Field(default_factory=list)

    objective: RoutingObjective = RoutingObjective.BEST_QUALITY
    cost_ceiling: Decimal | None = None
    fallback: "FallbackEligibility" = Field(default_factory=lambda: FallbackEligibility())
```

**Binding rules:**

1. `preferred_model` / `preferred_provider` MUST remain advisory only — never a hard filter. An
   unavailable/incapable preferred candidate MUST be silently skipped, never an error.
2. `excluded_providers` MUST be enforced as a hard filter (§4.3 step 3) — a scoped operator lever distinct
   from the process-wide, restart-gated `enabled_providers` setting (§17).
3. `RoutingCriteria.fallback` carries the `FallbackEligibility` configuration (§5.1) governing this specific
   call's fallback bounds; a `Capability` MAY override the process-wide defaults per call.

### 4.2 `RoutingPolicy` Protocol

```python
class RoutingTelemetrySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    p50_latency_ms_by_model: dict[str, float] = Field(default_factory=dict)   # empty = no data yet


class RoutingPolicy(Protocol):
    def rank(self, candidates: list[ModelDescriptor], criteria: RoutingCriteria,
              telemetry: RoutingTelemetrySnapshot) -> list[ModelDescriptor]:
        """No I/O, no read of any external mutable state - every input this method needs
        is one of the three parameters above. Most policies are also fully deterministic
        (same inputs -> same output); the one deliberate, named exception is
        WeightedSplitPolicy (§4.6), which draws its own local random value each call to
        realize a percentage split - still no I/O, still no read of external state, just
        not deterministic call-to-call. Non-FASTEST policies simply ignore `telemetry`."""
        ...
```

**Binding rule — what "pure" means, precisely:** `rank()`'s REQUIRED property is that it performs no I/O and
never reads shared/external mutable state directly. Determinism (same inputs always produce the same
output) is a property *most* policies also have, but it is a distinct property, not the same requirement.
`WeightedSplitPolicy` (§4.6) is the one named policy permitted to violate determinism while still satisfying
purity — its random draw MUST be generated fresh, locally, inside the call, and MUST NEVER be read from
`LatencyTracker`, `ProviderHealthStore`, or any other external/shared state.

### 4.3 `RoutingEngine` — canonical filter-and-rank sequence

`RoutingEngine` MUST execute the following sequence, in this exact order, for every `generate()` /
`generate_stream()` / `embed()` / `classify()` / `moderate()` / `rerank()` call:

1. **Hard filter** (`ModelRegistry.filter()`) — capability-flag requirements, `availability` in
   `{ga, beta}`.
2. **Provider-enabled filter** — drop candidates whose provider is not `ProviderRegistry.is_enabled()`.
3. **Exclusion filter** (`RoutingCriteria.excluded_providers`) — drop candidates whose `provider_id` is
   caller-excluded. A hard filter, not advisory.
4. **Health filter** — drop any candidate whose `(provider_id, model_id)` is currently marked unhealthy or
   `runtime_unavailable` in `ProviderHealthStore` (§18). The `unhealthy` flag MUST be TTL-based (default
   60s) and MUST expire automatically; `runtime_unavailable` (set only for `PERMANENT_INCOMPATIBLE`
   failures, §5.2) MUST NOT expire within the life of the process.
5. **Zero-candidate check** — if no candidate survives steps 1–4, `RoutingEngine` MUST raise
   `NoRoutableCandidateError` immediately (a `CapabilityConfigurationError`-flavored, non-retryable failure)
   — distinct from "candidates existed but all failed" (§5.4).
6. **Preference ranking** — the resolved `RoutingPolicy.rank(candidates, criteria, telemetry)` orders
   survivors best-first by `criteria.objective`. This ordering is *preference only* — not yet cost-gated.

`RoutingEngine` MUST NOT dispatch to a `ProviderAdapter` itself — step 6's output is handed to
`FallbackPolicy` (§5), which owns everything from eligibility filtering onward.

### 4.4 `RoutingPolicy` exception isolation

`RoutingEngine` MUST wrap every `RoutingPolicy.rank()` call. If a policy raises, `RoutingEngine` MUST log a
`routing_policy_failure` event (§16) and fall back to the built-in default policy for that objective — a
buggy or third-party policy MUST NEVER be permitted to fail the call outright; it may only degrade routing
quality for that one call.

### 4.5 `RoutingPolicyRegistry`

```python
class RoutingPolicyRegistry:
    def register(self, objective: str, policy: RoutingPolicy) -> None: ...
    def seal(self) -> None: ...
    def resolve(self, objective: str) -> RoutingPolicy: ...  # raises UnknownRoutingObjectiveError
```

Sealed-after-boot, explicit-registration-only, identical discipline to every other registry in this
contract (P18). Adding a new objective REQUIRES a new `RoutingPolicy` registered here — zero changes to
`RoutingEngine`, `RoutingCriteria`'s shape, or any `Capability`.

### 4.6 `LatencyTracker`

```python
class LatencyTracker(Protocol):
    async def record(self, provider_id: str, model_id: str, latency_ms: float) -> None:
        """Called once per completed provider attempt (success or failure) - the sole write path.
        provider_id/model_id are opaque strings only (P19, §18) - never resolved against
        ProviderRegistry/ModelRegistry content."""
        ...

    async def snapshot(self) -> RoutingTelemetrySnapshot:
        """Returns the current rolling p50-latency-per-model sample. Missing data for a model is
        simply omitted from the snapshot (§4.6 binding rule below) - never an error, never a
        blocking read."""
        ...
```

Owns the rolling p50-latency-per-model sample the `FASTEST` objective ranks by. `RoutingEngine` MUST fetch a
`RoutingTelemetrySnapshot` from `LatencyTracker` once per call and pass it into `rank()` as a value —
`RoutingPolicy` MUST NEVER hold or read a reference to `LatencyTracker` directly (§4.2). `LatencyTracker`
MUST be Redis-backed for cross-process consistency (P19, §21). Missing data for a model, or backend
unavailability, MUST fail open — the returned snapshot simply omits that model, and `RoutingPolicy` falls
back to the static `quality_tier` heuristic.

### 4.7 `WeightedSplitPolicy` (gradual provider/model migration)

One opt-in, built-in `RoutingPolicy` — `WeightedSplitPolicy(weights: dict[model_id, float])` — registered
through `RoutingPolicyRegistry` like any other policy. A `Capability` opts in explicitly for a migration
window; weights are edited and redeployed manually (restart-gated, P18). This is a **deliberately manual**
mechanism — no automatic promotion or automatic rollback on error-rate regression exists or may be added
without a separate, dedicated amendment (§26). See §4.2 for its determinism exemption.

---

## 5. Fallback

### 5.1 `FallbackEligibility`

```python
class FallbackEligibility(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_cost_multiplier: Decimal = Decimal("3.0")     # candidate price <= multiplier x cheapest-in-set price
    max_additional_cost: Decimal | None = None         # optional absolute cap - if set, BOTH bounds apply
    allow_cost_ceiling_override_on_exhaustion: bool = False   # opt-in: widen past the bound rather than fail
    max_fallback_attempts: int = 3
```

**Binding rule — cost anchor:** the eligibility bound MUST be anchored to the **cheapest price among the
filtered candidate set** (`min(price for c in ranked_candidates)`) — **never** to whichever candidate
`RoutingPolicy` happened to rank first. This is load-bearing: anchoring to the first-ranked candidate
degenerates to zero fallback depth under `RoutingObjective.LOWEST_COST`, since the first candidate under
that objective already equals the anchor.

### 5.2 `FailureClass`

```python
class FailureClass(str, Enum):
    TRANSIENT = "transient"                              # auth (this attempt only), rate limit, timeout, 5xx
    PERMANENT_INCOMPATIBLE = "permanent_incompatible"     # claimed capability not actually supported,
                                                            # or a moderation block - see §17 CapabilityNegotiator
```

### 5.3 `FallbackPolicy` — eligibility filtering

Given `RoutingEngine`'s ranked output and `criteria.fallback` (§4.1, §5.1), `FallbackPolicy` MUST:

1. Compute `cheapest_price = min(price(c) for c in ranked_candidates)`.
2. Keep every candidate where `price(c) <= cheapest_price * max_cost_multiplier` **AND**, if
   `max_additional_cost` is set, `price(c) - cheapest_price <= max_additional_cost`.
3. **Preserve the relative order** `RoutingPolicy` already produced among survivors — eligibility filtering
   MUST NOT re-rank.
4. Truncate to `max_fallback_attempts`. This ordered, bounded list is the final attempt sequence.

### 5.4 `FallbackPolicy` — dispatch loop

For each candidate in the sequence, in order, `FallbackPolicy` MUST:

1. **Check cache first** (`CacheCoordinator`, §13). A hit MUST return immediately, with no cost estimate and
   no `BudgetGuard` check performed for that candidate (P15).
2. **On a miss:** estimate cost (`CostEstimator`, §15.1) and obtain `BudgetGuard` approval (§15.2, Amendment
   C). A denial MUST continue to the next candidate — never fail the call outright while cheaper candidates
   remain untried.
3. **On approval, attempt dispatch.** "Attempt" MUST include up to `max_same_candidate_retries` (default 1,
   §6) retries against *this same candidate* before the candidate is considered to have failed — the
   same-candidate retry is nested inside this step, never a separate pass through the sequence.
4. Only once a candidate's full attempt cycle (initial try plus its same-candidate retries) is exhausted
   MUST `FallbackPolicy` classify the failure via `FailureClass` (§5.2):
   - **`TRANSIENT`** → mark `(provider_id, model_id)` unhealthy in `ProviderHealthStore` with TTL, move to
     the next candidate. `FallbackPolicy` MUST NEVER start a new attempt cycle for this same
     provider/model pair again within this call — once a candidate's attempt cycle (including its
     same-candidate retries) is exhausted, it is removed from the remaining sequence for this call
     regardless of TTL (the TTL affects only *future*, separate calls).
   - **`PERMANENT_INCOMPATIBLE`** → mark `(provider_id, model_id)` `runtime_unavailable` in
     `ProviderHealthStore` with **no TTL** (persists for the life of the process). If the failure is
     specifically a moderation block, `FallbackPolicy` MUST NOT continue the loop at all — it MUST raise
     immediately, never falling back to a different provider/model for the same disallowed content.

### 5.5 Exhaustion

If the loop runs out of candidates (all attempted and failed, or `BudgetGuard` denied every candidate) and
`allow_cost_ceiling_override_on_exhaustion=False` (the default), `FallbackPolicy` MUST raise
`AllProvidersFailedError(reason=...)` with `reason` one of `"cost_ceiling_exhausted"`,
`"all_candidates_failed"`, or `"all_candidates_budget_denied"` — preserved in `CapabilityCall.error` for
diagnostics (§16). If `allow_cost_ceiling_override_on_exhaustion=True`, `FallbackPolicy` MUST re-run §5.3
once more with both cost bounds lifted (unbounded), against the original ranked list minus already-attempted
pairs — this is the only path by which fallback may select a candidate outside the normal cost bound, and it
is never the default.

`AllProvidersFailedError` maps to `RetryableCapabilityError` if every underlying failure in the exhausted
chain was itself `TRANSIENT`-classified, else `PermanentCapabilityError` — a mixed-flavor exhaustion MUST
default to retryable.

---

## 6. Retry

Four independent, nested boundaries exist end to end. Phase 6 contract §5 established the first three; this
contract adds the fourth and fifth, entirely inside the Routing Gateway:

```
WorkflowDefinition.timeout_seconds          (whole workflow, Phase 5)
  -> WorkflowStepDefinition.timeout_seconds     (one step, WorkflowRunner, Phase 5)
     -> CapabilityConfig.timeout_seconds           (one Capability.execute() call, Phase 6)
        -> provider-adapter HTTP timeout               (one real HTTP attempt, this contract)
           -> max_same_candidate_retries                  (nested inside one candidate's attempt, this contract)
```

**Binding rules:**

1. **Workflow-level retry** (`WorkflowRetryPolicy.max_attempts`) — owned by `WorkflowRunner`, retries an
   entire step (a fresh `Capability.execute()` call, and a fresh `capability_execution_id`, §16) on
   `RetryableCapabilityError`. Unchanged from Phase 5/6.
2. **Gateway-internal, same-candidate retry** — owned by `FallbackPolicy`, nested inside a single
   candidate's "attempt" (§5.4). Bounded by `max_same_candidate_retries` (default: 1). MUST use short,
   capped exponential backoff (base 250ms, cap 2s, full jitter) — deliberately shorter than
   `WorkflowRetryPolicy.retry_delay_seconds`, since it is retrying an already-available candidate within one
   Capability-internal timeout window, not waiting out an external condition across a new step attempt.
   MUST NEVER apply to a `PERMANENT_INCOMPATIBLE`-classified failure.
3. **Gateway-internal, cross-candidate "retry"** — traversing `FallbackPolicy`'s bounded sequence, one
   exhausted candidate at a time, IS this layer's retry mechanism. No separate mechanism exists or may be
   added.
4. **Retry-multiplication ceiling is boot-time enforced, not a convention.** At `CapabilityRegistry` seal
   time (or an equivalent boot-sequence validation), the process MUST compute, for every registered
   `Capability`'s effective configuration:
   `WorkflowRetryPolicy.max_attempts × max_fallback_attempts × (1 + max_same_candidate_retries)`
   and MUST raise a boot-time error — not merely log a warning — if this product exceeds a configured
   ceiling (recommended default: 30). This REQUIRES no runtime cost; it is pure arithmetic over
   already-loaded configuration.
5. **Idempotency.** A Gateway-internal retry/fallback attempt MUST always be a fresh request — nothing about
   a failed attempt is reused by the next one. This is safe for pure-generation calls. Tool-calling loops
   are the one place this safety does not automatically hold (§9.4).

---

## 7. Streaming

1. `generate_stream()` MUST route through the same §4.3 filter-and-rank sequence as `generate()`, with
   `requires_streaming=True` added to the hard filter — a candidate lacking `supports_streaming` MUST be
   filtered out before the first chunk is ever requested.
2. **Fallback boundary (caller-observable, not transport-dependent):** fallback MUST be permitted only
   *before* the Gateway's `generate_stream()` `AsyncIterator` has yielded its first `GenerateChunk` to the
   caller. Once the first `yield` has occurred, no fallback MUST occur — full stop, regardless of what the
   provider or any intermediary proxy is doing internally. This boundary is defined by the Gateway's own
   emission state, never by an inferred provider/transport-level signal.
3. Every `ProviderAdapter` MUST implement `generate_stream` by translating the provider's native streaming
   format into `GenerateChunk` — the same provider-neutral shape regardless of provider. A provider with no
   streaming support MUST raise `UnsupportedGatewayCapabilityError`.
4. A `Capability` consuming `generate_stream` MUST accumulate chunks itself and construct exactly one
   `CapabilityCall` from the completed (or failed) stream (`gateway_method: "generate_stream"`) — unchanged
   from Phase 6 contract §4.
5. `generate_stream` responses MUST NEVER be cached (§13.4).

---

## 8. Structured Outputs

1. When `response_mode == "json_schema"`, each `ProviderAdapter` MUST use the provider's native
   structured-output mechanism where one exists, never a bare prompt instruction. A candidate lacking
   `supports_structured_output` MUST already have been excluded by the §4.3 hard filter.
2. `Capability`-side Pydantic validation against the prompt's `output_schema` remains `Capability`'s
   exclusive responsibility (Phase 6 contract P10) — the Gateway MUST NOT attempt to validate
   `structured_output` against a `Capability`-specific schema.
3. **On a schema mismatch,** the retry MUST be composed entirely inside `Capability.execute()`: append a
   new, separate `Message(role="user", content=[...])` carrying the violation description to the existing
   message list, then call `generate()` again against the **same** resolved model — no re-routing. The
   `RenderedPrompt` content (system/rules/output_schema) MUST NEVER be edited or mutated in place; `(name,
   version)` MUST continue to reproduce identically forever, per Phase 6 contract §8's binding audit
   guarantee. The retry's `CapabilityCall.metadata` MUST record
   `{"retry_reason": "schema_validation_failure", "retried_call_id": <first attempt's call_id>}`.
4. A second mismatch MUST raise `ValidationCapabilityError` — non-retried, unchanged from Phase 6.

---

## 9. Tool Calling

### 9.1 `ToolExecutor` Protocol

```python
class ToolExecutionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tool_call_id: str                # derived: f"{capability_execution_id}:tool:{round_index}:{tool_index}"
    tool_call: ToolCall               # from LLMGateway's contract (Phase 6 §7) - name + arguments

class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["SUCCESS", "FAILED"]
    output: dict[str, Any] | None
    error: str | None = None

class ToolExecutor(Protocol):
    """Injected into a Capability exactly like LLMGateway/PromptRepository/BudgetGuard.
    Never called by CapabilityExecutor, LLMGateway, or a ProviderAdapter - those three
    only ever see ToolDefinition/ToolCall as opaque data."""
    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult: ...
```

`ToolExecutionRequest.tool_call_id` is the one genuinely new field this contract introduces anywhere — a
Phase 7-owned schema, not a change to Phase 6's `ToolCall`.

### 9.2 `ToolRegistry`

```python
class ToolRegistry:
    def register(self, definition: ToolDefinition, executor: ToolExecutor, idempotent: bool) -> None: ...
    def seal(self) -> None: ...
    def resolve(self, name: str) -> tuple[ToolDefinition, ToolExecutor, bool]: ...  # raises UnknownToolError
```

Sealed-after-boot, explicit-registration-only (P18). `idempotent` is stored alongside the registration —
NEVER added to Phase 6's `ToolDefinition` itself. A tool implementation MUST NOT import a provider SDK and
MUST NOT call another `Capability` (Phase 6 P4 extends unchanged — a tool is not a backdoor around
"capabilities never call each other").

### 9.3 The tool-use loop

The loop MUST live entirely inside `Capability.execute()`, never in `CapabilityExecutor`:

1. `generate()` with `tools=[...]` — round 1 of at most `MAX_TOOL_ROUNDS`.
2. A non-empty `tool_calls` response REQUIRES, for each call: construct a `ToolExecutionRequest`, resolve
   `(ToolDefinition, ToolExecutor, idempotent)` from `ToolRegistry`, and execute within the allotted
   timeout slice (§9.5).
3. Append results as `role="tool"` messages and call `generate()` again — a new, independent `request_id`
   (§16), the full request-routing sequence (§4.3) run again.
4. Repeat until `finish_reason == "stop"` or `MAX_TOOL_ROUNDS` is exceeded.
5. Every round's `generate()` call MUST become its own `CapabilityCall` entry in `CapabilityResult.calls`
   (Phase 6 contract §4, unchanged).

### 9.4 Round limit and idempotency

`MAX_TOOL_ROUNDS` (default: 3) is a Phase-7-owned constant, bounding internal `generate()`↔tool-execute
rounds within one `Capability.execute()` invocation. **It MUST NOT be the same counter as Workflow-level
`MAX_AGENT_ROUNDS`** — the two are numerically coincidental at their defaults, never conflated. Exceeding
`MAX_TOOL_ROUNDS` MUST raise `ToolRoundLimitExceededError` → `PermanentCapabilityError`.

For `idempotent=False` tools, if a Gateway-internal retry/fallback would re-attempt a `generate()` call made
*after* that tool already executed within the current `capability_execution_id`, the tool loop MUST NOT
silently retry within that attempt — it MUST let the failure propagate to Workflow-level retry (which
starts a fresh `capability_execution_id`). `idempotent=True` tools need no special handling. Automatic
dedup/idempotency-key generation is explicitly out of scope (§23).

### 9.5 Timeout budget

Each `ToolExecutor.execute()` call MUST be allocated no more than
`remaining_capability_timeout / (MAX_TOOL_ROUNDS - rounds_completed_so_far)` — an even, conservative split
guaranteeing later rounds, including the final `generate()` call that must process the tool's result, always
retain some budget.

---

## 10. Vision and Multimodal Input

1. Images and PDFs MUST use the existing `ContentPart(type="artifact_ref", artifact_ref=<uri>,
   mime_type=<mime>)` shape (Phase 6 contract §7) — no new Gateway method for either.
2. A `Capability` requiring vision MUST set `requires_vision=True` (and, where relevant,
   `input_image_count`/`input_pdf_page_count`) on `RoutingCriteria` (§4.1); the §4.3 hard filter guarantees
   only a vision-capable candidate within its declared `max_images_per_request` /
   `max_file_size_mb` / `max_pdf_pages` limits is ever selected.
3. How a given `ProviderAdapter` handles PDF pre-processing (native acceptance vs. client-side
   rasterization) is entirely adapter-internal — invisible above the Gateway boundary, not specified here.
4. Future audio input, audio output, and video remain representable via the existing `ContentPart`/
   `ArtifactRef` shapes without a Gateway contract change; `modalities` gaining `"video"` is an additive,
   non-breaking widening when a real capability needs it (Phase 6 contract §14 rule 6).

---

## 11. Embeddings

1. `LLMGateway.embed()` (Phase 6 contract §7) remains the sole primitive — no dedicated "Embedding
   Capability" is required or implied by this contract.
2. `ModelDescriptor.embedding_dimension` (§3) MUST be populated for every `supports_embeddings=True` model —
   the field a future `VectorStore` integration would require to prevent mixed-dimension index corruption.
3. Embedding cache keying and TTL are specified in §13.5.
4. A `VectorStore` Protocol (`upsert`/`search`) is named as a future boundary and is explicitly **not
   designed** by this contract (§23).

---

## 12. Moderation

1. `LLMGateway.moderate()` (Phase 6 contract §7) remains a distinct, explicit method. Pre-generation and
   post-generation moderation MUST be composed explicitly by the `Capability` — two ordinary Gateway calls,
   each producing its own `CapabilityCall` — never silently gated by the Gateway on the `Capability`'s
   behalf.
2. A provider lacking a moderation endpoint MUST raise `UnsupportedGatewayCapabilityError`. The Router MAY
   route a `moderate()` call to a different provider than the one handling `generate()` for the same
   invocation, via the same per-`gateway_method` routing criteria (§4.1) already defined — no special-casing
   required.
3. An inline `GenerateRequest.moderate_input`/`moderate_output` convenience flag is explicitly **not
   designed** by this contract (§23).

---

## 13. Caching

### 13.1 Pipeline position

The cache lookup MUST occur **after** routing resolves a specific candidate `(provider_id, model_id)`, and
**before** any cost estimate or `BudgetGuard` check for that candidate (§5.4, P15). Caching MUST NOT occur
before routing.

### 13.2 Cache key composition

```python
class CacheKeyComponents(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    normalized_request_hash: str        # sha256 of GenerateRequest with preferred_model/preferred_provider/
                                         # cache_policy/metadata excluded
    resolved_provider_id: str           # the actual candidate being attempted
    resolved_model_id: str              # the actual candidate being attempted
    model_config_fingerprint: str       # sha256 of {temperature, max_tokens, top_p, tool_choice, response_mode}
    prompt_fingerprint: str | None      # sha256 of (metadata["prompt_name"], metadata["prompt_version"]) when present
    tool_schema_fingerprint: str | None
    structured_output_schema_fingerprint: str | None
    multimodal_input_fingerprint: str | None   # sha256 of (artifact_ref, mime_type) pairs - never the binary

    def cache_key(self) -> str:
        parts = [str(self.schema_version), self.normalized_request_hash, self.resolved_provider_id,
                  self.resolved_model_id, self.model_config_fingerprint,
                  self.prompt_fingerprint or "-", self.tool_schema_fingerprint or "-",
                  self.structured_output_schema_fingerprint or "-", self.multimodal_input_fingerprint or "-"]
        return sha256("|".join(parts).encode()).hexdigest()
```

**Binding rule:** `resolved_provider_id` and `resolved_model_id` MUST be part of every response-cache key.
A cache key computed before routing resolves a candidate — or omitting either field — is a contract
violation: two calls routed to different models MUST NEVER collide on the same cache entry.

### 13.3 Invalidation

`schema_version` bump invalidates the entire cache atomically. A prompt republish (new `prompt_version`)
and a model deprecation/removal each naturally produce a new key or stop new writes, respectively — neither
REQUIRES active invalidation. **Response cache TTL: default 1 hour, configurable via `cache_policy`, never
TTL-free.**

### 13.4 Never cacheable

A response MUST NOT be cached if any of: `cache_policy != "read_write"`; `finish_reason != "stop"`;
`GenerateResponse.artifacts` is non-empty; the corresponding `moderate()` call (if made) flagged the
content. `generate_stream` responses MUST NEVER be cached under any condition.

### 13.5 Moderation and embedding caches

`moderate()` responses MAY be cached, same key structure minus tool/structured-output/multimodal
fingerprints, **default TTL 5 minutes**. Embedding cache key MUST be
`(schema_version, resolved_provider_id, resolved_model_id, sha256(input_text))`, TTL-free/long-TTL by
default — embeddings are deterministic per resolved model version.

### 13.6 Provider-native prompt caching

Entirely orthogonal to, and entirely internal to, each `ProviderAdapter` — invisible above the Gateway
boundary. The Gateway-level response cache and provider-native prompt caching (e.g. Anthropic
`cache_control`) MUST stack without interaction; neither needs to know the other exists.

### 13.7 Failure behavior

`CacheCoordinator` failures (backend unavailable) MUST always fail open — treated as a miss, never blocking
or erroring a call. This is settled and MUST NOT be conflated with `RateLimiter`'s genuinely open
fail-open/closed question (§28).

### 13.8 `CacheStore` Protocol

`CacheStore` is the provider-neutral backing-store abstraction `CacheCoordinator` writes through — already
named in `CacheCoordinator`'s §18 row ("Writes: `CacheStore` (Redis)"). This subsection formalizes that
existing reference; it does not introduce an eighteenth component (§18 remains seventeen rows) and does not
specify a concrete Redis implementation.

```python
class CacheStore(Protocol):
    async def get(self, key: str) -> bytes | None:
        """Returns the raw cached payload, or None. A miss - key never written, or expired since
        written - is a normal, first-class outcome, never an error; the two cases are indistinguishable
        and MUST remain so."""
        ...

    async def set(self, key: str, value: bytes, ttl_seconds: int | None) -> None:
        """Writes value under key. ttl_seconds=None means no expiry (the embedding cache default,
        §13.5); every other caller MUST pass an explicit TTL (§13.3, §13.5). Expiry is enforced by
        CacheStore itself (native TTL/EXPIRE semantics in a Redis-backed implementation)."""
        ...

    async def delete(self, key: str) -> None:
        """Removes key if present; deleting an absent key is a no-op, never an error. Provided for
        completeness and any future direct-invalidation need - current invalidation (§13.3) is achieved
        via schema_version key-namespacing, not by calling delete() in bulk."""
        ...
```

**Binding rules:**

1. **Namespace/key-schema boundary.** Composing the namespace and key schema (`schema_version` prefix,
   `cache_type` distinguishing response/moderation/embedding caches, §13.2/§13.5) is entirely
   `CacheCoordinator`'s responsibility. `CacheStore` receives and returns only an already-fully-composed
   opaque string key — it MUST NOT assemble, parse, or interpret key structure itself.
2. **Serialization boundary.** `CacheStore` stores and returns opaque `bytes` only. Serializing a
   `GenerateResponse` (or a moderation/embedding result) to bytes, and deserializing bytes back into the
   appropriate response type, is `CacheCoordinator`'s responsibility — `CacheStore` MUST NOT know the shape
   of what it stores.
3. **Cache-miss return semantics.** `get()` returns `None` for both "never written" and "expired since
   written." `CacheCoordinator` MUST treat both identically as a miss (§13.1, P15) — `CacheStore` MUST NOT
   expose any way to distinguish the two.
4. **Timeout/failure behavior.** Any `CacheStore` operation that times out or raises a backend-connectivity
   error MUST be caught by `CacheCoordinator`, never propagate to `FallbackPolicy` or above. Per §13.7,
   `CacheCoordinator` failures always fail open: a `CacheStore` failure on `get()` is treated as a miss; a
   failure on `set()` is swallowed (the response the caller already has simply is not cached); a failure on
   `delete()` is swallowed and logged.
5. **Scope of ignorance.** `CacheStore` MUST NOT know about routing, models, providers, `BudgetGuard`, or
   `CostTracker` — it is a pure key/value byte store with TTL support, with zero awareness of what a key
   means or why it is being read or written. This mirrors the opacity discipline `ProviderHealthStore` and
   `RateLimiter` already observe toward `ModelRegistry`/`ProviderRegistry` content (§18).

---

## 14. Rate Limiting

```python
class RateLimitKey(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    provider_id: str
    model_id: str | None = None       # None = provider-wide limit
    capability_name: str | None = None
    tenant_id: str | None = None      # forward-compatible only - not populated or enforced in Phase 7

class RateLimiter(Protocol):
    async def acquire(self, keys: list[RateLimitKey]) -> None:
        """Every key must have capacity, or none are consumed (atomic, all-or-nothing -
        never a partial throttle). Raises RateLimitExceededError naming which key(s)
        were exhausted."""
        ...
```

**Binding rules:**

1. The Gateway MUST construct and check a composite key list per call — provider-wide, model-specific, and
   capability-specific buckets together — not a single key. `acquire()` MUST consume all-or-nothing: if any
   one bucket lacks capacity, no bucket is decremented.
2. Token-bucket implementation, Redis-backed for cross-process consistency (P19) — an in-process-only
   limiter is FORBIDDEN at any deployment running more than one worker process.
3. `RateLimitExceededError` MUST map to `RetryableCapabilityError` at the `Capability`/`CapabilityExecutor`
   boundary — a rate-limit rejection is, by definition, transient.
4. `tenant_id` MUST remain unpopulated and unenforced — present only so the key shape does not need to
   change when multi-tenancy is eventually introduced.
5. Fail-open vs. fail-closed behavior on a Redis outage remains an open question (§28) — not resolved by
   this contract.

---

## 15. Cost Accounting

### 15.1 `CostEstimator`

A pure function — no I/O, no persistence, reading only `PricingCatalog` (§15.3) and the candidate
`ModelDescriptor`. Produces a `CostEstimate`:

```python
class CostEstimate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expected: Decimal
    worst_case: Decimal
    currency: str                     # mirrors the candidate ModelDescriptor.pricing_currency
    model_id: str                     # the candidate model this estimate was computed against
    pricing_tier_used: Literal["standard", "cached_input", "batch"]   # always "standard" - rule below
```

This formalizes the value already described below; it changes no field the estimator computes, only names
the shape precisely. `currency` and `model_id` are carried through unchanged from the candidate
`ModelDescriptor`/`PricingTier` that produced the estimate; `pricing_tier_used` is always `"standard"` per
the rule immediately below — it exists on the type so a future, explicitly-amended cache-eligible or batch
estimation path has somewhere to record a different tier without a schema change.

- **Input tokens (both figures):** `len(concatenated message text) / 4` — an explicitly approximate
  heuristic, never a billing-accuracy claim.
- **Output tokens, `worst_case`:** `request.max_tokens` if set, else `ModelDescriptor.max_output_tokens`.
- Estimation MUST always be computed against the model's `"standard"` `PricingTier` (§3) — never the
  `"cached_input"` or `"batch"` tier, even when the request might qualify, since Phase 7 performs no
  automatic cache-eligibility detection. Overestimating is the required, safe default.

### 15.2 `BudgetGuard` sequencing (Amendment C — see §25 for the full amendment text)

`BudgetGuard.check(capability_name, priority, worst_case) -> approve | deny` MUST be invoked by the Routing
Gateway (specifically, `FallbackPolicy`, §5.4), once per fallback candidate, on a cache miss, immediately
before that candidate is dispatched. `BudgetGuard.check()` MUST gate on `worst_case`, never `expected`.
`expected` is recorded only for the `cost_estimate_variance` observability event (§16). `Capability` MUST
NEVER call `BudgetGuard` directly (P16).

Full sequence, binding:

```
Capability calls LLMGateway.generate(request)
  -> RateLimiter check (§14)
  -> RoutingEngine produces ranked candidates (§4.3 steps 1-6)
  -> FallbackPolicy produces the bounded attempt sequence (§5.3)
  -> FOR EACH candidate, in order:
       CacheCoordinator lookup (§13) -> hit: return (no cost estimate, no BudgetGuard check)
       IF miss:
         CostEstimator.estimate(candidate, request) -> CostEstimate(expected, worst_case)
         BudgetGuard.check(capability_name, priority, worst_case) -> approve | deny
         IF approved: dispatch to ProviderAdapter (§5.4)
         IF denied: continue to next candidate
  -> exhausted/denied -> AllProvidersFailedError / BudgetExceededError (§5.5)
  -> on success: actual CapabilityUsage from the provider response
  -> CostTracker.record(actual_usage, resolved_model, ...)   <- post-hoc, write-only, ACTUAL usage only
```

### 15.3 `PricingCatalog`

```python
class PricingCatalog(Protocol):
    def get_tier(self, model_id: str,
                 condition: Literal["standard", "cached_input", "batch"] = "standard") -> PricingTier:
        """Reads ModelRegistry.pricing_tiers for model_id. Raises UnknownModelPricingError if the
        model or that specific tier condition is absent - unreachable for condition="standard" in
        practice, given §3 rule 3's requirement that every model declare a "standard" tier."""
        ...
```

A thin, read-only accessor over `ModelRegistry.pricing_tiers` — the single source of truth for pricing.
`CostTracker` MUST read pricing from `PricingCatalog`, never maintain an independent price table (this
supersedes any prior reading of Phase 6 contract §9's "its own model-price table" wording — the price
number's source is `ModelRegistry`; `CostTracker`'s exclusive ownership of *writing* cost is unchanged).

### 15.4 Post-hoc recording

`CostTracker.record()` MUST always receive the actual, final, successful attempt's `CapabilityUsage` —
never a sum across internal fallback/retry attempts, never a failed attempt's usage. If `actual` deviates
materially from `worst_case`, a `cost_estimate_variance` observability event MUST fire (§16) — a tuning
signal, never a call-blocking condition. Nothing blocks an already-completed response because its actual
cost exceeded its estimate.

### 15.5 Derived guarantees (no special-casing required)

- **Streaming:** the same per-candidate `CostEstimator`/`BudgetGuard` check runs once, before the stream
  opens. No mid-stream re-check exists.
- **Tool loops:** each `generate()` call inside a tool-use loop is independently subject to §15.2's full
  sequence — a later round MAY be legitimately denied if earlier rounds already exhausted the budget. Zero
  tool-loop-specific cost code is required.
- **Batch requests:** not designed (§23). The expected future shape is one `BudgetGuard.check()` against a
  batch-aware `CostEstimator` sum, never one check per item.

### 15.6 Shadow cost (named, partially mitigated, not closed)

Real provider spend from a failed Gateway-internal attempt (§5.4's `TRANSIENT` branch, or a cancellation
that could not abort server-side, §2 rule 9) MAY never reach `CostTracker`, because `CostTracker` only ever
records the *final, successful* attempt's usage. The `cost_estimate_variance` event (§16) gives
observability into this risk; an attempt-level telemetry sink that would fully close it is explicitly
**not designed** by this contract (§23).

---

## 16. Observability

### 16.1 Identifier hierarchy

| Identifier | Source | Ownership |
|---|---|---|
| `trace_id` | `CapabilityContext.runtime.task_id` (Phase 6, reused) | Spans every step and every Workflow-level retry within one `EditorialTask` |
| `capability_execution_id` | Derived: `f"{task_id}:{capability_name}:{attempt}"` | One per `Capability.execute()` invocation, fresh on every Workflow-level retry |
| `request_id` | `CapabilityCall.call_id` (Phase 6, reused), passed through as `GenerateRequest.metadata["request_id"]` | One per `LLMGateway` method invocation |
| `provider_attempt_id` | Derived: `f"{request_id}:{attempt_index}"` | One per `FallbackPolicy` candidate attempt within one `request_id` |
| `model_route_id` | Derived: `f"{provider_attempt_id}:{provider_id}:{model_id}"` | The specific provider+model an attempt targeted |
| `tool_call_id` | `ToolExecutionRequest.tool_call_id` (§9.1, new field), derived: `f"{capability_execution_id}:tool:{round_index}:{tool_index}"` | One per tool invocation |

```
trace_id (task_id)
  └─ capability_execution_id (one per execute() attempt)
       └─ request_id (one per Gateway method invocation)
            └─ provider_attempt_id (one per FallbackPolicy candidate)
                 └─ model_route_id
       └─ tool_call_id (references the request_id whose response produced the ToolCall)
```

```python
class ObservabilityContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str
    capability_execution_id: str
    request_id: str | None = None    # unset until a Gateway method invocation begins (§16.1 table)
```

**Binding rule:** `ObservabilityContext` — a lightweight, immutable, read-only value object carrying
`trace_id`/`capability_execution_id`/`request_id` — MUST be threaded through every layer via explicit
parameter passing at construction time. It MUST NEVER become an implicit thread-local/contextvar, and it
MUST NEVER itself emit anything — each layer that emits a log/metric reads whatever ids it needs from the
context it was handed. `provider_attempt_id`/`model_route_id`/`tool_call_id` are derived strings (per the
table above), never additional fields on this type — `ObservabilityContext` carries only the three ids that
exist prior to, and independent of, any specific attempt.

### 16.2 Structured events and metrics — minimum emittable contract

| Category | Emitted by | Minimum fields (beyond ids) |
|---|---|---|
| Routing decision | `RoutingEngine` | `objective`, `candidates_considered`, `candidates_after_hard_filter`, `chosen_rank` |
| Routing policy failure | `RoutingEngine` | `objective`, `failed_policy_name`, `error_type`, `fallback_policy_used` (§4.4) |
| Fallback | `FallbackPolicy` | `attempt_index`, `candidate_provider_id`, `candidate_model_id`, `reason` |
| Retry | `FallbackPolicy` | `same_candidate_retry_index`, `backoff_ms` |
| Timeout | `ProviderAdapter` | `boundary`, `configured_timeout_ms`, `elapsed_ms` |
| Rate limit | `RateLimiter` | `rate_limit_key`, `outcome` |
| Cache hit/miss | `CacheCoordinator` | `cache_type`, `outcome`, `key_schema_version` |
| Budget denial | `BudgetGuard` | `capability_name`, `priority`, `worst_case_estimate`, `expected_estimate` |
| Provider error | `ProviderAdapter` | `failure_class`, `provider_error_code` (adapter-normalized) |
| Schema-validation failure | `Capability` | `schema_name`, `retry_attempted` |
| Tool call | `ToolExecutor` | `tool_name`, `outcome` |
| Streaming interruption | `ProviderAdapter` | `chunks_emitted_before_failure`, `had_final_chunk` |
| Token usage | `Capability` (`CapabilityCall` assembly) | `input_tokens`, `output_tokens`, `unit_type` |
| Cost | `CostTracker` + `CostEstimator` (`cost_estimate_variance`) | `actual_cost`, `expected_estimate`, `worst_case_estimate`, `variance_pct` |
| Latency | `ProviderAdapter` + `Capability` | `attempt_latency_ms`, `total_call_latency_ms` |

**Binding rule:** this table defines the REQUIRED shape — ids, event categories, minimum fields — not a
transport. The actual backend (OpenTelemetry, Prometheus, a logging pipeline) is unspecified and remains an
additive integration choice, never a redesign of what any layer already emits.

---

## 17. Configuration, Secrets, and Capability Negotiation

### 17.1 Reload behavior

No registry in this contract (`ProviderRegistry`, `ModelRegistry`, `ToolRegistry`, `RoutingPolicyRegistry`)
supports live reload (P18). Every configuration change — new provider, new model, credential rotation,
pricing update, routing policy/weight change — REQUIRES a process restart. The **one** exception is
`ProviderHealthStore`'s TTL-based health state (§18), which is runtime state, not configuration.

### 17.2 Structured credentials

```python
class ProviderCredential(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    api_key: SecretStr | None = None
    service_account_json: SecretStr | None = None
    access_key_id: SecretStr | None = None
    secret_access_key: SecretStr | None = None
    region: str | None = None
    base_url: str | None = None
```

A superset bag of optional fields — deliberately not one type per provider. Each provider's factory
function MUST validate that the *specific* subset it needs is present; this is a provider-specific concern
kept out of the shared type. `enabled_providers: list[str]` gates which providers are constructed at all
(§2 rule 2).

### 17.3 `CapabilityNegotiator`

```python
class CapabilityNegotiator(Protocol):
    async def verify(self, provider_id: str, model_id: str, adapter: ProviderAdapter,
                      claimed: ModelDescriptor) -> "NegotiationResult": ...

class NegotiationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    verified_flags: dict[str, bool]
```

MUST run once per `(provider_id, model_id)` pair, at boot, after both `ProviderRegistry` and `ModelRegistry`
seal, gated behind `Settings.verify_capabilities_at_boot: bool = False`. When enabled, it issues cheap,
deterministic behavioral probes per claimed capability flag; a mismatch marks that specific flag
`verified=False` in `ProviderHealthStore`, and `RoutingEngine`'s hard filter (§4.3 step 1) MUST additionally
exclude a candidate for whichever *specific* requirement failed verification — never a whole-model
exclusion. `CapabilityNegotiator` MUST run entirely outside the request path and MUST NEVER block boot on a
verification failure — it only narrows eligibility.

---

## 18. Component Boundaries

Seventeen components. Each row is binding: a component MUST NOT exceed its "Must NOT depend on" column, and
MUST implement the stated failure behavior exactly.

| Component | Owns | Reads | Writes | Must NOT depend on | State | Failure behavior |
|---|---|---|---|---|---|---|
| **ProviderAdapter** | Translation to/from one provider's wire format; that provider's SDK client | Already-resolved `GenerateRequest`/etc. | Nothing persisted | `ProviderRegistry`, `ModelRegistry`, `RoutingEngine`, `BudgetGuard`, `CostTracker`, any other `ProviderAdapter` | Immutable per-instance HTTP client; no request-scoped mutable state | Catches every SDK exception, redacts credentials, re-raises via this contract's typed hierarchy |
| **ProviderRegistry** | `provider_id -> (ProviderDescriptor, ProviderAdapter)` | `Settings` — boot only | Nothing after `seal()` | `ModelRegistry`, `RoutingEngine`, any Capability-layer component | Immutable after boot (sealed) | Typed registry errors; boot fails loud on an unrecognized `enabled_providers` entry |
| **ModelRegistry** | `model_id -> ModelDescriptor` | Static declarative Python module — boot only | Nothing after `seal()` | `ProviderRegistry` (opaque string only), any runtime component | Immutable after boot (sealed) | Boot-time `RegistryConsistencyError` on an unresolvable `provider_id` |
| **RoutingPolicy** | One ranking algorithm for one objective | `candidates`, `criteria`, `RoutingTelemetrySnapshot` | Nothing — pure function | Any I/O, any registry directly, `BudgetGuard`, `CostTracker` | Stateless | Exceptions isolated by `RoutingEngine`, never propagate |
| **RoutingEngine** | The §4.3 filter-and-rank pipeline; `RoutingPolicyRegistry`; `LatencyTracker` invocation | `ModelRegistry`, `ProviderRegistry.is_enabled()`, `ProviderHealthStore`, `LatencyTracker`, the resolved `RoutingPolicy` | Nothing persisted; emits routing-decision events | `ProviderAdapter` directly, `BudgetGuard`, `CostTracker` | Holds sealed registries by reference | `NoRoutableCandidateError` on zero survivors |
| **LatencyTracker** | The rolling p50-latency-per-model sample | Nothing external — updated from real call outcomes | Itself, one sample per completed attempt | `RoutingPolicy` (one-directional), `ModelRegistry`/`ProviderRegistry` content | Runtime, Redis-backed | No data / backend down → snapshot omits the model; `RoutingPolicy` falls back to `quality_tier` |
| **FallbackPolicy** | Eligibility filtering + dispatch loop + failure classification | `RoutingEngine`'s output, `CacheCoordinator`, `CostEstimator`, `BudgetGuard`, `ProviderRegistry.resolve()` | `ProviderHealthStore` | `CostTracker` (post-hoc only), `Capability`/`CapabilityExecutor` | Request-scoped attempted-pairs set; cross-call state lives in `ProviderHealthStore` | `AllProvidersFailedError` with reason code on exhaustion |
| **RateLimiter** | Token-bucket state per key | The key list passed in | Bucket counters (Redis) | `ModelRegistry`/`ProviderRegistry` (opaque strings only) | Runtime, Redis-backed, cross-process | `RateLimitExceededError`; Redis-unavailable behavior open (§28) |
| **CacheCoordinator** | Response/embedding/moderation cache read+write; key composition | `CacheKeyComponents` inputs | `CacheStore` (Redis) | `BudgetGuard`, `CostTracker`, `RoutingEngine` internals | Runtime, Redis-backed | Always fails open (treat as miss) |
| **BudgetGuard** | Pre-flight approve/deny only | `CostTracker`'s ledger; the `worst_case` estimate, on a cache miss only | Nothing — read-only | `LLMGateway`/`ProviderAdapter`, `CostEstimator` internals | Stateless; reads externally-owned ledger | `BudgetExceededError`, non-retryable, per candidate; never invoked for a cache hit |
| **CostEstimator** | Producing `(expected, worst_case)`, on a cache miss only | `PricingCatalog`, the candidate `ModelDescriptor`, request fields | Nothing — pure function | `CostTracker`, `BudgetGuard` (one-directional) | Stateless | A missing pricing tier is a boot-time `ModelRegistry` data error |
| **CostTracker** | Post-hoc, write-only cost recording; the spend ledger `BudgetGuard` reads | `PricingCatalog`, actual `CapabilityUsage` | The spend ledger; future `AIExecution` rows (Amendment B, still deferred) | `LLMGateway`/`ProviderAdapter`, `BudgetGuard` (one-directional) | Runtime, Redis-backed for cross-process consistency | Write failure is a cost-audit data-loss risk, not call-blocking; ledger-read failure shares §28's open question |
| **ObservabilityContext** | Nothing — a read-only value object carrying the id hierarchy | Nothing | Nothing (passed, not consulted) | Any stateful component; must never become a global/thread-local | Immutable, constructed once per id, threaded explicitly | N/A |
| **`LLMGateway` implementation boundary** (the "Routing Gateway") | Composing every component above into the unchanged `LLMGateway` Protocol surface | Everything above | Nothing directly — delegates to owning components | `Capability`/`CapabilityExecutor`/`Workflow` | Holds every component by reference, constructed once at boot | Never lets an internal exception cross unclassified |
| **ProviderHealthStore** | Runtime `(provider_id, model_id) -> {unhealthy_until, runtime_unavailable, verified_flags}` | Nothing external | Itself — from `FallbackPolicy` (health) and `CapabilityNegotiator` (verified flags) | `ModelRegistry`/`ProviderRegistry` content | The one genuinely "hot" runtime state; Redis-backed | Backend down → fail open (assume healthy) |
| **PricingCatalog** | Nothing new — a thin read accessor over `ModelRegistry.pricing_tiers` | `ModelRegistry` | Nothing | `CostTracker`, `BudgetGuard`, `CostEstimator` | Immutable, mirrors `ModelRegistry`'s sealed state | `UnknownModelPricingError` — unreachable given §3 rule 7 |
| **CapabilityNegotiator** | The boot-time behavioral verification pass | `ProviderRegistry`, `ModelRegistry`; issues real calls to each `ProviderAdapter` | `ProviderHealthStore.verified_flags` | `RoutingEngine`, `BudgetGuard`, `CostTracker` | None of its own | Narrows eligibility per-flag; never blocks boot |

---

## 19. Capability Integration

1. `Capability.execute(context: CapabilityContext) -> CapabilityResult` (Phase 6 contract §2) is
   UNCHANGED — this contract adds no new parameter, no new call site, and no new obligation on the
   `Capability` author beyond what Amendment C already implies (never call `BudgetGuard` directly, §25).
2. `build_registry(gateway: LLMGateway, prompt_repository: PromptRepository, budget_guard: BudgetGuard,
   tool_registry: ToolRegistry) -> CapabilityRegistry` MUST be the sole boot-sequence entry point that
   constructs every `Capability` with its dependencies injected. This fills a boot-sequence gap the Phase 6
   planning sketch left unspecified — it is not a change to any binding Phase 6 Protocol.
3. Boot order is fixed: `ProviderRegistry` and `ModelRegistry` seal → boot-time cross-registry validation
   (§3 rule 7) → optional `CapabilityNegotiator.verify()` pass (§17.3) → every §18 component constructed →
   the `LLMGateway` implementation boundary assembled → `build_registry()` called → `CapabilityRegistry`
   sealed → process ready to serve.
4. `CapabilityExecutor` (Phase 6 contract §5) is UNCHANGED by this contract — it holds no reference to any
   component named in §18, and continues to interact with a `Capability` exclusively through
   `Capability.execute()`.

---

## 20. Lifecycles

### 20.1 Provider onboarding (the binding runbook)

1. Write `integrations/llm_gateway/providers/<provider>_adapter.py` implementing `LLMGateway`.
   `generate()` alone is sufficient to onboard; every other method MAY raise
   `UnsupportedGatewayCapabilityError` until implemented.
2. Pass `tests/contract/test_provider_adapter_contract.py` (test-design guidance: v1 §19) before step 3.
3. Add credential fields via `ProviderCredential` (§17.2) to `core/config.py` and `.env.example`.
4. Add `ModelDescriptor` entries for every routable model, including `pricing_tiers`, `quality_tier`, and
   modality limits.
5. Leave `provider_id` **out** of `enabled_providers` initially — registered in code, inert in production.
6. Deploy to staging; if `verify_capabilities_at_boot=True`, confirm `CapabilityNegotiator` reports no
   unexpected mismatches.
7. Add `provider_id` to `enabled_providers`, restart — the only way a provider goes live.
8. Optionally use `WeightedSplitPolicy` (§4.7) to ramp traffic rather than a full cutover.

### 20.2 Provider startup/shutdown

**Startup** follows the fixed boot order in §19 rule 3.

**Shutdown:** stop accepting new `Capability.execute()` invocations (orchestration-layer concern, outside
this contract); in-flight `ProviderAdapter` calls complete or cancel per §2 rule 9; no registry teardown is
required — registries are in-memory and process-scoped.

### 20.3 Model registration

New `ModelDescriptor` entry, human-reviewed (§3 rule 8), deployed and restarted (no live registration).
`availability` starts at `"beta"` or `"ga"` per author judgment.

### 20.4 Model deprecation

Set `availability = "deprecated"`, `deprecation_note`, `replacement_model_id` (§3 rule 9); deploy and
restart. Capabilities pinned to it migrate to `replacement_model_id` at their own pace. Once unreferenced
and past a retention period, `availability = "unavailable"` and eventual removal — historical
`AIExecution.model` rows referencing it persist forever, a forward requirement for the future real-persistence
phase (§23).

### 20.5 Request routing

`Capability` calls `LLMGateway.generate()` → `RateLimiter.acquire()` (§14) → `RoutingEngine`'s §4.3
sequence → `FallbackPolicy`'s §5.3 eligibility filtering → the §5.4 dispatch loop.

### 20.6 Fallback

Per candidate: cache check (§13.1) → on miss, cost estimate and `BudgetGuard` approval (§15.2) → dispatch,
with the same-candidate retry nested inside the attempt (§6) → on failure, classify (§5.2) and continue or
raise (§5.4) → exhaustion (§5.5).

### 20.7 Retry

The four boundaries of §6, composed exactly as specified there — no additional retry mechanism exists
anywhere in this contract.

### 20.8 Streaming

`generate_stream()` follows §20.5's routing steps with `requires_streaming=True`; fallback bounded by §7
rule 2; one `CapabilityCall` per completed or failed stream; never cached (§13.4).

### 20.9 Tool calling

The §9.3 loop, bounded by `MAX_TOOL_ROUNDS` and the §9.5 timeout split, each round independently subject to
the full §15.2 cost sequence.

### 20.10 Structured-output validation

§8's provider-native-JSON-mode-then-Capability-validation sequence, with the §8 rule 3 correction-message
retry on mismatch.

### 20.11 Cost estimation and recording

The §15.2 sequence, per candidate, inside the dispatch loop — cache lookup first, estimate and approve on a
miss, record actual usage post-hoc (§15.4).

### 20.12 Failure and cancellation

Every failure classifies to a `FailureClass` value or a dedicated typed exception (§5.2, §5.5, §14, §17.1)
before crossing the `LLMGateway` implementation boundary (§18). `Capability` maps to the Phase 6
`CapabilityError` hierarchy (Phase 6 contract §5's mapping rule, v1 §7's mixed-flavor exhaustion default,
unchanged). Cancellation propagates per §2 rule 9.

---

## 21. Scalability Guarantees

| Dimension | Stays in-process | MUST be distributed (Redis) | Stable interfaces |
|---|---|---|---|
| 10 providers | `ProviderRegistry` (dict, O(1), sealed) | — | `ProviderAdapter = LLMGateway` recursion (§2) |
| 100 models | `ModelRegistry` (dict, O(1) resolve; O(n) `filter()`) | — | `ModelDescriptor` schema (§3, considered stable) |
| 50 capabilities | `RoutingCriteria.capability_name` as an opaque string throughout | — | `CapabilityRegistry`/`build_registry()` wiring (§19) |
| Millions of requests | `RoutingPolicy.rank()`, `FallbackPolicy` eligibility filtering — pure, sub-millisecond | `RateLimiter`, `CacheCoordinator`, `ProviderHealthStore`, `LatencyTracker`, `CostTracker`'s spend ledger | `LLMGateway` Protocol surface (Phase 6, untouched); `RateLimiter.acquire()`'s list-based signature |

**Binding rule:** every component listed in the "MUST be distributed" column REQUIRES a cross-process-consistent
backing store at any deployment running more than one worker process (P19). A process-local implementation
of any of these five is a contract violation, not an acceptable simplification, at the scale this contract
targets.

---

## 22. Extension Rules

1. **Adding a provider** REQUIRES no change to any Protocol, `RoutingEngine`, `FallbackPolicy`, or any other
   §18 component — write an adapter (§2), register it, follow §20.1. Zero changes to `LLMGateway`'s request/
   response types (Phase 6 contract §12, restated here for this layer).
2. **Adding a model** REQUIRES no code change beyond a `ModelDescriptor` entry (§3) — `model_id` is opaque
   end to end.
3. **Adding a routing objective** REQUIRES only a new `RoutingPolicy` registered through
   `RoutingPolicyRegistry` (§4.5) — zero changes to `RoutingEngine` or `RoutingCriteria`'s shape.
4. **Adding a tool** REQUIRES only a `ToolRegistry.register()` call (§9.2) — zero changes to
   `CapabilityExecutor` or the tool-use loop's shape.
5. **No addition under 1–4 above may introduce a new component beyond the seventeen named in §18**, change
   any Protocol signature named in this contract, or touch any Phase 6 contract text, without a formal
   amendment (§26).

---

## 23. Explicit Non-Goals

The following are intentionally **not** solved by this contract and MUST NOT be implemented as a side
effect of Phase 7 work:

- **True zero-downtime provider hot-swap.** Restart-required, config-only swapping is the guaranteed
  mechanism (§17.1); `WeightedSplitPolicy` (§4.7) is the closest this contract gets to gradual, and it is
  still restart-gated.
- **Automatic/managed canary rollback** for `WeightedSplitPolicy` — manual weight editing only (§4.7).
- **Batch inference** (`generate_batch()`) and **async/job-polling inference** — both require new Protocol
  shapes not designed here (§15.5).
- **Live, per-session dynamic MCP tool discovery** without a restart — only the static, boot-time snapshot
  form of MCP integration is supported (Tier 1); dynamic discovery (Tier 2) genuinely conflicts with P18 and
  requires a dedicated, separately-approved "hot registry" design.
- **`VectorStore` integration** (§11) — named as a future boundary, not designed.
- **Inline Gateway-side moderation composition** (`moderate_input`/`moderate_output` flags, §12) — explicit
  two-call composition is the only supported pattern.
- **Automatic idempotency-key generation / dedup** for tools (§9.4) — the binary `idempotent` flag and its
  no-retry-within-attempt rule are the only mechanism.
- **Attempt-level cost telemetry** that would fully close the shadow-cost gap (§15.6) — the
  `cost_estimate_variance` event provides visibility only.
- **Always-mandatory `CapabilityNegotiator` verification** — opt-in via `verify_capabilities_at_boot` only
  (§17.3), pending §28 Q5.
- Every non-goal already named in Phase 6 contract §13 remains a non-goal here, unchanged.

---

## 24. Canonical Rules

These rules are mandatory for all Phase 7 implementation and are the checklist future code review
validates against.

1. No file outside `integrations/llm_gateway/providers/` imports a provider SDK, directly or transitively.
2. A `ProviderAdapter` is exactly an `LLMGateway` implementation — no second, parallel interface exists.
3. Only the `LLMGateway` implementation boundary holds references to every §18 component; no other
   component's dependency set exceeds its own §18 row.
4. `Capability` never learns that routing, fallback, retry, rate limiting, caching, cost estimation, or
   budget approval happened — it observes only a `GenerateResponse`/error and exactly one `CapabilityCall`
   per `LLMGateway` invocation.
5. A cache hit is served without invoking `CostEstimator` or `BudgetGuard` (P15).
6. `BudgetGuard.check()` is invoked only by the Routing Gateway, per fallback candidate, on a cache miss —
   `Capability` never calls it directly (Amendment C, §25).
7. `RoutingPolicy.rank()` performs no I/O and reads no external mutable state directly; `WeightedSplitPolicy`
   is the sole named exception to determinism, never to purity.
8. `ProviderRegistry`, `ModelRegistry`, `ToolRegistry`, `RoutingPolicyRegistry` are explicit-registration-only
   and sealed-after-boot; none supports live reload.
9. `ProviderHealthStore`, `RateLimiter`, `CacheCoordinator`, `LatencyTracker`, and `CostTracker`'s ledger are
   Redis-backed for cross-process consistency — never process-local at scale.
10. The fallback cost bound is anchored to the cheapest price in the filtered candidate set, never to the
    first-ranked candidate's price.
11. `FallbackPolicy` never starts a new attempt cycle for an exhausted `(provider_id, model_id)` pair within
    one call; the same-candidate retry (§6) is nested inside one candidate's attempt, not a rule it
    contradicts.
12. The response-cache key includes the resolved `provider_id` and `model_id`, never only the pre-routing
    request.
13. The retry-multiplication ceiling is enforced at boot, not left as a reviewed-by-convention number.
14. A structured-output retry never mutates `RenderedPrompt` content — the correction is a new, appended
    `Message`.
15. `MAX_TOOL_ROUNDS` is never the same counter as Workflow-level `MAX_AGENT_ROUNDS`.
16. `pricing_tiers` is the sole source of pricing data; `CostTracker` reads it via `PricingCatalog`, never
    maintaining an independent price table.
17. Every provider SDK exception is caught, credential-redacted, and translated to this contract's typed
    hierarchy before crossing the `LLMGateway` boundary.
18. No component named in §18 may be added to, removed from, or renamed on this contract's list of
    seventeen without a formal amendment (§26).
19. Every Phase 6 contract principle, forbidden edge, and canonical rule remains binding except where
    Amendment C (§25) explicitly supersedes it.
20. Nothing in §23's non-goal list is implemented as a side effect of any in-scope Phase 7 work.

---

## 25. Amendment C — BudgetGuard Sequencing Relocation (Binding)

**Status: approved amendment, binding on this contract exactly as §§1–24 above. This amendment modifies
Phase 6 contract §9 ("Cost Tracking Contract") and is the only place this document, or any Phase 7 document,
touches Phase 6 contract text.**

**Root cause this amendment resolves:** Phase 6 contract §9 has `Capability` call `BudgetGuard.check()`
once, pre-flight, before calling `LLMGateway.generate()`. But `Capability` does not choose the final model —
`RoutingEngine` does, inside the Gateway, after the check has already happened. The check's input (an
estimate for a model `Capability` could only guess at) had no defined relationship to the model actually
used, on the very first attempt, not only during fallback.

**Binding text:** `BudgetGuard.check()` MUST be invoked by the Routing Gateway (specifically,
`FallbackPolicy`, §5.4), once per fallback candidate, on a cache miss, immediately before that candidate is
dispatched to a `ProviderAdapter` — **never** by `Capability`, and **never** once per logical call.
`Capability` MUST NOT hold a `BudgetGuard` dependency and MUST NOT call it under any circumstance.

**What is preserved, unchanged, from Phase 6 contract §9:**

1. `BudgetGuard`'s own contract remains pre-flight and read-only: given `(capability_name, priority,
   worst_case_estimate)`, it consults already-recorded spend (written exclusively by `CostTracker`) and
   either allows or raises `BudgetExceededError`.
2. `BudgetGuard` MUST NOT write spend data. `CostTracker` retains exclusive ownership of writing cost.
3. Budget checking (`BudgetGuard`) and cost recording (`CostTracker`) remain two separate components with
   two separate responsibilities (Phase 6 P5, unchanged).
4. The forbidden edge `BudgetGuard → LLMGateway` remains forbidden — this amendment adds the edge
   `LLMGateway (Routing Gateway) → BudgetGuard`, which Phase 6 never forbade, only did not anticipate.

**What changes:**

1. The call site moves from `Capability` to the Routing Gateway (`FallbackPolicy`).
2. The check moves from once-per-logical-call to once-per-fallback-candidate (§15.2), always on a cache
   miss (§13.1).
3. `CostEstimator` (§15.1) — new, not present in Phase 6 — is the sole producer of the `worst_case` estimate
   `BudgetGuard.check()` consumes.

**Why this is a strengthening, not a weakening, of Phase 6 P5:** centralization intent is preserved and
sharpened — budget enforcement now happens in exactly one place, for every attempt, and cannot be forgotten
by a `Capability` author, since `Capability` no longer has a manual step to remember at all.

**Binding conditions on this amendment, all of which apply simultaneously:**

1. This amendment does not reopen or redesign any other part of Phase 6 contract §9 — the pipeline stage
   table, the Capability/BudgetGuard/LLMGateway/CostTracker responsibility split, and the "budget checking
   and cost recording remain two separate components" rule are all unchanged in substance.
2. No future Phase 7 work may reintroduce a `Capability → BudgetGuard` call site without a further, separately-
   approved amendment.
3. The forbidden-edge table in Phase 6 contract §1 is read as amended by this document's §1 table (the
   Phase 7 extension), not rewritten in place in the Phase 6 contract file itself.

---

## 26. Amendment Rules

1. **Scope.** An amendment to this contract MAY change: a Protocol signature named herein, a component's
   ownership boundary (§18), a canonical rule (§24), or Phase 6 contract text (in the manner Amendment C
   demonstrates, §25). An amendment MUST NOT silently redefine a term this contract has already given a
   precise meaning to (e.g., "pure" per §4.2) without explicitly superseding that definition.
2. **Trigger.** An amendment is warranted only when a **Critical** or **Major** defect is found in this
   contract itself — the same bar `docs/phase7_principal_architect_review.md` and
   `docs/phase7_consistency_review.md` applied to the planning baseline. A stylistic preference, or a
   discovery that an alternative design would have been nicer, does NOT warrant an amendment.
3. **Form and placement.** An amendment MUST be a new, separately lettered top-level section appended at the
   **true end of this document** — after §29 (Reviewer Ratification Log), currently the last section — never
   inserted between existing sections (not between §25 and §26, nor anywhere else in the middle of the
   document), and never an in-place edit to §§1–24 or to a prior amendment's text. No existing section is
   ever renumbered to make room: Amendment C remains §25 forever; the next amendment is Amendment D, appended
   as a new final section, and so on for every amendment after it. Each amendment MUST explicitly name, in
   its own text, the section(s) of this contract — or of the Phase 6 contract, per Amendment C's precedent
   (§25) — that it modifies. Each amendment MUST state: the root cause it resolves, the exact binding text,
   what is preserved unchanged, what changes, and binding conditions — mirroring §25's structure. The
   Reviewer Ratification Log (§29) is a distinct, separate append-only record from the amendment sequence: a
   ratification confirmation is appended as a new row inside §29 itself, never as a new lettered amendment
   section; conversely, an amendment is never appended as a row inside §29 — the two append-only mechanisms
   never merge.
4. **Approval.** An amendment is binding only once explicitly approved, in the same sense Amendments A, B
   (Phase 6), and C (§25, this contract) were approved — a proposal alone, however well-reasoned, does not
   amend this contract.
5. **Non-goals do not silently expire.** Removing an item from §23 REQUIRES an amendment, not merely a
   later implementation that happens to build it.

---

## 27. Compatibility Guarantees

1. **`LLMGateway` Protocol surface (Phase 6 contract §7) is untouched by this contract** — every method
   signature, every request/response type, is exactly as Phase 6 defined it. Routing, fallback, retry, rate
   limiting, and caching are additive machinery behind an unchanged public surface.
2. **`Capability`'s public-facing API is unchanged**, with one net *simplification*: `Capability` no longer
   calls `BudgetGuard` directly (Amendment C) — one fewer manual step, not one more.
3. **`CapabilityContext`/`CapabilityResult`/`CapabilityCall` (Phase 6 contract §3–§4) are untouched.** Every
   mechanism this contract adds — tool loops, structured-output retries, streaming — expresses itself
   through the existing `calls: list[CapabilityCall]` shape Phase 6 already designed for exactly this
   purpose.
4. **`ModelDescriptor` (§3) is considered stable** as of this contract — every schema gap found across the
   review/consistency passes (pricing tiers, `quality_tier`, `embedding_dimension`, modality limits,
   deprecation fields) is now closed. A future field addition MUST be additive and optional, consistent with
   Phase 6 contract §14 rule 6's pattern for provider-neutral types.
5. **`RateLimiter.acquire()`'s list-based signature (§14) is the one Protocol this contract changed relative
   to the planning baseline's earliest draft, and it is now considered final** — a future amendment would be
   required to change it again.
6. **A `model_id` and a `provider_id` are permanent, opaque strings** — no future phase may introduce a
   closed enum, database constraint, or fixed vocabulary for either, mirroring the guarantee Phase 6 contract
   §5/§6 already gives `CapabilityDefinition.name`.
7. **Every one of the seventeen §18 components is a permanent name** for the life of this contract — a
   future amendment MAY add an eighteenth, but MUST NOT rename or merge any of the seventeen without
   following §26.

---

## 28. Pending Ratification — Provisional Defaults

Everything in §§1–27 above is fully binding. The seven items below are the exception: each was carried
forward from `docs/phase7_ai_integration_layer_planning_v2.md` §F as a genuine judgment call requiring your
explicit approval, not a mechanical defect — per instruction, this contract does not resolve them itself. To
remain implementable, each is given a **provisional default**, already reflected in the relevant section
above, which implementation MUST follow until explicitly ratified or overridden. A provisional default is
not equivalent to a canonical rule (§24) — it MAY change without triggering §26's amendment process, since
it was never fully settled to begin with.

| # | Question | Provisional default (currently implemented) | Awaiting your decision |
|---|---|---|---|
| Q1 | `RateLimiter`/`CostTracker`-ledger behavior on Redis unavailability (§14 rule 5, §18 `CostTracker` row) | Neither fail-open nor fail-closed is implemented — this is the one parameter this contract deliberately leaves unimplementable until decided | Fail open (availability-favoring) vs. fail closed (safety-favoring) |
| Q2 | Model configuration format (§3 rule 2) | Typed Python module | Python module vs. YAML/file-based (matching `PromptRepository`'s precedent) |
| Q3 | "Provider hot swap" definition (§17.1, §23) | Restart-required, config-only swap is the guaranteed mechanism | Accept restart-required as sufficient vs. pursue a true zero-downtime, infra-level mechanism outside this contract's scope |
| Q4 | `allow_cost_ceiling_override_on_exhaustion` default policy (§5.1) | `False` for every priority tier, uniformly | Uniform `False` vs. `True` by default for the highest priority tier only |
| Q5 | `verify_capabilities_at_boot` mandatoriness (§17.3) | `False` (recommended, not required, for a production boot) | Optional-but-recommended vs. mandatory in production boots (no override) |
| Q6 | `MAX_TOOL_ROUNDS` scope (§9.4) | One global constant, default 3 | Global constant vs. per-`Capability`-configurable via `CapabilityConfig` |
| Q7 | `WeightedSplitPolicy` scope (§4.7) | Manual-only, no automatic rollback | Manual-only vs. a minimal automatic rollback trigger on error-rate regression |

**Binding rule for this section specifically:** Q1 is the one item where the provisional default is
"unimplemented, pending decision" rather than a working default — `RateLimiter` and `CostTracker` MUST raise
a boot-time configuration error if deployed without an explicit fail-open/fail-closed setting, rather than
silently picking one. Q2–Q7 have working provisional defaults and MAY be implemented against as-is; ratifying
or overriding any of them later is a configuration/parameter change, not an architectural one, and does not
by itself require the §26 amendment process unless the override would also violate a canonical rule in §24.

---

## 29. Reviewer Ratification Log

This log records point-by-point confirmations obtained during your review, on your own numbering — distinct
from §28's self-identified pending items, so neither list misrepresents the other. An entry here that
already matches existing contract text changes nothing; it is recorded as explicit confirmation, not as a
new rule. An entry that ever required a change would be logged as an amendment (§26) instead, with a
cross-reference back to this line.

| Your # | As stated | Contract sections it confirms | Disposition |
|---|---|---|---|
| Q1 | "`ProviderAdapter` remains an implementation of the Phase 6 `LLMGateway` Protocol. Do not introduce a separate `ProviderAdapter` Protocol." | §1 P12; §2 (`ProviderAdapter = LLMGateway` type alias, rule 1) | **Ratified as already written** — no change. Recorded here as a locked commitment: no future Phase 7 work may introduce a second, parallel `ProviderAdapter` interface without an amendment (§26). |
| Q5 | "`ModelRegistry` remains a statically curated registry. No runtime discovery. No provider model enumeration. No database-backed model catalogue. Boot-time validation only." | §3 rules 2 and 7 (single explicit Python module, never a live model-listing endpoint, never a database table; boot-time `RegistryConsistencyError`) | **Ratified as already written** — no change. Recorded here as a locked commitment: no future Phase 7 work may add live model enumeration, provider-side discovery, or a database-backed catalogue to `ModelRegistry` without an amendment (§26). |

Further confirmations you send will be appended here, in the order received, without renumbering or editing
prior entries — the same append-only discipline §26 already establishes for amendments.

---

*End of specification.*
