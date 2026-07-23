# Phase 12 — Fresh News Automation Contract Adversarial Audit

Independently verifies `docs/phase12_fresh_news_automation_architecture_contract.md` ("the
Contract") against current repository source, treating it as untrusted. No production code, test,
migration, Decision Resolution, or the Contract itself was modified to produce this document.

---

## 1. Executive Verdict

The Contract's overall shape is sound: it correctly identifies and reuses two already-correct,
already-safe-under-concurrency existing functions, correctly excludes `NEWS_ANALYSIS` execution,
and correctly scopes file changes narrowly. However, this audit found **three genuine MAJOR gaps**,
each independently verified against current source, not assumed: (1) the Contract's own required
Integration Proof test commits to a testing approach whose concrete mechanism is not established,
and the disclosed gap (session-factory injection) is only half the real problem — source-pack/
registry injection is equally hardcoded and undisclosed; (2) the Contract does not freeze the exact
exception type the per-cycle failure handler must catch, creating a real, concrete risk (not
theoretical — Python's own `asyncio.CancelledError` inherits from `BaseException`) of silently
breaking the graceful-shutdown guarantee the Contract itself promises; (3) the Contract never
states what the worker actually does when collection is disabled by configuration, leaving a
real deployment-relevant behavior for Planning to invent. **CRITICAL = 0, MAJOR = 3, MINOR = 2.**
Per the stated approval rule, the Contract is **not yet approved**.

---

## 2. Repository Baseline

Re-verified this session: `git rev-parse HEAD` = `228c874b83bb7565629f3c9c5099302925336d59`
(unchanged). `git status --short` (excluding untracked docs) shows **zero** production/test/
migration change. No `worker/` directory exists anywhere in the repository. Phase 12 implementation
has not started.

---

## 3. Existing Function Verification

Re-read both functions in full, independently, this session:

- **`services/collector.py::run_collection_cycle()`** (lines 44–78): confirmed **zero parameters**;
  hardcodes `load_source_pack()` (no arguments — always resolves `DEFAULT_PACKAGE_DIR`, line 54)
  and `async_session_factory` (imported directly, line 21, used line 57). Confirmed the function's
  own outer `try/except Exception` (lines 53, 68–69) means it **never propagates an exception to
  its caller** — a DB-connectivity failure or any other unexpected error is always caught and
  logged, returning a (possibly empty) `CollectionReport`. This is stronger than the Contract's own
  §13 Case A implies (see Finding MINOR-2).
- **`services/triage_orchestrator.py::run_triage_cycle()`** (lines 222–300): confirmed it **does**
  accept an injectable `session_factory` parameter (default `async_session_factory`) — asymmetric
  with the collector, exactly as the Contract states. Confirmed it has **no** enclosing top-level
  `try/except` around its own body — an exception from its initial `select(NewsEvent)` query or
  session setup (e.g., a DB outage occurring specifically during the triage phase) **would**
  propagate to its caller, unlike the collector.

---

## 4. File Scope / Packaging Audit

Independently re-derived minimum scope: matches the Contract's §22 list exactly — `core/config.py`
(2 new fields), `docker-compose.yml` (1 new service), `pyproject.toml` (`"worker"` added to
`packages`), plus `worker/__init__.py`/`main.py`/`cycle.py` and 2–3 test files. **Packaging
correctly authorized**: `pyproject.toml`'s `[tool.hatch.build.targets.wheel]` `packages` list is
explicit (confirmed, `packages = ["app", "core", "database", "bot", "integrations", "services",
"schemas", "scripts", "capabilities"]`), and the Contract already authorizes adding `"worker"` to
it — correct and conservative, even though `Dockerfile`'s `COPY . .` (copying the full source tree
before `pip install .`) would very likely make `python -m worker.main` importable from `/app`
regardless, given Python's `-m`-invocation path resolution. No missing production/runtime file
found. **No MAJOR finding on packaging itself.**

---

## 5. Worker / Cycle Semantics

`worker/cycle.py`'s sketch (`run_automation_cycle()` calling `run_collection_cycle()` then
`run_triage_cycle()` sequentially) is confirmed compatible with both functions' real signatures —
no invented parameter, no duplicated logic. **However**, see Finding MAJOR-2 (exception-type
ambiguity) and MINOR-2 (Case A attribution) below — the *shape* is right, the *exact failure-
handling mechanics* are underspecified.

