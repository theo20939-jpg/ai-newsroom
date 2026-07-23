# Phase 12 — Fresh News Automation Decision Resolution

Decision Resolution only. No production code, test, migration, Contract, or Implementation Plan
was created or modified. Every claim below was independently re-verified against current source
this session (file:line evidence throughout) — the Gap Discovery document is treated as secondary,
not authoritative.

---

## 1. Executive Summary

Phase 12's job is narrow and mechanical: **make the two already-correct, already-tested, one-shot
cycles (`services/collector.py::run_collection_cycle()`, `services/triage_orchestrator.py::
run_triage_cycle()`) run on a recurring schedule instead of only when a human types a command.**
Nearly everything needed already exists and is safe to reuse unmodified. The two genuinely new
things are: (1) a small async scheduling loop (no new dependency — none is justified by current
architecture), and (2) one new, off-by-default configuration flag plus an interval setting. A
significant, evidence-based finding changes the shape of one of the task's own open questions:
**Triage already creates `EditorialTask` (`NEWS_ANALYSIS`) rows as an inherent, unmodifiable part
of its existing, frozen Phase 9 contract** — Phase 12 does not add this, it inherits it the moment
it invokes the existing `run_triage_cycle()` function. This is fully compatible with the "stop
before `NEWS_ANALYSIS` execution" boundary, because task *creation* and workflow *execution* are
already, independently, cleanly separated in the current codebase — nothing today invokes
`WorkflowRunner` for a `NEWS_ANALYSIS` task, and Phase 12 introduces no such invocation either.

## 2. Re-Verified Repository Reality

1. **Collector implementations** (**FACT**, `integrations/sources/`): `telegram_source.py`
   (Telethon Client API), `rss_source.py`, `arxiv_source.py`, `github_source.py`,
   `hacker_news_source.py` — all real, registered via `services/adapter_registry.py`.
2. **Triage implementation** (**FACT**, `services/triage.py` + `services/triage_orchestrator.py`):
   real, deterministic, atomic-claim-based, already designed for repeated/concurrent invocation
   (§6 below).
3. **Manual entry points** (**FACT**): `scripts/run_collector.py`, `scripts/run_triage.py` — both
   thin, one-shot wrappers (`asyncio.run(main())`, no loop) around the two service functions above.
   `scripts/run_triage.py`'s own docstring states: *"Production scheduling (cron, systemd timer,
   task queue) remains deferred (Contract §7.4) - this script has the same status
   scripts/run_collector.py itself has today."* — this is a **pre-existing, Phase-9-era, explicit
   acknowledgment** that scheduling was deliberately deferred, not an oversight.
4. **Worker infrastructure** (**FACT**): none exists — no dedicated worker process, no task-queue
   consumer, anywhere.
5. **Scheduler infrastructure** (**FACT**): `grep -rliE "celery|apscheduler|croniter|schedule\.every|
   BackgroundScheduler"` across all production `.py` files returns **zero matches**.
6. **Redis/Celery/APScheduler dependencies** (**FACT**, `pyproject.toml:6-19`): declared
   dependencies are `fastapi`, `uvicorn`, `pydantic-settings`, `sqlalchemy[asyncio]`, `asyncpg`,
   `alembic`, `redis`, `aiogram`, `telethon`, `httpx`, `feedparser`, `pyyaml`, `openai`. **No task-
   queue or scheduler library is declared at all.**
7. **Docker services** (**FACT**, `docker-compose.yml`): exactly `backend` (runs
   `uvicorn app.main:app` — `app/main.py` is a one-route health-check stub, confirmed by direct
   read), `postgres`, `redis`. **No collector, bot, or worker service exists in Docker.**
8. **Disconnected recurring collection** (**FACT**): none exists in any form — not even a stopped
   or misconfigured one. There is nothing to reconnect; it must be built.
9. **Collection and triage as one reusable service** (**FACT**): yes, already true today —
   `run_collection_cycle()` and `run_triage_cycle()` are both plain async functions with no
   CLI-specific logic inside them; the CLI scripts are pure wrappers. A scheduler can call these
   exact functions directly, with zero duplication of business logic.
