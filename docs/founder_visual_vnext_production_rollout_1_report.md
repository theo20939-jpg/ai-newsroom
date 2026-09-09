# FOUNDER-VISUAL-VNEXT-PRODUCTION-ROLLOUT-1 — report

Production rollout of the Founder-approved NINJA PULSE Telegram visual system vNEXT.

**Outcome: `FOUNDER_VISUAL_VNEXT_PROD_BLOCKED`.** The production repository/image state cannot
support a clean, verifiable `content_worker`-only rollup right now. **No production mutation was
performed** — no DB write, no container restart/rebuild/recreate, no git checkout/reset/clean/
merge on the VPS, no candidate materialised, no spec activated, `automation_worker` untouched.

---

## A. Founder-approved spec set

`telegram_news v3` · `telegram_breaking v3` · `telegram_data v3` · `telegram_quote v2` — APPROVED
(the truthful set from `design/proposed_visual_spec_vnext_production_alignment.md`). NEWS/BREAKING
v3 omit `logo_zone` (adaptive safe placement is intentional; RenderEvidence reports the actual
zone). `telegram_data v3` declares only fields true for **both** the hero card and the
source-preserving MINIMAL mode. The rejected misleading `telegram_data` v2/v4 candidates stay
rejected. **None of this was applied — see §S.**

## B. Production access proof (READ-ONLY)

SSH to `root@31.77.219.165` (`~/.ssh/ninja_temp`) **succeeded**.

| field | value |
|---|---|
| hostname | `vm178145.hosted-by.qwins.co` |
| time (UTC) | 2026-09-09 21:20 → 21:59 |
| uptime | 6 days 23h, load ~0.3 |
| DB / Redis | `ai_newsroom_postgres` healthy, `ai_newsroom_redis` healthy |

`docker ps` — all 7 services `Up`, RestartCount `0`:

| container | container ID | image ID | image tag | started |
|---|---|---|---|---|
| ai_newsroom_automation_worker | `2efc4c8b319d` | `f592398ca237` | `ai-newsroom-automation_worker:c6694b9` | 2026-09-09T11:22:52Z |
| ai_newsroom_content_worker | `b416b1c03f77` | `2117583c7445` | `ai-newsroom-content_worker:d2dea2c` | 2026-09-08T21:53:02Z |
| ai_newsroom_news_analysis_worker | `a722b21fdfb4` | `75ed4b0e3779` | `ai-newsroom-news_analysis_worker:d2dea2c` | 2026-09-08T22:48:56Z |
| ai_newsroom_telegram_bot | `aff0902c0ff4` | `ac8fd866dbf8` | `ai-newsroom-telegram_bot:d2dea2c` | 2026-09-08T21:51:58Z |
| ai_newsroom_backend | `bcdbab62156a` | `ddc9cc52b6ba` | `ai-newsroom-backend` | 2026-09-02T21:51:52Z |
| ai_newsroom_postgres | `6d7c65f7db5c` | `44c4ee9810ef` | `postgres:16-alpine` | 2026-09-07T11:10:17Z |
| ai_newsroom_redis | `db6fc18c1f3e` | `e7723ff73d96` | `redis:7-alpine` | 2026-09-06T19:25:02Z |

`content_worker` mounts only the `image_storage_data` volume (no source bind-mount) — it runs
purely from image `2117583c`. (`backend` bind-mounts `/opt/ai-newsroom/{app,core,database}` — not
in scope here.)

## C. Live content_worker SHA / image / container — NOT CONFIDENTLY IDENTIFIED (STOP, §4)

- `LIVE_CONTENT_WORKER_CONTAINER_ID = b416b1c03f77…`
- `LIVE_CONTENT_WORKER_IMAGE_ID = sha256:2117583c7445…` (tag `ai-newsroom-content_worker:d2dea2c`)
- `LIVE_CONTENT_WORKER_SOURCE_SHA = UNKNOWN`

Why UNKNOWN:

1. The image carries **no embedded source SHA** — `/app/GIT_SHA`, `/app/VERSION`, `/app/.git`
   are all absent (`docker run --rm … content_worker:d2dea2c` → `NOFILE`).
2. The image **tag** says `d2dea2c`, but that commit **does not exist in the production git
   repo**: `cd /opt/ai-newsroom && git cat-file -t d2dea2c` → `fatal: Not a valid object name`.
   Same for `c6694b9`, `70cbce7`, `ae0232c`, `0175dc3`.
