# FOUNDER-VISUAL-V8-PRODUCTION-ROLLOUT-1 - plan (NOT executed)

Prepared by FOUNDER-VISUAL-V8-FINAL-RELEASE-PREP-1. This document is the exact
next-phase runbook. **Do not execute any step here in the prep phase.**

## Inputs (frozen by the prep phase)

| name | value |
|---|---|
| `V8_RELEASE_SHA` | `d0a03773bebc98c6b71edb67fe368b85472e2d6b` |
| release branch | `release/founder-visual-v8-content-worker-1` (on origin) |
| baseline | `d2dea2cd7d5da714988217b1286afb8b96c26bb9` (proven live `content_worker` source) |
| superseded release | `a3fd0dcab034b01a22e86f6f8480bedfb5bf2cc1` - **DO NOT DEPLOY** |
| constraints file | `artifacts/founder_visual_v8_final_release_prep_1/constraints-content-worker-live.txt` (56 exact pins == live freeze) |
| base image pin | `FROM python:3.12.14-slim-trixie` (matches the running interpreter build; OS-snapshot digest not recoverable - documented limitation) |
| `FINAL_V8_SPEC_SET` | see the prep report section O (news: drop `source_image_treatment`; breaking: reuse v3; data: `font_size_max 300`/`font_size_min 100`; quote: reuse v2) |
| SSH | `root@31.77.219.165` via `~/.ssh/ninja_temp` |
| scope | `RUNTIME_DEPLOY_SCOPE = [content_worker]` ONLY |

## Hard preconditions (all must hold before step 1)

1. **Story Continuity constrained-enforcement canary on `automation_worker` is
   COMPLETE and declared stable.** Not mid-window. This is a blocking ordering
   constraint - the rollout must not perturb the VPS while that canary is being
   observed.
2. Explicit Founder authorization to run the rollout.
3. `origin/release/founder-visual-v8-content-worker-1 == d0a0377`.
4. No unexpected drift on the VPS repo / compose / env since this plan was written.

## Ordered gate

### 1. Read-only production preflight (SSH)

* `docker ps` - record every container image tag + status + uptime.
* `content_worker`: image id, `Created`, `StartedAt`, restart count.
* Control-plane DB: current ACTIVE spec rows for `telegram_news` / `telegram_breaking`
  / `telegram_data` / `telegram_quote` (scope, version, status, id); `alembic current`.
* Health endpoints for `content_worker` (and `automation_worker` - observe only).
* Disk free on `/`, Docker data root.
* `automation_worker` image id + uptime - **record only; never touch.**

### 2. Verify `content_worker` still `d2dea2c`

* Container image tag `ai-newsroom-content_worker:d2dea2c`, image id begins
  `sha256:2117583c7445...`.
* `docker exec ai_newsroom_content_worker pip freeze` == the prep constraints file
  (56 lines, ignoring `ai-newsroom @ file:///app`).
* If either differs -> **STOP**, re-run provenance reconciliation.

### 3. Backups (before ANY write)

* `pg_dump` the control-plane DB -> timestamped file under `/opt/ai-newsroom-ops/`.
* Copy `.env`, `docker-compose.yml` -> same backup dir.
* `docker tag ai-newsroom-content_worker:d2dea2c ai-newsroom-content_worker:rollback-d2dea2c`
  and `docker save` it to a `.tar` in the backup dir.
* Verify the `pg_dump` restores into a scratch database (dry restore) before proceeding.

### 4. Rollback assets recorded

* Rollback image tag: `ai-newsroom-content_worker:rollback-d2dea2c` (+ the saved tar).
* Rollback spec state: the section-1 ACTIVE spec row ids, plus the output of
  `activate_visual_spec_vnext.py --print-rollback` (captured in step 6 before promote).

### 5. Fetch + build the release image

* Clean checkout of `d0a0377` (fresh clone or `git fetch` + `git checkout --detach d0a0377`
  in an isolated build dir; **not** the live repo working tree).
* Build with the pinned base + constraints:
  ```
  docker build \
    --build-arg none \
    -f Dockerfile \
    -t ai-newsroom-content_worker:v8-d0a0377 .
  ```
  where `Dockerfile` for this build is `FROM python:3.12.14-slim-trixie` and
  `pip install --no-cache-dir -c constraints-content-worker-live.txt .`
  (the prep phase verified this exact recipe builds and passes).
