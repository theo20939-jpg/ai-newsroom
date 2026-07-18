# Phase 8 Architecture Contract — Capability Layer Specification

**Status: Final design specification. Single source of truth for the Capability Layer.**

This document converts `docs/phase8_capability_discovery.md`'s exploration into binding form. It
supersedes no prior document as a record of what was decided — it is not a revision of that
discovery document, and the discovery document is not edited by it. It **does** supersede the
discovery document as the thing future code and future contributors are validated against. Where
this document's wording differs from the discovery document's exploratory prose, this document
governs.

This document is normative. "MUST" / "MUST NOT" / "SHALL" / "SHALL NOT" statements are binding on
all Phase 8 implementation work. Where a rule is not yet enforced by tooling, it is enforced by
code review against this document — the same discipline Phase 6 and Phase 7 already establish.
Every rule below is written to be verifiable: either mechanically, or unambiguously by a reviewer
reading the code against the rule's exact text. No code is written, no existing code is modified,
no migration is created, and nothing is committed as part of producing this document.

This contract extends `docs/phase6_architecture_contract.md` and `docs/phase7_architecture_contract.md`
— it does not replace either, and it introduces no further amendment to either document. Every
principle, forbidden edge, and canonical rule in both remains binding and unchanged, including
Phase 7's Amendment C. Where this contract restates a Phase 6 or Phase 7 rule, that restatement is
for a Capability-implementer's convenience only, not a redefinition; the earlier contract remains
authoritative. This document governs `Capability` implementations exclusively — it does not alter
`CapabilityExecutor`, `CapabilityRegistry`'s own mechanics, `LLMGateway`, or any Phase 7 component.

---

## 1. Purpose

1. This contract defines the binding rules for `Capability` implementations — the layer between
   `CapabilityExecutor` (Phase 6, frozen) and `LLMGateway` (Phase 7, frozen, including Amendment
   C). Nothing above `CapabilityExecutor` or below `LLMGateway` is redesigned here.
2. This contract MUST be read together with, and is strictly subordinate to, the Phase 6 and
   Phase 7 contracts. Where any rule below appears to conflict with either, the earlier contract
   governs, except for the one explicit, already-settled correction restated in §17.4.
3. This contract MUST NOT modify, edit, or reinterpret Phase 6 or Phase 7 contract text.
4. This contract converts `docs/phase8_capability_discovery.md` into binding form. Where this
   contract's resolution of an open question differs from that document's recommendation (where
   one was offered), this contract governs; the discovery document remains historical context
   explaining *why*, not *what is currently required*.
5. This contract governs `Capability` implementations only. A rule below that also happens to
   describe `CapabilityExecutor`, `CapabilityRegistry`, `LLMGateway`, or `PromptRepository`
   behavior does so only insofar as it bounds what a `Capability` may assume of them — it does
   not create a new obligation on those components beyond what Phase 6/7 already impose.

---

## 2. Component Boundaries

### Forbidden dependency edges (extends Phase 6 §1 and Phase 7 §1's tables)

| Edge | Status |
|---|---|
| `Capability` → a provider SDK, directly or transitively | ❌ FORBIDDEN (Phase 6 P3, unchanged) |
| `Capability` → a database/ORM session or query | ❌ FORBIDDEN (Phase 6 P8, unchanged) |
| `Capability` → another `Capability` | ❌ FORBIDDEN (Phase 6 P4, unchanged) |
| `Capability` → `CapabilityExecutor` | ❌ FORBIDDEN (no upward dependency, unchanged) |
| `Capability` → any `workflows/` module | ❌ FORBIDDEN (Phase 6 P2, unchanged) |
| `Capability` → `BudgetGuard` | ❌ FORBIDDEN (Amendment C — restated, not re-amended, §17.4) |
| `Capability` → `CostTracker` | ❌ FORBIDDEN |
| `Capability` → `CacheStore` / `CacheCoordinator` / `RateLimiter` / `ProviderHealthStore` / `LatencyTracker` / `RoutingEngine` / `FallbackPolicy` / `ProviderRegistry` / `ModelRegistry` (direct) | ❌ FORBIDDEN — Phase 7 internal Gateway machinery, invisible to `Capability` (P14) |
| `Capability` → `LLMGateway` | ✅ REQUIRED — the sole AI ingress, injected at construction |
| `Capability` → `PromptRepository` | ✅ REQUIRED for any `Capability` that resolves a prompt, injected at construction |
| `Capability` → `ToolRegistry` | ✅ PERMITTED, optional — only for a `Capability` that invokes a tool, injected at construction |

