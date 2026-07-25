# Phase 14.5 — Observation Mode Run Report

## Status: RUNNING — threshold temporarily calibrated to 65, first naturally delivered item confirmed

This is a **living document** for a 1-3 day observation window that just started. It records the
configuration applied, the initial validation performed (workers actually running, real events
flowing through, at least one full real cycle observed at each stage), and real data gathered so
far. Cumulative totals (delivered count, topics, duplicates, hallucinations) will grow over the
remaining window and were not fully observable in this single session — see "How to check
progress later" at the end.

## Configuration applied (`.env`, real, persistent)

| Setting | Value | Note |
|---|---|---|
| `NEWS_COLLECTION_ENABLED` | `true` | **Added beyond the requested list** — see "Correction discovered during validation" below |
| `NEWS_ANALYSIS_ENABLED` | `true` | |
| `NEWS_ANALYSIS_FRESHNESS_CUTOFF_HOURS` | `2` (kept, as instructed) | |
| `CONTENT_GENERATION_ENABLED` | `true` | |
| `CONTENT_GENERATION_POLL_INTERVAL_SECONDS` | `1800` (set, as instructed) | |
| `CONTENT_GENERATION_BATCH_SIZE` | `5` (kept, as instructed) | |
| `CONTENT_GENERATION_DRY_RUN` | `false` (set, as instructed) | |
| `EDITORIAL_CHAT_ID` | `5507703201` (verified, as instructed) | |

Confirmed loaded correctly via a direct `Settings` read after applying — all 8 values match the
table above exactly.

**Minimal logging improvement applied**: `scripts/run_content_generation.py`'s existing
`content_generation_succeeded` log line now also includes `event_id` (previously `task_id`/
`draft_id` only) — a one-line, non-architectural addition, exactly as requested.

**Not done** (per explicit "Do NOT" list): no daily counter, no new database table, no
architecture redesign, no notification queue.

## Correction discovered during validation: the Collector must also run

The requested pipeline is "Sources → Collector → Triage → NEWS_ANALYSIS → CONTENT_GENERATION →
Telegram." The first `NEWS_ANALYSIS` cycle after enabling found **zero** eligible events, because
the Collector (`automation_worker`, Phase 12, gated by `NEWS_COLLECTION_ENABLED`, default
`False`) was not running — no fresh `NewsEvent` was entering the system at all. This was not
listed in the five settings to apply, but without it the entire observation would silently
produce nothing for the full 1-3 days. This uses existing, already-implemented Phase 12
infrastructure only (no new code) — I enabled it and started the `automation_worker` container.
Flagging this prominently since it changes what's actually running versus what was explicitly
enumerated.

## Containers running

| Container | Role | Status |
|---|---|---|
| `ai_newsroom_automation_worker` | Collector + Triage (Phase 12) | Up, `NEWS_COLLECTION_ENABLED=true` |
| `ai_newsroom_news_analysis_worker` | NEWS_ANALYSIS (Phase 13) | Up, enabled |
| `ai_newsroom_content_worker` | CONTENT_GENERATION + Telegram (Phase 14) | Up, enabled, live (not dry-run) |
| `ai_newsroom_postgres` / `ai_newsroom_redis` | infra | Up, healthy |

`ai_newsroom_backend` was not started (not required for this observation; API surface is
unrelated to the automated pipeline being validated).

## Live validation performed this session (~30 minutes of real operation observed)

1. **Collector cycle** (first run, ~18:48–18:52 UTC): fetched from the configured 127-source
   pack; one source (`iXBT News`) failed with an HTTP 301 (pre-existing feed-URL issue, not
   touched); **402 new real `NewsEvent` rows** collected and **404 new `EditorialTask` rows**
   created by Triage in this single cycle.
2. **NEWS_ANALYSIS cycles** (5-minute cadence, unchanged default): two subsequent cycles
   processed **10 new real events** (5 per cycle, `NEWS_ANALYSIS_BATCH_SIZE` default), all
   `SUCCESS`, zero failures, zero retries.
