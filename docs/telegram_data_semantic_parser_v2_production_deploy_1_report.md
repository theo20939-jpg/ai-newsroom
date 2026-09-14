# TELEGRAM-DATA-SEMANTIC-PARSER-V2-PRODUCTION-DEPLOY-1

Status: **BLOCKED before the production cutover write** — every verification, build, and
regression gate passed; the actual `docker-compose.override.yml` update (and the resulting
`content_worker` restart) is blocked by the execution harness's own auto-mode classifier
(`reason: [Production Deploy]`), which does not appear transient (repeated on retry). Production
is **completely unchanged** — `content_worker` is still running `instagram-editorial-delivery-
4d3c2f0`, `RestartCount=0`, override file untouched (verified at time of writing this report).

**A mid-task discovery reshaped this phase**: production had switched, ~9 minutes into this
phase's own verification, to a real, independently-deployed release
(`feature/instagram-telegram-editorial-delivery-1` @ `4d3c2f0`) that has no ancestry relationship
with the approved DATA fix (`f5b5225`) — confirmed via `git merge-base --is-ancestor` in both
directions (neither is an ancestor of the other). Per the Founder's own direction after this was
flagged, this phase pivoted to building a combined integration release instead of deploying
`f5b5225` alone (which would have silently reverted the Instagram-Telegram work).

---

## A. Production base

Verified TWICE (state changed between checks — see above):

- At phase start: `content_worker` running `unified-vision-77a105f`, `RestartCount=0`,
  `UNIFIED_EDITORIAL_PIPELINE_ENABLED=true`, DB `alembic_version=c48f6a1e9d02`, Redis
  `role:master`/`connected_slaves:0`/no public port mapping.
- ~15 minutes later, before the build step: `content_worker` AND `telegram_bot` both running
  `instagram-editorial-delivery-4d3c2f0` (started `2026-09-14T18:34:23Z`), DB
  `alembic_version=b7d1f92a4e6c` (the Instagram migrations had been applied as part of that
  deployment). This is the state used for the rest of this phase.

## B. Release source

```
feature/telegram-data-semantic-parser-v2-1 @ f5b5225   (the approved, Founder-reviewed DATA fix)
```

Verified: `LOCAL_HEAD == REMOTE_HEAD`, working tree clean, `git log -10` shows the expected
lineage (`f5b5225 -> 45de6d4 -> 39f764b -> 77a105f -> ...`).

## C. Combined diff audit

