# Phase 12 — Fresh News Automation Targeted Contract Re-Audit

Re-audit only. No Contract, Decision Resolution, production code, test, or migration file was
modified to produce this document. Every claim below was independently re-verified against current
source this session (cited file:line), including files not previously re-read in the correction
pass.

## 1. Executive Verdict

**4 of 5 original findings (all 3 MAJOR-labeled corrections' framing, both MINORs) are correctly
and completely resolved.** However, direct re-verification of the actual call chain behind
Correction 1's new `registry_builder` parameter surfaces **one new MAJOR finding**: the revised
Contract's own claim that `registry_builder` "lets a test map [a `SourceDefinition` list] to a fake
`SourceAdapter`" is not true as literally specified, because `AdapterRegistry.resolve()` — the
method actually called by `_load_active_sources()`/`_process_source()` — internally resolves
through a separate, hardcoded, non-injectable module-level dictionary
(`services/adapter_keys.py::ADAPTER_KEY_TO_ADAPTER`) that the frozen three-parameter seam never
names or routes around. A real `AdapterRegistry` instance, constructed exactly as the parameter's
own type annotation (`Callable[[list[SourceDefinition]], AdapterRegistry]`) demands, always resolves
to a **real, network-capable adapter singleton** — never a fake one — regardless of what
`source_pack_loader`/`registry_builder` a test supplies. This is a genuine fourth hidden dependency,
exactly the class of gap Check 1 was designed to catch. One MINOR finding is also newly surfaced: an
exhaustive-file-list contradiction between §22 and §24 over where the mandatory Configuration tests
live.

## 2. Previous Findings Resolution

| # | Original finding | Resolution status |
|---|---|---|
| MAJOR-1 | Integration test seam undisclosed/infeasible (source-pack hardcoding) | **Partially resolved.** `session_factory`/`source_pack_loader` are genuinely sufficient and correctly frozen. `registry_builder`'s stated purpose (substituting a network-free fake adapter) does not actually work as specified — see §3/§12 new finding below. |
| MAJOR-2 | Cancellation/shutdown exception semantics unfrozen | **Fully resolved.** See §5. |
| MAJOR-3 | Disabled-state behavior unfrozen, restart-loop risk | **Fully resolved.** See §6. |
| MINOR-1 | Unjustified Redis dependency in worker's Docker service | **Fully resolved.** See §8. |
| MINOR-2 | Failure table described an unreachable collector-fatal case | **Fully resolved.** See §7. |

## 3. Collector DI Verification

Re-read `services/collector.py` (current working tree) directly:

- `run_collection_cycle()`'s frozen signature (`session_factory`, `source_pack_loader`,
  `registry_builder`, all keyword-only, all defaulted) matches the Contract's §7 wording exactly,
  and each default (`async_session_factory`, `load_source_pack`, `build_registry`) is the exact
  object already hardcoded before this revision — **Check 2 (production-behavior preservation)
  passes**: calling with zero arguments is byte-for-byte identical to pre-revision behavior.
- `_load_active_sources(session, registry)` and `_process_source(session, source, registry, report)`
  call only `registry.resolve(source)` — no `isinstance` check, no other method — so a duck-typed
  substitute for `registry` is structurally accepted at runtime. **This is the one part of the seam
  that does work as intended, but only if the injected object is not a genuine `AdapterRegistry`.**
- Re-read `services/adapter_registry.py::AdapterRegistry.resolve()` directly (lines 75-95): it does
  **not** use whatever `url_index`/`definition_index` a custom `registry_builder` populated to
  decide the *adapter object itself* — it uses them only to decide the adapter *key* (a string), then
  does `adapter = ADAPTER_KEY_TO_ADAPTER.get(adapter_key)` (line 86), where `ADAPTER_KEY_TO_ADAPTER`
  is imported at module scope from `services/adapter_keys.py`.