3. The production checkout `/opt/ai-newsroom` is on a **different branch and lineage**:
   `HEAD = 324a57a9413c…` on `feature/phase19-editorial-depth-upgrade` — "feat: upload discovered
   videos natively to Telegram" (2026-08-30). Recent history:
   `324a57a ← f557b60 (fix: brand all NEWS media and enlarge overlay) ← fe35ca9 (fix: improve
   Story Memory duplicate matching) ← 021ee4b (V2.20D) ← de5ba2e (V2.20C) ← d67bd36`. This branch
   diverged from a `V2.20*` ancestor and never merged the reconciliation/adaptive/board lineage
   the vNEXT specs and renderer are built on.
4. The production checkout has **46 modified tracked files** + 2 stashes + many untracked
   `.env.bak.*` / migration files. Modified files include `services/brand_renderer.py` (a local
   **+45-line** addition of a `_build_data_signature_fallback` variant — different from the
   reviewed lineage), `services/meme_render.py` (+183), `services/final_post_review_notifier.py`,
   `services/telegraph_article_review_notifier.py` (+107), `docker-compose.yml`, `core/config.py`,
   `capabilities/executor.py`.
5. `/opt/ai-newsroom-ops/` shows a **prior aborted visual rollup**: `docker-compose.yml.bak-pre-visual-rollup-1`
   and `p01_c6694b9.bundle` (a thin git bundle that `git bundle verify` rejects —
   `Repository lacks these prerequisite commits: b45e384d3aa9…`).

**A `docker compose build content_worker` on the VPS right now would build from the dirty
`324a57a` tree**, producing an image matching neither the running `content_worker` nor any
reviewed rollup.

## D. Live visual-foundation proof — INCONCLUSIVE

Grepping the **running** image (`content_worker:d2dea2c`, `/app/services/…`):

- `render_evidence.py` and `telegram_art_director_spec_evaluation.py` contain the RenderEvidence /
  Art-spec-evaluation machinery (`NUMBER_MISMATCH`, `INFOGRAPHIC_DESTROYED` grep hits present).
- `brand_renderer.py` has `render_quote_card` + `render_data_card` (old signatures) but **no**
  `render_data_hero_card`, **no** `_QUOTE_MARK_GLYPH`, **no** `_derive_data_hero_evidence`, **no**
  `DataCandidate.series` / `QuoteCandidate.role` — i.e. it is a **pre-`70cbce7`** renderer, as
  expected.

The RenderEvidence + Art foundation appears present, but its **exact provenance cannot be pinned**
(no source SHA, tag references a missing commit). §5 requires proving the foundation on an
**identified** base — that precondition fails.

## E. Exact reviewed runtime delta

The approved board-alignment runtime change is commit **`70cbce7`** (local worktree
`C:/Users/Theodor/ai-newsroom-launch-visual-recap-1`, branch
`feature/launch-readiness-visual-recap-parallel-1`), touching exactly three `services/` files:

| file | change |
|---|---|
| `services/brand_renderer.py` | `+render_data_hero_card()` + constants/helpers; `render_data_card()` FULL_DATA_CARD delegates to it; `render_quote_card()` rewritten (red quote-mark motif, author role, no baked PULSE/NP); `+~215` lines |
| `services/render_evidence.py` | `+_derive_data_hero_evidence()`; `derive_data_render_evidence()` FULL branch routes to it; `+73` lines |
| `services/presentation_director.py` | `DataCandidate +series:tuple=() +delta:str|None`; `QuoteCandidate +role:str|None`; `+12` lines |

`0175dc3` (the launch-readiness audit) and `ae0232c` (this alignment phase) add **zero**
`services/` runtime code. So `A. visual runtime = 70cbce7's 3 files`;
`B. tests/scripts/docs = everything else`; `C. Story-Continuity changes = c6694b9's P0.1 stack`
(NOT wanted on content_worker); `D. control-plane = the candidate scripts` (spec DB only).

## F. Clean rollup construction — CANNOT BE PERFORMED (STOP, §7)

The rollup requires: `LIVE_CONTENT_WORKER_SOURCE_SHA` + the 3 files from `70cbce7`. Blocked
because:

1. **`LIVE_CONTENT_WORKER_SOURCE_SHA` is UNKNOWN** (§C) — there is no identified base to branch
   from.
2. **`70cbce7` / `ae0232c` were never pushed to `origin`.** They are local-only commits in this
   session's worktree. `cd /opt/ai-newsroom && git fetch origin --prune` was run (read-only —
   updates remote-tracking refs only, no checkout/branch/working-tree change) and afterwards the
   VPS still cannot resolve `d2dea2c`, `c6694b9`, `70cbce7`, or `ae0232c`. `origin` has
   `feature/director-control-plane-v1` but its tip is not `d2dea2c` as known locally.
