# Phase 12 — M5 Final Automated Verification Report

## Exact files changed/created

**Existing files, narrow edits only** (5):
- `core/config.py` — added `news_collection_enabled: bool = False`,
  `news_collection_interval_seconds: int = Field(default=1800, gt=0)`.
- `docker-compose.yml` — added the `automation_worker` service (no Redis dependency).
- `pyproject.toml` — added `"worker"` to the `packages` list.
- `services/collector.py` — added the `SourceAdapterResolver` `Protocol` and three keyword-only
  defaulted parameters to `run_collection_cycle()`; retyped `_load_active_sources()`/
  `_process_source()`'s `registry` parameter. No other line changed.
- `tests/test_settings_phase7.py` — added 6 tests for the two new `Settings` fields.

**New files** (3 production, 4 test):
- `worker/__init__.py`, `worker/main.py`, `worker/cycle.py`
- `tests/fakes/fake_source_adapter.py`, `tests/test_automation_integration.py`,
  `tests/test_worker_cycle.py`, `tests/test_worker_main.py`

**Total: exactly 12 files** — matches the frozen Contract/Plan file scope precisely (§3 of the
Implementation Plan), independently re-confirmed via `git diff --name-only` / `git status --short`
in this milestone (see Scope Audit below). No file outside this list was created or modified.
`services/adapter_registry.py`, `services/adapter_keys.py`, `Dockerfile` — all confirmed untouched.

## Milestone results

| Milestone | Result |
|---|---|
| M0 | Repository matched every frozen Contract/Plan assumption; no drift. |
| M1 | Collector DI seam implemented; 7 focused tests pass; one incident found and fixed during implementation (see below). |
| M2 | `worker/cycle.py` implemented; 6 focused tests pass. |
| M3 | `worker/main.py`, config, packaging, Docker implemented; 8+6 focused tests pass; one security incident occurred and was contained (see below). |
| M4 | Offline integration proof implemented; 3 additional focused tests pass (10 total in the file). |
| M5 | Full regression + all gates — this report. |

## Incidents (both resolved before this milestone)

1. **M1 — data-scoping bug in the first `FakeAdapterRegistry` design**: it resolved every active
   `NewsSource` in the shared database unconditionally, causing the collector to process all 83 real
   dev sources and create 492 polluting `NewsEvent` rows during the first (failing) test run.
   Immediately investigated, confirmed all 492 rows were created within a 1-minute window matching
   the test run and referenced by zero `EditorialTask` rows, deleted by exact `title` match, and
   confirmed zero remained. Fixed by scoping `FakeAdapterRegistry` to an explicit
   `resolvable_source_ids` set. Documented in `docs/phase12_m1_collector_di_report.md`.
2. **M3 — Telegram credential exposure via `docker compose config`**: this command resolves and
   prints every service's interpolated `.env` environment, not just the one being validated, and
   printed real Telegram credentials into tool output. Implementation was paused; full security
   verification performed (`docs/security_incident_telegram_credentials_rotation_verification.md`)
   confirmed no secret reached any repository file, `.env` remained gitignored/untracked, nothing was
   staged. The operator confirmed both the bot token and Telethon session string were rotated. Final
   verdict: **SECURITY INCIDENT CONTAINED**. All further Docker validation used only
   `docker compose config --quiet`/`--services`, which do not interpolate or print secret values.

Neither incident involved a pre-existing collector/repository defect outside Phase 12's own new code
— both were bugs/oversights in this milestone's own new implementation or verification process, and
both were corrected within the already-authorized scope.

## Focused test counts

- Collector DI (`tests/test_automation_integration.py`, M1 portion): 7
- Worker cycle (`tests/test_worker_cycle.py`): 6
- Worker runtime (`tests/test_worker_main.py`): 8
- Settings (`tests/test_settings_phase7.py`, Phase 12 portion): 6 new (17 total in file, 11
  pre-existing unaffected)
- Offline automation integration (`tests/test_automation_integration.py`, M4 portion): 3
- **Phase 12 total: 30 new tests, all passing.**

## Full suite

