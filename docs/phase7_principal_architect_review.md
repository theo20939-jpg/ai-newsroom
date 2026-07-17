# Phase 7 Principal Architect Review — Adversarial Pass

No code, no migrations, no commits. This is an independent, adversarial review of
`docs/phase7_ai_integration_layer_planning.md` (the "baseline") and, secondarily,
`docs/phase7_architecture_review.md` (the "self-review" — the baseline's own author's first pass at
stress-testing itself). The objective stated for this pass is to break the design, not endorse it. Every
one of the 30 named areas is reviewed below. Findings are classified **Critical** / **Major** / **Minor** /
**Observation**. Proposed fixes are shown where the fix is mechanical; where a fix requires a judgment call
the baseline's author cannot make unilaterally, it is left as a named risk/question, not silently resolved.

**Method note:** several findings below are things the baseline's own self-review (`phase7_architecture_review.md`)
already surfaced (the `quality_tier` schema mismatch, the retry-multiplication ceiling, the
`MAX_AGENT_ROUNDS` ambiguity, cache fail-open, provider-exclusion routing gap). Those are restated here only
where this pass reaches a different or sharper conclusion. The findings that are new to this pass are the
majority of what follows — the self-review, written by the same author who wrote the baseline, has an
inherent blind spot for its own framing assumptions, which is exactly what an independent pass exists to
catch.

---

## 1. Provider Registry

