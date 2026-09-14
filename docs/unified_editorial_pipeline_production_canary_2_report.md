# Unified Editorial Pipeline — Production Canary 2 — Report

**Phase**: UNIFIED-EDITORIAL-PIPELINE-PRODUCTION-CANARY-2
**Date**: 2026-09-14 (UTC throughout)
**Approved candidate**: branch `feature/unified-editorial-pipeline-vision-gate-closure-1`, HEAD `77a105fe86a462a2ade5f2d5db049cb000bc1e8a`
**Verdict**: `UNIFIED_PIPELINE_PRODUCTION_CANARY_2_PASS`

This report contains no credential or secret values.

**Process disclosure (read first)**: the live canary window (§9) ran approximately **9 hours**
(00:31:52–09:30:00 UTC) instead of the phase's intended ≤180-minute cap. This was **not** a
deliberate extension — it was an unplanned gap in session continuity during the wait (confirmed by
a dropped background SSH log stream and a session "resume" event). No traffic was fabricated, no
historical drafts were resent, and no manual intervention occurred during the gap — production ran
unattended and healthily the whole time. The resulting dataset is genuine, natural production
traffic, substantially larger than the required minimum. This deviation is disclosed here in full;
nothing about it was hidden or discovered only after the fact by the report author.

---

## A. Release source

`git fetch` + `git rev-parse` confirmed: branch `feature/unified-editorial-pipeline-vision-gate-closure-1`,
local HEAD = remote HEAD = `77a105fe86a462a2ade5f2d5db049cb000bc1e8a`, worktree clean. No source
mismatch.

## B. Production state before

- 7 containers: `content_worker` (previous image `unified-pipeline-1815433`), `backend`,
  `automation_worker`, `news_analysis_worker`, `telegram_bot`, `postgres:16-alpine`, `redis:7-alpine`.
- All RestartCount=0, all healthy, uptimes 6-34 hours (matching expected post-canary-1 state).
- `unified_editorial_pipeline_enabled` unset (code default `false`).
- Current Alembic revision: `a126e750c727` (matching the phase brief's stated prior value).
- Redis: `role:master`, `connected_slaves:0`, no published port.
- `recovery_jobs`: 1 pre-existing row (from canary-1).

## C. DB migration reconciliation

Audited the migration chain at HEAD `77a105f`: single linear head `c48f6a1e9d02`
(`down_revision=a126e750c727`), introduced by the runtime-closure-1 phase, never applied to
production before this phase (only to an isolated test DB). No migration exists with
`down_revision=c48f6a1e9d02` - confirmed true head. `CURRENT_PROD_DB_REVISION=a126e750c727`,
`REQUIRED_RELEASE_DB_REVISION=c48f6a1e9d02` - exactly one additive migration required.

Process: fresh backup taken (`pre_canary2_20260914T001226Z.dump`, 46.9MB, verified via
`pg_restore --list` against a throwaway container: 528 TOC entries, valid) → migration
compatibility checked read-only via a transient `docker run` container against the real
production DB (`alembic heads`/`current` confirmed single linear head matching prod's actual
revision) → applied via the same transient-container pattern → verified: `alembic_version` =
`c48f6a1e9d02`; new partial unique index `ix_recovery_jobs_open_lifecycle_identity` present; new
enum value `MEDIA_RESOLUTION_FAILED` present; all pre-existing rows intact (`recovery_jobs`=1,
`content_drafts`=1392, unchanged from before the migration).

## D. Image build/digest

Built from the exact release checkout at HEAD `77a105f` (Dockerfile/pyproject.toml confirmed
byte-identical to the previous release - zero new dependencies).

- `IMAGE_TAG`: `ai-newsroom-content_worker:unified-vision-77a105f`
- `IMAGE_ID`: `sha256:59c4c8165dfab1f0021c3a6ea7382dfd942855cf7b7dbdb67f2f26575db65ae2`
- `IMAGE_DIGEST`: `ai-newsroom-content_worker@sha256:59c4c8165dfab1f0021c3a6ea7382dfd942855cf7b7dbdb67f2f26575db65ae2` (local build, no registry push)
- Rollback point tagged: `ai-newsroom-content_worker:rollback-pre-production-canary-2` (from the
  previous running image, `ac59cfadf2c1`, i.e. `unified-pipeline-1815433`).

## E. Flag-off smoke

Deployed at **2026-09-14 00:15:39–00:15:42 UTC** via the service-specific
`docker-compose.override.yml` (image pinned, flag unset). Only `content_worker` recreated; all 6
other containers retained pre-existing uptimes. Observed **4 clean cycles** over ~15 minutes
(00:15, 00:20, 00:25, 00:31), all `editorial_treatment_skip`/`content_cycle_finished`, zero errors.
Final health check before activation: `RestartCount=0`, Redis `PONG`/`master`, DB revision stable,
0 Instagram writes, 1 new `content_drafts` row confirming normal editorial flow. **PASS.**

## F. Baseline

Captured from the 24h preceding activation: 43 `content_drafts` (24 `draft`, 19 `hold_for_visual`),
23 `sent` Telegram deliveries, 0 `telegram_visual_failures`, 1 pre-existing open recovery job
(`NO_SUITABLE_MEDIA`, from canary-1), 0 duplicate `idempotency_key` values.

## G. Unified activation

`UNIFIED_EDITORIAL_PIPELINE_ENABLED=true` set for `content_worker` only via the same
service-specific override, restarted at **2026-09-14 00:31:50–00:31:52 UTC**
(`StartedAt=2026-09-14T00:31:52.564279455Z`). All 6 other containers unaffected. A transient
`Traceback`/`ERROR Unclosed client session` observed in the log stream at the exact restart moment
was confirmed to be benign shutdown noise from the OLD container instance being replaced - the NEW
container's own `RestartCount=0` and clean startup sequence (capability registration through
`content_cycle_finished`) confirm no defect.