`pytest` (whole repository): **816 passed**, 0 failed, 0 errors, 186.65s. No regression in any
pre-existing test.

## Lint / types / architecture

- `ruff check .` (whole repository): **all checks passed**.
- `mypy worker/__init__.py worker/main.py worker/cycle.py services/collector.py core/config.py`:
  **1 pre-existing, unrelated warning** (`telethon.errors` missing stubs, `services/collector.py:19`
  — independently confirmed present at `HEAD` before any Phase 12 change; not introduced by this
  work, not fixed, per the frozen rule that pre-existing defects outside the narrow DI scope are not
  autonomously modified).
- `mypy tests/test_worker_cycle.py tests/test_worker_main.py tests/test_settings_phase7.py
  tests/test_automation_integration.py`: **clean, no issues found**.
- `mypy tests/fakes/fake_source_adapter.py` (checked in isolation to avoid a benign
  double-module-path mypy artifact when passed alongside files that import it transitively):
  **clean, no issues found**.
- `python -m scripts.validate_architecture`: **clean — 0 forbidden-dependency violations**.

## Security / secret hygiene

- `git ls-files .env`: empty — **`.env` not tracked**.
- `git check-ignore -q .env`: **`.env` is ignored**.
- `git diff --cached --name-only`: empty — **nothing staged**.
- No secret value was printed at any point during M5 verification (all Docker checks used
  `docker compose config --quiet`/`--services`, per the M3 incident's own safe-method finding).

## DB pollution result

Direct query for any `NewsSource` row matching `phase12-integration-test-%`: **zero rows**. Every
Phase 12 test's own explicit, FK-safe, `try/finally`-guaranteed cleanup (`EditorialTask` →
`NewsEvent` → `NewsSource`) left the shared database exactly as it found it.

## Migration audit

No new file under `alembic/versions/`. No migration exists anywhere in the diff.

## Scope audit

`git diff --name-only` (tracked, modified): exactly `core/config.py`, `docker-compose.yml`,
`pyproject.toml`, `services/collector.py`, `tests/test_settings_phase7.py` — the 5 authorized
narrow-edit files, no more, no fewer. `git status --short` (untracked, new): exactly
`tests/fakes/fake_source_adapter.py`, `tests/test_automation_integration.py`,
`tests/test_worker_cycle.py`, `tests/test_worker_main.py`, `worker/` — the 7 authorized new files
(plus this session's own `docs/phase12_m*.md`/incident-report documentation, explicitly permitted).
**No unauthorized production/runtime file was touched.**

## Explicit proof: `NEWS_ANALYSIS` is never executed

- Mechanical AST check (`tests/test_worker_cycle.py::test_worker_cycle_imports_no_downstream_execution_module`):
  `worker/cycle.py` imports none of `workflows.runner`, `capabilities.executor`, any
  `capabilities.*`, `scripts.run_content_generation`.
- Grep audit (this milestone, M5 gate): zero matches for the same forbidden set anywhere under
  `worker/`.
- Integration-level, mechanical zero-rows proof
  (`tests/test_automation_integration.py::test_full_offline_chain_creates_events_and_editorial_tasks_with_no_downstream_execution`):
  after a real collection + real triage pass creating 2 `EditorialTask(CREATED)` rows, zero
  `AIExecution` rows exist referencing them.

## Explicit proof: no `ContentDraft`

Same integration test as above: zero `ContentDraft` rows exist referencing this test's own
`EditorialTask` ids after a full collection + triage pass.

## Explicit proof: no public publishing

Grep audit (this milestone): zero matches for `aiogram`/`bot.loader`/`bot.handlers` anywhere under
`worker/`. `worker/main.py`/`worker/cycle.py` import only `core.*`, `services.collector`,
`services.triage_orchestrator`, and the Python standard library.

## Deviations from the frozen Contract/Plan

None in the final, corrected state. Two implementation-time incidents occurred (both documented
above and in their own milestone reports) — both were caught, contained, and corrected without
requiring any change to the frozen Contract or approved Plan, and without expanding authorized file
scope.

## Final Verdict

PHASE 12 M0–M5 COMPLETE — READY FOR M6 HUMAN AUTHORIZATION