Per Founder direction, created an isolated worktree/branch
`feature/telegram-data-semantic-parser-v2-instagram-integration-1`, based on the CURRENTLY-RUNNING
production tip `4d3c2f0` (never touching `/opt/ai-newsroom`'s own working tree), and merged
`f5b5225` into it.

**Zero file-level overlap** between the two lineages, confirmed before merging
(`git diff 39f764b..4d3c2f0 --name-only` vs `git diff 39f764b..f5b5225 --name-only` — no common
path; the one file that looked close, `services/editorial_pipeline/contracts.py`, is touched by
the Instagram side only — this phase's DATA fix never touches it, it only populates an
already-existing dataclass field at the Python level).

`git merge --no-edit f5b5225` from `4d3c2f0` → **clean merge, zero conflicts** (merge commit
`6e91f6c`). Audited both directions:

- `git diff 4d3c2f0..6e91f6c --stat` → exactly the 19 files the DATA fix touches, byte-identical
  content to `f5b5225`'s own diff against its own base.
- `git diff f5b5225..6e91f6c --stat` → exactly the 59 files the Instagram-Telegram lineage
  touches, byte-identical to `4d3c2f0`'s own diff against `39f764b`.

No unexpected files, no cross-contamination, no unrelated changes in either direction.

## D. Regression accounting

Chunked/targeted (not one monolithic run - matching the resource-constrained pattern already
established in this phase's own development work):

- **DATA blast radius** (every test that imports `content.py` or its real consumers, plus every
  DATA/RenderEvidence/brand_renderer suite): **224 passed, 0 failed**.
- **Instagram-Telegram blast radius** (every `test_instagram_*` suite plus the platform renderer/
  art-validator suites): **175 passed, 0 failed**.
- **Story Memory / arXiv / Vision Gate** (explicitly named in the original deploy brief's required
  chunk list, to confirm the merge itself introduces no cross-cutting surprise): **294 passed, 0
  failed**.
- **Total: 693 passed, 0 failed** across all three sweeps on the merged integration branch.

`ruff check` and `mypy` both clean on every touched production file from both lineages
(`content.py`, `brand_renderer.py`, `render_evidence.py`, `instagram_telegram_delivery.py`,
`contracts.py`).

This does not re-run the full ~493-file repository suite a third time (the DATA lineage alone was
already fully chunk-swept in the prior development phase - 489/489 files, 47 pre-existing/
environment-caused failures individually triaged and characterized, zero new). Given (a) zero
file-level overlap between the two lineages, (b) an exact, clean merge audited against both
parents, and (c) both blast radii plus the cross-cutting Story Memory/arXiv/Vision Gate suites all
fully green on the merged commit, this is treated as sufficient regression evidence for the merge
itself.

`NEW_FAILURES = 0`

## E. Semantic replay matrix

Unchanged from the DATA fix's own development-phase verification (the merge does not touch
`content.py` beyond what `f5b5225` already established) - re-confirmed passing on the merged
branch via the 224-test DATA blast-radius sweep above, which includes every test in
`tests/test_telegram_data_semantic_overflow_hotfix_1.py` and
`tests/test_telegram_data_semantic_parser_v2_1.py` (NASA/ASML/Maxus/comparator/pathological/
unknown-unit/geometry cases - see that phase's own report for the full matrix).

## F. Rollback preparation

```
PREVIOUS_IMAGE_TAG    = ai-newsroom-content_worker:instagram-editorial-delivery-4d3c2f0
PREVIOUS_IMAGE_ID     = (the currently-running image; not overwritten - still present and tagged)
```

No rebuild required to roll back - the previous image remains tagged and present on the host. Not
exercised this phase since no cutover occurred.

## G. Build

Cloned fresh at `/opt/ai-newsroom-release-6e91f6c` (never touching `/opt/ai-newsroom`'s own
checkout), checked out exactly `6e91f6c`, working tree clean. Built:

```
NEW_IMAGE_TAG    = ai-newsroom-content_worker:data-semantic-v2-instagram-6e91f6c
NEW_IMAGE_ID     = sha256:bba87bcdb00ec63872e2c733e6e58c74299b8b367a02db19e2989c7ed4b1e6b0
NEW_IMAGE_DIGEST = sha256:bba87bcdb00ec63872e2c733e6e58c74299b8b367a02db19e2989c7ed4b1e6b0
```

**Verified byte-for-byte correspondence to the approved source before considering deployment**:
`services/editorial_pipeline/content.py`'s SHA-256 inside the built image
(`34ed9f48cddb13e15340c380675ead10831beda2fc3e8968b2239a2d8b5b0290`) matches the local approved
worktree file exactly (same hash, confirmed both sides independently) - no uncommitted local
modification could have entered the image.

`telegram_bot` was deliberately NOT rebuilt - the DATA fix touches zero files under `bot/`
(verified: `git diff 4d3c2f0..6e91f6c --name-only | grep '^bot/'` → zero matches), so its
already-running Instagram-callback-routing image needs no change at all (§10's own "deploy
minimally" instruction).

## H. Deployment

**NOT PERFORMED.** The prepared `docker-compose.override.yml` update (pinning `content_worker`
only to the new image, leaving `telegram_bot`'s existing pin untouched, keeping
`UNIFIED_EDITORIAL_PIPELINE_ENABLED=true`) was blocked by the harness's own auto-mode classifier
(`Reason: [Production Deploy]`) on two separate attempts (not a one-off "Stage 2... usually
transient" message - a direct, repeated `[Production Deploy]` denial). Per the tool's own
guidance, this was not worked around. The exact override content that was prepared and is ready to
apply:

```yaml
services:
  content_worker:
    image: ai-newsroom-content_worker:data-semantic-v2-instagram-6e91f6c
    build: !reset null
    environment:
      UNIFIED_EDITORIAL_PIPELINE_ENABLED: "true"
  telegram_bot:
    image: ai-newsroom-telegram_bot:instagram-editorial-delivery-4d3c2f0
    build: !reset null
```

Applying it would require, on the host (`/opt/ai-newsroom`): writing the file above, then
`docker compose up -d --no-deps content_worker` (or the harness's own preferred mechanism, with
whatever Bash permission rule unblocks `[Production Deploy]`-classified actions).

## I. Live DATA candidates

Not reached - no deployment occurred.

## J. Semantic validation

Not reached live - fully validated in development (§E) and via the 224-test DATA blast-radius
sweep on this exact merged commit.

## K. Geometry validation

Not reached live. The disclosed Maxus hero-geometry limitation (real "тыс юаней" unit failing
closed at minimum font size - see the parser-v2 development report) remains unfixed by design, per
this phase's own explicit instruction not to touch DATA typography.

## L. Known Maxus safe-HOLD limitation

Unchanged, disclosed, not a blocker - see
`artifacts/telegram_data_semantic_parser_v2_1/MAXUS_HERO_GEOMETRY_GAP_evidence.json` (carried
through the merge unchanged).

## M. Unified non-regression

Confirmed via the regression accounting (§D): Story Memory (294 tests including
`test_story_memory.py`/`test_story_memory_v2.py`/`test_story_duplicate_guard.py`), arXiv
(`test_arxiv_source.py`/`test_arxiv_story_clustering_repair.py`), Vision Gate
(`test_unified_pipeline_vision_gate*.py`) - all green, zero diff introduced by this merge (neither
lineage touches any of these files, confirmed by the diff audit in §C).

## N. Telegram health

Not applicable - no restart occurred. Current production Telegram flow (already running the
Instagram-Telegram editorial-delivery release) is unaffected - not restarted, not touched.

## O. DB / Redis

DB: `alembic_version=b7d1f92a4e6c` both before and after this phase (no migration exists in the
DATA lineage; the merged branch's own migration chain has exactly one head, `b7d1f92a4e6c`,
identical to what's already applied in production - confirmed via `alembic heads`/`alembic
history` on the merged branch, and via a direct `psql` query against the live DB). **Zero
migration action taken or needed.**

Redis: not queried again this phase (unchanged from §A's first check - `role:master`, no public
port mapping); not touched.

## P. Rollback readiness

Not exercised - no deployment occurred, so no rollback was needed. The previous image
(`instagram-editorial-delivery-4d3c2f0`) remains the one actually running, untouched.

## Q. Final verdict

Blocked strictly on harness permission for the production-config write, not on any code, test, or
regression failure - every gate through build passed cleanly.

---

## Final metrics

```
PRODUCTION_BASE=instagram-editorial-delivery-4d3c2f0 (discovered mid-phase; not unified-vision-77a105f as originally expected - see §A)
RELEASE_HEAD=f5b5225 (merged into integration commit 6e91f6c per Founder direction)
ACTIVE_IMAGE=ai-newsroom-content_worker:instagram-editorial-delivery-4d3c2f0 (unchanged - deploy not performed)
PREVIOUS_IMAGE=ai-newsroom-content_worker:instagram-editorial-delivery-4d3c2f0 (same - no cutover occurred)

REGRESSION_TEST_FILES_TOTAL=493
REGRESSION_TEST_FILES_EXECUTED=693 tests across 3 targeted blast-radius sweeps (DATA/Instagram/Story-arXiv-VisionGate) on the merged commit; full 489-file sweep already completed for the DATA lineage alone in the prior development phase
REGRESSION_TESTS_COMPLETE=true (for the merge's actual blast radius; whole-repository re-run not repeated a third time - see §D for justification)
NEW_FAILURES=0

NASA_REPLAY_PASS=true
ASML_REPLAY_PASS=true
MAXUS_STRUCTURED_REPLAY_PASS=true
MAXUS_GEOMETRY_SAFE_HOLD_PASS=true

PERCENT_UNIT_CAN_CONTAIN_TRAILING_PROSE=false
COMPARATOR_CAN_ENTER_UNIT=false
SENTENCE_CAN_BECOME_SUBJECT=false
SENTENCE_CAN_BECOME_METRIC_LABEL=false
UNKNOWN_UNIT_CAN_BECOME_ARBITRARY_TEXT=false

SEMANTICALLY_UNSAFE_DATA_CAN_RENDER=false
SEMANTICALLY_UNSAFE_DATA_CAN_SEND=false
GEOMETRIC_OVERFLOW_CAN_SEND=false

CONTENT_WORKER_HEALTH=healthy (unchanged, still running previous image)
CONTENT_WORKER_RESTARTS=0

DATA_CANARY_DURATION=not_started
DATA_CANDIDATES_OBSERVED=0
DATA_LIVE_CANARY_VALIDATED=false

DATA_UNIT_TRAILING_PROSE=0
DATA_COMPARATOR_IN_UNIT=0
DATA_SENTENCE_SUBJECT=0
DATA_SENTENCE_LABEL=0
DATA_SEMANTIC_UNSAFE_SEND=0
DATA_GEOMETRIC_OVERFLOW_SEND=0

WRONG_SUBJECT_SELECTED=0
TEXT_ONLY_VISUAL_DEMOTIONS=0
LEGACY_FALLTHROUGHS=0
AMBIGUOUS_AUTO_RESENDS=0
DUPLICATE_SENDS=0

STORY_MEMORY_CHANGED=false
ARXIV_CHANGED=false
VISION_GATE_CHANGED=false
TRANSPORT_CHANGED=false
INSTAGRAM_CHANGED=false

DB_HEALTH=healthy
REDIS_ROLE=master
PUBLIC_REDIS_6379=false

ROLLBACK_REQUIRED=false (nothing was deployed)
```

## Final verdict

**TELEGRAM_DATA_SEMANTIC_PARSER_V2_PRODUCTION_BLOCKED**

Blocked on execution-harness permission for the production-config write
(`docker-compose.override.yml` update + `content_worker` restart), reason `[Production Deploy]`,
non-transient on retry. Everything up to and including the build is complete, verified, and ready:
merged integration commit `6e91f6c` (branch
`feature/telegram-data-semantic-parser-v2-instagram-integration-1`, pushed), image
`ai-newsroom-content_worker:data-semantic-v2-instagram-6e91f6c` built and hash-verified on the
production host, zero new migrations needed, 693/693 regression tests passing, ruff/mypy clean.
Awaiting either a Bash permission rule for this class of action, or the Founder/operator applying
the prepared override (§H) directly.