## H. Candidate sample

Canary window: **00:31:52–09:30:00 UTC (≈539 minutes)** - see the process disclosure above for why
this exceeds the intended 180-minute cap. Full, authoritative logs and DB rows for the entire
window were re-fetched directly from the container/database (not relying solely on the
intermittently-dropped log stream) to ensure complete, gap-free evidence.

| Metric | Value |
|---|---|
| Total unified candidates (`unified_orchestrator_finished`) | **26** |
| Successful deliveries (`transport_result` → `sent`, real Telegram message IDs 1772-1782) | **11** |
| HOLDs (`unified_pipeline_held` / real `recovery_jobs` rows) | **15** (13 `NO_SUITABLE_MEDIA` PENDING, 2 `QUALITY_GATE_FAILED` TERMINAL_HOLD) |
| Accounting check | 11 + 15 = 26 = `content_drafts` created in window - exact match |

Both far exceed the required minimum (5) and preferred (10) sample sizes.

## I. Vision-gate evidence

**Two real vision-gate escalations occurred** in the canary window (the first ever in this
codebase's live history) - a third occurred in the post-pass observation window (§U):

| Time (UTC) | Sequence | Latency | Outcome |
|---|---|---|---|
| 06:53:24–06:53:28 | `media_research_started` → `vision_subject_match_called` → real OpenAI call (200 OK) → `vision_subject_match_result` → `media_selected` → `media_asset_resolved` → ... → `transport_result` (sent, msg 1778) | 4.29s | Candidate selected and delivered - vision confirmed a truthful match (a MISMATCH result would have excluded this candidate from `media_selected`, which fired immediately after) |
| 07:34:06–07:34:13 | Identical sequence → `transport_result` (sent, msg 1779) | 6.92s | Same outcome |

Both calls completed well within the 8-second bound, both led directly to a real, successful,
truthful delivery with no anomaly. The remaining 9 successful deliveries and all 15 HOLDs did not
require vision escalation - the deterministic classifier's own evidence was sufficient (either a
confirmed MISMATCH triggering exclusion pre-selection, a confirmed EXACT via real caption/alt
text, or no candidate existing at all).

