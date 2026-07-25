# LLM Runtime Availability Recovery Report

Status: **LLM RUNTIME RECOVERY COMPLETE — HEALTHY**

Context: discovered during Phase 15 M2's live validation (`docs/
phase15_m2_category_reliability_report.md` §13) — pre-existing, unrelated to M2's own code
changes. This report covers a separate, read-only-first diagnosis and a single, narrowly-scoped
recovery action.

---

## 1. Exact runtime-unavailable mechanism

**Component**: `integrations/llm_gateway/fallback/health_store.py`'s `RedisProviderHealthStore`,
consulted by `integrations/llm_gateway/routing/engine.py::RoutingEngine.route()` step 4 (the
health filter) before any candidate model is considered routable.

**Redis keys** (exactly 3, confirmed via `KEYS "phase7:health:*"` before any change — no other
key matched this pattern):
- `phase7:health:openai:gpt-5.6-sol`
- `phase7:health:openai:gpt-5.6-luna`
- `phase7:health:openai:gpt-5.6-terra`

Key shape: `phase7:health:{provider_id}:{model_id}` (`RedisProviderHealthStore._redis_key()`).
These are the **only 3 models in the entire model catalog**
(`integrations/llm_gateway/models/catalog.py`) — so all 3 being unavailable meant zero routable
candidates for **any** capability, not a partial degradation.

**Who writes them**: only one component in the entire codebase calls the two write methods —
`integrations/llm_gateway/fallback/policy.py::FallbackPolicy._attempt_candidate()`:
- `mark_unhealthy(provider_id, model_id, ttl_seconds=60)` — called on a `ProviderTransientError`
  (rate limit, auth-this-attempt-only, timeout, 5xx, unmapped status error) after retries are
  exhausted. Writes `unhealthy_until_ms` with a 60-second TTL — **self-expiring**.
- `mark_runtime_unavailable(provider_id, model_id)` — called on a `ProviderPermanentIncompatibleError`
  or `ProviderModerationBlockedError`. Writes `runtime_unavailable=1` with **no TTL** — by design
  ("MUST NOT expire within the life of the process," per the module's own docstring), meant to
  persist for the life of the process. Since the store is Redis-backed (cross-process, for
  cross-process consistency), it in practice persists across process/container restarts too,
  until a value is explicitly deleted — **there is no automatic-clear or `mark_healthy()`/`reset()`
  method anywhere in this codebase**; manual key deletion is the only clearing mechanism that
  exists for this flag.

**Values found** (read via `HGETALL`, before any change):

| Key | Fields |
|---|---|
| `...gpt-5.6-sol` | `unhealthy_until_ms=1784891913643.7` (a since-expired transient marker, irrelevant once `runtime_unavailable` is also set), `runtime_unavailable=1` |
| `...gpt-5.6-luna` | `runtime_unavailable=1` |
| `...gpt-5.6-terra` | `runtime_unavailable=1` |

**Mechanism classification**: this is a **provider-failure cache / circuit-breaker**, not a
manual disablement and not a simple cooldown — `is_healthy()` fails open (returns `True`) on
Redis backend unavailability itself, and returns `False` only when a positive unhealthy/
unavailable record exists. `runtime_unavailable` specifically represents "this model was recently
proven incompatible with the current request shape or account/region" (its own condition set:
`BadRequestError` not classified as moderation, `PermissionDeniedError`, `NotFoundError`,
`UnprocessableEntityError`, or a moderation block) — a **circuit-breaker latch**, not a time-based
cooldown.

**Exact conditions that set it** (`integrations/llm_gateway/providers/openai_adapter.py::
_translate_exception()`): OpenAI SDK exceptions map to `ProviderPermanentIncompatibleError` for
`BadRequestError` (non-moderation code), `PermissionDeniedError`, `NotFoundError`,
`UnprocessableEntityError`; and to `ProviderModerationBlockedError` for a `BadRequestError` whose
`code` is in a small moderation-code set (`invalid_prompt`, `bio_policy`,
`image_content_policy_violation`, `content_policy_violation`).

**Exact conditions that normally clear it**: none exist in this codebase (confirmed by inspection
— `grep` found no `clear`/`reset`/`mark_healthy` call site or method anywhere). This is a
deliberate, standing gap, not something this recovery broke.

---

## 2. Root cause per model/provider

All 3 models share the same `provider_id="openai"` and the same API key, so a single
account/infrastructure-level condition explains all 3 being latched simultaneously — confirmed by
searching the last 2000 `EditorialTask` rows' recorded step errors (the only place a real,
redacted provider error message is durably captured; `capabilities/gateway_call.py`'s own
call/response objects are not separately persisted, per Phase 15 M0's already-disclosed
`CostTracker`/`AIExecution` gap).

**Only one explicit error message was recoverable** (by design: `FallbackPolicy._run_sequence()`
keeps only the *last* attempted candidate's `failure_detail` per workflow run — earlier
candidates' individual errors in the same run are not separately retained):

```
openai: PermissionDeniedError (status=403): Error code: 403 - {'error': {'code':
'unsupported_country_region_territory', 'message': 'Country, region, or territory not
supported', 'param': None, 'type': 'request_forbidden'}}
```

Recorded at `2026-07-24 21:23:11 UTC`, on a `NEWS_ANALYSIS` task's `research` step.

Per-model report:

| Model | Last known failure type | Auth issue | Rate limit | Timeout/network | Schema/validation | Circuit-breaker reached |
|---|---|---|---|---|---|---|
| gpt-5.6-sol | `PermissionDeniedError` (403, region) — inferred, see note below | No | No | No | No | Yes |
| gpt-5.6-terra | `PermissionDeniedError` (403, region) — the one directly-captured message | No | No | No | No | Yes |
| gpt-5.6-luna | `PermissionDeniedError` (403, region) — inferred, see note below | No | No | No | No | Yes |

**Note on sol/luna**: only one model's exact error string survives in the durable record (the
*last* one attempted in that run). Since `PermissionDeniedError` is account/region-scoped, not
model-specific, and all 3 models share one provider/API key, the same condition affecting one
model at that moment almost certainly affected the other two in the same run — consistent with
all 3 being latched at once with no other explanatory event found in the same window. This is
stated as an inference, not fabricated as directly-observed fact.

An earlier, separate, already-self-resolved event (`~2026-07-24 11:16–11:18 UTC`,
`openai.APITimeoutError`) produced only the 60-second **transient** mark (`mark_unhealthy`), not
the permanent one — irrelevant to the current blocker (already expired hours before this
investigation).

**Distinguishing ACTIVE FAILURE from STALE RUNTIME STATE**: the *recorded* condition (21:23:11 UTC)
was a genuine, real, ACTIVE failure at the time it occurred — not a code bug. Whether the Redis
*state* was still an accurate reflection of *current* provider reality, at the time of this
investigation, could only be determined by a fresh probe (§4) — not assumed either way in advance,
per instruction.

---

## 3. Credential / config sanity (no secrets printed)

Checked inside the live `news_analysis_worker` container:
- `OPENAI_API_KEY` is configured (non-empty, `sk-`-prefixed shape, length 164 — no value printed).
- Model names in `integrations/llm_gateway/models/catalog.py` (`gpt-5.6-sol`, `gpt-5.6-terra`,
  `gpt-5.6-luna`, all `provider_id="openai"`) match exactly what the routing engine attempted to
  resolve — no drift between catalog and what actually failed.
- `ProviderRegistry.is_enabled("openai")` → `True`.

No missing environment variable or configuration drift found.

---

## 4. Safe provider health probe

Used the existing, purpose-built `scripts/smoke_test_openai_adapter.py` — calls `OpenAIAdapter`
directly (bypassing `FallbackPolicy`/`RoutingEngine`/the Redis health store entirely), one minimal
request (`max_tokens=64`, "reply with exactly one short sentence"), no `NewsEvent`/
`EditorialTask`/`ContentDraft` created, no Redis health-store writes triggered by this path.

Run once per model, inside the live container (same network egress as production):

| Model | Result | Latency (approx) | Response preview |
|---|---|---|---|
| gpt-5.6-terra | **SUCCESS** | fast (single round-trip) | "I'm online and ready." |
| gpt-5.6-sol | **SUCCESS** | fast (single round-trip) | "I'm online." |
| gpt-5.6-luna | **SUCCESS** | fast (single round-trip) | "I'm online and ready to help." |

All 3 models responded successfully, with normal token usage, no error of any kind. This is
direct, current evidence that the account/region condition recorded at 21:23:11 UTC (§2) is no
longer in effect — the Redis `runtime_unavailable` state was **stale**, not reflecting current
provider reality.

---

## 5. Recovery action taken

Per the evidence in §3/§4 (provider/config currently healthy; Redis state proven stale by a fresh,
successful direct probe), and because manual key deletion is the *only* clearing mechanism this
codebase's health-store design provides (§1) — clearing it is not a workaround, it is the intended
(if manual) recovery path for a `runtime_unavailable` latch.

**Action**: deleted exactly the 3 stale keys, nothing else.

```
DEL phase7:health:openai:gpt-5.6-sol phase7:health:openai:gpt-5.6-luna phase7:health:openai:gpt-5.6-terra
```

Confirmed before deletion: `KEYS "phase7:health:*"` returned exactly these 3 keys, no others.
Confirmed after: `KEYS "phase7:health:*"` returns empty. No `FLUSHDB`/`FLUSHALL`, no other key
pattern touched, no application data (Postgres) touched, no `.env` change.

---

## 6. Verification after recovery

**Routing engine, direct check (no generation call)**: constructed a `RoutingEngine` against the
live Redis instance and called `route()` with `capability_name="research"` — a pure read/filter
operation, zero network calls to any provider. Result: all 3 models now returned as routable
candidates (`[('openai', 'gpt-5.6-sol'), ('openai', 'gpt-5.6-terra'), ('openai', 'gpt-5.6-luna')]`),
where before recovery this call raised `NoRoutableCandidateError`.

**Worker container health**: all 5 services `Up` (`automation_worker`, `news_analysis_worker`,
`content_worker`, `postgres` healthy, `redis` healthy) — unchanged by this action, no container
was restarted or rebuilt for this recovery.

**One natural NEWS_ANALYSIS opportunity observed** (no story was manually forced): the next
scheduled `news_analysis_worker` cycle after recovery (`~22:41–22:42 UTC`) completed **5
NEWS_ANALYSIS tasks with `status=COMPLETED`** — the first successful completions since the
21:23:11 UTC failure. The 5 tasks that failed in the *preceding* cycle (`22:36:11 UTC`, before the
Redis fix) failed with the exact same `"No routable candidate"`-class error already explained in
§2 — confirming the fix's before/after boundary cleanly.

**`content_worker`**: its next natural cycle (`~22:46 UTC`) completed with zero errors logged; 0
new `CONTENT_GENERATION` tasks were created in that window because none of the newly-analyzed
events happened to score ≥ `CONTENT_GENERATION_MIN_SCORE` yet — an ordinary, expected outcome (the
score-gate is already documented, in Phase 14.5's reports, as the dominant filter under normal
operation), not a sign of continued breakage. No story was manually forced and no manual Telegram
send was performed, per instruction — a naturally occurring delivery was not required for this
recovery step.

---

## 7. No backlog surprise

Confirmed unchanged, read directly from `Settings` after recovery: `NEWS_ANALYSIS_FRESHNESS_
CUTOFF_HOURS=2.0`, `CONTENT_GENERATION_FRESHNESS_CUTOFF_HOURS=24.0`,
`CONTENT_GENERATION_MIN_SCORE=65`, `NEWS_ANALYSIS_BATCH_SIZE=5`,
`CONTENT_GENERATION_BATCH_SIZE=5`, `NEWS_ANALYSIS_POLL_INTERVAL_SECONDS=300`,
`CONTENT_GENERATION_POLL_INTERVAL_SECONDS=1800`. `.env` was never written (`git status --short
.env` shows no change throughout). This recovery action only affects which models are considered
*routable* — it does not touch task eligibility, freshness windows, or batch selection logic in
any way, so no old backlog became newly eligible as a side effect. The 5 newly-COMPLETED tasks in
§6 were already-`CREATED`, already-within-freshness-window tasks that simply could not execute
before recovery — not a backlog reprocessing.

---

## 8. Remaining limitations

- **No automatic recovery mechanism exists** for a `runtime_unavailable` latch (§1) — if the same
  account/region condition recurs, the same manual-diagnosis-and-clear process would be needed
  again. Building an automatic re-probe/expiry mechanism would be a real architecture change and
  is explicitly out of scope for this recovery task.
- **Only one of the three models' exact failure messages was directly recoverable** from durable
  storage (§2) — the conclusion that all three shared the same root cause is a well-supported
  inference (shared account/provider, simultaneous latch, no other explanatory event), not a
  directly-observed fact for `sol`/`luna` individually.
- **The underlying OpenAI-side cause of the one observed `unsupported_country_region_territory`
  error is still unknown** — it could have been a transient OpenAI-side routing/geo-classification
  hiccup (most consistent with the evidence: identical key, identical models, identical container
  network egress now succeed cleanly) or a brief upstream network-path change. This report does
  not claim to know which; it only reports that the condition is not currently reproducible.

---

# LLM RUNTIME RECOVERY COMPLETE — HEALTHY
