# Phase 18.8 M0 — Local Environment Audit

Status: complete, read-only investigation. **This environment is not a sandbox** — it is a real,
already-operating local deployment with live paid OpenAI usage enabled (§5). Nothing in this
audit changed any configuration or container state.

## 1. Deployment target — clarification

This project has no remote VPS. What already exists, running on this Windows machine, is the
project's own `docker-compose.yml` stack (`services`: `backend`, `automation_worker`,
`news_analysis_worker`, `content_worker`, `telegram_bot`, `postgres`, `redis`). Phase 18.8 treats
this stack as "the server" per this phase's own explicit scope (not VPS deployment — that is
`docs/phase18_8_vps_deployment_checklist.md`'s own subject, a future-phase plan only, §M4).

## 2. Docker / Compose versions

- Docker: `29.6.1` (build `8900f1d`)
- Docker Compose: `v5.3.0`

## 3. Container status at audit time

| Container | Image | Status | Notes |
|---|---|---|---|
| `ai_newsroom_postgres` | `postgres:16-alpine` | **Up, healthy** | 5h uptime |
| `ai_newsroom_redis` | `redis:7-alpine` | **Up, healthy** | 5h uptime |
| `ai_newsroom_backend` | `ai-newsroom-backend` | **Up** | 5h uptime; `GET /` → `{"status":"Application running"}` |
| `ai_newsroom_automation_worker` | `ai-newsroom-automation_worker` | **Exited (1)** | stopped 2026-08-02 21:09 |
| `ai_newsroom_news_analysis_worker` | `ai-newsroom-news_analysis_worker` | **Exited (1)** | stopped 2026-08-02 21:09 |
| `ai_newsroom_content_worker` | `ai-newsroom-content_worker` | **Exited (1)** | stopped 2026-08-02 21:07/21:09 |
| `ai_newsroom_telegram_bot` | `ai-newsroom-telegram_bot` | **Exited (0)** | stopped 2026-08-02 21:09 |

## 4. Root cause of the four stopped containers

**Not an application crash.** All four containers' own logs show a normal SIGTERM-triggered
graceful shutdown at the same timestamp (2026-08-02 21:09:01, `telegram_bot`'s log shows the
literal `Received SIGTERM signal` line; the three workers each log `..._shutdown_complete`
immediately beforehand), and every workflow/task in flight at that moment had already completed
successfully — no unhandled exception, no data corruption, no partial write.

`worker/main.py`'s own docstring documents the exit-code-1-with-traceback pattern deliberately:
`asyncio.CancelledError` is intentionally left uncaught and re-raised after logging
`"automation_worker_shutdown_complete"` ("Contract §13"), so `asyncio.run()` prints a traceback and
the process exits non-zero on every SIGTERM-driven shutdown, by design — this is not a bug and was
not modified in this phase (this project's own architecture, reused exactly, per this phase's own
restriction).

**The actual reason they are still down**: all four are configured `restart: unless-stopped`
(`docker-compose.yml`), and Docker's own semantics for that policy are to *never* auto-restart a
container after an explicit stop — regardless of exit code, and regardless of a later Docker daemon
restart. `postgres`/`redis`/`backend` show only 5h uptime versus these containers' 2026-08-02
stop time, meaning Docker Desktop (or the host) itself restarted roughly 5 hours before this audit
- bringing back the three containers that were *not* in an explicitly-stopped state, but correctly
leaving the four explicitly-stopped ones down. This is standard, expected Docker behavior, not a
defect - they simply need to be started again (`docs/…M1`, §M1 below).

## 5. Env configuration — names only, real production-mode flags

Variable **names** present in `.env` (26 total; no values other than the explicitly non-secret
operational flags below were read or printed — postgres/redis/Telegram/OpenAI/GitHub
credentials were not inspected):

```
CONTENT_GENERATION_BATCH_SIZE, CONTENT_GENERATION_DRY_RUN, CONTENT_GENERATION_ENABLED,
CONTENT_GENERATION_MIN_SCORE, CONTENT_GENERATION_POLL_INTERVAL_SECONDS, EDITORIAL_CHAT_ID,
ENABLED_PROVIDERS, GITHUB_TOKEN, IMAGE_CANDIDATE_PERSISTENCE_MODE,
IMAGE_EDITORIAL_PREVIEW_ENABLED, IMAGE_INTELLIGENCE_MODE, NEWS_ANALYSIS_ENABLED,
NEWS_ANALYSIS_FRESHNESS_CUTOFF_HOURS, NEWS_COLLECTION_ENABLED, OPENAI_API_KEY, POSTGRES_DB,
POSTGRES_PASSWORD, POSTGRES_PORT, POSTGRES_USER, REDIS_DB, REDIS_HOST, REDIS_PORT,
REDIS_UNAVAILABLE_POLICY, TELEGRAM_API_HASH, TELEGRAM_API_ID, TELEGRAM_BOT_TOKEN,
TELEGRAM_SESSION_STRING
```