| # | Issue | Severity |
|---|---|---|
| 1.1 | No boot-time cross-validation that every `ModelDescriptor.provider_id` in the Model Registry actually resolves to a registered `ProviderRegistry` entry. The two registries are built independently (§4/§5/§18) and trust each other by convention only. A model registered for a provider that's disabled via `enabled_providers` is silently excluded at *query* time (Router's provider-enabled filter, §6 step 2) but never flagged at *boot* time as orphaned data. | **Major** |
| 1.2 | `ProviderDescriptor` models credential shape as a single boolean (`requires_credential`) paired with one `SecretStr` in `Settings` (§18). This works for simple bearer-token providers but has no representation for providers needing structured, multi-field credentials — a Vertex-AI-routed Gemini needs a service-account JSON, not an API key; an AWS-Bedrock-routed Anthropic needs an access key + secret + region. The baseline's `.env.example`/`Settings` sketch (§18) assumes every provider is shaped like OpenAI. | **Major** |
| 1.3 | The in-memory `unhealthy` flag (§7) that the Fallback Chain sets on repeated auth/availability failure has no operator-facing control surface — no way to inspect it, no way to manually clear it short of a full process restart, and the baseline never states whether it auto-clears on a subsequent success. This is a real gap in "how providers are selected" (this section's own named topic) once an operator needs to intervene during an incident. | **Major** |
| 1.4 | `resolve()`/`is_enabled()` are total, side-effect-free, O(1) — no issue found here. | **Observation** |

---

## 2. Model Registry

| # | Issue | Severity |
|---|---|---|
| 2.1 | **Internal contradiction, carried from the self-review, still unresolved in the current document.** §6.1 recommends shipping `quality_tier: int` as a static field "now," but the canonical `ModelDescriptor` schema in §5 does not include it. As written, §5 and §6.1 disagree about what `ModelDescriptor` actually contains. This is not stylistic — a Contract drafted from §5's code block alone omits a field §6.1 treats as already decided. | **Major** |
| 2.2 | Pricing is modeled as a single flat `input_price_per_million`/`output_price_per_million` pair. This has no representation for cache-discount pricing (Anthropic's prompt-caching discount is commonly ~90% off cached input tokens — a pricing dimension that is provider-*published*, not a hidden implementation detail) or volume/tiered pricing. Every consumer of this field — the `LOWEST_COST` routing objective (§6) and the proposed `CostTracker` pricing consolidation (§17.5) — will be systematically wrong for any provider offering such a discount, in the *expensive* direction (overestimating true cost), which will misrank `LOWEST_COST` routing decisions against providers whose real effective price is lower than the flat number suggests. | **Major** |
| 2.3 | No `embedding_dimension` field on `ModelDescriptor`. §13 names a future `VectorStore` integration but the registry that's supposed to describe embedding models has no field recording the one property a vector store absolutely must know before accepting a vector (dimensionality). Mixing 1536-dim and 3072-dim vectors from two different embedding models in one future index is a well-known, easy-to-hit real-world bug class this schema does nothing to prevent. | **Major** |
| 2.4 | No per-modality limits (max images per request, max file size, max PDF page count) — see §11 (Vision) below; recorded here because the natural home for such limits is `ModelDescriptor`, and it doesn't have room for them. | **Major** (cross-referenced from §11) |
| 2.5 | `ModelDescriptor` mutation has no versioning/history. Editing an existing entry in place (e.g., correcting a wrongly-recorded `context_window_tokens`) leaves no trace that historical `CapabilityCall`/`AIExecution` rows referencing that `model_id` were produced under a *different* believed capability set. Not a defect in normal operation, but a real gap for any future analytics/audit tooling that joins historical execution data against "current" `ModelRegistry` state and implicitly assumes it describes the past accurately. | **Minor** |
| 2.6 | Dict-keyed, sealed, O(1) resolve, string `model_id` never backed by a DB enum — this part is correct and was the right call. | **Observation** |

---

## 3. Provider lifecycle

| # | Issue | Severity |
|---|---|---|
| 3.1 | **This is a named deliverable from the original Phase 7 brief (item 3 of 10) and the baseline does not actually contain a section by this name, or an explicit state-transition diagram.** The lifecycle is real and inferable — `UNREGISTERED → (enabled_providers + credential present, at boot) → REGISTERED → HEALTHY ⇄ UNHEALTHY (in-memory, §7) → [restart required] → DEREGISTERED` — but it is scattered as prose fragments across §3, §4, §7, and §18, never assembled as its own artifact. A reader cannot answer "what are all the states a provider can be in, and what triggers each transition" from one place in the document. | **Major** |
| 3.2 | The inferred lifecycle above has no `HEALTHY ← UNHEALTHY` recovery transition at all short of a full process restart — once the Fallback Chain marks a provider unhealthy (§7), nothing in the design ever re-probes or re-admits it within the life of the process, even if the underlying cause (e.g., a transient credential propagation delay) has since resolved. | **Major** (same underlying gap as 1.3) |

---

## 4. Model lifecycle

| # | Issue | Severity |
|---|---|---|
| 4.1 | Same deliverable gap as §3: no assembled Model Lifecycle section exists. The `availability` enum (`ga → beta → deprecated → unavailable`) is defined (§5) but the document never states who approves a transition, what triggers `ga → deprecated` (a provider announcement? a manual decision? an automated feed nothing here designs?), or what happens to in-flight requests that had already selected a model the instant it flips to `unavailable`. | **Major** |
| 4.2 | **Real audit/compliance risk not named anywhere in the baseline:** `AIExecution.model` (Phase 6, a plain string column) will, over years of operation, accumulate `model_id` values for models that have since been fully removed from the (sealed, static) `ModelRegistry`. Any future tool that tries to reconstruct "what were this model's capabilities/price at the time this historical row was written" by calling `ModelRegistry.resolve(model_id)` will get `UnknownModelError` for anything retired. The baseline's own `PromptRepository` precedent solves the equivalent problem for prompts by guaranteeing `(name, version)` resolves identically *forever* (Phase 6 contract §8's binding rule) — no equivalent permanence guarantee is proposed for retired `ModelDescriptor` entries. | **Major** |

---

## 5. Routing policies

| # | Issue | Severity |
|---|---|---|
| 5.1 | **Self-contradiction in the `RoutingPolicy` Protocol.** §6 states `rank()` is a "Pure function - no I/O, no provider calls" as a docstring-level contract. §6.1 then describes the `fastest` objective as requiring "a small in-memory (or Redis-backed...) rolling p50-latency-per-model sample, updated after every real call" — i.e., a `RoutingPolicy` implementation with real mutable state and, in the Redis-backed variant, real I/O. The Protocol as literally specified cannot honestly implement the one objective the document spends the most words justifying. Either the Protocol needs an injectable metrics dependency, or `fastest` needs to be permanently demoted to the static-heuristic fallback the baseline already offers as a stopgap ("cheapest among the top quality tier") — the document doesn't pick one, it asserts both. | **Major** |
| 5.2 | No defined behavior when a registered `RoutingPolicy.rank()` implementation itself raises. Given `RoutingPolicyRegistry` (§6.2) is explicitly designed as a third-party-extensible point ("prefer_provider_diversity" is used as an example of an objective someone else might register), a single buggy or slow policy implementation has an unbounded blast radius — it can break every `generate()` call across every provider and capability in the process, for as long as it's registered. No isolation, timeout, or fallback-to-default-policy behavior is specified for this case. | **Major** |
| 5.3 | `RoutingCriteria` has no negative/exclusionary field (`excluded_providers`, or similar) — only positive, advisory hints (`preferred_model`/`preferred_provider`). An operator who knows Provider X is having a quality regression *that never trips the Fallback Chain's failure table* (calls succeed, just badly) has no lever to steer traffic away from it short of the blunt, all-capabilities, restart-required `enabled_providers` toggle. | **Major** |
| 5.4 | No weighted/multi-objective scoring (e.g., "70% cost, 30% quality") — a single `RoutingObjective` enum per request. This is a reasonable v1 scoping choice, but it is never named as a limitation anywhere in the document; a reader could easily assume the four named objectives are the ceiling of what's architecturally possible rather than a deliberately narrow starting set. | **Minor** |

---

## 6. Fallback chain

| # | Issue | Severity |
|---|---|---|
| 6.1 | **The cost-non-increasing fallback rule (§7.1) can silently reduce the Fallback Chain to zero usable candidates for exactly the routing objective it's most obviously paired with.** As written: "no fallback candidate has a materially higher estimated cost than the first (preferred) candidate." Consider `objective=LOWEST_COST` (the objective whose entire purpose is to pick the *cheapest* viable candidate first): by construction, the first candidate is already the cheapest model that satisfies the hard filters. The cost-non-increasing rule then means **every other surviving candidate, being pricier by definition, is excluded from the Fallback Chain** — a `LOWEST_COST`-routed call that fails its first attempt has *no fallback at all*, silently, even though other capable candidates exist and were already ranked. This directly undermines the brief's explicit requirement to design a working fallback strategy, precisely for the objective most likely to be chosen by cost-sensitive, high-volume capabilities — exactly the capabilities most likely to be run at the "millions of requests" scale this document is supposed to survive. | **Critical** |
| 6.2 | The moderation-block no-fallback rule (§7) is sound reasoning, correctly scoped. | **Observation** |
| 6.3 | `max_fallback_attempts` bounding is correct and necessary; the interaction with §5.3 (no provider-exclusion lever) means an operator's only tool during a live incident is the same blunt on/off switch named there. | **Major** (cross-ref 5.3) |

---

## 7. Retry ownership

| # | Issue | Severity |
|---|---|---|
| 7.1 | The retry-multiplication ceiling (§8) is presented as "a reviewed, visible number... not left as an emergent property nobody computed" but nothing in any Protocol *enforces* that review — it is a naming convention plus a hoped-for code-review habit. At 50 capabilities and more than one contributor over the system's stated 5-year horizon, this is exactly the kind of cross-file arithmetic mistake that survives code review undetected (§8's own Critical Risk 5 admits as much but stops short of proposing a mechanical check). | **Major** |
| 7.2 | No correlation/attempt-id concept threads through the four nested boundaries (workflow / step / capability-internal / provider-HTTP). When a call fails after retries across all four layers, there is no way to reconstruct, from logs alone, "attempt 2 of workflow retry, fallback candidate 2 of 3, same-candidate retry 1" as a single traceable sequence — see §26 (Observability) for the fuller version of this gap. | **Major** (cross-ref §26) |
| 7.3 | The ownership split itself (Workflow retries whole steps; Gateway retries/falls back internally within one call) is the correct layering and is not in dispute. | **Observation** |