3. Getting `70cbce7`'s files onto the VPS would mean pushing an entire unreconciled
   visual + Story-Continuity-P0.1 lineage to `origin` and pulling it into a repo on a different
   branch with 46 dirty files — **exactly what §4 ("do not overwrite unexplained production
   divergence") and §7 ("do not silently import a chain of unrelated commits") forbid**, and
   risky while the Story Continuity shadow observation runs on `automation_worker:c6694b9`.

`ROLLUP_SHA = —` (not created). `UNRELATED_RUNTIME_FILES = n/a` (no rollup).

## G. ROLLUP_SHA

Not created (§F).

## H. Rollup diff

n/a (§F).

## I. Local tests / static

From the prior phase `VISUAL-SPEC-VNEXT-PRODUCTION-ALIGNMENT-1` (base `70cbce7` renderer): full
relevant sweep **500 passed / 4 skipped / 0 new failures**; ruff + mypy clean on the changed
`services/` files. Not re-run here (no rollup to test).

## J. Production pre-spec state — `PROD_PRE_SPEC_STATE` (READ-ONLY, `docker exec … psql`)

| scope | version | status | parameters | active_from |
|---|---|---|---|---|
| `telegram_news` | 1 | superseded | `{safe_margin 0.019, placement_zone lower_left, logo_zone lower_right, scrim none, source preserve}` | — |
| `telegram_news` | **2** | **ACTIVE** | `{safe_margin 0.019, logo_zone lower_right, scrim none, source preserve}` | 2026-09-08 21:49:51Z |
| `telegram_breaking` | 1 | superseded | (same shape as news v1) | — |
| `telegram_breaking` | **2** | **ACTIVE** | `{safe_margin 0.019, logo_zone lower_right, scrim none, source preserve}` | 2026-09-08 21:49:51Z |
| `telegram_data` | **1** | **ACTIVE** | `{font 48–88, max_line_count 2, safe_margin 0.019, logo_zone lower_right, scrim none, source preserve}` | 2026-09-08 15:46:54Z |
| `telegram_quote` | **1** | **ACTIVE** | `{safe_margin 0.019, logo_zone lower_right, scrim none, source preserve}` | 2026-09-08 15:46:54Z |

`ACTIVE count per scope = 1` for all four (invariant holds). **No vNEXT (v3 / new-v2) rows exist
in production.** Production `telegram_news` / `telegram_breaking` are already on **v2**;
`telegram_data` / `telegram_quote` still on **v1**. (This differs from the dev control-plane DB,
which also carries the v3/v2 CANDIDATE rows — §3 "do not assume production state from prior
reports" was correct to insist on this read.)

## K. DB revision

`alembic_version = 4a1b7c9d2e3f` — matches the value §10 anticipated.

## L. Migration / schema verdict

`MIGRATION_REQUIRED = false` (alembic head is the expected `4a1b7c9d2e3f`; the vNEXT specs need
no schema change — `DeclarativeVisualParameters` already models every field, and adaptive
placement is expressed by omitting the optional `logo_zone`). `VISUAL_SPEC_SCHEMA_GAP = false`.
**No Alembic run, no schema change — and none was attempted.**

## M. Backups

**Not created** — the phase gates backups (§11) after a clean rollup is ready (§7–§10), and the
rollout is blocked before that point. Note: `/opt/ai-newsroom-ops/backups/` already holds recent
control-plane dumps, including `ai_newsroom_pre_visual_spec_v2_rollup_20260908T214036Z.dump` (the
news/breaking v2 activation) and `ai_newsroom_pre_story_continuity_p0_1_20260909T111543Z.dump`.

## N. content_worker rollback

Not applicable — `content_worker` was **not** changed. For a future attempt, the rollback tag
would be `ai-newsroom-content_worker:rollback-pre-founder-visual-vnext` → image `2117583c7445`
(the current live image), rollback = `docker compose up -d --no-deps --force-recreate content_worker`
after re-tagging. Not created this phase.

## O. VisualSpec rollback

Not applicable — no activation performed. `scripts/activate_visual_spec_vnext.py --print-rollback`
was **not** run against production (blocked before §13). Against the **dev** DB in the prior phase
it was verified: `--dry-run` promotes then rolls back, leaving the DB unchanged; rollback =
clone each SUPERSEDED prior row's params to a fresh CANDIDATE, then `promote_candidate()`.
Production rollback targets would be `telegram_news v2` / `telegram_breaking v2` / `telegram_data
v1` / `telegram_quote v1` (the current ACTIVE rows — §J), **not hard-coded "v1"**.

## P. Candidate field verification

Not performed — no candidates were materialised in production (§F blocks the phase before §14).
`CANDIDATE_FIELD_MATCH = n/a`.

## Q. Image build / source proof

`IMAGE_SOURCE_MATCH = n/a` — no image built (§15 gated behind the clean rollup).

## R. Pre-mutation safety flags

Not evaluated in full — the phase never reached §16. Read-only observations: `automation_worker`
healthy and cycling normally (`story_continuity_decision`, `event_recap_scan_finished`,
`automation_cycle_finished` in recent logs); `postgres` / `redis` healthy; all containers
RestartCount 0.

## S. VisualSpec activation

**NOT PERFORMED.** No `create_candidate_spec`, no `promote_candidate`, no SQL write of any kind
against the production control-plane DB. Every production DB access this phase was a read-only
`SELECT`.

## T. Production post-spec state

Identical to `PROD_PRE_SPEC_STATE` (§J) — unchanged. `ACTIVE_COUNT_TELEGRAM_NEWS = 1`,
`ACTIVE_COUNT_TELEGRAM_BREAKING = 1`, `ACTIVE_COUNT_TELEGRAM_DATA = 1`,
`ACTIVE_COUNT_TELEGRAM_QUOTE = 1` — still on v2 / v2 / v1 / v1.

## U. Container before / after matrix

| container | before (container ID / image ID / restarts / startedAt) | after | changed? |
|---|---|---|---|
| automation_worker | `2efc4c8b319d` / `f592398ca237` / 0 / 2026-09-09T11:22:52Z | identical | **NO** |
| content_worker | `b416b1c03f77` / `2117583c7445` / 0 / 2026-09-08T21:53:02Z | identical | **NO** |
| news_analysis_worker | `a722b21fdfb4` / `75ed4b0e3779` / 0 | identical | **NO** |
| telegram_bot | `aff0902c0ff4` / `ac8fd866dbf8` / 0 | identical | **NO** |
| backend | `bcdbab62156a` / `ddc9cc52b6ba` / 0 | identical | **NO** |
| postgres | `6d7c65f7db5c` / `44c4ee9810ef` / 0 / healthy | identical | **NO** |
| redis | `db6fc18c1f3e` / `e7723ff73d96` / 0 / healthy | identical | **NO** |

`CONTENT_WORKER = UNCHANGED`. No container was recreated.

## V. Health gate

Not applicable (nothing deployed). All services observed healthy and unchanged, read-only.

## W. Internal canaries

**Not run** — canaries (§21) are gated behind a successful deploy + health gate. The local
board-alignment canaries from the prior phases remain the evidence of renderer correctness
(`artifacts/founder_visual_board_alignment_1/`, `artifacts/visual_recap_canary/`).

## X–AC. NEWS / BREAKING / DATA generated / DATA infographic / QUOTE / adaptive logo results

Not evaluated in production this phase (no deploy). Locally (prior phases, base `70cbce7`) all
six render classes PASS SPEC_MATCH against the vNEXT candidate set with exactly one NNJ mark, no
clipping, verbatim metric / quote text, adaptive corner reported truthfully by RenderEvidence,
and the `INFOGRAPHIC_DESTROYED` / `NUMBER_MISMATCH` guards hard-BLOCK the negative cases
(`scripts/_visual_spec_vnext_replay.py`, `tests/test_founder_visual_board_alignment_1.py`).

## AD. Art evaluator result

Unchanged — no enforcing veto enabled, no evaluator code changed. Hard-failure enforcement
(`DUPLICATE_NNJ_BRAND_MARK`, `NUMBER_MISMATCH`, `INFOGRAPHIC_DESTROYED`, `TEXT_CLIPPING` → BLOCK)
is proven in the local test suite; the running production image already carries the Art-spec
evaluation machinery.

## AE. Publication safety

No autonomous public publication, no Story Continuity suppression change, no Telegram
channel/profile mutation, no Instagram write, no marketing send — **nothing was published or
sent**. No internal canary was run either (§W).

## AF. automation_worker non-interference

`AUTOMATION_WORKER_TOUCHED = false`. Container `2efc4c8b319d…`, image
`ai-newsroom-automation_worker:c6694b9` (`f592398ca237…`), RestartCount `0`, StartedAt
`2026-09-09T11:22:52.720Z` — **identical before and after**. Recent logs show normal Story
Continuity cycles. Story Continuity observation tooling/state untouched.

## AG. Final production source / spec state

Unchanged from the start of this phase:

- `content_worker` image `content_worker:d2dea2c` (`2117583c`), container `b416b1c03f77`.
- `/opt/ai-newsroom` HEAD `324a57a` on `feature/phase19-editorial-depth-upgrade`, 46 modified
  tracked files, 2 stashes (still present, untouched).
- control-plane DB: `telegram_news v2` / `telegram_breaking v2` / `telegram_data v1` /
  `telegram_quote v1` ACTIVE; alembic `4a1b7c9d2e3f`.
- **Only VPS-side effect this phase:** `git fetch origin --prune` in `/opt/ai-newsroom` refreshed
  remote-tracking refs under `.git/refs/remotes/origin/` (new `origin/feature/*` pointers added;
  stale ones pruned). No local branch, working tree, index, stash, or reflog-of-value change; no
  checkout. Harmless metadata refresh.

## AH. Remaining launch blockers

1. **Production repo/image provenance is unreconciled.** `/opt/ai-newsroom` is on
   `feature/phase19-editorial-depth-upgrade` (`324a57a`), 46 dirty tracked files + 2 stashes;
   the running images are tagged with SHAs (`d2dea2c`, `c6694b9`) that the on-disk repo cannot
   resolve, and no image embeds a source SHA. A safe `content_worker`-only rollup cannot be built
   or verified against an unknown, dirty base.
2. **The approved renderer commit `70cbce7` (and `ae0232c`) is local-only.** It must be pushed to
   `origin` (on its own, ideally as an isolated 3-file visual commit — not the full
   `c6694b9`-based branch) before any VPS-side rollup is possible.
3. **`telegram_data` / `telegram_quote` production specs are still v1** (not v2). The Founder-
   approved target is `telegram_data v3` / `telegram_quote v2`; `telegram_news` / `telegram_breaking`
   production is already v2 and would move to v3.
4. Founder-side reconciliation of the divergent production branch + dirty tree is a prerequisite,
   and is a Story-Continuity-adjacent operation (the dirty tree touches `core/config.py`,
   `docker-compose.yml`, `capabilities/executor.py`) — it must be done carefully and **not** by
   this visual rollout.

### Recommended path to unblock (Founder + a dedicated production-reconciliation step)

1. On the VPS, decide the canonical `content_worker` source: either (a) rebuild from a clean,
   pushed, identified SHA, or (b) formally adopt `324a57a` + the reviewed subset of the 46 dirty
   changes as the baseline and commit it to a real branch. Record the resulting
   `CONTENT_WORKER_BASELINE_SHA`.
2. Push the isolated visual delta: from this worktree, create a branch off
   `CONTENT_WORKER_BASELINE_SHA` (fetched locally) carrying **only** `70cbce7`'s three
   `services/` files, and push it to `origin` as `release/founder-visual-vnext-content-worker-1`.
3. Re-run this rollout phase: fetch that branch on the VPS, `git diff CONTENT_WORKER_BASELINE_SHA..release/…`
   must show only the 3 visual files (`UNRELATED_RUNTIME_FILES = 0`), then proceed through
   §8–§22 (rollup tests → prod spec read → backups → candidate materialisation → image build →
   transactional spec activation → `content_worker`-only recreate → health → internal canaries).

---

## Verdict

Production access works and the production spec state was read (`telegram_news v2` /
`telegram_breaking v2` / `telegram_data v1` / `telegram_quote v1` ACTIVE; alembic
`4a1b7c9d2e3f`). But a **clean, verifiable, visual-only `content_worker` rollup cannot be
constructed**: the live `content_worker` source SHA is not identifiable (image has no embedded
SHA; its `d2dea2c` tag references a commit absent from the production repo, which is on a
different branch with 46 uncommitted changes and 2 stashes), and the approved renderer commit
`70cbce7` is not present on `origin` or the VPS. Importing it would drag in an unreconciled
lineage — forbidden by §4/§7 and unsafe beside the live Story Continuity shadow observation.

No production DB write, no container change, no git working-tree change on the VPS,
`automation_worker` untouched, nothing published.

**FOUNDER_VISUAL_VNEXT_PROD_BLOCKED**

Do not retry until the production `content_worker` baseline is reconciled and the isolated visual
delta is pushed to `origin` (see §AH). Wait for Founder review.
