# Phase 18.9-R — Test-to-Production Isolation Remediation: Closure Report

Status: remediation complete, all acceptance criteria met, pending independent review before any
return to Phase 18.9's own paid-run preflight/authorization question.

## 1. Original incident summary

During Phase 18.9's own M6 test development (`tests/test_phase18_9_controlled_batch.py`), a
budget-check bug let a test call `run_bounded_analysis_batch(..., dry_run=False)` reach a genuine
`WorkflowRunner.run()` execution against the real, production-configured OpenAI provider - a real,
unauthorized paid API call during what was supposed to be a strictly read-only preflight phase.
Full original account: `docs/phase18_9_paid_pipeline_audit.md`'s dedicated incident section,
`docs/phase18_9_incident_snapshot.md`.

## 2. Confirmed financial impact

**Confirmed, incident-attributable minimum**: `intelligence` +$0.002432, `engagement` +$0.00246,
`scoring` +$0.000846 = **$0.005738** (real Redis ledger keys with no other explanation found - M1
audit, §4). A separate `research` +$0.007000 delta observed during the review is **not** part of
this incident - fully root-caused (§6 below) to an unrelated, pre-existing test defect. **Real,
confirmed unauthorized executions: at least 1. Suspected: 2** (both vulnerable tests showed
`status="completed"` in the same buggy run, each against an independent fixture). **Exact execution
count remains unresolved** - not claimed otherwise. **Provider-side financial confirmation was not
independently checked against the OpenAI dashboard by the user during this remediation** - this
report does not claim that confirmation happened.

## 3. Root cause

`scripts/phase18_9_controlled_batch_runner.py`'s original `_cumulative_cost_since_run_start` - a
stateful "delta since last call" cost query whose first call summed the entire historical
`ai_executions` table (4,632 rows, ~$6.82) as an implicit baseline, making every subsequent
"spent this run" calculation deeply negative and the budget check structurally incapable of ever
refusing a task. Fixed (already, in commit `85fa828`) with `_cost_spent_since(session,
run_started_at)` - a single, stateless `SUM(cost) WHERE created_at >= run_started_at` query.

## 4. Why the original poison pill alone was insufficient

The original fix added a per-test `_PoisonPillCapabilityRegistry` injected via the
`capability_registry` parameter - but this depended on **every individual test remembering to
inject it**. That discipline had already failed once (the incident itself). Phase 18.9-R's own M1
audit (`docs/phase18_9r_test_provider_path_audit.md`) found this was the **only** structurally
real-provider-reachable path in the entire suite, but "the only test that does this remembers to
protect itself" is not a suite-wide guarantee - a single new test, or a single edit removing the
injection, could reintroduce the exact same incident. Phase 18.9-R replaces "remember to opt in"
with three barriers active automatically, for every test, without any opt-in required.

## 5. All discovered real-provider-reachable paths

Full detail: `docs/phase18_9r_test_provider_path_audit.md`. Summary: of every
`assemble_ai_integration_layer()`/`OpenAIAdapter`/`httpx.AsyncClient` construction site in the test
suite, **exactly one** class was `REAL_PROVIDER_REACHABLE` -
`scripts/phase18_9_controlled_batch_runner.py` (and, by the same reused function, `scripts/
run_content_generation.py`) when driven with `dry_run=False` and no fake registry injected. Every
other site was already `SAFE_FAKE` or `SAFE_BLOCKED`. Zero `UNKNOWN` classifications remained open.

## 6. Redis shared-state finding

`tests/conftest.py::redis_client` connected directly to `settings.redis_url` - the same real,
production Redis instance `automation_worker`/`backend` use, isolated only by a per-test
unique-namespace *convention*, never structurally. `tests/test_api_cost_optimization_checklist.py::
test_ledger_namespace_is_utc_calendar_date_so_a_new_day_starts_empty` violated that convention
(by necessity - its own purpose requires testing the real calendar-date namespace), writing real
cost math (via a fake, no-network `CapabilityCall`) into the real `phase7:cost_ledger:2026-08-05:
research` key, and its `finally` block only deleted the *global* key, leaking the *capability-
specific* key indefinitely across every full-suite run on the same date. This fully explains the
separate `research` +$0.007000 increase found during incident review (exact decimal reproduction:
`1000/1e6*$1.00 + 1000/1e6*$6.00 = $0.007000`) - confirmed **unrelated** to the paid-call incident,
zero real provider calls involved.