- Re-read `services/adapter_keys.py` directly (lines 45-66): `ADAPTER_KEY_TO_ADAPTER` is a **fixed,
  module-level dict of real, singleton adapter instances**, built once at import time —
  `TelegramSourceAdapter()`, `RSSSourceAdapter()`, `GitHubSourceAdapter()`,
  `HackerNewsSourceAdapter()`, `ArxivSourceAdapter()` — every one of them a real, network-calling
  implementation. It is not a parameter anywhere in the frozen DI seam.

**Consequence, traced exactly**: a test that supplies `registry_builder=build_registry` (the
production default, or any function that constructs a genuine `AdapterRegistry(url_index,
definition_index)` as its own type annotation directs) will, for any `SourceDefinition` whose
`adapter` field names an implemented key (e.g. `"rss"`), resolve to the **real**
`RSSSourceAdapter()` singleton — not a fake — because `resolve()`'s adapter lookup never consults
anything the test passed in. **This directly contradicts §7's own worked claim** ("registry_builder
lets a test map that list to a fake SourceAdapter") and **§25's Integration Proof claim** ("no
external network call of any kind... the fake adapter never opens a socket").

**This is answered by Check 1's own explicit rule: a fourth hidden, non-injectable dependency
(`services/adapter_keys.py::ADAPTER_KEY_TO_ADAPTER`) still forces live-adapter resolution → MAJOR.**

**Note on severity, not a mitigation**: this is narrow and mechanically fixable — e.g. a test-side
fake can *subclass* `AdapterRegistry` and override `resolve()` entirely (bypassing
`ADAPTER_KEY_TO_ADAPTER` without ever calling it), or the Contract could name a second, explicit,
narrow monkeypatch of the `ADAPTER_KEY_TO_ADAPTER` dict as an accepted, disclosed exception to the
"no monkeypatching as the only strategy" rule. Either fix is a few sentences of Contract text, not a
redesign. But as currently frozen, the Contract's own concrete feasibility claim for §25's
Integration Proof is not actually true of the mechanism it names, and Planning would have to invent
this decision — failing Check 16's determinism bar for this one specific point.

## 4. Integration-Test Feasibility

- `session_factory` injection: **feasible, verified** — `run_collection_cycle()` opens its session
  via `async with session_factory() as session:` (unchanged call shape); a test `async_sessionmaker`
  bound to a test database satisfies this with no further gap.
- `source_pack_loader` injection: **feasible, verified** — `load_source_pack()`'s only consumer
  inside `run_collection_cycle()` is `definitions, _registry_report = source_pack_loader()`; a test
  callable returning a small, controlled `(list[SourceDefinition], SourceRegistryReport)` tuple
  satisfies this exactly, no hidden second dependency found.
- `registry_builder` injection: **not feasible as literally specified — see §3.** The seam is only
  complete once the Contract also either (a) authorizes a test-side `AdapterRegistry` subclass that
  overrides `resolve()`, or (b) authorizes a narrow, explicit monkeypatch of
  `services.adapter_keys.ADAPTER_KEY_TO_ADAPTER`. Neither is currently named.
- Downstream triage step: re-confirmed `run_triage_cycle(session_factory=...)` (unchanged,
  pre-existing DI) composes cleanly with the same test session factory, and creates
  `EditorialTask(NEWS_ANALYSIS, CREATED)` without invoking `WorkflowRunner` — `workflow_service.py`
  imports no capability/workflow-runner module (re-confirmed this session, §11 below). **This half
  of the chain is fully feasible, unchanged from the prior audit's own finding.**

## 5. Cancellation / Shutdown Verification

Re-confirmed: `asyncio.CancelledError` has inherited from `BaseException` (not `Exception`) since
Python 3.8, and this project's `pyproject.toml` requires `python>=3.12` — the invariant applies
throughout. The frozen `except Exception:` handler (§13) structurally cannot catch it; no wording
anywhere in the revised Contract introduces a `BaseException`/bare-`except` handler at cycle or loop
level. §14's disabled-idle path uses the identical `except asyncio.CancelledError: ... raise`
shape, so cancellation during idle-wait also propagates correctly. §24 adds explicit mandatory
tests for propagation-during-cycle, no-next-cycle-after-cancel, and a static
`except BaseException`/bare-`except` grep check. **No gap found — Check 4/5 both pass.**

