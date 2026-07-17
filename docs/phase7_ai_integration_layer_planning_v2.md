# Phase 7 Planning Report v2 — AI Integration Layer (Correction Pass)

No code, no migrations, no commits. This document supersedes nothing by deletion —
`docs/phase7_ai_integration_layer_planning.md` (v1) and `docs/phase7_principal_architect_review.md` (the
adversarial review) remain unchanged and are this document's only two inputs. Every section below exists to
resolve a specific finding from the review. Where v1 content is still correct and untouched by any finding,
it is referenced by section number rather than repeated.

**Scope discipline, per instruction:** no new broad review was performed. No abstraction was added beyond
what a specific Critical or Major finding required. Phase 1–6 contracts are amended in exactly one place
(Amendment C, §A.3) because Critical Finding 3 makes it structurally unavoidable — no other Phase 6 contract
text is touched.

**Consistency-fix pass:** `docs/phase7_consistency_review.md` found six Major internal-consistency issues in
this document (zero Critical). All six are corrected in place below — cache-before-budget ordering (§A.1
step 7, §A.2, §A.3, §D.6, §D.11), same-candidate retry reconciled with the "never repeats a failed pair"
rule (§A.1 step 7, §D.7 cross-reference), the exclusion-filter position made consistent everywhere (§A.1
step 2.5, §C, §D.5), `LatencyTracker` added to the canonical component table (§C), the `RoutingPolicy` vs.
`WeightedSplitPolicy` determinism wording resolved (§B.1, §B.17), and `CostTracker`'s ledger classified
consistently with the other distributed runtime components (§C, §E). No other content changed; no Protocol
signature was altered; no new component was introduced (`LatencyTracker` already existed in prose — it is
now tabulated, not invented).

## A. Critical findings — resolution

### A.1 Fallback correctness — **RESOLVED**

**Root cause (review §6.1):** the fallback-cost rule anchored the cost bound to *"the first (preferred)
candidate's price."* Under `LOWEST_COST` routing, the first candidate is already the cheapest — anchoring
to it excludes every other (necessarily pricier) candidate, collapsing the Fallback Chain to zero depth.

**Fix:** anchor the cost bound to the **cheapest price among the filtered candidate set**, not to whichever
candidate the objective happened to rank first. This makes the bound stable and objective-independent:
under `LOWEST_COST`, the anchor and the first candidate's price are the same number, but *other* candidates
up to the multiplier are still eligible; under `BEST_QUALITY`, the anchor is whatever the cheapest surviving
model costs, independent of how expensive the top-ranked (best-quality) pick is.