---

## 8. Streaming

| # | Issue | Severity |
|---|---|---|
| 8.1 | The "fallback allowed before first chunk, forbidden after" rule (§9) assumes a client can always cleanly distinguish "connection failed before any bytes arrived" from "connection failed after the provider had already started generating but before any chunk was flushed to this client." In practice, buffering intermediaries (an OpenRouter-style proxy, or even standard HTTP client buffering under certain SSE implementations) can make these two cases indistinguishable at the point the Gateway's timeout fires — the provider may have "started" but the client legitimately received zero bytes. The rule is well-intentioned but relies on a signal-clarity guarantee the transport layer doesn't obviously provide for every one of the seven named providers, several of which (OpenRouter explicitly) sit behind their own proxy layer. | **Major** |
| 8.2 | Streaming's non-interaction with synchronous capabilities is correctly reasoned and is not in dispute. | **Observation** |

---

## 9. Structured outputs

| # | Issue | Severity |
|---|---|---|
| 9.1 | **The schema-mismatch retry technique breaks a binding Phase 6 audit guarantee.** §10 proposes appending the schema-violation error to the prompt's `TASK`/`RULES` block for the retry attempt, "against the same resolved model, no re-routing." But Phase 6 contract §8 states, as a binding rule: *"A given `(name, version)` MUST resolve to the same `RenderedPrompt` forever... so that `AIExecution.prompt_version` remains a trustworthy audit pointer."* The retried call's actual rendered prompt is no longer reconstructable from `(name, version)` alone — it now also depends on an ad hoc runtime mutation the Capability performed. The `CapabilityCall.prompt_version` recorded for that second call points at a published version whose content, at the moment of that specific call, was not what was actually sent. The baseline neither acknowledges this tension nor proposes a fix (e.g., recording the injected correction text separately in `CapabilityCall`/`metadata` rather than folding it into the prompt content silently). | **Major** |
| 9.2 | Retrying against the *same* model on schema mismatch is presented as simply correct, without acknowledging the real cost: if the mismatch is systemic (this model genuinely cannot reliably satisfy this schema, not a one-off sampling fluke), the retry is very likely to fail the same way, burning a full round-trip before `ValidationCapabilityError`. A reasonable design choice (keeps retry `Capability`-owned per P3), but presented with more confidence than the tradeoff warrants. | **Minor** |

---

## 10. Tool calling

| # | Issue | Severity |
|---|---|---|
| 10.1 | Tool-call idempotency under retry (already named by the baseline itself as its own highest-severity open item, §23 Risk 1 / §25 Open Question 3) is confirmed here as genuinely unresolved and, independently, the single most consequential open item in the whole document — a side-effecting tool with no framework-level dedup, re-executed by a discarded-and-retried `Capability.execute()` attempt, is a correctness and safety defect the moment the first such tool ships. | **Critical** |
| 10.2 | `ToolExecutor.execute()` has no timeout parameter, and nothing states how its execution time relates to `CapabilityConfig.timeout_seconds`. A slow or hanging tool implicitly consumes the entire remaining Capability-internal timeout budget with no carve-out, potentially starving the subsequent `generate()` call the tool-use loop needs to make to process the tool's result — the loop could fail on a timeout that "should" have been the tool's problem alone. | **Major** |
| 10.3 | `ToolRegistry`'s sealed-after-boot pattern is architecturally consistent with every other registry in this system, but tools are the one category in this document explicitly expected to grow via a *dynamic-discovery* mechanism (MCP, §28) — see §28 for the sharper version of this tension. | **Major** (cross-ref §28) |

---

## 11. Vision

| # | Issue | Severity |
|---|---|---|
| 11.1 | `ModelDescriptor.supports_vision` is a bare boolean; there is no per-modality limit modeling (max images per request, max image size, max PDF page count) anywhere in the registry. A request can pass the Router's hard filter cleanly and still be structurally doomed — e.g., 40 images against a model capped at 20 per request — with the failure only surfacing at the provider adapter, generically, indistinguishable from any other provider error to the Fallback Chain. | **Major** |
| 11.2 | The `ContentPart`/`ArtifactRef` reuse for images, PDFs, and future audio/video is genuinely elegant and doesn't need a schema change for any of the four — this is a real strength worth stating plainly, not just an absence of problems. | **Observation** |

---

## 12. Embeddings

| # | Issue | Severity |
|---|---|---|
| 12.1 | No `embedding_dimension` field (restated from §2.3 — the natural home for this finding is here). | **Major** |
| 12.2 | **Confidence-level self-contradiction.** §13 calls the embedding cache "low-risk by construction" and recommends default-ON, TTL-free caching. §20's own failure table, entry 13, lists "a silent provider model behavior change under the same `model_id`" as a real, accepted, *unmitigated* risk. The same document is simultaneously confident enough to default the cache ON with no TTL and honest enough to list the exact scenario that breaks that confidence as an open risk — these two framings should be reconciled into one stated risk level, not left as two different tones in two different sections. | **Minor** |

