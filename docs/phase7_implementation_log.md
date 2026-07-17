# Phase 7 Implementation Log

Append-only progress log for the Phase 7 AI Integration Layer implementation, tracked against
`docs/phase7_architecture_contract.md` (frozen, unchanged) per the revised milestone plan at
`C:\Users\Theodor\.claude\plans\parallel-kindling-dolphin.md`. No milestone here implies a commit —
commits are made only on your explicit approval.

**Clean baseline (established before M0, after Docker/Postgres/Redis were confirmed up):**
195 passed, 0 failed, 0 skipped, 0 warnings (`python -m pytest -q`) — this count already includes
M0's own 14 new tests, since Docker was not available until mid-M0.

---

## M0 — Architecture boundary validator

**Files created**: `scripts/validate_architecture.py`, `tests/test_validate_architecture.py`.

**Files changed**: none.

**Tests added**: 14, in `tests/test_validate_architecture.py` (clean tree, workflow→capabilities,
workflow→llm_gateway, provider-SDK-outside-adapter, provider-SDK-inside-adapter-allowed,
capabilities/executor.py DB exemption, other-capability-file→database flagged,
gateway-boundary→capabilities flagged, budget_guard→gateway flagged,
cost_estimator→cost_tracker flagged, routing_policy→redis flagged, non-python/excluded-dir
skipping, syntax-error-reported-not-raised, custom-rule-set-injection).

**pytest**: 195 passed, 0 failed, 0 skipped (full suite, real Postgres+Redis via
`docker compose up -d postgres redis`).

**ruff**: `python -m ruff check scripts/validate_architecture.py tests/test_validate_architecture.py`
— clean.

**mypy**: `python -m mypy scripts/validate_architecture.py tests/test_validate_architecture.py`
— clean.

**Runtime evidence**: `python scripts/validate_architecture.py` against the real repo →
`validate_architecture: clean - 0 forbidden-dependency violations`.

**Architecture validation**: PASS (0 violations) — after one fix (see below).

**Finding fixed during this milestone (not a codebase defect — a bug in the new validator
itself)**: the first cut of the `capability-isolation` rule forbade any `database`-prefixed
import from `capabilities/` (other than `executor.py`). This flagged
`capabilities/capability_mapping.py`'s pre-existing, already-approved import of the
`AICapability` enum from `database.models.ai_execution` — a plain type reference, not a
database session or query, and not what Phase 6 contract §14 rule 1 / P3 / P8 actually forbids
("Capability → Database / ORM session"). Narrowed the rule's forbidden prefix from `database`
to `database.session` (the actual session/engine module); `sqlalchemy` stays forbidden as a
genuine ORM-usage signal. No production file was touched to make this pass — only the new
validator's own rule table was corrected.

**Known limitations carried forward**: the rule table is a hand-curated subset of the two
contracts' full forbidden-edge tables (documented in the script's own docstring) — it covers the
edges relevant to files that exist or will exist in this reduced delivery, not every abstract
edge naming a component with no file yet (e.g. `CapabilityNegotiator`, `ToolRegistry`, deferred
this delivery). Extend the `RULES` tuple by hand as new modules are added in later milestones.

**Working tree after this milestone**: `git status --short` shows only
`scripts/validate_architecture.py` and `tests/test_validate_architecture.py` as new, untracked
(plus the pre-existing untracked Phase 7 planning/review docs from the contract-audit session,
unrelated to this implementation work). No commit made.

---

## M1 — Settings, credentials and Gateway errors

**Files created**: `integrations/llm_gateway/errors.py` (full Gateway-layer exception
hierarchy: `GatewayError` base + 13 typed subtypes covering everything needed through M20's
reduced scope), `integrations/llm_gateway/providers/__init__.py`,
`integrations/llm_gateway/providers/base.py` (`ProviderCredential` per §17.2 +
`build_openai_credential(settings)`), `tests/test_settings_phase7.py`,
`tests/test_llm_gateway_errors.py`.

