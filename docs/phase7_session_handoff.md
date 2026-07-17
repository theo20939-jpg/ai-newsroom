# Phase 7 Session Hand-off Report

**Purpose**: allow a brand-new Claude Code session, with no memory of the prior conversation,
to resume Phase 7 (AI Integration Layer) implementation from exactly where it stopped. This
document is self-contained — read it, read the two files it points to
(`docs/phase7_architecture_contract.md` and `docs/phase7_implementation_log.md`), and you have
everything needed to continue.

**Why this document exists**: the implementing session hit a sustained platform-side outage in
the Bash/PowerShell tool-execution safety classifier (every command, including trivial ones
like `echo` and `python --version`, began failing with "temporarily unavailable... cannot
determine the safety of Bash/PowerShell right now"). M17's code changes were completed and
manually reviewed by inspection, but the mandatory verification checkpoint (pytest/ruff/mypy/
runtime validation/architecture validation/git status) could not be run before the session
needed to hand off. **No commits were made at any point in this session** — the working tree
is dirty by design, awaiting your explicit approval to commit.

---

## 1. Current repository state

**Caveat on this section**: `git status`/`git log` could not be re-run live due to the tool
outage described above. The values below are the last confirmed state observed during the
session (after milestone M16's checkpoint fully passed) plus the specific files edited during
the in-progress M17 milestone, tracked file-by-file as each edit was made. **Before doing
anything else, run `git status --short` and `git log -1` yourself to get the authoritative
current state** — this section should match, but verify rather than trust blindly.

- **Current branch**: `master`
- **Main branch** (for PRs): `main`
- **Latest commit hash**: `787afee` ("Implement Phase 6 capability framework contracts") — the
  session made zero commits, so HEAD should be unchanged from the session's start. Run
  `git rev-parse HEAD` to get the full hash and confirm.
- **Working tree status**: dirty (extensive uncommitted work — this is expected and intentional;
  do not discard it)

### Files modified (tracked files with uncommitted changes)

- `.env.example`
- `core/config.py`
- `services/budget_guard.py`
- `services/cost_tracker.py`
- `tests/conftest.py`
- `tests/test_budget_guard_protocol.py`

### Files created but uncommitted (untracked)

Documentation:
- `docs/phase7_ai_integration_layer_planning.md`
- `docs/phase7_ai_integration_layer_planning_v2.md`
- `docs/phase7_architecture_contract.md` (the frozen contract — single source of truth)
- `docs/phase7_architecture_review.md`
- `docs/phase7_consistency_review.md`
- `docs/phase7_principal_architect_review.md`
- `docs/phase7_implementation_log.md` (**read this in full** — detailed per-milestone log,
  M0–M16, with design notes, findings, and verification evidence)
- `docs/phase7_session_handoff.md` (this file)

Production code (`integrations/llm_gateway/` is entirely new this phase):
- `scripts/validate_architecture.py`
- `integrations/llm_gateway/errors.py`
- `integrations/llm_gateway/observability.py`
- `integrations/llm_gateway/gateway.py`
- `integrations/llm_gateway/boot.py`
- `integrations/llm_gateway/models/` (`__init__.py`, `registry.py`, `catalog.py`)
- `integrations/llm_gateway/providers/` (`__init__.py`, `base.py`)
- `integrations/llm_gateway/cache/` (`__init__.py`, `store.py`, `coordinator.py`)
- `integrations/llm_gateway/rate_limit/` (`__init__.py`, `limiter.py`)
- `integrations/llm_gateway/routing/` (`__init__.py`, `criteria.py`, `policy.py`, `registry.py`,
  `engine.py`, `latency_tracker.py`)
- `integrations/llm_gateway/fallback/` (`__init__.py`, `health_store.py`, `policy.py`)
- `services/cost_estimator.py`
- `services/pricing_catalog.py`

Tests:
- `tests/contract/` (`__init__.py`, `test_provider_adapter_contract.py`)
- `tests/fakes/fake_provider_adapter.py`
- `tests/fakes/fake_infra.py` (added during M17 — shared permissive fakes for pipeline tests)
- `tests/test_validate_architecture.py`
- `tests/test_settings_phase7.py`
- `tests/test_llm_gateway_errors.py`
- `tests/test_observability_context.py`
- `tests/test_model_registry.py`
- `tests/test_model_catalog.py`
- `tests/test_provider_registry.py`
- `tests/test_registry_consistency.py`
- `tests/test_pricing_catalog.py`
- `tests/test_cost_estimator.py`
- `tests/test_cache_store.py`
- `tests/test_cache_coordinator.py`
- `tests/test_rate_limiter.py`
- `tests/test_provider_health_store.py`
- `tests/test_latency_tracker.py`
- `tests/test_cost_tracker_real.py`
- `tests/test_budget_guard_real.py`
- `tests/test_routing_criteria.py`
- `tests/test_routing_policies.py`
- `tests/test_routing_policy_registry.py`
- `tests/test_routing_engine.py`
- `tests/test_fallback_policy.py`
- `tests/test_retry_ceiling.py`
- `tests/test_routing_gateway_golden_path.py` (rewritten during M17 — see §3)
- `tests/test_routing_gateway_pipeline.py` (new during M17 — see §3)

### Files edited during the in-progress M17 milestone specifically (not yet verified)

These already appear in the untracked list above (their containing directories are new), but
are called out here because they were touched *during M17*, after M16's last full green
checkpoint, and have **not** been re-verified:

- `integrations/llm_gateway/routing/engine.py` — added `preferred_model`/`preferred_provider`
  promotion (`_promote_preferred`), added `observability` parameter threading + log fields
- `integrations/llm_gateway/routing/policy.py` — `LowestCostPolicy` now imports
  `standard_combined_price` from `models/registry.py` instead of a private duplicate
- `integrations/llm_gateway/models/registry.py` — added `standard_combined_price()` function
- `integrations/llm_gateway/fallback/policy.py` — added `rate_limiter` parameter + per-candidate
  rate-limit check, added `observability` parameter threading, added `fallback`/`retry` log
  events
- `integrations/llm_gateway/rate_limit/limiter.py` — added the `RateLimiter(Protocol)` class
  (previously only the concrete `RedisRateLimiter` existed — a gap from M9)
- `integrations/llm_gateway/gateway.py` — rewritten for the full pipeline (see §3)
- `scripts/validate_architecture.py` — two rule narrowings (see M15 in `phase7_implementation_log.md`
  and §3 below)
- `tests/test_validate_architecture.py`, `tests/test_routing_engine.py`,
  `tests/test_fallback_policy.py` — new tests added for the above

---

## 2. Completed work

Full detail for every milestone below is in `docs/phase7_implementation_log.md` — this is a
condensed index. **Read that file for design rationale, exact findings, and verification
evidence per milestone.**

Baseline: a clean 195-passed/0-failed/0-skipped baseline was established before M0, after
confirming Docker Desktop, Postgres, and Redis were running (`docker compose up -d postgres redis`).

| # | Milestone | Purpose |
|---|---|---|
| M0 | Architecture boundary validator | `scripts/validate_architecture.py` — AST-based forbidden-import checker encoding Phase 6 §1 + Phase 7 §1's forbidden-edge tables. No third-party dependency. |
| M1 | Settings, credentials, Gateway errors | `core/config.py` additions (`enabled_providers`, `verify_capabilities_at_boot`, `redis_unavailable_policy`); `ProviderCredential` + `build_openai_credential()`; full `integrations/llm_gateway/errors.py` exception hierarchy. |
| M2 | ObservabilityContext | `integrations/llm_gateway/observability.py` — the id-hierarchy value object + derivation helpers (§16.1). |
| M3 | ModelRegistry + OpenAI catalogue | `models/registry.py` (with `model_validator` enforcing §3 rules 3/4/9), `models/catalog.py` seeded with the **real, live-verified GPT-5.6 family** (see §4). |
| M4 | ProviderRegistry + registry-consistency validation | `providers/base.py`'s `ProviderRegistry`/`ProviderFactory`/`build_provider_registry()`; `boot.py`'s `validate_registry_consistency()`. |
| M5 | FakeProviderAdapter framework | `tests/fakes/fake_provider_adapter.py` (configurable success/transient/permanent/moderation behaviors); `tests/contract/test_provider_adapter_contract.py`; added `ProviderTransientError`/`ProviderPermanentIncompatibleError`/`ProviderModerationBlockedError` to `errors.py`. |
| M6 | Golden Path `RoutingGateway.generate()` | First cut of `gateway.py` — one provider, one model, no fallback/cache/cost/budget, deterministic, explicit `ObservabilityContext` construction. Later extended at M17 (not replaced). |
| M7 | PricingCatalog + CostEstimator | `services/pricing_catalog.py`, `services/cost_estimator.py` (`CostEstimate` value object). |
| M8 | CacheStore + CacheCoordinator | `cache/store.py` (Redis-backed, base64 str/bytes shim), `cache/coordinator.py` (`CacheKeyComponents`, TTLs, never-cacheable rules, fail-open). Added shared `redis_client` fixture to `tests/conftest.py`. |
| M9 | RateLimiter | `rate_limit/limiter.py` — Redis Lua-script token bucket, atomic composite-key acquire, §28 Q1 boot enforcement. **Gap found at M17**: the `RateLimiter(Protocol)` type itself was missing (only the concrete class existed) — fixed during M17. |
| M10 | ProviderHealthStore | `fallback/health_store.py` — TTL `unhealthy` vs. permanent `runtime_unavailable`, fail-open. |
| M11 | LatencyTracker | `routing/latency_tracker.py` — `RoutingTelemetrySnapshot`, Redis LIST-backed rolling p50. |
| M12 | Real CostTracker + BudgetGuard | Added `RedisCostTracker`/`RedisBudgetGuard`. **Signature change (approved)**: `BudgetGuard.check()` changed from Phase 6's `check(request: BudgetCheckRequest{estimated_usage})` to Amendment C's `check(capability_name, priority, worst_case: Decimal)` — confirmed with user, no production call site existed, one Phase 6 test updated. |
| M13 | RoutingCriteria/RoutingPolicy/RoutingPolicyRegistry | `routing/criteria.py`, `routing/policy.py` (5 built-in policies), `routing/registry.py`. |
| M14 | RoutingEngine | `routing/engine.py` — the §4.3 six-step filter-and-rank sequence + §4.4 exception isolation. |
| M15 | FallbackPolicy + same-candidate retry | `fallback/policy.py` — §5/§6 in full. **Design bug found and fixed during this milestone's own tests**: eligibility filtering was invoking `CostEstimator` for every candidate (violating P15); fixed by extracting `standard_combined_price()`. Two validator false positives found/fixed (capability-isolation over-broad rules). |
| M16 | Retry-multiplication boot check | `boot.py`'s `validate_retry_ceiling()` (§6 rule 4). |

Every completed milestone (M0–M16) ended with a **fully green** checkpoint: `pytest -q` (all
passing, count grew from 195 → 415 across M0–M16), `ruff check` clean, `mypy` clean, a runtime
validation command run and its output inspected, `scripts/validate_architecture.py` clean (0
violations), and `git status --short` showing only the expected files. See
`docs/phase7_implementation_log.md` for the exact commands and output of each.

---

## 3. Current milestone

**Milestone**: M17 — Full `RoutingGateway.generate()` pipeline (`RateLimiter → RoutingEngine →
FallbackPolicy → cache-before-budget → cost estimation → budget approval → provider dispatch →
usage`).

**Implementation: COMPLETE.**
**Verification: BLOCKED BY EXECUTION ENVIRONMENT.**

### What was implemented (all code written, none of it yet re-verified)

1. **`integrations/llm_gateway/gateway.py` rewritten** — `RoutingGateway.__init__` now takes
   `(routing_engine: RoutingEngine, fallback_policy: FallbackPolicy)` (previously
   `(provider_registry, model_registry)` from the M6 Golden Path). `generate()` builds an
   `ObservabilityContext` and a `RoutingCriteria` from the incoming `GenerateRequest`
   (`capability_name`/`priority`/`excluded_providers` travel via `request.metadata`, matching
   the established "extend via metadata, never the frozen schema" pattern already used for
   `request_id`), calls `routing_engine.route(criteria, observability)`, then
   `fallback_policy.dispatch(request, ranked_candidates, criteria, observability)`.
2. **Confirmed with user and documented**: `RoutingGateway.generate()` does **not** call
   `CostTracker.record()`. Amendment C's scope is explicitly narrow (relocates only
   `BudgetGuard`'s call site). `CostTracker.record()`'s existing signature needs a full
   `CapabilityCall` only `Capability.execute()` can assemble — recording actual usage remains a
   future Capability's post-hoc responsibility.
3. **Rate-limiter placement decision (reasoned, not explicitly asked)**: `RateLimitKey.provider_id`
   is a *required* field, so composite provider/model/capability rate limiting is structurally
   impossible before a candidate is resolved by routing — contradicting §15.2's diagram, which
   lists a single "RateLimiter check" step *before* `RoutingEngine` runs. Resolved by
   implementing the rate-limit check **per-candidate, inside `FallbackPolicy`'s dispatch loop**
   (same place cost/budget checks already live), treating `RateLimitExceededError` exactly like
   a budget denial (continue to next candidate). `FallbackPolicy.__init__` gained an optional
   `rate_limiter: RateLimiter | None = None` parameter (backward compatible with all M15 tests).
4. **Gap found and fixed**: `RateLimiter(Protocol)` itself was never defined in M9 (only the
   concrete `RedisRateLimiter` class existed) — added to `rate_limit/limiter.py`, matching the
   Protocol-plus-impl pattern every other Redis-backed component already follows.
5. **Gap found and fixed**: `ObservabilityContext` was threaded through the M6 Golden Path but
   never through `RoutingEngine.route()` or `FallbackPolicy.dispatch()` once those real
   components were built in M14/M15 — violating §16.1's binding "MUST be threaded through every
   layer" rule. Fixed by adding an optional `observability: ObservabilityContext | None = None`
   parameter to both methods (backward compatible with M14/M15 tests), used to attach
   `trace_id`/`capability_execution_id`/`request_id` to log events.
6. **Gap found and fixed**: `FallbackPolicy` never emitted the `fallback`/`retry` structured
   events §16.2's table specifies. Added `logger.info("fallback", ...)` (on each failed
   candidate, before moving to the next) and `logger.info("retry", ...)` (on each same-candidate
   retry, with `same_candidate_retry_index`/`backoff_ms`).
7. **`RoutingEngine._promote_preferred()` added** — closes a real gap from M14: §4.1 rule 1
   ("`preferred_model`/`preferred_provider` MUST remain advisory only... an
   unavailable/incapable preferred candidate MUST be silently skipped, never an error") was
   never implemented. Now: after ranking, a matching `preferred_model` (or, if unset,
   `preferred_provider`) is promoted to the front of the ranked list; if the preference matches
   nothing, the list is returned unchanged, never an error.
8. **`tests/test_routing_gateway_golden_path.py` rewritten** — its *scenario and assertions* are
   unchanged (one provider, one model, deterministic response, explicit id propagation), but its
   *setup code* now constructs a real `RoutingEngine` + `FallbackPolicy` (via permissive fakes
   from the new `tests/fakes/fake_infra.py`) instead of the old bypass constructor. This is a
   strictly *stronger* regression test than before — it now exercises the real pipeline, not a
   shortcut.
9. **`tests/test_routing_gateway_pipeline.py` created** — new M17-specific tests: cross-provider
   fallback via `generate()` itself (not just `FallbackPolicy.dispatch()` directly), cache-hit
   skips cost/budget via `generate()`, budget-denial-continues-fallback via `generate()`,
   rate-limit-denial-continues-fallback via `generate()`, exhaustion raises
   `AllProvidersFailedError`, `capability_name`/`priority` correctly travel via metadata to
   `BudgetGuard`, `requires_tools` hard filter works end-to-end, `excluded_providers` hard filter
   works end-to-end, `preferred_model` promotion works end-to-end.
10. **`tests/fakes/fake_infra.py` created** — shared minimal permissive fakes
    (`PermissiveProviderHealthStore`, `EmptyLatencyTracker`, `AllowingBudgetGuard`,
    `InMemoryCacheStore`) to avoid duplicating pipeline-assembly boilerplate across test files.

### What was NOT done

- **No test in this milestone has been run.** `pytest`, `ruff check`, `mypy`, the runtime
  validation script, `scripts/validate_architecture.py`, and `git status --short` all need to be
  run for the first time on these changes.
- The changes were reviewed **by careful manual inspection only** (re-reading full file
  contents, cross-checking signatures and call sites, verifying import consistency against
  `scripts/validate_architecture.py`'s rules) — this is not a substitute for actually running
  the tests, and following the project's own "no code is proven until it runs" discipline,
  should not be treated as equivalent to a passing checkpoint.

### Reason verification could not run

Both the Bash and PowerShell tool-execution paths began returning
`"claude-sonnet-5[1m] is temporarily unavailable, so auto mode cannot determine the safety of
Bash/PowerShell right now"` for **every** command attempted, including trivially safe ones
(`echo test`, `python --version`) that had succeeded moments earlier. This persisted across 25+
consecutive attempts spanning a significant span of real time, with no recovery observed before
the session needed to hand off. This is a platform-side safety-classifier availability issue,
not something wrong with the commands themselves or the code.

**First action for the resuming session**: run the full M17 checkpoint (see §7's Resume Prompt)
before touching anything else. If it's green, log M17 in `docs/phase7_implementation_log.md`
(matching the format of every prior milestone entry) and proceed to M18. If anything fails, fix
it in place (the same way M15's cache-bypassing-CostEstimator bug was found and fixed by its own
test suite) before proceeding — do not skip ahead with a known-red checkpoint.

---

## 4. Decisions already approved

All of the following were explicitly discussed and approved during this session (not
assumptions) — do not re-litigate them without a new, explicit instruction from the user:

1. **OpenAI is the only real `ProviderAdapter`** in this delivery. Must stay entirely isolated
   inside `openai_adapter.py` (not yet created — that's M18); no OpenAI-specific field may ever
   be added to a shared Gateway schema. Real network calls must never run in the default
   `pytest` suite. A live smoke test must be optional, explicitly invoked, skip cleanly with no
   `OPENAI_API_KEY`, and never print/log the key. Anthropic and other providers are explicitly
   deferred to separately-approved future milestones.
2. **Cross-provider routing/fallback must be proven with multiple `FakeProviderAdapter`s** across
   ≥2 distinct fake `provider_id`s — not deferred. Done at M14 (RoutingEngine), M15
   (FallbackPolicy), and M17 (full pipeline via `generate()`).
3. **Reduced delivery scope**: implements `generate()` only, fully wired through the real
   pipeline. Explicitly **deferred** past this delivery (Protocol methods remain on
   `LLMGateway` unchanged — both `RoutingGateway` and the future OpenAI adapter raise
   `UnsupportedGatewayCapabilityError` for these until a separately-approved future milestone):
   `generate_stream()`, `embed()`, `classify()`, `moderate()`, `rerank()`, structured-output
   runtime validation/retry, `ToolRegistry`/`ToolExecutor` implementation, `CapabilityNegotiator`,
   real tool loops, MCP, any second real provider.
4. **Golden Path milestone (M6)**: the smallest possible `generate()` slice (one provider, one
   model, no fallback/retry/cache/budget/cost) proven before real pipeline complexity was wired
   in. Its test file remains a permanent regression test — confirmed at M17 that this means the
   *scenario/assertions* stay valid, not that the *setup code* can never be updated as
   `RoutingGateway`'s constructor legitimately evolves.
5. **Architecture validation mechanism**: a dependency-free, hand-maintained
   `scripts/validate_architecture.py` (AST import-scan), not `import-linter` and not a manual-only
   checklist — the lower-commitment default, since the user moved on to other clarifications
   before explicitly confirming this one.
6. **Milestone order**: the revised 21-milestone list (M0–M20) exactly as specified by the user
   (see §5 for the remainder).
7. **No automatic commits.** Every milestone leaves the repo in a runnable (or, per this
   hand-off, clearly-marked-blocked) state, but nothing is committed without explicit approval.
8. **Docker/Postgres/Redis must be running** for the real test suite (`docker compose up -d
   postgres redis`) — confirmed working at session start, clean 195-passed baseline established
   before M0.
9. **Model catalogue**: verified against **live, current OpenAI documentation** (not training
   data) on 2026-07-17 — the actual current lineup is the **GPT-5.6 family** (`gpt-5.6-sol`,
   `gpt-5.6-terra`, `gpt-5.6-luna`; NOT `gpt-4o`/`gpt-4o-mini`, which a pre-2026 training cutoff
   would incorrectly assume). All three were seeded into the static catalogue (`models/catalog.py`)
   per the user's explicit choice ("all three GPT-5.6" over "just terra" or "let me specify").
10. **`BudgetGuard` Amendment C signature change**: `check(capability_name, priority,
    worst_case: Decimal)` replacing Phase 6's `check(request: BudgetCheckRequest{estimated_usage:
    CapabilityUsage})` — confirmed with the user after verifying no production code called the
    old signature; the one Phase 6 shape-only test was updated to match.
11. **`CostTracker` ownership**: `RoutingGateway.generate()` does **not** call
    `CostTracker.record()` — confirmed with the user at M17. It remains a future Capability's
    responsibility (Amendment C's scope is narrow, only relocating `BudgetGuard`).
12. **Cache-before-budget/cost (P15)**: a cache hit MUST be served without invoking
    `CostEstimator` or `BudgetGuard` — enforced in `FallbackPolicy`'s dispatch loop and
    specifically the reason M15's eligibility-filtering bug (calling `CostEstimator` during
    filtering, before any cache check) was treated as a real defect requiring a fix, not a
    style nitpick.
13. **Retry semantics**: same-candidate retry nested inside one candidate's attempt cycle
    (bounded by `max_same_candidate_retries`, default 1 = up to 2 total tries), capped
    exponential backoff (base 250ms, cap 2s, full jitter), never retries a
    `PERMANENT_INCOMPATIBLE`-classified failure (including moderation blocks, which also skip
    all further fallback and raise immediately).
14. **Redis-backed test isolation**: every Redis-backed test uses uuid-namespaced keys and
    cleans them up in its own teardown; the shared `redis_client` test fixture constructs a
    fresh client per test (not the cached `core.redis.get_redis_client()` singleton) to avoid a
    cross-event-loop connection-reuse bug found and fixed at M8.
15. **§28 Q1 (fail-open/fail-closed on Redis unavailability)**: implemented exactly per the
    contract's own binding provisional rule — `RateLimiter` and the real `BudgetGuard` raise
    `MissingRedisFailurePolicyError` at construction if `settings.redis_unavailable_policy` is
    unset, rather than silently defaulting. `CostTracker`'s *write* path never blocks regardless
    of policy (§18's explicit "write failure is a cost-audit data-loss risk, not call-blocking").

---

## 5. Open work

Remaining milestones, in execution order (see the plan file referenced in `docs/phase7_implementation_log.md`'s
header for full descriptions; this list is sufficient to know what's left):

1. **M17 (finish)** — run the full checkpoint on the already-written code described in §3; fix
   anything that fails; log the milestone in `docs/phase7_implementation_log.md`.
2. **M18** — OpenAI ProviderAdapter, `generate()` only. Real `openai` SDK dependency added to
   `pyproject.toml`; `integrations/llm_gateway/providers/openai_adapter.py`; mocked-transport
   contract test (always runs); separate `@pytest.mark.live` test skipped without
   `OPENAI_API_KEY`; optional `scripts/smoke_test_openai_adapter.py`.
3. **M19** — Fixed boot sequence + `CapabilityRegistry` wiring.
   `integrations/llm_gateway/boot.py`'s `assemble_ai_integration_layer(settings)` (the fixed
   order: seal registries → consistency check → construct every component → assemble
   `RoutingGateway`); `capabilities/registry.py`'s `build_registry()` gains the
   injected-dependency signature per §19 rule 2 (still ships empty-sealed — no concrete
   `Capability` exists yet).
4. **M20** — Cross-cutting end-to-end and regression validation.
   `tests/test_ai_integration_layer_e2e.py`: cache-skips-cost-and-budget, budget-denial-
   continues-fallback anchored to cheapest price, cross-provider `TRANSIENT` fallback +
   unhealthy-TTL-skip on a repeat call, exhaustion → `AllProvidersFailedError` with correct
   reason, retry-ceiling enforced in the real boot path, full existing suite re-run to confirm
   zero regressions.

After M20, per the original instructions: report a final summary (completed milestones X/21,
architecture PASS/FAIL, tests X passed/X failed, ruff/mypy/runtime validation PASS/FAIL, working
tree clean/dirty, list all modified/new files) and **ask for approval before creating the Phase 7
implementation commit** — do not commit automatically even after M20 is green.

---

## 6. Known limitations

### Platform issues
- The Bash/PowerShell tool-execution safety-classifier outage that caused this hand-off (§3).
  No code-level cause; purely an execution-environment availability problem at the time of
  writing.

### Architecture debt
- `LowestCostPolicy`/`FallbackPolicy`'s eligibility filtering rank by
  `standard_combined_price()` (input + output "standard"-tier price summed) — the contract
  specifies no exact input/output weighting formula, so a simple sum was used; documented
  inline, not verified against any real-world usage-pattern weighting.
- `RoutingEngine`'s `chosen_rank` observability field is always logged as `0` (its own
  top-ranked recommendation) since `FallbackPolicy` — a separate, later stage — may dispatch a
  different candidate; there's no feedback path from `FallbackPolicy` back to `RoutingEngine`'s
  log event to report which rank was *actually* dispatched.
- No per-priority-tier budget ceiling scaling (`BudgetGuard` reads `priority` but doesn't use it
  to scale the ceiling) and no monthly ceiling enforcement (only `max_daily_ai_cost` is read;
  `max_monthly_ai_cost` remains unused) — the contract specifies no tier-based allocation
  formula, so none was invented.
- `CostEstimator.estimate()`'s `expected` field is computed identically to `worst_case` (the
  contract gives an explicit formula only for `worst_case`'s output-token source) — documented
  as a conservative reading, not an invented "typical case" heuristic.
- `RateLimiter`/`BudgetGuard`/`CostTracker`'s per-candidate rate-limit placement inside
  `FallbackPolicy` (§3 item 3 above) is a reasoned deviation from §15.2's literal diagram
  ordering, necessitated by `RateLimitKey.provider_id` being a required field — documented at
  length in `fallback/policy.py`'s module docstring, but worth another look if a future
  amendment clarifies the intended sequencing.

### Intentional deferrals (approved scope reductions, not omissions)
- `generate_stream()`, `embed()`, `classify()`, `moderate()`, `rerank()` — Protocol methods
  exist unchanged on `LLMGateway`; neither `RoutingGateway` nor any adapter implements them yet.
- Structured-output runtime validation/retry (§8 rule 3's correction-message loop lives inside a
  future `Capability.execute()`, which doesn't exist yet).
- `ToolRegistry`/`ToolExecutor` implementation, real tool loops, MCP.
- `CapabilityNegotiator` and `ProviderHealthStore.verified_flags` (no producer/consumer exists
  without it).
- `CostTracker.record()` is never called by `RoutingGateway` (§4 item 11) — a future Capability's
  job.
- Any second real provider adapter (Anthropic, etc.).

---

## 7. Resume instructions

### Resume Prompt

Paste this to a fresh Claude Code session in this repository to continue:

> Read `docs/phase7_session_handoff.md` in full, then read `docs/phase7_implementation_log.md`
> in full, then read `docs/phase7_architecture_contract.md` §1–§6 and §13–§18 (the sections most
> relevant to what's already built). Do not read the rest of the conversation — it doesn't
> exist; this repo and these three files are your only context.
>
> Phase 7 (AI Integration Layer) is mid-implementation. Milestones M0–M16 are complete and were
> fully verified (pytest/ruff/mypy/runtime validation/architecture validation all green) at the
> time they were finished. Milestone M17 (full `RoutingGateway.generate()` pipeline) has been
> **implemented but never verified** — the previous session's tool-execution environment went
> down before the checkpoint could run. Do not assume M17's code is correct; verify it from
> scratch.
>
> **Your first action**: run, in this order, and actually read the output of each:
> 1. `docker compose up -d postgres redis` then `docker compose ps` (confirm both healthy)
> 2. `python -m pytest -q` (full suite — expect somewhere around 415+ tests; note the exact
>    pass/fail count)
> 3. `python -m ruff check integrations/llm_gateway/ services/ scripts/ tests/`
> 4. `python -m mypy integrations/llm_gateway/ services/ scripts/`
> 5. `python scripts/validate_architecture.py` (expect "clean - 0 forbidden-dependency violations")
> 6. `git status --short` (compare against §1 of the hand-off doc — should match closely; if it
>    doesn't, figure out why before proceeding)
>
> If everything is green: append an M17 entry to `docs/phase7_implementation_log.md` (match the
> exact format of every prior milestone entry in that file — files created/changed, tests added,
> pytest/ruff/mypy results, runtime evidence via a `python -c "..."` one-liner exercising
> `RoutingGateway.generate()` end to end against ≥2 `FakeProviderAdapter`s, architecture
> validation result, known limitations, working-tree state), mark M17 done, and proceed to M18
> (§5 of the hand-off doc has the full remaining milestone list).
>
> If anything fails: fix it in place, the same way earlier milestones' own test suites caught
> and fixed real bugs (see `docs/phase7_implementation_log.md`'s M8, M9, M15 entries for
> examples of the expected fix-forward pattern) — do not skip ahead with a known-red checkpoint,
> and do not weaken a test to make it pass without understanding why it failed first.
>
> Constraints that remain in force for the rest of this delivery: do not redesign the
> architecture; do not edit `docs/phase7_architecture_contract.md`; do not create Amendments; do
> not add database migrations; do not commit anything without the user's explicit, in-the-moment
> approval (not a standing instruction — ask each time); keep implementing one milestone at a
> time with the full six-step checkpoint (pytest, ruff, mypy, runtime validation, architecture
> validation, git status) after each. Stop and ask the user if you discover: a genuine conflict
> with the frozen contract, a need for a database migration, an unexpected change to a Phase 1–6
> public contract, a real architectural defect, or a regression in previously-passing tests.
