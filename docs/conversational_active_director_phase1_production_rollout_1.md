# CONVERSATIONAL-ACTIVE-DIRECTOR-PHASE1 — Production Rollout 1

Founder-authorized, scoped production deploy of Phase 1 (Conversational Active Director + Product
Truth) only, isolated from Phases 2-6 of the Instagram Content Strategy V2 implementation.

## A. Release base

`347fdb1` — `feat(director): Phase 1 - conversational Director + Product Truth`, the first commit
on `feature/instagram-content-strategy-v2-implementation-1` after its own base (`d284d03`). Chosen
because it is the exact commit boundary where Phase 1's 15 files end and Phase 2 begins — no
cherry-pick was needed to isolate it from later phases.

## B. Correction source

`0900da2` — `fix(director): Phase 1 correction - bare да/нет answers a QUESTION, never rejected`
(Founder pre-deploy review finding). Built on top of the full V2 branch tip (`93f40d3`), so its own
tree includes Phases 2-6 — it was never deployable directly. Its diff touches exactly 2 files
(`bot/handlers/business_context.py`, one new test file), both Phase-1-owned.

## C. Final clean release SHA

New isolated worktree (`C:/Users/Theodor/ai-newsroom-phase1-release-1`), branch
`release/conversational-active-director-phase1-1`, created directly from `347fdb1`.
`git cherry-pick 0900da2` applied cleanly, no conflicts, no manual resolution needed.

**`PHASE1_RELEASE_HEAD=8392020`**

`git diff --stat 347fdb1..8392020` = exactly the same 2 files, 463 insertions / 28 deletions as
`0900da2`'s own diff — the cherry-pick is a semantically identical, clean transplant.

## D. Isolation proof

`git diff --name-status d284d03..8392020`: 16 files total (Phase 1's 15 + the correction's 1 new
test file, `bot/handlers/business_context.py` counted once). `grep -rlE` across the whole release
tree for every Phase 2-6 marker (`NEWS_DIGEST`, `trend_fingerprint`, `trend_cluster`,
`trend_observation`, `TrendSourceNotConfigured`, `instagram_news_digest`,
`instagram_reel_script_readiness`, `YouTubeTrendSourceAdapter`, `BlueskyTrendSourceAdapter`,
`digest_schedule_state`): **zero matches**. `alembic heads` on the release branch: single head
`a3f7c1d9e042` — Migration 1 present, Migrations 2 and 3 absent.

**`PHASE1_RELEASE_ISOLATED=true`**

## E. Tests

Release-branch test run (real Postgres, local dev container):

| Suite | Result |
|---|---|
| Phase 1 fixtures + correction (9 required conversational scenarios) | 51/51 pass |
| BusinessContextProposal + roles + command registry + snapshot | 27/27 pass |
| Telegram routing regression | 99/99 pass |

`ruff check` on every changed file: clean. `mypy` on the 3 core changed/new source files
(`bot/handlers/business_context.py`, `services/product_fact_state.py`,
`services/business_context_proposal_service.py`): zero findings in those files — the only mypy
output is the same pre-existing, unrelated, transitively-imported findings already disclosed in
the prior Founder audit (`services/design_reference_registry.py` missing PyYAML stubs,
`instagram_editorial_regeneration.py`, etc.), none introduced by this release.

**`NEW_FAILURES=0`**

## F. Pre-deploy runtime snapshot

Re-verified read-only, immediately before touching production, via
`~/.ssh/ninja_temp` (established read-only production-inspection pattern):

```
PROD_TELEGRAM_SHA=4d3c2f0 (unchanged since preflight)
PROD_DB_REVISION=b7d1f92a4e6c (unchanged since preflight)
RestartCount=0
```

Matched preflight exactly — proceeded.

**Rollback data captured:**
```
ROLLBACK_TELEGRAM_IMAGE=ai-newsroom-telegram_bot:instagram-editorial-delivery-4d3c2f0
ROLLBACK_TELEGRAM_IMAGE_ID=sha256:df7fd108d959a0ed8e75682c35799086df7c235d0c299ba202179445e1811861
```

## G. Image build

Built on the production host, from a fresh isolated git worktree
(`/opt/ai-newsroom-release-conversational-director-phase1-1`, fetched from the pushed release
branch, detached at `8392020`) — never from `/opt/ai-newsroom`'s own dirty, unrelated-branch
checkout.

```
PHASE1_IMAGE=ai-newsroom-telegram_bot:conversational-director-phase1-8392020
PHASE1_IMAGE_ID=sha256:92a618c60ae09f658d5bbe6269cc5a217e0d2eb4140d0570cc6d75f7511f2e0f
```

Content-verified: `sha1` of `bot/handlers/business_context.py` read from inside a `docker run` of
the built image (25877 bytes, `10884235e10872cfd385545dda1b5142b6facd34`) is byte-identical to the
same file read directly from the local release worktree at `8392020`.

## H. Migration