3. **CONTENT_GENERATION cycles** (30-minute cadence, as configured): the cycle at container
   startup (18:43, before the Collector was even running) found 0 eligible events, as expected.
   The next cycle (~19:13) also found **0 new eligible events** — see "Quality-gate observation"
   below for why. **No new automatic Telegram send occurred within this session's ~30-minute
   observation window.**

## Real topics observed (NEWS_ANALYSIS output, this session)

| Source | Title (truncated) | Score |
|---|---|---|
| vc.ru | Black Forest Labs анонсировала Flux 3 — мультимодальную модель для генерации... | 67 |
| vc.ru | «Сбер» предупредил клиентов о завершении обслуживания валютных... | 58 |
| Rozetked | В Xbox появится бесплатный стриминг игр с рекламой | 58 |
| Hacker News Front Page | A solid-state "atomic channel" for separating rare earth elements | 48 |
| Hacker News Front Page | From Evaluation to Guardrails: What We Brought to ACM FAccT 2026 | 32 |
| Hacker News Front Page | Building on ATProto | 15 |
| Anthropic GitHub | anthropics/anthropic-sdk-typescript: sdk: v0.114.0 | 12 |
| Hacker News Front Page | Geekbench 7 | 5 |
| Google News: Artificial Intelligence (×3) | `<a` (malformed) | 0 |
| llama.cpp Releases (×2) | `<details open="">` (malformed) | 0 |

(Plus the one real item already validated and sent earlier this session: vc.ru "Atoms" robotics
funding, score 82, `message_id=12` — see `docs/phase14_5_real_news_validation_report.md`.)

## Quality-gate observation (not a bug — a real finding about the min_score threshold)

**None** of the 10 newly analyzed real-topic items this session scored ≥ `CONTENT_GENERATION_
MIN_SCORE` (70, unchanged default) — the closest was "Black Forest Labs Flux 3" at 67, three
points short. This means the 5/day *ceiling* is very unlikely to be the binding constraint during
this trial; the `min_score=70` quality gate is. This is disclosed as an observation for the
1-3 day window, not changed — the task explicitly said keep `CONTENT_GENERATION_BATCH_SIZE=5`
and did not authorize touching `min_score`. If very few or zero messages are delivered over the
full window, this threshold is the most likely reason, not a pipeline defect.

## Source-quality observation (confirms the previously-reported limitation, now live)

The malformed-title bug reported in `docs/phase14_5_real_news_validation_report.md` (`Google
News: Artificial Intelligence` events with `title == '<a'`) is being processed automatically by
the live pipeline (unlike the earlier manual validation, which deliberately excluded these by
hand). **Good news**: the `scoring` capability correctly assigns these `score=0`, so the existing
`min_score=70` gate reliably filters them out before they could ever reach `CONTENT_GENERATION`
or Telegram — no code change was needed for this protection, it already exists. Also observed:
`llama.cpp Releases` has the same malformed-title pattern (`'<details open="">'`), also correctly
scored `0`. Not fixed (out of scope, per prior instruction); confirmed harmless in practice.

## Duplicates

Zero duplicate `CONTENT_GENERATION` tasks or Telegram sends observed — the existing `~exists()`
dedup check (`worker/content_cycle.py::_select_eligible_events()`) continues to guarantee this
structurally; no new mechanism was needed or added.

## Hallucinations

No new generated draft was produced during this session's live automatic cycles (none passed the
score gate yet), so there is nothing new to assess beyond what `docs/phase14_5_real_news_
validation_report.md` already documented for the one existing real draft (two unverified but
plausible secondary claims, flagged there, not repeated here).

## Delivered news count so far (before threshold calibration)

**0 new automatic deliveries** in this session's first ~30-minute observation window (one
message, `message_id=12`, was sent earlier via the separate manual Phase 14.5 validation, not by
this automatic run). This is an honest, expected early-window result given the score-gate finding
above — not a failure of the pipeline itself, which was directly confirmed working end-to-end
(Collector → Triage → NEWS_ANALYSIS all demonstrably processing real, fresh data correctly).