---

## 6. Session / Testability Audit

**High-scrutiny finding, confirmed real**: `run_collection_cycle()` hardcodes **two** things, not
one — the Contract's own §4/§24 discloses the session-factory half ("this Contract does not
prescribe which [technique]") but does not disclose that `load_source_pack()` is *also* called with
no arguments, meaning the exact source pack loaded is *also* not injectable through
`run_collection_cycle()`. A genuine "controlled/fake source boundary" integration test (§25) cannot
be built by parameter injection alone for *either* concern — see Finding MAJOR-1.

---

## 7. Dedup / Triage Audit

**Dedup**: re-verified `_compute_hash(source_id, external_id)` plus `NewsEvent.hash`'s `unique=True`
constraint; also verified `external_id` stability at the adapter level for RSS
(`entry.get("id") or entry.get("link")`, `integrations/sources/rss_source.py:43`) and arXiv
(`entry.get("id")`, `integrations/sources/arxiv_source.py:57`) — both stable, standard feed
identifiers, confirming repeated-poll dedup holds for these adapters too, not only Telegram.
**No finding.**

**Triage reprocessing**: re-verified that an event which successfully obtains an active task is
permanently excluded from both the `NEW`-query and the stale-recovery-candidate query (the latter
explicitly excludes any event with an active task, "regardless of how old `updated_at` is") — no
re-scoring, no repeated task-creation attempt, no wasted load for already-processed events. **No
finding — Contract's claim holds.**

---

## 8. NEWS_ANALYSIS Boundary Audit

Re-confirmed: neither `services/collector.py` nor `services/triage_orchestrator.py` imports
`workflows.runner` or `capabilities.executor` (repo-wide grep, zero matches in either file). The
Contract's own §23 frozen-file list and §24's mandatory AST import-boundary test would mechanically
enforce the same for the new `worker/` files. **No path to `EngagementCapability`/`NEWS_ANALYSIS`
execution exists in the authorized scope. No finding.**

---

## 9. CREATED Task Buildup Audit

Confirmed the Contract's §28 Risks entry explicitly states unbounded accumulation until a future
phase, no cost/data-integrity impact — this matches the audit's own option **B** ("accepted
unbounded technical debt until Phase 13/14") precisely, even though the Contract doesn't use that
literal letter-code framework. **This is adequately, explicitly disclosed — no finding.**

---

## 10. Config / Runtime / Docker Audit