## 6. Disabled-State Verification

Re-confirmed the frozen model (§14): idle via `await asyncio.Event().wait()` on a never-set Event —
this is a standard, correct, cancellation-responsive indefinite wait (implemented on a `Future`
internally; raises `CancelledError` cleanly on task cancellation), with no polling and no periodic
wake. No DB or source access occurs before or during the idle branch — `settings` is the same
process-wide singleton every entry point already loads (`core/config.py:117`), not a new side
effect. The model explicitly avoids the `restart: unless-stopped` + immediate-exit combination that
would cause a Docker restart loop. **No contradiction found elsewhere in the document suggesting an
immediate-exit alternative. Check 6/7 both pass.**

## 7. Failure-Semantics Verification

Re-confirmed directly against current source:
- `run_collection_cycle()`'s outer `try/except Exception:` (`services/collector.py:53,68-69`)
  unconditionally catches and never re-raises — the revised Case A's "never propagates" claim is
  accurate.
- `run_triage_cycle()` (`services/triage_orchestrator.py:222-300`) has **no** outer
  `try/except` wrapping its body — a top-level failure (e.g., the initial `select(NewsEvent)` query
  failing) would propagate uncaught out of the function, exactly as the revised Case B states.
- No other propagating collection-side exception path was found; the revised table's Case
  A/B split is accurate and complete. **Check 9 passes, no omitted path identified.**

## 8. Runtime / Docker Verification

Re-confirmed via direct import inspection: neither `services/collector.py`,
`services/triage_orchestrator.py`, nor `services/workflow_service.py` (the one additional module
the triage path reaches into, for `create_task()`) imports `redis`, `RateLimiter`, or `CostTracker`
anywhere (`services/workflow_service.py`'s full import list re-read: only `sqlalchemy`,
`database.models.*`, `schemas.*`, `workflows.errors`, `workflows.registry` — no `redis`-adjacent
module). The modules that *do* use Redis-backed cost/rate-limiting
(`services/budget_guard.py`, `services/cost_tracker.py`) are reached only through the AI Capability
layer, which Phase 12's own frozen boundary (§9/§23) never invokes. **Removing the worker's Redis
dependency is correct and complete — Check 8 passes, no contradiction found.** `backend`'s own
Redis dependency in `docker-compose.yml` is untouched, as required.

## 9. File Scope Verification

