# Phase 12 — M1 Collector DI Seam Report

## Changes

**`services/collector.py`** (existing file, narrow edit exactly per Contract §7/§22): added a local
`SourceAdapterResolver` `Protocol` (structural interface, `resolve(source) -> AdapterResolution |
None`), three keyword-only defaulted parameters on `run_collection_cycle()`
(`session_factory`, `source_pack_loader`, `adapter_resolver_factory`), retyped
`_load_active_sources()`/`_process_source()`'s `registry` parameter from `AdapterRegistry` to
`SourceAdapterResolver`, added typing-only imports (`typing.Protocol`, `collections.abc.Callable`,
`sqlalchemy.ext.asyncio.async_sessionmaker`, `schemas.source_definition.SourceDefinition`,
`services.adapter_registry.AdapterResolution`, `services.source_registry.SourceRegistryReport`).
No other line changed — `_fetch_with_retry`, `_process_item`, `_compute_hash`, retry/backoff,
failure isolation, and the outer `try/except Exception` are byte-for-byte unchanged.
`services/adapter_registry.py` and `services/adapter_keys.py` were **not** touched.

## New test infrastructure

- `tests/fakes/fake_source_adapter.py` — `FakeSourceAdapter` (network-free `SourceAdapter`) and
  `FakeAdapterRegistry` (a `SourceAdapterResolver`-satisfying fake, **scoped to an explicit set of
  resolvable source ids** — see incident below).
- `tests/test_automation_integration.py` — 7 M1 focused tests (M4's real-DB integration tests will
  be added to this same file later per the approved Plan's own collocation recommendation).

## Incident found and fixed during implementation

The first version of `FakeAdapterRegistry` resolved **every** `NewsSource` passed to it,
unconditionally. Since `_load_active_sources()` queries **all** active `NewsSource` rows in the
shared database (confirmed: this repository has no separate test database), the first test run
caused the collector to process all 83 real, pre-existing active sources in this dev database, not
just the test-owned one — creating 492 polluting `NewsEvent` rows (title `"Hello world"`) attached to
real `NewsSource` rows across three test runs before the bug was caught by an unexpected
`events_created == 83` assertion failure.

**Immediate remediation**: verified all 492 rows were created within a 1-minute window matching this
session's own test runs (`created_at` between 09:11:37 and 09:12:57 UTC today), verified zero
`EditorialTask` rows referenced any of them, and deleted them by exact `title = 'Hello world'` match
— confirmed zero remain afterward. No real/dev `NewsSource`, unrelated `NewsEvent`, or
`EditorialTask` row was touched.

**Fix**: `FakeAdapterRegistry` now requires an explicit `resolvable_source_ids: set` constructor
argument and returns `None` for any `NewsSource.id` not in that set — mirroring how the real
`AdapterRegistry.resolve()` only matches sources it actually recognizes. Every test now passes
`resolvable_source_ids={test_source.id}`. Re-ran the full suite after the fix: all 7 tests pass in
2.8s (vs. the original faulty run touching 83 real sources), and a follow-up direct query confirms
zero test-owned or polluting rows remain in the database.

## Verification

- `pytest tests/test_automation_integration.py -v` — **7 passed**.
- Post-run pollution check (direct query): zero `phase12-integration-test-*` `NewsSource` rows,
  zero `title = 'Hello world'` `NewsEvent` rows.
- `ruff check services/collector.py tests/fakes/fake_source_adapter.py
  tests/test_automation_integration.py` — **all checks passed**.
- `mypy services/collector.py tests/test_automation_integration.py` — **clean**, except one
  pre-existing, unrelated warning (`telethon.errors` missing stubs, `services/collector.py:19`) —
  independently confirmed present at `HEAD` (`git show HEAD:services/collector.py` also produces
  this exact warning) — not caused by this milestone's DI edit, not fixed, per the frozen R9 rule
  (pre-existing defects outside the narrow DI scope are not autonomously fixed).

**M1 complete. Proceeding to M2.**