---

## 13. Caching

| # | Issue | Severity |
|---|---|---|
| 13.1 | **The response cache key omits the resolved model.** §15 defines the key as `sha256(canonical GenerateRequest JSON)`. `GenerateRequest.preferred_model` is commonly `None` (routing-determined, the whole point of the Router). Two calls with byte-identical `GenerateRequest` content, routed at two different times to two *different* actual models (e.g., because the first-ranked candidate was healthy at time T1 and marked `unhealthy` by time T2 — a state change §7's Fallback Chain explicitly introduces), would hash to the **same cache key** despite representing output from two different models. A cache hit at T3 could silently return a response actually generated by a model that has since been deprecated or marked `unavailable` — the cache key is structurally detached from the one piece of information (which model actually produced this response) that determines whether reusing it is even valid. This is a genuine correctness bug in the caching design, not a hypothetical edge case — it is the *direct, mechanical* consequence of combining advisory (not pinned) model selection with a pre-routing cache key. | **Critical** |
| 13.2 | Cache-failure behavior (Redis unavailable) is specified for the Rate Limiter (§25 Open Question 5) but never asked for the Cache. Unlike the Rate Limiter, this isn't a genuinely open safety tradeoff — a cache miss on Redis failure is unambiguously the correct default (fail open, degrade to "no caching," never block or corrupt a call) — but the document never states it as a settled rule, leaving room for an implementer to bundle it with the harder Rate Limiter question and land on the wrong default by association. | **Major** |
| 13.3 | Three-cache separation (response / embedding / provider-native prompt cache) with distinct ownership is the correct shape and is not in dispute. | **Observation** |

---

## 14. Rate limiting

| # | Issue | Severity |
|---|---|---|
| 14.1 | **`RateLimiter.acquire(key: RateLimitKey)` takes exactly one key, but §16 claims four independently-enforced dimensions** (provider / model / tenant / capability). Nothing in the Protocol or the surrounding prose shows how a single call site composes a check across, e.g., "is the provider-wide bucket OK **and** is the per-model bucket OK **and** is the per-capability bucket OK" simultaneously. As specified, the caller can only ever pass one `RateLimitKey`, meaning only one dimension is actually enforced per call — the "four independently-configurable" framing oversells what the given signature can do. Either `acquire()` needs to accept a list of keys (all must succeed) or the design needs to state explicitly which single dimension wins when they conflict. | **Major** |
| 14.2 | Token-bucket, Redis-backed, keyed correctly for cross-process consistency — the right call, no issue with the underlying algorithm choice. | **Observation** |

---

## 15. BudgetGuard

| # | Issue | Severity |
|---|---|---|
| 15.1 | **The pre-flight estimate has no defined relationship to which model the Router will actually select, and this is not only a fallback-time problem.** §7.1 addresses the case where a *fallback* candidate is pricier than what `BudgetGuard` checked. It does not address the more basic case: `BudgetGuard.check(capability_name, priority, estimated_usage)` is called by the `Capability` **before** the Gateway has done any routing at all (Phase 6's fixed pipeline order, unchanged). If the `Capability` estimates cost assuming a cheap default model, but the Router's `BEST_QUALITY` (or any objective other than `LOWEST_COST`) objective picks an expensive model as its **first-ranked, non-fallback** candidate, `BudgetGuard`'s approval was never actually for the call that's about to happen — this is true on the very first attempt, not just on fallback. Neither Phase 6 nor this document specifies how a `Capability` is supposed to produce an accurate `estimated_usage` for a model it does not choose and cannot know in advance. This is a structural hole in the pre-flight budget check's validity, present from the first call, not an edge case introduced by fallback. | **Critical** |
| 15.2 | `BudgetGuard`'s pipeline position (pre-flight, once, read-only) is otherwise correctly preserved and not reopened by this document — the ordering discipline itself is sound; only the *input* to that check (the estimate) is unaddressed. | **Observation** |

---

## 16. CostTracker

| # | Issue | Severity |
|---|---|---|
| 16.1 | The proposed pricing consolidation (§17.5, Open Question 1 — `ModelRegistry` becomes the pricing source of truth) is the right direction, but it inherits §2.2's flat-pricing limitation wholesale: consolidating onto a source of truth that itself cannot represent cache-discount or tiered pricing means `CostTracker`'s *eventual* real cost computation will be systematically wrong for at least one already-named provider capability (prompt caching, §15) regardless of which table it reads from. Fixing the consolidation question (Open Question 1) without also fixing §2.2 solves the wrong half of the problem. | **Major** |
| 16.2 | The "shadow cost" of failed internal attempts (§17.2, already named as Critical Risk 2 by the baseline itself) is confirmed here as real and, notably, compounds with a case the baseline's Critical Risk list does not separately name — see §17 (AIExecutionMapper) below. | **Critical** (confirming the baseline's own classification) |

---

## 17. AIExecutionMapper

| # | Issue | Severity |
|---|---|---|
| 17.1 | **A second, distinct source of invisible real cost, not named by the baseline's shadow-cost discussion.** Phase 6's `AIExecutionMapper` maps `SUCCESS`-status `CapabilityCall`s only (Phase 6 contract §10.1, unchanged and correctly untouched by this document). Phase 7's tool-calling design (§11) means a single `Capability` execution can legitimately produce several `CapabilityCall`s — some `SUCCESS`, and, if the loop fails partway through, at least one `FAILED` — within one `CapabilityResult` whose overall `status` may itself be `FAILED`. Every `SUCCESS`-flavored call in that sequence represents **real, already-spent tokens**, but if the *overall* `CapabilityResult` is `FAILED`, none of this document or Phase 6 states whether those individually-successful `CapabilityCall`s still get mapped/persisted once real persistence is built. If they don't, real spend from partially-successful multi-call executions is invisible in exactly the same way as fallback-attempt shadow cost (§17.2) — a second, independent leak into the same blind spot, worth naming as its own risk rather than assuming it's covered by the existing Critical Risk 2. | **Major** |

---

## 18. PromptRepository

| # | Issue | Severity |
|---|---|---|
| 18.1 | Restated from §9.1: the structured-output retry technique (§10) is the one place Phase 7's design actually touches `PromptRepository`'s guarantees, even though `PromptRepository` itself is correctly never modified. The violation is behavioral (what a `Capability` does with a resolved prompt), not a Protocol change, which is exactly why it's easy to miss in a review that only checks "did any Protocol change" rather than "did any documented guarantee about that Protocol's *use* get quietly broken." | **Major** (same finding as 9.1, cross-referenced) |

---

## 19. LLMGateway

| # | Issue | Severity |
|---|---|---|
| 19.1 | The recursive "`ProviderAdapter` = `LLMGateway`, provider-scoped" design (§3) is genuinely elegant and is the single strongest structural decision in the document — confirmed here independently, not just accepted from the self-review. | **Observation** |
| 19.2 | **The contract test suite (§19) can only catch missing capability support, not silently degraded/lied-about capability support.** A `ProviderAdapter` that registers a `ModelDescriptor` with `supports_tools=True` but whose `generate()` implementation silently drops the `tools` field before calling the provider SDK (rather than raising `UnsupportedGatewayCapabilityError`) would pass every check the described contract test suite performs (Protocol-shape conformance, correct response types, `UnsupportedGatewayCapabilityError` raised for genuinely-unsupported methods). Catching this class of bug requires a *behavioral* assertion — "a tools-including request to a `supports_tools=True` model, given a prompt that obviously calls for a tool, actually produces `tool_calls` in the response" — which needs either a real provider call or a much smarter fake, neither of which the described suite includes. This is a real gap between what the registry *claims* about a model and what the code actually *does*, with no automated check bridging them. | **Major** |

---

## 20. CapabilityExecutor interaction

| # | Issue | Severity |
|---|---|---|
| 20.1 | **The "zero `CapabilityExecutor` changes needed" claim (§1, confirmed by the self-review) is true but sidesteps an unaddressed wiring gap one layer over.** Every `Capability` needs its `LLMGateway` (now, concretely, the Routing Gateway singleton, which itself holds the Provider Registry, Model Registry, Rate Limiter, and Cache) injected at construction (Phase 6 §2, P3). Phase 6's own `build_registry()` sketch (`docs/phase6_capability_framework_planning.md` §9) shows no Gateway parameter at all — capability construction in Phase 6 was sketched before a real Gateway existed to inject. Phase 7 introduces a real, stateful Routing Gateway object that must be constructed exactly once and threaded into every `Capability` at registration time, and neither document revisits `build_registry()`'s signature to show how. This is a genuine integration gap between the two already-written documents, not a hypothetical future problem — whoever writes the first real `Capability` against this design will hit it immediately. | **Major** |

---

## 21. Workflow interaction

| # | Issue | Severity |
|---|---|---|
| 21.1 | No changes proposed, none needed, none found under review. This is the cleanest boundary in the entire document — Workflow's ignorance of AI internals (P2, Phase 6) is fully preserved by every mechanism Phase 7 adds. | **Observation** |

---

## 22. Configuration ownership

| # | Issue | Severity |
|---|---|---|
| 22.1 | **Inconsistent operational ownership between adjacent, tightly-coupled concerns.** Provider enablement lives in `Settings`/`.env` (env var change + restart). Model configuration is proposed as a typed Python module (§18, code change + deploy). "Turn on DeepSeek" is, in practice, two completely different kinds of operational action performed by two different tools/people — flip an env var *and* verify DeepSeek's models already exist (and are marked `ga`) in a separate, version-controlled Python file — with nothing in the design confirming the two are in sync (this is the same underlying gap as §1.1's missing cross-registry validation, viewed from the operator's side rather than the boot sequence's side). | **Major** |
| 22.2 | `RateLimitKey.tenant_id` is explicitly pre-plumbed "ahead of need" (§16) for a future multi-tenancy concept, but no symmetric field exists anywhere near `ProviderDescriptor`/`ModelDescriptor` for a future per-tenant provider-access-control need (e.g., "tenant A may only use OpenAI"). If ahead-of-need plumbing is the stated policy for one future need, applying it asymmetrically to only one of the two places multi-tenancy would eventually touch is an inconsistency, not a neutral scoping choice. | **Minor** |