* In the built image, re-verify (as in the prep report section M):
  `IMAGE_SOURCE_MATCH = true`, `FONT_ASSETS_PRESENT = true`, `IMPORT_SMOKE = PASS`,
  and a DATA-hero render at 1280x1172 with Cyrillic.

### 6. Materialize + verify `FINAL_V8_SPEC_SET` (still CANDIDATE)

* Run the (idempotent, `--dry-run` first) proposal script to create the CANDIDATE
  rows for `telegram_news`, `telegram_data` with the section-O parameters, reusing
  the existing `telegram_breaking` v3 / `telegram_quote` v2 candidates.
* `AUTO_PROMOTION = false`. Rows are CANDIDATE only at this point.
* Diff each new candidate's `parameters` against the prep report section O. **Any
  mismatch -> STOP.**
* Capture `activate_visual_spec_vnext.py --print-rollback`.

### 7. Activate the specs transactionally

* Single DB transaction: `promote_candidate()` for all four scopes ->
  ```
  telegram_news     -> new vN   ACTIVE   (prior ACTIVE -> SUPERSEDED)
  telegram_breaking -> v3       ACTIVE   (prior ACTIVE -> SUPERSEDED)
  telegram_data     -> new vN   ACTIVE   (v1 -> SUPERSEDED)
  telegram_quote    -> v2       ACTIVE   (v1 -> SUPERSEDED)  [no-op if params == v1]
  ```
* Verify the four ACTIVE rows read back with exactly the section-O parameters.
* If the transaction fails or read-back mismatches -> roll back the transaction,
  **STOP**, do not touch the container.

### 8. Recreate ONLY `content_worker`

```
docker compose up -d --no-deps --force-recreate content_worker
```
* `--no-deps` so `postgres` / `redis` / `automation_worker` / `telegram_bot` are
  NOT recreated.
* Confirm `automation_worker` image id + container id are unchanged after this step.

### 9. Health gate

* `content_worker` container `healthy`; no crash loop; logs clean for 5 min.
* DB reachable from the container; worker heartbeat / cycle log advancing.
* If unhealthy within 10 min -> **rollback** (step 12).

### 10. Internal canaries only

* Trigger internal renders of NEWS / BREAKING (dark + bright) / DATA generated
  (`500/МЛН`, `68/%`, `1,4 млрд`) / DATA source-preserving / QUOTE / QUOTE-no-role
  into the **internal review channel** only.
* Verify each: correct canvas size, RenderEvidence `renderer_version`
  (`pulse-data-hero-v4-square`, `pulse-breaking-v7-board`), one NNJ, real Cyrillic,
  numbers verbatim, no Art BLOCK on the approved canaries.
* Compare against the prep-phase approved reference renders (allow glyph-edge
  JPEG-encoder byte differences per the prep report section N; layout/typography must
  match).

### 11. No public publication

* No post to any public channel during the canary window. `automation_worker`
  continues on its own unchanged image.

### 12. Rollback (on ANY failure in steps 8-11)

1. `promote_candidate()` the prior spec versions from the step-6 `--print-rollback`
   output (transactional).
2. `docker compose up -d --no-deps --force-recreate content_worker` using
   `ai-newsroom-content_worker:rollback-d2dea2c` (retag to `:d2dea2c` or point compose
   at the rollback tag).
3. Health-gate the rolled-back container.
4. Restore the control-plane DB from the step-3 `pg_dump` only if spec rollback
   read-back is inconsistent.
5. Report `FOUNDER_VISUAL_V8_PRODUCTION_ROLLOUT_ROLLED_BACK` with the failing gate.

### 13. Success criteria

* `content_worker` on `v8-d0a0377`, healthy, > 30 min stable.
* Four `FINAL_V8_SPEC_SET` rows ACTIVE, fields verified.
* All internal canaries pass; no Art BLOCK on approved classes; no factual /
  single-NNJ violation.
* `automation_worker` untouched (image id + container id identical to preflight).
* No public publication occurred during the canary window.
* -> `FOUNDER_VISUAL_V8_PRODUCTION_ROLLOUT_PASS`; hand the canary window to the
  Founder for public-enable authorization (a separate decision).

## Never in this rollout

* No `automation_worker` restart / rebuild / flag change.
* No Story Continuity code / clustering / identity-guard change.
* No touch of the Story Continuity production canary shell/process.
* No public channel publication.
* No `pyproject.toml` dependency-policy rewrite (constraints file only).
* No deploy of `a3fd0dc`.
