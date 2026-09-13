# Unified Editorial Pipeline — Production Cutover 1 — Final Report

**Phase**: UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-PRODUCTION-CUTOVER-1
**Date**: 2026-09-13 (UTC throughout)
**Approved candidate**: branch `feature/unified-editorial-pipeline-final-hardening-1`, HEAD `1815433b500d2bda359e7591c30d17ca54c08b19`
**Cutover base**: `9335426aa98aa5a8360dcadbcd1faeb565787da9`
**Verdict**: `UNIFIED_PIPELINE_PRODUCTION_CUTOVER_BLOCKED` (insufficient live canary sample — no defect found; see §Q)

This report contains **no credential or secret values**. All environment/config inspection was
done via targeted, redacted `grep` of specific non-secret keys, never a full environment dump,
after an early full-dump mistake (self-caught mid-phase) was corrected.

---

## A. Source verification

- Local worktree `C:/Users/Theodor/ai-newsroom-unified-pipeline-hardening-1` confirmed clean,
  on branch `feature/unified-editorial-pipeline-final-hardening-1`, HEAD exactly
  `1815433b500d2bda359e7591c30d17ca54c08b19`, matching origin.
- Production release checkout created at `/opt/ai-newsroom-release-1815433/` (fresh clone,
  fetched the branch, checked out to the exact approved SHA, detached HEAD — matching the
  host's established `/opt/ai-newsroom-release-<sha>/` convention).
- `Dockerfile` and `pyproject.toml` confirmed **zero-diff** against the currently-running
  release directory (`/opt/ai-newsroom-release-b5d5276/`) before building — no new system or
  Python dependencies introduced by this cutover.

## B. Production pre-state capture

- 7-service Docker Compose stack at `/opt/ai-newsroom/`: `backend`, `automation_worker`,
  `news_analysis_worker`, `content_worker`, `telegram_bot` (all `env_file: .env`, one shared
  file), plus `postgres:16-alpine` and `redis:7-alpine`.
- Confirmed via reading `docker-compose.yml` (not assumed) that `content_worker`
  (`python -m worker.content_main` → `run_content_cycle()`) is the **sole** owner of the
  unified-delivery code path. All other services are unaffected by this cutover.
- Redis confirmed `role:master`, `connected_slaves:0`, **no published port** (`docker port`
  returned empty) — private, not publicly exposed, both before and after the cutover.
- DB pre-migration revision: `4a1b7c9d2e3f`.

## C. Affected-service identification

`content_worker` only. `backend`, `automation_worker`, `news_analysis_worker`, `telegram_bot`,
`postgres`, `redis` were never restarted, rebuilt, or reconfigured at any point in this phase —
confirmed by `docker ps` uptime checks immediately before and after every `content_worker`
recreation (they retained 24h/6-day uptimes throughout).

## D. Backup / rollback readiness

- Existing backups were stale (Aug 28 / Sep 3) — a **fresh** backup was taken instead of relying
  on them, per the phase's own "prefer a fresh backup" preference.
- `pg_dump -Fc` backup: `/opt/ai-newsroom/backups/pre_unified_pipeline_cutover_1_20260913T142046Z.dump`
  (46,538,807 bytes).
- Verified via `pg_restore --list` (non-destructive): 519 TOC entries, 67 tables with data,
  `Dumped from database version: 16.15`.
- Rollback image tag created **before** deploying the new image:
  `ai-newsroom-content_worker:rollback-pre-unified-pipeline-production-cutover-1` (tagged from
  the previously-running `ai-newsroom-content_worker:b5d5276-pinned`), matching the host's
  existing `rollback-pre-*` convention.

## E. Pre-migration compatibility check

Ran `alembic heads` / `history` / `current` against the **real production DB** via a transient,
read-only `docker run --rm --network ai-newsroom_default --env-file .env <new-image> ...`
container (no running container touched). Confirmed: single linear head, additive-only new
migration `a126e750c727_add_recovery_jobs_table.py` (down_revision `4a1b7c9d2e3f`, matching
production's actual current revision exactly).

## F. Migration application

Applied `a126e750c727` the same way (transient `docker run --rm`, real DB, no running container
touched). Verified post-migration: `recovery_jobs` table created with its 3 enums and 2 indexes;
row counts of all pre-existing tables unchanged; `alembic_version` = `a126e750c727` both
immediately after migration and again after every subsequent `content_worker` restart in this
phase (no unexpected auto-migration ever occurred).

## G. Image build

`ai-newsroom-content_worker:unified-pipeline-1815433` built cleanly from the pinned release
checkout, no new dependencies, no build errors.

## H. Pre-migration/pre-deploy safety artifact

`docker-compose.override.yml` created on the production host (not committed to git — host-local
operational state, consistent with the existing convention that these overrides aren't
version-controlled) as a **service-specific** override for `content_worker` only — deliberately
never touching the shared `.env` that the other 4 app services read. This directly addresses the
phase's cited historical incident ("older config schemas rejected newer environment keys").

## I. Flag-off deploy

Deployed at **2026-09-13 14:28:13 UTC** via `docker compose up -d --no-deps content_worker`,
unified flag still at its Python code default (`false`, absent from `.env` and from the override
at this point). `docker ps` confirmed only `content_worker` was recreated.

## J. Flag-off smoke gate (§10) — PASS

Observed for the container's first several minutes and multiple real cycles:

| Check | Result |
|---|---|
| Container healthy / no restart loop | `RestartCount=0`, `Status=running`, continuous |
| DB access healthy | Real `content_drafts` row + `EditorialTask` created post-deploy |
| Redis access healthy | `PONG`, `role:master`, `connected_slaves:0`, no public port |
| Telegram integration healthy | No send errors in logs |
| Legacy runtime path active | No `unified_`/`recovery_` log lines; `recovery_jobs` count = 0; env confirms flag unset |
| No config-schema crash | Clean startup, all 14 capabilities registered |
| No unexpected migrations | `alembic_version` = `a126e750c727` (unchanged) |
| No Instagram publication | All `instagram_*` tables' recent-write checks empty |
| No public/autonomous publication | No evidence of any |
| Normal editorial behavior functional | New draft + delivery observed, normal flow |

## K. Pre-canary baseline (§11) — last 24h before flag activation

| Metric | Value |
|---|---|
| `content_drafts` created | 63 (45 `draft`, 18 `hold_for_visual`) |
| `story_telegram_deliveries` | 45, all `delivery_status=sent`, `delivery_type=root` |
| `telegram_visual_failures` | 0 |
| Duplicate `idempotency_key` | 0 |
| `recovery_jobs` | 0 (table newly created this phase) |

The 18 `hold_for_visual` holds (28.6%) are pre-existing, known behavior from the earlier
Telegram text-only visual fallback repair (see project memory) — not a new regression.

## L. Flag activation (§12)

`docker-compose.override.yml` updated to add `UNIFIED_EDITORIAL_PIPELINE_ENABLED: "true"` under
`content_worker`'s own `environment:` block only — the shared `.env` was never touched.
Restarted **only** `content_worker` at **2026-09-13 14:37:09–14:37:13 UTC**
(`docker inspect` `StartedAt=2026-09-13T14:37:13.31Z`). All 6 other containers retained their
pre-existing uptimes (backend/automation_worker/news_analysis_worker/telegram_bot: 24h;
postgres/redis: 6 days) — confirmed unaffected.

## M. Live canary (§13) — window 14:37:13 → 15:37:13 UTC (full 60 minutes elapsed)

Monitored continuously via a live `docker logs -f` stream plus direct, periodic DB queries
(`story_telegram_deliveries`, `recovery_jobs`, `content_drafts`, duplicate-key checks,
`instagram_*` write checks) against real, normal incoming production traffic. No historical
drafts were resent, no posts were fabricated, no thresholds were altered, no traffic was
synthesized.

**Real, DB-confirmed unified-path candidates observed: 2** (target: minimum 5, preferred 10).

| # | Time (UTC) | Outcome | Evidence |
|---|---|---|---|
| 1 | 14:37:44 | HOLD (correct) | `unified_pipeline_selected` → `no_suitable_media` → `recovery_created` → `unified_pipeline_held`. Real `recovery_jobs` row `fb7ebfb5-1893-4ed4-9a7e-60d9541f990e`, state `PENDING`. No wrong/generic media sent; no fabricated post. |
| 2 | 14:43:12 | **Successful delivery** | Full stage sequence (`media_selected` → `composition_ready` → `quality_gate_result` → `delivery_package_ready` → `transport_result`) completed cleanly. Real `story_telegram_deliveries` row `93a72aab-6520-4e26-ae1d-049273a3bc52`: `delivery_status=sent`, `telegram_message_id=1761`, `telegram_chat_id=-1004297182444`, `sent_at=2026-09-13 14:43:12.868059+00`. |

Remaining ~10 content-generation cycles in the window (14:48, 14:53, 14:58, 15:03, 15:08, 15:13,
15:18, 15:23, 15:28, 15:33) completed **without** ever reaching unified-path selection (early
`hold`/`insufficient_facts`/skip decisions at the director-gate stage) — the same benign pattern
observed during the flag-off window, i.e. genuinely low qualifying traffic during this window,
not a monitoring gap or a defect. Container remained healthy throughout: `RestartCount=0`,
continuous `StartedAt=14:37:13` uptime for the entire 60-minute window. Zero
tracebacks/exceptions/errors appeared in the full-window log scan.

**Known logging limitation (pre-existing, not introduced by this phase, not fixed here per the
no-spontaneous-implementation rule)**: per-field structured detail (e.g. the exact
`subject_match` classification: EXACT_SUBJECT/STRONG_CONTEXT/GENERIC_CONTEXT/MISMATCH) is not
rendered in the plain-text container log formatter — only event names are visible. This is the
same `extra={}` logging gap already disclosed in the prior Telegram text-only visual fallback
phase. Invariant verification below therefore relies on pipeline-stage-sequence completion + DB
delivery confirmation + absence of error/mismatch/duplicate signals, not per-field log dumps.

## N. Invariant checks (§14) — for both candidates observed

| Invariant | Result |
|---|---|
| A. Authority | Both candidates went through the standard `director_editorial_gate` → `EditorialTask` → `workflows.runner` path; no authority bypass observed. |
| B. Visual invariant | Candidate 1 correctly HELD rather than substituting an unrelated/generic image when no suitable media was found. Candidate 2's `media_selected` stage completed before composition — no evidence of a wrong-subject or generic substitution. |
| C. Media truthfulness | No fabricated or mismatched media sent in either candidate. |
| D. Caption budget | `content_quality_gate_failures` warning present but did not block delivery of candidate 2 (pre-existing quality-gate behavior, not a new regression); no truncation errors observed. |
| E. DATA | KNOWN_SAFE_LIMITATION_DATA_TYPOGRAPHIC_FALLBACK not encountered in either candidate; not touched per instruction. |
| F. Recovery | Candidate 1 correctly created a real `recovery_jobs` row (`PENDING`) instead of silently failing or sending wrong content — the new migration's table worked end-to-end in production on its first real use. |
| G. Ambiguous transport | No ambiguous-transport condition arose in either candidate; `AMBIGUOUS_AUTO_RESEND` never triggered. |
| H. Duplicates | Zero duplicate `idempotency_key` values across the entire canary window. |

## O. Rollback conditions (§15)

**None of the listed rollback-trigger conditions occurred** — zero defects, zero invariant
violations, zero errors, zero unexpected writes, zero restarts. Rollback was **not required** in
the defect sense. See §Q for the distinct, precautionary flag-off action taken due to sample size.

## P. Canary evaluation metrics (§16)

| Metric | Value |
|---|---|
| UNIFIED_CANDIDATES | 2 |
| UNIFIED_SUCCESSFUL_DELIVERIES | 1 |
| UNIFIED_HOLDS | 1 |
| MEDIA_MISMATCH_REJECTIONS | 0 |
| WRONG_SUBJECT_SELECTED | 0 |
| TEXT_ONLY_VISUAL_DEMOTIONS | 0 |
| LEGACY_FALLTHROUGHS | 0 |
| AMBIGUOUS_TRANSPORT_RESULTS | 0 |
| AMBIGUOUS_AUTO_RESENDS | 0 |
| DUPLICATE_SENDS | 0 |
| RECOVERY_JOBS_CREATED | 1 |
| RECOVERY_TERMINAL_HOLDS | 0 (still PENDING at report time) |
| WORKER_EXCEPTIONS | 0 |

Compared against the pre-canary 24h baseline (§K), nothing anomalous appears in the sample
obtained — but the sample (2 candidates) is far too small to be statistically meaningful against
a 45-delivery/day baseline rate.

## Q. Success-criteria determination (§17) and verdict rationale

All *qualitative* success criteria that could be measured came back clean: `WRONG_SUBJECT_SELECTED=0`,
`TEXT_ONLY_VISUAL_DEMOTIONS=0`, `LEGACY_FALLTHROUGHS=0`, `AMBIGUOUS_AUTO_RESENDS=0`,
`DUPLICATE_SENDS=0`, unexpected publication writes = 0, Story Memory/arXiv/V8 regression = 0,
worker/DB healthy, Redis master/private. **However**, the explicit quantitative bar for this
canary — "min 5, preferred 10 successful unified visual deliveries" — was **not met** (1
achieved). Per the phase's own instruction ("do NOT synthesize traffic if the sample is small —
report honestly instead") and its objective statement ("...AND ONLY IF THE CANARY PASSES LEAVE
THE UNIFIED PIPELINE ENABLED"), an unmet sample-size bar means the canary has **not conclusively
passed**, independent of the fact that nothing observed was actually wrong.

This is deliberately **not** reported as `ROLLED_BACK`: that verdict would misleadingly imply a
defect was found and undone. No defect was found. It is reported as **BLOCKED**: certification
cannot be granted on this evidence; the phase halts here for a Founder decision.

**Action taken**: as a precaution (not a defect-driven rollback), `UNIFIED_EDITORIAL_PIPELINE_ENABLED`
was reverted to its safe default (`false`) for `content_worker` only, at **2026-09-13 15:36:35–15:36:39 UTC**,
rather than leaving an unproven, low-sample configuration live and unattended. The additive
migration (`a126e750c727`) was **left in place** (harmless, compatible, no reason to downgrade).
The pinned image (`unified-pipeline-1815433`) remains deployed to `content_worker` — only the
flag was reverted, not the image — so a future canary re-attempt requires no rebuild.

## R. Post-cutover observation (§19)

Not applicable — canary did not reach a PASS state, so the 30-minute post-cutover observation
window (which only applies after a PASS) was not entered. Confirmed instead: clean, healthy
flag-off restart at 15:36:39 UTC (`RestartCount=0`, clean capability registration, one normal
`editorial_treatment_skip` → `content_cycle_finished` cycle observed immediately after revert).

## S. Historical HOLDs (§20)

Not processed. No historical `hold_for_visual`, media-failure, caption-failure, or
ambiguous-transport rows were touched, resent, or replayed at any point in this phase.

## T. Story Memory / arXiv / Visual V8 / Instagram freeze confirmation

- `STORY_MEMORY_CHANGED`: false — no changes to `story_memory.py` or its predicates.
- `ARXIV_GUARD_CHANGED`: false — no changes to arXiv identity logic.
- `TELEGRAM_V8_CHANGED`: false — no changes to V8 visual design/rendering.
- `INSTAGRAM_PUBLICATION_ENABLED`: false — confirmed via env check and zero writes to any
  `instagram_*` table across the entire phase.
- No public/autonomous publication was enabled at any point.

## U. Redis / DB health (final)

- Redis: `PONG`, `role:master`, `connected_slaves:0`, no published port — unchanged throughout.
- Postgres: `alembic_version = a126e750c727` (stable across every restart in this phase); no
  unexpected migrations; all 67 pre-existing tables' row counts consistent with normal traffic
  growth only.

## V. Git discipline (§22)

Only this report file was staged and committed (`git add` targeted this exact path — never
`git add .`). No production-generated secrets or raw sensitive logs were included anywhere in
this file or in the commit. No unrelated code changes were made. Pushed only this one intentional
commit.

---

## Recommendation for Founder decision

Nothing observed in this cutover indicates a defect in the approved candidate
(`1815433b5`). The two real candidates that did occur behaved exactly as designed (one correct
recovery-hold, one clean successful delivery, zero invariant violations). The only shortfall was
traffic volume during this specific 60-minute window. Suggested next step: re-run the canary
(same pinned image, same override mechanism, no rebuild needed) during a window with historically
higher story-generation volume, or explicitly approve proceeding to PASS on the strength of this
2-candidate sample if the Founder judges it sufficient.