---

## 23. Secrets management

| # | Issue | Severity |
|---|---|---|
| 23.1 | No credential rotation story anywhere in the document. Every credential is `SecretStr` loaded once at boot via `pydantic-settings`; rotating a live credential requires a full process restart across every worker, with no discussion of the operational blast radius at "millions of requests" scale (a rolling restart, a brief dual-validity window, or an accepted downtime window — none are named as the intended approach). | **Major** |
| 23.2 | No explicit rule requiring provider adapters to redact credentials from error logs/exceptions. Several provider SDKs' default exception `__str__`/`__repr__` implementations include request headers (which carry the `Authorization`/API-key header) — a very common, well-documented real-world credential-leak vector, and nothing in §3's adapter-isolation rules or §20's "never let a raw SDK exception cross the boundary" rule explicitly calls out redaction as part of that translation obligation. | **Major** |
| 23.3 | Restated from §1.2: single-`SecretStr`-per-provider doesn't fit every real provider's actual credential shape. | **Major** (cross-ref 1.2) |

---

## 24. Provider onboarding process

| # | Issue | Severity |
|---|---|---|
| 24.1 | This is a named deliverable (brief item 24) and no assembled onboarding runbook exists in the baseline — the mechanics are real but scattered (write adapter file, §3; register in the provider factory list, §4; add credential field, §18; add `ModelDescriptor` entries, §5/§18; pass the contract test suite, §19), with no single checklist, no stated minimum-viable-adapter bar (must a new adapter implement all six `LLMGateway` methods before it can be enabled, or is `generate()` alone sufficient to go live?), and no staged/canary rollout guidance (see §25). | **Major** |