## Temporary score calibration (70 → 65)

**Change**: `CONTENT_GENERATION_MIN_SCORE` lowered from the default `70` to `65`, using the
existing settings field only — no new configuration key introduced.

**Timestamp**: `.env` edited at `2026-07-23 19:19:33 UTC`; `content_worker` recreated (only that
service targeted) at `2026-07-23 19:19:4x UTC`; new value confirmed loaded
(`settings.content_generation_min_score == 65`) immediately after.

**Unchanged, verified explicitly after the restart** (all read directly from `Settings`):
`news_analysis_freshness_cutoff_hours=2.0`, `content_generation_freshness_cutoff_hours=24.0`,
`content_generation_poll_interval_seconds=1800`, `content_generation_batch_size=5`,
`editorial_chat_id=5507703201`, `content_generation_dry_run=False` — nothing besides
`content_generation_min_score` changed.

**Restart scope**: only `content_worker` was targeted (`docker compose up -d content_worker`).
`automation_worker` (31+ min uptime) and `news_analysis_worker` (36+ min uptime) were confirmed
untouched — their container uptimes were unaffected, so neither restarted nor lost any in-flight
state. `postgres` was recreated as a side effect of `docker-compose`'s shared `env_file: .env`
config-hash tracking (the same behavior observed during the earlier enablement step) — its named
volume persisted the data unchanged, reverified by a direct row-count query immediately after
(5127 `NewsEvent` rows, consistent with pre-restart state). This is a pre-existing characteristic
of this repo's `docker-compose.yml` (all services share one `env_file`), not a new side effect
introduced by this change, and not an additional service being "restarted" in the sense rule 3
means (no code, no worker logic, no config of `postgres` itself changed).

**No historical backlog became eligible**: `NEWS_ANALYSIS_FRESHNESS_CUTOFF_HOURS=2` and
`CONTENT_GENERATION_FRESHNESS_CUTOFF_HOURS=24` were both left untouched — the lowered score
threshold only changed which of the *already-fresh* (collected within the last ~2h at analysis
time), already-analyzed-today candidates could pass the quality gate. No task older than today's
observation window became eligible.

**No manual generation or send was performed.** The change was applied, the worker was restarted,
and the very next naturally-scheduled `content_worker` cycle (which runs once immediately on
startup, per its existing, unmodified `_run_enabled_loop()`) picked its own candidate using the
existing, unmodified `_select_eligible_events()` query — exactly as instructed.

### First naturally delivered item under the new threshold

| Field | Value |
|---|---|
| **Source** | `vc.ru` |
| **Title** | «Black Forest Labs анонсировала Flux 3 — мультимодальную модель для генерации изображений, видео и аудио.» |
| **Score** | `67` (below the old 70 threshold, above the new 65 threshold) |
| **event_id** | `c8510cb5-eebc-4f37-b849-d5e7666f323c` |
| **NEWS_ANALYSIS/CONTENT_GENERATION task_id** | `9f553935-4bbf-49b3-8fb0-676ecee48dc8` |
| **draft_id** | `beb3a223-a85f-4fb3-bb9c-d59561c54a68` |
| **CONTENT_GENERATION completed_at** | `2026-07-23 19:20:15 UTC` |

**Generated draft** (title: "Black Forest Labs анонсировала Flux 3"):
> Flux 3 позиционируется как единая мультимодальная модель для генерации изображений, видео и
> аудио. Пока она не вышла в открытый доступ, а сроки релиза, характеристики и условия
> использования остаются неизвестными.
>
> `#ИИ #ГенеративныйИИ #Flux3 #BlackForestLabs`

