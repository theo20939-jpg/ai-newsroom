# Phase 14.5 — Observation Mode Plan

## Objective

Run the existing Phase 12/13/14 pipeline (Sources → Collector → Triage → NEWS_ANALYSIS →
CONTENT_GENERATION → Telegram editorial notification) unattended, for a temporary evaluation
window, to observe real editorial quality on real incoming news — bounded to a small number of
generated/sent messages per day. **This is not permanent production mode**: no channel
publishing, no images/memes, no approval flow, no architecture change. Uses only the existing
`news_analysis_worker` / `content_worker` services and their existing `Settings` fields — no new
code, no new tables, no new capability.

## Exact configuration changes

All changes are `.env` values consumed by `core/config.py::Settings` (pydantic, loaded once at
process startup) — a real, persistent change this time, not the temporary in-process overrides
used during Phase 14 M6 / 14.5 validation scripts, because this must survive as a running
background service, not a one-off script.

| Setting | Current default | Proposed for observation mode | Why |
|---|---|---|---|
| `NEWS_ANALYSIS_ENABLED` | `False` | `True` | Turns on the analysis worker loop |
| `NEWS_ANALYSIS_POLL_INTERVAL_SECONDS` | `300` | `300` (unchanged) | 5-minute cadence is fine; volume is bounded by the two settings below, not by polling frequency |
| `NEWS_ANALYSIS_BATCH_SIZE` | `5` | `5` (unchanged) | Already a small, bounded per-cycle cap |
| `NEWS_ANALYSIS_FRESHNESS_CUTOFF_HOURS` | `48.0` | **`2.0`** | The default 48h window would make the ~80 already-queued `CREATED` tasks discovered during Phase 14.5 (real, but collected earlier, i.e. accumulated backlog) all immediately eligible the moment the worker turns on — exactly the "historical backlog" this task must not process. Narrowing to 2h means only events collected/published in roughly the last two hours are eligible, mirroring this codebase's own established `_isolated_freshness_window` test pattern (narrowing the cutoff to exclude pre-existing rows, used previously to protect real backlog during Phase 13 M3 test isolation) |
| `CONTENT_GENERATION_ENABLED` | `False` | `True` | Turns on the content worker loop |
| `CONTENT_GENERATION_POLL_INTERVAL_SECONDS` | `300` | **`86400`** (24h) | This is the actual daily-cap mechanism — see "How the limit is enforced" below |
| `CONTENT_GENERATION_BATCH_SIZE` | `5` | `5` (unchanged) | Combined with the 24h interval above, this is what makes the ceiling exactly 5/day |
| `CONTENT_GENERATION_SCAN_LIMIT` | `50` | `50` (unchanged) | Just bounds the SQL scan before the Python-side score filter; unrelated to the daily cap |
| `CONTENT_GENERATION_MIN_SCORE` | `70` | `70` (unchanged) | Existing quality gate, unrelated to volume |
| `CONTENT_GENERATION_FRESHNESS_CUTOFF_HOURS` | `24.0` | `24.0` (unchanged) | Reasonable given content cycles now run once/day anyway |
| `CONTENT_GENERATION_DRY_RUN` | `True` | **`False`** | Must be disabled for messages to actually reach Telegram — this is a real, persistent switch this time (not a temporary override), so it is called out explicitly here rather than buried in the table |
| `EDITORIAL_CHAT_ID` | unset | **`5507703201`** | The already-verified private chat (`docs/phase14_m6_chat_id_verification.md`) |

No other setting changes. No `docker-compose.yml` change — `news_analysis_worker` and
`content_worker` already exist and already read these same env vars.

## How the "max 5 generated news messages per day" limit is enforced

There is no daily counter anywhere in this codebase (`content_generation_batch_size` caps a
single *cycle*, not a day) — adding one would be a code/architecture change, which this task
explicitly forbids. The only limit-enforcement mechanism available from **existing configuration
alone** is: **make the content-generation cycle run at most once per ~24h, and cap that one
cycle's batch size at 5.**

`CONTENT_GENERATION_POLL_INTERVAL_SECONDS=86400` + `CONTENT_GENERATION_BATCH_SIZE=5` together
guarantee: at most one `run_content_cycle()` execution per ~24-hour period (cadence is "cycle
duration + configured interval," per `worker/content_main.py`'s own disclosed, already-accepted
behavior — not wall-clock/calendar-day exact, subject to slow drift run over run), and that one
execution never generates/sends more than 5 messages (`_select_eligible_events()`'s own
`content_generation_batch_size` cap, already enforced code, unmodified).

