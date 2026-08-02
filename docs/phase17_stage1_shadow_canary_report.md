# Phase 17 Stage 1 — Shadow Canary Report

Overall status: **Attempt 1 BLOCKED (stale image, root-caused) → Attempt 2 VALIDATED (real shadow
canary, rebuilt image, 5/5 events with full Phase 17 shadow data)**. Attempt 1's own failed result
is preserved below unchanged, per this project's own "never hide a failed experiment" discipline;
Attempt 2 follows as its own separate section.

## Attempt 1 — Original Canary (Stale Image)

Status: **BLOCKED — CANARY DID NOT EXERCISE PHASE 17 CODE (stale Docker image)**. Production
itself ran safely and normally throughout (0 crashes, 0 duplicate drafts/messages, 0 incremental
Phase 17 cost) — but the actual objective of Stage 1 (observing real `EditorialBrief`/`Channel
Relevance`/`AdaptiveLengthPlan`/`BeginnerFriendlyPlan`/`EditorialCompletenessAssessment` shadow
output on 5 fresh real events) was **not achieved**, for a specific, root-caused reason disclosed
in full below — not masked.

## 1. Objective

Run a bounded (5-10 event) Stage 1 canary: start the normal production workers plus
`editorial_brief_mode=shadow`/`channel_relevance_mode=shadow`/`adaptive_length_mode=shadow`/
`beginner_copywriting_mode=shadow`/`editorial_completeness_mode=shadow`, verify production output
is unchanged and Phase 17 shadow metadata is persisted alongside it, then stop.

## 2. Authorization scope

Explicit, narrow user authorization for Stage 1 shadow only (no Stage 2+, no enforcement, no
production Copywriting change, no public channel, no forced backlog processing) — see the
conversation's own Stage 1 authorization message.

## 3. Starting repository state

Branch `feature/phase17-editorial-intelligence`, HEAD `6831a77` (after the safe security preflight
commit). `checkpoint/phase17-stage1-pre-cutover` and `checkpoint/phase17-stage1-shadow-canary-start`
both created at this HEAD before any service was started.

## 4. Starting runtime state

`postgres`/`redis`/`backend` Up; `automation_worker`/`news_analysis_worker`/`content_worker`/
`telegram_bot` Exited, RestartCount=0. No stray host processes. No webhook set
(`getWebhookInfo` → `url` empty, `pending_update_count: 0`).

## 5. Preflight result

`scripts/security_preflight_safe.py`: **OVERALL PASS** — all 6 credential categories `SET`, all 5
live auth checks `PASS` (OpenAI, Telegram bot, Telegram user session, Postgres, Redis), override
file validated (5 mode keys, all values in `{off, shadow}`, zero secret-like key names). No secret
value was ever printed at any point.

## 6. Config activation

`docker-compose.override.yml` (untracked, never committed) added `EDITORIAL_BRIEF_MODE`,
`CHANNEL_RELEVANCE_MODE`, `ADAPTIVE_LENGTH_MODE`, `BEGINNER_COPYWRITING_MODE`,
`EDITORIAL_COMPLETENESS_MODE` = `shadow` to `automation_worker`/`news_analysis_worker`/
`content_worker`. Confirmed present in the actual running container's environment via a targeted,
non-secret `docker inspect` filter (only these 5 mode-variable names, nothing else printed).

## 7. Effective feature modes

Set correctly in the container environment (§6) - but see §11: **the running container image did
not contain the code that reads them**, so they had no observable effect.

## 8. Services started

`automation_worker`, `news_analysis_worker`, `content_worker`, `telegram_bot` — all reached
`running` state, RestartCount=0 throughout, zero crash-loop, zero unhandled exception in any
worker's log (one pre-existing, unrelated collector warning: a single RSS source, "ComfyUI
Releases", returned an HTTP 301 redirect; the collector's own existing retry/skip logic handled it
gracefully after 3 attempts — not a Phase 17 issue, not a stop condition).

Side effect observed and disclosed: `docker compose up` also **recreated** the `postgres`
container (a new container instance, triggered by Compose's own dependency-graph recreation logic
once dependent services changed) — the named data volume was preserved, confirmed by real-time
row-count continuity (no drop, only normal growth) immediately after recreation.

## 9. Canary sample