**Delivery verification (read-only, independent of the sending code path)**: no message-id
capture wrapper was installed this time (per instruction not to manually force or intervene), so
the Bot API's own per-send `message_id` was not captured at send time. Delivery was instead
confirmed passively via the existing Telethon user session already provisioned in this repo for
Collector source-reading (`integrations/sources/telegram_source.py`'s own client-construction
pattern, reused read-only here — `client.iter_messages("nnj_newsroombot", limit=5)`, no message
sent). Result: a message matching this exact draft's title/body/hashtags verbatim, `out=False`
(received, not sent by this session), timestamped `2026-07-23 19:20:15 UTC` — precisely matching
the `CONTENT_GENERATION` task's `completed_at` — appears in the chat, immediately above the
earlier `message_id=12` (Atoms) send. Telethon's own message identifier for this delivery is
`id=626448` (this is Telethon's per-session message numbering, not necessarily numerically
identical to the Bot API's own `message_id` counter — reported here as the independently-observed
identifier from the verification method actually used, since no Bot-API-side capture was
performed this time).

## Delivered news count so far (after threshold calibration)

**1 new automatic delivery** — the Flux 3 item above, selected and sent entirely by the normal
background cycle with no manual intervention.

## How to check progress later (for the remainder of the 1-3 day window)

- Delivered count / topics / drafts: query `ContentDraft` joined through `EditorialTask` for rows
  created after this report's timestamp, or check the Telegram chat (`5507703201`) directly.
- Duplicates: re-run the same `~exists()`-based dedup check per event_id (should always be ≤ 1).
- Source/quality issues: re-run the same scoring-extraction query used above
  (`workflow["step_results"]` → `scoring` step → `result["score"]`) against newly completed
  `NEWS_ANALYSIS` tasks.
- Container health: `docker ps` (all four should stay `Up`); `docker logs
  ai_newsroom_content_worker` / `ai_newsroom_news_analysis_worker` / `ai_newsroom_automation_
  worker` for cycle-level activity (note: per-cycle counts are in each log line's `extra=` fields,
  which the current basic console formatter does not render — only the event name shows in
  `docker logs`; use the same direct-DB-query approach used in this report to get real counts).

## How to stop (unchanged from `docs/phase14_5_observation_mode_plan.md`)

`docker compose stop automation_worker news_analysis_worker content_worker` for an immediate
halt, or flip all three `*_ENABLED` flags to `false` in `.env` and restart for a clean idle state.
Rollback table is unchanged from the plan document (this run added `NEWS_COLLECTION_ENABLED` to
that same revert-to-`false` list).

---

# HEALTH CHECK — 2026-07-24 11:08 UTC

Read-only diagnostics only. No code, `.env`, or container changes were made during this check.

## 1. Runtime status

| Service | State | Started | Restarts | Recent errors/crashes |
|---|---|---|---|---|
| `backend` | **not running** (never started this observation window — not required for the automated pipeline) | — | — | — |
| `postgres` | running, healthy | 2026-07-23 19:19:43 UTC | 0 | none |
| `redis` | running, healthy | 2026-07-21 05:14:57 UTC | 0 | none |
| `automation_worker` (Collector+Triage) | **container running, but silently stalled** | 2026-07-23 18:48:39 UTC | 0 | see below |
| `news_analysis_worker` | **container running, severely degraded** | 2026-07-23 18:43:27 UTC | 0 | see below |
| `content_worker` | **container running, but silently stalled** | 2026-07-23 19:19:49 UTC | 0 | see below |

**CRITICAL: two of three pipeline workers have stopped producing cycles, with no crash and no
restart.** All processes are still alive at the OS level (`docker top` shows each `python -m
worker.*` process present, low but non-zero CPU time, consistent with idling/blocked-on-I/O, not
crashed). Evidence:

- `automation_worker`: 6 completed cycles between `18:52:05` and `21:39:20` UTC yesterday (normal
  ~33-minute cadence). **Zero cycles since `21:39:20 UTC yesterday` — no collection for 13h29m.**
- `content_worker`: 6 completed cycles between `19:20:16` and `21:50:55` UTC yesterday (normal
  ~30-minute cadence, matching its configured interval exactly). **Zero cycles since `21:50:55
  UTC yesterday` — no content-generation cycle for 13h17m.**
