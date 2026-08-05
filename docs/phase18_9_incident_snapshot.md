# Phase 18.9 — Incident Snapshot (Evidence Preservation)

Captured before any further cleanup or test execution, per explicit instruction. Redis is treated
as **insufficient as sole authoritative source** - this snapshot exists precisely because the
global ledger key was found deleted mid-investigation. No secret is included anywhere below.

## 1. All `phase7:cost_ledger:*` keys observed for 2026-08-05, at snapshot time

| Key | Type | TTL | Value |
|---|---|---|---|
| `phase7:cost_ledger:2026-08-05` (global) | none (absent) | -2 | — |
| `phase7:cost_ledger:2026-08-05:research` | string | -1 (no expiry) | `0.050028` |
| `phase7:cost_ledger:2026-08-05:intelligence` | string | -1 | `0.002432` |
| `phase7:cost_ledger:2026-08-05:engagement` | string | -1 | `0.00246` |
| `phase7:cost_ledger:2026-08-05:scoring` | string | -1 | `0.000846` |

No other `phase7:cost_ledger:2026-08-05*` keys exist (`KEYS` pattern scan, exhaustive for this
date). No non-today-dated key was inspected (out of scope - this incident is confined to today's
namespace by construction, since every write path uses `_today_namespace()`).

## 2. Redis timestamps

Not available. Redis `STRING` values written via `INCRBYFLOAT` carry no built-in write timestamp,
and no `TTL` is set on any of these keys (`-1` throughout) - there is no way to determine exact
write times from Redis state alone. Approximate timing is reconstructed in §7 from the sequence of
actions taken in this session, not from Redis itself.

## 3. Relevant application/test/container logs

**None found.** `docker logs` for `automation_worker` (the only worker running throughout) shows
only real RSS-collection activity (stale-URL redirects for unrelated sources), no capability/
OpenAI activity - expected, since `automation_worker` cannot make capability calls (confirmed,
`docs/phase18_9_paid_pipeline_audit.md` §8/§O0). `backend`/`telegram_bot`/`postgres`/`redis`
container logs show nothing relevant. **This is itself a finding**: the incident's own test
execution ran as a local Python/pytest process directly on the host (not inside any Docker
container), so it produced no container-log trail at all - only the Redis ledger and this
session's own terminal transcript constitute the available evidence.

## 4. Task IDs / NewsEvent IDs involved

**Not recoverable.** The vulnerable tests used `tests/conftest.py::db_session` (a SAVEPOINT-based
transaction, rolled back at test teardown) and `real_news_event` (a fixture-created `NewsEvent`
inside that same transaction). Every `EditorialTask`/`NewsEvent` row created during the incident
was rolled back from Postgres - their UUIDs were never logged or captured outside the transaction
before rollback. This is a disclosed forensic gap, not a withheld fact.

## 5. `AIExecution` rows associated with the incident window

**Zero.** `SELECT COUNT(*) FROM ai_executions WHERE created_at::date = '2026-08-05'` returns 0, and
`ai_executions` total row count remains 4,632 (unchanged from before Phase 18.9 began) throughout
the entire session, verified repeatedly. The durable database record shows nothing - all evidence
of the incident comes from the independent Redis ledger writes (§1), which are not part of any
Postgres transaction and were therefore never rolled back.

## 6. Provider / model / request identifiers

**Model**: not directly logged; inferred as `gpt-5.6-luna` (the dominant/default real-routing
model per `docs/phase18_9_paid_pipeline_audit.md` §3 - >95% of real historical traffic). **Request
ID**: not available - would only exist in the `AIExecution.response` JSON field or raw HTTP
response headers, neither of which was captured (the DB row was rolled back; no HTTP-level logging
was enabled for this ad hoc host-process pytest run).

## 7. What removed the global ledger key — fully explained, root-caused

**Not part of the Phase 18.9 incident.** Direct code inspection
(`tests/test_api_cost_optimization_checklist.py::
test_ledger_namespace_is_utc_calendar_date_so_a_new_day_starts_empty`, a **pre-existing test, not
authored or modified in this session**) shows:

```python
tracker = RedisCostTracker(redis_client, pricing_catalog)  # production default: real calendar-date namespace
...
today_key = global_ledger_key(now.strftime("%Y-%m-%d"))
try:
    await tracker.record(uuid.uuid4(), "research", call)   # `call` is a fake CapabilityCall - no network call
    ...
finally:
    await redis_client.delete(today_key)                    # deletes ONLY the global key
    ...                                                      # never deletes capability_ledger_key(namespace, "research")
```

