# Phase 18.9-R M1 — Full Test-to-Provider Path Audit

Status: complete, read-only. Every path below was located via direct code inspection (`grep`
followed by reading the actual file), not inferred from naming. No `UNKNOWN` classification
remains open - every discovered path was resolved to one of the four other categories.

## Classification legend

- **SAFE_FAKE** — constructs/uses a fake object (mock, `FakeProviderAdapter`, `httpx.MockTransport`,
  `AsyncMock(spec=AsyncOpenAI)`) - structurally cannot reach a real provider regardless of bugs
  elsewhere in the test.
- **SAFE_BLOCKED** — would reach real construction code, but is explicitly monkeypatched/asserted
  to fail loudly if ever invoked (an existing poison-pill-shaped pattern).
- **SHARED_STATE_ONLY** — touches real, shared infrastructure (Postgres, Redis) but never a real
  LLM provider; risk is data/ledger pollution, not paid API cost.
- **REAL_PROVIDER_REACHABLE** — the exact, confirmed shape of the Phase 18.9 incident: real
  `Settings` (real `.env`, real key) combined with an unguarded `assemble_ai_integration_layer()`/
  `CapabilityExecutor` call path.

## 1. Every path that can construct `assemble_ai_integration_layer()`

| File | Pattern | Classification |
|---|---|---|
| `tests/test_boot_assembly.py` | `Settings(_env_file=None, openai_api_key=SecretStr("sk-test-..."))`, never calls `.generate()` | SAFE_FAKE |
| `tests/test_capability_boot_wiring_e2e.py` | Same `_env_file=None` + fake key pattern | SAFE_FAKE |
| `tests/test_phase8_cross_cutting_regression.py` | Same pattern | SAFE_FAKE |
| `tests/test_phase9_cross_cutting_regression.py` | Same pattern | SAFE_FAKE |
| `tests/test_analysis_worker_main.py` | `patch("worker.analysis_main.assemble_ai_integration_layer", return_value=_FAKE_AI_LAYER)` | SAFE_FAKE |
| `tests/test_content_worker_main.py` | Same patch pattern | SAFE_FAKE |
| `tests/test_run_content_generation.py` | `monkeypatch.setattr(..., "assemble_ai_integration_layer", _fail_if_called)` - an **existing poison-pill precedent**, raises `AssertionError` if ever reached | SAFE_BLOCKED |
| `scripts/phase18_9_controlled_batch_runner.py` | Real `assemble_ai_integration_layer(settings, ...)` with real `core.config.settings`, called lazily, gated by (now-fixed) budget check | **REAL_PROVIDER_REACHABLE** - this is the confirmed incident's own code path, now fixed but not yet independently barrier-protected at the suite level |
| `scripts/run_content_generation.py` | Same real construction, but only reached via explicit CLI/manual invocation, never automatically by any test | REAL_PROVIDER_REACHABLE (same reasoning) |
| Other `scripts/phase17_*.py` files | Manual, human-invoked tools, never imported/executed by any test | Not test-reachable - out of this audit's own scope (which is test paths) |

**Verdict**: exactly one class of real risk exists - `scripts/phase18_9_controlled_batch_runner.py`
(and, by the same reused function, `scripts/run_content_generation.py`) when driven with
`dry_run=False` and no injected fake registry. Every other `assemble_ai_integration_layer()` call
site in the test suite already uses an established safe pattern.

## 2. Direct `OpenAIAdapter`/`AsyncOpenAI` construction

| File | Pattern | Classification |
|---|---|---|
| `tests/test_openai_adapter.py` | `AsyncMock(spec=AsyncOpenAI)` - fully fake client, real `OpenAIAdapter` wraps it | SAFE_FAKE |
| `tests/test_fallback_policy.py` | Mentions OpenAI only in a docstring explaining why `FakeProviderAdapter` is used instead | SAFE_FAKE |
| `tests/test_openai_strict_schema_compliance.py` | Same - uses `FakeLLMGateway`/`FakeProviderAdapter` | SAFE_FAKE |
| `tests/test_validate_architecture.py` | Static text scanning only, no construction | Not applicable |
| `tests/test_provider_registry.py` | `Settings(_env_file=None, ...)` | SAFE_FAKE |

`OpenAIAdapter.__init__(credential, *, client=None)` constructs a **real** `AsyncOpenAI(api_key=...,
base_url=credential.base_url)` only when `client` is not injected. `credential.base_url` defaults
to `None`, meaning the OpenAI SDK's own hardcoded default (`https://api.openai.com/v1`) is used.
This is the exact mechanism the incident exploited.

## 3. `verify_capabilities_at_boot` - confirmed not a hidden real-call trigger

`integrations/llm_gateway/boot.py`: `if settings.verify_capabilities_at_boot: raise
CapabilityNegotiatorNotImplementedError(...)` - this setting, even if `True`, never makes a real
call (the feature itself is unimplemented, it just raises). All SAFE_FAKE tests above explicitly
set it `False` anyway. Confirmed by reading the source, not assumed.

## 4. `tests/test_api_cost_optimization_checklist.py` — the specifically-required investigation