10. **Frozen Phase 5–11 components requiring modification**: **none** — re-confirmed; nothing in
    §2 items 1–9 touches `workflows/runner.py`, `capabilities/executor.py`,
    `capabilities/registry.py`, any `capabilities/*_capability.py`, `services/content_draft_service.py`,
    `scripts/run_content_generation.py`, any `database/models/*.py`, or any Phase 11 file.

## 3. Phase 12 Boundary

**DECISION**: Phase 12 stops exactly at:
```
Configured sources → scheduled automatic collection → NewsEvent persistence (existing dedup)
    → automatic Triage (existing logic) → EditorialTask(NEWS_ANALYSIS, status=CREATED)
STOP. No WorkflowRunner invocation. No CONTENT_GENERATION. No ContentDraft.
```
**Evidence-driven refinement of the task's own recommended boundary**: the task suggested Phase 12
"stops after existing triage" and separately asked whether Phase 12 "creates EditorialTask rows."
The evidence in §2/§10 (below) shows these are not independent questions — `run_triage_cycle()`
**already, unavoidably** creates `EditorialTask` rows as part of what "run existing triage" means.
The boundary is therefore not "triage runs but doesn't create tasks" (that would require *modifying*
Triage's own frozen behavior, out of scope) — it is "task *creation* (inherited from Triage) is
in scope; task *execution* (`WorkflowRunner` invocation) is not."

Per-question answers:
- What starts a cycle? A new, small, single scheduling loop (§4).
- How often? One global interval, configurable (§5).
- What sources participate? Whatever `NewsSource` rows are currently `active=True` — unchanged
  from today's manual behavior.
- Source failure? Isolated per-source; healthy sources continue (§7, already the existing
  contract).
- Successful cycle? Matches `CollectionReport`'s existing definition — sources processed vs.
  failed, events created, duplicates skipped — no new definition needed.
- Duplicates? Existing exact-hash dedup (§9) — sufficient for this phase's own stated scope.
- Does triage run immediately after collection? **DECISION: yes**, as the next step of the same
  scheduled cycle (§10).
- Per-item or per-batch? Per-batch, matching `run_triage_cycle()`'s own existing shape (queries
  all eligible `NEW`/stale-`PROCESSING` events each pass, not just "this cycle's new ones" — see
  §10).