**Disclosed limitation**: this is an interval-based approximate daily cap, not a hard
calendar-day counter. Over many days the cycle time will drift slightly (a few seconds to
minutes per day, depending on cycle duration). It will never exceed 5 messages *per cycle*, and
cycles will never be closer together than ~24h minus that cycle's own run time.

**Important, separately disclosed scope note**: this 5/day ceiling applies to
`CONTENT_GENERATION` output (i.e., generated drafts and Telegram sends) only. `NEWS_ANALYSIS`
runs on its own, more frequent cadence (every 5 minutes, up to 5 events per cycle) and is **not**
capped at 5/day by this configuration — it will keep analyzing fresh events (subject to the 2h
freshness window above) as they arrive, most of which will never reach `CONTENT_GENERATION`
(quality/score filtered, or simply not among the 5 picked once per day). This is an accepted
trade-off: this codebase has no existing "analysis-count" cap knob, and adding one would be an
architecture change. If actual analysis volume during the trial turns out higher than expected,
the correct lever is narrowing `NEWS_ANALYSIS_FRESHNESS_CUTOFF_HOURS` further, or reducing
`NEWS_ANALYSIS_BATCH_SIZE` — both configuration-only, no code change.

## Fresh-only / no-backlog guarantee

- `NEWS_ANALYSIS_FRESHNESS_CUTOFF_HOURS=2.0` excludes essentially the entire ~80-task backlog
  discovered during Phase 14.5 (all collected several hours before this plan), letting through
  only events collected/published after observation mode is enabled (plus, honestly disclosed,
  any backlog item that happens to fall inside the 2h window at the exact moment of enabling —
  a narrow, accepted edge case, not fully eliminable via freshness-filtering alone without a
  code change).
- `CONTENT_GENERATION_FRESHNESS_CUTOFF_HOURS=24.0` (unchanged) additionally bounds which
  `NEWS_ANALYSIS`-completed events are eligible for content generation.
- No synthetic/test events are eligible by construction: both eligibility queries join through
  `NewsEvent`/`NewsSource`, which only contain rows the real Collector/Triage pipeline wrote (or
  the two deliberately preserved, clearly-labeled Phase 13 M7 / Phase 14 M6 validation artifacts
  — real, distinguishable rows already excluded from prior real-candidate scans by name/title
  inspection, not by any new filter).

## Duplicate-notification avoidance (already structurally guaranteed, no code change needed)

`worker/content_cycle.py::_select_eligible_events()`'s existing `~exists()` check excludes any
event that already has a `CONTENT_GENERATION` task **in any status** (not just active ones) —
this is the exact mechanism, already implemented and tested
(`tests/test_content_worker_cycle.py`, parametrized across all 4 `TaskStatus` values), that
guarantees a given event can never receive a second `CONTENT_GENERATION` task, and therefore
never a second Telegram send via the automatic cycle. No further change is required to satisfy
this requirement.

## Failed generation must not block the worker (already structurally guaranteed)

- `run_content_cycle()` processes eligible events one at a time; if `outcome.content_draft is
  None` for one event, it increments `result.failed` and `continue`s to the next — never aborts
  the cycle (`worker/content_cycle.py`).
- `worker/content_main.py::_run_enabled_loop()` wraps the entire `run_content_cycle()` call in
  `try/except Exception: logger.exception(...)`, so even a cycle-level exception is logged and
  the loop proceeds to the next `poll_interval` sleep, never crashing the worker process.
- The same two guarantees already exist symmetrically for `NEWS_ANALYSIS`
  (`worker/analysis_cycle.py` / `worker/analysis_main.py`).

No code change needed — this requirement is already satisfied by existing, tested behavior.

## Logging requirement: event_id + generated draft id (requires one minimal, non-architectural addition)

Checked current logging: `scripts/run_content_generation.py`'s `content_generation_succeeded`
log line already includes `task_id` and `draft_id`, but **not** `event_id`. This is the one gap
against the stated requirement.