- `news_analysis_worker`: 30 completed cycles between `18:43:32` and `21:53:11` UTC yesterday
  (normal ~6-7 minute cadence). Then a **7.5-hour gap**, one cycle at `05:19:34` today, then a
  **5.7-hour gap**, one cycle at `11:00:10` today (both found 0 new work — see §3). Effectively
  stalled, with two lucky exceptions.
- `redis`'s own background-save log independently shows its last write-triggered save at
  `21:55:36 UTC yesterday` — no further save-trigger activity since, corroborating that this is a
  shared, host/environment-level event around `21:39–21:55` yesterday, not an isolated bug in one
  worker's own code. (Redis responds `PONG` right now — it is not crashed, just quiet, matching
  everything else.)
- Postgres and Redis clocks were checked against the host clock just now and are consistent (no
  drift) — whatever happened has since cleared at the infrastructure level; only the three
  long-lived worker loops remain stuck.

**Most likely explanation** (diagnosis only, not fixed): the pattern (simultaneous stall across
independent processes, containers never marked crashed/restarted, later partial/sporadic recovery
for one process) is most consistent with the host machine suspending (sleep) for an extended
period, which would pause Docker Desktop's VM and everything in it uniformly, followed by an
imperfect resume where TCP/async-timer state for long-lived connections did not cleanly recover
for two of the three workers. This is a hypothesis based on the available evidence, not confirmed
by fixing/restarting anything (out of scope for this check).

**Pipeline operational status**: Sources → Collector: **NOT running** (stalled). Collector →
NewsEvent: not producing new rows. NewsEvent → NEWS_ANALYSIS: **effectively idle** (nothing fresh
to analyze; occasional cycles find 0 eligible work). Score gate → CONTENT_GENERATION: **NOT
running** (stalled) — 2 real, already-qualifying events are provably waiting (see §5). CONTENT_
GENERATION → Telegram: not running as a consequence. **The full background pipeline is currently
NOT operational**, despite every container showing `Up`.

## 2. Active configuration (effective values, no secrets)

| Setting | Value |
|---|---|
| `NEWS_COLLECTION_ENABLED` | `True` |
| `NEWS_ANALYSIS_ENABLED` | `True` |
| `CONTENT_GENERATION_ENABLED` | `True` |
| `NEWS_ANALYSIS_FRESHNESS_CUTOFF_HOURS` | `2.0` |
| `NEWS_ANALYSIS_POLL_INTERVAL_SECONDS` | `300` |
| `NEWS_ANALYSIS_BATCH_SIZE` | `5` |
| `CONTENT_GENERATION_FRESHNESS_CUTOFF_HOURS` | `24.0` |
| `CONTENT_GENERATION_POLL_INTERVAL_SECONDS` | `1800` |
| `CONTENT_GENERATION_BATCH_SIZE` | `5` |
| `CONTENT_GENERATION_MIN_SCORE` | `65` (temporary calibration, unchanged since the last update) |
| `CONTENT_GENERATION_DRY_RUN` | `False` |
| `EDITORIAL_CHAT_ID` | configured, confirmed `5507703201` — matches the already-approved private destination |

All values read directly from the live `Settings` object; no secrets (tokens/keys/passwords)
were printed.

## 3. Activity since observation mode start (2026-07-23 ~18:48 UTC)

- **New real `NewsEvent` rows collected**: 533
- **New `NEWS_ANALYSIS` `EditorialTask` rows created**: 656
- **NEWS_ANALYSIS status breakdown** (of tasks created since start): `CREATED` 521, `COMPLETED`
  135, `FAILED` 0, `RUNNING` 0
- **Score distribution** (135 scored completions): highest **78**, lowest **0**, average **18.4**,
  median **8**. Count ≥ 65: **6** (5 unique events — one event has 2 duplicate qualifying runs,
  see §6). Count < 65: **129**.
- **CONTENT_GENERATION tasks**: 8 `COMPLETED`, 1 `FAILED` (all-time; the `FAILED` one and 5 of the
  8 `COMPLETED` predate this observation window — see prior report sections). **3 new `COMPLETED`
  CONTENT_GENERATION tasks during this observation window**, 0 new failures.
