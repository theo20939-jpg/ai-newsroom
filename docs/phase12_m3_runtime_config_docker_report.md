# Phase 12 — M3 Runtime / Config / Docker Report

## Changes

**`worker/main.py`** (new) — `main()`: `setup_logging()`, registers `SIGTERM`/`SIGINT` handlers via
`loop.add_signal_handler(sig, task.cancel)` (narrow `except NotImplementedError` guard per signal,
required on this dev machine's Windows event loop — confirmed working, see Verification below), then
branches: `news_collection_enabled=False` → `_run_disabled_idle()` (logs once, waits on a never-set
`asyncio.Event()`, cancellation-responsive, zero DB/source access); otherwise →
`_run_enabled_loop()` (`while True: try: await run_automation_cycle() except Exception: log; await
asyncio.sleep(interval)`). `except Exception` only throughout — `asyncio.CancelledError` is never
caught except at the outermost `try/except asyncio.CancelledError: log; raise` in `main()` itself
(and identically inside `_run_disabled_idle()`), so it always propagates and triggers cleanup/exit.

**`core/config.py`** (existing, narrow edit) — added `news_collection_enabled: bool = False`,
`news_collection_interval_seconds: int = Field(default=1800, gt=0)`, exact names/defaults/validation
per Contract §11/§16.

**`pyproject.toml`** (existing, narrow edit) — added `"worker"` to the `packages` list.

**`docker-compose.yml`** (existing, narrow edit) — added the `automation_worker` service exactly per
Contract §15: `build: .` (reuses `backend`'s image), `command: ["python", "-m", "worker.main"]`,
`env_file: .env`, `environment: POSTGRES_HOST: postgres` only, `depends_on: postgres` only (no
Redis), `restart: unless-stopped`, no public port, no volumes (matching the Contract's own
snippet — no dev bind-mount, unlike `backend`).

**`tests/test_settings_phase7.py`** (existing, narrow edit) — 6 new tests for the two Settings
fields (default/override/validation).

**`tests/test_worker_main.py`** (new) — 8 tests.

## Incident during this milestone

Initial Docker validation used plain `docker compose config`, which resolves and prints every
service's interpolated `.env` environment — this exposed real Telegram credentials
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_SESSION_STRING`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`) in tool
output. Implementation was paused; a full security verification was performed
(`docs/security_incident_telegram_credentials_rotation_verification.md`) — confirmed no secret was
written to any repository file, `.env` remains gitignored/untracked, nothing was staged. The operator
confirmed the bot token and Telethon session string were both rotated. **Final verdict: SECURITY
INCIDENT CONTAINED — READY TO RESUME PHASE 12.** All further Docker validation in this milestone
used only `docker compose config --quiet` (validates everything, prints nothing on success) and
`docker compose config --services` (service names only) — neither interpolates or prints secret
values.

## Verification

- `pytest tests/test_worker_main.py tests/test_settings_phase7.py -v` — **25 passed** (8 worker/main
  tests: enabled loop runs cycles and respects interval, survives an ordinary `Exception` and
  continues, cancellation during cycle execution propagates, cancellation during interval sleep
  propagates, disabled mode runs zero cycles and touches nothing, disabled mode logs its idle state
  exactly once, static proof of no bare/`BaseException` catch in either worker module, `main()`
  starts without crashing on this platform — proving the `NotImplementedError` guard works in
  practice, not just in theory; plus 17 settings tests, no regression in the 11 pre-existing ones).
- `ruff check worker/ core/config.py tests/test_worker_main.py tests/test_settings_phase7.py` — **all
  checks passed**.
- `mypy worker/main.py worker/cycle.py core/config.py tests/test_worker_main.py
  tests/test_settings_phase7.py` — **clean, no issues found**.
- `docker compose config --quiet` — **valid, no interpolated content printed**.
- `docker compose config --services` — lists `postgres`, `automation_worker`, `redis`, `backend`.

No deviation from the frozen Contract/Plan design. No pre-existing defect encountered in this
milestone's own files.

**M3 complete. Proceeding to M4.**
