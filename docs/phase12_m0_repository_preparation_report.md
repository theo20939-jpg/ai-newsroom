# Phase 12 — M0 Repository Preparation Report

No code changed in this milestone. Baseline re-verified immediately before implementation began.

- `git rev-parse HEAD` = `228c874b83bb7565629f3c9c5099302925336d59` — unchanged since every prior
  Phase 12 governance document's own citation.
- `git status --short` — only untracked `docs/*.md` files; zero non-documentation change.
- `worker/` does not exist.
- `run_collection_cycle()` (`services/collector.py:44`) takes zero parameters; hardcodes
  `async_session_factory` (import line 21, use line 57), `load_source_pack()` (import line 26, call
  line 54, zero args), `build_registry(definitions)` (import line 25, call line 55).
- `AdapterRegistry.resolve()` (`services/adapter_registry.py:75-95`) resolves the actual adapter
  object via `services/adapter_keys.py::ADAPTER_KEY_TO_ADAPTER` (module-level dict of real,
  network-calling adapter singletons), independent of whatever `SourceDefinition`s were used to
  build the registry's own `url_index`/`definition_index`.
- `run_triage_cycle(session_factory: async_sessionmaker[AsyncSession] = async_session_factory)`
  (`services/triage_orchestrator.py:222-223`) already accepts an injectable session factory.
- Collector dedup: `services/collector.py:145-168` — exact-hash + `IntegrityError` catch inside
  `session.begin_nested()`.
- Triage duplicate-active-task safety: `services/triage_orchestrator.py:199-209` — catches
  `DuplicateActiveTaskError` as a non-failure no-op.
- `core/config.py` conventions re-confirmed: `Field(gt=0)` pattern
  (`stale_processing_threshold_seconds`), opt-in-by-default bool pattern
  (`verify_capabilities_at_boot`).
- `pyproject.toml:36` — `packages = ["app", "core", "database", "bot", "integrations", "services",
  "schemas", "scripts", "capabilities"]` — `"worker"` not yet present.
- `docker-compose.yml` — 3 services (`backend`, `postgres`, `redis`); `backend`'s own
  `POSTGRES_HOST`/`REDIS_HOST` override pattern re-confirmed as the template to follow.
- No `WorkflowRunner`/`capabilities.executor` import anywhere in
  `services/collector.py`/`services/triage_orchestrator.py`/`services/workflow_service.py`.

**Final re-audit clarifications, re-verified once more immediately before implementation**:
- **A** — `independent_session_factory()` (`tests/test_triage_orchestrator_claims.py:38-42`) returns
  `tuple[AsyncEngine, async_sessionmaker[AsyncSession]]`. The **second** element is the callable
  factory `run_collection_cycle`/`run_triage_cycle` require. Implementation will unpack this
  explicitly (`engine, session_factory = independent_session_factory()`), never pass the tuple
  itself.
- **B** — `NewsSource` (`database/models/news_source.py`) requires `name: str`, `type: SourceType`
  (nullable `False`, no default) at minimum to construct a valid row; `url`, `category`,
  `reliability_score` are nullable; `active` defaults `True`; `id`/`created_at`/`updated_at` are
  server/default-generated. M4 will insert this row directly via the session factory, independent of
  the fake `source_pack_loader`, since `_load_active_sources()` queries `NewsSource` directly from
  the database.

**M0 completion criterion met — repository matches every frozen Contract/Plan assumption.**
Proceeding to M1.