- Rejected/low-priority items? Triage's existing behavior applies unchanged — every eligible event
  gets a `TaskPriority`, never dropped (Contract §4's "no hard-drop invariant," re-confirmed in
  `services/triage.py`'s own code comment).
- `EditorialTask` creation? **Yes, inherited from Triage — see above.**
- `WorkflowRunner` invocation? **No.**
- `ContentDraft` creation? **No.**

## 4. Scheduling Mechanism

**DECISION: C — a simple, dedicated, in-process async worker loop** (`while True: await run_cycle();
await asyncio.sleep(interval)`), run as its own small entry-point script/process, mirroring the
existing `bot/main.py`/`scripts/run_*.py` shape this codebase already uses everywhere.

Assessed against the task's own criteria, using only current-repository evidence:
- **A (APScheduler)**, **B (Celery)**: rejected — neither is a declared dependency (§2 item 6); the
  task explicitly instructs not to introduce either "merely because old docs mentioned" them, and no
  current-source evidence justifies the added complexity (a persistent broker, worker/beat
  processes, serialization) for what is, today, exactly two sequential function calls.
- **D (external cron)**: viable in principle, but strictly worse than C given this project's own
  established pattern — every long-running process in this repo (`bot/main.py`) is already a
  simple Python `asyncio` loop, not an externally-cron-invoked one-shot; introducing an external
  cron dependency here would be a second, inconsistent operational pattern for no benefit over C.
- **C (simple async worker loop)**: matches the codebase's own existing convention exactly
  (`bot/main.py`'s shape), adds zero new dependencies, is trivially testable (call the loop body
  function directly, once, in a test), integrates into Docker exactly like the `bot` process would
  (a new service running `python -m scripts.run_worker` or equivalent — no new infrastructure
  class), and needs no new restart-behavior design beyond Docker's own `restart: unless-stopped`
  (already used for every other service in `docker-compose.yml`).

**RECOMMENDATION, not yet a required decision**: toward the ~1000/day target, this same loop shape
scales by shortening the interval or, if ever needed, adding source-level parallelism inside one
cycle — neither requires a different scheduling mechanism, only tuning within it.

## 5. Collection Cadence

**DECISION: a single, global, configurable interval** — one new `Settings` field (e.g.
`news_collection_interval_seconds`), not a per-source value.

**Evidence for "not per-source"**: `schemas/source_definition.py` already defines a per-source
`fetch_interval` field in the config-package layer — but `services/source_pack_importer.py`'s own
docstring states explicitly: *"No new database columns are introduced here - priority, tags,
fetch_interval and adapter stay on the SourceDefinition objects and are simply not exported."*
**FACT**: `fetch_interval` is deliberately never imported into `NewsSource`; the database has no
per-source cadence column today. Adding one would require a migration — explicitly out of this
task's scope ("Do not create migrations"). A single global interval requires no schema change at
all (matches "prefer the simplest solution compatible with current architecture").

**DECISION on default value**: not fixed here — this is a genuine, low-risk, easily-changed product
tuning parameter (RECOMMENDATION: start conservative, e.g. 15–30 minutes, adjustable without any
code change via `.env`), not an architectural decision this Discovery must lock down.

## 6. Overlap Protection

**DECISION: no new locking mechanism is required.** Re-derived directly from source, not assumed:

- **Collector side** (**FACT**, `database/models/news_event.py`: `hash: Mapped[str] =
  mapped_column(String, unique=True, ...)`; `services/collector.py::_process_item()`: wraps the
  insert in `session.begin_nested()` and explicitly catches `IntegrityError` as "duplicate, skip").
  A concurrent second collection cycle attempting to insert the same item would hit this unique
  constraint and be correctly classified as a duplicate — **already safe under concurrency, by
  construction, today.**
- **Triage side** (**FACT**, `services/triage_orchestrator.py:45-67,107-138`): both the new-event
  claim and the stale-recovery acquisition are single, atomic, conditional `UPDATE ... WHERE status
  = ...` statements, returning whether *this* call's attempt affected the row. The module's own
  docstrings state plainly this is designed for exactly this scenario ("another instance already
  claimed it... not an error"). **Already safe under concurrent/overlapping invocation, by
  construction, today.**

**Chosen mechanism, precisely**: rely on the single-process, sequential loop (§4) as the practical
overlap-avoidance mechanism — not because correctness would otherwise be at risk (it would not, per
the two points above), but for **efficiency and rate-limit respect**: a strictly sequential loop
avoids redundant, wasted external-API calls (re-fetching the same Telegram channel/RSS feed
concurrently for results that would just be discarded as duplicates) and avoids doubling the risk
of a Telegram `FloodWaitError`. If this process is ever deployed as multiple replicas in the future,
a distributed lock would become necessary — no evidence in this repository suggests that scenario
today (`docker-compose.yml` defines single instances of every service).

## 7. Source Failure Semantics

**DECISION: preserve exactly the existing contract, unmodified.** **FACT**
(`services/collector.py:60-67`): `run_collection_cycle()` already isolates failures per source —
each source's processing is wrapped in its own `try/except`, a failure increments
`report.sources_failed`, rolls back only that source's uncommitted work, logs via
`logger.exception`, and the loop continues to the next source. **Healthy sources already continue
today; this is not a new decision Phase 12 must make.** Retries: `_fetch_with_retry()` already
retries transient fetch failures up to `MAX_FETCH_ATTEMPTS = 3` with exponential backoff, except
`FloodWaitError`, which is never retried within the same cycle (logged and skipped). Cycle-level
result: `CollectionReport`'s existing fields already answer "what happened this cycle" — no new
reporting shape is needed.

## 8. Telegram Collection Semantics

Re-inspected directly (`integrations/sources/telegram_source.py`):
- **Configured channels**: loaded from `NewsSource.url` (the channel identifier) via the existing
  `_load_active_sources()` query — unchanged.
- **Credentials/session**: a pre-generated `StringSession` plus `telegram_api_id`/
  `telegram_api_hash` (Client API credentials, `core/config.py`) — entirely separate from the Bot
  API token used by `bot/`.
- **History vs. new-only**: `client.iter_messages(channel, limit=MESSAGE_FETCH_LIMIT)` fetches the
  **50 most recent** messages every cycle — **FACT**: there is no persisted "last seen message ID"
  or lookback-window state; every cycle re-fetches the same recent window regardless of what was
  already collected.
- **Duplicate prevention across repeated cycles**: entirely delegated to the exact-hash dedup layer
  (§9) — re-fetching the same 50 messages repeatedly is expected and safe; only genuinely new
  messages within that window produce new `NewsEvent` rows.
- **After restart**: no special handling needed or present — the next cycle simply re-fetches the
  same 50-message window; nothing is lost, nothing new is duplicated (dedup holds).
- **Safe to run repeatedly**: **yes, already proven safe** by the dedup+retry contracts already in
  place — confirmed, not assumed.

**Media preservation question (binding per this task's own §7/§19)**: **FACT**, re-confirmed:
`_to_raw_item()` extracts only `external_id`/`text`/`url`/`published_at`; Telethon's `Message`
object does expose `.photo`/`.media`, and this adapter does not read them. **DECISION: Phase 12
does not change this.** **Is this irreversible?** **No** — `NewsEvent.url` (e.g.
`https://t.me/{channel}/{message.id}`) is persisted for every collected item; a future phase can
re-fetch the *same* message via Telethon (or the RSS/web equivalent) to extract media at that
later time, **provided the source's message/post history remains available** (an assumption, not a
guarantee — flagged as a non-blocking risk in §22, not a Phase 12 blocker, since nothing about
Phase 12 itself shortens that availability window). **Phase 12 does not make future media recovery
impossible.**

## 9. Dedup Semantics

**DECISION: existing exact-hash dedup (`services/deduplication.py`) is sufficient for Phase 12's
own stated scope**, and is explicitly not expanded. **FACT**: the hash is
`sha256(f"{source_id}:{external_id}")` — this is exactly "prevent scheduled polling from repeatedly
inserting the same source item," which is Phase 12's only dedup requirement per this task's own
framing. Semantic/cross-source event clustering ("is this the same underlying story from two
sources") is explicitly **not** attempted by this dedup layer and is explicitly **deferred**,
matching this task's own instruction not to implement advanced clustering unless already required
— it is not required for "prevent repeated insertion of the same polled item."

## 10. Triage Integration

**DECISION: yes, Phase 12's scheduled cycle runs `run_triage_cycle()` immediately after
`run_collection_cycle()`, within the same recurring loop iteration** (two sequential calls, not a
new merged function — preserves each service's own existing, independent, already-tested
transaction boundaries).

**What triage receives** (**FACT**, re-confirmed from `run_triage_cycle()`'s own source, §2 item 2
of this document): **not** "only newly-created NewsEvent IDs" — the function itself queries **all**
`NewsEvent` rows with `status == NEW` (plus stale-`PROCESSING` recovery candidates) on every
invocation, regardless of which cycle created them. This is `run_triage_cycle()`'s own existing,
unmodified contract — Phase 12 does not need to, and must not, pass it a specific event list.

**Scoring semantics**: unchanged — **DECISION, explicit**: Phase 12 does not touch
`services/triage.py`'s Freshness+reliability-only formula. The known limitation (current triage ≠
engagement/reach intelligence) is preserved exactly as-is and explicitly deferred to Phase 13.

## 11. `NEWS_ANALYSIS` Boundary

**DECISION, precise**: Phase 12 must not, and (per current source) does not, invoke
`WorkflowRunner`/`CapabilityExecutor` for any `NEWS_ANALYSIS` task. **This is already true of
`run_triage_cycle()` and `run_collection_cycle()` today** — neither imports `workflows.runner` or
`capabilities.executor` (re-confirmed by direct read; `services/triage_orchestrator.py`'s own
module docstring even cites the mechanically-enforced architecture-validator rule for this exact
boundary). Phase 12 introduces no new code that would invoke either. The `engagement_analysis`
step's missing `EngagementCapability` (Gap Discovery §6/§10) is therefore **not triggered by Phase
12 at all** — it is only reachable if something executes a `NEWS_ANALYSIS` workflow, which nothing
in Phase 12's scope does. Phase 12 does not implement `EngagementCapability`, does not remove the
step, and does not need to — it simply never reaches that code path.

## 12. `EditorialTask` Decision

**DECISION, restated precisely from §3/§10**: yes, `EditorialTask` rows (type `NEWS_ANALYSIS`,
status `CREATED`) will be created automatically, as an unavoidable, inherited consequence of
invoking the existing, unmodified `run_triage_cycle()` on a schedule. This is not new Phase 12
logic — it is Phase 9's own frozen behavior, now invoked automatically instead of manually. Task
creation does **not** belong to Phase 14 — it already belongs to (and is owned by) Triage, which
predates this phase.

**Disclosed consequence (not a blocker)**: these `CREATED` `NEWS_ANALYSIS` tasks will accumulate
in the database at whatever rate collection produces eligible events, and will remain `CREATED`
indefinitely until a future phase (14) builds the orchestration that executes them. This causes no
data-integrity problem and no cost (no `WorkflowRunner`/AI call happens for a `CREATED` task) — it
is purely a growing backlog of inert rows, an accepted, disclosed side effect of sequencing Phase 12
before Phase 14, not a defect.

## 13. Runtime / Docker Topology

**DECISION**: introduce one new, dedicated worker process/service (its own small entry-point
script, e.g. mirroring `bot/main.py`'s shape — an `asyncio` loop calling
`run_collection_cycle()`/`run_triage_cycle()` on the configured interval), added as its own service
in `docker-compose.yml` alongside `backend`/`postgres`/`redis`/(and, if containerized in the future,
`bot`) — **not** folded into the existing `backend` (FastAPI health-check stub) or the `bot`
process (Telegram long-polling), to keep each process single-purpose, matching this codebase's own
established separation-of-concerns convention throughout Phases 4–11.

**Not yet decided here** (Contract-level detail, not this Discovery's job to fix): exact script
name/location, exact restart-policy wording, exact environment-variable names beyond §14's shape,
exact health-check definition. **RECOMMENDATION**: `restart: unless-stopped`, matching every
existing service in `docker-compose.yml`.

## 14. Configuration

**DECISION — minimal set**:
- `news_collection_enabled: bool` — **default `False`** (safety during rollout). **Evidence for
  this default direction**: this codebase already has an established, repeated convention of
  "off/empty by default, explicit opt-in required" for exactly this class of risk
  (`enabled_providers: list[str] = []`, `verify_capabilities_at_boot: bool = False` — both cited,
  with their own Phase 7 rationale, as "no [X] goes live until explicitly opted in"). Automated
  collection has the same profile (real external API calls, real rate-limit exposure, real cost
  implications at scale) and should follow the same, already-precedented pattern — not a new
  principle invented for this phase.
- `news_collection_interval_seconds: int` — a single global value (§5), sensible positive default,
  `Field(gt=0)` validation (mirroring `stale_processing_threshold_seconds`'s own existing pattern,
  `core/config.py:80`).

**Test/local-dev consideration**: with `news_collection_enabled` defaulting `False`, running the
test suite or a local dev session never triggers unwanted real external API calls merely by
importing configuration — consistent with this repository's entire testing discipline (no live
external call in the automated suite).

## 15. Manual One-Shot Path

**DECISION: yes, preserved, unchanged.** `scripts/run_collector.py` and `scripts/run_triage.py`
remain exactly as they are — the new scheduled worker calls the **same**
`run_collection_cycle()`/`run_triage_cycle()` functions these scripts already call, with zero
duplicated business logic. **Verified compatible**: both functions already take no
CLI-specific arguments and are already plain, reusable `async def` functions — nothing about their
current shape prevents this reuse.

## 16. Observability

**DECISION**: reuse existing logging conventions exactly — `CollectionReport`
(`sources_processed`, `sources_failed`, `events_created`, `duplicates_skipped`) and
`TriageCycleReport` (`events_claimed`, `events_recovered`, `tasks_created`, `claim_races_lost`,
`duplicate_active_task_outcomes`, `other_failures`) **already carry every field this task's own
§15 asks for** except explicit cycle duration and "items fetched" (currently only "events created"/
"duplicates skipped" are counted, not raw fetched-item count before dedup). **RECOMMENDATION**: log
cycle start/end timestamps and duration at the new worker-loop level (one `logger.info` per full
iteration), without modifying either report dataclass — this is presentation, not a new
architecture concern. No new monitoring platform is warranted or in scope.

## 17. Test Strategy

**DECISION — required test categories**, all achievable with existing conventions (real `db_session`
fixture where DB durability matters, no live external Telegram/RSS call anywhere):
- Scheduler-loop trigger test (the loop body calls both cycle functions in order — testable by
  calling the loop's own extracted function once, asserting both were invoked, via a fake/mock,
  not a real sleep-forever loop).
- No-overlap test: not a new mechanism to test (§6) — instead, a test proving the sequential loop
  never starts iteration N+1 before iteration N's `await` completes (trivial given `asyncio`'s own
  single-coroutine sequencing).
- Repeated-collection dedup test: **already exists** implicitly in the Collector's own test suite;
  confirm/extend if a scheduled-context-specific case is missing.
- Partial source failure test: **already exists** (`services/collector.py`'s own established
  per-source isolation, already tested at Phase 4).
- Collection → persistence, collection → triage: integration-level tests chaining
  `run_collection_cycle()` then `run_triage_cycle()` against a real `db_session`, asserting
  `NewsEvent`/`EditorialTask` rows appear as expected.
- No `NEWS_ANALYSIS` execution test: an AST import-boundary test (mirroring every prior phase's own
  convention) confirming the new worker script imports neither `workflows.runner` nor
  `capabilities.executor`.
- No `ContentDraft` creation test: confirm zero `ContentDraft` rows exist after a full
  collection+triage cycle in an isolated test transaction.
- Clean shutdown test: confirm the loop exits cleanly on a cancellation signal (matching
  `bot/main.py`'s own asyncio-task-cancellation precedent, already proven in this project's own
  Telegram-diagnostic work this session).
- Real-DB durability: required wherever `NewsEvent`/`EditorialTask` persistence is asserted,
  matching every existing Phase 4/9 test's own convention.

**No live external Telegram/RSS/API call anywhere in the automated suite** — matching this
project's unbroken discipline since Phase 7.

## 18. Live Acceptance Test

**DECISION — defined, not executed.** Future, human-authorized proof, matching this task's own
8-point outline: start the automation with `news_collection_enabled=True`; identify one genuinely
new post in a real configured source (or a safely-controlled equivalent); confirm no developer
manually invokes the collector for that specific item; observe the scheduled cycle detect it
automatically; confirm a new `NewsEvent` row is persisted; confirm the *next* cycle's dedup
correctly skips re-inserting it; confirm Triage runs automatically and creates the expected
`EditorialTask`; confirm, by direct DB inspection, that no `NEWS_ANALYSIS` workflow was ever
executed (task remains `CREATED`, no `AIExecution`/workflow-runner side effect appears). Not run
now.

## 19. Future Visual Requirement Protection

**DECISION/FINDING**: no Phase 12 decision destroys or discards information the future 5+ image
requirement will need. The one place media is discarded (§8) is **pre-existing behavior, unchanged
by Phase 12** — and, per §8's own analysis, not irreversible, since the original source URL is
preserved and can be re-visited later. **No Phase 12 decision blocks or worsens this.**

## 20. Public Publishing Exclusion

**DECISION, restated exactly and bindingly**: Phase 12 does not publish to any public Telegram
channel, does not schedule any public post, does not auto-approve any content, and does not send
any generated post externally. "Automation" in this phase's scope means exclusively internal
collection/triage processing — it has no relationship to, and does not imply progress toward,
public-facing publishing.

## 21. Decision Table

| Decision | Options considered | Chosen | Evidence | Reason | Deferred consequence |
|---|---|---|---|---|---|
| Phase 12 boundary | Stop before triage / stop after triage / include CONTENT_GENERATION | Stop after triage (task creation inherited) | §2, §3 | Matches existing Triage contract exactly; going further requires the missing EngagementCapability | NEWS_ANALYSIS tasks accumulate CREATED |
| Scheduling mechanism | APScheduler / Celery / async loop / external cron | Async loop | §4, `pyproject.toml` | No new dependency; matches existing `bot/main.py` convention | Future multi-replica deployment would need re-evaluation |
| Cadence model | Global fixed / configurable / per-source | Global, configurable | §5, `source_pack_importer.py` docstring | Per-source needs a new DB column (migration, out of scope) | Per-source cadence deferred |
| Overlap protection | Distributed lock / single-worker sequential loop / skip-if-running flag | Sequential single-process loop | §6 | Both Collector and Triage are already concurrency-safe by construction; sequential loop is for efficiency, not correctness | Multi-replica deployment would need a real lock |
| Source failure handling | New per-source isolation / reuse existing | Reuse existing (already correct) | §7 | Already implemented and tested at Phase 4 | None |
| Telegram media | Preserve now / defer | Defer | §8 | Not required for Phase 12's own scope; not irreversible | Future re-fetch depends on source history remaining available |
| Dedup | Exact-hash / semantic clustering | Exact-hash (existing) | §9 | Sufficient for "no duplicate insert on repeated poll" | Semantic clustering deferred to Phase 13 |
| Triage invocation | Pass new-event IDs only / re-run full eligibility query | Re-run full eligibility query (existing behavior) | §10 | Matches `run_triage_cycle()`'s own existing, unmodified contract | None |
| EditorialTask creation | New Phase 12 logic / inherited from Triage | Inherited from Triage | §11, §12 | Cannot be separated from "run existing Triage" without modifying frozen Phase 9 code | Backlog of CREATED tasks accumulates until Phase 14 |
| Runtime topology | New dedicated worker / fold into backend or bot | New dedicated worker | §13 | Matches this codebase's single-purpose-process convention | None |
| Config defaults | Enabled by default / disabled by default | Disabled by default | §14 | Matches existing "opt-in by default" convention (`enabled_providers`, `verify_capabilities_at_boot`) | Requires explicit operator action to activate |
| Manual path | Remove / preserve | Preserve | §15 | Same underlying functions reused; zero duplication | None |

## 22. Risks

- `NEWS_ANALYSIS`-typed `EditorialTask` rows will accumulate indefinitely in `CREATED` status until
  Phase 14 exists — a growing, inert backlog, not a data-integrity or cost risk, but worth operator
  awareness.
- Re-fetching the same Telegram/RSS window every cycle (§8) is somewhat wasteful once collection
  runs frequently at scale — acceptable at today's evidence-supported scope, worth revisiting if
  cadence is later shortened aggressively toward the ~1000/day target.
- Deferred Telegram media capture assumes source message history remains available for a future
  re-fetch — a reasonable but unverified assumption, not something Phase 12 can control.
- Enabling this automation for the first time will, immediately and correctly, surface the existing
  `~3130`-`NewsEvent`/`~3134`-`EditorialTask` backlog already in the database (re-confirmed this
  session) growing further — an expected consequence of turning on a previously-manual process, not
  a new phenomenon Phase 12 introduces.

## 23. Blocking Human Decisions

**None identified.** Every decision in §3–§20 was resolvable directly from current source evidence,
without inventing a product/business judgment call the available evidence doesn't already settle.

## 24. Deferred Questions (non-blocking)

- Exact default collection interval value (a tunable, not an architectural question — §5).
- Exact worker script name/location and exact Docker service name (Contract-level detail).
- Whether to eventually add per-source cadence (would require a migration; deferred, not blocked).
- Whether "items fetched" (pre-dedup raw count) should be added to `CollectionReport` for richer
  observability (§16) — a minor, optional enhancement, not required for Phase 12's own scope.

## 25. Architecture Contract Inputs

The forthcoming Phase 12 Architecture Contract should freeze, at minimum: the exact new
worker/script file and its authorized-file-scope entry; the exact two `Settings` fields and their
names/defaults/validation; the exact Docker Compose service addition; the exact sequential
collection→triage call shape per iteration; the explicit non-goals restated verbatim from §11/§19/
§20 (no `WorkflowRunner` invocation, no media capture, no public publishing); and the exact test
obligations enumerated in §17.

## 26. Final Verdict

All decisions required to proceed to an Architecture Contract were resolved directly from current
repository evidence. No blocking human decision remains.

---

PHASE 12 DECISIONS RESOLVED — READY FOR ARCHITECTURE CONTRACT
