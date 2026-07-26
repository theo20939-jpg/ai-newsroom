# Phase 15 — Runtime Reliability: Automatic Provider Health Recovery

Status: **IMPLEMENTED AND DEPLOYED**. Fixes the recurring `runtime_unavailable` Redis latch
that had already required two separate manual recovery interventions this phase
(`docs/llm_runtime_availability_recovery_report.md`, and the M5.1 recurrence documented in
`docs/phase15_m5_fact_safety_report.md`). No architecture rewrite: the existing circuit-breaker
design (`ProviderHealthStore` + `FallbackPolicy`) is extended, not replaced.

---

## 1. The recurring defect

`integrations/llm_gateway/fallback/health_store.py`'s `mark_runtime_unavailable()` wrote a
`runtime_unavailable=1` flag with **no TTL and no automatic-clear mechanism** for every
`PERMANENT_INCOMPATIBLE`-classified provider failure. This classification bucketed three very
different OpenAI SDK exceptions together: `NotFoundError` (invalid model id — genuinely
permanent), `UnprocessableEntityError` (rejected request shape — genuinely permanent), and
`PermissionDeniedError` (HTTP 403 — a regional/account-scoped condition).

The last of these had already been directly observed to be **transient at the timescale of
hours, not permanent**: `docs/llm_runtime_availability_recovery_report.md` documents a real
`unsupported_country_region_territory` 403 recorded at `2026-07-24 21:23:11 UTC`, whose
condition had already cleared by the time of the same day's re-probe — yet the Redis latch it
set had **no way to expire on its own**, requiring a manual `KEYS`/`DEL` diagnosis-and-clear
each time it recurred (confirmed recurring again during M5.1, `docs/phase15_m5_fact_safety_
report.md`'s own M5.1 section). Since all 3 catalog models share one `provider_id="openai"` and
one API key, a single account-level 403 latches every model simultaneously — zero routable
candidates for any capability, stopping the entire pipeline until someone noticed and
intervened.

## 2. Error taxonomy used to distinguish bounded from permanent

| OpenAI exception | Gateway exception (after this fix) | Latch behavior |
|---|---|---|
| `AuthenticationError` | `ProviderTransientError` | 60s TTL, unchanged |
| `RateLimitError` | `ProviderTransientError` | 60s TTL, unchanged |
| `InternalServerError`, `ConflictError` | `ProviderTransientError` | 60s TTL, unchanged |
| `APIConnectionError` / `APITimeoutError` | `ProviderTransientError` | 60s TTL, unchanged |
| unmapped `APIStatusError` | `ProviderTransientError` | 60s TTL, unchanged |
| `BadRequestError` (moderation code) | `ProviderModerationBlockedError` | permanent, unchanged |
| `BadRequestError` (non-moderation) | `ProviderPermanentIncompatibleError` | **permanent, unchanged** |
| `NotFoundError` (invalid model id) | `ProviderPermanentIncompatibleError` | **permanent, unchanged** |
| `UnprocessableEntityError` (rejected shape) | `ProviderPermanentIncompatibleError` | **permanent, unchanged** |
| **`PermissionDeniedError` (403, regional/account)** | **`ProviderRegionalUnavailableError` (new)** | **bounded TTL (new)** |

Only `PermissionDeniedError` moved to the new bounded class — every other classification is
untouched, preserving the exact existing protection for genuinely permanent configuration
errors (an invalid model id must never silently "expire" and get retried forever).

## 3. The fix

**Two independent, additive mechanisms**, both opt-in via new optional parameters (every
existing caller's behavior is unchanged by default):

1. **Bounded cooldown.** `mark_runtime_unavailable(provider_id, model_id, ttl_seconds=None)` —
   `ttl_seconds=None` (default) preserves the exact old "no TTL, permanent until manual clear"
   behavior. `FallbackPolicy` now passes a real TTL
   (`settings.provider_regional_unavailable_cooldown_seconds`, default 3600s/1 hour) specifically
   for a caught `ProviderRegionalUnavailableError`. The bound is stored in a second Redis hash
   field, `runtime_unavailable_until_ms`, checked at read time in `is_healthy()` — the same
   explicit-timestamp-at-read-time pattern the codebase already used for `unhealthy_until_ms`
   (never Redis's own key-level `EXPIRE`, since the hash also carries the separate
   `runtime_unavailable` flag that per the original design "MUST NOT expire within the life of
   the process" for the *permanent* case — expiring the whole key would silently clear that too).
2. **Auto-clear on success.** A new `mark_healthy(provider_id, model_id)` method clears all
   three fields (`unhealthy_until_ms`, `runtime_unavailable`, `runtime_unavailable_until_ms`).
   `FallbackPolicy._attempt_candidate()` now calls it immediately after every real, observed
   successful `adapter.generate()` call — a candidate does not have to wait out its full cooldown
   if it turns out to already be working again.

No background re-probe loop, no periodic paid polling, no provider storm: recovery is driven
entirely by (a) the passage of time (TTL expiry, read lazily — no timer/task) and (b) organic
production traffic's own next successful call. Both mechanisms reuse the pipeline's existing
call pattern; neither adds a single new provider call.

## 4. Files changed

- `integrations/llm_gateway/errors.py` — new `ProviderRegionalUnavailableError`; clarified
  `ProviderPermanentIncompatibleError`'s docstring to state what it's now reserved for.
- `integrations/llm_gateway/providers/openai_adapter.py` — `_translate_exception()` splits
  `PermissionDeniedError` into its own branch.
- `integrations/llm_gateway/fallback/health_store.py` — `mark_runtime_unavailable()` gains
  optional `ttl_seconds`; new `mark_healthy()`; `is_healthy()` checks the new bounded-expiry
  field.
- `integrations/llm_gateway/fallback/policy.py` — new `FailureClass.REGIONAL_UNAVAILABLE`; new
  `except ProviderRegionalUnavailableError` branch; `mark_healthy()` called on every successful
  attempt; new `regional_unavailable_cooldown_seconds` constructor parameter (default 3600s).
- `core/config.py` — new `provider_regional_unavailable_cooldown_seconds: int = 3600` setting.
- `integrations/llm_gateway/boot.py` — threads the setting into `FallbackPolicy`'s construction.
- Test fakes updated for the new `ProviderHealthStore` surface (`mark_healthy`, optional
  `ttl_seconds`): `tests/fakes/fake_infra.py::PermissiveProviderHealthStore`, and two
  locally-defined fakes in `tests/test_fallback_policy.py` / `tests/test_routing_engine.py`.
  `tests/fakes/fake_provider_adapter.py` gained a `"regional_unavailable"` behavior.
- `tests/test_openai_adapter.py` — the pre-existing `PermissionDeniedError` translation test
  updated to assert the new exception type (a deliberate reclassification, not a regression).

## 5. Tests

New tests, all passing:

- `tests/test_provider_health_store.py` (Redis integration, real local Redis): bounded mark
  creates the expiry field and is unhealthy; bounded mark expires automatically after its TTL;
  `mark_healthy()` clears a bounded mark before its TTL elapses; `mark_healthy()` also clears a
  permanent (no-TTL) mark; `mark_healthy()` also clears a transient `unhealthy` mark; a permanent
  mark still writes no expiry field at all; a bounded mark touches only its own Redis key (no
  unrelated keys affected); the state-transition log line contains no API-key-shaped or
  `Bearer `-prefixed pattern; both new methods swallow backend errors exactly like the existing
  ones (fail-open discipline preserved).
- `tests/test_fallback_policy.py` (pure unit, no Redis): a `ProviderRegionalUnavailableError`
  marks runtime_unavailable **with** the configured TTL and continues to the next candidate,
  never retried (same non-retry discipline as `ProviderPermanentIncompatibleError`); the
  cooldown is configurable via the constructor; a successful dispatch calls `mark_healthy()`.
- `tests/test_openai_adapter.py` — `PermissionDeniedError` now asserted to translate to
  `ProviderRegionalUnavailableError`, not `ProviderPermanentIncompatibleError`.

Full regression (all files touching `ProviderHealthStore`/`FallbackPolicy`/`RoutingEngine`/boot
wiring, plus Fact Safety and workflow integration): **203 passed**, 0 failed, in isolated runs.
See `docs/phase15_final_closure_report.md` §14 for the complete final full-suite total.

## 6. Deployment

`docker compose build news_analysis_worker content_worker && docker compose up -d --no-deps
news_analysis_worker content_worker` — the two services that actually dispatch real LLM Gateway
calls in production. `automation_worker` (Collector + Triage) does not use the LLM Gateway at
all (`services/triage_orchestrator.py`'s own docstring: "no LLMGateway, no Capability layer, no
provider SDK") and was left untouched, matching "deploy only affected services." `backend` is
not currently running in this environment (not in `docker compose ps` output) and was not
started. `postgres`/`redis` were not restarted.

## 7. Post-deploy verification

Read-only check, no smoke probes issued (none were necessary — all 3 catalog models were
already confirmed healthy with no active latch; see §8):

- `provider_regional_unavailable_cooldown_seconds` confirmed live at `3600` inside the running
  `news_analysis_worker` container.
- `fact_safety_mode` confirmed still `"shadow"`; `editorial_scoring_version` confirmed still
  `"v1"` — this deployment touches neither.

## 8. Current provider health state (read-only)

`KEYS "phase7:health:*"` still returns all 3 model keys (`gpt-5.6-sol`, `gpt-5.6-luna`,
`gpt-5.6-terra`) with a leftover `unhealthy_until_ms` field each — stale, already-expired
60-second transient markers from ordinary past operation, not an active latch. Direct
`is_healthy()` calls (read-only, no generation request) confirmed all 3 currently `True`
(healthy/routable). No `runtime_unavailable` flag is set on any model at the time of this
report. Deliberately no smoke probes were spent confirming this further: natural
`NEWS_ANALYSIS` cycles already provide the same evidence for free (see
`docs/phase15_final_closure_report.md`'s live-pipeline section) without spending paid provider
calls that aren't otherwise needed.

## 9. Remaining limitations

- The bounded cooldown (default 1 hour) is a fixed constant per deployment, not
  adaptive/exponential-backoff across repeated regional failures — a reasonable, simple starting
  point per the task's own "smallest architecture-preserving fix" instruction, not tuned against
  multiple real recurrences (only one real historical incident exists to calibrate against).
- `mark_healthy()` only fires on a candidate that is actually *attempted* — a model excluded
  from every attempt sequence for an unrelated reason (e.g. cost ceiling) would not have its
  stale state cleared by this path; it still benefits from the TTL expiry path, just not the
  faster auto-clear-on-success path.
- This fix addresses the `runtime_unavailable` latch specifically (the one directly implicated
  in both real historical incidents). The pre-existing 60-second `unhealthy` (transient) TTL was
  already self-expiring and is unchanged.

---

**RUNTIME RELIABILITY FIX COMPLETE — AUTOMATIC RECOVERY IN PLACE, NO ACTIVE LATCH**