This test deliberately uses the **real, production-default, calendar-date namespace** (its own
purpose is to verify that production's namespace-by-date behavior works) and calls the real
`RedisCostTracker.record()` with a **fake, no-network `CapabilityCall`** object
(`model_used="gpt-5.6-luna"`, `input_tokens=1000`, `output_tokens=1000`). This writes real,
correctly-computed cost data into the real `phase7:cost_ledger:2026-08-05:research` key -
**zero real OpenAI calls involved** - then explicitly **deletes only the global key** in its
`finally` block, leaving the per-capability `research` key to leak, uncleaned, indefinitely, across
every full-suite run on the same calendar date.

**Exact confirmation**: `gpt-5.6-luna` pricing is $1.00/M input + $6.00/M output tokens
(`integrations/llm_gateway/models/catalog.py`). This test's fixed 1000/1000 token call costs
exactly `1000/1,000,000 × $1.00 + 1000/1,000,000 × $6.00 = $0.001 + $0.006 = $0.007000` - an
**exact** match to the previously-unexplained second `research` ledger increase
($0.043028 → $0.050028, delta = $0.007000 exactly). This is now fully resolved: that specific
increase is a real, pre-existing test-hygiene defect (incomplete cleanup, unrelated to any live
provider call), not a second unauthorized execution. It very likely also explains some or all of
the *original* $0.042 "research" baseline this audit found unexplained in M0 (this same leaky test
has run once per full-suite execution in every phase of this session - 18.6, 18.7, 18.8 - each
calendar day reset would zero it, but all of this session's activity has occurred on the same
simulated date, 2026-08-05, so the leak accumulates across all of them without a natural reset).
**This finding is disclosed, not fixed** - correcting this pre-existing test's cleanup is outside
Phase 18.9's own scope (a defect that predates this phase) unless separately authorized.

## 8. Confirmation: no paid workers running

`docker ps` at snapshot time: `news_analysis_worker` and `content_worker` are **absent** from the
running-container list (only `postgres`, `redis`, `backend`, `automation_worker`, `telegram_bot`
are up). Confirmed directly, not inferred.

## 9. Confirmation: ledger no longer growing

All 4 today-dated capability keys (§1) were read three times: (a) immediately after the original
incident's own remediation began, (b) 20 seconds later, (c) immediately after forcibly terminating
the then-running full regression suite (PID 21892, killed per instruction while at 93% progress,
`PowerShell Stop-Process -Force`). All three reads returned **identical** values - the ledger is
confirmed static as of this snapshot.

## 10. Incident classification (per explicit instruction - not double-counting the vanished
global aggregate against the per-capability entries)

| Component | Status |
|---|---|
| `intelligence` ($0.002432), `engagement` ($0.00246), `scoring` ($0.000846) | **Confirmed part of the genuine incident** - all three are keys with no other explanation found; no pre-existing test writes to these under the real-date namespace |
| `research`'s $0.007000 second increment ($0.043028 → $0.050028) | **Root-caused, reclassified as NOT part of the incident** - the pre-existing `test_ledger_namespace_is_utc_calendar_date_so_a_new_day_starts_empty` leak (§7), zero real provider calls |
| `research`'s original ~$0.042 baseline (and the further ~$0.001028 this audit first attributed to the incident) | **Unresolved, likely also (fully or partly) the same pre-existing leak**, accumulated across this session's prior full-suite runs (Phase 18.6/18.7/18.8) on the same simulated calendar date - not cleanly separable from any possible genuine incident contribution with the evidence available |
| Global ledger key deletion | **Fully explained** (§7) - the same pre-existing test's own `finally` block, not evidence of tampering or a separate event |
| Confirmed unauthorized executions | **At least 1** |
| Suspected unauthorized executions | **2** (both `test_task_refused_when_conservative_estimate_would_exceed_remaining_budget` and `test_cumulative_prior_spend_counts_toward_the_same_budget` showed `status="completed"` in the same buggy run, each against its own independent `real_news_event` fixture instance - each independently capable of a full real execution) |
| Exact execution count | **Unresolved** - cannot be determined from available evidence (no task/event IDs recovered, `AIExecution` rows rolled back, no request IDs captured) |
| Provider-authoritative cost | **Pending independent OpenAI usage-dashboard verification** - not checked from this environment, no access available |