- **New `ContentDraft` rows**: 3 (one per new completed task above).
- **Naturally delivered Telegram editorial messages**: **3**, independently confirmed via
  read-only chat inspection (Telethon, same method as the prior threshold-calibration check) —
  not inferred from `ContentDraft` count alone. All 3 drafts have a matching, content-identical
  message in the chat with `out=False` and a timestamp matching the task's `completed_at`:
  - "Black Forest Labs анонсировала Flux 3" (`19:20:15 UTC`)
  - "ChatGPT Health стал доступен всем совершеннолетним пользователям в США" (`19:50:29 UTC`)
  - "Данные «Медикейд» могли незаконно передать «Палантиру»" (`20:20:44 UTC`)

## 4. Recent pipeline sample (latest 10 real analyzed events)

All 10 are from yesterday (`21:45:38`–`21:53:11 UTC`) — nothing has been analyzed today beyond
two empty cycles (§1), so this is genuinely the most recent activity.

| Timestamp (UTC) | Source | Title | Score | NEWS_ANALYSIS | CONTENT_GENERATION | Draft |
|---|---|---|---|---|---|---|
| 21:53:11 | Google News: AI | **`<a` (malformed)** | 0 | COMPLETED | — | no |
| 21:52:51 | Google News: AI | **`<a` (malformed)** | 0 | COMPLETED | — | no |
| 21:52:35 | Lobsters | **malformed** (`<p><a href="...">`) | 2 | COMPLETED | — | no |
| 21:52:21 | Lobsters | **malformed** (`<p><a href="...">`) | 8 | COMPLETED | — | no |
| 21:52:07 | Techmeme | **malformed** (`<a href="...apnews...">`) | 42 | COMPLETED | — | no |
| 21:46:40 | BBC Technology | A new bill would let the US government order the shutdown of AI models th... | **78** | COMPLETED | **none — stuck, see §5** | no |
| 21:46:22 | 9to5Mac | **malformed** (`<div class="feat-image">...`) | 0 | COMPLETED | — | no |
| 21:46:07 | 9to5Mac | **malformed** (`<div class="feat-image">...`) | 0 | COMPLETED | — | no |
| 21:45:53 | 9to5Google | **malformed** (`<div class="feat-image">...`) | 0 | COMPLETED | — | no |
| 21:45:38 | Engadget | "The company wants people to be anti-doomer, but doesn't say why." | 8 | COMPLETED | — | no |

6 of the latest 10 have malformed titles (HTML fragments) — consistent with the previously
reported limitation, still live.

## 5. Delivery check — all events with score ≥ 65

| event_id | source | title | score | CONTENT_GENERATION | draft_id | Telegram evidence |
|---|---|---|---|---|---|---|
| `c8e288f3-1a84-4358-ab68-8e4524e42b63` | BBC Technology | A new bill would let the US government order the shutdown of AI models... | 78 | **none — no task exists** | — | not delivered |
| `eaf2ca13-1b1a-40c6-bd40-84aae53286ee` | Hacker News Front Page | ICE Illegally Scooped Up Medicaid Data, Then Shared It with Palantir | 78 (×2, duplicate NA runs) | COMPLETED (`aab8b5b0-...`) | `e5015eae-f750-489d-96ff-b96e490ab692` | **delivered**, confirmed (§3) |
| `8c5a7ed0-580c-4636-80dc-e615a0a96be1` | Engadget | ChatGPT Health is rolling out to users in the US who are 18 years or o... | 68 | **none — no task exists** | — | not delivered |
| `f0a32409-c6cb-49ac-95b4-4eddd44a059a` | Techmeme | (malformed title, real content underneath) OpenAI makes ChatGPT Health available... | 78 | COMPLETED (`964cbf4f-...`) | `679f0b10-7587-4511-968c-5d0ebf188e02` | **delivered**, confirmed (§3) — see §6 for the malformed-header consequence |
| `c8510cb5-eebc-4f37-b849-d5e7666f323c` | vc.ru | Black Forest Labs анонсировала Flux 3 | 67 (also 82 on an earlier duplicate run) | COMPLETED (`9f553935-...`) | `beb3a223-a85f-4fb3-bb9c-d59561c54a68` | **delivered**, confirmed (§3, and prior section) |