5 real, fresh `ContentDraft`s were created over ~30 minutes (matching the real
`content_generation_poll_interval_seconds` configuration) — monitored via a bounded, read-only
polling loop (60s interval, 40-minute cap) that stopped automatically the moment the count reached
baseline+5. Categories observed: AI ×3, GADGETS ×2. All 5 came from the normal, unmodified
production pipeline (Research → Intelligence → Scoring → Copywriting → Quality, confirmed via the
real `AIExecution` capability breakdown: RESEARCH ×20, INTELLIGENCE ×40, SCORING ×20,
COPYWRITING ×5, QUALITY ×5 — exactly the expected production capability set, nothing else).

## 10. Per-event shadow results

**None were produced.** Querying each of the 5 new `ContentDraft`s' own `EditorialTask.workflow`
step_results found no `editorial_brief`, `channel_relevance`, `adaptive_length_plan`,
`beginner_friendly_plan`, `editorial_completeness`, or `calibrated_fact_safety` key anywhere - see
§11 for the root cause.

## 11. Root cause (disclosed, not masked)

`docker compose up -d` does **not** rebuild an image unless `--build` is passed or no image
exists yet - it reuses whatever image was last built. `docker images` confirms the
`ai-newsroom-content_worker` image in use was built **2026-07-31 04:00:49** - verified via
`git merge-base --is-ancestor` to predate `checkpoint/phase17-m0` (2026-08-01) entirely. **The
running containers executed pre-Phase-17 code** - none of M0 through M6.1 (including the
`editorial_completeness_mode`/`_attach_editorial_completeness` code added this session) existed in
that image. The five `*_MODE=shadow` environment variables were correctly present in each
container's own environment (§6) but were read by a `core/config.py` that may not even have
defined those fields yet, and by a `capabilities/executor.py` with none of the M1-M6 attach hooks
- so they were silently inert, never erroring, never logging (confirmed: zero
`editorial_brief_started`/`adaptive_length_plan_started`/`beginner_friendly_plan_started`/
`completeness_assessment_started`/`article_topic_assessment_started` log lines, and zero
`*_failed` log lines, across the entire canary window - the attach code was never reached at all,
not reached-and-failed).

**This is a real gap in the runbook this session did not anticipate**: none of the M6.1 readiness
work verified that the production Docker image actually contained the Phase 17 code before
authorizing a canary. `scripts/phase17_cutover_preflight.py`'s own `schema_imports_valid` /
`workflow_registry_compatible` checks run in the **host** Python environment (this session's own
working directory), not inside the actual container image - a blind spot now disclosed for the
next attempt.

## 12. Production output invariance

True, but for the "wrong" underlying reason: production text was unchanged because Phase 17 code
never ran at all in these containers, not because the additive-merge design was exercised and
proven safe under real load. The additive-merge design itself remains validated by 107 targeted
tests (M5+M6+M6.1) and the full regression suite (19/1949, unchanged) - just not re-validated
*live*, which was this canary's own purpose.

## 13. LLM/API cost analysis