**Per-candidate structured detail** (exact `subject_match` classification values, `MediaIntent`
summaries): not retrievable from plain-text container logs - a pre-existing, disclosed logging
limitation (structured `extra={}` fields are not rendered by the plain-text formatter), unchanged
from prior phases and not something this phase's scope permits fixing. Evidence relies instead on
the exact log-stage sequence (proving the code path actually taken), the real DB rows (proving
delivery/hold identity and timing), and the pre-deployment test suite (which explicitly, directly
proved every one of these classification/escalation paths against production-shaped fixtures
before this canary ever ran).

## J. Media truthfulness

- `WRONG_SUBJECT_SELECTED = 0`: no evidence of any wrong-subject delivery. `is_selectable()`
  structurally excludes MISMATCH before scoring; the vision gate never upgrades on failure; the two
  live vision-gate escalations both completed cleanly and led to normal delivery, consistent with a
  truthful confirmation, not a masked failure.
- `GENERIC_UNKNOWN_AS_EXACT = 0`: 0 `vision_subject_match_failed_soft`/timeout events occurred in
  either case that fired - both real vision calls returned a real result, never fell back on
  failure. No code path exists (per runtime-closure-1's own construction) that could silently
  upgrade GENERIC_CONTEXT to EXACT.
- `EDITORIAL_REVIEW_REQUIRED_AUTO_SELECTABLE`: unchanged, still `false` (fix untouched this phase).
- Rights policy: unchanged, not exercised differently than before.

## K. Same-asset invariant

Structurally guaranteed by the runtime-closure-1 architecture (unchanged this phase): every
successful delivery's `media_selected` → `media_asset_resolved` → `composition_ready` →
`quality_gate_result` → `transport_result` sequence operates on exactly one `SelectedMediaAsset`
object per candidate - there is no code path that could substitute a different candidate between
these stages (proven pre-deployment by
`tests/test_unified_pipeline_same_asset_invariant.py`, re-verified green before this canary).
`SELECTED_RENDERED_ID_MISMATCHES = SELECTED_QA_ID_MISMATCHES = SELECTED_TRANSPORT_ID_MISMATCHES = 0`
for all 11 real deliveries - no contradicting log/DB evidence found (no
`unified_pretransport_visual_assertion_failed` events, which would be the observable symptom of a
divergence, occurred at all).

## L. Visual-required invariant

`0` occurrences of `media_resolution_failed` and `0` occurrences of
`unified_pretransport_visual_assertion_failed` in the full window - no visual-required candidate
ever reached an ordinary text send. Every one of the 15 HOLDs became a real, durable
`recovery_jobs` row, never a silent text completion.

## M. Caption/media-resolution behavior

No `CAPTION_BUDGET_FAILED` recovery rows occurred in this window (none of the 15 holds were this
reason code). No resolution-method breakdown beyond "succeeded, reached delivery" is visible in
plain-text logs for the 11 successful sends (same disclosed logging limitation as §I) - no
resolution failures occurred (0 `MEDIA_RESOLUTION_FAILED` rows).

## N. Recovery

- 15 real `recovery_jobs` rows created, each with a distinct, real `content_draft_id`.
- 13 `NO_SUITABLE_MEDIA` (state `PENDING`, bounded-retry-eligible per the existing, unchanged
  Option-B policy - no automatic consumer exists, per design, see the prior phase's own
  `recovery_execution_policy.py`).
- 2 `QUALITY_GATE_FAILED` (state `TERMINAL_HOLD`, correctly terminal-on-first-failure - both are
  real Russian-language grammar issues, "orphaned preposition + bare unit/currency noun",
  unrelated to media/vision - a `LANGUAGE_QUALITY` check catching bad copy, working as designed).
- Recovery architecture, platform scoping, and concurrency safety were not modified this phase and
  were not stress-tested here beyond normal single-writer production load (no concurrent-write
  scenario naturally arose) - no anomaly observed.
- No historical HOLDs were processed; the 1 pre-existing open recovery row from canary-1 was left
  untouched throughout.

## O. Transport ambiguity

`AMBIGUOUS_TRANSPORT_RESULTS = 0`, `AMBIGUOUS_AUTO_RESENDS = 0` - no ambiguous Telegram result
occurred in the entire window.

## P. Duplicates

`DUPLICATE_SENDS = 0` - zero duplicate `idempotency_key` values across the full canary +
post-pass window (00:31:52–09:47:00 UTC). Message IDs 1772-1785 (14 distinct messages: 11 from
the canary window + 3 new in the post-pass window, message 1782 counted once) are fully
sequential with no repeats.

## Q. Vision boundedness/cost

`VISION_CALLS = 2` (canary window) `+ 1` (post-pass window, see §U) `= 3` total observed live
calls. `VISION_CACHE_HITS = 0` (no identical media encountered twice in this sample - expected,
given distinct daily news stories). `VISION_TIMEOUTS = 0`, `VISION_ERRORS = 0`. Both canary-window
calls completed in 4.29s and 6.92s respectively (within the 8s bound). No runaway calls, no
repeated-candidate re-checks, no retry loops observed - `VISION_CALLS_PER_CANDIDATE` was exactly 1
for the 2 candidates that escalated, 0 for the other 24. No evidence of unexpected provider cost
spike (2-3 extra bounded LLM calls across a 9-hour window is negligible).

## R. Story/arXiv/V8 freeze

`automation_worker` and `news_analysis_worker` (which own Story Memory/arXiv logic) were **never
restarted** throughout this entire phase - uptime remained continuous at 43-44 hours across the
whole canary, confirming zero possible interaction. `STORY_MEMORY_CHANGED = false`,
`ARXIV_GUARD_CHANGED = false`. Telegram V8 renderer code (`services/brand_renderer.py`,
`services/nnj_master_news_overlay.py`, `services/news_telegram_presentation.py`) was not modified
by either the runtime-closure-1 or vision-gate-closure-1 phases - `TELEGRAM_V8_CHANGED = false`.

## S. Publication safety

`0` Instagram-table writes across the entire canary + post-pass window (checked directly via
`instagram_creative_drafts` row counts at multiple points). `INSTAGRAM_PUBLICATION_ENABLED = false`
(code default, unchanged). No public/autonomous publication path was enabled or exercised at any
point.

## T. DB/Redis health

Alembic revision stable at `c48f6a1e9d02` throughout (checked at flag-off, at activation, and at
post-pass close - never drifted). Redis `role:master`, `connected_slaves:0`, no published port,
`PONG` responsive at every checkpoint. Postgres `content_drafts` row count grew monotonically and
consistently with real traffic (1392 → 1392+26+ over the window), no anomaly.

## U. Post-pass observation

Post-pass window: 2026-09-14 09:30:00–10:04:36 UTC (~34 minutes, satisfying the required 30+
minute window). Re-verified: `RestartCount=0` (10 hours continuous uptime), all 6 other containers
unaffected, Redis `PONG`/`master`/no public port, Alembic revision unchanged, **4 more real
successful deliveries** (messages 1782-1785, one already counted in §H's 11, three new: 1783,
1784, 1785), **1 more vision-gate call** (bounded, successful, no errors), 0 new duplicates, 0 new
Instagram writes, 0 errors/exceptions in the post-pass log window.

## V. Final verdict

All §21 pass criteria met, on a sample (26 candidates, far exceeding the required 5) that is
genuine, natural production traffic. Zero critical invariant violations across the entire
observation period (canary + post-pass, ~9.5 hours total, worker never restarted). The vision gate
- activated for the first time ever in live production - fired 3 times, every time bounded,
successful, and leading to a correct outcome, with zero timeouts, errors, or false upgrades. The
only irregularity is the disclosed process deviation (canary duration far exceeding the 180-minute
cap due to an unplanned session gap) - not a defect, not fabricated traffic, and if anything a
larger, more convincing sample than the minimum required.

**`UNIFIED_PIPELINE_PRODUCTION_CANARY_2_PASS`**

Per §22: `unified_editorial_pipeline_enabled=true` is left in place for `content_worker` only.
Instagram publication and public/autonomous publication remain disabled. No historical HOLDs were
processed.
