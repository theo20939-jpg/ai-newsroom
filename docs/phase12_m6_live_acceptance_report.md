# Phase 12 M6 — Live Scheduled Ingestion Acceptance

No credential/secret value is included anywhere in this report. No fake/test seam was used —
this milestone exercised the real, unmodified `worker/main.py` entry point against the real
configured Postgres database and real external sources.

## 1. Verdict

**PASS**, with one disclosed, pre-existing platform limitation (Windows lacks a POSIX `SIGTERM`
equivalent — already documented in the Contract/Plan and separately, directly verified by the M3
automated test suite's own cancellation tests, not re-litigated here as a live-acceptance failure).

## 2. Security Pre-flight

- Presence-only checks (no values printed): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_SESSION_STRING`,
  `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` — all
  **PRESENT**.
- `.env`: confirmed **ignored** (`git check-ignore -q .env`) and **not tracked**
  (`git ls-files .env` empty).
- No interpolating Docker command was run. `docker compose config --services` was used earlier in
  M3 (service names only, already verified safe).
- `docs/security_incident_telegram_credentials_rotation_verification.md` re-confirmed: **SECURITY
  INCIDENT CONTAINED** — operator confirmed both the bot token and Telethon session string were
  rotated after the earlier M3 exposure.

**Pre-flight passed. Live acceptance proceeded.**

## 3. Environment / Worker Configuration

(No secrets.)

- `news_collection_enabled`: `False` (persistent `.env` default, unchanged) — enabled **only** via a
  temporary, process-scoped environment override (`NEWS_COLLECTION_ENABLED=true`) on the single
  command that launched the worker; `.env` itself was never edited.
- `news_collection_interval_seconds`: `1800` (real default, not shortened, per explicit instruction).
- Postgres: reachable, container `ai_newsroom_postgres` reported `Up ... (healthy)`.
- Worker launched via its real, unmodified entry point: `python -m worker.main` (confirmed via
  direct process inspection: `CommandLine: ...python.exe -m worker.main`) — no fake adapter, no fake
  source pack, no test session factory, no direct call to `run_collection_cycle()`/
  `run_triage_cycle()`.

## 4. Baseline State

Recorded at `2026-07-23T10:00:50.94Z`, before worker start, no data modified:

- `NewsEvent` count: 3130
- `EditorialTask` counts by status: `CREATED=3130`, `COMPLETED=3`, `FAILED=1`
- `ContentDraft` count: 2

## 5. Live Source Used

**arXiv cs.AI** (`NewsSource.id = bbb606d3-3aea-496b-b473-ab1ee914fba5`) — selected for its high
publication frequency, no credential requirement, and already-configured, already-active status. No
new source was added; no source business logic was altered.

## 6. Scheduled Cycle Evidence

Two full scheduled cycles were observed, both triggered entirely by the worker's own internal loop —
no manual `run_collection_cycle()`/`run_triage_cycle()` invocation at any point:

| Cycle | Collection | Triage |
|---|---|---|
| 1 (fires immediately on worker start) | `processed=66 failed=16 created=1536 duplicates=1407` | `phase9_triage_cycle_finished` immediately after |
| 2 (fires ~1800s later, per the real, unmodified interval) | `processed=66 failed=16 created=57 duplicates=2885` | `phase9_triage_cycle_finished` immediately after |

`worker.cycle`'s own `automation_cycle_finished` log line confirmed collection completed before
triage started, both times, matching `worker/cycle.py`'s frozen sequential design.

The 16 per-cycle source failures (identical set both cycles: e.g. `ComfyUI Releases` — GitHub repo
moved, HTTP 301; `Tom's Hardware`, `AnandTech`, `MacRumors` — stale feed URLs; `Android Authority` —
HTTP 403) are **pre-existing, stale source-pack URLs, unrelated to Phase 12** — `services/collector
.py`'s own existing, frozen retry-then-skip logic (3 attempts, then `report.sources_failed += 1`,
`logger.exception(...)`, continue to the next source) handled every one of them correctly; collection
of the other 66 sources continued and completed normally both cycles. This is live confirmation of
Contract §7's failure isolation, not a defect — no fix was made or needed (per Step 13's failure
policy: not a Phase-12-caused defect, and not something this milestone is authorized to patch).

## 7. Fresh NewsEvent Evidence

- Total `NewsEvent` count: `3130` (baseline) → `4666` (after cycle 1, +1536) → `4723` (after cycle 2,
  +57) — both deltas match their cycles' own `CollectionReport.events_created` exactly.
