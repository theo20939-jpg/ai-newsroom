# Phase 13 — M4 Milestone Report: Analysis Worker Runtime / Config / Docker

## Status: GREEN

## Files changed (within authorized §4 scope)

**Production (new)**: `worker/analysis_main.py`
**Production (modified, narrow)**: `docker-compose.yml` (one new service); `core/config.py`'s 4
new fields were added during M3 for mypy correctness (§ M3's own report), not repeated here.
**Tests (new)**: `tests/test_analysis_worker_main.py`
**Tests (modified)**: `tests/test_settings_phase7.py` (4 new field tests + 1 non-decision proof)

## Implementation notes

`worker/analysis_main.py` mirrors `worker/main.py`'s enabled/disabled/signal-handling shape
exactly. The AI integration layer is assembled via `assemble_ai_integration_layer(settings,
prompt_repository)` with **no** `redis_client` kwarg — matching the one real, existing production
caller (`scripts/run_content_generation.py:96`) exactly, not a new pattern.

**No `pyproject.toml` edit, no `Dockerfile` edit** — independently re-verified this session
(Final Gate Audit's own Gate 12 findings re-confirmed unchanged): `Dockerfile`'s `COPY . .`
already copies `prompts/`; `pyproject.toml`'s `packages` list already includes `worker`.

## Docker validation (secret-safe only, per the mandatory rule)

`docker compose config --quiet` — exit 0, no output (valid). `docker compose config --services`
— lists `postgres, automation_worker, redis, backend, news_analysis_worker`, confirming the new
service registers correctly. Plain `docker compose config` was never run.

## Settings

`news_analysis_enabled` (default `False`), `news_analysis_poll_interval_seconds` (default `300`,
`gt=0`), `news_analysis_batch_size` (default `5`, `gt=0`), `news_analysis_freshness_cutoff_hours`
(default `48.0`, `gt=0`) — all four match the Contract/Plan exactly. No `max_daily_ai_cost`
field was added for Phase 13; a test proves this explicitly, and further proves neither
`worker/analysis_cycle.py` nor `worker/analysis_main.py` references `CostTracker`/`BudgetGuard`/
`max_daily_ai_cost` anywhere. (A pre-existing, general `max_daily_ai_cost` field, unrelated to
Phase 13 and tied to `BudgetGuard`'s own already-established, already-non-functional cost-ledger
design per the Decision Resolution's own documented finding, already existed in `Settings` before
this Plan — the binding decision was never to add a *new*, Phase-13-specific one, which is what
this milestone's own test correctly proves instead of its own, initially mis-worded first draft.)

## Default safety

Disabled by default (`news_analysis_enabled: bool = False`). While disabled, `main()` calls
`_run_disabled_idle()` before any AI-layer assembly — zero task query, zero AI/Redis/provider
call, `assemble_ai_integration_layer` proven `assert_not_called()` in the disabled-mode test. No
restart loop (`asyncio.Event().wait()` blocks indefinitely, cancellation-responsive).

## Validation run this milestone

- `pytest tests/test_analysis_worker_main.py` — **9 passed** (enabled loop + interval, ordinary
  exception survival, cancellation during cycle, cancellation during sleep, disabled mode
  touches nothing, disabled mode logs once, no bare/BaseException catch, starts without
  crashing, cycle-level infrastructure failure logs and continues — mirrors `tests/
  test_worker_main.py`'s own 8-test shape plus one Phase-13-specific addition for MINOR-2).
- `pytest tests/test_settings_phase7.py` — **29 passed** (25 pre-existing + 4 new field tests +
  1 non-decision proof, zero pre-existing test line modified).
- `ruff check` on all 3 M4-touched files — all checks passed.
- `mypy worker/analysis_main.py` — no issues found.
- No live provider call anywhere in this milestone's tests (`assemble_ai_integration_layer` is
  mocked at the module boundary in every test).

## Deviations from the Plan

None beyond the M3-report-documented config-field-timing shift (already disclosed there).

M4 complete. Continuing to M5.