### Component ownership

| Component | Owns | Reads | Writes | Must NOT depend on | State | Failure behavior |
|---|---|---|---|---|---|---|
| **`Capability`** (any implementation) | Turning one `CapabilityContext` into zero-or-more `LLMGateway` calls and one validated `CapabilityResult` | `CapabilityContext` (per call); `LLMGateway`, `PromptRepository`, optionally `ToolRegistry` (constant, injected) | Nothing persisted (P8) | Everything in the forbidden-edges table above | Constructed once at boot; holds no per-call mutable state (§3.2) | Raises only `CapabilityError` subtypes (§11) |

**Binding rules:**

1. No component named in this contract may be added to a `Capability`'s dependency set beyond
   `{LLMGateway, PromptRepository, ToolRegistry}` without a formal amendment (§19.1).
2. A `Capability` implementation MUST NOT exceed the dependency set the forbidden-edges table
   above grants it, regardless of what `build_registry()` itself is constructed with (§5.3).

---

## 3. Capability Lifecycle

1. A `Capability` implementation MUST be constructed exactly once per process lifetime, by
   `build_registry()`, with its dependencies injected — never self-constructed, never a per-call
   object.
2. A `Capability` instance MUST NOT hold any per-call mutable state. Every fact a given `execute()`
   call needs MUST come from either the `CapabilityContext` argument to that call or the
   Capability's own constant, injected dependencies.
3. `Capability.execute()` MUST be invoked at most once per `CapabilityExecutor.execute(step)` call.
4. A `Capability` MUST behave correctly and independently on every invocation — whether a first
   attempt or a Workflow-level retry carrying a fresh `capability_execution_id` — and MUST NOT
   retain memory of any prior `execute()` call, including a prior attempt of the same step.
5. A `Capability` MUST complete within the timeout `WorkflowRunner` already enforces (Phase 5,
   unchanged) and MAY additionally enforce its own, smaller internal timeout around its own
   Gateway calls.
6. `Capability.execute()` MUST terminate in exactly one of two ways: returning one
   `CapabilityResult` with `status="SUCCESS"`, or raising exactly one `CapabilityError` subtype.
   Partial, streamed, or multi-return behavior is FORBIDDEN.

---

## 4. Capability Protocol

1. The `Capability` Protocol (Phase 6 §2) is unchanged by this contract: exactly one method,
   `execute(context: CapabilityContext) -> CapabilityResult`, `async`.
2. A `Capability` implementation MUST accept, at construction, only: an `LLMGateway` instance, a
   `PromptRepository` instance, and — only if it invokes at least one tool — a `ToolRegistry`
   instance. It MUST NOT accept any other injected AI-facing dependency.
3. A `Capability` implementation MUST NOT accept a `BudgetGuard` at construction, under any
   circumstance (Amendment C).
4. A `Capability` implementation MUST NOT accept a `CostTracker` at construction.
5. A `Capability` implementation MUST NOT import a provider SDK, directly or transitively.
6. A `Capability` implementation MAY hold additional, purely computational dependencies that
   introduce no edge forbidden by §2's table (for example, a pure text-formatting utility).
7. A `Capability` implementation MUST satisfy the `Capability` Protocol structurally; this
   contract does not require inheritance from any particular base type to do so (§6.8, §14.6).