**Critical finding — this is a live environment, not a sandbox**:

| Flag | Value | Meaning |
|---|---|---|
| `NEWS_COLLECTION_ENABLED` | `true` | Real collectors run when `automation_worker` is up |
| `NEWS_ANALYSIS_ENABLED` | `true` | Real editorial analysis runs when `news_analysis_worker` is up |
| `CONTENT_GENERATION_ENABLED` | `true` | Real content drafting runs when `content_worker` is up |
| `CONTENT_GENERATION_DRY_RUN` | **`false`** | **Live, not dry-run** - `content_worker`/`news_analysis_worker` make real, billed OpenAI calls (confirmed directly in their own pre-shutdown logs: `POST https://api.openai.com/v1/responses` → `200 OK`, for `editorial_brief`, `article_topic_assessment`, `channel_fit_assessment`, `adaptive_length_plan`, `beginner_friendly_plan`, `completeness_assessment`) |
| `ENABLED_PROVIDERS` | `["openai"]` | Only OpenAI is wired as an LLM provider |
| `IMAGE_INTELLIGENCE_MODE` | `shadow` | Shadow-only, matches this project's own established discipline |
| `IMAGE_EDITORIAL_PREVIEW_ENABLED` | `true` | Telegram preview cards are built for human editorial review |
| `REDIS_UNAVAILABLE_POLICY` | `fail_closed` | A Redis outage blocks rather than silently degrades |

**Meme intelligence flags** (`core/config.py` defaults, not `.env`-overridden - confirmed via
`grep` against `.env`, none of the five meme-related settings appear there at all, so every one is
at its coded default): `meme_opportunity_mode="off"`, `meme_safety_gate_mode="off"`,
`meme_image_generation_mode="off"`, `meme_telegram_preview_mode="off"`,
`meme_opportunity_calibration_version="v1"`, `meme_safety_calibration_version="v1"` - all
unchanged, consistent with every prior phase's own final state.

**Consequence for M1**: restarting `news_analysis_worker`/`content_worker` resumes real,
billed OpenAI spend as an inherent effect of their own existing, already-approved business logic -
not a new capability this phase adds, but a real financial action all the same. Per explicit user
decision, only `automation_worker` (zero-LLM-cost collection) and `telegram_bot` (polling/UI, no
paid calls of its own) are restarted in this phase; `news_analysis_worker`/`content_worker` remain
stopped, pending separate confirmation (§M1).

## 6. Migration state — persistent, already-documented gap

`alembic current` → `31a8d7c95c87`; `alembic heads` → `21177d5b859e`. **Unchanged from Phase
18.5/18.6/18.7's own repeated finding**: the real database is still one revision behind head (the
Phase 18 `meme_candidates` table). Not touched in this phase - applying it is a real production
migration, one of this project's own standing stop conditions requiring separate authorization,
independent of Phase 18.8's own scope.

## 7. Ports, volumes, resource usage

| Port | Service |
|---|---|
| `5432` | Postgres |
| `6379` | Redis |
| `8000` | Backend (FastAPI) |

Named volumes (all present, all local driver): `ai-newsroom_postgres_data`,
`ai-newsroom_redis_data`, `ai-newsroom_image_storage_data`.

`docker system df`: 8 images (1.13GB), 3 active local volumes (138.3MB), 6.17GB build cache
(5.52GB reclaimable - normal accumulation from repeated local `docker build`, not itself a health
problem).

## 8. Summary

| Check | Status |
|---|---|
| Docker / Compose installed and current | ✅ |
| Postgres reachable, healthy | ✅ (`pg_isready` → accepting connections) |
| Redis reachable, healthy | ✅ (`PING` → `PONG`) |
| Backend reachable | ✅ (`GET /` → 200) |
| Migrations at head | ❌ (one revision behind - pre-existing, out of scope here) |
| automation_worker running | ❌ → fixed in M1 |
| news_analysis_worker running | ❌ → intentionally left stopped (real paid-API consequence, pending separate confirmation) |
| content_worker running | ❌ → intentionally left stopped (same reason) |
| telegram_bot running | ❌ → fixed in M1 |