**Files changed**: `core/config.py` (added `enabled_providers`, `verify_capabilities_at_boot`,
`redis_unavailable_policy` — no default, per §28 Q1's binding provisional rule), `.env.example`
(mirrored additions with a Phase 7 comment block).

**Design correction made during this milestone**: originally planned `openai_provider_credential`
as a `Settings` *property* (per the pre-revision plan text). Implementing it that way would have
required `core/config.py` to import `integrations.llm_gateway.providers.base`, which — because
`core.config.settings` is imported by nearly everything, including `workflows/` — would
transitively pull Gateway-layer code into `workflows/`'s import graph even though no file under
`workflows/` names it directly, working against the spirit of Phase 6 P2 ("Workflow knows
nothing about AI"). Fixed by inverting the dependency: `build_openai_credential(settings)` is a
free function in `integrations/llm_gateway/providers/base.py` that takes `Settings` as a
parameter, so `core/config.py` imports nothing from the Gateway layer. This is an implementation
correction, not a scope or contract change.

**Tests added**: 39 total — 9 in `test_settings_phase7.py` (defaults, JSON-array env parsing for
`enabled_providers`, `Literal` validation for `redis_unavailable_policy` including a rejected
invalid value, `build_openai_credential` with and without a key), 30 in
`test_llm_gateway_errors.py` (parametrized hierarchy checks that every Gateway exception
subclasses `GatewayError` and none subclasses `capabilities.errors.CapabilityError`, plus
`AllProvidersFailedError`'s `reason` attribute).

**pytest**: 234 passed, 0 failed, 0 skipped (full suite, real Postgres+Redis).

**ruff**: clean on all touched files.

**mypy**: clean on all touched files, after one fix — `Settings(_env_file=None, ...)` isn't
visible to mypy without the pydantic mypy plugin (not configured in this repo); isolated to one
`# type: ignore[call-arg]` inside a single `_settings()` test helper rather than repeating it
per call site.

**Runtime evidence**: `python -c "..."` against the real, cached `get_settings()` singleton —
confirmed `enabled_providers=[]`, `verify_capabilities_at_boot=False`,
`redis_unavailable_policy=None` (this repo's real `.env` doesn't set any of the three), built an
OpenAI credential with `api_key is None` (no real key configured), and raised/caught
`AllProvidersFailedError` confirming `.reason` round-trips.

**Architecture validation**: PASS (0 violations).

**Known limitations carried forward**: `ProviderRegistry`/`ModelRegistry`/`RoutingEngine`/etc.
exception types exist in `errors.py` now but nothing yet raises them (those components land in
M3–M14). `ToolRegistry`/`CapabilityNegotiator`-related exceptions are intentionally not added —
both are deferred past this delivery per your scope reduction.

**Working tree after this milestone**: `git status --short` shows `.env.example` and
`core/config.py` as modified, and the files listed above as new/untracked (plus the same
pre-existing untracked Phase 7 docs). No commit made.

---

## M2 — ObservabilityContext

**Files created**: `integrations/llm_gateway/observability.py` (`ObservabilityContext` +
`derive_provider_attempt_id`/`derive_model_route_id`), `tests/test_observability_context.py`.

**Files changed**: none.

**Scope note**: only the two Gateway-internal derivations (`provider_attempt_id`,
`model_route_id`) are implemented. `capability_execution_id` is derived by
`CapabilityExecutor` (confirmed in `capabilities/executor.py` — already tracks `task_id`/
`attempt` internally), not this layer. `tool_call_id` belongs to `ToolExecutionRequest`,
deferred with the rest of §9's tool-calling framework past this delivery — no placeholder
added for it, per "do not expand scope."

**Tests added**: 6 — required-fields-only construction, `request_id` optional field, frozen
(`ValidationError` on mutation attempt), `extra="forbid"` rejection, and both derivation
helpers' exact string formats per §16.1.

**pytest**: 240 passed, 0 failed, 0 skipped (full suite).

**ruff**: clean. **mypy**: clean.

**Runtime evidence**: `python -c "..."` constructing a real `ObservabilityContext` and deriving
`provider_attempt_id`/`model_route_id` from it end to end — printed `call-1:0` and
`call-1:0:openai:gpt-4o-mini`, matching §16.1's `f"..."` formats exactly.

**Architecture validation**: PASS (0 violations).

**Known limitations carried forward**: none new. `ObservabilityContext` is not yet threaded
through any component — that begins at M6 (Golden Path).

**Working tree after this milestone**: only the two new files added versus M1's state (plus
the same pre-existing untracked Phase 7 docs and M1's modified `.env.example`/`core/config.py`).
No commit made.

---

## M3 — ModelRegistry and static OpenAI catalogue

**Files created**: `integrations/llm_gateway/models/__init__.py`,
`integrations/llm_gateway/models/registry.py` (`PricingTier`, `ModelDescriptor`,
`ModelRegistry` per §3, plus a `model_validator` enforcing §3 rules 3/4/9 — "standard" tier
required, `embedding_dimension` required when `supports_embeddings=True`, deprecation fields
required together — since these are stated as binding "MUST" rules, not left as unenforced
documentation), `integrations/llm_gateway/models/catalog.py`, `tests/test_model_registry.py`,
`tests/test_model_catalog.py`.

**Files changed**: none.

**Live-data verification performed before writing the catalogue** (per your explicit
instruction not to assume from training data): fetched `developers.openai.com/api/docs/pricing`
and `/models` directly, and cross-checked via web search against multiple independent
third-party pricing trackers. **Finding reported to you and confirmed**: OpenAI's current
lineup is a new **GPT-5.6 family (Sol/Terra/Luna), released 2026-07-09** — materially
different from the `gpt-4o`/`gpt-4o-mini` family a pre-2026 training cutoff would assume. This
does not conflict with the frozen contract (`model_id` is opaque, `PricingTier` is generic
`Decimal` fields per §3) — it's a factual "which real models" question, not an architectural
one. You confirmed seeding all three: `gpt-5.6-sol` ($5.00/$30.00 per 1M, quality_tier=100),
`gpt-5.6-terra` ($2.50/$15.00, quality_tier=70), `gpt-5.6-luna` ($1.00/$6.00, quality_tier=40),
all sharing a 1.05M-token context window and 128K max output. Only the `"standard"`
`PricingTier` is populated — batch/cached-input pricing for this family wasn't confirmed
against an official source, and §15.1 requires `"standard"`-tier-only estimation regardless.

**Tests added**: 22 in `test_model_registry.py` (register/resolve/seal mechanics,
duplicate/sealed/unknown-model errors, `filter()`'s hard requirements and
ga/beta-only-by-default behavior, frozen/`extra=forbid`, and all three validator rules —
embedding-dimension, standard-tier-required, deprecation-fields-together — against ad-hoc
descriptors, never the real catalogue); 7 in `test_model_catalog.py` (the real catalogue
resolves all three models, is sealed, raises on an unregistered id like `gpt-4o`, all three
share `provider_id="openai"` and a standard tier, and quality/price ordering is
Sol > Terra > Luna as intended).

**pytest**: 262 passed, 0 failed, 0 skipped (full suite).

**ruff**: clean. **mypy**: clean, after one fix — a test helper returning `object` couldn't
support `>` comparison; retyped to return `Decimal` directly instead of using `# type:
ignore`.

**Runtime evidence**: `python -c "..."` building the real catalogue, resolving all three
models, printing quality tier / pricing / context window for each, and running
`filter(requires_tools=True)` — all three qualify (all support tools), output matches the
verified pricing/quality-tier table exactly.

**Architecture validation**: PASS (0 violations).

**Known limitations carried forward**: the catalogue is OpenAI-only (by design, per your
provider-scope decision). `max_images_per_request`/`max_file_size_mb`/`max_pdf_pages` are left
at their `None` ("no declared limit") defaults for all three models — no official figure for
these was confirmed during verification, and `None` makes no false claim either way.

**Working tree after this milestone**: the three new files/dirs above added versus M2's state;
no other files touched. No commit made.

---

## M4 — ProviderRegistry and registry-consistency validation

**Files created**: `integrations/llm_gateway/boot.py` (`validate_registry_consistency()` only
so far), `tests/test_provider_registry.py`, `tests/test_registry_consistency.py`.

**Files changed**: `integrations/llm_gateway/providers/base.py` (added `ProviderAdapter =
LLMGateway` alias, `ProviderDescriptor`, `ProviderRegistry`, `ProviderFactory`,
`build_provider_registry()`); `integrations/llm_gateway/models/registry.py` (added
`ModelRegistry.all_models()` — a small, clearly-scoped addition needed by this milestone's own
`validate_registry_consistency()`, since the contract's given `ModelRegistry` code block only
lists `register`/`seal`/`resolve`/`filter`, and `filter()`'s availability parameter is typed to
exclude `"deprecated"`/`"unavailable"` by design — boot-time consistency checking needs *every*
registered model regardless of status, so a minimal enumeration accessor was required; not a
redesign, just plumbing the contract's own §3 rule 7 needs).

**Design note**: `build_provider_registry()` takes a `dict[str, ProviderFactory]` (descriptor +
credential-builder + adapter-builder bundle) rather than separate parallel dicts, keeping the
three per-provider pieces atomic and impossible to mismatch by index/key drift.

**Tests added**: 31 — 12 in `test_provider_registry.py` (register/resolve/seal mechanics,
duplicate/sealed/unknown-provider errors, `is_enabled()` before/after seal, plus
`build_provider_registry()`'s three rules: registers when enabled+credentialed, skips silently
when credential missing, skips silently when absent from `enabled_providers`, raises
`UnknownProviderError` when enabled with no matching factory, and seals its result); 3 in
`test_registry_consistency.py` (consistent registries pass, a dangling `provider_id` raises
`RegistryConsistencyError`, an empty `ModelRegistry` trivially passes); 1 in
`test_model_registry.py` for `all_models()`. A minimal locally-defined dummy adapter (not the
full `FakeProviderAdapter`, which lands in M5) structurally satisfies `LLMGateway` for these
registry-mechanics tests, which never call any of its methods.

**pytest**: 278 passed, 0 failed, 0 skipped (full suite).

**ruff**: clean. **mypy**: clean, after two fixes — `Settings(_env_file=None, **overrides)`
needed `**overrides: Any` (not `object`) for the unpacking itself to type-check, on top of the
already-established `# type: ignore[call-arg]` for `_env_file`.

**Runtime evidence**: `python -c "..."` exercising all four `build_provider_registry()`
branches end to end against a dummy adapter and OpenAI's real `build_openai_credential` — no
`enabled_providers` → not registered; enabled but no key → not registered; enabled + key set →
registered and resolvable; unknown enabled provider → raised `UnknownProviderError` with the
expected message. Then ran `validate_registry_consistency()` against the real OpenAI catalogue
(all three `gpt-5.6-*` models, `provider_id="openai"`) and a registry with `openai` enabled —
passed silently as expected.

**Architecture validation**: PASS (0 violations).

**Known limitations carried forward**: `build_provider_registry()` and
`validate_registry_consistency()` are not yet wired into any actual boot sequence — that's
M19. No real adapter factory exists yet (OpenAI's lands in M18); this milestone proves the
registry mechanics only, as planned.

**Working tree after this milestone**: the three new files above, plus modifications to
`providers/base.py` and `models/registry.py`; no other files touched beyond M1's
`.env.example`/`core/config.py`. No commit made.

---

## M5 — FakeProviderAdapter framework

**Files created**: `tests/fakes/fake_provider_adapter.py` (`FakeProviderAdapter`,
`FakeProviderBehavior`), `tests/contract/__init__.py`, `tests/contract/test_provider_adapter_contract.py`
(the exact file §20.1 step 2 names).

**Files changed**: `integrations/llm_gateway/errors.py` — added `ProviderTransientError`,
`ProviderPermanentIncompatibleError`, `ProviderModerationBlockedError`: the dispatch-level
exceptions a `ProviderAdapter` raises on failure, which a future `FallbackPolicy` (M15)
classifies into `FailureClass.TRANSIENT`/`PERMANENT_INCOMPATIBLE` (§5.2). Needed for
`FakeProviderAdapter` to raise something realistic; not present in M1's original hierarchy
because the fallback-classification design wasn't concretized yet at that point.

**Scope note**: only `generate()` has real, configurable behavior on `FakeProviderAdapter` —
`generate_stream`/`embed`/`classify`/`moderate`/`rerank` uniformly raise
`UnsupportedGatewayCapabilityError`, matching exactly what the real OpenAI adapter (M18) will
also do for those same deferred methods, per §2 rule 5's "generate() alone is sufficient to
onboard" minimum bar and your explicit scope reduction.

**Tests added**: 11 in `test_provider_adapter_contract.py` — successful `generate()` shape and
`call_count` tracking, all three failure behaviors raising their matching typed exception (with
`call_count` still incremented on failure), all five deferred methods raising
`UnsupportedGatewayCapabilityError`, and two distinct fake `provider_id`s proven independently
usable together (the mechanism M15's cross-provider fallback tests will build on).

**pytest**: 289 passed, 0 failed, 0 skipped (full suite).

**ruff**: clean. **mypy**: clean — one tooling quirk found and worked around: passing both
`tests/fakes/fake_provider_adapter.py` directly *and* `tests/contract/` (which imports it) in
the same mypy invocation triggers a "Source file found twice under different module names"
error, because `tests/` has no `__init__.py` while `tests/contract/` now does, so mypy infers
two different root packages for the same file. Worked around by never combining a direct
`tests/fakes/*.py` path with a test-package directory path in one invocation; verified both
`tests/fakes/fake_provider_adapter.py` alone and `tests/contract/` (which transitively checks
it via import) pass cleanly on their own. No source code changed for this — it's an `mypy`
invocation-ordering quirk from this repo's existing lack of a `tests/__init__.py`, not a defect
in any file.

**Runtime evidence**: `python -c "..."` (via `asyncio.run`) driving two independent
`FakeProviderAdapter`s — one `success`, one `transient_failure` — through `generate()`
end-to-end: the success adapter returned a valid response, the failure adapter raised
`ProviderTransientError` with the expected message, and both adapters' `call_count`
incremented correctly and independently.

**Architecture validation**: PASS (0 violations).

**Known limitations carried forward**: `FakeProviderAdapter` is not yet used by anything beyond
its own contract test — it becomes load-bearing starting at M6 (Golden Path).

**Working tree after this milestone**: the new files above; no other files touched beyond
earlier milestones' changes. No commit made.

---

## M6 — Golden Path: RoutingGateway.generate()

**Files created**: `integrations/llm_gateway/gateway.py` (`RoutingGateway`),
`tests/test_routing_gateway_golden_path.py`.

**Files changed**: none.

**Design note on ObservabilityContext propagation**: `LLMGateway.generate()`'s signature is
frozen exactly as Phase 6 §7 defined it (§27 compatibility guarantee) — no `observability`
parameter can be added to the public method. `RoutingGateway.generate()` therefore constructs
an `ObservabilityContext` internally, in `_build_observability_context()`, reading
`request.metadata["request_id"/"trace_id"/"capability_execution_id"]` (§16.1: request_id
explicitly travels this way; trace_id/capability_execution_id follow the same channel since no
other one exists), generating a fresh id as a fallback for anything a caller didn't set rather
than raising. That constructed context is then passed as an **explicit parameter** into
`_resolve_and_dispatch()` — proving the "never a contextvar, always explicit parameter passing"
discipline (§16.1 binding rule) at the one call boundary that exists so far. This internal
shape (`_resolve_and_dispatch(request, observability)`) is deliberately final now, not a
placeholder to be renamed later — M7–M17 fill in its body with real
cache/cost/budget/routing/fallback logic without changing this signature.

**Golden Path properties proven** (all per your explicit checklist): one resolved model (first
`ModelRegistry.filter()` candidate), one `FakeProviderAdapter`, no fallback (a second
registered provider/adapter is proven never touched), no retry, no cache, no `BudgetGuard`
decision, no `CostTracker` write (none of these objects exist yet, so nothing could be — a
structural guarantee, not just an untested absence), no real network (`FakeProviderAdapter`
only), deterministic response (two calls produce identical output), explicit
`ObservabilityContext` propagation (both the "ids provided" and "ids defaulted" paths tested).

**Tests added**: 7 — successful resolve-and-dispatch, determinism across repeated calls,
`NoRoutableCandidateError` on an empty `ModelRegistry`, explicit-id propagation, fallback-id
generation when metadata is empty, distinct fallback ids per call, and the "second provider
never touched" no-fallback proof.

**pytest**: 296 passed, 0 failed, 0 skipped (full suite).

**ruff**: clean. **mypy**: clean.

**Runtime evidence**: `python -c "..."` (via `asyncio.run`) building a `RoutingGateway` from a
real `ProviderRegistry`/`ModelRegistry` seeded with the actual `gpt-5.6-terra`
`ModelDescriptor` from M3's catalogue (not just an ad-hoc fake) and a `FakeProviderAdapter`
standing in for the not-yet-built real OpenAI adapter — `generate()` returned
`model_used="gpt-5.6-terra"`, `finish_reason="stop"`, and `_build_observability_context()`
correctly threaded the explicit `request_id`/`trace_id`/`capability_execution_id` supplied in
`request.metadata`.

**Architecture validation**: PASS (0 violations).

**Known limitations carried forward**: `RoutingGateway` is only constructed manually in tests
so far — no boot-sequence wiring exists yet (M19). `generate_stream`/`embed`/`classify`/
`moderate`/`rerank` are not implemented on `RoutingGateway` at all yet (not even an
`UnsupportedGatewayCapabilityError` stub) since they're deferred past this delivery and nothing
currently calls them on this class — they'll be added if/when a future, separately-approved
milestone implements them, consistent with "generate() alone is sufficient" (§2 rule 5) applying
to the composition root the same way it applies to an individual adapter.

**Working tree after this milestone**: the two new files above; no other files touched beyond
earlier milestones' changes. No commit made. **This is a natural pause point** — the first
working end-to-end slice (registries -> Gateway -> fake adapter -> response) now exists and is
fully verified.

---

## M7 — PricingCatalog and CostEstimator

**Files created**: `services/pricing_catalog.py` (`PricingCatalog` Protocol +
`ModelRegistryPricingCatalog`), `services/cost_estimator.py` (`CostEstimate`, `CostEstimator`),
`tests/test_pricing_catalog.py`, `tests/test_cost_estimator.py`.

**Files changed**: none. Neither wired into `RoutingGateway` yet, as planned.

**Underspecified-contract detail resolved conservatively, reported (not silently changed)**:
§15.1 explicitly gives the token-count source for `worst_case`'s output tokens
(`request.max_tokens`, else `ModelDescriptor.max_output_tokens`) but states no distinct formula
for `expected`'s output-token count. Since `expected` never gates anything (`BudgetGuard`
always checks `worst_case`, §15.2) and exists only for the `cost_estimate_variance`
observability event, this implementation mirrors `worst_case`'s figures for `expected` too,
documented inline, rather than inventing an unstated "typical case" heuristic (e.g. an
arbitrary fraction of max output). This is an implementation-detail gap, not a contract
conflict — nothing here contradicts any binding rule, so it did not warrant stopping.

**Tests added**: 4 in `test_pricing_catalog.py` (standard-tier lookup, non-standard tier lookup
when present, `UnknownModelPricingError` for an unregistered model, and for a present model
missing the requested tier condition); 7 in `test_cost_estimator.py` (`pricing_tier_used` is
always `"standard"`, `currency`/`model_id` carried through from the candidate, the
len/4 input-token heuristic verified by hand-computed arithmetic, `worst_case` using
`request.max_tokens` when set, falling back to `ModelDescriptor.max_output_tokens` when unset,
zero output cost when neither is set, and frozen/immutable).

**pytest**: 307 passed, 0 failed, 0 skipped (full suite).

**ruff**: clean. **mypy**: clean.

**Runtime evidence**: `python -c "..."` estimating cost for the real `gpt-5.6-terra`
`ModelDescriptor` (from M3's catalogue) against a 2000-character prompt — produced
`expected=worst_case=Decimal('1.921250')`, `currency='USD'`, `pricing_tier_used='standard'`;
hand-checked: 2000 chars / 4 = 500 input tokens × $2.50/1M = $0.00125, plus 128,000 max output
tokens × $15.00/1M = $1.92 — sums to $1.92125, matching exactly.

**Architecture validation**: PASS (0 violations).

**Known limitations carried forward**: neither component is wired into `RoutingGateway` yet —
that happens at M17 as part of the full pipeline.

**Working tree after this milestone**: the four new files above; no other files touched beyond
earlier milestones' changes. No commit made.

---

## M8 — CacheStore and CacheCoordinator

**Files created**: `integrations/llm_gateway/cache/__init__.py`,
`integrations/llm_gateway/cache/store.py` (`CacheStore` Protocol + `RedisCacheStore`),
`integrations/llm_gateway/cache/coordinator.py` (`CacheKeyComponents`, `CacheCoordinator`),
`tests/test_cache_store.py`, `tests/test_cache_coordinator.py`.

**Files changed**: `tests/conftest.py` — added a `redis_client` fixture (see fix below).

**Two underspecified/inconsistent contract details resolved, documented inline (not silent),
neither a genuine conflict**: §13.2's illustrative `CacheKeyComponents` code comments reference
two things Phase 6's frozen `GenerateRequest` doesn't have: (1) `cache_policy` as if it were a
request field — it doesn't exist, only `metadata: dict[str, Any]` does, so it's read from
`request.metadata.get("cache_policy", "read_write")`, exactly mirroring how `request_id`/
`trace_id`/`capability_execution_id` already established the "extend via metadata, never the
frozen schema" pattern; (2) `top_p` as one of `model_config_fingerprint`'s inputs — no such
field exists anywhere in this codebase's `GenerateRequest`, so it's omitted (the fingerprint
still covers every generation-configuring field that does exist:
`temperature`/`max_tokens`/`tool_choice`/`response_mode`). Both are documented in the module
docstring. Neither breaks the section's actual binding rule (`resolved_provider_id`/
`resolved_model_id` MUST be part of every key — implemented as dedicated `CacheKeyComponents`
fields, unaffected by either gap) — illustrative-comment field lists, not numbered "MUST"
rules, so this didn't warrant stopping the session.

**Not implemented, by design**: moderation-response caching (§13.5) and embedding-cache
keying — `moderate()`/`embed()` are both deferred past this delivery, so there is nothing yet
to cache for either.

**Bug found and fixed during this milestone**: the first cut of the `redis_client` test
fixture returned `core.redis.get_redis_client()`'s module-level `@lru_cache` singleton,
reused across every test. Since pytest-asyncio gives each test function its own event loop by
default, a connection pool first opened on one test's loop breaks (`RuntimeError: Event loop is
closed`) when a later test's loop tries to reuse it — the exact same failure mode
`db_session`'s own docstring already documents for `asyncpg`/`database.session.engine`. Fixed
by having the fixture construct a fresh `Redis.from_url(...)` client per test (closed in
teardown via `aclose()`), mirroring `db_session`'s existing pattern instead of reusing the
production singleton. 5 of the 20 new tests failed before this fix; all pass after.

**Tests added**: 7 in `test_cache_store.py` (miss-on-never-written, set/get byte round trip
including non-UTF-8 bytes, TTL-free persistence, TTL expiry making a key indistinguishable
from never-written, delete-removes, delete-of-absent-is-no-op) — all against real Redis with
uniquely namespaced keys cleaned up per test; 13 in `test_cache_coordinator.py` (store-then-
lookup round trip, genuine miss, different-resolved-model/provider never collide for an
otherwise-identical request, three never-cacheable predicates — non-`stop` finish_reason,
non-empty artifacts, `cache_policy != "read_write"` — plus the cacheable-by-default-when-absent
case, fail-open on both `lookup()` and `store()` against a raising fake store, fail-open on a
corrupt cached payload, key determinism, and one real-Redis integration round trip).

**pytest**: 327 passed, 0 failed, 0 skipped (full suite).

**ruff**: clean. **mypy**: clean, after one fix — `RedisCacheStore.get()`'s local variable was
over-narrowly annotated `str | None` when the installed `redis` stub returns `bytes | str |
None`; removed the explicit annotation and let it infer (`base64.b64decode` already accepts
both `str` and `bytes`).

**Runtime evidence**: `python -c "..."` (via `asyncio.run`) against real Redis — looked up a
request before storing (miss), stored a real `GenerateResponse`, looked up the same request
again (hit, `text == "cached!"`), then cleaned up the key.

**Architecture validation**: PASS (0 violations).

**Known limitations carried forward**: neither `CacheStore` nor `CacheCoordinator` is wired
into `RoutingGateway` yet — that happens at M17.

**Working tree after this milestone**: the five new files above plus the `conftest.py` fixture
addition; no other files touched beyond earlier milestones' changes. No commit made.

---

## M9 — RateLimiter

**Files created**: `integrations/llm_gateway/rate_limit/__init__.py`,
`integrations/llm_gateway/rate_limit/limiter.py` (`RateLimitKey`, `RedisRateLimiter`),
`tests/test_rate_limiter.py`.

**Files changed**: none.

**Design note**: §14 rule 1 requires the composite provider-wide/model-specific/capability-
specific key check to be **atomic and all-or-nothing** even under concurrent callers — a plain
Python loop doing separate Redis GET-then-SET calls per key cannot guarantee that (a race
between two concurrent `acquire()` calls could each see capacity and both consume it,
exceeding the limit). Implemented as a single Lua script (`EVAL`), which Redis executes as one
atomic operation across every key in the composite list, so no partial throttle can occur.
Capacity/refill-rate are constructor parameters (not part of `RateLimitKey`, which is identity-
only per the frozen §14 code block) — the contract doesn't specify numeric defaults, so this
implementation exposes them as tunable constructor arguments rather than inventing a hardcoded
"correct" limit.

**§28 Q1 enforcement**: `RedisRateLimiter.__init__` raises `MissingRedisFailurePolicyError`
immediately if `settings.redis_unavailable_policy` is `None` — the literal binding text of the
contract's own provisional rule for this still-open question. Once set, the runtime behavior on
an actual backend failure follows whichever policy was configured: `fail_open` lets the call
through, `fail_closed` raises `RateLimitExceededError` (the only signal `RateLimiter.acquire()`
can give a caller per its own Protocol, so reused rather than inventing a second exception type
for the same "call blocked" outcome).

**Tests added**: 9 — boot-time raise when the policy is unset, successful acquire within
capacity, exhaustion after capacity is consumed, the all-or-nothing proof (a composite acquire
against one already-exhausted key and one healthy key raises, and the healthy key's capacity is
provably untouched afterward — a solo acquire against it still succeeds), refill-over-time,
empty-key-list no-op, fail-open swallowing a simulated backend outage, fail-closed raising on
the same simulated outage, and `tenant_id`'s never-populated-by-default shape. All Redis-backed
tests use uuid-namespaced `provider_id`s and delete their own hash keys in `finally` blocks.

**pytest**: 336 passed, 0 failed, 0 skipped (full suite).

**ruff**: clean. **mypy**: clean, after two fixes — a test helper's `redis_unavailable_policy`
parameter needed the precise `Literal["fail_open","fail_closed"] | None` type instead of `str
| None`; monkeypatching `limiter._script` with a test double needed an explicit `# type:
ignore[assignment]` (deliberately swapping in a differently-typed callable to simulate a
backend outage).

**Runtime evidence**: `python -c "..."` (via `asyncio.run`) against real Redis with
`capacity=3`, two composite keys (`openai` provider-wide + `openai`/`gpt-5.6-terra`
model-specific) — three consecutive `acquire()` calls succeeded, the fourth raised
`RateLimitExceededError` naming both underlying Redis keys.

**Architecture validation**: PASS (0 violations).

**Known limitations carried forward**: not yet wired into `RoutingGateway` — that happens at
M17. `RateLimitExceededError` → `RetryableCapabilityError` mapping (§14 rule 3) is, as
documented in M1's `errors.py`, a future Capability author's responsibility, not performed in
this layer.

**Working tree after this milestone**: the three new files above; no other files touched beyond
earlier milestones' changes. No commit made.

---

## M10 — ProviderHealthStore

**Files created**: `integrations/llm_gateway/fallback/__init__.py`,
`integrations/llm_gateway/fallback/health_store.py` (`ProviderHealthStore` Protocol +
`RedisProviderHealthStore`), `tests/test_provider_health_store.py`.

**Files changed**: none.

**Design note**: the contract names this component and its `{unhealthy_until,
runtime_unavailable, verified_flags}` data shape narratively (§18's table row, §4.3 step 4,
§5.4's write points) but — unlike `RateLimiter`/`CacheStore` — gives no explicit Protocol code
block, so the method names (`mark_unhealthy`, `mark_runtime_unavailable`, `is_healthy`) are
this implementation's own reasonable design. `verified_flags` is deliberately **not**
implemented: it's written only by `CapabilityNegotiator`, which is deferred past this delivery
per your scope reduction, so there is no producer or consumer for it yet — building
unexercised storage for a feature with zero callers isn't "the smallest useful
production-oriented Gateway core." TTL semantics use an explicit `unhealthy_until_ms`
timestamp compared at read time, never Redis's own key-level `EXPIRE`, since both fields share
one hash key and `runtime_unavailable` must never expire — expiring the whole key would
silently clear it too.

**Tests added**: 9 — never-marked-pair defaults healthy, `mark_unhealthy` flips it unhealthy,
TTL expiry restores healthy automatically, `mark_runtime_unavailable` flips it unhealthy,
`runtime_unavailable` has no TTL to expire (re-checked after a short wait), `runtime_unavailable`
specifically survives past an *unrelated* `unhealthy_until` TTL lapsing on the same
(provider_id, model_id) hash key (proving the two fields don't interfere), and fail-open on
both `is_healthy` (returns `True`) and the two `mark_*` writes (swallow silently) against a
raising Redis stub. Redis-backed tests use uuid-namespaced pairs cleaned up per test.

**pytest**: 345 passed, 0 failed, 0 skipped (full suite).

**ruff**: clean. **mypy**: clean.

**Runtime evidence**: `python -c "..."` (via `asyncio.run`) against real Redis — a
never-marked `(openai, gpt-5.6-terra)` pair reported healthy; after `mark_unhealthy`, reported
unhealthy; a *different* model (`gpt-5.6-luna`) marked `runtime_unavailable` also reported
unhealthy, confirming both write paths and per-model-pair isolation.

**Architecture validation**: PASS (0 violations).

**Known limitations carried forward**: not yet wired into `RoutingEngine`/`FallbackPolicy` —
that happens at M14/M15. `verified_flags` support deferred until `CapabilityNegotiator` lands
(a separately-approved future milestone, outside this delivery's scope).

**Working tree after this milestone**: the three new files above; no other files touched beyond
earlier milestones' changes. No commit made.

---

## M11 — LatencyTracker

**Files created**: `integrations/llm_gateway/routing/__init__.py`,
`integrations/llm_gateway/routing/latency_tracker.py` (`RoutingTelemetrySnapshot` — moved here
from its first mention alongside `RoutingPolicy` since `LatencyTracker` is what actually
produces it — `LatencyTracker` Protocol, `RedisLatencyTracker`), `tests/test_latency_tracker.py`.

**Files changed**: none.

**Design note**: `record(provider_id, model_id, latency_ms)` matches the audited §4.6 Protocol
exactly, but `RoutingTelemetrySnapshot.p50_latency_ms_by_model` is keyed by `model_id` alone
(per §4.2's frozen shape) — in the ordinary case this is unambiguous since
`ModelDescriptor.provider_id` is a required FK, so one `model_id` belongs to exactly one
provider; in the rare case two providers coincidentally reuse the same `model_id` string,
`snapshot()` merges both providers' raw samples before computing the median rather than
silently dropping one. Storage is a bounded Redis LIST per `(provider_id, model_id)` (`LPUSH`
+ `LTRIM`, default rolling window 20 samples) plus a Redis SET index of every pair ever
recorded, so `snapshot()` enumerates exactly the models with data without an O(keyspace)
`KEYS`/`SCAN` scan.

**Tests added**: 6 — empty snapshot for a never-recorded pair, record-then-snapshot reports the
correct median, the rolling window caps at the configured size (verified by checking the raw
Redis LIST contents directly, not just the computed median), two distinct pairs don't
interfere, and fail-open on both `snapshot()` (empty result) and `record()` (swallowed) against
a raising Redis stub. Redis-backed tests use uuid-namespaced pairs cleaned up per test
(deleting both the sample LIST and removing the pair from the index SET).

**pytest**: 351 passed, 0 failed, 0 skipped (full suite).

**ruff**: clean. **mypy**: clean.

**Runtime evidence**: `python -c "..."` (via `asyncio.run`) against real Redis — recorded three
latencies (150/250/350ms) for `gpt-5.6-terra`, `snapshot()` correctly reported the median
(250.0).

**Architecture validation**: PASS (0 violations).

**Known limitations carried forward**: not yet wired into `RoutingEngine` (`FASTEST` objective
consumption) — that happens at M14.

**Working tree after this milestone**: the three new files above; no other files touched beyond
earlier milestones' changes. No commit made.

---

## M12 — Real Redis CostTracker and BudgetGuard

**Files created**: `tests/test_cost_tracker_real.py`, `tests/test_budget_guard_real.py`.

**Files changed**: `services/cost_tracker.py` (`RedisCostTracker` added; `CostTracker`
Protocol docstring corrected per §15.3's supersession of Phase 6's "own model-price table"
wording), `services/budget_guard.py` (**signature change** — see below), `tests/test_budget_guard_protocol.py`
(updated to the new signature).

**Confirmed-with-you signature change (Amendment C, §25)**: Phase 6's `BudgetGuard.check(request:
BudgetCheckRequest{capability_name, priority, estimated_usage: CapabilityUsage})` is replaced
with `check(capability_name, priority, worst_case: Decimal)`, matching Amendment C's explicit
pseudo-signature and its statement that `CostEstimator` is "the sole producer of the
`worst_case` estimate `BudgetGuard.check()` consumes." `BudgetCheckRequest` is removed — it no
longer matches the actual approved calling convention. I verified before touching anything that
**no production code called the old signature** (`capabilities/executor.py` confirms
`CapabilityExecutor` never calls `BudgetGuard`, matching Amendment B's existing deferral); the
only casualty was the one Phase 6 shape-only test, which you approved updating. `CostTracker.record()`'s
signature is untouched — Amendment C doesn't touch it — confirmed by `tests/test_cost_tracker_protocol.py`
passing unmodified.

**Design notes**:
- Both `RedisCostTracker`/`RedisBudgetGuard` accept an optional `ledger_namespace` — `None`
  (production default) computes the real UTC calendar date at each call; tests inject a fixed
  uuid-based namespace instead, so repeated runs on the same real day never share ledger state
  (avoids relying on date-based cleanup, which would risk cross-test contamination on a shared
  key).
- `RedisCostTracker.record()` reads pricing exclusively via `PricingCatalog` (§15.3), computing
  actual cost the same way `CostEstimator` computes estimates, but from `call.usage`'s real
  token counts. Per §18's CostTracker row, it writes **only** the Redis spend ledger — no
  `AIExecution` database row, no migration (Amendment B remains in effect, explicitly still
  deferred by §18's own text: "future AIExecution rows (Amendment B, still deferred)").
- `record()` write failures are **unconditionally swallowed**, regardless of
  `redis_unavailable_policy` — per §18's explicit failure-behavior column: "Write failure is a
  cost-audit data-loss risk, not call-blocking; ledger-read failure shares §28's open question."
  Only `RedisBudgetGuard`'s ledger *read* branches on the fail-open/fail-closed policy — this is
  why only `RedisBudgetGuard`, not `RedisCostTracker`, requires `redis_unavailable_policy` to be
  set at construction (`MissingRedisFailurePolicyError` otherwise).
- `RedisBudgetGuard` denies if today's recorded global spend plus `worst_case` would exceed
  `settings.max_daily_ai_cost` (an existing, previously-unused Settings field — no new
  configuration invented). `priority` is accepted (Protocol shape, included in the denial
  message) but doesn't currently scale the ceiling per tier — the contract specifies no
  tier-based allocation formula, so none was invented.

**Tests added**: 14 — 5 in `test_cost_tracker_real.py` (global-ledger increment matches
hand-computed cost, per-capability breakdown also increments, accumulation across multiple
calls, zero-cost/no-raise when `model_used` is `None`, write failures swallowed); 9 in
`test_budget_guard_real.py` (boot-time raise when policy unset, always-allow when no ceiling
configured, allow under ceiling, deny when `worst_case` alone exceeds it, deny when existing
spend + `worst_case` exceeds it, allow at the exact ceiling boundary, denial message names the
capability, fail-open vs fail-closed on a simulated ledger-read outage). `test_budget_guard_protocol.py`'s
2 tests were updated in place to the new signature (count unchanged).

**pytest**: 365 passed, 0 failed, 0 skipped (full suite) — includes the pre-existing
`test_cost_tracker_protocol.py` passing unmodified, confirming `CostTracker.record()`'s
signature truly wasn't touched.

**ruff**: clean. **mypy**: clean, after one fix — `redis_client.get()`'s return type
(`bytes | str | None`) needed an explicit `Decimal(str(raw))` conversion in four test
assertions rather than passing the union type directly to `Decimal()`.

**Runtime evidence**: `python -c "..."` (via `asyncio.run`) driving the full
`CostTracker` → `BudgetGuard` interaction against real Redis and the real `gpt-5.6-terra`
pricing from M3's catalogue: recorded a call (100K input + 50K output tokens → hand-verified
$0.25 + $0.75 = $1.00), then confirmed a second `check()` for `worst_case=$0.90` against a
`$1.00` daily ceiling correctly raised `BudgetExceededError` (`1 + 0.9 > 1.0`).

**Architecture validation**: PASS (0 violations).

**Known limitations carried forward**: neither component is wired into `RoutingGateway`/
`FallbackPolicy` yet — that happens at M15/M17. No per-priority-tier budget scaling (documented
above, not contract-mandated). `max_monthly_ai_cost` remains unused/unread by this
implementation — only `max_daily_ai_cost` is enforced, matching the ledger's daily-namespace
design; a monthly ceiling would need its own namespace scheme and wasn't required for this
delivery's scope.

**Working tree after this milestone**: the two new files above, plus the three modified files
listed; no other files touched beyond earlier milestones' changes. No commit made.

---

## M13 — RoutingCriteria, RoutingPolicy and RoutingPolicyRegistry

**Files created**: `integrations/llm_gateway/routing/criteria.py` (`RoutingObjective`,
`FallbackEligibility`, `RoutingCriteria`), `integrations/llm_gateway/routing/policy.py`
(`RoutingPolicy` Protocol, `BestQualityPolicy`, `LowestCostPolicy`, `FastestPolicy`,
`ReasoningPolicy`, `WeightedSplitPolicy`), `integrations/llm_gateway/routing/registry.py`
(`RoutingPolicyRegistry`), `tests/test_routing_criteria.py`, `tests/test_routing_policies.py`,
`tests/test_routing_policy_registry.py`.

**Files changed**: `integrations/llm_gateway/errors.py` — added
`RoutingPolicyRegistryAlreadySealedError` (the contract names `UnknownRoutingObjectiveError`
explicitly for `resolve()`'s failure but not `register()`-after-`seal()`'s; reusing
`UnknownRoutingObjectiveError` for that would have been semantically wrong — a "sealed
registry" bug is not an "unknown objective" bug — so a dedicated exception was added,
mirroring the `*RegistryAlreadySealedError` pattern every other registry in this delivery
already follows).

**Design notes on formulas the contract states narratively, not as exact algorithms**:
`LowestCostPolicy` ranks by standard-tier `input_price_per_million + output_price_per_million`
combined — the contract specifies no input/output weighting formula, so a simple sum is used,
documented inline. `FastestPolicy` implements §4.6's binding fallback rule precisely: candidates
with telemetry data always rank ahead of candidates without, and among the latter, higher
`quality_tier` ranks better — not an arbitrary tie-break. `ReasoningPolicy` ranks by
`reasoning_tier` (extended > standard > none) with `quality_tier` as an in-tier tiebreaker.
`WeightedSplitPolicy` draws one weighted-random primary pick from named candidates each call
(the one contract-named exception to determinism, §4.2) with every other candidate — weighted
and unweighted alike — following in `quality_tier` order as the fallback sequence.

**Tests added**: 34 total — 8 in `test_routing_criteria.py` (defaults, frozen/`extra=forbid`,
`FallbackEligibility` defaults, per-instance `fallback` construction); 15 in
`test_routing_policies.py` (each built-in policy's ranking behavior including `FastestPolicy`'s
known-vs-unknown-latency precedence and `ReasoningPolicy`'s tier ordering plus tiebreaker, and
`WeightedSplitPolicy`'s always-picks-a-weighted-candidate / eventually-covers-both-options-
across-200-trials / empty-weights-fallback / never-picks-unweighted-as-primary properties); 4
in `test_routing_policy_registry.py` (register/resolve round trip, unknown-objective raise,
sealed-registry raise, resolve identical before/after seal).

**pytest**: 388 passed, 0 failed, 0 skipped (full suite).

**ruff**: clean, after removing one unused import. **mypy**: clean.

**Runtime evidence**: `python -c "..."` ranking the real three-model `gpt-5.6-*` catalogue
under both `best_quality` and `lowest_cost` objectives via a real, sealed
`RoutingPolicyRegistry` — `best_quality` correctly produced `[sol, terra, luna]`
(quality_tier 100 > 70 > 40) and `lowest_cost` correctly produced the exact reverse
(`luna` cheapest, `sol` priciest), confirming both policies' logic against real pricing data,
not just synthetic fixtures.

**Architecture validation**: PASS (0 violations).

**Known limitations carried forward**: none of these are wired into `RoutingEngine` yet — that
happens at M14.

**Working tree after this milestone**: the six new files above; no other files touched beyond
earlier milestones' changes. No commit made.

---

## M14 — RoutingEngine

**Files created**: `integrations/llm_gateway/routing/engine.py` (`RoutingEngine`),
`tests/test_routing_engine.py`.

**Files changed**: none.

**Design notes**: `RoutingEngine` holds its own built-in-default `RoutingPolicy` instances
(one per `RoutingObjective`), independent of whatever is or isn't registered in
`RoutingPolicyRegistry` — this is what §4.4's exception-isolation rule requires ("fall back to
the built-in default policy for that objective"), and it also means an objective with nothing
registered at all still routes correctly rather than failing, which is a distinct case from "a
registered policy raised" and is not logged as a `routing_policy_failure` event (only genuine
runtime failures are). `candidates_considered` (the §16.2 event field) is implemented as the
total count of every registered model regardless of availability
(`ModelRegistry.all_models()`), distinct from `candidates_after_hard_filter` — the contract
names both fields but doesn't define "considered" precisely, so the broadest reasonable
reading was used. `chosen_rank` is emitted as `0` — `RoutingEngine` always recommends its own
top-ranked candidate; which one is actually dispatched is `FallbackPolicy`'s decision (M15),
a distinct, later concern.

**Tests added**: 9 — hard filter (missing capability flag excluded), provider-enabled filter
(model under an unregistered provider excluded), exclusion filter (caller-excluded provider
removed even though healthy/enabled), health filter (a health-store-marked-unhealthy
candidate excluded), zero-candidate raise, preference ranking under `best_quality`,
**cross-provider candidates from ≥2 distinct fake `provider_id`s both survive and rank
correctly together** (per your standing cross-provider-proof requirement), a policy that
always raises falls back to the built-in default and never propagates, and an objective with
nothing registered in `RoutingPolicyRegistry` silently uses the built-in default.

**pytest**: 397 passed, 0 failed, 0 skipped (full suite).

**ruff**: clean. **mypy**: clean, after one fix — a test's dummy provider adapter (structurally
untyped, matching earlier milestones' pattern) needed an `Any`-returning helper function rather
than being passed directly to `ProviderRegistry.register()`, which expects the `LLMGateway`
Protocol shape.

**Runtime evidence**: `python -c "..."` (via `asyncio.run`) building a real `RoutingEngine`
from the real OpenAI catalogue (M3), a real `ProviderRegistry` with `openai` registered, and
real Redis-backed `ProviderHealthStore`/`LatencyTracker` (empty `RoutingPolicyRegistry`,
falling back to the built-in default) — `route()` under `best_quality` correctly returned
`[gpt-5.6-sol, gpt-5.6-terra, gpt-5.6-luna]`, end to end against real infrastructure.

**Architecture validation**: PASS (0 violations).

**Known limitations carried forward**: not yet wired into `RoutingGateway` — that happens at
M17. `RoutingEngine` does not yet dispatch to a `ProviderAdapter` (by design — that's
`FallbackPolicy`'s exclusive job, landing at M15).

**Working tree after this milestone**: the two new files above; no other files touched beyond
earlier milestones' changes. No commit made.

---

## M15 — FallbackPolicy and same-candidate retry

**Files created**: `integrations/llm_gateway/fallback/policy.py` (`FailureClass`,
`FallbackPolicy`), `tests/test_fallback_policy.py`.

**Files changed**: `integrations/llm_gateway/models/registry.py` (added
`standard_combined_price()` — see design fix below), `integrations/llm_gateway/routing/policy.py`
(`LowestCostPolicy` now imports the shared helper instead of its own private duplicate),
`scripts/validate_architecture.py` + `tests/test_validate_architecture.py` (two rule
narrowings — see below).

**Real design flaw found and fixed during this milestone's own test run**: the first cut of
`_build_attempt_sequence` (§5.3 eligibility filtering) computed each candidate's "price" via
`CostEstimator.estimate()`. Since eligibility filtering runs *before* any cache lookup (§5.4
step 1), this meant `CostEstimator` was being invoked for every candidate on *every* call,
including ones that would ultimately be served from cache — directly violating P15 ("a cache
hit MUST be served without invoking CostEstimator or BudgetGuard"). Caught by
`test_cache_hit_skips_cost_estimate_and_budget_check_entirely` failing on the second (cached)
dispatch. Fixed by extracting `standard_combined_price()` (input+output "standard"-tier rate,
the same lightweight metric `LowestCostPolicy` already ranked by) into `models/registry.py` as
a shared, request-independent utility, and using it for eligibility filtering instead —
`CostEstimator` is now invoked only inside the dispatch loop, per-candidate, only on an actual
cache miss, exactly as §5.4 step 2 specifies.

**Two validator false positives found and fixed (mirroring M0's earlier fix pattern)**:
1. `fallback-policy-isolation` blanket-forbade the whole `capabilities` prefix, but the
   contract itself specifies `BudgetGuard.check()` raises `capabilities.errors.BudgetExceededError`,
   which `FallbackPolicy` MUST catch (§5.4 step 2) — narrowed to forbid only
   `capabilities.registry`/`capabilities.executor`/`capabilities.capability_mapping` (the actual
   Capability/CapabilityExecutor business logic), matching `budget_guard.py`'s identical,
   already-established M12 precedent.
2. `gateway-boundary-no-upward-knowledge` applied to the *entire* `integrations/llm_gateway/`
   tree, not just the composition root — meaning it would have blocked `fallback/policy.py`'s
   legitimate `capabilities.errors` import too. Narrowed to apply only to `gateway.py` itself
   (the actual "LLMGateway implementation boundary" the contract names), with the same
   `capabilities.errors` exemption. Two new validator tests added confirming the exemption and
   that `capabilities.registry` is still correctly flagged.

**Design notes**: `_attempt_candidate()` uses the three typed exceptions from M5
(`ProviderTransientError`/`ProviderPermanentIncompatibleError`/`ProviderModerationBlockedError`)
as the self-classifying signal for `FailureClass` — a `PERMANENT_INCOMPATIBLE`-flavored failure
(including moderation) is never retried (§6 rule 2), ending the attempt cycle on the first such
failure; only `TRANSIENT` failures retry, up to `max_same_candidate_retries`, with capped
exponential backoff and full jitter (base 250ms, cap 2s, §6 rule 2). Exhaustion reason
resolution: `"cost_ceiling_exhausted"` when eligibility filtering itself produced an empty
sequence; `"all_candidates_budget_denied"` when every candidate was denied by `BudgetGuard`
and nothing was ever dispatched; `"all_candidates_failed"` otherwise (covers pure-failure and
mixed failure/budget-denial cases) — a three-way partition matching the contract's three named
reasons, since it doesn't define a fourth for the mixed case.

**Tests added**: 10 in `test_fallback_policy.py` — **cross-provider fallback proven with 2
distinct fake `provider_id`s** (a `TRANSIENT` failure on one falls back to a healthy second,
marking the first unhealthy), `PERMANENT_INCOMPATIBLE` marks `runtime_unavailable` and is never
retried, a moderation block raises immediately with the second provider never even touched,
same-candidate retry count matches `max_same_candidate_retries` exactly, budget denial
continues to the next candidate without dispatching the denied one, **cache hit skips
`CostEstimator`/`BudgetGuard` entirely** (call counts proven unchanged across a second,
cache-served dispatch), the cost anchor is the cheapest candidate regardless of ranked order
(a deliberately-first-ranked expensive candidate is still excluded), exhaustion raises
`AllProvidersFailedError` with `"all_candidates_failed"`, exhaustion with
`"all_candidates_budget_denied"` when nothing is ever dispatched, and
`allow_cost_ceiling_override_on_exhaustion` successfully retries with widened bounds after the
default-bounded pass excludes everything. 2 more added to `test_validate_architecture.py` (the
two rule-narrowing fixes above).

**pytest**: 409 passed, 0 failed, 0 skipped (full suite).

**ruff**: clean, after removing one unused test import. **mypy**: clean.

**Runtime evidence**: `python -c "..."` (via `asyncio.run`) against **real Redis-backed**
`CacheCoordinator`/`RedisBudgetGuard`/`RedisProviderHealthStore` (not fakes) and real
`ModelDescriptor`s derived from the M3 catalogue, across two distinct fake `provider_id`s
(`openai` failing transiently, `openai-backup` succeeding) — `dispatch()` correctly fell back
to `gpt-5.6-terra` on the backup provider after the primary's transient failure, confirming the
whole mechanism against real infrastructure, not just in-memory fakes.

**Architecture validation**: PASS (0 violations).

**Known limitations carried forward**: not yet wired into `RoutingGateway`/`RoutingEngine` —
that's M17 (full pipeline). `dispatch()` only calls `adapter.generate()` — matching this
delivery's reduced scope.

**Working tree after this milestone**: the two new files above, plus the three modified files
listed; no other files touched beyond earlier milestones' changes. No commit made.

---

## M16 — Retry-multiplication boot check

**Files created**: `tests/test_retry_ceiling.py`.

**Files changed**: `integrations/llm_gateway/boot.py` — added `validate_retry_ceiling()` and
`DEFAULT_RETRY_MULTIPLICATION_CEILING = 30`.

**Design note**: pure arithmetic, no runtime cost, exactly as §6 rule 4 specifies:
`WorkflowRetryPolicy.max_attempts × max_fallback_attempts × (1 + max_same_candidate_retries)`,
raising `RetryCeilingExceededError` (not merely logging) if the product exceeds the ceiling.
Takes an optional `capability_name` for the error message, since §19 rule 3 calls for this to
run once per registered Capability at boot — a boot-time failure should be immediately
actionable (which capability's config is the problem), not just a bare number.

**Tests added**: 6 — under ceiling passes, exactly-at-ceiling passes (not `>`, so `==` is
allowed), over ceiling raises, a custom (lower) ceiling is honored, the error message includes
`capability_name` when given, and the error message names the computed product and ceiling.

**pytest**: 415 passed, 0 failed, 0 skipped (full suite).

**ruff**: clean. **mypy**: clean.

**Runtime evidence**: `python -c "..."` — `3 × 3 × (1+1) = 18` (under 30) didn't raise;
`5 × 5 × (1+2) = 75` (over 30) raised `RetryCeilingExceededError` naming `capability='research'`
and the full computed breakdown.

**Architecture validation**: PASS (0 violations).

**Known limitations carried forward**: not yet called anywhere in a real boot sequence — that's
M19 (`assemble_ai_integration_layer()`), where it needs to be invoked once per registered
Capability's effective configuration. No concrete Capability exists yet in this codebase, so
in practice this will have zero capabilities to check against until a future phase adds one —
the function itself is fully ready and tested regardless.

**Working tree after this milestone**: the one new file above, plus `boot.py`'s extension; no
other files touched beyond earlier milestones' changes. No commit made.

---

## M17 — Full `RoutingGateway.generate()` pipeline

**Session note**: implementation was completed in the prior session, but that session hit a
sustained platform-side tool-execution outage before the checkpoint could run (see
`docs/phase7_session_handoff.md`). This resuming session re-verified everything from scratch per
the hand-off's explicit instruction not to assume M17's code was correct — Docker/Postgres/Redis
were already up (confirmed healthy via `docker compose ps`), and the full six-step checkpoint was
run for the first time on these changes.

**Files created**: `tests/fakes/fake_infra.py` (shared permissive fakes —
`PermissiveProviderHealthStore`, `EmptyLatencyTracker`, `AllowingBudgetGuard`,
`InMemoryCacheStore`), `tests/test_routing_gateway_pipeline.py`.

**Files changed**: `integrations/llm_gateway/gateway.py` (rewritten — `RoutingGateway.__init__`
now takes `(routing_engine, fallback_policy)`; `generate()` builds `ObservabilityContext` and
`RoutingCriteria` from the incoming `GenerateRequest`, with `capability_name`/`priority`/
`excluded_providers` traveling via `request.metadata`), `integrations/llm_gateway/routing/engine.py`
(added `_promote_preferred()` — closes a real M14 gap: §4.1 rule 1's "preferred_model/
preferred_provider MUST remain advisory only" was never implemented; added `observability`
parameter threading), `integrations/llm_gateway/routing/policy.py` (`LowestCostPolicy` now
imports `standard_combined_price` from `models/registry.py`), `integrations/llm_gateway/fallback/policy.py`
(added `rate_limiter` parameter + per-candidate rate-limit check, `observability` parameter
threading, `fallback`/`retry` structured log events), `integrations/llm_gateway/rate_limit/limiter.py`
(added the `RateLimiter(Protocol)` — a gap from M9, where only the concrete `RedisRateLimiter`
existed), `tests/test_routing_gateway_golden_path.py` (setup code rewritten to construct a real
`RoutingEngine` + `FallbackPolicy` via `fake_infra.py` instead of the old M6 bypass constructor;
scenario/assertions unchanged — a strictly stronger regression test).

**Design decisions carried from the prior session (re-verified, not re-litigated)**:
1. **Rate-limiter placement**: §15.2's diagram lists a single pre-`RoutingEngine` RateLimiter
   step, but `RateLimitKey.provider_id` is required (§14), making a composite key structurally
   impossible before a candidate is resolved. Implemented per-candidate inside `FallbackPolicy`'s
   dispatch loop instead (same place cost/budget checks live); `RateLimitExceededError` is
   treated exactly like a budget denial. Documented at length in `fallback/policy.py`'s module
   docstring.
2. `RoutingGateway.generate()` does **not** call `CostTracker.record()` — Amendment C's scope is
   narrow (relocates only `BudgetGuard`'s call site); recording actual usage remains a future
   `Capability`'s post-hoc responsibility.
3. `ObservabilityContext` is now threaded through `RoutingEngine.route()` and
   `FallbackPolicy.dispatch()` (both gained an optional `observability` parameter) — closes a gap
   where §16.1's "MUST be threaded through every layer" rule wasn't fully honored after M14/M15.

**Real bug found and fixed during this session's checkpoint** (this session's own contribution,
not carried from the prior one): `test_routing_gateway_pipeline.py::test_full_pipeline_cross_provider_fallback_via_generate`
failed on first run — `failing.call_count == 2`, not the asserted `1`. Root cause: the test's
`_build_gateway` helper never exposed `FallbackPolicy`'s `max_same_candidate_retries` parameter,
so it silently used the production default of `1` (§6 rule 2 — up to 2 total tries per
candidate). Against a `transient_failure` fake adapter (which fails every call, never
eventually succeeds), this correctly means 2 calls before `FallbackPolicy` moves to the next
candidate — the production code was right; the test's assumption was wrong. Confirmed against
the already-verified M15 suite (`tests/test_fallback_policy.py::test_cross_provider_fallback_transient_failure_moves_to_next_candidate`),
which isolates this exact same scenario by explicitly passing `max_same_candidate_retries=0` —
the M17 test had simply never adopted that established pattern. Fixed by adding the
`max_same_candidate_retries` parameter to `_build_gateway` (default `1`, matching production) and
passing `0` explicitly in the one test whose intent is cross-provider fallback, not retry depth —
same fix-forward discipline as M8/M9/M15's own found-and-fixed bugs, not a weakened assertion.

**Tests added**: 9 in `test_routing_gateway_pipeline.py` — cross-provider fallback via
`generate()` itself, cache-hit skips cost/budget via `generate()`, budget-denial-continues-
fallback via `generate()`, rate-limit-denial-continues-fallback via `generate()`, exhaustion
raises `AllProvidersFailedError`, `capability_name`/`priority` travel via metadata to
`BudgetGuard`, `requires_tools` hard filter end-to-end, `excluded_providers` hard filter
end-to-end, `preferred_model` promotion end-to-end.

**pytest**: 431 passed, 0 failed, 0 skipped (full suite) — up from M16's 415 (16 new: 9 pipeline
+ others already present from the prior session's M17 work across `test_routing_engine.py`/
`test_fallback_policy.py`/`test_validate_architecture.py`).

**ruff**: clean (`integrations/llm_gateway/`, `services/`, `scripts/`, `tests/`). **mypy**: clean
on every Phase 7 path; 5 pre-existing errors remain in `services/source_registry.py`,
`services/collector.py`, `scripts/create_telegram_session.py` (missing `yaml`/`telethon` stubs,
one `SecretStr | None` union-attr) — all three predate Phase 7 (from the Phase 4.2 foundation
commit `8c3f8f2`), untouched by this phase's work, not a regression.

**Runtime evidence**: `python -c "..."` (via `asyncio.run`) building a real `RoutingGateway`
(`RoutingEngine` + `FallbackPolicy`) from scratch with two `FakeProviderAdapter`s
(`p-a`/`m-a` transient-failing, `p-b`/`m-b` succeeding) and in-memory fakes for cache/health/
latency/budget — `gateway.generate()` correctly routed to `m-a` first, retried it twice (default
`max_same_candidate_retries=1`), fell back to `m-b`, and returned its response
(`model_used == "m-b"`, `failing.call_count == 2`, `succeeding.call_count == 1`).

**Architecture validation**: PASS (0 violations).

**Known limitations carried forward** (unchanged from the prior session's hand-off, still
accurate): `LowestCostPolicy`/`FallbackPolicy` eligibility filtering ranks by
`standard_combined_price()` (input+output "standard"-tier price summed — the contract specifies
no exact weighting formula); `RoutingEngine`'s `chosen_rank` observability field is always `0`
(no feedback path from `FallbackPolicy` reporting which rank was actually dispatched); no
per-priority-tier budget ceiling scaling and no monthly ceiling enforcement (only
`max_daily_ai_cost` is read); `CostEstimator.estimate()`'s `expected` field is computed
identically to `worst_case`; the per-candidate rate-limiter placement (decision 1 above) is a
reasoned deviation from §15.2's literal diagram ordering.

**Working tree after this milestone**: same file set as the prior session's hand-off (§1 of
`docs/phase7_session_handoff.md`) plus the one-line test fix in `test_routing_gateway_pipeline.py`
described above; no other files touched. No commit made.

---

## M18 — Real OpenAI ProviderAdapter, `generate()` only

**Session note**: this milestone starts from the M17 checkpoint commit
(`9bc0f0338b9972e0a3884462ac3d45e0baf1b146`), created and approved in a separate step after M17.

### Official-source verification (performed before any code was written)

- **Model catalogue re-check**: `models/catalog.py`'s three GPT-5.6 entries were independently
  re-verified against `developers.openai.com/api/docs/models/gpt-5.6-{sol,terra,luna}` (live
  fetch, not training-data memory — this milestone's session postdates the assistant's training
  cutoff and the family itself, so nothing about it could be answered from memory). Every field
  matched exactly: `model_id`, `context_window_tokens=1_050_000`, `max_output_tokens=128_000`,
  and standard-tier pricing (Sol $5.00/$30.00, Terra $2.50/$15.00, Luna $1.00/$6.00 per million
  input/output tokens). **No catalogue change was needed or made** — zero discrepancies found.
- **SDK and API surface**: the official `openai` PyPI package (installed: 2.45.0, satisfying the
  `openai>=2.40` constraint added to `pyproject.toml`). Verified against the live
  `github.com/openai/openai-python` (main branch) source, not documentation summaries alone:
  `AsyncOpenAI`, `client.responses.create(...)` (OpenAI's Responses API — confirmed as the
  currently-recommended surface for new integrations per
  `developers.openai.com/api/docs/guides/migrate-to-responses`, over the older Chat Completions
  API), the full typed exception hierarchy (`openai/_exceptions.py`), and the exact response
  field shapes (`Response`, `ResponseUsage`, `ResponseOutputMessage`, `ResponseFunctionToolCall`,
  `IncompleteDetails`, `ResponseError`) used for translation.

### Architectural gap found and fixed (not OpenAI-specific)

`FallbackPolicy._attempt_candidate()` called `adapter.generate(request)` with the plain,
unmodified request — never telling the adapter which `(provider_id, model_id)` routing/fallback
had actually resolved for that attempt. Invisible with `FakeProviderAdapter` (each fake test
instance is hard-wired to exactly one model), but a real, multi-model provider adapter serving
three models under one `provider_id` (this milestone's `OpenAIAdapter`, `gpt-5.6-{sol,terra,
luna}` all under `provider_id="openai"`) has no other way to know which model to call. Fixed by
having `FallbackPolicy` inject `resolved_provider_id`/`resolved_model_id` into
`request.metadata` immediately before each dispatch attempt (`fallback/policy.py`) — the same
"extend via metadata, never the frozen schema" pattern M17 already established for
`request_id`/`capability_name`/`priority`/`excluded_providers`/`cache_policy`. Confirmed
cache-key-neutral: `CacheKeyComponents.normalized_request_hash` (§13.2) already excludes
`metadata` entirely, so the addition cannot perturb cache correctness — verified by the full
463-test suite staying green, not merely asserted. No schema changed; no Phase 1–6 or Phase 7
Protocol signature changed. Documented at length in both `fallback/policy.py`'s module docstring
and `openai_adapter.py`'s own docstring.

**Files created**: `integrations/llm_gateway/providers/openai_adapter.py` (`OpenAIAdapter`,
`build_openai_provider_factory()`), `tests/test_openai_adapter.py`,
`scripts/smoke_test_openai_adapter.py`.

**Files changed**: `integrations/llm_gateway/fallback/policy.py` (the gap fix above — 29 lines,
`_attempt_candidate()` plus its module docstring), `pyproject.toml` (added `"openai>=2.40"` to
`dependencies`).

**Design notes**:
- `generate()` only; `generate_stream()`/`embed()`/`classify()`/`moderate()`/`rerank()` all raise
  `UnsupportedGatewayCapabilityError`, matching `FakeProviderAdapter`'s established pattern for
  the same five deferred methods exactly.
- One persistent `AsyncOpenAI` client per adapter instance, constructed once in `__init__`
  (optionally injectable for tests), reused across every `generate()` call.
- Request translation: `GenerateRequest.messages` → Responses API `input` items (`input_text`/
  `input_image` content parts); `tools`/`tool_choice` → `FunctionToolParam`-shaped entries;
  `response_mode="json_schema"` → `text.format={"type":"json_schema",...}`. `role="tool"`
  messages explicitly raise a typed error rather than being silently mistranslated — the
  Responses API has no "tool" input role (only user/assistant/system/developer), and correctly
  translating a tool result requires the `capability_execution_id`/`call_id` bookkeeping that
  lives in `Capability.execute()`'s tool loop (§9.3), which has no concrete implementation yet
  in this codebase.
- Response translation: `response.output_text` → `text`; `response.output[].type ==
  "function_call"` items → `tool_calls`; `response.incomplete_details.reason` (`"max_output_
  tokens"`/`"content_filter"`) → `finish_reason` (`"length"`/`"content_filter"`), matching the
  Responses API's own literal values exactly; otherwise `"tool_calls"` or `"stop"`.
  `response.usage.{input,output}_tokens` → `CapabilityUsage`.
- Exception translation: every `openai.OpenAIError` subtype maps to exactly one of
  `ProviderTransientError` (`RateLimitError`, `AuthenticationError` — §5.2's own wording, "auth
  (this attempt only)", is TRANSIENT — `InternalServerError`, `ConflictError`,
  `APIConnectionError`/`APITimeoutError`), `ProviderPermanentIncompatibleError`
  (`PermissionDeniedError`, `NotFoundError`, `UnprocessableEntityError`, and `BadRequestError`
  for a non-moderation code), or `ProviderModerationBlockedError` (`BadRequestError` with a code
  in `{invalid_prompt, bio_policy, image_content_policy_violation, content_policy_violation}` —
  the moderation-shaped codes found in `ResponseError.code`'s live type definition). `asyncio.
  CancelledError` is a `BaseException`, never caught by the `except openai.OpenAIError` clause,
  and propagates unchanged.
- Credential redaction: only `.message`/`.code`/`.status_code`/the exception's own type name are
  ever read from a caught exception — never `.request`/`.response` (the `httpx` objects that
  carry the `Authorization` header). The assembled message is passed through a `_redact()` helper
  that replaces the adapter's own literal API-key value plus generic `Bearer <token>`/`sk-...`
  patterns with `[REDACTED]`, before ever being attached to a raised exception.
- `build_openai_provider_factory()` returns a ready `ProviderFactory` for M19's
  `assemble_ai_integration_layer()` to consume — not wired into any real boot sequence yet.

**Tests added**: 32 in `tests/test_openai_adapter.py` — successful text generation, request
translation (message/tool/tool_choice/max_tokens/temperature → payload), response translation
(text, tool_calls + `finish_reason="tool_calls"`, `length`, `content_filter`), usage mapping,
model mapping (resolved_model_id takes precedence over preferred_model; falls back to
preferred_model when metadata absent; raises when neither is present), metadata-driven dispatch
target, persistent-client reuse (same instance across 2 calls; exactly one `AsyncOpenAI(...)`
construction when no client is injected), all 5 deferred methods raise
`UnsupportedGatewayCapabilityError`, 9 exception-translation cases (rate limit, 5xx, auth,
connection, timeout, permission-denied, not-found, bad-request, moderation-coded bad-request),
one explicit "no raw `OpenAIError` crosses the boundary" assertion, 2 credential-redaction cases
(exact-key-value match and generic Bearer-pattern match), `asyncio.CancelledError` propagation,
a schema-snapshot test asserting `GenerateRequest`/`GenerateResponse`/`RoutingCriteria`/
`ModelDescriptor` carry no OpenAI-specific field, a Protocol-shape structural check, and a
provider-factory construction test. All fake OpenAI responses are built from the real, installed
`openai` SDK's own Pydantic types (`Response.model_construct(...)`, `ResponseUsage`, etc.) — an
"official SDK-compatible fake," not an invented shape.

**Bug found and fixed during this milestone's own test run**: the first cut of the test helper
`_mock_client()` branched on `isinstance(response, Exception)` to decide whether to configure
`side_effect` vs. `return_value` on the mock. `asyncio.CancelledError` is a `BaseException`
subclass, not an `Exception` subclass (since Python 3.8) — so the helper silently treated it as
a *return value* instead of a raised side effect, and `test_cancelled_error_propagates_unchanged`
failed with `AttributeError: 'CancelledError' object has no attribute 'output'` deep inside
response translation, not with the expected `CancelledError` propagating. Fixed by checking
`isinstance(response, BaseException)` instead — a test-fixture bug, not an adapter bug (the
adapter's own `except openai.OpenAIError` clause was already correct and untouched).

**pytest**: 463 passed, 0 failed, 0 skipped (full suite; 431 from the M17 checkpoint + 32 new).
No real network call anywhere in the suite — every OpenAI-facing test uses an injected mock
`AsyncOpenAI`-shaped client.

**ruff**: clean (`integrations/llm_gateway/providers`, `tests`, `scripts`) after removing one
unused import (`ResponseError`, imported in the test file but never directly referenced — its
error-code values are used as string literals instead). **mypy**: clean on
`integrations/llm_gateway/providers` (3 source files).

**Runtime evidence**: `python -c "..."` (via `asyncio.run`) constructing a real `OpenAIAdapter`
with an injected mock `AsyncOpenAI` client (`responses.create` returning a real
`openai.types.responses.Response` instance built via `model_construct`) and calling `generate()`
end to end — correctly returned `model_used="gpt-5.6-terra"`, `usage.input_tokens=42`,
`usage.output_tokens=7`, `finish_reason="stop"`, with `client.responses.create.await_count == 1`
confirming exactly one (mocked, no-network) call was made.

**Architecture validation**: PASS (0 violations) — confirms `openai` is imported nowhere outside
`integrations/llm_gateway/providers/openai_adapter.py` in production source (the
`provider-sdk-confinement` rule scans `scripts/` too; `smoke_test_openai_adapter.py` imports only
the adapter/settings modules, never `openai` directly). `tests/` is validator-exempt by design
(rules apply to production source, not test doubles) — this is why
`tests/test_openai_adapter.py` may import real `openai` SDK types to build its fakes.

**Known limitations / explicitly deferred (this milestone's own scope, not a new gap)**:
- `generate_stream()`/`embed()`/`classify()`/`moderate()`/`rerank()` all raise
  `UnsupportedGatewayCapabilityError` — separately approved future milestones, per instruction.
- `role="tool"` message translation (mid-tool-loop) is not implemented — raises a clear typed
  error instead of mistranslating; no concrete `Capability` drives a tool loop yet.
- `build_openai_provider_factory()` is not wired into any real boot sequence — that's M19's
  `assemble_ai_integration_layer()`.
- The live smoke script (`scripts/smoke_test_openai_adapter.py`) was verified to skip cleanly
  with no `OPENAI_API_KEY` configured (confirmed: no `.env` key present in this environment,
  exit code 0, no network call, no key printed) but was **not** run against a real key — that
  requires the user's separate, explicit, in-the-moment approval per instruction.

**Working tree after this milestone**: the 3 new files above, plus the 2 modified files
(`fallback/policy.py`, `pyproject.toml`) — 5 files total. No other files touched. No commit made.

---

## M19 — Fixed boot sequence + `CapabilityRegistry` wiring

**Session note**: this milestone starts from the M18 checkpoint commit
(`e8d642e62b1f471525e81a79227019d8056e8f5f`), approved and continued autonomously per instruction
("continue implementing the documented Phase 7 milestones autonomously, beginning with M19").

**Canonical scope source**: `docs/phase7_session_handoff.md` §5 item 3 — "Fixed boot sequence +
`CapabilityRegistry` wiring. `integrations/llm_gateway/boot.py`'s `assemble_ai_integration_layer
(settings)` (the fixed order: seal registries → consistency check → construct every component →
assemble `RoutingGateway`); `capabilities/registry.py`'s `build_registry()` gains the
injected-dependency signature per §19 rule 2 (still ships empty-sealed — no concrete
`Capability` exists yet)." Cross-checked against `docs/phase7_architecture_contract.md` §19
rule 3's full fixed-order text (the hand-off's own summary stops at "assemble RoutingGateway";
the contract's own text continues through "`build_registry()` called → `CapabilityRegistry`
sealed → process ready to serve" — the contract, as the designated single source of truth, is
followed in full, treating the hand-off's summary as abbreviated, not a deliberate narrowing).

**Files created**: `integrations/llm_gateway/tools/__init__.py`,
`integrations/llm_gateway/tools/registry.py` (`ToolExecutionRequest`, `ToolExecutionResult`,
`ToolExecutor`, `ToolRegistry`), `tests/test_tool_registry.py`, `tests/test_boot_assembly.py`.

**Files changed**: `integrations/llm_gateway/boot.py` (`assemble_ai_integration_layer()`,
`AIIntegrationLayer`), `capabilities/registry.py` (`build_registry()`'s new signature),
`integrations/llm_gateway/errors.py` (4 new exceptions), `integrations/llm_gateway/gateway.py`
(gap fix, see below), `tests/test_capability_registry.py` (updated for the new
`build_registry()` signature), `tests/test_routing_gateway_pipeline.py` (5 new tests for the
gateway.py gap fix).

### Scope decisions made during this milestone (documented, not asked, per instruction to
### proceed without routine approval)

1. **`ToolRegistry` (§9.1, §9.2) implemented now, minimally.** `capabilities.registry.
   build_registry()`'s contract-mandated signature (§19 rule 2) requires a
   `tool_registry: ToolRegistry` parameter, and `ToolRegistry` is a concrete class (not a
   Protocol) per §9.2 - it did not exist anywhere in this codebase before this milestone (tool-
   calling machinery was explicitly deferred at M17). Implemented exactly and only what §9.1/
   §9.2 specify verbatim: `ToolExecutionRequest`, `ToolExecutionResult`, `ToolExecutor`
   (Protocol), `ToolRegistry` (register/seal/resolve, sealed-after-boot, explicit-registration-
   only - identical discipline to ProviderRegistry/ModelRegistry/RoutingPolicyRegistry, P18).
   Zero tool-loop logic, zero `MAX_TOOL_ROUNDS`, zero Capability-side machinery (§9.3/§9.4/§9.5
   remain fully deferred, unchanged) - `assemble_ai_integration_layer()` constructs and seals an
   *empty* `ToolRegistry`, exactly mirroring `build_registry()`'s own "ships empty-sealed" state.
2. **`prompt_repository: PromptRepository` is an injected parameter, not internally
   constructed.** No concrete `PromptRepository` implementation exists anywhere in this codebase
   (`integrations/prompts/protocol.py`'s own docstring: "prompt lifecycle lives in a separate,
   not-yet-built Prompt Publisher" - explicitly out of Phase 7's scope). `assemble_ai_
   integration_layer(settings, prompt_repository, *, redis_client=None)` accepts it as a required
   parameter instead, matching the dependency-injection discipline every other component in this
   file already follows.
3. **A real, documented inconsistency in the frozen contract, not resolved, correctly deferred.**
   §19 rule 2's `build_registry(gateway, prompt_repository, budget_guard, tool_registry)`
   signature includes `budget_guard: BudgetGuard` - but Amendment C (§25, appended after §19)
   explicitly forbids `Capability` from ever holding or calling `BudgetGuard`. §26's append-only
   discipline means Amendment C never edited §19 rule 2's text in place, so this reads as a
   holdover from a pre-Amendment-C draft. Not a blocker for this milestone: `build_registry()`
   still ships an empty, sealed registry (no concrete `Capability` exists to inject anything
   into), so nothing today actually threads `budget_guard` into a `Capability` constructor. The
   parameter is accepted and type-checked, matching the contract's literal signature exactly;
   whether a future concrete `Capability` genuinely receives it (almost certainly it must not,
   per Amendment C) is left for whichever future milestone builds the first real `Capability` -
   documented here rather than silently decided either way.
4. **`CapabilityNegotiator.verify()` (§17.3) fails loud instead of silently no-op'ing.**
   `settings.verify_capabilities_at_boot` defaults `False` and is honored silently in that case;
   if set `True`, `assemble_ai_integration_layer()` raises `CapabilityNegotiatorNotImplemented
   Error` rather than doing nothing, since `CapabilityNegotiator` itself has no implementation
   anywhere yet (deferred past this delivery). Matches this codebase's established "fail loud on
   an unhonorable boot configuration" discipline (`RegistryConsistencyError`,
   `MissingRedisFailurePolicyError`, `UnknownProviderError`).
5. **Retry-multiplication-ceiling boot enforcement (§6 rule 4) deliberately NOT wired in.**
   Correctly validating it needs each registered Capability's Workflow-level
   `WorkflowRetryPolicy.max_attempts` cross-referenced against Gateway-level fallback config -
   two separate registries (`workflows.registry` + `capabilities.registry`) that
   `CapabilityRegistry` exposes no public iteration API over. With zero concrete Capabilities
   registered in this delivery there is nothing to validate against regardless - exactly what
   M16's own log entry already predicted ("in practice this will have zero capabilities to check
   against until a future phase adds one"), still true after M19.
6. **`CostTracker` constructed and returned in `AIIntegrationLayer`, not discarded.** Per §19
   rule 3's "every §18 component constructed," `RedisCostTracker` is built during boot even
   though nothing calls it yet (`RoutingGateway.generate()` deliberately never calls
   `CostTracker.record()`, confirmed at M17) - returned in the bundle rather than constructed
   and immediately discarded, so a future caller assembling a real Capability has it ready.

### Real gap found and fixed (blocking, not cosmetic)

`RoutingGateway` (M17) never implemented `generate_stream`/`embed`/`classify`/`moderate`/
`rerank` - only `generate()` existed. The M17 hand-off's own decision log said the other five
Protocol methods should raise `UnsupportedGatewayCapabilityError`, matching
`FakeProviderAdapter`'s and (from M18) `OpenAIAdapter`'s already-established pattern - this was
simply never added to `gateway.py` itself. Invisible until this milestone because nothing
before required a `RoutingGateway` instance to structurally satisfy `LLMGateway` end to end;
`capabilities.registry.build_registry(gateway: LLMGateway, ...)` (§19 rule 2) does, and mypy
correctly rejected `assemble_ai_integration_layer()`'s `build_registry(gateway, ...)` call
(`Argument 1 to "build_registry" has incompatible type "RoutingGateway"; expected "LLMGateway"`)
until this was fixed. Fixed by adding the same five stub methods, unchanged in shape from every
other `LLMGateway` implementation already in this codebase. 5 new tests added in
`tests/test_routing_gateway_pipeline.py` proving each raises `UnsupportedGatewayCapabilityError`
against a real, fully-constructed `RoutingGateway`.

**Tests added**: 9 in `test_tool_registry.py` (register/resolve, idempotent flag stored
per-registration, duplicate registration raises, unknown name raises, registration-after-seal
raises, resolution-after-seal still works, empty-sealed registry resolves nothing,
`ToolExecutionRequest`/`ToolExecutionResult` shape); 5 in `test_boot_assembly.py` (successful
assembly produces a working `RoutingGateway` + empty-sealed `CapabilityRegistry` +
`RedisCostTracker`, `verify_capabilities_at_boot=True` fails loud,
missing `redis_unavailable_policy` fails loud at construction, a model registered under a
disabled provider fails `RegistryConsistencyError`, the injected `redis_client` is actually used
rather than the cached singleton); 5 in `test_routing_gateway_pipeline.py` (the gateway.py gap
fix, one per deferred method); `test_capability_registry.py` updated in place (6 existing tests
now route through `build_registry()`'s new signature via a local `_build_registry()` helper
instead of the removed module-level singleton - same assertions, same coverage).

**Bug found and fixed during this milestone's own test run**: none beyond the two documented
above (the `ToolRegistry`-shape and `RoutingGateway`-Protocol-conformance gaps) - both caught by
mypy/the test suite before commit, not discovered post-hoc.

**pytest**: 482 passed, 0 failed, 0 skipped (full suite; 463 from the M18 checkpoint + 9 tool
registry + 5 boot assembly + 5 gateway deferred-method tests). No real network call anywhere -
the boot-assembly tests construct a real `OpenAIAdapter` (via `enabled_providers=["openai"]` +
a fake, clearly-non-functional key, needed only so `build_provider_registry()`/`validate_
registry_consistency()` have something real to wire and validate) but never call `generate()`
on it - `AsyncOpenAI` client construction is pure client-side setup, no request is ever made.

**ruff**: clean (`integrations/llm_gateway`, `capabilities`, `tests`, `scripts`). **mypy**:
clean on the full changed scope (`boot.py`, `tools/`, `capabilities/registry.py`, `gateway.py` -
5 source files) and on a broader sweep (`integrations/llm_gateway services scripts capabilities`,
55 source files) - the same 5 pre-existing, unrelated findings from the Phase 4.2 foundation
commit (`source_registry.py`, `collector.py`, `create_telegram_session.py`) remain, confirmed
not a regression (identical to the M17/M18 checkpoints).

**Runtime evidence**: `tests/test_boot_assembly.py`'s own integration tests, run against real
local Redis (docker-compose), constitute the runtime evidence for this milestone - assembling
every §18 component for real (Redis-backed `RateLimiter`/`ProviderHealthStore`/`LatencyTracker`/
`BudgetGuard`/`CostTracker`, a real `ModelRegistry`/`ProviderRegistry` with the real OpenAI
catalogue and a real `OpenAIAdapter`, a real sealed `RoutingPolicyRegistry` with all four
built-in policies registered, a real `RoutingEngine`/`FallbackPolicy`/`RoutingGateway`) and
confirming the resulting `RoutingGateway` structurally satisfies `LLMGateway` and the
`CapabilityRegistry` resolves and seals correctly.

**Architecture validation**: PASS (0 violations) - confirms `boot.py` importing
`build_openai_provider_factory` (a plain function, not the `openai` SDK itself) from
`openai_adapter.py` does not trip the `provider-sdk-confinement` rule, and that
`capabilities/registry.py`'s new imports (`LLMGateway`, `PromptRepository`, `BudgetGuard`,
`ToolRegistry`) don't match the `capability-isolation` rule's forbidden prefixes (provider SDKs,
`database.session`, `sqlalchemy`).

**Alembic**: no migrations created or touched.

**Known limitations / explicitly deferred (this milestone's own scope, not new gaps)**:
- Retry-multiplication-ceiling boot enforcement remains unwired (see decision 5 above).
- `budget_guard`'s presence in `build_registry()`'s signature vs. Amendment C's Capability-side
  prohibition is documented, not resolved (see decision 3 above) - a future milestone building
  the first real Capability must address it, almost certainly by never threading `budget_guard`
  through to that Capability's own constructor.
- `PromptRepository` still has no concrete implementation anywhere (Prompt Publisher remains
  entirely unbuilt, outside Phase 7's scope) - `assemble_ai_integration_layer()` can only be
  called today with a caller-supplied fake/stub, exactly as its own tests do.
- `CapabilityNegotiator` (§17.3) remains unimplemented; `verify_capabilities_at_boot` must stay
  `False` until a future milestone builds it.
- `tool_registry`'s tool-use loop (§9.3), `MAX_TOOL_ROUNDS` (§9.4), and per-round timeout split
  (§9.5) remain entirely unbuilt - `ToolRegistry` itself is the only piece this milestone added.

**Working tree after this milestone**: 4 new files (`tools/__init__.py`, `tools/registry.py`,
`test_tool_registry.py`, `test_boot_assembly.py`) + 6 modified files (`boot.py`,
`capabilities/registry.py`, `errors.py`, `gateway.py`, `test_capability_registry.py`,
`test_routing_gateway_pipeline.py`) — 10 files total. No other files touched. No commit made
until the checkpoint below passes.