---

## 5. Capability Registry

1. Every `Capability` implementation MUST be registered via `capabilities.registry.build_registry()`
   before `CapabilityRegistry.seal()` is called.
2. `build_registry()`'s signature MUST remain
   `(gateway: LLMGateway, prompt_repository: PromptRepository, budget_guard: BudgetGuard, tool_registry: ToolRegistry) -> CapabilityRegistry`,
   exactly matching Phase 7 §19 rule 2.
3. The `budget_guard` parameter `build_registry()` accepts MUST NOT be passed to, stored by, or
   referenced from any `Capability` implementation constructed within it. It is accepted solely
   for signature-fidelity to Phase 7 §19 rule 2 and is never used (§17.5, §18 rule 19).
4. Each `Capability` MUST be registered under a unique `CapabilityDefinition.name`; registering two
   implementations under the same name is FORBIDDEN (Phase 6 §6, unchanged).
5. Registering a new `Capability` MUST require no modification to any already-registered
   `Capability`, to `CapabilityRegistry`'s own methods, or to `CapabilityExecutor` (§14.1).

---

## 6. Capability Execution

1. A `Capability` MUST construct every Gateway request it makes entirely from data available in
   the `CapabilityContext` it was given for that call and its own constant, injected dependencies.
2. A `Capability` MUST treat `preferred_model`/`preferred_provider` as advisory hints only and
   MUST NOT assume either will be honored (Phase 6 §7 / Phase 7 §4.1 rule 1, unchanged).
3. A `Capability` MUST NOT rely on any `RoutingObjective` other than the Gateway's default
   (`BEST_QUALITY`) being honored in this delivery, and MUST NOT use `preferred_model`/
   `preferred_provider` as a substitute mechanism for expressing a cost or latency objective
   (§16.2).
4. A `Capability` MUST assemble exactly one `CapabilityCall` per `LLMGateway` method invocation it
   makes, whether that invocation succeeds or fails (Phase 6 §4, unchanged).
5. A `Capability` MUST set `metadata["request_id"]`, `metadata["trace_id"]`, and
   `metadata["capability_execution_id"]` on every outgoing Gateway request, derived from
   `CapabilityContext.runtime` exactly per Phase 7 §16.1's formula (§12).
6. A `Capability` MAY set `metadata["cache_policy"]` to opt a specific call out of caching. It
   MUST NOT read, infer, or otherwise depend on cache state in any other way.
7. A `Capability` MUST catch every `GatewayError` subtype it can receive and translate it to a
   `CapabilityError` subtype before it propagates (§11).
8. The mechanism satisfying rules 4, 5, and 7 (call bookkeeping, observability-metadata stamping,
   and error translation) MUST be centralized in one shared, reusable location used by every
   `Capability` that calls `LLMGateway` — never independently reimplemented, divergently, per
   `Capability`. This contract does not mandate the mechanism's shape (a base class, composed
   helper functions, or another structure are all permitted) — only that centralization exists
   and is actually used (§16.3, §19.2 Q1).
9. The Capability Layer relies entirely on the multimodal abstractions already defined by the
   frozen Phase 7 Gateway contract: a `Capability` MAY represent non-text input using the existing
   `ContentPart(type="artifact_ref", ...)` shape and MAY read non-text output from the existing
   `GenerateResponse.artifacts` field (Phase 6 §7, unchanged). No additional Capability-layer
   abstraction for multimodal input or output exists or is required — a `Capability` handling
   images or other non-text modalities uses the same `Message`/`ContentPart`/`GenerateResponse`
   shapes every other `Capability` uses.

---

## 7. Prompt Management

1. A `Capability` MUST resolve every prompt it uses via `PromptRepository.resolve(name, version)`.
   It MUST NOT embed prompt content in its own source code as a substitute for a published prompt.
2. A `Capability` MUST fill the `CONTEXT`/`TASK` portions of its assembled message list from
   `CapabilityContext` data only, never from `PromptRepository`.
