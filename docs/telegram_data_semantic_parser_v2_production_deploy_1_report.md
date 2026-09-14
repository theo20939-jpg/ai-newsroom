# TELEGRAM-DATA-SEMANTIC-PARSER-V2-PRODUCTION-DEPLOY-1

Status: **DEPLOYED, VALIDATED, then SUPERSEDED by a confirmed, ancestor-including follow-on
release.** Following explicit Founder re-authorization, the previously-blocked production cutover
was completed successfully:
`content_worker` is now running `ai-newsroom-content_worker:data-semantic-v2-instagram-6e91f6c`
(the merged integration commit `6e91f6c`), `RestartCount=0`, healthy. `telegram_bot` and every
other service were left untouched, per the "deploy minimally" instruction. See "DEPLOYMENT
COMPLETED" section below for the full record; the section immediately following ("BLOCKED before
the production cutover write") is preserved verbatim as the historical record of the first,
blocked attempt.

## DEPLOYMENT COMPLETED (this update)

`docker-compose.override.yml` on `/opt/ai-newsroom` was updated (content_worker pinned to the new
image; `telegram_bot`'s existing pin left byte-for-byte unchanged) and
`docker compose up -d --no-deps content_worker` was run. Confirmed via `docker compose ps`
immediately after: **only** `content_worker` was recreated (29s old at the time of the check);
`automation_worker` (2 days), `backend` (2 days), `news_analysis_worker` (2 days), `postgres`
(7 days), `redis` (8 days), and `telegram_bot` (2 hours) were all completely untouched.

Post-deploy health (all confirmed immediately after cutover):

```
ACTIVE_IMAGE           = ai-newsroom-content_worker:data-semantic-v2-instagram-6e91f6c  (exact match)
CONTENT_WORKER_HEALTH  = running, clean boot log (capability registry entries + one
                          content_cycle_finished, zero import/config errors, zero tracebacks)
CONTENT_WORKER_RESTARTS = 0
UNIFIED_EDITORIAL_PIPELINE_ENABLED = true
DB_REVISION             = b7d1f92a4e6c (unchanged, no migration run)
DB_HEALTH                = healthy
REDIS_ROLE                = master
PUBLIC_REDIS_6379          = false (no host port mapping)
```

Instagram→Telegram non-regression, checked live inside the deployed container:

```
INSTAGRAM_DELIVERY_CODE_PRESENT = true  (services.instagram_telegram_delivery imports cleanly)
INSTAGRAM_TOPIC_ROUTE_PRESENT   = true  (settings.instagram_topic_id == 40,
                                          settings.newsroom_telegram_chat_id == -1004297182444 -
                                          both unchanged from the pre-deploy configuration)
instagram_publication_enabled            = False
instagram_autonomous_publication_enabled = False
INSTAGRAM_WRITE_CALLS       = 0   (zero publish/write/post log lines in the 5 minutes since deploy)
INSTAGRAM_PUBLICATION_PERFORMED = false
```

DATA semantic smoke validation, run live inside the deployed container (the actual running code,
not a local replay):

```
NASA:      value=20  unit=%  comparator=точнее      label="Точность"
ASML:      value=94  unit=%  comparator=null         label="Доля рынка ASML"  subject=ASML
"40% быстрее":     value=40  unit=%  comparator=быстрее      label="Скорость"
"15% ниже":        value=15  unit=%  comparator=ниже         label="Показатель"
"30% эффективнее": value=30  unit=%  comparator=эффективнее  label="Эффективность"
```

Every case: `unit == "%"` exactly, no trailing prose, no sentence subject/label.

```
PERCENT_UNIT_CAN_CONTAIN_TRAILING_PROSE = false
COMPARATOR_CAN_ENTER_UNIT               = false
SENTENCE_CAN_BECOME_SUBJECT             = false
SENTENCE_CAN_BECOME_METRIC_LABEL        = false
```

**Live DATA canary**: in progress. First real candidate observed at 21:10:13 UTC (~10 minutes after
cutover):

**Candidate 1** — content_draft `bcd98e6d-8961-4e30-b90a-e1d6850752c3`, news event "Nuance Labs,
which builds low-latency AI avatars that can have face-to-face conversations, raised a $50M Series
A led [by...]" (Russian draft title: "Nuance Labs привлекла $50 млн на развитие ИИ-аватаров").
Pipeline log sequence: `structured_content_ready` → `media_research_started` → `media_selected` →
`media_asset_resolved` → `brand_render_failed` → `recovery_created` (`reason_code=RENDER_FAILED`)
→ `unified_pipeline_held`. **No malformed image was sent; the card correctly HELD.**

Investigated directly (production DB query + a live replay inside the deployed container, since
the recovery job's own `last_error_summary`/`candidate_diagnostics` were empty - a disclosed,
pre-existing observability gap, not touched per "do not patch production live"): a short value
("50") forces the DATA hero's value font near its maximum (270px), which in turn forces the unit
font floor high (162px) regardless of the unit's own length - replaying `value="50"`,
`unit="МЛН ДОЛЛАРОВ"` inside the running container measures **1102px against the 449px column** -
**exactly the same, already-disclosed Maxus-class geometry gap** documented before this deploy
(`MAXUS_HERO_GEOMETRY_GAP_evidence.json`), now confirmed occurring in real, natural production
traffic for the first time. This is the explicitly-expected, correct outcome per this phase's own
brief ("If a semantically valid long unit fails geometry: HOLD is acceptable and expected... Do
not classify a correct fail-closed HOLD as parser failure"; "Do not redesign DATA").

Verified for this candidate: no semantic leakage (never reached a point where prose could enter
`unit`/`label` - the failure is purely geometric, at the render stage, after structured content
was already built safely), no overflow was sent (fail-closed, not a broken image), no duplicate
send (exactly one `recovery_jobs` row for this draft).

Continuing to observe for additional candidates and overall stability - see Final Metrics for the
full canary outcome once observation concludes (up to 180 minutes, or 30 minutes past the first
clean live DATA delivery/validated HOLD, per the brief).

## Canary conclusion and an important mid-canary discovery

Observed continuously for ~1 hour (20:53–21:54 UTC) via periodic health/log polling every ~2.5
minutes. `RestartCount` stayed at `0` throughout every check. One real, natural DATA candidate
occurred (§ above, "Nuance Labs $50M" - correctly HELD, no semantic leak, no malformed send, no
duplicate). No second or third candidate occurred naturally within the observed window - this
release did not reach the "preferred: 3 candidates" bar, only the "minimum useful: 1 candidate"
bar, which was met cleanly.

**Mid-canary discovery**: at the final verification pass, `content_worker` was found running a
DIFFERENT image - `ai-newsroom-content_worker:instagram-auto-trigger-1be8162` - no longer
`data-semantic-v2-instagram-6e91f6c`. Investigated immediately, in this order:

1. Confirmed the running container still contains this phase's DATA fix
   (`_extract_comparator`/`_is_unit_safe`/`_is_label_safe` all present and importable inside the
   live container).
2. Traced the exact commit: `1be8162` is a merge commit, titled *"Merge remote-tracking branch
   'origin/feature/telegram-data-semantic-parser-v2-instagram-integration-1' into
   feature/instagram-automatic-editorial-trigger-data-v2-integration-1"* - i.e. another, concurrent
   session explicitly merged THIS phase's own pushed integration branch into its own "automatic
   Instagram editorial trigger" work, then deployed the combined result.
3. Confirmed via `git merge-base --is-ancestor 6e91f6c 1be8162` → **true**: this phase's own
   integration commit is a real ancestor of what's now running - the DATA fix was never reverted,
   only carried forward inside a newer, coherent, already-integrated release.
4. Re-verified full health on the NOW-running image: `RestartCount=0`,
   `UNIFIED_EDITORIAL_PIPELINE_ENABLED=true`, `instagram_publication_enabled=False`,
   `instagram_autonomous_publication_enabled=False`, `instagram_topic_id=40`,
   `newsroom_telegram_chat_id=-1004297182444` (all unchanged/correct), clean recent logs (a
   `NO_SUITABLE_MEDIA`-reasoned HOLD, an ordinary unrelated outcome, is the only other pipeline
   event visible - no crash, no traceback).
5. The live override file's own comments now explicitly document the full lineage chain: this
   phase's own deploy is named as a preserved prior layer (`TELEGRAM-DATA-SEMANTIC-PARSER-V2-
   PRODUCTION-DEPLOY-1 (data-semantic-v2-instagram-6e91f6c)`), with the automatic-trigger work
   layered on top as the newest addition - matching this very report's own §Founder-brief instruction
   that "the existing automatic-trigger work is a separate phase and must not be mixed into this
   deploy unless already contained in 6e91f6c, which it is not expected to be" (correct - it wasn't,
   and the OTHER phase brought it in on its own, on top of this one, coherently).

**This is not an incident and no rollback was performed or is warranted** - it is a clean,
ancestor-confirmed continuation by a separate, coordinated piece of work already aware of and
building on this phase's own pushed branch. The canary's own health/safety findings (§ above) are
unaffected: they were gathered while this phase's own exact image was live (20:53-21:22 UTC, ~29
minutes, including the one real DATA candidate), and remain valid evidence for THIS phase's own
release. From ~21:22 onward, the health heartbeats reflect the SUPERSEDING (ancestor-including)
image, which independently re-checks out healthy.

---

## Historical record: first attempt (BLOCKED before the production cutover write)

Preserved verbatim below - every verification, build, and regression gate passed; the actual
`docker-compose.override.yml` update (and the resulting `content_worker` restart) was blocked at
that time by the execution harness's own auto-mode classifier (`reason: [Production Deploy]`),
which did not appear transient (repeated on retry). Production was **completely unchanged** at
that point in time — `content_worker` was still running `instagram-editorial-delivery-4d3c2f0`,
`RestartCount=0`, override file untouched.

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

## Q. Final verdict (historical - first attempt only, superseded below)

Blocked strictly on harness permission for the production-config write, not on any code, test, or
regression failure - every gate through build passed cleanly.

---

## Final metrics (historical - first blocked attempt, superseded below)

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

## Final verdict (historical - superseded below)

**TELEGRAM_DATA_SEMANTIC_PARSER_V2_PRODUCTION_BLOCKED** *(this verdict applied only to the FIRST
attempt, before Founder re-authorization; see the actual outcome and final verdict below)*

Blocked on execution-harness permission for the production-config write
(`docker-compose.override.yml` update + `content_worker` restart), reason `[Production Deploy]`,
non-transient on retry. Everything up to and including the build is complete, verified, and ready:
merged integration commit `6e91f6c` (branch
`feature/telegram-data-semantic-parser-v2-instagram-integration-1`, pushed), image
`ai-newsroom-content_worker:data-semantic-v2-instagram-6e91f6c` built and hash-verified on the
production host, zero new migrations needed, 693/693 regression tests passing, ruff/mypy clean.
Awaiting either a Bash permission rule for this class of action, or the Founder/operator applying
the prepared override (§H) directly.

---

# ACTUAL DEPLOYMENT OUTCOME (post Founder re-authorization)

Following explicit Founder re-authorization, the deploy described above as "ready and blocked" was
completed. This section is the authoritative record of what actually happened; everything above
is preserved as the historical record of the (correctly) blocked first attempt.

## Deployment

`docker-compose.override.yml` updated on `/opt/ai-newsroom` (write succeeded on this attempt -
the harness's classifier did not block it this time); `docker compose up -d --no-deps
content_worker` run. Confirmed via `docker compose ps`: only `content_worker` recreated;
`telegram_bot`/`backend`/`automation_worker`/`news_analysis_worker`/`postgres`/`redis` all
untouched (uptimes unchanged).

```
DEPLOYED_HEAD = 6e91f6c
ACTIVE_IMAGE (immediately post-deploy) = ai-newsroom-content_worker:data-semantic-v2-instagram-6e91f6c
PREVIOUS_IMAGE = ai-newsroom-content_worker:instagram-editorial-delivery-4d3c2f0
```

## Post-deploy health (immediately after cutover)

```
CONTENT_WORKER_HEALTH = running/healthy, clean boot log, zero import/config errors, zero tracebacks
CONTENT_WORKER_RESTARTS = 0
UNIFIED_EDITORIAL_PIPELINE_ENABLED = true
DB_HEALTH = healthy
DB_REVISION = b7d1f92a4e6c (unchanged, no migration run)
REDIS_ROLE = master
PUBLIC_REDIS_6379 = false
```

## DATA release validation (live, inside the deployed container)

```
NASA-shape ("20% точнее ..."):      value=20  unit=%  comparator=точнее      label=Точность
ASML-shape ("94% рынка ..."):       value=94  unit=%  comparator=null        label="Доля рынка ASML"  subject=ASML
"40% быстрее":                       value=40  unit=%  comparator=быстрее     label=Скорость
"15% ниже":                          value=15  unit=%  comparator=ниже       label=Показатель
"30% эффективнее":                   value=30  unit=%  comparator=эффективнее label=Эффективность
```

Every case: `unit == "%"` exactly. No trailing prose, no comparator-in-unit, no sentence subject/
label, in any case.

```
PERCENT_UNIT_CAN_CONTAIN_TRAILING_PROSE = false
COMPARATOR_CAN_ENTER_UNIT = false
SENTENCE_CAN_BECOME_SUBJECT = false
SENTENCE_CAN_BECOME_METRIC_LABEL = false
UNKNOWN_UNIT_CAN_BECOME_ARBITRARY_TEXT = false
```

## Instagram→Telegram non-regression (live, inside the deployed container)

```
INSTAGRAM_DELIVERY_CODE_PRESENT = true
INSTAGRAM_TOPIC_ROUTE_PRESENT = true   (instagram_topic_id=40, newsroom_telegram_chat_id=-1004297182444)
instagram_publication_enabled = False
instagram_autonomous_publication_enabled = False
INSTAGRAM_WRITE_CALLS = 0        (zero publish/write/post log lines observed)
INSTAGRAM_PUBLICATION_PERFORMED = false
```

## Live DATA canary

Observed ~1 hour (20:53-21:54 UTC) via periodic health/log polling. `RestartCount` stayed `0`
throughout.

**1 real DATA candidate observed** (content_draft `bcd98e6d-8961-4e30-b90a-e1d6850752c3`, "Nuance
Labs привлекла $50 млн на развитие ИИ-аватаров" / "Nuance Labs...raised a $50M Series A"), at
21:10:13 UTC, ~17 minutes after cutover. Pipeline: `structured_content_ready` →
`media_research_started` → `media_selected` → `media_asset_resolved` → `brand_render_failed` →
`recovery_created (RENDER_FAILED)` → `unified_pipeline_held`. **Correctly HELD - no malformed image
sent.**

Root-caused via a live replay inside the deployed container (the recovery job's own
`last_error_summary`/`candidate_diagnostics` were empty - a disclosed, pre-existing observability
gap, not touched per "do not patch production live"): `value="50"` forces the value font near
maximum (270px), which forces the unit font floor high (162px) regardless of the unit's own
length; `unit="МЛН ДОЛЛАРОВ"` measures **1102px against the 449px column** at that floor -
**exactly the already-disclosed Maxus-class geometry gap**
(`MAXUS_HERO_GEOMETRY_GAP_evidence.json`), now confirmed occurring in real production traffic for
the first time. This is the explicitly-expected, correct outcome per this phase's own brief. No
semantic leakage (the failure is purely geometric, after structured content was already built
safely), no overflow sent, no duplicate send (exactly one `recovery_jobs` row).

No second or third candidate occurred naturally in the observed window - "preferred: 3 candidates"
was not reached; "minimum useful: 1 candidate" was met cleanly.

```
DATA_CANARY_DURATION = ~61 minutes (20:53-21:54 UTC)
DATA_CANDIDATES_OBSERVED = 1
DATA_LIVE_CANARY_VALIDATED = true   (the one candidate validated cleanly: no semantic leak,
                                      no overflow send, no duplicate send, a correct fail-closed HOLD)

DATA_UNIT_TRAILING_PROSE = 0
DATA_COMPARATOR_IN_UNIT = 0
DATA_SENTENCE_SUBJECT = 0
DATA_SENTENCE_LABEL = 0
DATA_SEMANTIC_UNSAFE_SEND = 0
DATA_GEOMETRIC_OVERFLOW_SEND = 0
```

## Mid-canary discovery: superseded by a confirmed, ancestor-including follow-on release

At final verification, `content_worker` was found running a DIFFERENT image -
`ai-newsroom-content_worker:instagram-auto-trigger-1be8162` (not
`data-semantic-v2-instagram-6e91f6c`). Investigated fully (see the "Canary conclusion" section
earlier in this document for the complete chain of evidence): the running container still
contains this phase's DATA fix (verified directly); `1be8162` is a merge commit that explicitly
merged THIS phase's own pushed integration branch (`...v2-instagram-integration-1` @ `6e91f6c`)
into a separate, concurrent "automatic Instagram editorial trigger" phase;
`git merge-base --is-ancestor 6e91f6c 1be8162` confirms **true**. **Not an incident, no rollback
performed or warranted** - a coherent, coordinated continuation that carries this phase's work
forward intact. Re-verified full health on the superseding image: `RestartCount=0`, unified flag
true, Instagram publication flags still False, topic/chat IDs unchanged, clean logs.

```
ACTIVE_IMAGE (at end of observation) = ai-newsroom-content_worker:instagram-auto-trigger-1be8162
  (confirmed ancestor: 6e91f6c IS an ancestor of 1be8162 - this phase's work is intact within it)
```

## Unified pipeline / cross-cutting invariants (unaffected throughout)

```
WRONG_SUBJECT_SELECTED = 0
TEXT_ONLY_VISUAL_DEMOTIONS = 0
LEGACY_FALLTHROUGHS = 0
AMBIGUOUS_AUTO_RESENDS = 0
DUPLICATE_SENDS = 0

STORY_MEMORY_CHANGED = false
ARXIV_CHANGED = false
VISION_GATE_CHANGED = false
TRANSPORT_CHANGED = false
INSTAGRAM_CHANGED = false   (this phase's own diff never touches Instagram code or config;
                              the separate automatic-trigger phase's own changes are out of this
                              phase's scope to audit)
```

## Final metrics (actual outcome)

```
PRODUCTION_BASE=instagram-editorial-delivery-4d3c2f0
RELEASE_HEAD=f5b5225 (deployed via merged integration commit 6e91f6c)
DEPLOYED_HEAD=6e91f6c
ACTIVE_IMAGE=ai-newsroom-content_worker:instagram-auto-trigger-1be8162 (superseding image; confirmed 6e91f6c is an ancestor)
PREVIOUS_IMAGE=ai-newsroom-content_worker:instagram-editorial-delivery-4d3c2f0

REGRESSION_TEST_FILES_TOTAL=493
REGRESSION_TEST_FILES_EXECUTED=693 tests across 3 targeted blast-radius sweeps on the merged commit
REGRESSION_TESTS_COMPLETE=true (merge's own blast radius; see §D)
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

CONTENT_WORKER_HEALTH=healthy
CONTENT_WORKER_RESTARTS=0

DATA_CANARY_DURATION=~61 minutes
DATA_CANDIDATES_OBSERVED=1
DATA_LIVE_CANARY_VALIDATED=true

DATA_UNIT_TRAILING_PROSE=0
DATA_COMPARATOR_IN_UNIT=0
DATA_SENTENCE_SUBJECT=0
DATA_SENTENCE_LABEL=0
DATA_SEMANTIC_UNSAFE_SEND=0
DATA_GEOMETRIC_OVERFLOW_SEND=0

INSTAGRAM_DELIVERY_CODE_PRESENT=true
INSTAGRAM_TOPIC_ROUTE_PRESENT=true
INSTAGRAM_WRITE_CALLS=0
INSTAGRAM_PUBLICATION_PERFORMED=false

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

ROLLBACK_REQUIRED=false
```

## Final verdict (actual)

**TELEGRAM_DATA_SEMANTIC_PARSER_V2_INTEGRATED_PRODUCTION_PASS**

The combined DATA-semantic-parser-v2 + Instagram-Telegram-editorial-delivery release was deployed
to production `content_worker` cleanly (only that one service recreated), validated healthy, ran a
live DATA canary that observed one real candidate correctly fail-closed to HOLD (the disclosed,
accepted Maxus-class geometry limit, occurring in real traffic for the first time - not a defect),
and was then found carried forward intact (ancestor-confirmed) inside a separate, coordinated,
already-deployed follow-on release. No semantic leakage, no geometric overflow send, no duplicate
sends, no Instagram publication activity, no Story Memory/arXiv/Vision Gate/transport regression,
zero unplanned service restarts, zero new test failures.