Two new, separate components replace the single "Fallback Chain" of v1 §7: **`RoutingEngine`** (produces a
best-first *preference* order — pure ranking, no cost gating) and **`FallbackPolicy`** (converts that
preference order into a bounded, cost-gated, dedup'd *attempt* sequence). This is the "separate routing
preference from fallback eligibility" requirement — preference and eligibility are now two different
functions over two different inputs, not one blended step.

```python
class FallbackEligibility(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_cost_multiplier: Decimal = Decimal("3.0")     # candidate price <= multiplier x cheapest-in-set price
    max_additional_cost: Decimal | None = None         # optional absolute cap - if set, BOTH bounds apply
    allow_cost_ceiling_override_on_exhaustion: bool = False   # opt-in: widen past the bound rather than fail
    max_fallback_attempts: int = 3                      # unchanged from v1 §7


class FailureClass(str, Enum):
    TRANSIENT = "transient"          # auth (this call only - see A.4/health TTL), rate limit, timeout, 5xx
    PERMANENT_INCOMPATIBLE = "permanent_incompatible"   # model can't actually do what ModelRegistry claimed,
                                                          # or a moderation block - see §B.12 CapabilityNegotiator
```

**Candidate-filtering and candidate-ranking sequence (exact):**

1. **Hard filter** (`ModelRegistry.filter()`, unchanged from v1 §6 step 1) — capability-flag requirements,
   `availability` in `{ga, beta}`.
2. **Provider-enabled filter** (unchanged from v1 §6 step 2) — drop candidates whose provider isn't
   registered/enabled.
2.5. **Exclusion filter** (`RoutingCriteria.excluded_providers`, §B.23) — drop any candidate whose
   `provider_id` appears in the caller-supplied exclusion list. A hard filter, not advisory — gives an
   operator a scoped lever to steer traffic away from one provider without the blunt, all-capabilities
   `enabled_providers` restart. Sits here, between the provider-enabled filter and the health filter, in
   every reference to this sequence in this document (§B.23, §C, §D.5).
3. **Health filter (NEW)** — drop any candidate whose `(provider_id, model_id)` is currently marked
   unhealthy in `ProviderHealthStore` (§C) — a TTL-based flag (default 60s), not the permanent, restart-only
   flag v1 had; it expires and the candidate becomes eligible again automatically. This closes the
   review's finding 1.3/3.2 (no recovery without restart) as a side effect of this fix, at zero extra
   design cost.
4. **If zero candidates survive the hard, provider-enabled, exclusion, and health filters (steps 1, 2, 2.5,
   3):** raise `NoRoutableCandidateError` immediately (a `CapabilityConfigurationError`-flavored,
   non-retryable failure — this almost always means the `Capability` asked for a combination of
   requirements no registered model satisfies, a config bug, not a transient condition). This is distinct
   from "candidates existed but all failed" (step 8).
5. **Preference ranking** — `RoutingPolicy.rank(candidates, criteria)` (unchanged Protocol from v1 §6,
   purity question resolved separately in §B.1) orders survivors best-first by the requested objective.
   This ordering expresses *preference only* — it is not yet cost-gated.
6. **Fallback-eligibility filtering (NEW step)** — `FallbackPolicy.eligible(ranked_candidates, criteria.fallback)`:
   compute `cheapest_price = min(price for c in ranked_candidates)`; keep every candidate where
   `price(c) <= cheapest_price * max_cost_multiplier` **and**, if `max_additional_cost` is set,
   `price(c) - cheapest_price <= max_additional_cost`; **preserve the relative order** `RoutingPolicy`
   already produced among the survivors (fallback eligibility filters, it does not re-rank). Truncate to
   `max_fallback_attempts`. This is the final attempt sequence.
7. **Dispatch loop** — for each candidate in the sequence (in order): check cache first (§A.2) — a hit
   returns immediately, with no cost estimate and no `BudgetGuard` check, since serving a cache hit costs
   nothing; on a miss, estimate cost and get `BudgetGuard` approval (§A.3), then attempt. "Attempt" includes
   up to `max_same_candidate_retries` (default 1, v1 §8/§D.7) retries against *this same candidate* before
   the candidate is considered to have failed — the same-candidate retry is nested inside this step, not a
   separate pass through the sequence. Only once a candidate's attempt cycle (initial try plus its
   same-candidate retries) is exhausted does `FallbackPolicy` classify the failure via `FailureClass`:
   - `TRANSIENT` → mark `(provider_id, model_id)` unhealthy in `ProviderHealthStore` with TTL, move to next
     candidate. **Never starts a new attempt cycle for this same provider/model pair again within this
     call** — once a candidate's attempt cycle (including its same-candidate retries) is exhausted, it is
     removed from the remaining sequence for this call regardless of TTL (TTL only affects *future*, separate
     calls).
   - `PERMANENT_INCOMPATIBLE` → mark `(provider_id, model_id)` `runtime_unavailable` in `ProviderHealthStore`
     with **no TTL** (persists for the life of the process — this is a capability-negotiation failure, not a
     transient one; see §B.12) **and, if the failure is a moderation block specifically, do not continue the
     loop at all** — raise immediately (unchanged from v1 §7's moderation rule).
8. **Exhaustion** — if the loop runs out of candidates (all attempted and failed, or `BudgetGuard` denied
   every candidate — §A.3) and `allow_cost_ceiling_override_on_exhaustion=False` (default): raise
   `AllProvidersFailedError(reason=...)` with `reason` one of `"cost_ceiling_exhausted"`,
   `"all_candidates_failed"`, or `"all_candidates_budget_denied"` — preserved in `CapabilityCall.error` for
   diagnostics (§A.4). If `allow_cost_ceiling_override_on_exhaustion=True`, re-run step 6 once more with
   `max_cost_multiplier` and `max_additional_cost` both lifted (unbounded), against the *original* ranked
   list minus already-attempted pairs — this is the explicit, opt-in "fall back to a more expensive model
   when required" path the brief asked for; it is never the default.

**Why this fixes the `LOWEST_COST` case:** the anchor (`cheapest_price`) is now a property of the *filtered
candidate set*, never of *which candidate the objective ranked first*. A `LOWEST_COST`-routed call whose
first attempt fails still has up to `max_fallback_attempts - 1` further candidates available, bounded at
`3×` the cheapest price by default — real fallback depth, not zero.

---

### A.2 Cache correctness — **RESOLVED**

**Root cause (review §13.1):** the cache key was `sha256(canonical GenerateRequest JSON)`, computed
*before* routing resolves an actual model — two calls with identical (advisory, often-`None`)
`preferred_model` content but different *resolved* models collide on one key.

**Fix, structural:** caching moves from *before* the Router (v1 §2 diagram) to *after* it — a cache
lookup/write now happens per-candidate, once a specific `(provider_id, model_id)` is the thing about to be
attempted, never before that's known. This is not just a key-composition fix; it's a pipeline-order fix.
Within the per-candidate flow, the cache lookup happens **before** any cost estimate or `BudgetGuard` check
for that candidate (§A.1 step 7, §A.3) — a cache hit costs nothing, so it must never be blocked by a budget
decision that would only ever have applied to a real provider call.

**Cache key composition — every component required, in a fixed order, each independently hashed then
concatenated before a final hash (so a change in any one component always changes the final key, and
partial/prefix collisions across components are impossible):**

```python
class CacheKeyComponents(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1                    # bump on any change to this composition -> invalidates
                                                 # the entire cache atomically, no manual flush needed
    normalized_request_hash: str                # sha256 of GenerateRequest with preferred_model/
                                                 # preferred_provider/cache_policy/metadata excluded
                                                 # (routing hints and cache intent don't affect output)
    resolved_provider_id: str                   # NEW - the actual candidate being attempted
    resolved_model_id: str                      # NEW - the actual candidate being attempted
    model_config_fingerprint: str                # sha256 of {temperature, max_tokens, top_p, tool_choice,
                                                  # response_mode} - the generation parameters that affect output
    prompt_fingerprint: str | None                # sha256 of (metadata["prompt_name"], metadata["prompt_version"])
                                                  # when the Capability supplies them (a documented, additive
                                                  # metadata convention - no Phase 6 schema change); None if absent
    tool_schema_fingerprint: str | None            # sha256 of request.tools when present, else None
    structured_output_schema_fingerprint: str | None   # sha256 of request.response_schema when
                                                          # response_mode == "json_schema", else None
    multimodal_input_fingerprint: str | None       # sha256 of the ordered list of (artifact_ref, mime_type)
                                                    # pairs from every ContentPart(type="artifact_ref"),
                                                    # else None - never the binary itself

    def cache_key(self) -> str:
        parts = [str(self.schema_version), self.normalized_request_hash, self.resolved_provider_id,
                  self.resolved_model_id, self.model_config_fingerprint,
                  self.prompt_fingerprint or "-", self.tool_schema_fingerprint or "-",
                  self.structured_output_schema_fingerprint or "-", self.multimodal_input_fingerprint or "-"]
        return sha256("|".join(parts).encode()).hexdigest()
```

**Invalidation/versioning:**
- `schema_version` bump → atomic full-cache invalidation (key composition changed, old keys are simply never
  looked up again; no active eviction needed — old entries age out via TTL, §below).
- Prompt republish (a new `prompt_version`) → naturally produces a new `prompt_fingerprint`, hence a new key
  — no active invalidation needed, old-prompt-version entries age out via TTL.
- Model deprecation/removal from `ModelRegistry` → naturally stops new writes under that `resolved_model_id`
  (Router never selects it again); existing entries age out via TTL. No active invalidation needed.
- **Response cache TTL: default 1 hour** (unlike the embedding cache — response freshness matters more than
  embedding stability; see below). Configurable per-`Capability` via `cache_policy`, never TTL-free.

**Never cacheable (new, explicit rules):**
- `cache_policy != "read_write"` (opt-in only, unchanged from v1).
- `finish_reason != "stop"` (truncated/filtered/tool-interrupted — not a complete, safely-reusable answer).
- Any `GenerateResponse.artifacts` is non-empty (binary-output references may be run-scoped/ephemeral in
  object storage; caching a dangling reference is worse than a miss).
- Any response where the corresponding `moderate()` call (if the `Capability` made one) flagged the content —
  a `Capability`-level discipline, not a Gateway-enforced one, named here so it isn't assumed automatic.

**Streaming cache behavior:** `generate_stream` responses are **never cached** — no partial-chunk cache
semantics are designed. A `Capability` that wants a cacheable answer uses `generate()`. This is a
deliberate scope cut, not an oversight: it avoids an entire new complexity class (partial-stream identity,
replay semantics) for a benefit (streamed responses tend to be user-facing/interactive, where freshness is
usually wanted anyway) that doesn't clearly justify the cost.

**Moderation cache behavior:** `moderate()` responses **may** be cached, using the same key structure minus
the tool/structured-output/multimodal fingerprints (moderate() doesn't carry them) — **default TTL 5
minutes**, deliberately much shorter than the response cache's 1 hour, because a provider's moderation
policy/model can change without any `model_id` version bump more readily than its generation quality does.

**Embedding cache behavior (extends v1 §13, tightened):** key = `(schema_version, resolved_provider_id,
resolved_model_id, sha256(input_text))` — v1 already kept `model_id` in the key; `resolved_provider_id` is
added for full precision (guards against two providers coincidentally exposing an identical `model_id`
string, cheap to add). TTL-free/long-TTL default preserved — embeddings remain deterministic per resolved
model version, unlike generation.

**Provider-side prompt-cache interaction (unchanged from v1 §15):** entirely orthogonal, entirely internal
to each `ProviderAdapter`. The Gateway-level response cache answers "do we call the provider at all";
provider-native prompt caching (Anthropic `cache_control`, etc.) answers "how much do we pay when we do" —
the two layers stack without interaction and neither needs to know the other exists.

---

### A.3 BudgetGuard sequencing — **RESOLVED (Amendment C to Phase 6 contract §9)**

**Root cause (review §15.1):** Phase 6 has `Capability` call `BudgetGuard.check()` once, pre-flight, *before*
calling `LLMGateway.generate()` — but the `Capability` does not choose the final model; the Router does,
inside the Gateway, after the check already happened. The check's input (an estimate for a model the
`Capability` guessed) has no defined relationship to the model actually used, on the very first attempt, not
only during fallback.

**Fix, structural — this is the one place this document amends a Phase 6 contract rule, because no
Gateway-side fix is possible while the check-call site stays outside the Gateway.**

**Amendment C (proposed, binding pending your approval — same status class as Phase 6's own Amendments A/B):**
`BudgetGuard.check()` is invoked by the **Routing Gateway**, once per fallback candidate, immediately before
that candidate is dispatched — not by the `Capability`, and not once per logical call. This strengthens P5's
centralization intent (budget enforcement now happens in exactly one place, for every attempt, and cannot be
forgotten by a `Capability` author) at the cost of moving the call site. `BudgetGuard`'s own contract
(pre-flight, read-only, raises `BudgetExceededError`) is **unchanged** — only *who calls it and when* moves.
The forbidden-edge table's `BudgetGuard → LLM Gateway ❌ FORBIDDEN` rule is **not violated** — the new edge is
`LLM Gateway → BudgetGuard`, which Phase 6 never forbade, only didn't anticipate.

**New component, owning the estimate input this check needs: `CostEstimator`** (§C) — a pure function, no
I/O, no persistence, reading only `PricingCatalog` (§C).

**Exact sequence (per the brief's requested chain, now fully specified):**

```
Capability calls LLMGateway.generate(request)      <- single call site, unchanged for the Capability;
                                                        Capability no longer calls BudgetGuard directly at all
  -> RateLimiter check (unchanged, v1 §16)
  -> RoutingEngine produces ranked candidates (§A.1 steps 1, 2, 2.5, 3, 5)
  -> FallbackPolicy produces the bounded attempt sequence (§A.1 step 6)
  -> FOR EACH candidate, in order:
       CacheCoordinator lookup (§A.2) -> hit: return (no cost estimate, no BudgetGuard check - free)
       IF miss:
         CostEstimator.estimate(candidate, request) -> CostEstimate(expected, worst_case)
         BudgetGuard.check(capability_name, priority, worst_case) -> approve | deny
         IF approved:
           dispatch to ProviderAdapter -> success: return GenerateResponse; failure: classify (§A.1 step 7), next candidate
         IF denied:
           continue to next candidate (a cheaper one may still be approved)
  -> all candidates exhausted/denied -> AllProvidersFailedError / BudgetExceededError (§A.1 step 8)
  -> on success: actual CapabilityUsage from the provider response
  -> CostTracker.record(actual_usage, resolved_model, ...)   <- unchanged ownership, post-hoc, write-only,
                                                                  always the ACTUAL usage, never an estimate
```

**Clarifications, each answered directly:**

- **Who produces cost estimates:** `CostEstimator`, always — never the `Capability`, never `BudgetGuard`
  itself (which only ever *consumes* an estimate and returns approve/deny).
- **How estimates are calculated before token usage is known:** a declared, explicitly approximate
  heuristic — input tokens ≈ `len(concatenated message text) / 4` (a standard rough token/character ratio);
  output tokens (worst case) = `request.max_tokens` if set, else the candidate's
  `ModelDescriptor.max_output_tokens`. This is a **safety bound**, not a billing-accuracy claim — named
  explicitly as approximate, not precise.
- **Worst-case vs. expected estimate:** both are computed; `BudgetGuard.check()` is gated on **`worst_case`**
  (a pre-flight safety gate must protect against what *could* happen, not the typical case). `expected` is
  recorded for observability only (§A.4's `cost_estimate_variance` event), letting the estimator's accuracy
  be tuned from real data over time without changing what gates approval.
- **How fallbacks are re-approved:** every candidate gets its own independent cache lookup and, on a miss,
  its own independent `CostEstimator` + `BudgetGuard.check()` call inside the dispatch loop (§A.1 step 7) —
  this is the direct fix: a denial on a pricier candidate no longer blocks a cheaper one from being tried,
  and a cache hit never triggers a budget check at all.
- **What happens if actual cost exceeds the estimate:** nothing blocks the already-completed response —
  tokens are already spent and cannot be unspent. `CostTracker` records the true actual cost normally
  (protecting the *next* call, whose `BudgetGuard` check reads the now-updated ledger). If `actual` deviates
  materially from `worst_case`, a `cost_estimate_variance` observability event fires (§A.4) — a tuning
  signal, not a failure.
- **How streaming is budgeted:** identically — the same per-candidate `CostEstimator`/`BudgetGuard` check
  runs once, before the stream opens, using the same `worst_case` heuristic (token *accounting* doesn't
  change because delivery is incremental). No mid-stream re-check is performed — pausing an active stream to
  re-ask `BudgetGuard` is not designed and would be a materially larger complexity addition than this fix
  warrants; the "actual may exceed estimate" handling above already covers the consequence.
- **How tool loops are budgeted:** no special-casing needed — this falls out for free. Every `generate()`
  call inside a `Capability`'s tool-use loop (§11) is its own independent `LLMGateway` invocation, so each
  one independently passes through the full sequence above, including its own `BudgetGuard` check against
  the *current* ledger. A loop's 4th internal call can be legitimately denied if the first 3 already
  exhausted the budget — correct behavior, achieved with zero tool-loop-specific code.
- **How batch requests are budgeted:** **not designed** — batch inference (`generate_batch()`) remains an
  explicitly deferred non-goal (v1 §22, unchanged). When it is designed, the expected shape is a single
  `BudgetGuard.check()` against the **sum** of a batch-aware `CostEstimator` output across every item, not
  one check per item — named as a forward compatibility expectation, not built now.

---

### A.4 Observability — **RESOLVED (contracts and ownership only — no OpenTelemetry/Prometheus wiring)**

**Root cause (review §26.1):** no correlation-ID design, no structured log schema, no metrics schema existed
anywhere in v1, despite being an explicit topic and despite being a precondition for operating at the
brief's stated scale.

#### A.4.1 Identifier hierarchy

Every identifier below is either an **existing field reused** (preferred, per "no unnecessary abstractions")
or a **cheap, deterministic, derived string** — only one genuinely new field is introduced anywhere
(`ToolExecutionRequest.tool_call_id`, a Phase 7-owned schema not yet frozen by any contract).

| Identifier | Source | New? |
|---|---|---|
| `trace_id` | `CapabilityContext.runtime.task_id` (already exists, Phase 6) — spans every step and every Workflow-level retry within one `EditorialTask` | Reused |
| `capability_execution_id` | Derived: `f"{task_id}:{capability_name}:{attempt}"` — one per `Capability.execute()` invocation, fresh on every Workflow-level retry | Derived, no new field |
| `request_id` | `CapabilityCall.call_id` (already exists, Phase 6) — generated by the `Capability` before calling `LLMGateway`, passed through as `GenerateRequest.metadata["request_id"]` (existing generic `metadata: dict` field — no schema change) so Gateway-internal logs can correlate back to the exact `CapabilityCall` that will eventually be built from this call | Reused via a documented metadata convention |
| `provider_attempt_id` | Derived: `f"{request_id}:{attempt_index}"` — one per `FallbackPolicy` candidate attempt (§A.1 step 7) within one `request_id` | Derived, no new field |
| `model_route_id` | Derived: `f"{provider_attempt_id}:{provider_id}:{model_id}"` — identifies exactly which routing decision a given attempt represents | Derived, no new field |
| `tool_call_id` | **New field**, `ToolExecutionRequest.tool_call_id: str` (§B, Phase 7's own schema) — derived by the `Capability`'s tool loop as `f"{capability_execution_id}:tool:{round_index}:{tool_index}"` | New field, Phase 7-owned only |

**Parent-child tree:**

```
trace_id (task_id)
  └─ capability_execution_id (one per execute() attempt)
       └─ request_id (= CapabilityCall.call_id; one per Gateway method invocation - e.g. one per
       |    generate() call inside a tool loop, one per schema-mismatch retry call)
       |     └─ provider_attempt_id (one per FallbackPolicy candidate)
       |          └─ model_route_id (the specific provider+model that attempt targeted)
       └─ tool_call_id (references the request_id whose response produced the ToolCall, and precedes
            the next request_id that carries the tool's result back)
```

**Ownership:** a lightweight, injected, read-only value object — `ObservabilityContext` (§C) — carries
`trace_id`/`capability_execution_id`/`request_id` down through every layer via explicit parameter passing
(construction-time injection, same discipline as every other dependency in this system — not an implicit
thread-local/contextvar, to keep every layer trivially unit-testable in isolation). `ObservabilityContext`
itself emits nothing; each layer that emits a log/metric reads whatever ids it needs from the context it was
handed and attaches them itself. No central "observability capability" or god-object logger exists.

#### A.4.2 Structured events and metrics, by category

Every row: **who emits it**, the **minimum structured fields** the log event carries (always includes the
relevant ids from §A.4.1), and the **metric(s)** derived from it. No transport/backend is specified — this
is a contract for what must be emittable, not an implementation.

| Category | Emitted by | Key structured fields (beyond ids) | Metric(s) |
|---|---|---|---|
| Routing decision | `RoutingEngine` | `objective`, `candidates_considered`, `candidates_after_hard_filter`, `chosen_rank` | routing decisions/sec by objective |
| Fallback | `FallbackPolicy` | `attempt_index`, `candidate_provider_id`, `candidate_model_id`, `reason` (from step 8's reason codes) | fallback depth used (histogram); `AllProvidersFailedError` rate by `reason` |
| Retry (Gateway-internal, v1 §8) | `FallbackPolicy` dispatch loop | `same_candidate_retry_index`, `backoff_ms` | same-candidate retry rate |
| Timeout | `ProviderAdapter` | `boundary` (`workflow`\|`step`\|`capability`\|`provider_http`), `configured_timeout_ms`, `elapsed_ms` | timeout rate by boundary and provider |
| Rate limit | `RateLimiter` | `rate_limit_key` (provider/model/capability dimension — §B.2), `outcome` (`acquired`\|`rejected`) | rejection rate by key dimension |
| Cache hit/miss | `CacheCoordinator` | `cache_type` (`response`\|`embedding`\|`moderation`), `outcome`, `key_schema_version` | hit rate by cache type |
| Budget denial | `BudgetGuard` (called from Gateway, §A.3) | `capability_name`, `priority`, `worst_case_estimate`, `expected_estimate` | denial rate by capability |
| Provider error | `ProviderAdapter` | `failure_class` (§A.1), `provider_error_code` (adapter-normalized, never a raw provider-specific code leaked past the adapter) | error rate by provider, by `failure_class` |
| Schema-validation failure | `Capability` (v1 §10) | `schema_name`, `retry_attempted` (bool) | validation-retry rate |
| Tool call | `ToolExecutor` | `tool_name`, `outcome` (`SUCCESS`\|`FAILED`) | tool call volume/error rate by tool |
| Streaming interruption | `ProviderAdapter` | `chunks_emitted_before_failure`, `had_final_chunk` | mid-stream failure rate |
| Token usage | `CapabilityCall` assembly (`Capability`) | `input_tokens`, `output_tokens`, `unit_type` | tokens/sec by capability, by model |
| Cost | `CostTracker` (post-hoc, v1 §17 unchanged) + `CostEstimator` (`cost_estimate_variance`, §A.3) | `actual_cost`, `expected_estimate`, `worst_case_estimate`, `variance_pct` | spend/hour by capability, by provider; estimate-variance distribution |
| Latency | `ProviderAdapter` (per attempt) + `Capability` (per `CapabilityCall`, end to end) | `attempt_latency_ms`, `total_call_latency_ms` | p50/p95/p99 by provider, by model, feeding the `fastest` routing objective's telemetry need (v1 §6.1) |

**Explicitly deferred (named, not designed):** the actual transport/backend (OpenTelemetry span export,
Prometheus scraping, a logging pipeline) is not chosen here, per instruction. What's fixed by this section is
the **shape** — ids, event categories, minimum fields — so that whichever backend is chosen later is an
additive integration, not a redesign of what any layer already knows how to emit.

---

## B. Major findings — resolution

Every Major finding from `docs/phase7_principal_architect_review.md`, deduplicated across sections
(several were the same underlying gap flagged from two different topic angles — one correction, listed
once, cross-referenced from both). ID column matches this document's own numbering, not the review's
section numbers, to keep the table self-contained.

| ID | Finding (review ref) | Root cause | Correction | Section | Phase 7? | Deferred? |
|---|---|---|---|---|---|---|
| B.1 | Routing purity vs `FASTEST` (5.1) | `RoutingPolicy.rank()` claimed pure but needed mutable latency state | Latency becomes an explicit, pre-fetched `RoutingTelemetrySnapshot` parameter; `rank()` stays pure | §B.1 below | Yes (contract), impl deferred | Latency tracker impl deferred (unchanged from v1 §6.1) |
| B.2 | `RateLimiter` signature (14.1) | `acquire()` took one key, claimed 4 dimensions | `acquire(keys: list[RateLimitKey])`, all-or-nothing | §B.2 below | Yes | No |
| B.3–6 | Provider/Model/Request/Failure lifecycle (3.1, 4.1) | Named deliverables never assembled as artifacts | Section D | §D | Yes (docs) | No |
| B.7 | Onboarding runbook (24.1) | Mechanics scattered, no checklist | Section D.1 | §D.1 | Yes (docs) | No |
| B.8 | Pricing model (2.2, 16.1) | Flat price/token can't express cache-discount/tiered/batch pricing | `pricing_tiers: list[PricingTier]` replaces flat fields | §B.8 below | Yes | Batch tier unused until `generate_batch()` exists |
| B.9 | Structured-output retry vs. prompt audit (9.1/18.1) | Retry mutated rendered prompt content in place | Correction sent as an appended `Message`, never edits `RenderedPrompt` content | §B.9 below | Yes | No |
| B.10 | Local-model blocking I/O (30.1) | Sync inference code could block the shared event loop | Binding rule: `asyncio.to_thread`/pool for any non-network-async adapter | §B.10 below | Yes (rule only) | No |
| B.11 | MCP vs. P9 (28.1) | Claimed compatibility without engaging dynamic discovery | Two-tier: static boot-time snapshot (P9-compatible) vs. live discovery (named non-goal) | §B.11 below | Tier 1 only | Tier 2 explicitly deferred |
| B.12 | Silent capability-flag lies (19.2) | Contract tests are shape-only | New `CapabilityNegotiator`, opt-in boot-time behavioral self-test | §B.12 below | Yes (design), opt-in at runtime | Always-on verification deferred (cost/availability tradeoff) |
| B.13 | Tool idempotency (old review §10.1) | No dedup mechanism for side-effecting tools | `idempotent: bool` on `ToolRegistry.register()`; non-idempotent tools block same-attempt retry | §B.13 below | Yes (rule) | Automatic dedup/idempotency-key mechanism deferred |
| B.14 | Cancellation propagation (new) | Undefined whether in-flight provider calls are actually aborted on timeout | Binding rule: adapters must not swallow `CancelledError`; SDKs that can't abort server-side are a named, accepted limitation | §B.14 below | Yes (rule) | True server-side abort for non-cancellable SDKs deferred |
| B.15 | Streaming fallback boundary (8.1) | "Before/after first chunk" relied on ambiguous transport-level signal | Boundary redefined as caller-observable: before vs. after the Gateway's own first `yield` | §B.15 below | Yes | No |
| B.16 | Tool-loop round/timeout limits (self-review §5; 10.2) | `MAX_AGENT_ROUNDS` reuse ambiguous; `ToolExecutor` had no timeout budget | New, separate `MAX_TOOL_ROUNDS`; even timeout-budget split per remaining round | §B.16 below | Yes | No |
| B.17 | Model deprecation/replacement (4.2, 25.2) | No replacement pointer; no gradual migration mechanism | `replacement_model_id` field; opt-in `WeightedSplitPolicy` (manual, not automatic) | §B.17 below | Yes | Automatic/managed canary system deferred |
| B.18 | Configuration reload / secrets (22.1, 23.1–23.3, 1.1, 1.2) | Scattered findings across credential shape, rotation, redaction, cross-registry validation | Consolidated: restart-only reload (explicit), structured `ProviderCredential`, mandatory redaction rule, boot-time cross-registry check | §B.18 below | Yes | Live/hot config reload deferred (consistent with P9) |
| B.19 | Retry-multiplication ceiling not enforced (old review §6) | Process discipline only, no mechanical check | Boot-time validation: reject registration if `max_attempts × max_fallback_attempts × (1+max_same_candidate_retries)` exceeds a configured ceiling | v1 §8 (rule strengthened here) | Yes | No |
| B.20 | Cache fail-open unstated (13.2) | Only `RateLimiter`'s fail-open/closed question was named, not the Cache's | Settled explicitly: `CacheCoordinator` failures always fail open (treat as miss) | §A.2 (restated) | Yes | No |
| B.21 | Embedding dimension / per-modality limits (2.3, 11.1, 12.1) | No dimension field; no image/PDF/size limits | Additive `embedding_dimension`, `max_images_per_request`, `max_file_size_mb`, `max_pdf_pages` on `ModelDescriptor`; matching count fields on `RoutingCriteria` | §C (`ModelRegistry`) | Yes | No |
| B.22 | `quality_tier` schema gap (2.1) | Recommended in v1 §6.1 prose, absent from v1 §5 schema | Added directly to `ModelDescriptor` now | §C (`ModelRegistry`) | Yes | No |
| B.23 | No provider-exclusion lever (5.3/6.3) | Only positive (`preferred_*`) hints existed | `excluded_providers: list[str]` added to `RoutingCriteria`, enforced as a hard filter | §A.1 (restated) | Yes | No |
| B.24 | `RoutingPolicy` exception isolation (5.2) | Unbounded blast radius for a failing third-party policy | `RoutingEngine` wraps every `RoutingPolicy.rank()` call; an exception falls back to the default built-in policy for that objective and logs a `routing_policy_failure` event (§A.4), never propagates to fail the call | v1 §6.2 (rule added) | Yes | No |
| B.25 | `build_registry()` Gateway-wiring gap (20.1) | Phase 6's illustrative sketch predates a real Gateway to inject | `build_registry(gateway, prompt_repository, budget_guard, tool_registry) -> CapabilityRegistry` — fills a previously-unspecified boot-sequence gap; not a change to any binding Phase 6 Protocol | §C (`CapabilityRegistry`, boot sequence note) | Yes (docs) | No |
| B.26 | `AIExecutionMapper` partial-success gap (17.1) | SUCCESS-only mapping leaves a multi-call `FAILED` execution's real spend invisible | Named as a forward requirement for the future real-persistence phase; already safely bounded today by Amendment B's existing full deferral (no writes happen at all yet) | v1 §17.4 (note added) | No — nothing to build yet | Yes, safely (Amendment B already covers it) |
| B.27 | Shadow cost (16.2, confirming v1 Critical Risk 2) | Failed internal attempts' real spend invisible to `CostTracker` | Partially mitigated: `cost_estimate_variance` observability event (§A.4) gives visibility; full closure (an attempt-level telemetry sink) remains deferred | §A.3/§A.4 | Partial | Yes, with the stated boundary (visible, not closed) |

---

### B.1 Routing policy purity vs. `FASTEST` (expanded)

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
        WeightedSplitPolicy (§B.17), which draws its own local random value each call to
        realize a percentage split - still no I/O, still no read of external state, just
        not deterministic call-to-call. Non-FASTEST policies simply ignore `telemetry`."""
        ...
```

`RoutingTelemetrySnapshot` is fetched once, per call, by `RoutingEngine` from a separate, explicitly
stateful `LatencyTracker` component (owns the rolling p50 sample, Redis-backed per v1 §6.1 — outside the
`RoutingPolicy` entirely) and passed in as a value. This resolves the contradiction: state now lives in a
dependency constructed and read *before* the pure ranking call, never inside it. Missing data (a model never
called before) falls back to the static `quality_tier` heuristic (v1 §6.1, now a real field per B.22).

**What "pure" means here, precisely (resolves the B.17 tension):** this Protocol's actual, load-bearing
requirement is that `rank()` never performs I/O and never reads shared/external mutable state directly — the
property that let `FASTEST` be fixed by turning `LatencyTracker`'s state into an explicit, pre-fetched
parameter instead of a hidden dependency. Determinism (same inputs always produce the same output) is a
property *most* policies also happen to have, but it is not the same requirement, and §B.17's
`WeightedSplitPolicy` is the one named policy that satisfies the first without the second.

**Exception isolation (B.24, folded in here):** `RoutingEngine` wraps every `RoutingPolicy.rank()` call.
If it raises, `RoutingEngine` logs a `routing_policy_failure` event (§A.4) and falls back to the built-in
default policy for that objective — a third-party or buggy policy can degrade routing quality, never break
routing entirely.

**Provider exclusion (B.23, folded in here):** `RoutingCriteria` gains `excluded_providers: list[str] =
Field(default_factory=list)` — enforced as a hard filter (new step 2.5 in §A.1's sequence, between the
provider-enabled filter and the health filter). Gives an operator a scoped lever for "steer traffic away
from Provider X" without the blunt, all-capabilities `enabled_providers` restart.

---

### B.2 `RateLimiter` dimensions and signature (expanded)

```python
class RateLimiter(Protocol):
    async def acquire(self, keys: list[RateLimitKey]) -> None:
        """Every key must have capacity, or none are consumed (atomic, all-or-nothing —
        never a partial throttle). Raises RateLimitExceededError naming which key(s)
        were exhausted, for §A.4 observability."""
        ...
```

The Gateway constructs the key list per call: `[RateLimitKey(provider_id=P), RateLimitKey(provider_id=P,
model_id=M), RateLimitKey(provider_id=P, capability_name=C)]` — provider-wide, model-specific, and
capability-specific buckets, checked together. `tenant_id` remains unpopulated, unchanged from v1 — still a
forward-compatible-only field, not a feature.

---

### B.8 Pricing model (expanded)

```python
class PricingTier(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    condition: Literal["standard", "cached_input", "batch"] = "standard"
    input_price_per_million: Decimal
    output_price_per_million: Decimal


# ModelDescriptor change: replaces the two flat Decimal fields (v1 §5) with:
pricing_tiers: list[PricingTier] = Field(min_length=1)   # "standard" tier is REQUIRED
pricing_currency: str = "USD"
```

`CostEstimator` (§A.3) always estimates against the `"standard"` tier by default — a deliberate
under-estimation-avoidance choice: overestimating is safe (BudgetGuard gates on `worst_case` anyway);
silently assuming a discount that doesn't materialize for this specific call is not. `"cached_input"` and
`"batch"` tiers are present in the schema now so a future phase can use them without a `ModelDescriptor`
change, but nothing in Phase 7 automatically detects cache-eligibility or invokes them.

---

### B.9 Structured-output retry vs. prompt-version audit (expanded)

The retry no longer mutates rendered prompt content. The schema-violation correction is sent as a new,
separate `Message(role="user", content=[ContentPart(type="text", text=<violation description>)])`
**appended to the existing message list** — the original `RenderedPrompt` (system/rules/output_schema) is
never edited, so `(name, version)` still reproduces identically forever, satisfying Phase 6 contract §8's
binding audit guarantee unchanged. `CapabilityCall.metadata` (existing free-form dict, Phase 6 §4) records
`{"retry_reason": "schema_validation_failure", "retried_call_id": <first attempt's call_id>}` so the retry
is auditable as a retry, not indistinguishable from an unrelated first attempt with an unusual message list.

---

### B.10 Local-model blocking I/O (expanded)

**Binding rule, alongside v1 §3's existing adapter-isolation rule:** any `ProviderAdapter` whose underlying
call path is not itself async-non-blocking (an in-process, synchronous local-inference-library binding)
MUST execute that call via `asyncio.to_thread()` or a dedicated, bounded thread/process pool — never call
blocking code directly inside an `async def`. Ollama accessed over its own local HTTP server (the common
deployment) is exempt — that path is pure async HTTP, identical in shape to every hosted provider. The rule
binds only a genuinely in-process, synchronous local-model adapter, should one ever be built.

---

### B.11 MCP vs. no-dynamic-discovery (P9) (expanded)

Stated honestly, not overclaimed, as two distinct tiers:

- **Tier 1 (Phase 7-compatible, no P9 exception, this is what "MCP support" means today):** at boot, connect
  once to each configured MCP server, enumerate its tools, register each into `ToolRegistry` exactly like
  any other tool, then seal. Tools only refresh on restart — identical discipline to every other registry
  in this system.
- **Tier 2 (explicitly named non-goal, not designed):** live, per-session dynamic MCP tool discovery without
  a restart. This genuinely conflicts with P9 and would require a dedicated, separately-approved "hot
  registry" design that exists nowhere else in this system. Not attempted here.

---

### B.12 Provider/model capability negotiation (expanded)

```python
class CapabilityNegotiator(Protocol):
    async def verify(self, provider_id: str, model_id: str, adapter: ProviderAdapter,
                      claimed: ModelDescriptor) -> "NegotiationResult": ...

class NegotiationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    verified_flags: dict[str, bool]    # e.g. {"supports_tools": True, "supports_structured_output": False}
```

Runs **once per `(provider_id, model_id)` pair, at boot**, after both registries seal, gated behind a
`Settings.verify_capabilities_at_boot: bool = False` flag (default off — it requires live credentials and
real network calls, undesirable for offline/CI boots; recommended `True` for a production boot). It issues a
small number of cheap, deterministic behavioral probes for each *claimed* flag (e.g., a trivial
tools-including request, confirming `tool_calls` comes back non-null or `UnsupportedGatewayCapabilityError`
is raised — never a silent 200 with `tools` ignored). A mismatch marks that specific flag `verified=False` in
`ProviderHealthStore` (§C); the Router's hard filter (§A.1 step 1) additionally excludes a candidate for
whichever *specific* requirement its flag failed verification on — not a whole-model exclusion.

---

### B.13 Tool idempotency (expanded)

`ToolRegistry.register(definition: ToolDefinition, executor: ToolExecutor, idempotent: bool)` — `idempotent`
is stored alongside the registration (not added to Phase 6's `ToolDefinition` itself, avoiding any Phase 6
contract change). Default posture is conservative: for `idempotent=False` tools, if a Gateway-internal
retry/fallback would re-attempt a `generate()` call made *after* that tool already executed within the
current `capability_execution_id`, the tool loop MUST NOT silently retry within that attempt — it lets the
failure propagate to Workflow-level retry (which starts a fresh `capability_execution_id`, accepting the
same named risk as before, now explicitly bounded rather than open-ended). `idempotent=True` tools need no
special handling. **Deferred:** framework-generated idempotency keys / automatic dedup remain unbuilt.

---

### B.14 Cancellation propagation (expanded)

**Binding rule:** every `ProviderAdapter` method MUST NOT swallow `asyncio.CancelledError` propagation from
an outer timeout (v1 §8's four nested boundaries) — no bare `except Exception` that would catch it, and any
wrapped SDK call must actually abort the underlying connection where the SDK supports it. **Named, accepted
limitation:** for SDKs that cannot cancel an in-flight request server-side (common for some blocking clients
wrapped via `asyncio.to_thread`, §B.10), the coroutine gives up waiting but the provider may still complete
(and bill for) the call server-side — this is the same shadow-cost risk as B.27/v1 §17.2, not a new one, just
a new trigger for it.

---

### B.15 Streaming fallback boundary (expanded)

Redefined from a provider/transport-level signal (ambiguous under buffering proxies) to a **caller-observable
boundary entirely within the Gateway's own control:** fallback is permitted only *before* the Gateway's
`generate_stream()` `AsyncIterator` has yielded its first `GenerateChunk` to the caller. Once the first
`yield` has happened, no fallback occurs — full stop, regardless of what the provider or any intermediary
proxy was doing internally. This removes the dependency on transport-level signal clarity entirely.

---

### B.16 Tool-loop round and timeout limits (expanded)

**Round limit:** a new, Phase-7-owned constant, `MAX_TOOL_ROUNDS` (default 3 — numerically coincidental
with `MAX_AGENT_ROUNDS`, explicitly **not** the same counter). Bounds internal `generate()`↔tool-execute
rounds within one `Capability.execute()` invocation, entirely independent of Workflow-level
`MAX_AGENT_ROUNDS` step chaining. Exceeding it raises `ToolRoundLimitExceededError` →
`PermanentCapabilityError` (an unbounded tool loop is a capability-logic bug, not transient).

**Timeout budget:** each `ToolExecutor.execute()` call is allocated no more than
`remaining_capability_timeout / (MAX_TOOL_ROUNDS - rounds_completed_so_far)` — an even, conservative split
guaranteeing later rounds (including the final `generate()` call that must process the tool's result) always
retain some budget, never fully consumed by an early, slow tool call.

---

### B.17 Model deprecation and replacement (expanded)

`ModelDescriptor` gains `deprecation_note: str | None` and `replacement_model_id: str | None` (additive) —
set when `availability` transitions to `"deprecated"`, so an operator or the Router's logging can surface
what a deprecated model's suggested replacement is. Router behavior for `deprecated` is otherwise unchanged
from v1 (selectable only if explicitly `preferred_model`'d, never a default candidate).

**Gradual replacement:** one new, opt-in, built-in `RoutingPolicy` — `WeightedSplitPolicy(weights: dict[model_id,
float])` — registered through the same `RoutingPolicyRegistry` mechanism v1 §6.2 already designed (no new
architecture). A capability opts into weighted-split routing explicitly for a migration window; weights are
edited and redeployed manually (restart-gated, consistent with P9). **Deliberately not** an automatic/managed
canary system (no automatic promotion, no automatic rollback on error-rate regression) — that remains
deferred; this is the minimal, manual mechanism the brief's "future provider replacement" gap needed.

**Determinism note (see §B.1's precise definition of "pure"):** `WeightedSplitPolicy` is the one named
`RoutingPolicy` implementation that is not deterministic call-to-call — realizing a percentage split
requires the same `(candidates, criteria, telemetry)` input to sometimes rank the new model first and
sometimes the old one. It still satisfies `RoutingPolicy`'s actual requirement: no I/O, no read of
`LatencyTracker`, `ProviderHealthStore`, or any other external/shared state — its random draw is generated
fresh, locally, inside the call, never read from outside it. This is stated here explicitly so the exception
is visible next to the one policy that needs it, not just in §B.1's Protocol docstring.

---

### B.18 Configuration reload and secrets (expanded)

**Reload behavior, stated explicitly:** no registry (`ProviderRegistry`, `ModelRegistry`, `ToolRegistry`,
`RoutingPolicyRegistry`) supports live reload. Every configuration change — new provider, new model,
credential rotation, pricing update, routing policy/weight change — requires a process restart. This is not
a gap; it is the deliberate, consistent consequence of P9, restated here as the explicit answer rather than
left implicit. The **one** exception is `ProviderHealthStore`'s TTL-based health state (§A.1), which is
runtime state, not configuration, and is intentionally the only "hot" thing in this design.

**Structured credentials:**

```python
class ProviderCredential(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    api_key: SecretStr | None = None
    service_account_json: SecretStr | None = None   # e.g. a Vertex-AI-routed provider
    access_key_id: SecretStr | None = None            # e.g. an AWS-hosted provider
    secret_access_key: SecretStr | None = None
    region: str | None = None
    base_url: str | None = None
```

A superset bag of optional fields (deliberately not one type per provider — that would be an unnecessary
abstraction for seven providers). Each provider's factory function validates that the *specific* subset it
needs is present — a provider-specific concern, kept out of the shared type.

**Secret redaction (binding rule, extends v1 §20 failure #18's existing "never let a raw SDK exception
cross the boundary" rule):** in translating a provider SDK exception to this document's typed hierarchy,
every `ProviderAdapter` MUST strip/redact any header or field matching a known credential pattern
(`Authorization`, `api-key`, `x-api-key`, or the adapter's own known credential field names) from the
logged representation — never rely on the SDK's default `__str__`/`__repr__`.

**Boot-time cross-registry validation (closes review 1.1 mechanically):** after `ProviderRegistry` and
`ModelRegistry` both seal, a boot-sequence check confirms every `ModelDescriptor.provider_id` resolves in
`ProviderRegistry`; a mismatch raises `RegistryConsistencyError` and the process fails to start — consistent
with this system's existing fail-loud-at-boot discipline, not a new philosophy.

---

## C. Canonical architecture decisions — component boundaries

Seventeen components, each with exactly one responsibility. "State" distinguishes immutable, sealed-at-boot
configuration from genuine runtime state — `ProviderHealthStore`, `RateLimiter`/`CacheCoordinator`'s backing
stores, `LatencyTracker`, and `CostTracker`'s spend ledger hold the latter; everything else is either
stateless or immutable after boot.

| Component | Owns | Reads | Writes | Must NOT depend on | State | Failure behavior |
|---|---|---|---|---|---|---|
| **ProviderAdapter** | Translation to/from one provider's wire format; that provider's SDK client | Already-resolved `GenerateRequest`/etc. (model pinned) | Nothing persisted | `ProviderRegistry`, `ModelRegistry`, `RoutingEngine`, `BudgetGuard`, `CostTracker`, any other `ProviderAdapter` | Immutable per-instance HTTP client (connection pool); no request-scoped mutable state | Catches every provider SDK exception, redacts credentials (§B.18), re-raises via this document's typed hierarchy — never a raw SDK exception crosses the boundary |
| **ProviderRegistry** | `provider_id -> (ProviderDescriptor, ProviderAdapter)` | `Settings` (credentials, `enabled_providers`) — boot only | Nothing after `seal()` | `ModelRegistry`, `RoutingEngine`, any Capability-layer component | Immutable after boot (sealed) | `register()`/`resolve()` raise typed registry errors; boot fails loud on an unrecognized `enabled_providers` entry (§B.18) |
| **ModelRegistry** | `model_id -> ModelDescriptor` (pricing tiers, capability flags, `quality_tier`, `embedding_dimension`, modality limits) | Static declarative Python module (v1 §18) — boot only | Nothing after `seal()` | `ProviderRegistry` (referenced only by opaque `provider_id` string), any runtime component | Immutable after boot (sealed) | Boot-time `RegistryConsistencyError` if a `provider_id` doesn't resolve (§B.18) |
| **RoutingPolicy** | One ranking algorithm for one objective | `candidates`, `criteria`, `RoutingTelemetrySnapshot` (all passed in, §B.1) | Nothing — pure function (no I/O, no read of external state — see §B.1 for the precise definition, including the one named non-deterministic exception, `WeightedSplitPolicy`, §B.17) | Any I/O, any registry directly, `BudgetGuard`, `CostTracker` | Stateless | Exceptions isolated by `RoutingEngine` (§B.24), never propagate to the caller |
| **RoutingEngine** | Hard-filter → provider-enabled filter → exclusion-filter → health-filter → preference-ranking pipeline (§A.1 steps 1, 2, 2.5, 3, 5); `RoutingPolicyRegistry`; `LatencyTracker` invocation | `ModelRegistry`, `ProviderRegistry.is_enabled()`, `ProviderHealthStore`, `LatencyTracker`, the resolved `RoutingPolicy` | Nothing persisted; emits routing-decision events (§A.4) | `ProviderAdapter` directly (never dispatches), `BudgetGuard`, `CostTracker` | Holds sealed registries by reference; `RoutingPolicyRegistry` itself sealed-after-boot | `NoRoutableCandidateError` when zero candidates survive filtering (§A.1 step 4) |
| **LatencyTracker** | The rolling p50-latency-per-model sample (§B.1) the `FASTEST` routing objective ranks by | Nothing external — updated from real call outcomes | Itself — one sample per completed provider attempt, sourced from `attempt_latency_ms` observability events (§A.4.2) | `RoutingPolicy` (one-directional: `RoutingEngine` fetches a `RoutingTelemetrySnapshot` from it and passes that value into `rank()`; `RoutingPolicy` never reads `LatencyTracker` directly), `ModelRegistry`/`ProviderRegistry` content (keyed by opaque `model_id` strings only) | Runtime, Redis-backed for cross-process consistency — the same requirement as `ProviderHealthStore`/`RateLimiter`/`CacheCoordinator` | No data yet for a model, or backend unavailable → the returned snapshot simply omits that model; `RoutingPolicy` (§B.1) falls back to the static `quality_tier` heuristic — fails open, same posture as `ProviderHealthStore` |
| **FallbackPolicy** | Eligibility-filtering + dispatch loop + failure classification (§A.1 steps 6–8) | `RoutingEngine`'s ranked output, `CacheCoordinator`, `CostEstimator`, `BudgetGuard`, `ProviderRegistry.resolve()` | `ProviderHealthStore` (marks unhealthy/`runtime_unavailable`) | `CostTracker` (post-hoc only), `Capability`/`CapabilityExecutor` | Request-scoped attempted-pairs set only; cross-call state lives in `ProviderHealthStore` | `AllProvidersFailedError` with reason code on exhaustion (§A.1 step 8) |
| **RateLimiter** | Token-bucket state per key | The key list passed in (§B.2) | Bucket counters (Redis) | `ModelRegistry`/`ProviderRegistry` (receives ids as opaque strings) | Runtime, Redis-backed, cross-process | `RateLimitExceededError`; Redis-unavailable behavior is genuinely open (§F) |
| **CacheCoordinator** | Response/embedding/moderation cache read+write; key composition (§A.2) | `CacheKeyComponents` inputs (resolved candidate + request) | `CacheStore` (Redis) | `BudgetGuard`, `CostTracker`, `RoutingEngine` internals (receives the resolved candidate as a value) | Runtime, Redis-backed | **Always fails open** (treat as miss, §B.20) — never blocks or errors a call |
| **BudgetGuard** | Pre-flight approve/deny only (Phase 6 ownership, unchanged) | `CostTracker`'s ledger; the `worst_case` `CostEstimate` passed in by `FallbackPolicy`, on a cache miss only (Amendment C, §A.1 step 7/§A.3) | Nothing — read-only (unchanged, Phase 6 P5) | `LLMGateway`/`ProviderAdapter` (still forbidden — the new edge is `FallbackPolicy → BudgetGuard`, never the reverse), `CostEstimator` internals | Stateless itself; reads externally-owned ledger | `BudgetExceededError`, non-retryable, per candidate, never invoked for a cache hit (§A.1 step 7) |
| **CostEstimator** | Producing `(expected, worst_case)` from request shape + `PricingCatalog`, on a cache miss only | `PricingCatalog`, the candidate `ModelDescriptor`, request token-relevant fields | Nothing — pure function | `CostTracker` (never reads actuals), `BudgetGuard` (one-directional: estimator feeds guard only) | Stateless | Never raises for normal input; a missing pricing tier is a `ModelRegistry` boot-time data error, not a runtime failure here |
| **CostTracker** | Post-hoc, write-only cost recording; the spend ledger `BudgetGuard` reads (Phase 6 P5, unchanged) | `PricingCatalog` (§17.5 consolidation, decided), actual `CapabilityUsage` | The spend ledger; future `AIExecution` rows via `AIExecutionMapper` (Amendment B, still deferred) | `LLMGateway`/`ProviderAdapter`, `BudgetGuard` (one-directional: guard reads tracker, never the reverse) | Runtime, Redis-backed for cross-process consistency — the same requirement as `RateLimiter`/`CacheCoordinator`/`ProviderHealthStore`/`LatencyTracker`: `BudgetGuard`'s per-candidate check (§A.3, Amendment C) depends on a consistent view of spend across every worker process, or the centralization Amendment C claims doesn't actually hold at the scale in §E. Durable, cross-restart persistence of the underlying data remains a future-phase concern (Amendment B, still deferred) — this row is about cross-process *consistency today*, not long-term storage | A write failure here is a cost-audit data-loss risk, not call-blocking — the call already completed and returned. A ledger *read* failure during `BudgetGuard`'s check shares the same open fail-open/fail-closed question as `RateLimiter`'s (§F Q1) — not resolved here |
| **ObservabilityContext** | Nothing — a read-only value object carrying the id hierarchy (§A.4.1) | Nothing | Nothing (passed, not consulted) | Any stateful component; must never become a global/thread-local | Immutable, constructed once per `capability_execution_id`/`request_id`, threaded explicitly | N/A — a plain value object cannot fail |
| **`LLMGateway` implementation boundary** (the "Routing Gateway," v1 §1) | Composing every component above into the single, unchanged `LLMGateway` Protocol surface a `Capability` calls | Everything above | Nothing directly — delegates every write to its owning component | `Capability`/`CapabilityExecutor`/`Workflow` (no upward knowledge, Phase 6 P1 unchanged) | Holds every component above by reference, constructed once at boot (§B.25) | Never lets an internal component's exception cross unclassified — always one of this document's typed exceptions |
| **ProviderHealthStore** | Runtime `(provider_id, model_id) -> {unhealthy_until, runtime_unavailable, verified_flags}` (§A.1, §B.12) | Nothing external | Itself — from `FallbackPolicy` (health) and `CapabilityNegotiator` (verified flags, boot-time only) | `ModelRegistry`/`ProviderRegistry` content (keyed by opaque ids only) | **The one genuinely "hot" runtime state in this design** (§B.18) — Redis-backed for cross-process consistency | Backend unavailable → fail open (assume healthy) — an outage degrades to normal routing, never blocks all calls |
| **PricingCatalog** | Nothing new — a thin read accessor over `ModelRegistry.pricing_tiers` (§17.5, decided) | `ModelRegistry` | Nothing | `CostTracker`, `BudgetGuard`, `CostEstimator` (one-directional: everything reads from it) | Immutable, mirrors `ModelRegistry`'s sealed state | `UnknownModelPricingError` — should be unreachable given §B.18's boot-time cross-registry validation |
| **CapabilityNegotiator** | The boot-time behavioral verification pass (§B.12) | `ProviderRegistry`, `ModelRegistry` (claimed flags); issues real calls to each `ProviderAdapter` | `ProviderHealthStore.verified_flags` | `RoutingEngine`, `BudgetGuard`, `CostTracker` — runs once, at boot, outside the request path entirely | None of its own — writes only into `ProviderHealthStore` | A verification failure narrows routing eligibility for that specific flag only (§B.12), never blocks boot |

---

## D. Lifecycles — step-by-step

Each lifecycle assembles already-designed pieces (§A/§B/§C) into an explicit sequence; nothing new is
introduced here beyond ordering.

### D.1 Provider onboarding (the runbook — resolves B.7)

1. Write `integrations/llm_gateway/providers/<provider>_adapter.py` implementing `LLMGateway`. **Minimum
   viable bar, stated explicitly:** `generate()` alone is sufficient to onboard — every other method MAY
   raise `UnsupportedGatewayCapabilityError` until implemented.
2. Run it against `tests/contract/test_provider_adapter_contract.py` (v1 §19) — must pass before step 3.
3. Add its credential fields via `ProviderCredential` (§B.18) to `core/config.py` + a `.env.example` entry.
4. Add `ModelDescriptor` entries for every model this system will route to, including `pricing_tiers`
   (§B.8), `quality_tier` (§B.22), and any modality limits (§B.21).
5. Leave `provider_id` **out** of `enabled_providers` initially — registered in code, inert in production.
6. Deploy to staging. If `verify_capabilities_at_boot=True` (§B.12), confirm `CapabilityNegotiator` reports
   no unexpected flag mismatches.
7. Add `provider_id` to `enabled_providers`, restart (§B.18 — the only way a provider goes live).
8. Optional: use `WeightedSplitPolicy` (§B.17) to ramp traffic gradually rather than a full cutover.

### D.2 Provider startup/shutdown

**Startup:**
1. Load `Settings` (credentials, `enabled_providers`).
2. `build_provider_registry(settings)` — one adapter per enabled+credentialed provider; register; seal.
3. `build_model_registry()` — load the static module; register; seal.
4. Boot-time cross-registry validation (§B.18) — fail loud on mismatch.
5. Optional `CapabilityNegotiator.verify()` pass (§B.12).
6. Construct `RoutingEngine`, `FallbackPolicy`, `RateLimiter`, `CacheCoordinator`, `CostEstimator`,
   `PricingCatalog`, `ProviderHealthStore`; assemble the `LLMGateway` implementation boundary.
7. `build_registry(gateway, prompt_repository, budget_guard, tool_registry)` (§B.25) — construct every
   `Capability` with the now-ready Gateway injected; seal `CapabilityRegistry`.
8. Process ready to serve.

**Shutdown:** stop accepting new `Capability.execute()` invocations (orchestration-layer concern, outside
this document); in-flight `ProviderAdapter` calls complete or cancel per normal `asyncio` shutdown (§B.14);
no registry teardown is needed — everything is in-memory, process-scoped, reclaimed on exit.

### D.3 Model registration

1. New `ModelDescriptor` entry in the static module, `provider_id` must already exist in `ProviderRegistry`'s
   known provider list (need not be enabled).
2. Code review confirms capability flags match the provider's documented support — the human gate that
   precedes `CapabilityNegotiator`'s machine gate (§B.12).
3. Deploy + restart — no live registration (§B.18).
4. `availability` starts at `"beta"` or `"ga"` per author judgment.

### D.4 Model deprecation

1. Set `availability = "deprecated"`, `deprecation_note`, `replacement_model_id` (§B.17).
2. Deploy + restart. From here: selectable only via explicit `preferred_model`, never a default candidate.
3. Capabilities pinned to it migrate to `replacement_model_id` at their own pace — no enforced deadline.
4. Once unreferenced and past a retention period (a data-retention policy, not an architecture decision):
   `availability = "unavailable"`, eventual removal. Historical `AIExecution.model` rows referencing it
   persist forever — the forward requirement named in §B.26, unresolved by this phase.

### D.5 Request routing

1. `Capability` calls `LLMGateway.generate(request)` — single, unchanged call site.
2. `RateLimiter.acquire(keys)` (§B.2) — reject early if any bucket is exhausted.
3. `RoutingEngine` runs §A.1 steps 1, 2, 2.5, and 3 (hard filter → provider-enabled filter → exclusion
   filter → health filter), then step 5 (preference ranking).
4. `FallbackPolicy` runs §A.1 step 6 (eligibility filtering) — final bounded attempt sequence.
5. Sequence handed to the dispatch loop (§D.6).

### D.6 Fallback

1. For each candidate, in order: cache check first (§A.2) — a hit returns immediately, with no cost
   estimate or `BudgetGuard` check; on a miss, estimate cost → `BudgetGuard` approval (§D.11) → dispatch to
   `ProviderAdapter`.
2. Success: return `GenerateResponse`, write-through to cache if opted in, exit loop.
3. Failure: the same-candidate retry (§D.7, up to `max_same_candidate_retries`) is exhausted first; only
   then does `FallbackPolicy` classify `TRANSIENT`/`PERMANENT_INCOMPATIBLE` (§A.1 step 7), update
   `ProviderHealthStore`, and continue to the next candidate (moderation block raises immediately instead).
4. Exhaustion: reason-coded `AllProvidersFailedError` or `BudgetExceededError` (§A.1 step 8).

### D.7 Retry

1. Provider-HTTP level (innermost): up to `max_same_candidate_retries` (default 1) with short capped
   backoff, **nested inside a single candidate's "attempt" in §A.1 step 7** — the candidate is only
   considered failed, and only then does the sequence move to the next candidate, once this retry budget is
   exhausted too.
2. Gateway-internal: traversing the bounded fallback sequence, one exhausted candidate at a time, *is* this
   layer's retry — no separate mechanism.
3. Capability-internal: none by default; a `Capability` may implement its own (e.g., §B.9's structured-output
   retry), always producing a new `CapabilityCall`.
4. Workflow-level (outermost, Phase 5, unchanged): retries a whole step, starting a fresh
   `capability_execution_id` (§A.4.1) each time.
5. Multiplication ceiling (§B.19) is enforced at boot, not left as a convention.

### D.8 Streaming

1. `Capability` calls `generate_stream(request)`.
2. §D.5 steps 2–4 run identically, `requires_streaming=True` added to the hard filter.
3. Fallback permitted only before the Gateway's own first `yield` (§B.15).
4. `Capability` accumulates chunks into one `CapabilityCall` (`gateway_method: "generate_stream"`, unchanged).
5. Never cached (§A.2).

### D.9 Tool calling

1. `generate()` with `tools=[...]` — round 1 of at most `MAX_TOOL_ROUNDS` (§B.16).
2. Non-empty `tool_calls` → construct `ToolExecutionRequest(tool_call_id=..., ...)` (§A.4.1/§B.13) per call,
   resolve `(ToolDefinition, ToolExecutor, idempotent)` from `ToolRegistry`, execute within its allotted
   timeout slice (§B.16).
3. Append results as `role="tool"` messages, call `generate()` again — a new, independent `request_id`,
   full §D.5/§D.11 sequence again.
4. Repeat until `finish_reason == "stop"` or `MAX_TOOL_ROUNDS` exceeded (→ `ToolRoundLimitExceededError`).
5. Every round's `generate()` call is its own `CapabilityCall` (Phase 6 §4, unchanged).

### D.10 Structured-output validation

1. `generate(response_mode="json_schema", response_schema=...)`; Router already required
   `supports_structured_output` for this candidate.
2. Adapter uses native JSON mode where available (v1 §10, unchanged).
3. `Capability` validates the result against its own Pydantic model.
4. Mismatch → append a correction `Message` (§B.9, never mutates the rendered prompt), retry against the
   **same** resolved model — a second `CapabilityCall`, retry linkage recorded in `metadata`.
5. Second mismatch → `ValidationCapabilityError` (unchanged, non-retried).

### D.11 Cost estimation and recording

1. Per candidate, inside the dispatch loop: cache lookup first (§A.2) — a hit skips estimation and budget
   approval entirely, since serving it costs nothing. On a miss: `CostEstimator.estimate()` →
   `(expected, worst_case)` (§A.3).
2. `BudgetGuard.check(capability_name, priority, worst_case)` → approve/deny.
3. Denied → next candidate (§A.3's per-candidate re-approval). Approved → dispatch.
4. Success → actual `CapabilityUsage` from `GenerateResponse.usage`.
5. `CostTracker.record(actual_usage, resolved_model, capability_name, ...)` — post-hoc, updates the ledger
   `BudgetGuard` reads on the *next* call.
6. Material `actual`/`worst_case` deviation → `cost_estimate_variance` event (§A.4), never call-blocking.

### D.12 Failure and cancellation

1. Every failure classifies to `TRANSIENT`/`PERMANENT_INCOMPATIBLE` (§A.1 step 7) or a dedicated typed
   exception (`RateLimitExceededError`, `BudgetExceededError`, `NoRoutableCandidateError`,
   `AllProvidersFailedError`, `ContentModerationBlockedError`, `ToolRoundLimitExceededError`).
2. The `LLMGateway` implementation boundary never lets any of the above, or a raw provider exception, cross
   unclassified (§C).
3. `Capability` maps to the Phase 6 `CapabilityError` hierarchy (v1 §7, unchanged) —
   `RetryableCapabilityError`/`PermanentCapabilityError` per the existing mixed-flavor exhaustion rule.
4. `CapabilityExecutor` maps to `workflows.errors` (Phase 6 §5, unchanged) — untouched by this document.
5. **Cancellation** (§B.14): an outer timeout raises `asyncio.CancelledError` through the stack; every layer,
   `ProviderAdapter` especially, must let it propagate, never swallow it; SDKs unable to abort server-side
   are a named, accepted limitation (a shadow-cost trigger, §B.27).

---

## E. Scalability re-validation

| Dimension | Stays in-process | Must be distributed | Deferred | Stable interfaces |
|---|---|---|---|---|
| 10 providers | `ProviderRegistry` (dict, O(1), sealed) | — | — | `ProviderAdapter = LLMGateway` recursion (v1 §3, unchanged) |
| 100 models | `ModelRegistry` (dict, O(1) resolve; O(n) `filter()`, n=100 trivially fast) | — | Capability-flag indexing if `n` grows well past today's target | `ModelDescriptor` schema (now stable post-B.8/B.12/B.21/B.22 fixes — this pass's schema changes are the last ones expected before a Contract) |
| 50 capabilities | `RoutingCriteria.capability_name` as an opaque string throughout — zero structural cost per capability added | — | — | `CapabilityRegistry`/`build_registry()` wiring (§B.25, now fully specified) |
| Millions of requests | `RoutingPolicy.rank()`, `FallbackPolicy` eligibility filtering — pure, in-memory, sub-millisecond per call | `RateLimiter` (Redis, v1 §16/§21, unchanged), `CacheCoordinator` (Redis, §A.2), `ProviderHealthStore` (Redis — distributed requirement introduced by the §A.1 fix; the TTL-based health flag must be cross-process-consistent for the same reason the Rate Limiter and Cache already had to be), `LatencyTracker` (Redis, §B.1/§C, only if the `FASTEST` objective is ever implemented beyond its static fallback), **`CostTracker`'s spend ledger (Redis — classified consistently with the other four runtime stores in this row; `BudgetGuard`'s per-candidate check, §A.3, needs the same cross-process-consistent view of spend that motivates every other entry here, or Amendment C's centralization claim doesn't hold at this scale)** | Attempt-level cost telemetry (full shadow-cost closure, §B.27); latency-informed `FASTEST` beyond the static `quality_tier` fallback (v1 §6.1, unchanged) | `LLMGateway` Protocol surface (Phase 6, entirely untouched by this pass); `RateLimiter.acquire()`'s new list-based signature (§B.2 — this is the one Protocol this pass changes, and it is now considered stable) |

**Net effect of this correction pass on scalability:** one new distributed-state requirement
(`ProviderHealthStore`) was introduced as a *direct consequence* of fixing Critical Finding 1 (TTL-based
health recovery needs to be visible across worker processes the same way rate-limit and cache state already
did) — named explicitly here rather than left implicit, since re-evaluating scalability after a correction
pass means catching exactly this kind of second-order effect. A later consistency-fix pass found the
identical gap for `CostTracker`'s ledger and formally tabulated `LatencyTracker` (§C) — both are now
classified the same way, for the same underlying reason: any runtime state a per-candidate decision (health,
latency ranking, or budget approval) depends on must be cross-process-consistent at this scale, not merely
correct within one worker.

---

## F. Open questions requiring your approval

Only genuine judgment calls remain here — every mechanical defect from the review was resolved directly in
§A/§B/§C/§D, not deferred to this list, per instruction. Four of v1's seven open questions are now closed
(pricing consolidation, fallback-cost constraint, tool idempotency's safe boundary, streaming semantics —
see the "no longer open" line under Q4 below); three carry forward unchanged; four are new, produced by
decisions this pass had to make that are genuinely a matter of taste or risk tolerance, not correctness.

| # | Question | Option A | Option B | Recommendation | Impact |
|---|---|---|---|---|---|
| 1 | `RateLimiter`/`CostTracker`-ledger Redis-unavailable behavior (carried from v1 Open Q5, still open; §C's `CostTracker` row now names the same tradeoff for a ledger read during `BudgetGuard`'s check) | Fail open (unthrottled / unbudgeted) — availability-favoring | Fail closed (reject all calls) — safety-favoring | No recommendation — genuine availability-vs-safety tradeoff, same as v1, now shared by both components for the same reason | Determines whether a Redis outage becomes an AI-layer outage, or a rate-limit-storm / budget-under-enforcement risk |
| 2 | Model configuration format (carried from v1 Open Q4, still open) | Typed Python module (mypy-checked, this document's working assumption) | YAML/file-based, matching `PromptRepository`'s precedent | Leaning Python module, as v1 did — unchanged | Determines whether `ModelDescriptor` typos fail at import time or at runtime |
| 3 | "Provider hot swap" definition (carried from v1 Open Q6, still open) | Accept restart-required swap as sufficient (consistent with P9); §B.17's `WeightedSplitPolicy` is the closest this design gets to gradual, still restart-gated | Pursue true zero-downtime swap via an infra-level mechanism (blue-green deploy) outside this document's scope | Accept restart-required swap — unchanged from v1 | Determines whether "provider replacement" ever needs an application-architecture answer beyond what's already designed |
| 4 | `allow_cost_ceiling_override_on_exhaustion` default policy (NEW, from §A.1) | Global default `False` for every priority tier (this document's current design) | `True` by default for the highest priority tier only (e.g. urgent editorial tasks are allowed to exceed the cost ceiling rather than fail) | No recommendation — a real product-priorities question, not an architecture one | Determines whether a high-priority task can ever fail outright due to cost-ceiling exhaustion, or always eventually gets *some* candidate tried |
| 5 | `verify_capabilities_at_boot` (NEW, from §B.12) | Recommended but optional (`False` default, current design) | Mandatory in production boots (no override) | Leaning mandatory-in-production, but flagged as genuinely open since it adds a hard network+credential dependency to every boot | Determines whether a credential outage at boot time (vs. at first request time) becomes a deploy-blocking failure |
| 6 | `MAX_TOOL_ROUNDS` scope (NEW, from §B.16) | One global constant (default 3, this document's current design, mirroring `MAX_AGENT_ROUNDS`) | Per-`Capability`-configurable via `CapabilityConfig` (like `timeout_seconds` already is) | Leaning global constant for now — no capability exists yet to prove per-capability tuning is needed | Determines whether every future tool-calling capability shares one ceiling or can tune its own |
| 7 | `WeightedSplitPolicy` scope (NEW, from §B.17) | Manual-only — operator edits weights, redeploys (current design) | Add a minimal automatic rollback trigger (e.g., revert weights if the new split's error rate exceeds a threshold) | Manual-only for now — automatic rollback needs real production error-rate data/thresholds this document has no basis to guess at | Determines whether provider migration remains a fully human-supervised process or gains a first automated safety net |

---

**Status:** every Critical finding (§A.1–§A.4) is marked RESOLVED. Every Major finding from the review is
either resolved (§B.1–§B.27, most with a mechanical fix applied directly) or explicitly deferred with a
named, safe boundary (idempotency §B.13, MCP tier 2 §B.11, AIExecutionMapper partial-success §B.26, shadow
cost §B.27). No source code, migration, or Phase 1–6 file was modified. Exactly one Phase 6 contract rule is
amended (Amendment C, §A.3 — `BudgetGuard`'s call site moves from `Capability` to the Routing Gateway), and
it is a Critical-defect-driven amendment, not a stylistic one, as instructed. `docs/phase7_ai_integration_layer_planning.md`
and `docs/phase7_principal_architect_review.md` remain unchanged.

**Consistency-fix pass status:** all six Major findings from `docs/phase7_consistency_review.md` are applied
in place above — cache-before-budget ordering, same-candidate retry reconciled with the never-repeat rule,
the exclusion-filter position made consistent across §A.1/§C/§D.5, `LatencyTracker` added to §C's canonical
table, the `RoutingPolicy`/`WeightedSplitPolicy` determinism wording resolved, and `CostTracker`'s ledger
reclassified consistently with the other distributed runtime components. No Protocol signature was changed,
no new component was introduced, and no Phase 6 contract beyond the already-approved Amendment C was
touched. Waiting for your review of §F before an Architecture Contract is drafted.