3. A `Capability` MUST NOT pass `CapabilityContext`, or any part of it, to `PromptRepository`
   (Phase 6 §8, unchanged).
4. A `Capability` MUST treat every `RenderedPrompt` returned by `resolve()` as immutable — it MUST
   NOT mutate `system`, `rules`, or `output_schema` before use (§10.2).
5. A concrete `PromptRepository` implementation MUST exist before any `Capability` is exercised
   outside a test double (§19.2 Q4).
6. That implementation MUST satisfy Phase 6 §8's binding rules unchanged: `resolve()` MUST be
   side-effect-free and MUST NOT perform a network call; a given `(name, version)` MUST resolve to
   the same `RenderedPrompt` for the life of the deployment; no mutating method (`register`,
   `update`, `publish`, `rollback`, or equivalent) MUST NOT ever be added to it.

---

## 8. Tool Integration

1. A `Capability` MUST hold a `ToolRegistry` dependency only if it invokes at least one tool; a
   `Capability` that never calls a tool MUST NOT accept one (§4.2).
2. The tool-use loop, where a `Capability` implements one, MUST live entirely inside that
   `Capability`'s own `execute()` call and MUST NOT be delegated to `CapabilityExecutor` or any
   Phase 7 component (Phase 7 §9.3, unchanged).
3. A `Capability` implementing a tool-use loop MUST bound it by `MAX_TOOL_ROUNDS` and MUST raise a
   `PermanentCapabilityError`-mapped failure on exceeding it (Phase 7 §9.4, unchanged).
4. A `Capability` MUST allocate each `ToolExecutor.execute()` call no more than its fair share of
   remaining execution budget, per Phase 7 §9.5's split (unchanged).
5. A `Capability` MUST respect a resolved tool's `idempotent` flag: for `idempotent=False` tools,
   it MUST NOT silently re-invoke a `generate()` call made after that tool already executed within
   the same `capability_execution_id` (Phase 7 §9.4, unchanged).
6. Registering a new tool via `ToolRegistry.register()` MUST require no change to
   `CapabilityExecutor`, `LLMGateway`, or any `Capability` not choosing to use that tool (§14.4).

---

## 9. Validation

1. Every `Capability` MUST validate its `structured_output` against, at minimum, the JSON Schema
   shape declared by the resolved prompt's `output_schema` before returning a `CapabilityResult`
   with `status="SUCCESS"` (Phase 6 P10, unchanged floor).
2. A `Capability` MAY apply additional, stricter validation beyond rule 1 (for example, a
   capability-specific typed model), using any mechanism of its own choosing. This contract does
   not mandate one (§16.4, §19.2 Q3).
3. A `Capability` MUST NOT return `status="SUCCESS"` if its `structured_output` fails the
   validation required by rule 1.
4. A `Capability` MUST NOT return free text as a final answer; every successful result's
   `structured_output` MUST be a JSON-serializable dict satisfying rule 1 (Phase 6 P10, restated).

---

## 10. Structured Outputs

1. When a `Capability` requests `response_mode="json_schema"`, it MUST rely on the resolved
   model's native structured-output mechanism (already guaranteed by the Gateway per Phase 7 §8
   rule 1) and MUST NOT additionally attempt prompt-based enforcement as a substitute.
2. On a schema-validation mismatch (§9.3), a `Capability` MAY retry exactly once, by appending a
   new `Message` describing the violation to its existing message list and calling `generate()`
   again against the same resolved model. It MUST NOT re-route to a different model and MUST NOT
   mutate the original `RenderedPrompt` content in doing so (Phase 7 §8 rule 3, unchanged).
3. A retry performed under rule 2 MUST record
   `{"retry_reason": "schema_validation_failure", "retried_call_id": <first attempt's call_id>}`
   in that retry's `CapabilityCall.metadata` (Phase 7 §8 rule 3, unchanged).
