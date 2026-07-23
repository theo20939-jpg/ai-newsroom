# Phase 12 — Fresh News Automation Implementation Plan

Planning only. No production code, test, migration, or Contract file was modified to produce this
document. No worker was started. No external API/network call was made.

## 1. Status and Authority

**Status: Implementation Plan, pending Planning Audit.** The Architecture Contract
(`docs/phase12_fresh_news_automation_architecture_contract.md`, Revision 3, "PHASE 12 CONTRACT
REVISION 3 — READY FOR RE-AUDIT") was approved by
`docs/phase12_fresh_news_automation_contract_final_reaudit.md` ("PHASE 12 CONTRACT APPROVED —
READINESS SCORE: 9/10", CRITICAL=0, MAJOR=0). The Contract is frozen and authoritative; this plan
reinterprets nothing it decided and adds no new architecture. Every implementation-level choice
below that the Contract left open (exact internal naming inside new files, exact signal-handling
mechanism, exact dataclass field layout) is disclosed explicitly as a Planning-level decision, not
presented as if the Contract already froze it.

## 2. Baseline Verification (Step 1)

Independently re-read current source this session, not trusted from prior reports:

- `git rev-parse HEAD` = `228c874b83bb7565629f3c9c5099302925336d59` — the Phase 11 final-closure
  commit, identical to the commit every Phase 12 governance document has cited throughout.
- `git status --short` — only untracked `docs/*.md` files (all Phase 9/9.5/10/11/12 governance
  documents accumulated this session, including the Contract itself, both audits, and this plan's
  own eventual file). **Zero staged or modified production/test/migration file.**
- `worker/` does not exist anywhere in the repository (confirmed via directory check) — Phase 12
  implementation has not started.
- Re-read `services/collector.py`, `services/adapter_registry.py`, `services/adapter_keys.py`,
  `services/triage_orchestrator.py`, `core/config.py`, `docker-compose.yml`, `pyproject.toml`,
  `Dockerfile`, `database/session.py`, `database/models/news_event.py`,
  `database/models/editorial_task.py`, `tests/test_settings_phase7.py`, `scripts/run_collector.py`,
  `scripts/run_triage.py`, `bot/main.py`, `schemas/raw_news_item.py`, `schemas/source_definition.py`,
  `tests/fakes/fake_gateway.py` — every fact the approved Contract cites (hardcoded
  `async_session_factory`/`load_source_pack`/`build_registry`; `AdapterRegistry.resolve()`'s
  dependency on `ADAPTER_KEY_TO_ADAPTER`; `run_triage_cycle`'s existing `session_factory` DI;
  `NewsEvent.hash` unique constraint; `EditorialTask.status` including `CREATED`; the
  `tests/test_settings_phase7.py` convention; no Redis import in the collector/triage path) is
  confirmed byte-for-byte accurate against current source. **No drift found.**

**M0 completion criterion met: repository state matches every frozen Contract assumption.**
Implementation Planning proceeds — no `PHASE 12 IMPLEMENTATION PLAN BLOCKED` condition exists.

## 3. Exact File Scope (Step 2)

Re-derived directly from Contract §22/§23 (not re-invented):

| File | Status | Purpose | Permitted change | Depends on | Risk | Verification |
|---|---|---|---|---|---|---|
| `worker/__init__.py` | NEW | Package marker | Docstring only, matching `bot/__init__.py` | none | Low | Import succeeds |
| `worker/cycle.py` | NEW | One-cycle orchestration | `run_automation_cycle()` + `AutomationCycleResult` dataclass | `services/collector.py`, `services/triage_orchestrator.py` | Low | M2 tests |
| `worker/main.py` | NEW | Process entry point, loop, shutdown, disabled-idle | `main()`, enabled-loop helper, signal wiring | `worker/cycle.py`, `core/config.py`, `core/logging.py` | Medium (cancellation correctness) | M3 tests |
| `core/config.py` | EXISTING, narrow | Two new `Settings` fields | Add `news_collection_enabled`, `news_collection_interval_seconds` only | none | Low | M3D tests |
| `docker-compose.yml` | EXISTING, narrow | New worker service | Add one service block, no Redis | none | Low | Manual `docker compose config` review |
| `pyproject.toml` | EXISTING, narrow | Package installability | Add `"worker"` to `packages` list | none | Low | `pip install .` / import check |
| `services/collector.py` | EXISTING, narrow | Testability seam | Add 3 keyword-only defaulted params, local `SourceAdapterResolver` Protocol, retype 2 internal params, typing-only imports — **nothing else** | `services/adapter_registry.py` (read-only), `services/source_registry.py` (read-only) | Medium (must not change behavior) | M1 tests |
| `tests/fakes/fake_source_adapter.py` | NEW (test) | Fake adapter + fake resolver | `FakeSourceAdapter(SourceAdapter)`, `FakeAdapterRegistry` (satisfies `SourceAdapterResolver`) | `integrations/sources/base.py`, `services/adapter_registry.py` (only for `AdapterResolution`) | Low | M1/M4 tests import it |
| `tests/test_worker_cycle.py` | NEW (test) | `worker/cycle.py` unit tests | Order, failure semantics, no-duplication proof | `worker.cycle` | Low | M2 |
| `tests/test_worker_main.py` | NEW (test) | `worker/main.py` unit tests | Loop, disabled idle, cancellation | `worker.main` | Low | M3 |
| `tests/test_automation_integration.py` | NEW (test) | Full offline chain | Fake seam → real collector → real triage → DB | `worker.cycle` or direct `services.*` calls | Medium (real DB fixture) | M4 |
| `tests/test_settings_phase7.py` | EXISTING, narrow (test) | Config tests | Add tests for the two new fields only | `core.config` | Low | M3D |

**Total: 3 new production files, 4 narrow existing-file edits, 5 test-file items (4 new + 1 narrow
edit).** No file outside this table is touched. `services/adapter_registry.py`,
`services/adapter_keys.py`, `Dockerfile`, and every file in Contract §23's frozen list remain
untouched — independently re-confirmed necessary/sufficient in §2 above (no Dockerfile change: `COPY
. .` + `pip install .` already installs whatever `pyproject.toml`'s `packages` list names).

## 4. Dependency Graph

```
M0 (baseline, no code)
  └─→ M1 (services/collector.py seam)
        └─→ M1 tests (tests/fakes/fake_source_adapter.py + collector-seam assertions)
              └─→ M2 (worker/cycle.py) ── depends on M1 only for the fake used in its own tests;
              │                            production path in M2 needs no M1 change to *call*
              │                            run_collection_cycle()/run_triage_cycle() with zero args
              └─→ M3D (core/config.py Settings) ── independent of M1/M2, can run in parallel
                    └─→ M3A–M3C (worker/main.py) ── depends on M2 (calls run_automation_cycle())
                                                      and M3D (reads settings.news_collection_enabled/
                                                      news_collection_interval_seconds)
                          └─→ M3E (pyproject.toml) ── depends on worker/ existing as a package
                                └─→ M3F (docker-compose.yml) ── depends on M3E (image must be able
                                                                  to import worker.main)
                                      └─→ M4 (offline integration) ── depends on M1 (fake seam) +
                                      │                                M2 (real cycle orchestration)
                                      └─→ M5 (regression/readiness gate) ── depends on all of the above
                                            └─→ M6 (manual live acceptance) ── HUMAN AUTHORIZATION ONLY
```

`M3D` (Settings) has no code dependency on `M1`/`M2` and may be implemented at any point before
`M3A–M3C` needs it — noted so an implementer is not blocked waiting on the collector seam to start
config work.

## 5. M0 — Repository Preparation

No production code changes. Checklist (all independently re-verified in §2, restated here as the
milestone's own completion gate):

1. `run_collection_cycle()` current signature: `async def run_collection_cycle() -> CollectionReport`
   (`services/collector.py:44`) — zero parameters, confirmed.
2. Hardcoded session factory: `from database.session import async_session_factory`
   (`services/collector.py:21`), used at line 57.
3. Hardcoded `load_source_pack()`: imported at line 26, called with zero args at line 54.
4. `build_registry`/`AdapterRegistry` path: `services/adapter_registry.py:98-129` (`build_registry`),
   `:64-95` (`AdapterRegistry`, `.resolve()`).
5. `ADAPTER_KEY_TO_ADAPTER`: `services/adapter_keys.py:64-66`, five real adapter singletons.
6. `run_triage_cycle()` injectable `session_factory`: confirmed at
   `services/triage_orchestrator.py:222-223`, already defaulted to `async_session_factory`.
7. Collector dedup: `services/collector.py:145-168` — `_compute_hash()` +
   `deduplication.is_duplicate()` + `IntegrityError` catch inside `session.begin_nested()`.
8. Triage duplicate-active-task behavior: `services/triage_orchestrator.py:199-209`, catches
   `DuplicateActiveTaskError`, non-failure no-op.
9. Settings conventions: `core/config.py` — `Field(gt=0)` pattern
   (`stale_processing_threshold_seconds`), `opt-in-by-default` bool pattern
   (`verify_capabilities_at_boot`).
10. `pyproject.toml` explicit package inclusion: `[tool.hatch.build.targets.wheel] packages = [...]`
    (line 36) — confirmed `"worker"` is not yet present.
11. Docker Compose process conventions: `backend` service (`docker-compose.yml:2-20`) — `build: .`,
    `env_file: .env`, `restart: unless-stopped`, `depends_on` with `condition: service_healthy`.
12. No current `worker` package — confirmed via directory check, §2.
13. No hidden `WorkflowRunner` invocation in the collection/triage path — confirmed via import list
    of `services/collector.py`, `services/triage_orchestrator.py`, `services/workflow_service.py`
    (none import `workflows.runner` or `capabilities.executor`).

**M0 completion criterion met.** Proceed to M1.

## 6. M1 — Collector Dependency-Injection Seam

**Target**: `services/collector.py` only (plus the read-only cross-reference to
`services/adapter_registry.py` for the `AdapterResolution` import — no edit to that file).

### 6.1 Exact planned change

1. Add imports (typing-only, no new dependency): `from typing import Protocol`, `from
   collections.abc import Callable` (replacing/augmenting the existing plain imports),
   `from sqlalchemy.ext.asyncio import async_sessionmaker` (added alongside the existing
   `AsyncSession` import from the same module), `from services.source_registry import
   SourceRegistryReport` (alongside the existing `load_source_pack` import), `from
   services.adapter_registry import AdapterResolution` (alongside the existing `AdapterRegistry,
   build_registry` import).
2. Define, directly below the existing imports and above `CollectionReport`:
   ```python
   class SourceAdapterResolver(Protocol):
       def resolve(self, source: NewsSource) -> AdapterResolution | None: ...
   ```
3. Change `run_collection_cycle()`'s signature from `async def run_collection_cycle() ->
   CollectionReport:` to:
   ```python
   async def run_collection_cycle(
       *,
       session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
       source_pack_loader: Callable[[], tuple[list[SourceDefinition], SourceRegistryReport]] = load_source_pack,
       adapter_resolver_factory: Callable[[list[SourceDefinition]], SourceAdapterResolver] = build_registry,
   ) -> CollectionReport:
   ```
   (`SourceDefinition` needs importing too — currently not imported in `services/collector.py`;
   add `from schemas.source_definition import SourceDefinition`, used only in the type hint.)
4. Inside the function body, replace `definitions, _registry_report = load_source_pack()` with
   `definitions, _registry_report = source_pack_loader()`; replace `registry =
   build_registry(definitions)` with `registry = adapter_resolver_factory(definitions)`; replace
   `async with async_session_factory() as session:` with `async with session_factory() as session:`.
5. Change `_load_active_sources(session: AsyncSession, registry: AdapterRegistry)` and
   `_process_source(session: AsyncSession, source: NewsSource, registry: AdapterRegistry, report:
   CollectionReport)`'s `registry` parameter type hint from `AdapterRegistry` to
   `SourceAdapterResolver` — **no other change to either function's body.**

No other line changes. `_fetch_with_retry`, `_process_item`, `_compute_hash`, the outer
`try/except Exception`, and every log message are byte-for-byte unchanged.

### 6.2 Default production path (must be provably unchanged)

```
run_collection_cycle()                            # zero args, called from worker/cycle.py and
                                                    # scripts/run_collector.py exactly as today
  → session_factory=async_session_factory (default)
  → source_pack_loader=load_source_pack (default)  → config/newsroom_sources_v1 on disk
  → adapter_resolver_factory=build_registry (default) → real AdapterRegistry(url_index, definition_index)
       → registry.resolve(source) → ADAPTER_KEY_TO_ADAPTER.get(adapter_key) → real adapter singleton
  → real adapter.fetch(source, context) → real network call, exactly as before this change
```
Every step is identical in object identity and behavior to pre-Phase-12 `services/collector.py` —
the `Protocol` retype is erased at runtime (Python does not enforce type hints), so `build_registry`
returning a real `AdapterRegistry` is unaffected.

### 6.3 Test (fake) path

```
run_collection_cycle(
    session_factory=independent_session_factory(),  # §12.0 — this repo's own real-Postgres,
                                                      # factory-shaped test helper; NOT a
                                                      # separate test database (none exists)
    source_pack_loader=lambda: ([controlled_source_definition], SourceRegistryReport()),
    adapter_resolver_factory=lambda defs: FakeAdapterRegistry(fake_adapter),
)
  → FakeAdapterRegistry.resolve(source) → AdapterResolution(adapter=FakeSourceAdapter(), definition=...)
  → FakeSourceAdapter.fetch(source, context) → canned RawNewsItem list, zero network I/O
  → real _process_item() → real dedup → real, committed NewsEvent row in settings.database_url,
    owned by the test (§12.0's uniqueness/cleanup discipline applies here identically)
```
`FakeAdapterRegistry` never imports `services.adapter_keys` and never constructs a real
`AdapterRegistry` — confirmed structurally sufficient in the final re-audit (§5-§6 of
`phase12_fresh_news_automation_contract_final_reaudit.md`).

### 6.4 Explicitly not changed

Collector business logic, dedup, persistence, failure semantics, retry behavior, source behavior,
`services/adapter_registry.py`, `services/adapter_keys.py` — all confirmed untouched by this plan.

## 7. M1 Tests

`tests/fakes/fake_source_adapter.py` (new):
```python
class FakeSourceAdapter(SourceAdapter):
    def __init__(self, items: list[RawNewsItem] | None = None, error: Exception | None = None) -> None:
        self._items = items or []
        self._error = error

    async def fetch(self, source: NewsSource, context: SourceFetchContext) -> list[RawNewsItem]:
        if self._error is not None:
            raise self._error
        return self._items


class FakeAdapterRegistry:
    def __init__(self, adapter: SourceAdapter, definition: SourceDefinition | None = None) -> None:
        self._adapter = adapter
        self._definition = definition

    def resolve(self, source: NewsSource) -> AdapterResolution | None:
        return AdapterResolution(adapter=self._adapter, definition=self._definition)
```
(Mirrors `tests/fakes/fake_gateway.py`'s own constructor-configured-response convention — no new
fakes pattern invented.)

Tests planned (in `tests/test_worker_cycle.py` or a dedicated `tests/test_collector_di.py` — exact
file left to implementer discretion per Contract §22's own "not frozen more precisely" allowance;
recommend collocating with `tests/test_automation_integration.py` since both concern the same seam):

1. `run_collection_cycle()` called with zero args still uses `async_session_factory`/
   `load_source_pack`/`build_registry` (asserted via `inspect.signature(run_collection_cycle)`
   default values, not by exercising a real DB — fast, no I/O).
2. Injected `session_factory` is used: pass `independent_session_factory()` (§12.0 — this project's
   own real-Postgres, factory-shaped test helper, imported from
   `tests/test_triage_orchestrator_claims.py`; **not** a separate test database, since none exists —
   it is `settings.database_url`, the same connection string the real application uses), bound to a
   uniquely-named test `NewsSource`; confirm the resulting `NewsEvent` is identifiable by its
   test-owned `source_id` and is removed by the test's own explicit, failure-safe cleanup (§12.0).
3. Injected `source_pack_loader` is used: pass a fake loader returning a distinct, recognizable
   `SourceDefinition`; assert the resulting `NewsEvent.source_id`/content matches the fake source,
   not any real pack entry.
4. Injected `adapter_resolver_factory` is used: pass `FakeAdapterRegistry`; assert
   `FakeSourceAdapter.fetch()` was called (a call-count/received-args assertion on the fake) and
   that a `NewsEvent` was persisted from its canned items.
5. Fake resolver bypasses real `AdapterRegistry` construction: assert (via `unittest.mock.patch` or
   an import-time flag) that `services.adapter_registry.build_registry` and
   `services.adapter_keys.ADAPTER_KEY_TO_ADAPTER` are never called/accessed during a fake-seam run.
6. Fake adapter path never requires `ADAPTER_KEY_TO_ADAPTER`: same as #5, stated as its own explicit
   assertion per the final re-audit's specific finding.
7. No external network: `FakeSourceAdapter` never imports `httpx`/`telethon`/`feedparser`; a
   network-block fixture (e.g. monkeypatching `socket.socket` to raise) around this specific test
   proves no accidental fallback to a real adapter.

## 8. M2 — Worker Cycle Orchestration

**Target**: `worker/cycle.py` (new).

### 8.1 Design

```python
"""One automation cycle: collection, then triage. No business logic of its own."""
from dataclasses import dataclass
from datetime import datetime, timezone

from services.collector import CollectionReport, run_collection_cycle
from services.triage_orchestrator import TriageCycleReport, run_triage_cycle


@dataclass
class AutomationCycleResult:
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    collection: CollectionReport
    triage: TriageCycleReport


async def run_automation_cycle() -> AutomationCycleResult:
    started_at = datetime.now(timezone.utc)
    collection_report = await run_collection_cycle()
    triage_report = await run_triage_cycle()
    finished_at = datetime.now(timezone.utc)
    result = AutomationCycleResult(
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=(finished_at - started_at).total_seconds(),
        collection=collection_report,
        triage=triage_report,
    )
    logger.info(
        "automation_cycle_finished",
        extra={
            "duration_seconds": result.duration_seconds,
            "sources_processed": collection_report.sources_processed,
            "sources_failed": collection_report.sources_failed,
            "events_created": collection_report.events_created,
            "duplicates_skipped": collection_report.duplicates_skipped,
            "events_claimed": triage_report.events_claimed,
            "events_recovered": triage_report.events_recovered,
            "tasks_created": triage_report.tasks_created,
        },
    )
    return result
```

`run_collection_cycle`/`run_triage_cycle` are imported as module-level names specifically so tests
can monkeypatch `worker.cycle.run_collection_cycle`/`worker.cycle.run_triage_cycle` directly —
Contract §24's own cited convention ("verifiable by patching both names at the `worker.cycle` module
boundary... mirroring Phase 11's own proven handler-test-double convention"). **No additional
injected `collection_runner`/`triage_runner` parameter is added to `run_automation_cycle()`** —
module-boundary patching is sufficient and matches the Contract's own frozen sketch (§6:
`run_automation_cycle() -> AutomationCycleResult`, no parameters). This is the smallest option
consistent with the Contract, and avoids inventing a second DI mechanism alongside M1's.

`AutomationCycleResult`'s field set is a Planning-level choice (the Contract's §18 only requires
"cycle start/end timestamps and duration... plus both reports' fields," not an exact shape) — the
above satisfies that requirement exhaustively using only fields `CollectionReport`/
`TriageCycleReport` already expose, inventing no new metric.

### 8.2 Ordering invariant

Collection `await`s to completion before triage starts — enforced structurally by sequential
`await` statements in a single coroutine, not by any lock (no concurrency is introduced, matching
Contract §6/§12).

### 8.3 Failure semantics (exact, matching Contract §13)

`run_automation_cycle()` itself does **not** catch any exception — collection's own internal
`try/except Exception` (`services/collector.py`, unmodified) already guarantees it never raises;
triage's own uncaught top-level exception (if any) propagates out of `run_automation_cycle()`
unmodified. **The `except Exception` cycle-level recovery handler belongs to `worker/main.py`
(§9.3 below), not to `worker/cycle.py`** — keeping `run_automation_cycle()` itself simple and
side-effect-transparent (it either returns a result or lets triage's real exception propagate,
exactly reflecting Contract §13's Case A/B split at the boundary where it actually occurs).

## 9. M2 Tests

`tests/test_worker_cycle.py` (new), using `unittest.mock.patch("worker.cycle.run_collection_cycle",
...)` / `patch("worker.cycle.run_triage_cycle", ...)`:

1. Both are called exactly once each, collection before triage (assert via a shared call-order list
   both mocks append to).
2. Triage is still called after a collection result reflecting source-level failures (mock
   `run_collection_cycle` to return a `CollectionReport(sources_failed=1, ...)`; assert
   `run_triage_cycle` was still invoked) — proves Contract §13's "collection returns normally →
   triage still runs" at this layer.
3. A `TriageCycleReport`-returning mock combined with a raising mock (simulating the real,
   unwrapped `run_triage_cycle()` top-level failure) causes `run_automation_cycle()` to raise —
   confirming it does **not** swallow the exception itself (that is `worker/main.py`'s job, tested
   separately in M3).
4. `asyncio.CancelledError` raised from a mocked `run_triage_cycle()` propagates out of
   `run_automation_cycle()` uncaught (no `except Exception`/`except BaseException` anywhere in this
   file — grep-verifiable).
5. Mechanical AST/import check: `worker/cycle.py` imports neither `workflows.runner`,
   `capabilities.executor`, any `capabilities.*_capability`, nor `scripts.run_content_generation`.
6. `AutomationCycleResult`'s `duration_seconds` is non-negative and consistent with
   `finished_at - started_at` for a mocked, artificially-delayed pair of calls.

## 10. M3 — Worker Runtime

**Targets**: `worker/main.py`, `worker/__init__.py`, `core/config.py`, `pyproject.toml`,
`docker-compose.yml`.

### 10.1 M3A — Enabled mode

```python
async def _run_enabled_loop() -> None:
    while True:
        try:
            await run_automation_cycle()
        except Exception:
            logger.exception("automation_cycle_failed")
        await asyncio.sleep(settings.news_collection_interval_seconds)
```
`except Exception` catches an ordinary triage-propagated failure (§8.3); it structurally cannot
catch `asyncio.CancelledError` (a `BaseException` subclass). `asyncio.sleep()` is itself a
cancellation point — no special handling needed for "cancellation during interval sleep," it is a
direct consequence of `except Exception` never intercepting `CancelledError` at either await point.
Start-to-start cadence is `cycle duration + configured interval`, matching Contract §28's disclosed,
accepted (non-wall-clock) scheduling model.

### 10.2 M3B — Disabled mode

Exactly the Contract §14 model, implemented verbatim:
```python
async def _run_disabled_idle() -> None:
    logger.info("automation_disabled_idle")
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        logger.info("automation_worker_shutting_down_disabled")
        raise
```
No busy loop (a single `await` on a never-set `Event`), no repeated logging (the log call happens
once, before the wait), no DB/source access (neither `run_collection_cycle` nor `run_triage_cycle`
is imported into this idle path's call graph).

### 10.3 M3C — Cancellation and signal wiring (Planning-level mechanism, Contract-compatible)

```python
async def main() -> None:
    setup_logging()
    task = asyncio.current_task()
    assert task is not None
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, task.cancel)
        except NotImplementedError:
            # add_signal_handler is not implemented on Windows' default event loop.
            # No fallback handler is registered here; local Windows dev remains
            # stoppable only through the interpreter's normal process-interruption
            # path (Ctrl+C / process termination), whose exact responsiveness during
            # a long await (e.g. the disabled-idle wait, §10.2) is NOT verified or
            # guaranteed by this plan - it is not a Phase 12 architecture requirement,
            # since the Contract's actual deployment target is Linux/Docker, where
            # this handler registers successfully and is fully exercised (M6 step 13).
            pass
    try:
        if not settings.news_collection_enabled:
            await _run_disabled_idle()
            return
        await _run_enabled_loop()
    except asyncio.CancelledError:
        logger.info("automation_worker_shutdown_complete")
        raise


if __name__ == "__main__":
    asyncio.run(main())
```
**Disclosed Planning-level design decision, not a Contract reinterpretation**: the Contract requires
"exits only on cancellation/`SIGTERM`" but does not specify the exact mechanism converting an OS
`SIGTERM` into task cancellation. `loop.add_signal_handler(signal.SIGTERM, task.cancel)` is the
standard `asyncio` mechanism for this and is required for `docker-compose.yml`'s `restart:
unless-stopped` + `docker stop`/`docker compose down` (which sends `SIGTERM`) to trigger the
Contract's graceful-shutdown path at all — without it, Python's default `SIGTERM` disposition
terminates the process immediately, bypassing every cleanup guarantee the Contract freezes. This is
implementation plumbing realizing an already-frozen behavior, not a new architectural choice. The
`NotImplementedError` guard is a genuine, disclosed platform note: this repository's dev machine is
Windows (`win32`, per this session's own environment), where `add_signal_handler` is unsupported on
the default event loop for both `SIGTERM` and `SIGINT`.

**Correction (audit N1): no claim is made about Windows Ctrl+C responsiveness.** The guard's only
architecturally-required property is that `NotImplementedError` is caught narrowly (this specific
call only — never a broad `except Exception`/`except BaseException` that could mask an unrelated
registration error) so that failing to register a Windows signal handler does not crash the worker
at startup. Beyond "does not crash," this plan makes **no guarantee** about exact Windows console
signal-delivery timing during a long, timer-free await (notably `_run_disabled_idle`'s
`asyncio.Event().wait()`, §10.2) — this is a known class of `ProactorEventLoop` behavior this plan
has not independently tested, and it is explicitly **not** a Phase 12 architecture guarantee, since
the Contract's actual deployment target is Linux/Docker, where `add_signal_handler` registers
successfully for both signals and the graceful-shutdown path is fully exercised and verified live
(M6 step 13). Local Windows development remains usable for iterating on the code (running tests,
short manual smoke runs), just without a verified guarantee of prompt interactive-shutdown timing.

### 10.4 M3D — Configuration

```python
# core/config.py, added to class Settings, matching stale_processing_threshold_seconds's own
# gt=0 pattern and enabled_providers/verify_capabilities_at_boot's own opt-in-by-default pattern:
news_collection_enabled: bool = False
news_collection_interval_seconds: int = Field(default=1800, gt=0)
```
Names, defaults, and validation are copied verbatim from Contract §11/§16 — no value invented by
Planning. Tests added to `tests/test_settings_phase7.py`:
1. `test_news_collection_enabled_defaults_false`
2. `test_news_collection_interval_seconds_defaults_1800`
3. `test_news_collection_enabled_overridable_via_env` (`monkeypatch.setenv("NEWS_COLLECTION_ENABLED", "true")`)
4. `test_news_collection_interval_seconds_overridable_via_env`
5. `test_news_collection_interval_seconds_rejects_zero` / `..._rejects_negative` (mirrors
   `test_redis_unavailable_policy_rejects_unknown_value`'s own `pytest.raises` shape)

### 10.5 M3E — Packaging

`pyproject.toml` line 36: `packages = ["app", "core", "database", "bot", "integrations", "services",
"schemas", "scripts", "capabilities", "worker"]` — one entry added, alphabetical/list-order
otherwise unchanged. Verification: `pip install .` (or `pip install -e .` in a clean venv) followed
by `python -c "import worker.main"` succeeds. **`Dockerfile` requires no change** — re-confirmed in
§2; `COPY . .` precedes `pip install .`, so the newly-added `worker/` source is already present
before the wheel build reads the updated `packages` list.

### 10.6 M3F — Docker Compose

Exact block from Contract §15, transcribed verbatim (no Redis, `depends_on: postgres` only):
```yaml
automation_worker:
  build: .
  container_name: ai_newsroom_automation_worker
  restart: unless-stopped
  env_file: .env
  environment:
    POSTGRES_HOST: postgres
  command: ["python", "-m", "worker.main"]
  depends_on:
    postgres:
      condition: service_healthy
```
No public port (the worker exposes no server, unlike `backend`'s `8000:8000`) — not required by any
Contract clause, and adding one would be unauthorized scope expansion. Kept separate from `backend`
and any future `bot` service, per Contract §15's own stated separation rationale. Verification:
`docker compose config` (static validation, no containers started) confirms the service parses and
`depends_on`/`environment` resolve without error — no live container run during Planning or M1–M5.

## 11. M3 Tests

`tests/test_worker_main.py` (new):

**Enabled**: mock `worker.main.run_automation_cycle`; run `main()` as a task with
`settings.news_collection_enabled=True` and a short test interval; cancel after N iterations;
assert the mock was called ≥1 time and `asyncio.sleep` (patched to a fast stub or measured via
`asyncio.wait_for` with a small timeout) occurred between calls.

**Disabled**: mock `worker.main.run_automation_cycle`; run `main()` with
`settings.news_collection_enabled=False`; assert the mock was **never** called; assert the coroutine
is still running (not returned) after a short bounded wait; cancel it; assert it raises/exits via
`CancelledError` within a bounded time (e.g. `asyncio.wait_for(task, timeout=1.0)` combined with
`task.cancel()`); assert the "idle" log line appears exactly once (capture via `caplog`).

**Cancellation**: with `run_automation_cycle` mocked to hang or run normally, cancel the running
`main()` task mid-cycle and mid-sleep (two separate test cases); assert `CancelledError` propagates
out of `main()` (i.e. `await task` re-raises `CancelledError`, not swallowed); assert no further
call to `run_automation_cycle` occurs after cancellation.

**Static check**: grep/AST assertion — no `except BaseException` and no bare `except:` exists in
`worker/main.py` or `worker/cycle.py`.

**Ordinary error**: mock `run_automation_cycle` to raise a plain `Exception` once then succeed;
assert `main()`'s enabled loop survives (does not exit, does not propagate the exception), and the
next scheduled cycle still runs.

## 12. M4 — Offline Integration Verification

### 12.0 Database isolation strategy (frozen — corrects the Plan's original imprecise wording)

**This repository has no separate test database.** Re-confirmed by direct re-read of
`tests/conftest.py`, `tests/test_triage_orchestrator_claims.py`, and
`tests/test_triage_orchestrator_cycle.py`: every existing "real Postgres" test — with no
exception — connects to `settings.database_url`, the exact same connection string the live
application (and the eventual M6 worker) uses. There is no `test_ai_newsroom`-style separate
database, no schema reset, no container swap. **The Plan's own earlier "real test database"/
"in-memory test DB" wording was imprecise and is corrected here.**

Two isolation patterns already exist in this codebase, and they are **not interchangeable**:

1. `tests/conftest.py::db_session` — yields an already-**instantiated** `AsyncSession`, wrapped in
   an outer transaction with a SAVEPOINT join mode, rolled back at teardown. **Not usable here**:
   `run_collection_cycle(session_factory=...)` requires a **callable** invoked as `async with
   session_factory() as session:`, not a pre-built session object. Adapting `db_session` to this
   shape (e.g. `lambda: db_session`) is not merely awkward — `AsyncSession.__aexit__` calls
   `close()`, so the *first* of `run_collection_cycle()`'s or `run_triage_cycle()`'s two separate
   `async with session_factory() as session:` blocks to exit would close the shared session before
   the second one runs, breaking the collection→triage chain the Contract's own Integration Proof
   (§25) requires this test to exercise end to end.
2. `tests/test_triage_orchestrator_claims.py::independent_session_factory()` — returns `(engine,
   async_sessionmaker(engine, expire_on_commit=False))`, a genuine **factory**, matching
   `run_collection_cycle`/`run_triage_cycle`'s own required parameter shape exactly, already bound
   to `settings.database_url` via a dedicated `NullPool` engine (no connection-pool reuse across
   test event loops — the same reason `conftest.py`'s own fixtures avoid the production
   `database.session.engine` singleton). `tests/test_triage_orchestrator_cycle.py` **already uses
   this exact pattern** for `run_triage_cycle(session_factory=factory)` — the direct, proven
   precedent for `run_collection_cycle(session_factory=...)`'s identical need.

**DECISION, frozen for M1/M4: use `independent_session_factory()`, imported by name from
`tests/test_triage_orchestrator_claims.py` — no third isolation mechanism is invented.**

**Why transaction rollback alone is insufficient for this path (explicit rationale, not assumed)**:
`run_collection_cycle()` and `run_triage_cycle()` each call the *injected* `session_factory()`
themselves and issue their own real `session.commit()` calls internally (`services/collector.py`'s
`_process_source()` commits per source; `services/triage_orchestrator.py`'s `run_triage_cycle()`
commits per claimed/recovered event) — these are genuine, independent commits against
`settings.database_url`, not writes made through a single outer test-owned transaction a `db_session`
-style fixture could roll back. An M4 test built around `db_session`'s rollback discipline would
**not** actually undo what `run_collection_cycle()`/`run_triage_cycle()` themselves committed through
their own `session_factory()` calls — rollback-only cleanup is therefore explicitly rejected for
this path, not merely unused by oversight.

**Cleanup ownership and FK order (re-derived from current models, not guessed)**: re-read
`database/models/news_event.py`, `database/models/editorial_task.py`,
`database/models/news_source.py` directly this session:
- `EditorialTask.event_id` → `ForeignKey("news_events.id")`
- `NewsEvent.source_id` → `ForeignKey("sources.id")` (`NewsSource.__tablename__ == "sources"`)

The only rows M4 creates are one test-owned `NewsSource`, the `NewsEvent`(s)
`run_collection_cycle()` persists from it, and the `EditorialTask`(s) `run_triage_cycle()` persists
from those — no other model is touched by this test (no `ContentDraft`, no `AIExecution`, confirmed
by the same zero-rows assertions already planned). **Cleanup order, children first: `EditorialTask`
rows (by `event_id`) → `NewsEvent` rows (by `source_id`) → the one `NewsSource` row (by `id`).** No
`TRUNCATE`, no `DELETE FROM <table>` without a `WHERE` clause, no schema reset, no drop/recreate —
every delete is scoped to the exact test-owned primary/foreign keys collected during the test.

**Uniqueness strategy**: the test-owned `NewsSource.name` is
`f"phase12-integration-test-{uuid4()}"` (a distinctive, greppable prefix plus a UUID, matching
`independent_session_factory()`'s own sibling helper `real_committed_event()`'s
`f"claims-test-{uuid4()}"` naming convention exactly). The fake `RawNewsItem.external_id`s used by
`FakeSourceAdapter` are similarly prefixed (e.g. `f"phase12-test-item-{uuid4()}"`). Because
`_compute_hash(source_id, external_id)` (`services/collector.py:173-179`) hashes the **newly
generated, guaranteed-unique** `NewsSource.id` together with the external id, hash-collision with any
real production `NewsEvent` is structurally impossible even before considering the external-id
prefix — the prefix exists for human/log greppability, not for hash-uniqueness. **The repeated-poll
dedup test (§12.1) reuses the identical `external_id` for poll 1 and poll 2** — this is required, not
incidental: dedup is keyed on `(source_id, external_id)`, so proving "second poll does not
duplicate" specifically requires the *same* identity presented twice, against the *same* test-owned
`NewsSource`.

**Failure-safe cleanup, mandatory**: every row created by the test is tracked (the test-owned
`NewsSource.id`, and the `NewsEvent`/`EditorialTask` ids that flow from it) and removed inside a
`try/finally` (or an equivalent pytest fixture teardown that always runs, e.g. a fixture using
`yield` with the cleanup after it) — cleanup **must** execute even if a collector assertion, a
triage assertion, or the dedup assertion fails partway through the test body. No cleanup step is
made conditional on the preceding assertions having passed.

**Pre/post pollution check, mandatory, scoped to test-owned rows only**: before the test body runs,
query for any pre-existing row matching this run's own generated unique `NewsSource.name` (expected:
none — this also guards against a previous failed run having silently left rows behind, in which
case the check fails loudly rather than the accumulation going unnoticed) — and after cleanup,
re-query the same test-owned identifiers and assert zero rows remain. **This check is scoped
strictly to the test's own unique-named rows — it never asserts the shared `sources`/`news_events`/
`editorial_tasks` tables are empty**, since real dev/production data (and other tests' own rows) may
legitimately coexist in the same database at any time.

### 12.1 Exact frozen integration flow

```
unique test-owned SourceDefinition/NewsSource (name="phase12-integration-test-{uuid4()}")
  → fake source_pack_loader (returns 1 controlled SourceDefinition matching the inserted NewsSource)
  → fake adapter_resolver_factory (returns FakeAdapterRegistry wrapping FakeSourceAdapter,
    configured with 2 canned RawNewsItems, external_id="phase12-test-item-{uuid4()}" each)
  → real run_collection_cycle(
        session_factory=independent_session_factory(),
        source_pack_loader=...,
        adapter_resolver_factory=...,
    )
  → committed NewsEvent rows in settings.database_url, owned by the test (2 rows, exact-hash deduped)
  → real run_triage_cycle(session_factory=independent_session_factory())
  → committed EditorialTask(NEWS_ANALYSIS, CREATED) rows, owned by the test (one per NewsEvent)
  → assertions (collection report, triage report, row contents)
  → second poll: same fake seam, same external_ids, re-run run_collection_cycle() — dedup proof (§12.1a)
  → assertions (zero new NewsEvent rows; run_triage_cycle() again — zero new EditorialTask rows)
  → finally: explicit FK-safe cleanup (EditorialTask → NewsEvent → NewsSource, by tracked id)
  → post-test pollution check: zero rows remain matching this run's unique NewsSource.name
```
No external API call (`FakeSourceAdapter` performs no network I/O — proven by construction, not by
mocking a real adapter's network layer). No production credential is read beyond the same
`settings.database_url` every existing "real Postgres" test in this repository already uses. No
`WorkflowRunner`/`AIExecution` row exists afterward (mechanical `SELECT COUNT(*) FROM ai_executions`
== 0, or equivalent ORM query) — a **zero-rows** assertion, not "no exception raised." No
`ContentDraft` row exists afterward (same mechanical-zero-rows pattern).

### 12.1a Dedup proof

Run the same fake seam through `run_collection_cycle()` twice against the **same** test-owned
`NewsSource` and the **same** two `external_id`s (§12.0's uniqueness strategy): first invocation
creates 2 `NewsEvent` rows (`CollectionReport.events_created == 2`); second invocation creates 0 new
rows (`CollectionReport.duplicates_skipped == 2`) — exercising the real, unmodified
`services/deduplication.py::is_duplicate()` path, not a new dedup mechanism.

### 12.2 Triage proof

After the collection pass above, `run_triage_cycle(session_factory=independent_session_factory())`
claims both `NEW` events (scoped to this test's own rows only — the query itself is global per
Contract §8, but assertions are scoped to the test-owned `event_id`s), runs the real
`decide_triage()`, and calls the real `create_task()` — asserting `TriageCycleReport.tasks_created
>= 2` (not `==`, since other `NEW` events may legitimately coexist in the shared database from
unrelated activity — assertions must filter to the test's own `event_id`s) and that the two
test-owned `EditorialTask` rows have `status == CREATED`, `workflow_type == NEWS_ANALYSIS`. A
**second** call to `run_triage_cycle()` (simulating the next scheduled cycle) must create **zero**
additional tasks for the test's own events (`DuplicateActiveTaskError` caught internally) — proving
Contract §10's repeated-scheduled-triage-safety claim end-to-end, not just by source inspection.

### 12.3 `CREATED`-task buildup — visibility, not resolution

No new mechanism is implemented. The M4 integration test's own assertions above (`tasks_created`
scoped-count, both test-owned rows still `CREATED` before cleanup removes them) already make the
accumulation visible in the offline suite. For the human-run M6 acceptance procedure (§14 below),
the operator query is documented verbatim as:
```sql
SELECT COUNT(*) FROM editorial_tasks WHERE status = 'CREATED';
```
(or the ORM-equivalent `select(func.count()).where(EditorialTask.status == TaskStatus.CREATED)`,
optionally joined/filtered by the JSON `workflow` column's embedded `workflow_type` if the operator
wants the `NEWS_ANALYSIS`-only subset — `EditorialTask.workflow_type` is not its own DB column, per
direct re-read of `database/models/editorial_task.py`) — run once before and once after the M6
observation window, per Contract §26. This is a documented *procedure*, not a new script or
production file; it requires no addition to §3's file-scope table.

## 13. M5 — Full Regression / Readiness Gate

All of the following must pass before M6 is even proposed to the human operator — no live API spend
before this gate is green:

1. Phase 12 focused tests: `pytest tests/test_worker_cycle.py tests/test_worker_main.py
   tests/test_automation_integration.py -v`
2. Collector DI tests (§7, wherever collocated): included in the same focused run if placed in a
   dedicated file, or run as part of the existing collector-related suite.
3. Worker cycle tests: covered by #1.
4. Worker runtime tests: covered by #1.
5. Settings tests: `pytest tests/test_settings_phase7.py -v`
6. Offline integration test: covered by #1 (`tests/test_automation_integration.py`).
7. Full suite: `pytest`
8. Lint: `ruff check .`
9. Types: `mypy worker/ services/collector.py tests/fakes/fake_source_adapter.py
   tests/test_worker_cycle.py tests/test_worker_main.py tests/test_automation_integration.py
   tests/test_settings_phase7.py` (every changed/new file, per Contract DoD item 19 — not a
   repo-wide mypy run unless this project already gates on one).
10. Architecture validator: `python -m scripts.validate_architecture`
11. Secret/security hygiene: confirm no credential value appears in any new file's source or logs;
    `.env` remains untracked (`git status` shows no `.env` entry).
12. Git scope audit: `git status --short` and `git diff --stat` show changes **only** to the 12
    files enumerated in §3's table — no unrelated file touched.
13. Migration audit: `alembic history` / directory listing of `alembic/versions/` shows no new file.
14. Public-publishing exclusion audit: grep `worker/` for `aiogram`/`bot.loader`/`bot.handlers` —
    zero matches expected.
15. `NEWS_ANALYSIS`-execution exclusion audit: grep `worker/` for `workflows.runner`,
    `capabilities.executor`, `capabilities.*_capability`, `scripts.run_content_generation` — zero
    matches expected (mechanically enforced by M2's own AST test, §9 item 5, but re-run manually
    here as the whole-milestone gate).
16. **Test-pollution gate (new, per §12.0's isolation strategy)**: after item 1's/item 6's run of
    `tests/test_automation_integration.py`, independently re-query `settings.database_url` for any
    row matching that test run's own unique `NewsSource.name` prefix
    (`phase12-integration-test-*`). Expected: zero rows. **If any test-owned row remains — for any
    reason, including a test failure that skipped its own `finally` cleanup — M5 FAILS.** Do not
    proceed to M6 until this is confirmed clean; a leftover row must be manually deleted (by its
    exact tracked id, never a blanket table delete) and the cleanup defect fixed before re-running
    this gate.

**M5 is the last automated gate. It does not execute against any live external source or
credential** — every check above is either static (lint/type/grep) or runs against
`settings.database_url` (the same connection string the real application and M6 both use, per
§12.0 — not a separate live external source), matching every prior Phase's own
regression-checkpoint convention.

## 14. M6 — Manual Live Scheduled-Ingestion Acceptance

**HUMAN AUTHORIZATION REQUIRED. Not executed during implementation. Not executed automatically by
any agent.** Documented here as the exact procedure a human operator (or an agent explicitly
re-authorized for this one step, separately from this Planning session) follows once M5 is green:

1. Confirm at least one real, already-configured, `active` `NewsSource` exists in the target
   database (query, no write).
2. Record the current `EditorialTask` `CREATED`/`NEWS_ANALYSIS` count (§12.3's query) as the
   **before** baseline.
3. Start the worker with `news_collection_enabled=true` (`.env` or environment override) via
   `docker compose up -d automation_worker` (or the local `python -m worker.main` equivalent for a
   non-Docker acceptance run).
4. Confirm no developer manually runs `scripts/run_collector.py`/`scripts/run_triage.py` for the
   duration of the observation window.
5. Wait at least one full configured interval (default 1800s) — do not shorten the interval to force
   an early observation, since that would not be testing the deployed cadence.
6. Confirm a genuinely new source item was collected: query for a `NewsEvent` row whose
   `collected_at` falls after step 3's start time.
7. Confirm Triage ran automatically: query for the corresponding `EditorialTask(NEWS_ANALYSIS,
   CREATED)` row, if the event was triage-eligible.
8. Wait for a second scheduled cycle; confirm the same source item was **not** re-inserted as a
   second `NewsEvent` (dedup holds live, not just offline).
9. Confirm, by direct database inspection, `WorkflowRunner` was never invoked: zero new
   `AIExecution` rows, the `EditorialTask` remains `status == CREATED`.
10. Confirm no `ContentDraft` was created attributable to this worker's own operation (row count
    unchanged from before step 3, modulo any unrelated manual activity the operator is independently
    aware of).
11. Confirm no public Telegram/channel publication occurred (no message sent by any bot process
    attributable to this worker — the worker imports no `aiogram`/bot code at all, per M5 item 14,
    so this is a sanity re-confirmation, not an expected-to-fail check).
12. Record the **after** `CREATED`-task count from step 2's query; report the delta as the observed
    accumulation rate for this window (informational — accepted operational debt, not a failure
    condition).
13. **Stop procedure**: `docker compose stop automation_worker` (sends `SIGTERM`, respects
    `docker-compose.yml`'s default stop grace period); confirm the container logs show the
    "automation_worker_shutdown_complete" line (§10.3) before the container exits, proving graceful
    shutdown was exercised live, not just in the offline cancellation tests (§11). If the container
    does not log this line within the grace period and is instead `SIGKILL`ed, this is a live
    finding to report, not something to silently retry past.
14. **No repeated uncontrolled live retries**: if step 6/7/8/9/10 fails, stop the worker (step 13),
    do not restart-and-retry automatically, and report the failure for human review rather than
    looping the acceptance attempt.

## 15. Risk Register

| ID | Cause | Impact | Mitigation | Verification |
|---|---|---|---|---|
| R1 | Collector DI accidentally changes a production default value/object identity | Silent behavior change in the one already-live code path (manual `scripts/run_collector.py` runs, and the future worker) | M1 change is signature-and-forwarding only; every default is the exact pre-existing hardcoded object | M1 test §7 item 1 (signature defaults); M5 item 12 diff review |
| R2 | Fake test path accidentally still touches `ADAPTER_KEY_TO_ADAPTER`/real `AdapterRegistry` | Integration test silently exercises live adapters, defeating the whole seam | `FakeAdapterRegistry` never imports `services.adapter_keys`/constructs `AdapterRegistry` | M1 test §7 items 5-6; M4's network-block fixture |
| R3 | Worker cancellation accidentally swallowed (wrong except clause) | Docker `stop`/`down` cannot cleanly terminate the worker; `restart: unless-stopped` may then fight a hung process | `except Exception` only, never `BaseException`/bare `except`, enforced by static check | M2 test item 4; M3 test static check; M6 step 13 live proof |
| R4 | Disabled worker busy-loops or restart-loops | Wasted CPU, or Docker restart storm on a disabled deployment | `asyncio.Event().wait()` idle model, single log line, no exit | M3B design; M3 disabled tests |
| R5 | Multiple worker instances (operator error, future multi-replica) increase external API load | Doubled source-API/`FloodWaitError` exposure, not a correctness risk (Contract §12) | `docker-compose.yml` defines a single instance; existing hash-unique/atomic-claim safeguards make correctness independent of instance count | Contract §12, unchanged; not re-verified here (no new evidence needed) |
| R6 | A long-running cycle extends effective start-to-start cadence | Slightly less frequent collection than the configured interval under load | Disclosed, accepted (Contract §28); no wall-clock scheduler introduced | M3A design note |
| R7 | Stale source credentials/session (e.g. expired Telethon `StringSession`) | Per-source (or all-Telegram) fetch failures, silently absorbed by existing `except Exception` in `_process_source` | Unchanged from today; out of Phase 12's own scope to add monitoring | M6 step 6 (a failed collection would show as zero new events, prompting manual investigation) |
| R8 | `NEWS_ANALYSIS(CREATED)` task buildup | Row-count growth, informational | Accepted, documented operational debt (§12.3); no premature `WorkflowRunner` invocation | M4 assertions; M6 step 2/12 |
| R9 | Collector's first-ever real-DB integration test exposes a genuine pre-existing (Phase-4-era) collector defect **outside** M1's narrow authorized DI changes | Could block M4/M5 for a reason outside this plan's own authorized scope | **Frozen distinction**: if the defect is directly caused by M1's own new DI/forwarding code (i.e. a bug in the implementer's own new signature/Protocol/forwarding, not in pre-existing collector business logic), fix it within M1's already-authorized narrow scope like any other new-code bug — no escalation needed. If the defect is a genuine pre-existing collector behavior unrelated to the DI edit (e.g. in `_process_source`, `_fetch_with_retry`, `_process_item`, or any frozen §23 file), **STOP implementation and report it as a blocker** — do not autonomously fix frozen collector business logic, do not broaden M1's file scope to patch it | M4 test failures analysis; the distinction is made by checking whether the failure trace touches only §6.1's authorized lines or reaches into unmodified body code |
| R14 | Shared dev Postgres test pollution: no separate test database exists (§12.0); M4's `run_collection_cycle()`/`run_triage_cycle()` calls commit independently through their own injected `session_factory()`, so an outer test transaction cannot own/undo their writes | Residual test-owned `NewsSource`/`NewsEvent`/`EditorialTask` rows could contaminate manual dev testing, `/news` output, dedup behavior, or M6's own acceptance counts | Unique test-owned identifiers (`phase12-integration-test-{uuid4()}` `NewsSource.name`, prefixed `external_id`s) + `independent_session_factory()` (not a rollback fixture) + explicit, FK-safe cleanup (`EditorialTask` → `NewsEvent` → `NewsSource`) inside `try/finally`, never a table-wide delete | M5 item 16's dedicated post-test pollution check (zero test-owned rows remain); §12.0's pre-test check also catches a *previous* run's leftover pollution before it silently accumulates |
| R10 | `worker` package works via local editable install/bind mount but is missing from the actual built Docker image | Container starts but `python -m worker.main` fails with `ModuleNotFoundError` | `pyproject.toml`'s `packages` list is the single source of truth for both; M3E verification runs `pip install .` (not `-e`) before the Docker build step is trusted | M3E verification; M5 (recommend an explicit `docker compose build automation_worker` + `docker compose run --rm automation_worker python -c "import worker.main"` smoke check before M6, static-only, no long-running container) |
| R11 | Docker Compose accidentally re-adds a Redis dependency to the worker service (copy-paste from `backend`) | Unnecessary coupling, worker blocked on Redis health even though it never uses it | Contract §15 snippet transcribed verbatim (§10.6); `depends_on` lists only `postgres` | M5 item 12 diff review; visual `docker-compose.yml` diff against Contract §15 |
| R12 | Accidental expansion into `WorkflowRunner`/`NEWS_ANALYSIS` execution during implementation (e.g. "helpfully" clearing `CREATED` tasks) | Violates the frozen Contract boundary, reintroduces the `EngagementCapability` gap mid-Phase-12 | Explicit prohibition restated in every milestone (§8.3, §12.3); mechanically enforced by M2/M5's import-boundary checks | M2 test item 5; M5 item 15 |
| R13 | `loop.add_signal_handler(SIGTERM, ...)` is unsupported on Windows' default event loop | Local Windows developer runs `python -m worker.main` directly and hits `NotImplementedError` at startup | Guarded with `try/except NotImplementedError` (§10.3); production target is Linux/Docker, unaffected | M3 test suite runs on the actual dev machine (Windows) as its own proof the guard works; Docker smoke check (R10) proves the Linux path still installs real handlers |

## 16. Dependency-Ordered Implementation Sequence

1. M0 baseline (no code) — already satisfied (§2/§5).
2. `services/collector.py` DI seam (§6).
3. `tests/fakes/fake_source_adapter.py` + collector-seam focused tests (§7).
4. `worker/cycle.py` (§8).
5. `tests/test_worker_cycle.py` (§9).
6. `core/config.py` Settings additions (§10.4) — independent, may be done in parallel with steps 2-5.
7. `tests/test_settings_phase7.py` additions (§10.4).
8. `worker/main.py` + `worker/__init__.py` (§10.1-10.3).
9. `tests/test_worker_main.py` (§11).
10. `pyproject.toml` packaging (§10.5).
11. `docker-compose.yml` service (§10.6).
12. `tests/test_automation_integration.py` — dedup proof, triage proof (§12).
13. Full M5 gate (§13).
14. **STOP.**
15. Human review of this Plan's execution (a Planning-Audit-equivalent pass over the actual diff).
16. M6 only after explicit, separate human authorization (§14).

## 17. Definition of Done Mapping

| Contract §27 item | Milestone | File(s) | Verification | Manual/Automated |
|---|---|---|---|---|
| 1. Worker exists, starts cleanly | M3 | `worker/main.py` | M3 tests + M5 item 9 (Docker smoke, R10) | Automated + one manual smoke |
| 2. Cadence configurable | M3D | `core/config.py` | M3D tests | Automated |
| 3. Collection runs automatically on interval | M3A | `worker/main.py` | M3 enabled-mode tests | Automated |
| 4. Triage runs automatically after collection | M2 | `worker/cycle.py` | M2 test item 1 | Automated |
| 5. Repeated polling does not duplicate | M4 | `tests/test_automation_integration.py` | §12.1 dedup proof | Automated |
| 6. Per-source failure isolation preserved | M1 | `services/collector.py` (unmodified body) | M1 (no behavior test needed — body untouched); M4 could add a mixed-success/failure fake source pack | Automated |
| 7. Worker survives/logs single-cycle failure | M3A/M2 | `worker/main.py`, `worker/cycle.py` | M2 item 3, M3 "ordinary error" test | Automated |
| 8. No overlapping self-cycles | M3A | `worker/main.py` (sequential `while True`) | Structural — single coroutine, no concurrency introduced | Automated (no explicit test needed beyond code review) |
| 9. No `NEWS_ANALYSIS` execution | M2/M5 | `worker/cycle.py`, `worker/main.py` | M2 item 5, M5 item 15 | Automated |
| 10. No `WorkflowRunner` invocation | M2/M5 | same | same | Automated |
| 11. No `ContentDraft` generated | M4 | `tests/test_automation_integration.py` | zero-rows assertion | Automated |
| 12. No `EngagementCapability` implemented | all | (absence) | M5 item 15 grep | Automated |
| 13. No public publishing | M5 | (absence) | M5 item 14 grep | Automated |
| 14. No migration in the diff | M5 | (absence) | M5 item 13 | Automated |
| 15. Collector/Triage semantics byte-for-byte preserved | M1 | `services/collector.py` | M1 tests §7 item 1; frozen-file diff review | Automated + manual diff review |
| 16. Every mandatory test exists and passes | M1-M4 | all test files | M5 items 1-6 | Automated |
| 17. Full regression suite passes | M5 | — | M5 item 7 | Automated |
| 18. `ruff check .` clean | M5 | — | M5 item 8 | Automated |
| 19. Targeted `mypy` clean | M5 | — | M5 item 9 | Automated |
| 20. Architecture validator 0 violations | M5 | — | M5 item 10 | Automated |
| 21. Secret/security hygiene | M5 | — | M5 item 11 | Automated + manual review |
| 22. Manual live acceptance passes | M6 | — | §14, full procedure | **Manual, human-authorized only** |

**Every Contract DoD item is mapped. None is unmapped.**

## 18. Out of Scope

Restated explicitly, unchanged from the Contract: `EngagementCapability`; engagement/reach scoring;
`NEWS_ANALYSIS` execution; `WorkflowRunner` invocation; `CONTENT_GENERATION`; `ContentDraft`;
image/media persistence; the 5+ image-candidate requirement; meme generation; editorial actions;
public publishing; Celery; APScheduler; migrations; per-source cadence.

**The user's eventual product requirement — each proposed editorial news item should offer at least
5 relevant image candidates — is explicitly not addressed by this plan.** It belongs to a future,
separately-governed Visual Intelligence phase (Contract §20's own disclosed technical-debt framing);
nothing in this plan forecloses it (`NewsEvent.url` remains preserved, per Contract §20), but nothing
here implements any part of it either.

## 19. Self-Audit

1. **Did I plan only Contract-authorized files?** Yes — §3's table is derived directly from Contract
   §22, no addition.
2. **Is collector DI minimal and production-default-preserving?** Yes — §6.1/§6.2, signature-only
   change, every default is the pre-existing hardcoded object.
3. **Can the fake adapter bypass every real singleton/network path?** Yes — §6.3/§7, structurally
   proven (no `ADAPTER_KEY_TO_ADAPTER`/`AdapterRegistry` construction in the fake path).
4. **Is cancellation technically correct?** Yes — §10.1/§10.3, `except Exception` only, `CancelledError`
   propagates through both the cycle `await` and the interval `asyncio.sleep()`.
5. **Is disabled mode deterministic?** Yes — §10.2, single frozen model, no busy loop, no restart-loop
   exposure.
6. **Is Docker/package behavior build-safe?** Yes — §10.5/§10.6, no Dockerfile change needed, R10's
   Docker smoke check closes the one residual "works locally, missing from image" risk explicitly.
7. **Does offline integration use real collector persistence and real Triage?** Yes — §12, both
   `run_collection_cycle()` and `run_triage_cycle()` are the real, unmodified functions; only the
   source-pack/adapter-resolution/session boundary is faked.
8. **Is `NEWS_ANALYSIS` never executed?** Yes — §8.3/§12/§13 item 15, mechanically enforced at three
   layers (M2 unit test, M4 zero-rows assertion, M5 grep gate).
9. **Is `CREATED`-task buildup honestly visible but not "fixed"?** Yes — §12.3/§14 step 2/12, an
   observation procedure only, no new mechanism, explicit statement that this is accepted debt.
10. **Can each milestone stop cleanly for review?** Yes — §16's sequence ends at M5/step 14 with an
    explicit STOP before any human-authorized live step.
11. **Does M6 require explicit human authorization?** Yes — §14's header states this twice, and §16
    item 16 repeats it as the sequence's own final gate.
12. **Can implementation proceed without inventing architecture?** Yes. Every substantive behavior
    (DI seam shape, exception semantics, disabled-state model, Docker topology, config
    defaults/validation, integration-test flow) is copied directly from the frozen, approved
    Contract. The only choices this plan itself makes (§8.1's exact `AutomationCycleResult` field
    list, §10.3's exact signal-handling mechanism and its Windows guard, exact test file names/
    locations) are implementation mechanics realizing already-frozen behavior, not new product or
    architecture decisions, and are each disclosed as such rather than presented as Contract text.

**Self-audit result: #12 = YES. Plan is ready.**

## 20. Final Recommendation

Implementation may proceed milestone-by-milestone (M0→M5) exactly as sequenced in §16, with a
mandatory stop before M6 pending separate human authorization, once this Plan itself passes a
Planning Audit.

---

PHASE 12 IMPLEMENTATION PLAN READY FOR AUDIT