---

## 25. Future provider replacement

| # | Issue | Severity |
|---|---|---|
| 25.1 | The "hot swap" tension is already well-named by the baseline (Open Question 6) — confirmed here as correctly identified, not restated as a new finding. | **Observation** |
| 25.2 | **A distinct, unnamed gap: gradual/percentage-based traffic migration.** Replacing a provider in a real, high-traffic system is rarely a binary cutover — the standard practice is a canary or percentage-ramped shift while watching error/quality metrics. Today's design is strictly binary (`enabled_providers` on/off, restart-gated); nothing in the Router or `RoutingPolicy` design (§6) supports "route 5% of `Capability X`'s traffic to the new provider, ramping up," which is a materially different (and more production-realistic) need than the already-named hot-swap question. | **Major** |

---

## 26. Observability

| # | Issue | Severity |
|---|---|---|
| 26.1 | **This is the single largest gap in the entire baseline relative to the brief's own topic list.** There is no dedicated section, no correlation/trace-ID design threading through the four nested retry/timeout boundaries (§8, §7.2 above), no structured log event schema, and no metrics design (latency per provider/model, cache hit rate, fallback-chain depth actually used, rate-limiter rejection rate, per-provider error rate) anywhere in the document. The baseline mentions "worth a metric" and "surfaced in logs/metrics" as asides in two places (§7, §8) but never turns either into an actual design. For a system explicitly required to survive "millions of requests" across "10 providers" for "the next 5 years," operating without any designed observability layer is not a stylistic gap — it is a precondition for running the system at all past a small pilot scale. This should be treated as a blocking gap, not a nice-to-have addition. | **Critical** |

---

## 27. Failure handling

| # | Issue | Severity |
|---|---|---|
| 27.1 | The failure taxonomy is split across two tables (§7's trigger table and §20's failure-mode table) with overlapping but not identical framing, and neither states, in one place, the full chain: raw failure → Gateway-internal behavior → exception type raised → `CapabilityError` subtype it maps to → Workflow-level retry eligibility. A reader has to reconstruct this mapping by cross-referencing both tables plus §8's `AllProvidersFailedError` mixed-flavor rule. | **Minor** |
| 27.2 | Coverage of the failure modes actually named in the brief (provider fails, model unavailable, rate limited, timeout, moderation blocks, budget exceeded) is otherwise thorough and specific — this is a documentation-organization finding, not a coverage gap. | **Observation** |

---

## 28. Future MCP compatibility

| # | Issue | Severity |
|---|---|---|
| 28.1 | **The compatibility claim is optimistic in a way that doesn't survive contact with what MCP actually is.** §22 states MCP "becomes one more way to populate the Tool Registry... no `ToolExecutor` Protocol change required." This treats MCP as a static registration source. In practice, MCP's central value proposition is *dynamic* tool discovery — a client connects to a live MCP server and introspects its available tools at runtime, often per-session or per-user-configuration, not at process boot. This is in direct, unacknowledged tension with P9 ("no dynamic discovery... every capability/prompt/tool registered explicitly, at process start, before the relevant registry seals" — Phase 6 contract, a system-wide principle Phase 7 treats as sacred everywhere else). A real MCP integration under this design's current rules would only support a *static snapshot* of an MCP server's tools taken at build time — which defeats a meaningful fraction of what makes MCP useful in the first place (connecting a running system to a newly-available tool server without a restart). The document should state this honestly as a real, unresolved architectural conflict between P9 and a named future-compatibility target, not assert compatibility as if it were already achieved. | **Major** |

---

## 29. Future multi-agent compatibility

| # | Issue | Severity |
|---|---|---|
| 29.1 | Correctly and explicitly deferred, consistent with the existing Phase 6 non-goal, not reopened by anything in this document. No issue found. | **Observation** |

---

## 30. Future local model compatibility

| # | Issue | Severity |
|---|---|---|
| 30.1 | **Ollama-as-just-another-adapter is architecturally elegant but the design never addresses the one way local models are structurally different from all six HTTP-based providers: they may run synchronous, CPU/GPU-bound inference in-process or on the same host, not purely over an async HTTP call.** If a local-model `ProviderAdapter`'s `generate()` implementation calls blocking inference-library code directly inside an `async def` without offloading it (e.g., via `asyncio.to_thread` or a dedicated process pool), it stalls the entire event loop for the duration of that inference call — blocking **every other concurrent request across every other provider**, not just local-model calls. This is a real, concrete correctness risk specific to local models that the "just another `LLMGateway` implementation" framing (§3, §22) doesn't surface, because it's true of every *other* provider (all seven, including Ollama when accessed over its own local HTTP server rather than in-process) that they're pure async HTTP and this risk doesn't apply to them at all. | **Major** |

---