4. A second consecutive schema-validation mismatch for the same logical task MUST cause the
   `Capability` to raise `ValidationCapabilityError`; the `Capability` MUST NOT make a third
   attempt.

---

## 11. Error Handling

1. A `Capability` MUST raise only `CapabilityError` subtypes (Phase 6 §5, unchanged). It MUST NOT
   let a bare `Exception`, a `GatewayError` subtype, or any other unclassified exception cross its
   own `execute()` boundary.
2. The externally observable Gateway failure model — the complete set of exceptions a `Capability`
   can actually receive from an `LLMGateway` method call, verified against the real `FallbackPolicy`
   implementation — consists of exactly four types: `NoRoutableCandidateError` (raised before any
   dispatch is attempted, when no candidate survives routing), `ProviderModerationBlockedError`
   (raised immediately on a moderation block), `AllProvidersFailedError` (raised on fallback
   exhaustion, carrying a `reason` of `"cost_ceiling_exhausted"`, `"all_candidates_failed"`, or
   `"all_candidates_budget_denied"`), and `UnsupportedGatewayCapabilityError` (raised when a
   `Capability` calls a Gateway method the resolved implementation does not support). A `Capability`
   MUST classify each of these into exactly one `CapabilityError` subtype before it propagates: at
   minimum, `NoRoutableCandidateError` and `UnsupportedGatewayCapabilityError` MUST map to
   `CapabilityConfigurationError`; `ProviderModerationBlockedError` MUST map to
   `PermanentCapabilityError`; `AllProvidersFailedError` MUST map to `PermanentCapabilityError`,
   unless its `reason` indicates a purely transient exhaustion, in which case it MUST map to
   `RetryableCapabilityError` (mirrors Phase 7 §5.5's mixed-flavor-defaults-to-retryable rule).
3. `ProviderModerationBlockedError` carries special handling a `Capability` MUST preserve: it is
   raised specifically because content was blocked by moderation, is never retried at any layer
   below the Gateway boundary, and never triggers a fallback attempt against a different provider
   or model for the same disallowed content (Phase 7 §5.4). A `Capability` receiving it MUST NOT
   retry the same request against a different resolved model or provider itself, and MUST classify
   it as a non-retryable failure.
4. `ProviderTransientError`, `ProviderPermanentIncompatibleError`, `RateLimitExceededError`, and
   `capabilities.errors.BudgetExceededError` are all caught internally by `FallbackPolicy` during
   its per-candidate dispatch loop and never cross the Gateway boundary to a `Capability`, in either
   direction. A `Capability` MUST NOT write handling code expecting to catch any of these four
   directly from an `LLMGateway` method call — none of them is part of the externally observable
   failure model in rule 2. Budget exhaustion specifically is visible to a `Capability` only as
   `AllProvidersFailedError(reason="all_candidates_budget_denied")`.
5. The translation required by rule 2 MUST be centralized per §6.8 — never reimplemented
   independently, divergently, per `Capability`.
6. A `CapabilityTimeoutError` a `Capability` raises internally MUST be treated as retryable by
   default at the `CapabilityExecutor` boundary (Phase 6 §5, unchanged).

---

## 12. Observability

1. A `Capability` MUST derive `capability_execution_id` as
   `f"{task_id}:{capability_name}:{attempt}"` from `CapabilityContext.runtime`, exactly matching
   Phase 7 §16.1's formula. It MUST NOT invent a different derivation.
2. A `Capability` MUST set `trace_id`, `capability_execution_id`, and `request_id` on every Gateway
   request it makes (§6.5 names this obligation; this rule is its binding source).
3. A `Capability` MUST NOT construct or rely on any identifier outside Phase 7 §16.1's hierarchy;
   it MUST NOT introduce a new identifier scheme.
4. A `Capability` MUST NOT emit structured log events duplicating what `RoutingGateway`,
   `FallbackPolicy`, or a `ProviderAdapter` already emit for the same attempt — no redundant
   instrumentation of Gateway-internal machinery (P14).

---

## 13. Cost Accounting

1. A `Capability` MUST NOT compute cost itself, in any form (Phase 6 §9, unchanged).
2. A `Capability` MUST NOT call `BudgetGuard` or `CostTracker`, directly or transitively (§2, §4.3,
   §4.4).
3. A `Capability`'s `CapabilityResult.calls` list MUST include one `CapabilityCall` entry for every
   Gateway attempt made in producing that result, including failed attempts, each carrying the
   `usage` actually returned (or absent, if none was returned). Omitting a failed attempt from
   `calls` is FORBIDDEN.
4. A `Capability` MUST NOT read or infer its own remaining budget, current spend, or spend history
   from any source.

---

## 14. Extension Rules

1. Adding a new `Capability` MUST require zero changes to `workflows/`, `LLMGateway`,
   `PromptRepository`'s own contract, `CapabilityRegistry`'s methods, or any other
   already-registered `Capability`'s implementation.
2. Adding a new `Capability` MUST require exactly: one new `CapabilityDefinition`, one new
   `Capability` implementation, one new registration call in `build_registry()`, and — only if the
   Capability will persist `AIExecution` rows in a future phase — one new `capability_mapping`
   entry.
3. Adding a new prompt MUST require zero code change to any already-registered `Capability` that
   does not use it, and zero change to `PromptRepository`'s own contract.
4. Adding a new tool MUST require zero change to `CapabilityExecutor`, `LLMGateway`, or any
   `Capability` not choosing to use it (Phase 7 §22 rule 4, unchanged).
5. The Capability Layer MUST remain provider-agnostic: adding, removing, or replacing a provider
   adapter MUST require zero change to any `Capability` implementation, `CapabilityDefinition`, or
   this contract. Provider selection is decided exclusively inside `LLMGateway` (§2's forbidden-
   edges table already makes this structural — a `Capability` has no dependency on
   `ProviderRegistry`, `ModelRegistry`, or any `ProviderAdapter`); this rule states the resulting
   guarantee explicitly (Phase 7 §22 rule 1, unchanged).
6. No addition permitted under rules 1–5 may introduce a new Capability-layer component beyond
   what this contract names, or a new forbidden-edge violation, without a formal amendment
   (§19.1).

---

## 15. Testing Requirements

1. Every `Capability` implementation MUST have unit tests that exercise `execute()` without any
   dependency on a real network call, a real provider, or a real `LLMGateway` implementation.
2. A unit test MUST exercise a `Capability` against a fake `LLMGateway` — an object satisfying the
   `LLMGateway` Protocol with deterministic, test-controlled responses — never `RoutingGateway` or
   any real provider adapter.
3. A unit test that resolves a prompt MUST exercise the `Capability` against a fake
   `PromptRepository` — an object satisfying the `PromptRepository` Protocol — never a real,
   published prompt store.
4. A fake `LLMGateway` or fake `PromptRepository` used in testing MUST be deterministic: identical
   input MUST produce identical output on every test run, mirroring the same determinism
   `PromptRepository.resolve()` itself guarantees in production (§7.6).
5. No test in the standard test suite MUST make a real network call to a provider or issue a real
   request through `RoutingGateway`. This is unchanged from Phase 7's own binding practice.
6. An integration test that exercises a `Capability` against a real, fully assembled
   `RoutingGateway` MAY use real infrastructure only where the property under test cannot be
   proven any other way; such a test is a distinct tier from unit tests and MUST NOT replace them.
7. Each registered `Capability` MUST have at least one regression test proving its
   `CapabilityContext -> CapabilityResult` shape for its simplest, deterministic scenario. That
   test MUST continue to pass unmodified as the `Capability`'s own internals evolve, unless its
   contract-visible behavior itself intentionally changes.

---

## 16. Non-Goals

The following are intentionally **not** solved by this contract and MUST NOT be implemented as a
side effect of Phase 8 work:

1. Every non-goal named in Phase 6 §13 remains a non-goal here, unchanged: long-term/
   cross-execution memory beyond `step_results`, RAG orchestration, multi-agent coordination
   beyond `MAX_AGENT_ROUNDS`, long-running/continuous-monitoring capabilities, background
   autonomous agents, a plugin marketplace, distributed execution of a single capability,
   human-in-the-loop suspend/resume, and multi-event capabilities.
2. Reaching a `RoutingObjective` other than `BEST_QUALITY`, a per-call `cost_ceiling`, or a
   per-call `FallbackEligibility` override from within a `Capability` (§6.3) — closing this gap
   REQUIRES a Phase 7 contract change, not a Capability-layer one, and is not designed here.
3. A shared base class, mixin, or other specific code-level shape for the centralization required
   by §6.8 (§19.2 Q1) — only that centralization exists is binding; its shape is not designed.
4. Automated schema-to-typed-model generation or cross-validation tooling (§9.2, §19.2 Q3).
5. A full Prompt Publisher (authoring workflow, validation gates, promotion) — out of scope per
   Phase 6 §8. This contract requires only a minimal, lookup-only `PromptRepository`
   implementation (§7.5), never authoring or publishing tooling.
6. Nothing in this section is implemented as a side effect of any in-scope Phase 8 work.

---

## 17. Compatibility Guarantees

1. The `Capability` Protocol (Phase 6 §2) is untouched by this contract — one method,
   `execute(context) -> result`, unchanged.
2. `CapabilityContext`, `CapabilityResult`, `CapabilityDefinition`, `CapabilityConfig`,
   `CapabilityCall`, and `CapabilityUsage` (Phase 6 §3–§4) are untouched by this contract.
3. `LLMGateway`'s Protocol surface (Phase 6 §7, Phase 7 §27) is untouched by this contract.
4. This contract's one explicit correction to a literal reading of Phase 6 text is the same one
   Phase 7 Amendment C already made: `Capability` does not hold or call `BudgetGuard` (§4.3). This
   is not a new amendment — it is Amendment C's already-binding rule, restated here so it cannot
   be missed by reading Phase 6 §2/§9 in isolation.
5. `build_registry()`'s four-parameter signature (Phase 7 §19 rule 2) is untouched by this
   contract; §5.3 clarifies its `budget_guard` parameter's handling without changing the signature.
6. A `Capability`'s public-facing shape (what a Workflow author or `CapabilityExecutor` observes)
   MUST NOT change as a result of any future Capability-layer amendment unless that amendment
   explicitly says so (mirrors Phase 7 §27's own guarantee).

---

## 18. Canonical Rules

These rules are mandatory for all Phase 8 implementation and are the checklist future code review
validates against.

1. A `Capability` never imports a provider SDK, directly or transitively.
2. A `Capability` never calls another `Capability`.
3. A `Capability` never holds a database session or issues a query.
4. A `Capability` never holds or calls `BudgetGuard`.
5. A `Capability` never holds or calls `CostTracker`.
6. A `Capability`'s only permitted injected dependencies are `LLMGateway`, `PromptRepository`, and
   — optionally — `ToolRegistry`.
7. A `Capability` holds no per-call mutable state.
8. A `Capability` raises only `CapabilityError` subtypes across its own boundary.
9. Every exception in the externally observable Gateway failure model
   (`NoRoutableCandidateError`, `ProviderModerationBlockedError`, `AllProvidersFailedError`,
   `UnsupportedGatewayCapabilityError`) is translated to a `CapabilityError` subtype in one
   centralized, shared location; `ProviderModerationBlockedError` is never retried and never
   triggers further fallback.
10. `ProviderTransientError`, `ProviderPermanentIncompatibleError`, `RateLimitExceededError`, and
    `capabilities.errors.BudgetExceededError` never cross the Gateway boundary — `FallbackPolicy`
    catches all four internally; `AllProvidersFailedError(reason="all_candidates_budget_denied")`
    is the only externally observable budget-exhaustion signal.
11. Every Gateway call a `Capability` makes carries `trace_id`/`capability_execution_id`/
    `request_id`, derived exactly per Phase 7 §16.1's formula.
12. Every `structured_output` is validated against at least the resolved prompt's `output_schema`
    before a `SUCCESS` result is returned.
13. Every Gateway attempt, successful or failed, is recorded as one `CapabilityCall` in
    `CapabilityResult.calls`.
14. A structured-output correction retry is composed as an appended `Message`, never a mutation of
    the original `RenderedPrompt`, and never re-routed to a different model.
15. A tool-use loop, when one exists, lives entirely inside `Capability.execute()`, bounded by
    `MAX_TOOL_ROUNDS`.
16. `PromptRepository.resolve()` is the only path by which a `Capability` obtains prompt content;
    `CapabilityContext` never crosses into `PromptRepository`.
17. Adding a `Capability`, a prompt, or a tool never requires modifying any other
    already-registered `Capability`.
18. No Capability-layer component beyond what this contract names may be added without a formal
    amendment.
19. `build_registry()`'s `budget_guard` parameter is accepted but never passed to, or used by, any
    `Capability`.
20. Nothing in §16 (Non-Goals) is implemented as a side effect of in-scope work.

---

## 19. Future Ratification

### 19.1 Amendment process

1. An amendment to this contract MAY change a Protocol signature named herein, a component's
   ownership boundary (§2), or a canonical rule (§18). An amendment MUST NOT silently redefine a
   term this contract has already given a precise meaning to without explicitly superseding that
   definition.
2. An amendment is warranted only when a **Critical** or **Major** defect is found in this
   contract itself. A stylistic preference, or a discovery that an alternative design would have
   been nicer, does NOT warrant an amendment.
3. An amendment MUST be a new, separately lettered section appended at the true end of this
   document — never an in-place edit to §§1–18 or to a prior amendment's text.
4. An amendment is binding only once explicitly approved — a proposal alone does not amend this
   contract.
5. Removing an item from §16 (Non-Goals) REQUIRES an amendment, not merely a later implementation
   that happens to build it.

### 19.2 Pending items — provisional defaults, not open blockers

Each item below is a genuine judgment call carried forward from `docs/phase8_capability_discovery.md`,
left open there. Each is given a binding provisional default so this contract remains fully
implementable without further approval; none of them blocks any `Capability` from being built
under this contract's other rules.

| # | Question | Provisional default (binding until ratified) | Awaiting |
|---|---|---|---|
| Q1 | Exact shape of the §6.8/§11.5 centralization mechanism | Not specified; MUST exist, MAY take any shape (base class, composed helpers, or otherwise) | Validation against the first two or three real `Capability` implementations |
| Q2 | Whether/when a `Capability` may reach a non-default `RoutingObjective` or per-call cost ceiling (§16.2) | Not reachable; `BEST_QUALITY` only | A future, Phase-7-scoped extension to `RoutingGateway`'s metadata handling — outside this contract's authority |
| Q3 | Validation strategy beyond the §9.1 floor | `Capability` author's choice, unconstrained by this contract | Revisiting once patterns emerge across several real Capabilities |
| Q4 | `PromptRepository`'s concrete storage mechanism (§7.5) | Not specified by this contract | An implementation decision, made when it is built |
| Q5 | Whether `build_registry()`'s `budget_guard` parameter is ever given a legitimate use | No — treated as permanently unused (§5.3, §18 rule 19) | Only if a future, currently unnamed need arises |

1. A provisional default in this table is not equivalent to a canonical rule (§18). It MAY change
   without triggering §19.1's amendment process, since it was never fully settled to begin with —
   unless the change would also violate a canonical rule, in which case §19.1 applies.

---

*End of specification.*
