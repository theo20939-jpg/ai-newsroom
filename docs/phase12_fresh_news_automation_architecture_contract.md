# Phase 12 — Fresh News Automation Architecture Contract

## 1. Status and Authority

**Status: Revision 3 — targeted correction of `docs/phase12_fresh_news_automation_contract_reaudit.md`'s
1 MAJOR + 1 MINOR findings (CRITICAL=0). Pending final re-audit.** Revision 2 resolved the original
audit's 3 MAJOR + 2 MINOR findings (collection-cycle testability seam, cancellation/exception-catch
semantics, disabled-state worker behavior, Docker Redis dependency, failure-table Case A) but the
re-audit found Revision 2's `registry_builder` parameter did not actually close the testability seam:
`AdapterRegistry.resolve()` resolves the real adapter object through a separate, non-injectable
module-level dependency (`services/adapter_keys.py::ADAPTER_KEY_TO_ADAPTER`), so a test-supplied
`registry_builder` returning a genuine `AdapterRegistry` could never yield a network-free fake
adapter. Revision 3 corrects exactly this (§7/§22/§24/§25) and closes one file-scope omission for
Configuration tests (§22/§24). No other Revision 1/2 decision is reopened. This document converts
`docs/phase12_fresh_news_automation_decision_resolution.md` ("Decision Resolution") into binding
implementation form. No production code, test, or migration was modified to produce this document.
Every implementation-fact claim was independently re-verified against current source this session
(cited file:line where practical) — no claim is inherited from Decision Resolution or Discovery
without re-checking.

**Source-of-truth order**: this Contract (once approved) > Decision Resolution (the approved
product/architecture decisions this Contract codifies, never reinterprets) >
`docs/post_phase11_newsroom_gap_discovery.md` (shared evidence) > frozen Phase 4–11 contracts, all
of which remain in force, unamended.

**No source contradiction was found** between Decision Resolution and current repository state —
every technical assumption it made was re-verified feasible exactly as decided.

Every statement is tagged **FACT** (re-verified source evidence), **DECISION** (frozen, binding
choice), **INFERENCE** (reasoned conclusion), or **RECOMMENDATION** (non-binding).

## 2. Purpose

**DECISION**: Phase 12 makes the two already-correct, already-tested, one-shot cycles —
`services/collector.py::run_collection_cycle()` and
`services/triage_orchestrator.py::run_triage_cycle()` — run automatically, on a recurring internal
schedule, instead of only when a human manually invokes `scripts/run_collector.py`/
`scripts/run_triage.py`. Phase 12 removes the need for a developer to manually trigger a
collection/triage pass. **It does not make the full editorial pipeline automatic** — that begins
only once a future, separately-governed phase resolves the missing `EngagementCapability` and
builds `NEWS_ANALYSIS`-execution/`CONTENT_GENERATION`-trigger orchestration.

## 3. Scope

**DECISION — IN SCOPE**:
- Recurring automatic collection, using existing, unmodified collector logic.
- Configured, already-`active` `NewsSource` rows — no new source-configuration mechanism.
- Existing `NewsEvent` persistence and exact-hash dedup, unmodified.
- Automatic invocation of existing `run_triage_cycle()` immediately after each collection pass.
- The `EditorialTask(NEWS_ANALYSIS, CREATED)` rows this produces — **inherited** from Triage's own
  frozen Phase 9 contract, not new Phase 12 feature logic (§10).
- Cycle-level operational logging (§18).
- Safe worker startup/graceful shutdown (§14).
- One global, configurable collection cadence (§11).
- The Docker/runtime process needed to run the worker (§15).

**DECISION — OUT OF SCOPE, binding**:
`EngagementCapability` implementation; reach-aware scoring; any change to Triage's scoring formula;
any `WorkflowRunner` invocation; `NEWS_ANALYSIS` execution; `CONTENT_GENERATION` execution;
`ContentDraft` generation; image/media persistence; the 5+ image-candidate requirement; meme
generation; editorial actions (Approve/Reject/Rework); authorization/RBAC; public publishing of any
kind; a scheduler for public posts; per-source cadence / any new database column; Celery;
APScheduler; any migration.

## 4. Existing Architecture

Every claim re-read directly this session:

| Component | Classification | Evidence |
|---|---|---|
| `services/collector.py::run_collection_cycle()` | **EXISTING, narrow signature addition only** (§7/§22) | Full file re-read; loads active sources, fetches via adapter, cleans, dedups, persists `NewsEvent`, per-source failure isolation, retry-with-backoff. Orchestration body is unmodified — only three new defaulted, keyword-only parameters are added to its signature. |
| `integrations/sources/*.py` (Telegram/RSS/arXiv/GitHub/HN adapters) | **EXISTING, unchanged** | `integrations/sources/` directory listing |
| `services/deduplication.py::is_duplicate()` | **EXISTING, unchanged** | Exact-hash lookup, `NewsEvent.hash` unique constraint |
| `services/triage_orchestrator.py::run_triage_cycle()` | **EXISTING, unchanged** | Atomic claim-or-skip, creates `EditorialTask(NEWS_ANALYSIS)` via `services.workflow_service.create_task()` |
| `services/triage.py::decide_triage()` | **EXISTING, unchanged** | Freshness (0.6) + `NewsSource.reliability_score` (0.4) only — frozen, closed input set |
| `database.session.async_session_factory` | **EXISTING, unchanged** | `database/session.py:14` |
| `core/logging.py::setup_logging()` | **EXISTING, unchanged** | `logging.basicConfig`, used by every existing entry-point script |
| `core/config.py::Settings` | **EXISTING, narrow addition** (§16) | Two new fields only |
| `docker-compose.yml` | **EXISTING, narrow addition** (§15) | One new service definition |
| `scripts/run_collector.py`, `scripts/run_triage.py` | **EXISTING, unchanged** | Manual one-shot path preserved (§17) |
| A new `worker/` package (`main.py`, `cycle.py`) | **NEW IN PHASE 12** | §5–§7 |