## A. If this architecture were deployed today, what would most likely require redesign within two years?

**Observability (§26).** Not because the rest of the design is unstable, but because it is the one entire
layer that doesn't exist yet as a design at all. The moment this system runs in production with real
traffic across even 3–4 providers, correlating a slow or failed request across four nested retry boundaries
(§7.2) without trace IDs, structured events, or metrics becomes operationally unworkable almost immediately
— this isn't a "nice to have that gets prioritized eventually," it's a "the team will build *something* for
this within the first month of real traffic, under production pressure, without the careful cross-boundary
design this document gives every other concern." Retrofitting tracing context through the Router, Fallback
Chain, and every `ProviderAdapter` after the fact — rather than threading it through from the start — is a
structural, cross-cutting change, not an additive patch, which is exactly the definition of "requires
redesign."

**Second-most-likely:** the `BudgetGuard` pre-flight estimate problem (§15.1). It is invisible in
development and low-traffic staging (misestimates are small in absolute terms) and becomes a real, visible
financial-control failure exactly at the volume this document is designed to reach — the failure mode is
silent until it isn't, which is the most dangerous kind of design gap to leave unresolved.

---

## B. Which parts are over-engineered?

- **`RoutingPolicyRegistry` as a fully pluggable, third-party-extensible system** (§6.2), built before a
  single real capability or provider adapter exists to prove which objectives are actually needed. Four
  named objectives plus a general extension mechanism, for a system with zero production routing decisions
  made yet, is more infrastructure than the current evidence justifies.
- **The four-layer nested timeout/retry model** (§8) is architecturally tidy but arguably one layer more
  than warranted before a real adapter exists to validate the numbers — folding the provider-HTTP timeout
  into "an adapter implementation detail with a documented default" rather than a named fourth architectural
  boundary with its own multiplication-ceiling formula would have been a lighter, equally correct starting
  point.
- **The three-cache taxonomy's provider-native prompt-caching row** (§15) is designed in enough detail to
  look decided, while its actual content is "left entirely to individual adapter discretion" — the level of
  table/prose investment doesn't match how little is actually specified.

---

## C. Which parts are under-engineered?

- **Observability (§26)** — essentially absent, as established above.
- **Secrets management** (§23) — no rotation story, no redaction rule, credential shape assumes every
  provider looks like OpenAI.
- **Provider onboarding process** (§24) — mechanics exist, scattered; no runbook, no minimum-viable-adapter
  bar, no staged rollout.
- **Cost accounting's actual pricing model** (§2.2/§16.1) — flat per-token pricing cannot represent
  cache-discount pricing that at least one named provider already publishes.
- **The `BudgetGuard` pre-flight estimate mechanism itself** (§15.1) — the check's *existence* is well
  specified; what number a `Capability` is actually supposed to pass in, given it doesn't control routing,
  is not specified at all.

---

## D. Which assumptions are risky?

1. That model pricing is representable as a flat per-million-token number (§2.2) — false for at least one
   already-named provider capability (prompt caching).
2. That a single `SecretStr` covers every provider's credential shape (§1.2/§23.3) — false for
   Vertex-AI-style or AWS-style credential shapes.
3. That "the first-ranked candidate's price" is a safe anchor for bounding fallback cost (§6.1) — breaks
   completely for the `LOWEST_COST` objective, the one it's most naturally paired with.
4. That MCP tool sources can be treated as "just another static registration input" (§28.1) — ignores MCP's
   actual dynamic-discovery value proposition and its direct tension with P9.
5. That most provider APIs don't bill genuinely failed requests, used to partially justify accepting the
   shadow-cost gap (§17.2) — the baseline's own text flags this as "unverified," which is honest, but the
   overall design still leans on it as an implicit mitigation.
6. That a `Capability` can produce an accurate `BudgetGuard` cost estimate without knowing which model the
   Router will actually pick (§15.1) — never stated as an assumption at all, which is itself the risk: an
   unstated assumption is harder to revisit than a named one.

---

## E. Which interfaces are likely to become unstable?

- **`RoutingCriteria`/`RoutingPolicy`/`RoutingObjective`** — will need real revision once actual capabilities
  and real routing data exist; the four-objective taxonomy is an untested guess, and §6.1's
  purity-vs-statefulness contradiction (5.1) alone guarantees `RoutingPolicy`'s signature isn't final.
- **`ModelDescriptor`** — pricing shape (2.2), missing `quality_tier` (2.1), missing `embedding_dimension`
  (2.3/12.1), and missing per-modality limits (2.4/11.1) are four separate, independent pressures on the
  same schema; it will not survive to a Contract unchanged.
- **`RateLimiter.acquire()`** — its single-key signature doesn't support the four-dimension enforcement the
  surrounding prose claims (14.1); this will need to change the moment more than one dimension is actually
  implemented.
- **`ProviderDescriptor`/credential injection shape** — will need to change the moment a non-bearer-token
  provider is onboarded (1.2/23.3).

---

## F. Can this architecture realistically support 10 providers, 100 models, 50 capabilities, and millions of requests without redesign?