Applied via a one-off container from the new image, attached to the `ai-newsroom_default` network,
using production's real `.env` (read-only, via `--env-file`, never modified) plus the same
`POSTGRES_HOST`/`REDIS_HOST` overrides the compose service itself uses:

```
python -m alembic upgrade a3f7c1d9e042
```

Output: `Running upgrade b7d1f92a4e6c -> a3f7c1d9e042, add director conversational extension
(Migration 1)`. Verified `alembic current` == `a3f7c1d9e042` afterward. `head` was never targeted.

Column-level verification (`\d business_context_proposals`, `\d products` via `psql` inside the
`postgres` container):

| Column | Type | Nullable |
|---|---|---|
| `business_context_proposals.question_text` | text | yes |
| `business_context_proposals.origin` | varchar(30) | yes |
| `business_context_proposals.origin_context` | json | yes |
| `products.undecided_facts` | json | yes |

`ix_business_context_proposals_origin` index present. No other table/column touched.

**`MIGRATION_1_APPLIED=true`**, **`PROD_DB_REVISION_AFTER=a3f7c1d9e042`**

## I. telegram_bot rollout

Production's own established scoped-deploy mechanism (`docker-compose.override.yml`, which already
pins each service to an immutable pre-built image with `build: !reset null`) was used, changing
**exactly one line** — `telegram_bot.image` — nothing else in that file. Original backed up first
to `docker-compose.override.yml.bak-before-phase1-8392020` on the host.

```
docker compose up -d --no-deps telegram_bot
```

`--no-deps` scopes the recreate to that single service; every other container's `Up <duration>`
uptime confirms none of them restarted:

| Container | Status after deploy |
|---|---|
| `ai_newsroom_telegram_bot` | **Recreated**, Up 45s → running |
| `ai_newsroom_content_worker` | Up 15h (untouched) |
| `ai_newsroom_backend` | Up 2 days (untouched) |
| `ai_newsroom_automation_worker` | Up 2 days (untouched) |
| `ai_newsroom_news_analysis_worker` | Up 2 days (untouched) |
| `ai_newsroom_postgres` | Up 8 days, healthy (untouched) |
| `ai_newsroom_redis` | Up 8 days, healthy (untouched) |

**`OTHER_CONTAINERS_RESTARTED=false`**

## J. Runtime smoke

- Startup log: `Bot started` / `Run polling for bot @nnj_newsroombot` — no traceback.
- `RestartCount=0`, re-checked after a 15s stabilization window — still 0, still `running`.
- Structural check inside the container: 9 message handlers registered on
  `bot.handlers.business_context.router`; the plain-text handler (`handle_plain_text`) is last;
  `handle_product` (a slash command) is present — existing commands are not shadowed.
- End-to-end ORM read (SELECT only, zero writes) against the real production DB through the new
  image and migrated schema: `BusinessContextProposal.origin`/`.question_text` and
  `Product.undecided_facts` all read without error (0 existing rows — this feature has no
  production data yet, expected).

No Product data was fabricated or written during smoke.

## K. Rollback image

If `telegram_bot` becomes unhealthy: restore
`docker-compose.override.yml.bak-before-phase1-8392020` over `docker-compose.override.yml`
(reverts the one changed line back to `ai-newsroom-telegram_bot:instagram-editorial-delivery-4d3c2f0`,
image ID `sha256:df7fd108d959a0ed8e75682c35799086df7c235d0c299ba202179445e1811861`), then
`docker compose up -d --no-deps telegram_bot` again. Migration `a3f7c1d9e042` is purely additive
and stays in place — the old image never reads the new nullable columns, so no downgrade is needed
for an application-level rollback alone. `alembic downgrade b7d1f92a4e6c` is reserved for a
separate, explicit decision, only after the old bot image is confirmed healthy again.

## L. Founder canary instructions

**Nothing was simulated.** Please send the real conversation yourself, in the internal NINJA
Newsroom chat (`chat_id=-1004297182444`), **General topic** (no sub-topic — `business_context_topic_id`
is unset, so the plain "General" topic is the authorized location):

1. `"В NINJA AI добавляем Production Mode."`
2. Answer whatever clarification the Director raises naturally in your own words, e.g.
   `"Пока в разработке, экономику ещё не решили."`
3. Inspect the proposal preview the bot sends back.
4. Confirm intentionally (e.g. reply `"подтверждаю"`, or use the inline button).

Afterward, worth checking: the resulting `Product` state (planned feature recorded correctly),
`production_mode.billing` = `UNDECIDED` if you gave that answer, a `ProductContextVersion` row
exists with your real message as `raw_instruction`, `confirmed_at`/`confirmed_by` are populated,
and no duplicate question was raised for the same fact.

## M. Production invariants

```
TREND_AUTONOMOUS_CONTENT_GENERATION=false
PUBLIC_INSTAGRAM_PUBLICATION=false
INSTAGRAM_WRITE_CALLS=0
```

Phases 2-6 remain entirely absent from this release (see §D). `content_worker`,
`automation_worker`, `news_analysis_worker`, `backend`, `postgres`, `redis` were never touched.