**Finding, confirmed by direct source check**: neither `services/collector.py` nor
`services/triage_orchestrator.py` imports `redis` anywhere (re-confirmed via full-file re-read of
both, this session and the prior Contract-writing session) — yet the Contract's §15 illustrative
`docker-compose.yml` snippet includes `REDIS_HOST: redis` and an implicit `depends_on: redis`
(copied from the `backend` service's own environment block). **See Finding MINOR-1.**

**Finding, confirmed by direct re-reading of the Contract's own text**: §16/§5 never state what
`worker/main.py` does when `news_collection_enabled=False` — exits cleanly (A), stays alive but
never runs a cycle (B), is not started by Compose at all (C), or something else (D). **See Finding
MAJOR-3.**

---

## 11. Observability Audit

Re-confirmed `CollectionReport`/`TriageCycleReport`'s exact existing fields (§3 above) — the
Contract's §18 correctly commits to using *only* these, explicitly not promising a raw "items
fetched" count neither dataclass exposes. **No over-promised, infeasible metric. No finding.**

---

## 12. Test Feasibility Audit

See Finding MAJOR-1 (Integration Proof feasibility) and MINOR-2 (Case A attribution). Unit-level
worker/cycle tests (mocking `run_collection_cycle`/`run_triage_cycle` at the `worker.cycle` module
boundary, mirroring Phase 11's own already-proven `bot.handlers.news` patching technique) are fully
feasible with no gap — this specific, narrower test category is not in question.

---

## 13. Live Acceptance Feasibility

The already-imported, real, already-active source pack (RSS/arXiv/GitHub/Hacker News feeds,
confirmed present from Phase 4/Discovery evidence) provides a low-risk, no-write, no-cost real
external source suitable for the live acceptance test described in the Contract's §26 — genuinely
waiting for one new real item to appear in a public feed is feasible and safe. **No finding.**

---

## 14. Future Visual / Publication Boundaries

Re-confirmed: the Contract's §20/§21 accurately restate that no new destructive media transformation
is introduced and no path to public publishing exists in the authorized file scope. **No finding.**

---

## 15. Findings

### MAJOR-1
**SEVERITY**: MAJOR
**CONTRACT LOCATION**: §24 (Testing Requirements, "Disclosed testing-strategy input for Planning"),
§25 (Integration Proof)
**SOURCE EVIDENCE**: `services/collector.py:44,54,57` — `run_collection_cycle()` takes no
parameters and internally calls both `load_source_pack()` (no `package_dir` argument, always
resolving the real `config/newsroom_sources_v1` package) and `async_session_factory()` (the real,
production session factory) with no injection seam for either.
**PROBLEM**: the Contract commits to a required Integration Proof test ("a controlled/fake source
boundary... feeding into the real `services/collector.py`... persistence path against a real test
database") and discloses only the session-factory half of why this is non-trivial. It does not
disclose or resolve the *second*, independent hardcoding (source-pack/registry resolution), and
names no concrete technique (e.g., module-level monkeypatching of `services.collector.
load_source_pack`/`services.collector.async_session_factory`, the same class of technique already
proven in this project's own Phase 11 handler tests) that would make this test achievable without
a live external network call and without modifying frozen `services/collector.py`.
**IMPACT**: Definition of Done item 16 ("every mandatory automated test exists and passes")
includes this Integration Proof. Without a named, Contract-authorized technique, Planning must
invent — without further architectural guidance — how to construct the "controlled source" boundary,
which is exactly the kind of substantive, undisclosed decision an audit must catch before
approval.
**REQUIRED CORRECTION**: either (a) explicitly name and authorize the specific test technique
(module-level patching of both `services.collector.load_source_pack` and
`services.collector.async_session_factory` for this one integration test, clarifying this is
test-time runtime substitution, not a modification to `services/collector.py`'s own source), or
(b) narrow the Integration Proof's scope to test `worker/cycle.py`'s own orchestration against
mocked collection/triage results, deferring a true first-ever real-DB test of collector.py's own
internals to a separate, explicitly-chartered task.

### MAJOR-2
**SEVERITY**: MAJOR
**CONTRACT LOCATION**: §13 (Failure Semantics), §14 (Startup/Shutdown)
**SOURCE EVIDENCE**: Python's `asyncio.CancelledError` inherits from `BaseException`, not
`Exception`, since Python 3.8 (a language-level fact, not repository-specific, but directly
relevant to how §13's "worker/cycle.py additionally wraps the whole cycle in a try/except" must be
implemented).
**PROBLEM**: the Contract's §13 never freezes the exact exception type the per-cycle wrapper must
catch. If Planning implements this with a bare `except:` or `except BaseException:` (both natural,
easy mistakes for "catch everything and don't crash"), a shutdown signal delivered while a cycle is
running would be silently swallowed by this same handler, breaking the graceful-cancellation
guarantee §14 explicitly promises.
**IMPACT**: a real, concrete (not theoretical) risk of shipping a worker that cannot be gracefully
stopped — directly contradicting the Contract's own §14/§27 (Definition of Done item mentioning
clean shutdown implicitly via §14).
**REQUIRED CORRECTION**: freeze explicitly: the per-cycle failure handler must catch `Exception`
only (never bare `except:`, never `BaseException`), and `asyncio.CancelledError` must be allowed to
propagate uncaught through both the cycle-execution and the interval-sleep code paths.

### MAJOR-3
**SEVERITY**: MAJOR
**CONTRACT LOCATION**: §11 (Cadence), §16 (Configuration)
**SOURCE EVIDENCE**: `core/config.py`'s existing conventions (`enabled_providers`,
`verify_capabilities_at_boot`) gate *construction* of downstream objects on their flag, but each of
those call sites already has its own established "if disabled, do nothing" behavior defined
elsewhere in already-existing code — no direct precedent exists for what an always-running
long-lived *process* should do when its own top-level feature flag is off.
**PROBLEM**: the Contract never states what `worker/main.py` does when
`news_collection_enabled=False`. Given `docker-compose.yml`'s proposed service (§15) has no
conditional start logic and `restart: unless-stopped`, this is not a cosmetic detail — Planning must
choose between the process exiting immediately (which, combined with `restart: unless-stopped`,
would cause a rapid restart loop — an operationally bad outcome), idling forever without ever
cycling (wasting a container slot but otherwise harmless), or some other mechanism, with no Contract
guidance either way.
**IMPACT**: a genuine deployment-behavior gap that could produce a restart-loop container in
production if Planning picks the wrong option by default.
**REQUIRED CORRECTION**: freeze explicitly, e.g.: "when `news_collection_enabled=False`, the worker
process starts, logs that automation is disabled, and idles (sleeps in a loop, checking the flag
periodically, or simply sleeps for the configured interval indefinitely without ever calling
`run_automation_cycle()`) rather than exiting" — a specific, deterministic choice, not left open.

## 16. Observations

### MINOR-1
**LOCATION**: §15 (Runtime / Docker)
**PROBLEM**: the illustrative `docker-compose.yml` snippet includes `REDIS_HOST: redis` (implying a
`depends_on: redis` dependency), but neither `run_collection_cycle()` nor `run_triage_cycle()`
imports or uses Redis anywhere (re-confirmed by direct source re-read this session) — this was
copied from the `backend` service's own environment block without verifying necessity, exactly the
kind of blind-copy the audit's own instructions warned against.
**IMPACT**: harmless (the worker would simply wait for Redis to become healthy before starting, and
Redis is already required by other services in the same Compose file) but factually imprecise.
**REQUIRED CORRECTION** (non-blocking): remove `REDIS_HOST`/the Redis dependency from the worker
service's definition, retaining only `POSTGRES_HOST`/the Postgres health dependency.

### MINOR-2
**LOCATION**: §13 (Failure Semantics), Case A
**PROBLEM**: Case A ("Collector orchestration throws an unexpected fatal exception") describes a
path that, per direct re-verification of `run_collection_cycle()`'s current source (§3 above), is
actually unreachable — the function's own existing outer `try/except` guarantees it never
propagates an exception to its caller, under any circumstance. The real, reachable risk of an
unhandled cycle-level exception is entirely on the triage side (§3: `run_triage_cycle()` has no
equivalent outer catch) plus any bug in `worker/cycle.py`'s own glue code.
**IMPACT**: none on the Contract's promised *outcome* (log, don't crash, continue is still correct
and achievable) — this is a precision/attribution issue in the Contract's own explanatory table, not
a behavioral gap.
**REQUIRED CORRECTION** (non-blocking): reword Case A to correctly attribute the reachable failure
surface to `run_triage_cycle()` and `worker/cycle.py`'s own code, not to
`run_collection_cycle()`, which already cannot raise.

## 17. Readiness Score

**6/10.** The Contract's architectural shape, file scope, and NEWS_ANALYSIS/EngagementCapability
boundary are all sound and well-evidenced. The three MAJOR findings are each narrow and
correctable with focused text additions — none requires redesigning the worker/cycle relationship
or reopening the scheduling-mechanism decision — but they are genuine, concrete gaps (one with real
operational-safety consequences — MAJOR-2's shutdown-swallowing risk — and one bound directly to a
required Definition-of-Done test item — MAJOR-1), not merely stylistic. The score reflects real,
adversarially-found defects, not a rubber-stamp pass.

## 18. Final Verdict

PHASE 12 CONTRACT NOT READY — CORRECTIONS REQUIRED