**Proposed minimal fix** (to be applied at enablement time, not part of this planning step, per
"do not modify architecture" — this is a one-line logging addition, not a structural change):
add `"event_id": str(event_id)` to the `extra=` dict of that existing log call in
`scripts/run_content_generation.py::run_content_generation_for_event()`. No signature change, no
new parameter, no behavior change — purely an additional structured-log field.

## Expected API cost

This codebase does not automatically track real dollar cost —
`integrations/llm_gateway/boot.py` documents that `RoutingGateway.generate()` deliberately never
calls `CostTracker.record()` (a disclosed, pre-existing gap, not something to fix here). No
precise daily $ figure can be honestly quoted from this codebase alone.

**Order-of-magnitude estimate**, from the real Phase 14.5 validation run
(`docs/phase14_5_real_news_validation_report.md`) and the model catalog's published per-million-
token pricing (`$1–$5` input / `$6–$30` output per million tokens, depending on model tier):

- One full `NEWS_ANALYSIS` → `CONTENT_GENERATION` pipeline for one event = 8 provider calls, of
  which 2 were served from cache (effectively free) in the observed run — so **6 billed calls**
  per fully-generated-and-sent item.
- At the 5/day ceiling: **≈30 billed calls/day** from the content-generation side, plus
  additional `NEWS_ANALYSIS`-only calls (4 each) for every fresh event analyzed but not selected
  for content generation (volume depends on live Collector throughput within the 2h freshness
  window — not precisely predictable in advance).
- Given typical short-article prompt/response sizes, this is very likely a **low single-digit
  dollar amount per day**, but this is an estimate, not a tracked figure.

**Recommendation**: confirm actual spend via the OpenAI usage dashboard during the trial window
rather than relying on this estimate alone.

## How to stop observation mode

Two options, from fastest/least graceful to slower/most graceful:

1. **Immediate stop** (no config change needed): `docker compose stop news_analysis_worker
   content_worker`. Both containers halt immediately; no further cycles run. `docker compose up
   -d news_analysis_worker content_worker` resumes with whatever `.env` was in effect.
2. **Clean disable** (matches the existing `enabled=False` idle-loop convention both workers
   already implement): set `NEWS_ANALYSIS_ENABLED=False` and `CONTENT_GENERATION_ENABLED=False`
   in `.env`, then `docker compose restart news_analysis_worker content_worker`. Both processes
   start, log "...idling, no cycles will run", and sit in `asyncio.Event().wait()` — no DB/AI/
   Telegram access at all, as already implemented and tested for both workers.

Either way, the durable `/news` command remains available to review any drafts already generated
during the trial, unaffected by stopping the workers.

## Rollback procedure

If the trial needs to be fully reverted to the pre-observation-mode state:

1. Stop the workers (either method above).
2. Revert `.env` to the pre-trial values: `NEWS_ANALYSIS_ENABLED=False`,
   `CONTENT_GENERATION_ENABLED=False`, `CONTENT_GENERATION_DRY_RUN=True`,
   `EDITORIAL_CHAT_ID` unset (or its prior value), `NEWS_ANALYSIS_FRESHNESS_CUTOFF_HOURS=48.0`,
   `CONTENT_GENERATION_POLL_INTERVAL_SECONDS=300` — i.e., every row in the table above reverted
   to its "Current default" column.
3. `docker compose restart news_analysis_worker content_worker` to pick up the reverted `.env`.
4. No data rollback is needed or intended: any `NewsEvent`/`EditorialTask`/`ContentDraft` rows
   created during the trial are real, valid editorial data — they are **not** deleted (same
   preserve-and-label precedent already established for Phase 13 M7 / Phase 14 M6 artifacts).
   Any Telegram messages already sent during the trial cannot be un-sent by this procedure and
   are not attempted to be recalled.
5. Confirm rollback: both workers log "...idling, no cycles will run" again;
   `docker compose ps` shows both containers `Up` but idle; no further Telegram messages arrive.

## What this plan does NOT change

- No architecture, workflow contract, capability, or Collector/Triage code.
- No new database table, no new config *field* beyond values already defined in
  `core/config.py` (only the one disclosed, minimal logging-line addition described above, at
  enablement time).
- No channel publishing, no approval flow, no image/meme generation.
- No permanent removal of `dry_run` as a concept — it is being set to `False` for this bounded
  trial window only, with an explicit, documented rollback back to `True`.

---

PHASE 14.5 OBSERVATION MODE READY