- **arXiv cs.AI specifically**: 5 genuinely new papers collected in cycle 1 (e.g. *"Natural-language
  autoencoders score explanations of hidden activations"*, *"We consider a task planning scenario in
  which robots sharing a persist[ent]..."*), each with `collected_at = 2026-07-23T10:04:07Z` —
  consistent with this live run's own timing (worker started ~10:01Z), not pre-existing data.
- None of these were present at baseline (baseline's own latest `NewsEvent.collected_at` was
  `2026-07-21T12:08:15Z`, over two days earlier).

## 8. Automatic Triage Evidence

- `EditorialTask` `CREATED` count: `3130` → `4666` (+1536, cycle 1) → `4723` (+57, cycle 2) — exact
  1:1 match with new `NewsEvent` rows both cycles, confirming Triage ran automatically, immediately
  after collection, every cycle, with no event left unprocessed.
- Sample log evidence: `Created EditorialTask ...: event=... workflow=NEWS_ANALYSIS priority=B` (and
  `S`/`A`/`C` at various points) — real, `decide_triage()`-computed priorities, not fabricated.
- Every observed new event was triage-eligible and produced a `NEWS_ANALYSIS(CREATED)` task — no
  scoring threshold was touched or needed adjustment.

## 9. Dedup Evidence

- Cycle 2's own report: `duplicates=2885` out of `2942` items re-fetched from the same 66 sources —
  the overwhelming majority correctly recognized as already-seen via the real, unmodified
  `services/deduplication.py::is_duplicate()` path.
- Direct query: zero duplicate `hash` values anywhere in the `NewsEvent` table (both globally and
  scoped to arXiv cs.AI specifically) after both cycles.
- Duplicate-active-task protection: all 4666 events already claimed/triaged in cycle 1 produced
  **zero** additional `EditorialTask` rows in cycle 2 — `EditorialTask` count grew by exactly 57
  (matching only the genuinely new events), confirming `DuplicateActiveTaskError`'s existing,
  unmodified catch worked correctly across a real ~30-minute interval, not just in an offline test.

## 10. Downstream Boundary Verification

- `AIExecution` count: **0** before, during, and after both cycles — `WorkflowRunner` was never
  invoked; `EngagementCapability` was never invoked; `CONTENT_GENERATION` was never started.
- `ContentDraft` count: **2 → 2**, unchanged — no draft was created as a consequence of Phase 12.
- No Telegram/channel auto-publication occurred: the worker process imports no `aiogram`/
  `bot.loader`/`bot.handlers` code at all (re-confirmed structurally in M5; the live log shows zero
  outbound Bot-API calls — only Telethon Client-API *collection* connections, an existing, frozen,
  already-authorized read path unrelated to publishing).

## 11. CREATED Task Observation

- Before M6: `3130` `CREATED` `NEWS_ANALYSIS` tasks (pre-existing operational debt, unrelated to this
  run).
- After M6: `4723` `CREATED` tasks (+1593 net, matching the two cycles' combined new-event count
  exactly).
- Per the frozen Contract/Plan boundary: **not executed, not cleared, not "fixed."** This remains
  accepted, temporary operational debt for a future, separately-governed phase.

## 12. Shutdown Verification

The worker ran stably across two full real cycles (~37 minutes total) with no crash, no unhandled
exception, and no restart. Stopping it exposed a **disclosed, pre-existing platform limitation**, not
a new defect: this development machine is Windows, which has no POSIX `SIGTERM` equivalent and no
message-loop for `python -m worker.main`'s console process, so `loop.add_signal_handler()` silently
declined to register (confirmed, by design, in `worker/main.py`'s own comment and the M3 test suite's
`test_main_starts_without_crashing_on_this_platform`). Windows' `Stop-Process` (the closest available
mechanism) performs a hard `TerminateProcess`, which does not give Python a chance to run its own
`except asyncio.CancelledError` cleanup — confirmed by the absence of an
`automation_worker_shutdown_complete` log line after termination. The process **did** stop cleanly
from an OS perspective (verified: zero `python.exe` processes remain, no orphan). **The actual
graceful-cancellation code path (`task.cancel()` → `asyncio.CancelledError` → logged cleanup) is
separately and directly verified** by `tests/test_worker_main.py`'s own cancellation tests (M3),
which call `task.cancel()` in-process — exactly what a real Linux/Docker `SIGTERM` handler would
trigger via the same `loop.add_signal_handler(signal.SIGTERM, task.cancel)` wiring, fully functional
on the Contract's actual deployment target.

## 13. Data Integrity / Security Verification

- Zero test-owned Phase 12 integration rows (`NewsSource.name LIKE 'phase12-integration-test-%'`)
  remain — this milestone used only the real production seam, no fakes, so none were ever created.
- `ContentDraft` count unchanged (2 → 2).
- No new file under `alembic/versions/` — no migration occurred.
- No orphan process remains (`Get-Process -Id 26956` → not found; `Win32_Process` filter for
  `python.exe` → zero rows).
- `git status --short`: only the same 12 Phase 12 files already modified/created through M0–M5, plus
  this session's own `docs/*.md` governance files — **no unauthorized production/test file changed**
  during live acceptance. Nothing staged, nothing committed.
- No secret value was printed at any point in this milestone.

## 14. Deviations / Findings

- **16 pre-existing stale source-pack URLs** surfaced as per-source failures both cycles (out-of-scope
  for Phase 12 to fix — a source-pack data-quality issue, not collector code; correctly and
  automatically isolated by existing, frozen failure handling). Worth flagging for a future,
  separately-authorized source-pack maintenance pass — not a Phase 12 blocker.
- **Windows graceful-shutdown limitation**, discussed in §12 — disclosed since M3, not new, not a
  Phase 12 code defect, and does not affect the actual Linux/Docker production target.

Neither finding required, or received, any code change during this milestone.

## 15. Final Verdict

PHASE 12 M6 PASSED — FRESH NEWS AUTOMATION LIVE-VALIDATED — READY FOR PHASE 12 CLOSURE