**Material fact re-confirmed this session, superseded by this revision**: `run_collection_cycle()`
previously took **no parameters** — it hardcoded `from database.session import
async_session_factory` (`services/collector.py:21,57`) **and** hardcoded `load_source_pack()`
called with zero arguments (`services/collector.py:26,54`, always resolving
`source_registry.DEFAULT_PACKAGE_DIR`) **and** hardcoded `build_registry(definitions)`
(`services/collector.py:25,55`), unlike `run_triage_cycle(session_factory:
async_sessionmaker[AsyncSession] = async_session_factory)`, which already accepts an injectable
session factory (`services/triage_orchestrator.py:222-223`, matching
`scripts/run_content_generation.py`'s own established DI-seam convention). **Revision 1 disclosed
only the session-factory half of this hardcoding and left it unresolved as a testing friction
point.**

**Material fact, newly traced this session (Revision 3 correction) — the real adapter-resolution
chain**: `AdapterRegistry.resolve()` (`services/adapter_registry.py:75-95`) does **not** decide the
returned adapter *object* from the `url_index`/`definition_index` a `registry_builder` populates —
it uses those only to derive an adapter-key *string*, then looks up the actual `SourceAdapter`
**instance** via `adapter = ADAPTER_KEY_TO_ADAPTER.get(adapter_key)` (line 86), where
`ADAPTER_KEY_TO_ADAPTER` is a fixed, module-level dict of real, singleton, network-calling adapters
(`TelegramSourceAdapter()`, `RSSSourceAdapter()`, `GitHubSourceAdapter()`,
`HackerNewsSourceAdapter()`, `ArxivSourceAdapter()`) built at import time in
`services/adapter_keys.py:45-66`. **Revision 2's `registry_builder` parameter, typed to return a
genuine `AdapterRegistry`, therefore could never produce a network-free fake adapter** — any
function constructing a real `AdapterRegistry` (including the production default, `build_registry`)
resolves through this same hardcoded map regardless of what `SourceDefinition`s it was built from.
This revision corrects the seam at the one point that actually needs to change:
`_load_active_sources()`/`_process_source()` (`services/collector.py:81-100`) consume the injected
object through exactly one method, `registry.resolve(source) -> AdapterResolution | None` — no
`isinstance` check, no other method call — so retyping this parameter to a narrow **structural**
interface (a `Protocol` exposing only `resolve()`) rather than the concrete `AdapterRegistry` class
is sufficient to let a test supply an object that never touches `ADAPTER_KEY_TO_ADAPTER` at all. See
§7 for the frozen signature — this closes all three original hardcodings *and* the newly-traced
fourth one, with no change to `services/adapter_registry.py` or `services/adapter_keys.py`.

**Material fact, newly confirmed this session**: `services/collector.py` has **zero existing test
coverage** — the only repository reference to `run_collection_cycle` outside the module itself is
a synthetic fixture string inside `tests/test_validate_architecture.py` (line 299), used only to
test the architecture validator's own pattern-matching, not collector behavior. Phase 12's own
integration proof (§25) will be the first real-database exercise of this pre-existing function.
This revision authorizes exactly one narrow signature addition to `services/collector.py` to make
that exercise concretely feasible (§7/§22) — the function's internal orchestration body is not
otherwise touched.

## 5. Automation Mechanism

**DECISION, binding**: a dedicated, single-purpose async worker process — no Celery, no
APScheduler, no scheduler embedded inside the FastAPI (`app/main.py`) or Telegram bot
(`bot/main.py`) processes. **Re-confirmed this session**: `pyproject.toml:6-19` declares no
task-queue or scheduler dependency; a repo-wide search for
`celery|apscheduler|croniter|schedule\.every|BackgroundScheduler` in production code returns zero
matches. Introducing either framework now would add a new dependency and new operational surface
(broker, worker/beat processes) with no current-source justification, for what is exactly two
sequential function calls today.

Conceptual shape, matching `bot/main.py`'s own established pattern:
```
startup (setup_logging(), read configuration)
    → while not shutting down:
        → run one cycle (§6)
        → sleep for the configured interval (§11), unless shutdown was requested
    → graceful shutdown (§14)
```

## 6. Cycle Contract

**DECISION, binding — new module, `worker/cycle.py`**, one function:
```python
async def run_automation_cycle() -> AutomationCycleResult:
    collection_report = await run_collection_cycle()      # services.collector — called with zero args;
                                                            # every injectable parameter (§7) resolves to
                                                            # its production default, identical to today
    triage_report = await run_triage_cycle()               # services.triage_orchestrator, unmodified
    return AutomationCycleResult(collection=collection_report, triage=triage_report, ...)
```
**DECISION**: `worker/cycle.py` never passes non-default arguments to either function in production.
The three new `run_collection_cycle()` parameters (§7) exist solely so tests can substitute
controlled fakes — production call sites (`worker/cycle.py`, `scripts/run_collector.py`) invoke it
exactly as before, with zero arguments.
**DECISION**: collection and triage run **sequentially, in the same process, same event loop, one
after the other** — not concurrently, not in separate processes. Each retains its own existing,
independent session-per-cycle discipline (`run_collection_cycle()` opens/closes its own session
internally per source; `run_triage_cycle()` opens one session for its whole batch) — **Phase 12
introduces no shared session between the two**, and no change to either function's own transaction
boundaries.

**DECISION, binding**: `worker/cycle.py` **does not** duplicate any collector/triage business logic
— it only calls the two existing functions and combines their already-existing report dataclasses
for logging (§18).

## 7. Collection

**DECISION, binding**: Phase 12 reuses `run_collection_cycle()`'s orchestration exactly as it
exists today — no modification to source loading, per-source failure isolation, persistence
semantics, exact-dedup protection, or retry behavior. **FACT, re-confirmed**: a source's fetch
failure is caught, logged, and increments `report.sources_failed`; the loop continues to the next
source (`services/collector.py:60-67`) — this is already deterministic and requires no new Phase 12
decision.

**DECISION, binding — Correction 1 (MAJOR-1 resolution, corrected in Revision 3): concrete, frozen
testability seam, reaching all the way to the actual adapter instance used for fetching.**
`run_collection_cycle()`'s signature gains exactly three new, keyword-only, defaulted parameters —
its body is otherwise byte-for-byte unmodified. **Revision 3 change from Revision 2**: the third
parameter is renamed `adapter_resolver_factory` (from `registry_builder`) and retyped to return a
narrow, local, structural `Protocol` — `SourceAdapterResolver` — instead of the concrete
`AdapterRegistry` class:

```python
from typing import Protocol

class SourceAdapterResolver(Protocol):
    """Structural interface for whatever `_load_active_sources()`/`_process_source()` actually
    call. `AdapterRegistry` already satisfies this exactly, with no change to it required —
    Python's structural typing does not require an explicit subclass relationship. A test-owned
    fake object satisfying only this method never touches `AdapterRegistry` or
    `services/adapter_keys.py::ADAPTER_KEY_TO_ADAPTER` at all."""

    def resolve(self, source: NewsSource) -> AdapterResolution | None: ...


async def run_collection_cycle(
    *,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    source_pack_loader: Callable[[], tuple[list[SourceDefinition], SourceRegistryReport]] = load_source_pack,
    adapter_resolver_factory: Callable[[list[SourceDefinition]], SourceAdapterResolver] = build_registry,
) -> CollectionReport:
    ...
    definitions, _registry_report = source_pack_loader()
    registry = adapter_resolver_factory(definitions)

    async with session_factory() as session:
        ...
```

`_load_active_sources(session, registry)` and `_process_source(session, source, registry, report)`
(`services/collector.py:81-100`) have their `registry: AdapterRegistry` type hints changed to
`registry: SourceAdapterResolver` — **their bodies are unmodified**; both already call only
`registry.resolve(source)`, nothing else, confirmed by direct re-read.

**Why this exact shape, not Option B (a new Phase-12-owned wrapper function)**: this codebase
already has an established, proven convention for exactly this problem —
`run_triage_cycle(session_factory: async_sessionmaker[AsyncSession] = async_session_factory)`
(`services/triage_orchestrator.py:222-223`) and
`run_content_generation_for_event(..., session_factory=..., capability_registry=...)`
(`scripts/run_content_generation.py`) both add defaulted, keyword-only DI parameters directly to the
production function, with zero behavior change when called with no arguments. A wrapper (Option B)
would not actually avoid touching `services/collector.py`: since the inner hardcoded calls
(`load_source_pack()`, `build_registry(...)`, `async_session_factory`) live *inside*
`run_collection_cycle()`'s own body, a wrapper could only redirect them by either (a) duplicating
the collector's orchestration logic outside `services/collector.py` — explicitly forbidden by §17's
zero-duplication rule — or (b) still requiring the identical signature change to the inner function,
just reached through an extra layer. Option A is therefore both the smallest change and the one
most consistent with this repository's own existing pattern.

**Why a `Protocol` retype closes the newly-traced gap, without touching `AdapterRegistry` or
`adapter_keys.py`**: the re-audit traced that `AdapterRegistry.resolve()` resolves its returned
adapter object via the separate, hardcoded, module-level `ADAPTER_KEY_TO_ADAPTER` dict of real
adapter singletons (`services/adapter_keys.py:45-66`) — meaning any function that constructs a
genuine `AdapterRegistry` (as `registry_builder`'s Revision-2 type demanded) necessarily resolves
real, network-calling adapters, no matter what `SourceDefinition`s it was built from. The fix is not
to modify `AdapterRegistry` or `ADAPTER_KEY_TO_ADAPTER` (both remain frozen, §23) — it is to stop
requiring the injected parameter to *be* an `AdapterRegistry` at all. Since the two call sites that
consume it use only structural access (`registry.resolve(source)`), retyping the parameter to the
`SourceAdapterResolver` `Protocol` above means a test can supply **any** object with a matching
`resolve()` method — most simply, a small test-owned class that wraps a fake, network-free
`SourceAdapter` directly and never imports or references `ADAPTER_KEY_TO_ADAPTER` at all. No global
singleton mutation, no monkeypatching of any kind, is required by this design. `AdapterRegistry`
itself continues to satisfy `SourceAdapterResolver` structurally with **zero code change to it** —
`build_registry` remains the correct, unmodified production default.

**Why three parameters, not two**: closing only `session_factory` leaves `load_source_pack()`
hardcoded to the real, on-disk `config/newsroom_sources_v1` package — a test could substitute a test
database but would still resolve against whatever `SourceDefinition`s that real package declares.
Injecting `source_pack_loader` lets a test supply a controlled, in-memory `SourceDefinition` list;
injecting `adapter_resolver_factory` (now correctly typed) lets a test map that list to a genuinely
**fake**, network-free adapter resolution, closing the full chain end to end:

```
fake source_pack_loader → fake adapter_resolver_factory
    (returns a test-owned object satisfying SourceAdapterResolver, wrapping a fake,
     network-free SourceAdapter — never constructs a real AdapterRegistry,
     never touches ADAPTER_KEY_TO_ADAPTER)
    → real run_collection_cycle() orchestration (_load_active_sources, _process_source,
      _fetch_with_retry, _process_item, exact-hash dedup)
    → real test session_factory → real NewsEvent persistence, asserted directly against the test DB
```

**Production behavior is unchanged by default**: every one of the three parameters defaults to the
exact function/value `run_collection_cycle()` already hardcodes today
(`async_session_factory`, `load_source_pack`, `build_registry`) — `build_registry`'s own
implementation is untouched, and it continues to return a real `AdapterRegistry` that resolves real
adapters exactly as before, since `SourceAdapterResolver` is a type-level narrowing only, not a
behavioral change. `worker/cycle.py` and `scripts/run_collector.py` both call
`run_collection_cycle()` with zero arguments (§6/§17) — the production code path is byte-for-byte
identical in behavior to before this correction. This is a signature-and-type-only, narrow
testability edit — no source-adapter redesign, no `AdapterRegistry`/`adapter_keys.py` change, no
collector business-logic rewrite, no change to failure isolation, retry, or dedup semantics.

## 8. Triage

**DECISION, binding**: immediately following collection in the same cycle, `worker/cycle.py` calls
`run_triage_cycle()` **unmodified**. **FACT, re-confirmed**: this function re-queries **all**
currently-eligible `NewsEvent` rows (`status == NEW`, plus stale-`PROCESSING` recovery candidates)
on every invocation (`services/triage_orchestrator.py:261-267`) — it does not need, and must not be
given, a list of "this cycle's new events only." Scoring semantics (`services/triage.py`'s
Freshness + static-reliability formula) are **unchanged** — Phase 12 adds no engagement/reach
signal.

## 9. NEWS_ANALYSIS Boundary

**DECISION, binding, safety invariant, restated exactly per Decision Resolution §11**: Phase 12
**MUST NOT**: invoke `WorkflowRunner` for a `NEWS_ANALYSIS` task; execute the `engagement_analysis`
step; work around, remove, or bypass it; auto-complete any `NEWS_ANALYSIS` task. **FACT,
re-confirmed this session**: neither `services/collector.py` nor `services/triage_orchestrator.py`
imports `workflows.runner` or `capabilities.executor` — Phase 12's own new module
(`worker/cycle.py`) imports neither either (§23's authorized scope contains no such import).
`NEWS_ANALYSIS` tasks created by Triage (§10) remain in `CREATED` status indefinitely under Phase
12 — their execution belongs to a later, separately-governed phase.

## 10. EditorialTask Semantics

**DECISION, binding, stated exactly**: `EditorialTask(type=NEWS_ANALYSIS, status=CREATED)` row
creation is **inherited, existing Triage behavior** — re-confirmed this session
(`services/triage_orchestrator.py:191-197`, `_run_phase_b()` calls
`services.workflow_service.create_task()` with `workflow_type=WorkflowType.NEWS_ANALYSIS`) — **not**
new Phase 12 feature logic. Phase 12 does not construct, request, or influence this call in any way
beyond invoking the already-existing `run_triage_cycle()` function.

**Duplicate-active-task safety, re-verified from source, not assumed**: `create_task()` (via
`_find_active_task()`, reused unmodified) already raises `DuplicateActiveTaskError` if an active
(`CREATED`/`RUNNING`) task already exists for an event — `_run_phase_b()` already catches this
exact exception and treats it as a non-failure, no-op outcome
(`services/triage_orchestrator.py:199-209`). **Repeated scheduled triage cannot create duplicate
active `NEWS_ANALYSIS` tasks for the same event** — this safety is already guaranteed by existing,
unmodified Phase 9 code, confirmed by direct re-read, not assumed from Decision Resolution's own
claim.

**DECISION, binding, explicit framing (unchanged from Revision 1, restated per correction-task
instruction)**: at most, the existing duplicate-active-task protection above applies — no new
protection is added or needed. `CREATED` tasks are expected to **accumulate indefinitely** once
automation runs continuously, since no phase currently executes `NEWS_ANALYSIS` (§9). This is
**accepted, temporary operational debt**, not a defect Phase 12 must resolve, and Phase 12
explicitly **must not** "solve" it by invoking the currently-broken `NEWS_ANALYSIS`/
`EngagementCapability` path (§9/§23). It **must be monitored during Manual Live Acceptance** (§26)
— by direct database inspection of `EditorialTask` row counts/age, not by new tooling — so the
accumulation rate is observed at least once before Phase 12 is considered operationally accepted,
and is tracked as a named risk (§28) for a future phase to address.

## 11. Cadence

**DECISION, binding — one new `Settings` field**:
```python
news_collection_interval_seconds: int = Field(default=1800, gt=0)
```
Global, not per-source (`schemas/source_definition.py`'s `fetch_interval` is confirmed,
re-verified this session, never imported into `NewsSource` — `services/source_pack_importer.py`'s
own docstring states this explicitly; adding it now would require a migration, out of scope).
Default **1800 seconds (30 minutes)** — a deliberately conservative starting cadence, roughly
double `stale_processing_threshold_seconds`'s own existing 900-second default
(`core/config.py:80`), balancing "fresh enough for an SMM newsroom" against avoiding unnecessary
source-API load; freely retunable via `.env` with no code change. `Field(gt=0)` matches
`stale_processing_threshold_seconds`'s own existing validation pattern exactly
(`core/config.py:80`) — an invalid (zero/negative) value fails loudly at `Settings` construction,
not silently.

## 12. Concurrency / Overlap

**DECISION, binding**: no new distributed lock is introduced. **Grounded in existing safeguards,
re-verified this session, not merely asserted**:
- `NewsEvent.hash` carries a database-level `unique=True` constraint
  (`database/models/news_event.py:58`); `services/collector.py::_process_item()` wraps its insert
  in `session.begin_nested()` and explicitly catches `IntegrityError` as "duplicate, skip"
  (`services/collector.py:162-168`) — a concurrent duplicate insert is already correctly handled.
- `_claim_new_event()`/`_acquire_recovery_ownership()` are single, atomic, conditional `UPDATE`
  statements returning whether *this* call's attempt affected the row
  (`services/triage_orchestrator.py:45-67,107-138`) — explicitly designed, per their own
  docstrings, for safe concurrent/overlapping invocation.

**The single, sequential worker loop (§5) is chosen for efficiency and source-rate-limit respect,
not because correctness would otherwise be at risk** — both existing services are already safe
under concurrency by construction.

**Multiple accidental worker instances (operational risk, not a correctness risk)**: **DECISION**:
if two worker instances were ever run simultaneously (e.g., an operator error, or a future
multi-replica deployment with no further changes), **data remains correct** per the two safeguards
above — the only consequence is doubled, wasted external-API load and doubled `FloodWaitError`
exposure on Telegram sources. Documented as an operational risk (§28), not architected around here;
`docker-compose.yml` defines a single instance of every service, and no evidence in this repository
suggests multi-replica deployment is planned.

## 13. Failure Semantics

**DECISION, binding, per case — Case A corrected this revision (MINOR-2/Correction 5)**:

| Case | Behavior |
|---|---|
| **A. Collection completes with one or more source-level failures** | **Not a fatal case.** `run_collection_cycle()`'s own outer `try/except Exception` (`services/collector.py:53,68-69`) already guarantees the function **never propagates** an exception to its caller — a DB-connectivity failure, or any other internal error, is caught, logged ("Collection cycle aborted - could not connect to the database"), and an (possibly partial or empty) `CollectionReport` is returned normally. **Correction, replacing Revision 1's mischaracterization**: there is no reachable "collector throws a fatal exception to `worker/cycle.py`" scenario under the current, unmodified collector contract — Revision 1's Case A described a scenario that direct re-verification of `services/collector.py`'s source proves cannot occur. `worker/cycle.py` calls `run_collection_cycle()` and **always** receives a normal return; **triage still runs per §8's unconditional-invocation rule**, regardless of how many (if any) sources failed or whether collection itself hit an internal error. |
| **B. Triage raises an exception at the cycle level** | This is the real, reachable "unexpected failure" surface for a cycle: `run_triage_cycle()`'s own per-event try/except (§10) already isolates individual event failures, but if the cycle-level call itself raises (e.g., a DB outage at the top-level query, which — unlike collector — is **not** wrapped by any existing outer try/except inside `services/triage_orchestrator.py`, confirmed by direct re-read), the exception propagates out of `run_triage_cycle()` to `worker/cycle.py`. **`worker/cycle.py`'s own cycle-level handler (§14) is the only place this is caught** — logged, the process does not crash, and the loop proceeds to the next scheduled interval. |
| **C. One source fails, collector returns normally** | Already deterministic (§7) — no new decision needed; folded into Case A above. |
| **D. Database unavailable** | During collection: covered by Case A (collector's own internal catch, never propagates). During triage: covered by Case B (`worker/cycle.py`'s cycle-level catch). Either way: logged, process stays alive, retried at the next interval. |
| **E. Cycle succeeds** | Logged per §18; loop proceeds to sleep for the configured interval. |

**DECISION, binding — Correction 2 (MAJOR-2 resolution): exact exception-catch semantics, frozen.**
`worker/cycle.py`'s cycle-level failure handler (Case B) and `worker/main.py`'s loop **MUST** catch
`Exception` specifically — the same convention `services/collector.py` and every other
exception-boundary in this codebase already uses. They **MUST NOT** catch `BaseException` and
**MUST NOT** use a bare `except:`. This is not a stylistic preference: `asyncio.CancelledError`
inherits from `BaseException`, not `Exception`, since Python 3.8 — a handler written as `except
BaseException` or bare `except:` would silently swallow a cancellation/shutdown signal and continue
looping, breaking §14's graceful-shutdown guarantee. Concretely:

```python
try:
    await run_triage_cycle()
except Exception:
    logger.exception("Cycle failed, will retry next interval")
    # asyncio.CancelledError is NOT an Exception subclass — it is never caught here,
    # and propagates uncaught out of this handler and out of the loop.
```

**Frozen invariant, binding**: Cancellation (task cancellation, `SIGTERM`-triggered shutdown, or any
other `BaseException`-derived termination signal) **always propagates** out of the cycle body, out
of any interval-sleep (`asyncio.sleep()` is itself cancellable and re-raises `CancelledError`
correctly by construction — no special handling is added around it), and out of the run loop into
`main()`'s own `try/except (asyncio.CancelledError)` (§14) — which performs cleanup and lets the
process exit cleanly. The loop **MUST NOT** swallow a cancellation and continue sleeping or running
further cycles.

**DECISION, binding, explicit answer to "does triage run if all sources fail"**: **yes** —
`run_triage_cycle()` is called unconditionally after `run_collection_cycle()` returns (whether or
not any new events were created), because it also serves stale-`PROCESSING`-event recovery
(`services/triage_orchestrator.py`'s own existing, independent responsibility) — this must not be
skipped merely because a given cycle's collection produced zero new events. This is deterministic
and requires no future Planning judgment call.

**DECISION**: the worker process **survives** any single cycle's failure and always proceeds to the
next scheduled interval — no fail-fast shutdown on a transient cycle error. Only an explicit
shutdown signal (§14) stops the loop.

## 14. Startup / Shutdown

**DECISION, binding**: `worker/main.py`'s `main()` follows the same `asyncio.run(main())` shape
every existing entry point in this repository already uses (`bot/main.py`, every `scripts/run_*.py`
file). Graceful shutdown: the loop task is cancelled on a standard `asyncio` cancellation signal
(matching this project's own already-proven pattern from this session's own diagnostic scripts —
`asyncio.create_task()` + `task.cancel()` + `await task` inside a `try/except
(asyncio.CancelledError)`), ensuring no orphaned loop iteration and no dangling DB session. No new
shutdown framework is introduced solely for this purpose. `CancelledError` is caught **only** at
this outermost boundary, to perform cleanup and exit — never inside the per-cycle handler (§13),
per the frozen exception-catch semantics above.

**DECISION, binding — Correction 3 (MAJOR-3 resolution): one frozen disabled-state model.**
When `news_collection_enabled = False` at startup, the worker process **remains alive but idle** —
it never runs a collection or triage cycle, never accesses the database or any source, and exits
only on cancellation/`SIGTERM`. Exactly one model is frozen (not offered as options):

```python
async def main() -> None:
    setup_logging()
    if not settings.news_collection_enabled:
        logger.info("news_collection_enabled is False - automation worker idling, no cycles will run")
        try:
            await asyncio.Event().wait()   # never set; blocks indefinitely, cancellation-responsive
        except asyncio.CancelledError:
            logger.info("Automation worker shutting down (disabled, no cycle was ever run)")
            raise
        return
    # ... normal loop (§5) runs only when enabled ...
```

**Why this shape**: `asyncio.Event().wait()` on an Event that is never set blocks the coroutine
indefinitely without polling or busy-waiting, while remaining fully cancellation-responsive (it is
implemented on top of a `Future` and raises `CancelledError` correctly when the task is cancelled) —
no new synchronization primitive or library is introduced. This is deliberately chosen over having
`main()` return/exit immediately when disabled, because this process is deployed with
`restart: unless-stopped` (§15): an immediate, "successful" exit would cause Docker to restart the
container in a tight loop indefinitely (exit → restart → sees disabled → exit again), which is a
**bug this Contract explicitly forbids**, not an accepted risk. Under the frozen model, the
container starts once, logs its idle state once, and simply keeps running without doing anything —
identical in operational shape to `restart: unless-stopped` on any other steady-state service in
this `docker-compose.yml`.

**Frozen guarantees, binding**: while disabled, the worker (a) logs its idle state exactly once at
startup, not repeatedly; (b) calls neither `run_collection_cycle()` nor `run_triage_cycle()`; (c)
makes no database connection and no source-adapter call; (d) performs no tight/busy loop of any
kind; (e) responds to cancellation exactly as the enabled path does (§13's propagation invariant
applies identically here).

## 15. Runtime / Docker

**DECISION, binding — Correction 4 (MINOR-1 resolution): no Redis dependency.** Add exactly one new
service to `docker-compose.yml`, depending only on the services this worker's actual code path
requires:
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
**Correction, replacing Revision 1's snippet**: Revision 1 copied `REDIS_HOST`/a `redis`
`depends_on` entry from the `backend` service without checking whether the worker's actual code path
needs it. Re-confirmed this session: neither `services/collector.py` nor
`services/triage_orchestrator.py` (nor any module either imports) imports `redis` anywhere — a
repo-wide check of both files' import lists confirms this. The worker depends only on Postgres, the
one service its actual code path touches. **This correction is scoped to the worker service only —
`backend`'s own existing Redis dependency in `docker-compose.yml` is untouched**, since nothing in
this Contract's evidence concerns whether `backend` itself needs Redis.

`restart: unless-stopped` matches every existing service in `docker-compose.yml`
(`postgres`/`redis`/`backend`) exactly — no new restart-policy convention. **This service is kept
separate from `backend`** (the FastAPI health-check stub, `app/main.py`) **and from any future
containerized `bot` service** — one process, one responsibility, matching this codebase's own
established separation (`bot/` vs. `app/` vs. `scripts/` are already distinct today). Shares the
same built image (`build: .`) as `backend` — no second Dockerfile needed, since `worker/` becomes
part of the same installed package.

## 16. Configuration

**DECISION, binding — exactly two new `Settings` fields** (`core/config.py`):
```python
news_collection_enabled: bool = False
news_collection_interval_seconds: int = Field(default=1800, gt=0)
```
**`news_collection_enabled` defaults `False`** — matching this repository's own established,
repeated "opt-in by default" convention for exactly this risk profile (`enabled_providers: list[str]
= []`, `verify_capabilities_at_boot: bool = False` — both cited with their own Phase 7 rationale:
"no [X] goes live until explicitly opted in"). This is not a new principle invented for Phase 12 —
it is the same pattern this codebase already uses for comparable real-external-call/real-cost
capabilities. No new secret is introduced — Telegram/RSS/etc. source credentials are already
configured (`telegram_api_id`/`telegram_api_hash`/`telegram_session_string`, `core/config.py`).

## 17. Manual One-Shot Reuse

**DECISION, binding**: `scripts/run_collector.py` and `scripts/run_triage.py` remain exactly as
they are, untouched. `worker/cycle.py::run_automation_cycle()` calls the **same**
`run_collection_cycle()`/`run_triage_cycle()` functions these scripts already call — zero
duplicated business logic, confirmed compatible by direct inspection (§4/§6): neither function has
any CLI-specific coupling preventing this reuse.

## 18. Observability

**DECISION, binding**: reuse `CollectionReport` (`sources_processed`, `sources_failed`,
`events_created`, `duplicates_skipped`) and `TriageCycleReport` (`events_claimed`,
`events_recovered`, `tasks_created`, `claim_races_lost`, `duplicate_active_task_outcomes`,
`other_failures`) exactly as they exist — no modification to either dataclass. `worker/cycle.py`
logs one structured `logger.info` line per cycle combining both reports' fields plus cycle
start/end timestamps and duration (computed in `worker/cycle.py` itself, not inside either existing
report). No new monitoring platform, no metrics library, is introduced.

## 19. Dedup

**DECISION, binding**: Phase 12 relies exclusively on the existing exact-hash dedup
(`services/deduplication.py::is_duplicate()`) — sufficient, and only sufficient, for "the same
polled source item is not repeatedly inserted." Cross-source/semantic event clustering remains
explicitly deferred to a future phase (Decision Resolution §9/§13) — **no embedding/vector-database
dependency of any kind is introduced in Phase 12.**

## 20. Future Visual Requirement Protection

**DECISION/FINDING, restated exactly**: Phase 12 introduces **no new** destructive media-discard
behavior. The existing limitation (`integrations/sources/telegram_source.py::_to_raw_item()`
extracts only text/url/timestamp, discarding Telethon's available `.photo`/`.media`) is **pre-
existing, Phase-4-era behavior, unmodified by Phase 12** — and, per Decision Resolution §8's own
analysis, not irreversible: `NewsEvent.url` is preserved, enabling a future phase to re-fetch the
original message for media extraction, provided the source's message history remains available (a
disclosed assumption, not a guarantee). **No schema field is added now.** This remains named,
known technical debt for a future Visual Intelligence phase, not something Phase 12 must fix or
avoid worsening beyond "do not add a new discard mechanism," which it does not.

## 21. Public Publishing Exclusion

**DECISION, binding, restated exactly**: "Automation" in Phase 12's scope means **internal
newsroom processing only**. Phase 12 does not publish to any public Telegram channel, does not
schedule any public post, does not auto-approve any content, and does not deliver any generated
post externally. No code path introduced by Phase 12 sends a Bot-API message of any kind — the
worker never imports or uses `aiogram`/`bot.loader`/`bot.handlers` in any form.

## 22. Authorized File Scope

**DECISION, binding — exhaustive.**

**Existing files authorized for narrow edit**:
- `core/config.py` — add exactly the two `Settings` fields in §16.
- `docker-compose.yml` — add exactly the one service in §15 (no Redis dependency, per Correction 4).
- `pyproject.toml` — add `"worker"` to `[tool.hatch.build.targets.wheel]`'s `packages` list
  (mirroring how `"bot"` was already added when that package was introduced).
- **`services/collector.py` — EXISTING FILE AUTHORIZED FOR NARROW TESTABILITY EDIT (Correction 1,
  updated Revision 3).** The **only** permitted changes:
  1. Add the three defaulted, keyword-only parameters to `run_collection_cycle()`'s signature frozen
     in §7 (`session_factory`, `source_pack_loader`, `adapter_resolver_factory`), threaded through to
     the three call sites (`async_session_factory()`, `load_source_pack()`, `build_registry(...)`)
     that already exist inside the function body at those exact lines.
  2. Define the local `SourceAdapterResolver` `Protocol` (§7) inside `services/collector.py` — no new
     file, no addition to `services/adapter_registry.py`.
  3. Retype the existing `registry: AdapterRegistry` parameter on `_load_active_sources()` and
     `_process_source()` to `registry: SourceAdapterResolver` — **their bodies do not change**, only
     the type hint, since both already call solely `registry.resolve(source)`.
  4. Add the typing-only imports this requires (`typing.Protocol`, `collections.abc.Callable`,
     `sqlalchemy.ext.asyncio.async_sessionmaker`, `services.source_registry.SourceRegistryReport`,
     `services.adapter_registry.AdapterResolution`) — no new *behavioral* import, no new adapter, no
     new business-logic module.

  No other line of `services/collector.py` may change — no change to `_fetch_with_retry`,
  `_process_item`, `_compute_hash`, retry/backoff behavior, failure isolation, or the outer
  try/except (§13). **`services/adapter_registry.py` and `services/adapter_keys.py` are not edited
  by this correction** — `AdapterRegistry`/`build_registry`/`ADAPTER_KEY_TO_ADAPTER` are unchanged
  and continue to satisfy `SourceAdapterResolver` purely structurally, with no explicit relationship
  declared between them.

**New files authorized to create**:
- `worker/__init__.py` — docstring only, matching `bot/__init__.py`'s own convention.
- `worker/main.py` — the loop/startup/shutdown entry point (§5, §14), including the disabled-state
  idle path (§14 Correction 3).
- `worker/cycle.py` — `run_automation_cycle()` and its result dataclass (§6).

**Test files** (exact names not frozen beyond this level of specificity, matching every prior
phase's own convention):
- A test file for `worker/cycle.py`'s orchestration logic (e.g. `tests/test_worker_cycle.py`),
  including the cancellation and Case-A/B failure-semantics tests (§24).
- A test file for `worker/main.py`'s loop/shutdown/disabled-idle behavior (e.g.
  `tests/test_worker_main.py`).
- A test-only fake source-adapter double (e.g. `tests/fakes/fake_source_adapter.py`), containing
  **two** pieces, both test-owned, neither imported by production code: (a) a fake `SourceAdapter`
  implementing `integrations/sources/base.py::SourceAdapter`'s protocol, returning canned
  `RawNewsItem` objects with zero network I/O — mirroring this project's own existing `tests/fakes/`
  convention (e.g. `fake_gateway.py`); and (b) a small fake resolver object satisfying §7's
  `SourceAdapterResolver` `Protocol` (a `resolve(source) -> AdapterResolution | None` method
  returning an `AdapterResolution` wrapping the fake adapter above) — this fake resolver never
  constructs a real `AdapterRegistry` and never imports
  `services.adapter_keys.ADAPTER_KEY_TO_ADAPTER`.
- An integration test proving the real chain (fake source pack + fake resolver/adapter → real
  collector orchestration → real test database → real triage → `EditorialTask`) using the
  three-parameter DI seam (§7) and a real test database (e.g.
  `tests/test_automation_integration.py`), or added to an existing suitable file if Planning finds
  one — not frozen more precisely than this, per this Contract's own discretion-at-Planning-level
  convention (mirrors Phase 11 Contract §23's own precedent).
- **`tests/test_settings_phase7.py` — EXISTING FILE AUTHORIZED FOR NARROW TEST ADDITION (new this
  revision, Correction 2).** Add the mandatory Configuration tests (§24) for
  `news_collection_enabled`/`news_collection_interval_seconds` to this file — confirmed, by direct
  re-read, to be this repository's own established location for direct `Settings`-field
  default/override/validation tests (it already carries this exact pattern for `enabled_providers`,
  `verify_capabilities_at_boot`, `redis_unavailable_policy`, and — added after a later phase, not
  Phase 7 itself — `default_content_language`, proving new fields already land here regardless of
  which phase introduces them). No other test in this file may be modified.

**Files explicitly frozen** (§23's full list, restated here as this section's own binding
boundary).

**No broad directory is authorized.** No file outside this exhaustive list may be created or
edited to implement Phase 12.

## 23. Frozen Components

**DECISION, binding — MUST NOT MODIFY**, unless a future session finds direct, cited evidence
proving otherwise (none was found this session):

**`services/collector.py` is excluded from this list as of this revision** — it carries exactly one
narrow, exhaustively-specified authorized edit (§7/§22, Correction 1, updated Revision 3: three
defaulted keyword-only parameters added to `run_collection_cycle()`'s signature plus a local
`SourceAdapterResolver` `Protocol` definition and two retyped internal parameters; its body
otherwise unmodified). **Explicitly confirmed still fully frozen, named here precisely because this
correction pass traced their internals**: `services/adapter_registry.py` (`AdapterRegistry`,
`build_registry`, `AdapterResolution` — Revision 3's `SourceAdapterResolver` `Protocol` in
`services/collector.py` satisfies compatibility with this class purely structurally, with zero
change to this file) and `services/adapter_keys.py` (`ADAPTER_KEY_TO_ADAPTER` and every adapter
singleton it holds — untouched, never monkeypatched, never mutated). Every other file below remains
fully frozen: every file under `integrations/sources/` (adapters), `services/deduplication.py`,
`services/triage.py` (scoring logic), `services/triage_orchestrator.py`, `services/workflow_service.py`,
`workflows/runner.py`, every file under `workflows/definitions/`, `capabilities/executor.py`,
`capabilities/registry.py`, every `capabilities/*_capability.py`, `capabilities/capability_mapping.py`
(including the `"engagement"` alias — not touched, not resolved, not removed),
`integrations/llm_gateway/**`, `integrations/prompts/**`, `services/content_draft_service.py`,
`scripts/run_content_generation.py`, every file under `database/models/`, every Alembic migration
file, `database/session.py`, `bot/**` (the entire Telegram Editorial Inbox and bot layer),
`schemas/editorial_inbox.py`, `schemas/editorial_task.py`, `schemas/workflow.py`,
`scripts/run_collector.py`, `scripts/run_triage.py` (preserved unchanged, §17).

**No evidence surfaced this session that any of the above requires amendment.**

## 24. Testing Requirements

Binding minimums:

**Worker/cycle tests** (`worker/cycle.py`, `worker/main.py`):
- One cycle invokes `run_collection_cycle()` then `run_triage_cycle()`, in that exact order
  (verifiable by patching both names at the `worker.cycle` module boundary — mirroring Phase 11's
  own proven handler-test-double convention — not by requiring a real DB for this specific test).
- Triage runs exactly once per cycle, unconditionally, even if collection reports zero new events
  (§13).
- Mechanical AST import-boundary test: `worker/cycle.py` and `worker/main.py` import neither
  `workflows.runner`, `capabilities.executor`, any `capabilities.*_capability`, nor
  `scripts.run_content_generation` — proving the `NEWS_ANALYSIS`/`CONTENT_GENERATION` boundary (§9)
  mechanically, mirroring every prior phase's own established convention.
- A simulated `Exception` from the mocked `run_triage_cycle()` call is caught by the cycle-level
  handler; the loop does not crash and proceeds to the next interval (§13 Case B).
- The loop respects the configured interval (verifiable with a short, test-only interval and a
  bounded number of iterations, avoiding real `asyncio.sleep(1800)` in the suite).

**Cancellation tests (Correction 2, MAJOR-2 — new this revision, mandatory)**:
- `asyncio.CancelledError` raised from within a mocked cycle call **propagates** out of the
  cycle-level handler and out of the loop — it is not caught, logged, or swallowed as an ordinary
  failure (proving the `except Exception`, not `except BaseException`/bare `except:`, rule in §13).
- After a cancellation, no further cycle is scheduled or started (no "one more sleep then continue"
  behavior).
- `main()`'s outer `try/except (asyncio.CancelledError)` runs its cleanup path and the coroutine
  returns/exits without an unhandled exception propagating out of `main()` itself.
- A static/source check (grep or AST) confirms no `except BaseException` and no bare `except:`
  exists anywhere in `worker/cycle.py` or `worker/main.py`.

**Disabled-mode tests (Correction 3, MAJOR-3 — new this revision, mandatory)**:
- With `news_collection_enabled=False`, running `main()` calls neither `run_collection_cycle()` nor
  `run_triage_cycle()` (verifiable via mocked/patched call-count assertions of zero).
- The disabled path remains cancellation-responsive: cancelling the running `main()` task while
  idle raises/propagates `CancelledError` promptly (bounded-time test, not a real indefinite wait).
- No tight/busy loop: the idle path is a single `await`, not a `while True` with a short sleep —
  verifiable by asserting the idle coroutine suspends immediately (no CPU-bound spin) and logs its
  idle state exactly once, not repeatedly, over the test's bounded duration.

**Testability/integration tests (Correction 1, MAJOR-1 — mandatory, updated Revision 3 to close the
re-audit's traced adapter-singleton gap)**:
- `run_collection_cycle()` invoked with a fake `source_pack_loader` (returning a small, controlled
  `SourceDefinition` list) and a fake `adapter_resolver_factory` (returning a test-owned object
  satisfying `SourceAdapterResolver`, wrapping a fake, network-free `SourceAdapter` that returns
  canned `RawNewsItem`s) and a real test `session_factory` persists the expected `NewsEvent` row(s)
  into a real test database — proving the real orchestration path (`_load_active_sources`,
  `_process_source`, `_fetch_with_retry`, `_process_item`, exact-hash dedup) end-to-end with **no
  live network call of any kind**.
- **Mandatory, specific to the re-audit's finding**: a test asserts the fake resolver/adapter path
  never imports or references `services.adapter_keys.ADAPTER_KEY_TO_ADAPTER` and never constructs a
  real `AdapterRegistry` — i.e., that the injected `adapter_resolver_factory` genuinely bypasses the
  real singleton map rather than merely wrapping it. The simplest sufficient proof: the fake
  resolver class lives entirely in `tests/fakes/fake_source_adapter.py` with no import of
  `services.adapter_registry`/`services.adapter_keys`, and the integration test's fake
  `SourceDefinition`(s) use a `url`/`adapter` value that would fail or hang if a real network call
  were ever attempted — making a silent fallback to a real adapter fail the test rather than pass it
  unnoticed.
- Calling `run_collection_cycle()` with zero arguments still resolves every parameter to its
  documented production default (`async_session_factory`, `load_source_pack`, `build_registry`) and
  **still correctly resolves real adapters exactly as before this correction** (a non-integration,
  fast unit test may assert `build_registry([...a real SourceDefinition...]).resolve(...)` still
  returns the expected real adapter type — proving the `Protocol` retype changed nothing about
  `AdapterRegistry`'s own behavior).
- **Source-failure test**: the fake resolver/adapter is configured so one source's fetch raises;
  the cycle-level result still reflects the other, successful source(s) and the failed source
  increments `report.sources_failed` — exercising the real, existing failure-isolation code (§7),
  now provable without a live network call.

**Dedup test**: running the same cycle twice against the same fake source data does not create a
second `NewsEvent` for the same item.

**Triage integration test**: after a real collection pass (via the fake seam above) persists at
least one new `NewsEvent`, the automatic triage call creates the expected
`EditorialTask(NEWS_ANALYSIS, CREATED)` — and a **mechanical** check confirms no `AIExecution` row
and no workflow-runner side effect exists afterward (zero rows, not merely "no exception").

**Configuration tests (file authorized in §22, Correction 2)**: added to
`tests/test_settings_phase7.py` — `news_collection_enabled` defaults `False`; overridable via env;
`news_collection_interval_seconds` defaults `1800`; overridable via env; `gt=0` validation rejects
zero/negative values at `Settings` construction (matching this file's own existing
default/override/validation test shape, e.g. `test_enabled_providers_defaults_to_empty_list`,
`test_default_content_language_is_overridable_via_env`).

**No live external Telegram/RSS/API call anywhere in the automated suite** — matching this
project's unbroken discipline since Phase 7. This is now achieved by the DI seam above, not by
monkeypatching unsafe global module state as the primary or only test strategy.

## 25. Integration Proof

**DECISION, binding — concrete seam frozen this revision (Correction 1, corrected Revision 3)**:
one real-database integration test proving the full in-scope chain, using `run_collection_cycle()`'s
three injectable parameters (§7): a fake `source_pack_loader` supplies a small, controlled
`SourceDefinition` list; a fake `adapter_resolver_factory` returns a test-owned object satisfying
`SourceAdapterResolver` (`tests/fakes/fake_source_adapter.py`, §22) — this object wraps a fake,
network-free `SourceAdapter` returning canned `RawNewsItem` objects, and is constructed **without**
building a real `AdapterRegistry` and **without** consulting
`services.adapter_keys.ADAPTER_KEY_TO_ADAPTER` at any point; a real test `session_factory` feeds
the real, unmodified collector orchestration
(`_load_active_sources`/`_process_source`/`_fetch_with_retry`/`_process_item`) and real
`services/deduplication.py` persistence path against a real test database. Immediately after, the
real, unmodified `run_triage_cycle()` runs against the same test database, confirming the expected
`NewsEvent` and `EditorialTask(NEWS_ANALYSIS, CREATED)` rows exist, and mechanically confirming zero
`WorkflowRunner`/`CONTENT_GENERATION`/`ContentDraft` side effect occurred. **No external network
call of any kind (Telegram/RSS/arXiv/GitHub/HN/OpenAI) is made by this test, and no production
credential is read** — this is now a traced, structural guarantee (the fake resolver's `resolve()`
method returns the fake adapter directly; there is no code path by which the real
`ADAPTER_KEY_TO_ADAPTER` map or any real `SourceAdapter` implementation is ever reached), not an
unverified assumption about `AdapterRegistry`'s internals. No monkeypatching of any global state is
required to achieve this.

## 26. Manual Live Acceptance

**DECISION, binding — one manual, human-authorized live test, not executed during Contract
writing**: start the real Phase 12 worker (`news_collection_enabled=True`); confirm no developer
manually invokes the collector for the duration of the test; identify one genuinely new item in a
real, already-configured source (or a safely-controlled equivalent); confirm the worker's next
scheduled cycle automatically detects and persists it as a new `NewsEvent`; confirm the *following*
cycle's dedup correctly does not re-insert it; confirm Triage runs automatically and the expected
`EditorialTask(NEWS_ANALYSIS, CREATED)` appears; confirm, by direct database inspection, that
`WorkflowRunner` was never invoked (no `AIExecution` row, task remains `CREATED`) and no
`ContentDraft` was created by this phase's own operation.

## 27. Definition of Done

1. A dedicated automation worker (`worker/main.py`) exists and starts cleanly.
2. Global cadence is configurable (`news_collection_interval_seconds`).
3. Collection runs automatically on the configured interval.
4. Triage runs automatically, immediately after collection, every cycle.
5. Repeated polling does not duplicate a previously-collected source item.
6. Per-source failure isolation is preserved exactly as it exists today.
7. The worker survives and logs any single cycle's failure, per §13's frozen semantics.
8. No overlapping self-cycles (single sequential loop, §5/§12).
9. No `NEWS_ANALYSIS` execution occurs.
10. No `WorkflowRunner` invocation occurs.
11. No `ContentDraft` is generated by this phase.
12. No `EngagementCapability` is implemented.
13. No public publishing occurs.
14. No migration exists anywhere in the diff.
15. Existing collector/Triage semantics are byte-for-byte preserved (no modification to any frozen
    file in §23).
16. Every mandatory automated test (§24) exists and passes.
17. The full repository regression suite passes.
18. `ruff check .` passes clean.
19. Targeted `mypy` passes clean on every changed/new file.
20. `python -m scripts.validate_architecture` reports 0 violations.
21. Secret/security hygiene passes.
22. The one manual live scheduled-ingestion acceptance test (§26) passes.

## 28. Risks

- **Multiple worker instances** (§12): correctness is preserved by existing safeguards; the only
  consequence is doubled source-API load and doubled rate-limit exposure — mitigated by
  `docker-compose.yml` defining a single instance, not by new application-level locking.
- **Source rate limits**: `services/collector.py`'s existing `FloodWaitError` handling
  (skip-for-this-cycle, no retry) is unchanged and already accounts for this; running on a schedule
  increases exposure frequency proportionally to how short the configured interval is.
- **Long-running cycles**: because the loop is `run cycle → sleep interval` (not wall-clock-fixed),
  a cycle taking longer than the configured interval simply extends the effective start-to-start
  cadence — disclosed, not a defect, no new mechanism needed to handle it.
- **Stale source credentials/session** (e.g., an expired Telethon `StringSession`): would surface
  as a per-source (or, for Telegram specifically, potentially all-Telegram-sources) failure, caught
  and logged per §13 — the worker does not crash, but repeated failure would go otherwise
  unnoticed without external monitoring (out of this Contract's own scope to build).
- **`NEWS_ANALYSIS` task buildup**: `CREATED` tasks accumulate indefinitely until a future phase
  executes them — no data-integrity or cost impact, disclosed explicitly (Decision Resolution §22,
  restated with explicit monitoring obligation in §10 this revision). Accepted temporary
  operational debt; must be observed via direct database inspection during Manual Live Acceptance
  (§26), not solved by Phase 12 invoking `NEWS_ANALYSIS`/`EngagementCapability`.
- **Database growth**: `NewsEvent`/`EditorialTask` row counts grow continuously once automation is
  enabled — no retention/archival policy exists or is introduced here; a future operational concern,
  not a Phase 12 blocker.
- **Existing media discard** (§20): unchanged, disclosed, not worsened.
- **Triage reprocessing behavior**: none — re-confirmed (§10) that repeated cycles cannot create
  duplicate active tasks; no reprocessing risk exists.
- **Docker restart loop**: `restart: unless-stopped` combined with a genuinely fatal *startup*
  error (e.g., missing required credentials, `Settings` construction failure) would cause repeated
  container restarts — identical risk profile to every other service already using this same
  policy in `docker-compose.yml`, not a new class of risk Phase 12 introduces. **Explicitly not a
  risk when `news_collection_enabled=False`**: §14's frozen disabled-state model (Correction 3)
  keeps the process alive and idle rather than exiting, so the disabled configuration itself can
  never trigger this restart loop.

## 29. Canonical Rules

1. Phase 12 automates collection + existing Triage only — nothing further downstream.
2. One dedicated, single-purpose async worker process; no Celery, no APScheduler.
3. One sequential cycle at a time per worker instance; no overlapping self-cycles.
4. One global, configurable cadence; no per-source cadence, no new database column.
5. Existing collector logic is reused, unmodified.
6. Existing exact-hash dedup is reused, unmodified.
7. Existing Triage is reused, unmodified, including its scoring formula.
8. `NEWS_ANALYSIS` tasks may be created (inherited from Triage) but are never executed by Phase 12.
9. No `WorkflowRunner` invocation anywhere in Phase 12's own code.
10. No `ContentDraft` creation anywhere in Phase 12's own code.
11. No engagement/reach intelligence is implemented in Phase 12.
12. No media/image handling is implemented in Phase 12.
13. No public publishing exists in Phase 12, in any form.
14. No migration exists in Phase 12.
15. The manual one-shot path (`scripts/run_collector.py`/`scripts/run_triage.py`) remains fully
    usable and unmodified.
16. `run_collection_cycle()`'s only Phase 12 change is three defaulted, keyword-only injectable
    parameters (`session_factory`, `source_pack_loader`, `adapter_resolver_factory`) plus a local
    `SourceAdapterResolver` `Protocol`; called with zero arguments in production, behavior is
    byte-for-byte identical to before any Phase 12 correction. `services/adapter_registry.py` and
    `services/adapter_keys.py` are never edited — the injected resolver bypasses them structurally,
    not by modifying them.
17. Cycle-level and loop-level exception handling catches `Exception` only — never `BaseException`,
    never a bare `except:`. `asyncio.CancelledError` always propagates uncaught.
18. When disabled (`news_collection_enabled=False`), the worker process stays alive and idles
    (cancellation-responsive, no cycles, no DB/source access, no busy loop) — it never exits
    immediately, and therefore never causes a Docker restart loop.
19. The worker service depends only on the services its actual code path requires (Postgres) — no
    dependency is inherited from another service without evidence it is actually needed.

## 30. Acceptance Checklist

Self-audited before submission:

1. **Did I accidentally authorize `NEWS_ANALYSIS` execution?** No — §9/§23 explicitly forbid any
   `WorkflowRunner`/`capabilities.executor` import in the new module, mechanically enforced by
   §24's AST test.
2. **Did I accidentally authorize `EngagementCapability`?** No — §3/§23 explicitly exclude it;
   `capabilities/capability_mapping.py`'s existing alias is untouched.
3. **Did I accidentally authorize `ContentDraft` creation?** No — no path to
   `services/content_draft_service.py` exists anywhere in the authorized scope.
4. **Did I introduce Celery/APScheduler without evidence?** No — §5 explicitly rejects both, with
   the dependency-list evidence cited.
5. **Did I duplicate collector or Triage logic?** No — §6/§17 both state and verify zero
   duplication; the new module only calls existing functions.
6. **Is failure behavior deterministic?** Yes — §13's per-case table leaves nothing to Planning's
   invention.
7. **Is multiple-worker risk honestly documented?** Yes — §12/§28, including the explicit
   concession that correctness (not just performance) claims rest on already-existing safeguards,
   not a new one.
8. **Is exact file scope exhaustive?** Yes — §22, three new files, three config/build edits, no
   broad directory.
9. **Is Docker/runtime topology deterministic?** Yes — §15, one named service, exact command,
   exact policy.
10. **Can Implementation Planning proceed without inventing new architecture?** Yes — every module
    name, function boundary, configuration field, failure case, and test obligation is frozen at
    implementation-actionable precision; the only items left to Planning's own discretion are
    genuinely cosmetic (exact test file naming, exact loop-timeout technique for tests).
11. **Is the collection-cycle testability seam concretely named and feasible without live
    network/monkeypatching-as-the-only-strategy?** Yes — §7 freezes the exact three parameters
    (including the `SourceAdapterResolver` `Protocol` retype), §22 authorizes the exact narrow edit
    to `services/collector.py`, §25 traces the exact fake-loader → fake-resolver/adapter →
    real-orchestration → real-DB chain.
11a. **Does the seam actually reach the real adapter-instance resolution point, or does a hidden
    singleton lookup remain?** No hidden lookup remains — §4/§7 trace `AdapterRegistry.resolve()`'s
    dependency on `ADAPTER_KEY_TO_ADAPTER` exactly, and close it by retyping the injected parameter
    to a structural `Protocol` a test-owned resolver can satisfy without ever constructing a real
    `AdapterRegistry` or importing `ADAPTER_KEY_TO_ADAPTER`.
11b. **Is `services/adapter_registry.py`/`services/adapter_keys.py` modified to achieve this?** No —
    §22/§23 explicitly confirm both are untouched; the fix is a type-level narrowing at the
    consuming end (`services/collector.py`) only.
11c. **Is the mandatory Configuration test file explicitly authorized?** Yes — §22 authorizes a
    narrow addition to `tests/test_settings_phase7.py`, confirmed by direct re-read to be this
    repository's own established location for exactly this kind of test.
12. **Can `CancelledError` be silently swallowed anywhere in the frozen design?** No — §13 freezes
    `except Exception` only, explicitly forbids `BaseException`/bare `except:`, and §24 adds a
    mandatory test plus a static check for this.
13. **Can the disabled configuration cause a Docker restart loop?** No — §14 freezes a single idle-
    while-alive model; §28 explicitly documents why the restart-loop risk does not apply to this
    case.
14. **Is the worker's Redis dependency justified by evidence?** No dependency remains — §15 removes
    it after re-confirming neither collector nor triage imports `redis`.
15. **Does the failure table describe any scenario that cannot actually occur in the current
    source?** No — §13's Case A is corrected to match `run_collection_cycle()`'s own proven
    never-propagates behavior; the real reachable failure surface (triage-level exception) is
    named exactly.
16. **Does production behavior of `run_collection_cycle()` change by default after this revision?**
    No — §7 freezes that every new parameter defaults to the exact value already hardcoded before
    this revision; zero-argument call sites (§6/§17) are unaffected.
17. **Was `NEWS_ANALYSIS` execution, `EngagementCapability`, or any other frozen-out-of-scope item
    reintroduced by this correction pass?** No — §2/§3/§9/§23's exclusions are unchanged; §10 adds
    only a monitoring/framing clarification, not new execution logic.

**No self-audit question surfaced a defect requiring correction before submission.**

---

PHASE 12 CONTRACT REVISION 3 — READY FOR RE-AUDIT