## 7. Database isolation finding

`tests/conftest.py::db_session`/`_test_engine` connect to the same real `ai_newsroom` database
(`current_database()` confirmed directly) - isolated via a real, well-established SAVEPOINT-based
rollback, not a separate database. **This was never the actual gap** - proven directly: even during
the real incident, `ai_executions`/`editorial_tasks`/`news_events` row counts never showed any
permanent change attributable to it (the real damage was entirely in Redis). Full reasoning and the
one honest correction to the brief's own assumed shape (no separate test database exists, and
building one was judged disproportionate to this incident's actual cause):
`docs/phase18_9r_postgres_isolation_audit.md`.

## 8. Barriers implemented

Three independent barriers, all installed at `tests/conftest.py` module-import time (before any
test or fixture runs, and before `core.config.get_settings()`'s own `@lru_cache` construction can
read the real `.env`):

1. **Barrier 1 - provider construction poison pill.** `OpenAIAdapter.__init__` patched globally:
   raises `RealProviderConstructionBlockedError` when `client is None` (real construction) *unless*
   the credential's key matches an already-established, pre-existing SAFE_FAKE test-key pattern
   (contains `"test"`/`"fake"`, and is not itself the Barrier 2 sentinel) - refined after an initial,
   too-broad version broke 6 pre-existing, already-safe tests (§14).
2. **Barrier 2 - credential isolation.** `os.environ["OPENAI_API_KEY"]` set to a clearly-invalid
   sentinel (`test-disabled-no-real-provider-access`) as the literal first executable lines of
   `conftest.py`, before any import that could read the real `.env`. Real `.env` file on disk
   confirmed untouched; running Docker containers confirmed unaffected (each reads its own
   `env_file: .env` once, at container start, entirely outside this process).
3. **Barrier 3 - network egress denial, below the application/provider layer.** `httpx.AsyncClient.
   send`/`httpx.Client.send` patched globally: any request whose client is not already routed
   through `httpx.MockTransport` and whose target host is not `localhost`/`127.0.0.1`/`::1` raises
   `NetworkEgressBlockedTestError` before any real network I/O occurs.

Plus, supporting M5/M6: a dedicated, isolated Redis test-database index (15, vs. production's 0),
and the leaking checklist test fixed (fake, controlled date instead of the real calendar date;
both the global and capability-specific keys deleted in `finally`).

## 9. Tests proving each barrier

`tests/test_phase18_9r_isolation_barriers.py` - 22 tests, all passing, organized exactly by the
brief's own required categories: Automatic protection (4), Credential isolation (6), Network
isolation (5), Redis isolation (3), Database isolation (3), Secret safety (2, incl. one covering
network-barrier messages specifically). Zero real OpenAI calls are made or attempted anywhere in
this file - every test proves a barrier fires *before* any request could be constructed, never by
actually attempting a real provider request (per instruction).

## 10. Full suite result

`python -m pytest -q`, run start-to-finish under all three barriers active:

**2,490 collected, 2,461 passed, 29 failed** (1,641.83s / 27m21s), started 2026-08-05 15:20 UTC,
ended 2026-08-05 15:48 UTC (~15:20→15:48).

## 11. Exact failure-set comparison

All 29 failures are an **exact subset** of Phase 18.8's own established 31-failure baseline (8
`test_capability_executor.py`, 1 `test_content_generation_integration.py`, 2 `test_content_worker_
cycle.py`, 1 `test_content_worker_cycle_image_preview.py`, 1 `test_editorial_inbox_service.py`, 2
`test_editorial_scoring.py`, 2 `test_fact_safety.py`, 1 `test_news_handler.py`, 1 `test_phase10_
workflow_integration.py`, 7 `test_phase18_db_integration.py`, 3 `test_phase18_meme_pipeline_
offline_e2e.py`) - **zero new failures, by exact test node ID, not merely by count.** The 2
missing-from-this-run failures (`test_analysis_worker_main.py`/`test_content_worker_main.py`'s own
`test_cycle_level_infrastructure_failure_logs_and_waits_for_next_interval`) are the same test
already documented as genuinely timing-flaky since Phase 18's own final acceptance - passed this
run, consistent with non-determinism, not a fix (neither file was touched by this remediation).