Real production cost for this window: **$0.127774** (90 `AIExecution` rows: RESEARCH $0.029432,
INTELLIGENCE $0.072532, SCORING $0.014537, COPYWRITING $0.006016, QUALITY $0.005257) - this is the
**normal production pipeline's own cost** for processing these events (research/intelligence/
scoring run against many analyzed events; copywriting/quality only for the 5 that became drafts),
not a Phase 17 cost. **Phase 17 incremental LLM calls: 0** (trivially true, and also structurally
guaranteed even had the image been current - see M5/M6/M6.1's own zero-LLM-import tests).

## 14. Telegram validation

`telegram_bot` polled cleanly (`Run polling for bot @nnj_newsroombot`), no webhook conflict, no
duplicate consumer. 5 real cards were sent via `content_worker`'s own existing
`send_editorial_card` path to `settings.editorial_chat_id` (the pre-existing private editorial
review chat - confirmed in an earlier session step to be the only Telegram destination anywhere in
this codebase). No button was clicked by this session. Any pending approve/reject decision on
these 5 cards is **PENDING HUMAN REVIEW** - not simulated.

## 15. Duplicate-message check

0 task_ids with more than one `ContentDraft` (checked directly). No evidence of a duplicate
Telegram send (content_worker's own send path is called exactly once per completed
`CONTENT_GENERATION` workflow run, unchanged, pre-existing behavior).

## 16. Worker health

RestartCount=0 for all 4 services throughout and at teardown. All exited cleanly on
`docker compose stop` (`content_worker`/`automation_worker`/`news_analysis_worker` exit code 1 -
the same SIGTERM-driven exit code observed in every pre-canary snapshot this session, not new;
`telegram_bot` exit code 0).

## 17. Stop-condition audit

None of the listed hard stop conditions (ContentDraft mutation, task-state mutation, duplicate
message, duplicate polling, Phase 17 LLM call, API cost spike, crash loop, Telegram error, secret
leakage, rollback impossibility) occurred. The stale-image finding (§11) is a **separate, newly-
disclosed gap** not on the original stop-condition list - treated with equivalent severity because
it means Stage 1's core objective was not met, not because anything unsafe happened.

## 18. Rollback verification

`docker-compose.override.yml` removed. All 4 services stopped (RestartCount=0, clean exit).
`.env` untouched. No migration was touched. No data was deleted. Rollback is, and remains, trivial
(nothing to actually roll back - config was never persisted, only a transient container-level
override for this window).

## 19. Known limitations

- The M6.1 cutover readiness package (this session's own earlier work) did not include an image-
  freshness check - added as a required fix before any future canary attempt (§20).
- The 5 real Telegram cards sent during this window await the user's own review/approval in the
  editorial chat, exactly as the pre-existing production workflow always requires - unaffected by
  Phase 17 either way.

## 20. Human checks still required

1. Rebuild the Docker image (`docker compose build` or `docker compose up -d --build`) before any
   future Stage 1 attempt, so the containers actually run current `HEAD` (including all of
   M0-M6.1).
2. Review the 5 real preview cards already sent to the editorial chat during this window (normal
   production review, unrelated to Phase 17's own success/failure here).
3. Re-authorize a fresh, bounded Stage 1 canary attempt after the image is rebuilt and this
   session (or a future one) re-verifies, from *inside* a running container, that the M1-M6 attach
   log lines actually appear for at least one real event before letting the canary run to
   completion.

## 21. Final verdict

**PHASE 17 STAGE 1 BLOCKED — ROLLED BACK SAFELY.** Nothing unsafe happened, but Stage 1's own
purpose - observing real Phase 17 shadow output - was not achieved, because the running
containers used a Docker image built 2026-07-31, before any Phase 17 code existed. This is
disclosed in full, not minimized. Recommended immediate next step: rebuild the image, then repeat
this exact canary procedure.

---

## Attempt 2 — Rebuilt Current Image

Status: **VALIDATED — 5/5 real events with full Phase 17 shadow output, zero incremental cost,
zero invariant violations.**

### 1. Old-image root cause

Restated from Attempt 1 (§11 above): `docker compose up -d` never rebuilds an image on its own;
the 4 application services (`automation_worker`, `news_analysis_worker`, `content_worker`,
`telegram_bot`) each have their **own separately-tagged image** (`ai-newsroom-<service>`, built
via `build: .`, no shared name, no bind mounts) - all four were stale (2026-07-28 through
2026-07-31), each individually predating `checkpoint/phase17-m0` (2026-08-01).

### 2. Controlled rebuild procedure

`docker compose build automation_worker news_analysis_worker content_worker telegram_bot` -
**only** these 4 application images, never `postgres`/`redis` (pulled, not built) and never
`backend` (out of scope - has live `app`/`core`/`database` bind mounts, doesn't execute the
`CONTENT_GENERATION`/`NEWS_ANALYSIS` workflow, user-scoped out unless required). No
`docker compose down -v`, no volume touched, no destructive command used at any point.

### 3. Image identity proof

| Service | Old image ID | Old build time | New image ID | New build time |
|---|---|---|---|---|
| automation_worker | `4d875338f0ef` | 2026-07-29 13:48 | `186c64d16d09` | 2026-08-02 23:33 |
| news_analysis_worker | `2973c9d59dab` | 2026-07-28 14:15 | `35f78034b495` | 2026-08-02 23:33 |
| content_worker | `d85703b183c3` | 2026-07-31 04:00 | `b4305b8b4fff` | 2026-08-02 23:33 |
| telegram_bot | `22b1308172695` | 2026-07-31 22:41 | `369eee92481f` | 2026-08-02 23:33 |

### 4. Phase 17 code presence proof

Before touching any real event, a one-off `docker compose run --rm --no-deps content_worker
python -c "..."` (auto-removed after exit, never left a stray container) confirmed, inside the
**new** image itself: `EditorialBrief import: PASS`, `ChannelRelevance import: PASS`,
`AdaptiveLength import: PASS`, `BeginnerFriendly import: PASS`, `EditorialCompleteness import:
PASS`, `CalibratedFactSafety import: PASS`, `config_fields_present: PASS`, `executor_hooks_present:
PASS`, `editorial_completeness_schema_version: v1`, `security_preflight_safe_present: PASS` (this
session's own newest file, proving the image reflects current `HEAD`, not just "some" later
commit).

### 5. Service recreation scope

`docker compose up -d --no-deps automation_worker news_analysis_worker content_worker
telegram_bot` - confirmed via `docker inspect` that **only these 4 containers were recreated**;
`postgres`/`redis` container IDs were compared before and after (§6) and found byte-identical, both
on the first recreation (proving the image) and again after the real canary run.

### 6. Postgres/Redis preservation

`postgres` ID `10defff4287d...`, `redis` ID `331d207fcc33...` - identical before build, after the
first `--no-deps` recreate, and after the full ~32-minute canary run (checked every 60s by the
monitoring loop itself, which was configured to immediately abort on any mismatch - never
triggered). Real DB row counts only ever grew, never reset.

### 7. Effective shadow modes

Untracked `docker-compose.override.yml`, scoped precisely to which service actually reaches each
attach hook (avoiding unnecessary duplication): `news_analysis_worker` got
`EDITORIAL_BRIEF_MODE=shadow` + `CHANNEL_RELEVANCE_MODE=shadow` only (its own `NEWS_ANALYSIS`
workflow never reaches the "copywriting"/"quality" steps); `content_worker` got all 5
(`EDITORIAL_BRIEF_MODE`, `CHANNEL_RELEVANCE_MODE`, `ADAPTIVE_LENGTH_MODE`,
`BEGINNER_COPYWRITING_MODE`, `EDITORIAL_COMPLETENESS_MODE`, all `shadow`). Validated via
`scripts/security_preflight_safe.py`'s own static YAML-only parser (never `docker compose
config`): `PASS`, 0 secret-like key names, 5 total mode keys.

### 8. Runtime hook proof

Before letting the canary run to full completion, real log lines were confirmed from the live
`news_analysis_worker` container for a genuinely fresh event:
`editorial_brief_started` → `editorial_brief_completed` → `article_topic_assessment_started` →
`article_topic_assessment_completed` (20:36:32, task `72a60c23...`). Only after this real,
positive proof did the canary continue toward its 5-event cap.

### 9. Five-event sample

Monitored via the same bounded, read-only polling design as Attempt 1 (60s interval, 40-minute
cap, plus a `postgres`/`redis` container-ID check on every single iteration). Target (baseline+5)
reached at 00:08:46, ~32 minutes after container start - all 5 `ContentDraft`s created in a single
final content-generation cycle burst (00:07:19-00:07:48).

### 10. Per-event results

| event (short) | category | source sufficiency | channel fit | adaptive length format | completeness recommendation | calibrated Fact Safety |
|---|---|---|---|---|---|---|
| `2d35bad8` | AI | partial | REVIEW | short_update | NOT_READY | pass |
| `12ce8e52` | STARTUPS | headline_only | REVIEW | insufficient_source | INSUFFICIENT_SOURCE | review |
| `17389223` | AI | sufficient | ACCEPT | explainer | REVIEW | pass |
| `847618cd` | SOFTWARE | sufficient | ACCEPT | explainer | REVIEW | review |
| `ac1f1ff5` | AI | partial | ACCEPT | short_update | REVIEW | review |

**5/5 events produced complete Phase 17 shadow output** - `EditorialBrief`, `ChannelRelevance`,
`AdaptiveLengthPlan`, `BeginnerFriendlyPlan` (all 5 resolved `audience_level: tech_interested`),
`EditorialCompleteness`, and `CalibratedFactSafety` all present for every event, zero missing keys,
zero shadow exceptions logged. Consistent with M5's own already-disclosed finding (docs/
phase17_m5_editorial_completeness_gate_shadow_report.md §27): 0/5 reached `READY` - all REVIEW/
NOT_READY/INSUFFICIENT_SOURCE, the same known, disclosed calibration-conservatism gap, not a new
defect. (Separately, the real production `QualityCapability` LLM judge itself returned
`passed: false` for all 5 of these events - the pre-existing production judge's own independent
opinion, unrelated to and uninfluenced by any Phase 17 shadow component.)

### 11. Shadow execution metrics

Hook execution count: 5/5 for every one of the 5 required hooks (`editorial_brief`,
`channel_relevance`, `adaptive_length_plan`, `beginner_friendly_plan`, `editorial_completeness` +
`calibrated_fact_safety`) = **30/30 individual hook executions succeeded, 0 failures, 0 missing
keys, 0 reason-code-less silent gaps.**

### 12. Cost separation

`AIExecution` rows scoped exactly to these 5 `ContentDraft`-producing tasks (via `task_id`, not a
time window): **COPYWRITING ×5 ($0.007401), QUALITY ×5 ($0.009012) = 10 calls, $0.016413** - the
real, normal production cost of finishing these 5 drafts (their `research`/`intelligence` steps
were reused from prior `NEWS_ANALYSIS` tasks, per the pre-existing cost-optimization reuse
mechanism, `services/analysis_reuse.py`, unrelated to Phase 17). Broader window total (all
analysis-cycle activity across the full ~32-minute run, most of which never became a `ContentDraft`):
105 calls, $0.184743 across RESEARCH/INTELLIGENCE/SCORING/COPYWRITING/QUALITY - the normal
capability set, nothing else. **Phase 17 incremental LLM calls: 0** (verified both structurally -
every Phase 17 attach function is provably free of any Gateway import, per each milestone's own
static test - and empirically, by capability-name enumeration containing only the 5 expected
production names).

### 13. Production invariants

Production text changed: **no**. `ContentDraft` mutated by shadow: **no**. Task state mutated by
shadow: **no**. Duplicate `ContentDraft`s: **0** (checked directly, `task_id` grouped, 0 groups
with >1 row). Automatic `REJECT`: **no** (Phase 17 `channel_relevance` shadow never blocks
anything; the one `REVIEW`-decision event still produced a normal `ContentDraft`).

### 14. Telegram invariants

`telegram_bot` polled cleanly throughout (no webhook, no conflict). 5 real cards were sent via the
pre-existing, unmodified `content_worker` → `settings.editorial_chat_id` path. Duplicate Telegram
messages: **0**. Phase 17 never touched caption/body/buttons (purely additive `step_results`
JSON, never read by the Telegram formatting/send path). Any pending approve/reject decision on
these 5 cards is **PENDING HUMAN REVIEW** - not simulated.

### 15. Stop-condition audit

None triggered: no `ContentDraft`/task-state mutation, no duplicate draft/message, no extra Phase
17 LLM call, no worker crash loop, no Telegram error, no `postgres`/`redis` recreate during the
canary window itself, no DB count anomaly, no secret leakage, no automatic `REJECT`, no production
prompt change, rollback remained trivially available throughout (nothing persistent to roll back).

### 16. Rollback verification

`docker-compose.override.yml` removed after the run. All 4 application services stopped
(`RestartCount=0` throughout, clean exit). `postgres`/`redis` never stopped, never recreated
during or after this attempt. `.env` untouched. No migration touched. No data deleted.

### 17. Human review requirements

1. Review the 5 real preview cards now sitting in the editorial chat (2 from Attempt 1 + 5 from
   Attempt 2 = 7 total awaiting normal human approve/reject - unrelated to Phase 17's own
   validation, the pre-existing production review workflow).
2. No Phase 17-specific human action is blocking - shadow metadata is already fully persisted.

### 18. Stage 2 recommendation

**Not recommended yet, and not authorized regardless** - per this session's own explicit scope,
Stage 1 is the ceiling for this engagement. Should a future session consider Stage 2, the M5
completeness-gate calibration gap (0/5 `READY` here, matching the 0/96 gold-set backtest) should
be addressed first, since Stage 2 is closer to using these signals for real candidate delivery
decisions.

### 19. Final verdict

**PHASE 17 STAGE 1 COMPLETE — HUMAN REVIEW REQUIRED.** The rebuilt-image retry fully validates the
Stage 1 shadow mechanism on 5 real, fresh events: real `EditorialBrief`/`ChannelRelevance`/
`AdaptiveLengthPlan`/`BeginnerFriendlyPlan`/`EditorialCompletenessAssessment`/
`CalibratedFactSafetyAssessment` output persisted for every event, zero production impact, zero
incremental cost, zero invariant violations, zero stop conditions triggered. Stage 2 was not
started.