1. **Why it mutates the real "research" ledger**: `test_ledger_namespace_is_utc_calendar_date_
   so_a_new_day_starts_empty` deliberately constructs `RedisCostTracker(redis_client,
   pricing_catalog)` with **no fixed namespace** (its own stated purpose: proving production's
   real, calendar-date-based namespace behavior), then calls the real `tracker.record(uuid.uuid4(),
   "research", call)` with a **fake, no-network `CapabilityCall`** object
   (`model_used="gpt-5.6-luna"`, 1000/1000 fake tokens). This writes real, correctly-computed cost
   math into the real `phase7:cost_ledger:2026-08-05:research` key.
2. **Whether it can ever make a real provider call**: **No.** `RedisCostTracker.record()` never
   calls a provider - it is a pure cost-computation-and-Redis-write function, confirmed by reading
   `services/cost_tracker.py::record()` directly (no LLM Gateway import in that module at all).
   `CapabilityCall` here is a plain dataclass-like object the test constructs by hand, not the
   result of any real call.
3. **Why it was not isolated previously**: the test's own docstring/purpose *requires* using the
   real calendar-date namespace (that's the specific behavior under test) - the defect is that its
   `finally` block only deletes the *global* ledger key (`today_key`), never the *capability-
   specific* key (`capability_ledger_key(namespace, "research")`) that the same `record()` call
   also writes to. An incomplete cleanup, not a deliberate design choice.
4. **Whether it uses the real Redis instance**: **Yes** - the `redis_client` fixture
   (`tests/conftest.py`) connects to `settings.redis_url`, the same real, production Redis instance
   `automation_worker`/`backend` use. No dedicated test database index or isolated instance exists
   anywhere in this codebase today (§6 below).
5. **Whether it cleans up shared keys**: **Partially** - deletes the global key, leaks the
   capability-specific key indefinitely (confirmed root cause of the second, initially-alarming
   ledger increase investigated during Phase 18.9's own incident review,
   `docs/phase18_9_incident_snapshot.md` §7).
6. **Whether other tests have the same pattern**: searched exhaustively (`grep -rn
   "global_ledger_key("` across the full repository) - **this is the only test file that calls
   `global_ledger_key()`/`capability_ledger_key()` with the real calendar-date namespace instead of
   a UUID-based one.** Every other file that constructs `RedisCostTracker`/`RedisBudgetGuard`
   (`tests/test_budget_guard_real.py`, `tests/test_cost_tracker_real.py`,
   `tests/test_cost_recording_integration.py`) uses an injected UUID namespace with explicit
   teardown deletion - verified directly, not assumed.

Classification: **SHARED_STATE_ONLY** (real Redis writes, zero provider risk) - but a confirmed,
real defect, fixed in M5.

## 5. Postgres: `db_session`/`real_news_event` fixtures

`tests/conftest.py`'s `db_session` connects to `settings.database_url` (the real, same production
Postgres database `automation_worker`/`backend` use), isolated only via a SAVEPOINT-based
transaction rolled back at teardown. **SHARED_STATE_ONLY under normal use** - but M6 examines why
this is insufficient on its own when the same test can also reach a real provider/Redis side
effect that a Postgres rollback cannot undo (the exact shape of the Phase 18.9 incident).

## 6. Redis: `redis_client` fixture

Connects to `settings.redis_url` directly - **no dedicated test database index, no namespace
isolation enforced structurally**, only by per-test convention (unique UUID namespaces + manual
teardown deletion). This convention held everywhere except `test_api_cost_optimization_checklist.
py` (§4). Classification: **SHARED_STATE_ONLY**, with a confirmed structural gap - fixed in M5 by
moving to a dedicated Redis database index (defense in depth beyond convention alone).

## 7. HTTP transport paths (relevant to M4's network barrier design)

Only 4 production modules construct `httpx.AsyncClient` directly:
`integrations/sources/{arxiv,github,hacker_news,rss}_source.py`. Every test exercising them
(`tests/test_{arxiv,github,hacker_news,rss}_source.py`) monkeypatches `httpx.AsyncClient.__init__`
to force `transport=httpx.MockTransport(handler)` - confirmed via direct reading, real network
never touched, fake target URLs like `https://example.com/feed.rss` never actually resolved.
**SAFE_FAKE.** No test constructs `httpx.AsyncClient`/`httpx.Client` for a real external request
anywhere in the suite. This directly informs M4's design: a global `.send()` guard that always
allows requests already routed through `httpx.MockTransport` (checked by transport type, not
hostname) will not conflict with any of these 4 files' own established pattern.

## Summary — zero `UNKNOWN` remaining

Every test-reachable path resolves cleanly. The **only** `REAL_PROVIDER_REACHABLE` path is
`scripts/phase18_9_controlled_batch_runner.py`'s (and, by extension, `scripts/
run_content_generation.py`'s) real `assemble_ai_integration_layer()` call when driven with
`dry_run=False` and no fake registry injected - exactly the incident's own shape, already partially
mitigated (M5/M6 of the original Phase 18.9 work: lazy construction + per-test poison-pill
injection) but not yet protected by a **suite-wide, automatic** barrier independent of any
individual test remembering to inject a fake registry. M2 closes this gap.