`ruff check` on all 4 changed test files: all checks passed. `mypy --ignore-missing-imports` on all
4 (checked individually - a `tests.conftest` vs `conftest` module-name collision occurs only when
checking multiple files under `tests/` together in one mypy invocation, a benign tooling quirk, not
a real issue): no issues found in any file.

## 12. Production ledger before/after

| Key | Before Stage 8 | After Stage 8 |
|---|---|---|
| `phase7:cost_ledger:2026-08-05:research` | 0.050028 | 0.050028 |
| `phase7:cost_ledger:2026-08-05:intelligence` | 0.002432 | 0.002432 |
| `phase7:cost_ledger:2026-08-05:engagement` | 0.00246 | 0.00246 |
| `phase7:cost_ledger:2026-08-05:scoring` | 0.000846 | 0.000846 |

**Byte-for-byte identical** - checked before and after every one of the 8 staged verification runs
(M8 stages 2-8), not only once. Zero drift at any point during this entire remediation's own
testing.

## 13. Production database before/after

| Table | Before Stage 8 | After Stage 8 | Changed |
|---|---|---|---|
| `news_events` | 13,845 | 13,861 | Yes - `automation_worker`'s own ordinary, separately-authorized (Phase 18.8) collection activity, unrelated to any test |
| `ai_executions` | 4,632 | 4,632 | **No** - the one table only a real paid execution could grow |
| `content_drafts` | 284 | 284 | **No** - same reasoning |
| `editorial_tasks` | 14,381 | 14,421 | Yes - `automation_worker`'s own triage step creating tasks for newly-collected events, same as `news_events`' growth |

## 14. Secrets review

- No real API key, bot token, database password, Redis credential, or authorization header was
  printed, logged, or included in any file this remediation created.
- `docker compose config` was never run.
- `.env` was never read for its secret values beyond the one, explicitly-scoped, non-secret-value
  check confirming `OPENAI_API_KEY=` line still exists and does not contain the sentinel (proving
  the file itself was never edited) - the real value was never printed.
- Barrier failure messages were explicitly tested to contain neither the sentinel nor any
  `"sk-"`-shaped value, nor an `Authorization` header value (§9's Secret safety category).
- One real design correction, disclosed rather than hidden: an initial version of Barrier 1 was
  too broad and broke 6 pre-existing tests that legitimately construct a real (never-called)
  `AsyncOpenAI` client using this codebase's own long-established fake-key conventions
  (`"sk-test-not-a-real-key-0000000000"`, `"sk-test-fake-key-0123456789"`). Fixed by recognizing
  those specific, pre-existing patterns as safe (§8) - the real Barrier-2 sentinel itself remains
  excluded from that allowance, so the incident's own exact shape is still always blocked.

## 15. Remaining limitations / is the safety loop closed?

**Yes, for this remediation's own explicit scope.** All Phase 18.9-R acceptance criteria are met:
≥2 independent barriers active for every pytest run (all 3 are), one operates below the
application/provider layer (Barrier 3), pytest cannot access the real key, tests cannot reach real
OpenAI endpoints, shared production Redis ledgers are untouched, production Postgres business
records are untouched, the leaking checklist test is fixed, the full suite completed with zero new
failures matched by exact identity, zero additional paid calls occurred (ledger proof, §12), zero
Telegram/image/publication side effects occurred (no code path in this remediation touches any of
those - confirmed by the same M1 audit), no secret was exposed.

**Explicitly not resolved by this remediation, disclosed rather than implied fixed:**
- The exact number of real unauthorized executions during the original incident (1 confirmed
  minimum, 2 suspected) remains unresolved - no new evidence-gathering was possible (the original
  task/event IDs were never recoverable, `docs/phase18_9_incident_snapshot.md` §4).
- Provider-side financial confirmation against the real OpenAI usage dashboard has not happened
  from this environment - only the user can do this independently.
- Phase 18.9's own original question - whether to authorize a controlled paid run - remains
  entirely separate from this remediation and is **not** being asked again in this report.

**This report does not request paid-run authorization and does not resume Phase 18.9's own M7-M11
(the actual controlled paid run).** That remains a fully separate decision, pending independent
review of this remediation first, per instruction.