**No — not as currently specified**, though the gap is narrower than it might sound. The registry mechanics
(Provider Registry, Model Registry, Router's filter-then-rank algorithm) genuinely do scale to these numbers
without redesign — that part of both prior documents' conclusions holds up under this pass too. But three of
this review's Critical findings are not "nice to fix eventually" items; they are correctness/production
blockers that get **strictly worse**, not better, at the exact scale named in the question:

- The cache-key bug (13.1) actively corrupts more responses the more traffic and the more provider
  health-state changes occur — both of which increase directly with request volume and provider count.
- The `BudgetGuard` estimate mismatch (15.1) compounds financial risk in direct proportion to request
  volume — a small per-call misestimate times millions of calls is a real, material discrepancy, not a
  rounding error.
- Observability's absence (26.1) becomes an operational blocker, not a cosmetic gap, at real multi-provider,
  high-volume scale — this isn't optional past a certain point, it's a precondition for operating the system
  at all.

The skeleton survives. The system as fully specified today would not survive contact with the stated scale
without first closing these three gaps — which is a real, if bounded, redesign, not a footnote.

---

## G. Three biggest technical debts that should intentionally remain deferred

Distinct from the Critical/Major items above (which must be fixed, not deferred):

1. **Latency-informed `fastest` routing and static `quality_tier` maintenance** (§5.1/§6.1) — fine to run on
   a static heuristic until real capabilities and real traffic exist to justify the added runtime-state
   complexity.
2. **True zero-downtime provider hot-swap and gradual/canary traffic migration** (§25.1/§25.2) — legitimate
   future needs, but building either before a single real provider adapter exists would be solving a
   problem with no evidence behind it yet; restart-based swap plus a documented manual-intervention runbook
   is an acceptable interim state.
3. **Vector DB integration and batch/async-job inference** (§13/§22) — correctly named, correctly
   undesigned; no capability depends on either today, and both would need real requirements from an actual
   RAG-adjacent or batch-processing capability to design well rather than speculatively.

---

## Scores

| Dimension | Score |
|---|---|
| Architecture Score | **6/10** |
| Production Readiness | **3/10** |
| Maintainability | **7/10** |
| Extensibility | **6/10** |
| Scalability | **6/10** |
| Future Compatibility | **6/10** |

**Rationale, briefly:** the layering discipline and the recursive `ProviderAdapter = LLMGateway` decision
(§19.1) are genuinely strong and pull every other score up from where the open defects alone would put them.
Production Readiness is scored lowest and separately from the others deliberately — the cache-key bug
(13.1), the `BudgetGuard` estimate gap (15.1), and the absence of observability (26.1) are the kind of gaps
that are invisible in design review and expensive in an incident, which is exactly what "production
readiness" is meant to measure independently of architectural elegance.

---

## Conclusion

**Not accepted as-is.** Critical and Major issues remain. The following must be corrected before an
Architecture Contract is written:

**Critical (blocking):**
1. Fallback cost-non-increasing rule can silently reduce the Fallback Chain to zero candidates under
   `LOWEST_COST` routing (§6.1) — needs a redesigned cost-bounding rule (e.g., anchor to `cost_ceiling` or a
   guaranteed minimum candidate depth, not "the first candidate's price").
2. Response cache key omits the resolved model, enabling stale/wrong-model cache hits (§13.1) — the cache
   key must incorporate the actual resolved `model_id`, not just the pre-routing `GenerateRequest`.
3. `BudgetGuard`'s pre-flight cost estimate has no defined relationship to the model the Router will
   actually select, on the *first* attempt, not only on fallback (§15.1) — requires an explicit design
   decision (this review does not have enough information to recommend one unilaterally; it is a genuine
   sequencing question between Phase 6's `BudgetGuard` contract and Phase 7's routing).
4. Observability is not designed (§26.1) — needs a dedicated section: correlation/trace-ID propagation
   across the four nested retry/timeout boundaries, a structured log event schema, and a metrics schema
   (latency per provider/model, cache hit rate, fallback depth used, rate-limiter rejection rate).

**Major (should be corrected, not merely noted):**
5. `quality_tier` schema inconsistency between §5 and §6.1.
6. `RoutingPolicy` Protocol claims purity but `fastest` requires mutable state — resolve one way or the
   other.
7. Missing exception-handling contract for a failing `RoutingPolicy` implementation.
8. `RateLimiter.acquire()`'s single-key signature doesn't support the claimed four-dimension enforcement.
9. Missing assembled Provider/Model/Request/Failure Lifecycle sections (named deliverables, not produced as
   distinct artifacts).
10. Missing assembled Provider Onboarding runbook (named deliverable, same gap).
11. `ModelDescriptor` pricing model too flat for cache-discount/tiered pricing.
12. No `embedding_dimension` field; no per-modality (image/PDF) limits.
13. Structured-output retry technique silently breaks Phase 6's prompt-version audit-trail guarantee.
14. `AIExecutionMapper`'s SUCCESS-only mapping leaves partial multi-call-execution cost invisible, a second
    instance of the shadow-cost problem.
15. Contract test suite cannot catch a provider adapter that silently degrades a claimed capability.
16. No wiring design for wiring the Routing Gateway singleton into `Capability` construction
    (`build_registry()` gap spanning Phase 6/7).
17. MCP compatibility claim doesn't engage with MCP's dynamic-discovery nature vs. P9.
18. Local-model adapters have an unaddressed blocking-I/O risk to the shared event loop.
19. No credential-rotation story; no secret-redaction rule for adapter error logs; single-`SecretStr`
    credential shape doesn't fit every provider.
20. No gradual/canary traffic-migration mechanism for provider replacement.

This is not a rejection of the architecture's shape — the registry/routing/fallback skeleton, the
`ProviderAdapter = LLMGateway` recursion, and the discipline of keeping all of this invisible above the
`CapabilityCall` boundary are sound and should not be redesigned. It is a rejection of treating the current
document as complete. Items 1–4 are correctness and completeness defects in the baseline as written, not
matters of taste; items 5–20 range from concrete schema/protocol fixes to named-but-unresolved judgment
calls that genuinely need your decision, not mine.

Waiting for direction on which of the above to correct before either document is revised, and before any
Architecture Contract is drafted.