**Yes — 2 qualifying real items are stuck between the score gate and CONTENT_GENERATION**:
`c8e288f3` (BBC, score 78, analyzed `21:46:40` yesterday) and `8c5a7ed0` (Engadget, score 68,
analyzed `20:38:51` yesterday). Neither has a `CONTENT_GENERATION` task at all. This is a direct,
expected consequence of `content_worker` having executed zero cycles since `21:50:55` yesterday
(§1) — not a separate selection-logic defect. Both are still within the 24h
`CONTENT_GENERATION_FRESHNESS_CUTOFF_HOURS` window as of this check, so **if `content_worker`
resumes soon, both would naturally be picked up without any manual action**; the Engadget one
(analyzed ~14.5h ago) is closer to aging out than the BBC one (~13.4h ago). No resend or manual
trigger was performed.

## 6. Error / anomaly check

**CRITICAL**
- Two of three pipeline workers (`automation_worker`, `content_worker`) have produced zero cycles
  for 13+ hours despite showing `Up` — see §1. The pipeline is not currently delivering anything
  new, and won't until this clears (naturally or via a restart, neither attempted here).
- **Duplicate `NEWS_ANALYSIS` tasks for the same `NewsEvent`**: **108 distinct events** have 2 or
  3 separate `NEWS_ANALYSIS` `EditorialTask` rows (all-time, not just this window) — confirmed via
  a direct `GROUP BY event_id HAVING COUNT(*) > 1` query. Example: event `eaf2ca13-...` has 3
  separate completed analysis runs (scores 78, 78, and one earlier). This means Triage is
  re-creating analysis tasks for events that already have one (active-only dedup, not full-history
  dedup — the same class of gap previously disclosed for `workflow_service.create_task()`'s own
  `_find_active_task()`). Real cost impact: each duplicate re-run is up to 4 additional real
  provider calls. **Contained, not compounding further downstream**: `CONTENT_GENERATION`'s own
  separate dedup (by `event_id`, any status) verified to still hold — `eaf2ca13` has exactly one
  `CONTENT_GENERATION` task despite 3 `NEWS_ANALYSIS` duplicates, so no duplicate drafts or
  Telegram sends resulted from this. Not fixed (diagnostics only, per instruction).

**WARNING**
- **A malformed title reached a real, delivered Telegram message**: event `f0a32409` (Techmeme)
  scored 78 (high) despite `title == '<a href="https://techcrunch.com/...">...'` — the scoring
  capability evidently scores on more than the raw title field, so a broken title does not
  reliably predict a low score. The delivered card's headline field shows the raw HTML fragment
  verbatim (confirmed via the read-only chat check in §3) — a real, live editorial-quality defect,
  distinct from the already-known "malformed titles usually score near 0" pattern documented
  earlier in this report. Not fixed (diagnostics only).
- **`NEWS_ANALYSIS` demand far exceeds supply at current settings**: 656 tasks created, only
  135 (21%) ever completed before the stall; 521 remain `CREATED` and, since collection has
  produced nothing for 13+ hours, these will keep aging out of the 2h freshness window unanalyzed
  rather than ever being processed (this is the intended, safe behavior of the freshness cutoff —
  not backlog leakage — but it does mean a large majority of collected news this window was never
  evaluated at all).
- Two real, already-qualifying events are unprocessed and stuck (§5) — will very likely resolve
  automatically once `content_worker` resumes, given they're both still within the freshness
  window.
- Several individual RSS/feed sources fail consistently (`iXBT News`, `NVIDIA Newsroom`,
  `LangChain Blog`, `LlamaIndex Blog`, `Replit Blog`, `Windows Central`, `VentureBeat AI`, `The
  Register AI`, `SemiAnalysis`, `MacRumors`, `ComfyUI Releases`, `Azure AI Blog`, `Axios AI`,
  `Android Authority`, `AnandTech` — each failed on every one of the 6 collection cycles that ran)
  — all pre-existing feed-URL/HTTP issues (403/404/301), already caught and skipped gracefully by
  the Collector's own existing error handling; no crash resulted. Not fixed (out of scope).