Re-confirmed the 7-item scope (3 new files, 4 narrow existing-file edits) is otherwise accurate and
necessary:
- `pyproject.toml`'s `packages` list must include `"worker"` for `pip install .` to install it as an
  importable package — confirmed necessary (`Dockerfile:8-11` does `COPY . .` then `pip install .`,
  which builds and installs a wheel scoped by `pyproject.toml`'s own `packages` list).
- No `Dockerfile` change is needed — `COPY . .` already copies the full source tree including a
  future `worker/` directory before `pip install .` runs; `worker.main` becomes invocable via
  `python -m worker.main` once installed. **Confirmed no hidden Dockerfile requirement — Check 11's
  conditional MAJOR does not trigger.**
- `docker-compose.yml`'s proposed `command`/`depends_on`/`environment` are all satisfiable from the
  same built image as `backend`, no second image needed.

## 10. Test Scope Verification

The three worker-specific test files and the fake-adapter test double are correctly scoped and
sufficient for what they cover. However: **§24 mandates "Configuration tests" for the two new
`Settings` fields** (`news_collection_enabled`, `news_collection_interval_seconds`,
default/override/`gt=0` validation, "mirroring `tests/test_settings_phase7.py`'s own established
pattern") **but §22's exhaustive test-file list names no file for them** — neither an extension to
`tests/test_settings_phase7.py` (confirmed to exist, `tests/test_settings_phase7.py`) nor a new
file. §22 states "No file outside this exhaustive list may be created or edited to implement Phase
12," which — read literally — leaves the mandatory Configuration tests with no authorized home.
This is a mechanical omission, not a design gap: the fix is one line (e.g., authorizing an
extension of `tests/test_settings_phase7.py` or a new `tests/test_worker_config.py`). **Classified
MINOR** — it does not require inventing new architecture, does not block feasibility, and has an
obvious one-line resolution, unlike the §3 finding.

## 11. NEWS_ANALYSIS / Task-Buildup Non-Regression

Re-confirmed §9/§10/§23 wording: the boundary is unchanged (Triage may create
`NEWS_ANALYSIS(CREATED)`; Phase 12 never executes it), duplicate-active-task protection is
unmodified and still cited from source, `CREATED`-task accumulation is explicitly named as accepted
temporary operational debt, and §10/§26/§28 now explicitly require it be observed (row-count/age via
direct DB inspection) during Manual Live Acceptance — not solved via `NEWS_ANALYSIS` execution. No
wording anywhere suggests or permits Planning to "fix" this by starting `WorkflowRunner`. **No
regression found.**

## 12. Findings

### CRITICAL

None.

### MAJOR

**M1 — `registry_builder` does not actually enable a network-free fake adapter (new finding).**
`services/adapter_registry.py::AdapterRegistry.resolve()` (lines 75-95) resolves the actual adapter
object via the module-level, non-injectable `services/adapter_keys.py::ADAPTER_KEY_TO_ADAPTER` dict
of real, network-calling adapter singletons — not via anything a `registry_builder` callable
supplies. A test using the seam exactly as §7 types it (`Callable[[list[SourceDefinition]],
AdapterRegistry]`, e.g. the production default `build_registry` fed a test source pack) will always
resolve to a **real** adapter, contradicting §7's own worked example and §25's "no external network
call of any kind... never opens a socket" claim. Fix is narrow: the Contract must explicitly
authorize one concrete mechanism — either (a) a test-side `AdapterRegistry` subclass overriding
`resolve()` to bypass `ADAPTER_KEY_TO_ADAPTER` entirely (no production file touched, no type
contradiction), or (b) a disclosed, narrow monkeypatch of `ADAPTER_KEY_TO_ADAPTER` itself as an
explicit exception to the "no monkeypatching as the only strategy" rule. This does not reopen
MAJOR-1's design (Option A vs. B, session_factory, source_pack_loader all remain correct) — it is
one missing sentence closing the one part of the three-parameter seam that doesn't yet work as
claimed.

### MINOR

**N1 — §22/§24 exhaustive-file-list contradiction for Configuration tests.** §24 mandates
Configuration tests for the two new `Settings` fields; §22's exhaustive authorized-file list names
no file for them (not `tests/test_settings_phase7.py`, not a new file). One line closes this — e.g.
authorize extending `tests/test_settings_phase7.py`, matching how §22 already handles the
integration-test file's "or added to an existing suitable file" discretion.

### OBSERVATIONS

- Everything re-verified in §3–§11 that is *not* flagged above is confirmed correct, evidence-backed,
  and requires no further correction.
- The M1 fix, once written, should also update §25's Integration Proof wording (currently asserts
  the fake adapter "never opens a socket" as an unqualified fact, when it is only true once the
  chosen mechanism from M1's fix is actually in place).

## 13. Readiness Score

**7/10.** Four of five original findings are cleanly and completely resolved with no regression.
The one new MAJOR is narrow, mechanically fixable in a short Contract addendum, and does not
reopen any previously-approved design decision — but per this audit's own approval bar
(CRITICAL=0, MAJOR=0), it is disqualifying as submitted.

## 14. Final Verdict

PHASE 12 CONTRACT NOT READY — CORRECTIONS REQUIRED