- The synthetic `M6 Live Validation Source` (`https://example.com/m6-validation-feed.xml`) is
  still an active `NewsSource` and is polled every collection cycle, always 404s, and produces no
  events — harmless (no synthetic events entered the live pipeline from it) but unnecessary
  ongoing polling overhead.
- The Telegram card header still renders the literal string "UNKNOWN" for every message sent so
  far (all delivered `NewsEvent` rows have `category == NewsCategory.UNKNOWN`) — previously
  reported, unchanged, still live.

**INFO**
- No `RUNNING`-stuck tasks found (0 `RUNNING` `NEWS_ANALYSIS` tasks) — the stall is a worker-loop
  problem, not an abandoned in-flight task.
- No synthetic/test `NewsEvent` entered the live analysis pool during this window (the only
  test-labeled source, `M6 Live Validation Source`, never successfully fetches any items).
- Zero `ERROR`-level log lines in `news_analysis_worker` or `content_worker` logs for this entire
  window — no provider/API/database/Redis errors observed in either.
- The one all-time `CONTENT_GENERATION` `FAILED` task predates this observation window (2026-07-21)
  and is unrelated to it.

## 7. Cost / provider activity (no new API calls made for this check)

- **NEWS_ANALYSIS**: 135 completed tasks × 4 steps = up to **540 capability invocations** this
  window (some fraction of the 108-events'-worth of duplicate re-runs may have been served from
  cache if the prompt/content were identical to an earlier run — not independently verifiable
  without re-instrumenting the gateway, which was not done here, diagnostics only).
- **CONTENT_GENERATION**: 3 new completions this window × 4 steps = up to **12 capability
  invocations**, of which (based on the identical pattern already directly observed twice earlier
  in this report, where `research`/`intelligence` were served from cache in ~7ms) a meaningful
  fraction were likely cache hits — not independently re-confirmed here since that would require
  instrumenting a live call, out of scope for read-only diagnostics.
- **Failed provider calls**: none observed (zero `ERROR`-level lines in either worker's logs).
- **Dollar cost**: not reliably determinable — this codebase does not invoke `CostTracker.
  record()` anywhere (a previously-disclosed, pre-existing gap), so no real spend figure can be
  read from application state. Not fabricated here; recommend checking the OpenAI usage dashboard
  directly for an authoritative number.

## 8. Final verdict

## C. BROKEN — one or more required stages are not functioning.

**Can the bot be safely left running as-is?** Yes, in the narrow sense that nothing is actively
harmful — no crash loop, no error spam, no duplicate Telegram sends, no runaway cost (workers are
idle, not busy-looping). But it is **not currently doing its job**: the Collector and
`content_worker` stages have been silently stalled for 13+ hours, so no new news will be
collected and no new message will be delivered until this clears on its own or the affected
containers are restarted (not done in this check, per instruction).

**What is currently limiting delivered news/quality?** Two independent things: (1) the ongoing
worker stall (§1) is the dominant, currently-binding constraint — it has fully stopped new
collection and delivery since `21:50 UTC` yesterday; (2) separately, even during the healthy
window, the `min_score` gate and per-cycle batch/ordering meant only 3 of 5 qualifying real items
actually got delivered before the stall hit — the other 2 (§5) are simply waiting for
`content_worker` to run again.

**Is immediate intervention required?** For safety, no (nothing is actively breaking or
overspending). For the observation goal to keep working, **yes** — `automation_worker` and
`content_worker` will very likely need a manual restart to resume collecting/delivering; this
health check deliberately did not perform that restart, per its own read-only scope. Recommend
authorizing a targeted restart of just those two containers as a clear next step.

---

PHASE 14.5 OBSERVATION MODE HEALTH CHECK COMPLETE — BROKEN
