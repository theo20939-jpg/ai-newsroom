# VPS Deployment Guide

**Status:** documentation only. No server was provisioned, nothing was deployed, nothing was
committed. Builds on and supersedes the numbers in `docs/phase18_8_vps_deployment_checklist.md`
(now stale — written before Story Memory, article acquisition, video discovery, and rich media
existed) and reflects the state validated in `docs/pre_vps_integrated_validation_report.md`
(**READY FOR VPS**, commits `1817a7a`, `915b553`, `3e6a7a6`).

Reuses the existing, unmodified `docker-compose.yml` / `Dockerfile` / `alembic` setup exactly —
no new services, no architecture change.

---

## 1. Server requirements

| Resource | Recommendation | Basis |
|---|---|---|
| RAM | 4 GB minimum, 8 GB comfortable | Phase 18.8's own real observed baseline (~490 MiB for 5/7 services, ~1 GiB extrapolated for all 7) is the best available real data point; the newly-validated features (Story Memory, article acquisition, video discovery, rich media) add DB rows and occasional larger HTTP fetches (bounded video validation, `video_discovery_max_bytes=20MB` cap) but no new services or persistent processes, so this baseline is not expected to shift materially |
| vCPU | 2 vCPU minimum | All real load observed (both in Phase 18.8 and in the 60-minute integrated validation just completed) is I/O-bound — HTTP fetches, LLM API waits, Telegram sends — not CPU-bound |
| Disk | 40 GB minimum, 80 GB comfortable | Phase 18.8's baseline (111.5 MB Postgres for 13,520 events) plus new tables added since (`news_event_story_links`, `news_event_article_acquisitions`, `content_draft_media_items`, `content_draft_editorial_plans`, `story_context_snapshots`, `media_vision_reviews`, and others — 21 migrations total). Also budget for the `image_storage_data` named volume (image candidate bytes) and Docker image/build cache |
| OS | Linux (Ubuntu 22.04/24.04 LTS or Debian 12) | `worker/main.py`/`worker/analysis_main.py`/`worker/content_main.py` all register `SIGTERM`/`SIGINT` handlers via `loop.add_signal_handler()`, which is not implemented on Windows' default event loop — graceful shutdown only works correctly on the Linux/Docker target this project's code already assumes |
| Docker | Docker Engine + Compose v2 plugin | Locally proven versions: Docker `29.6.1`, Compose `v5.3.0` — install matching or newer |
| Network (outbound) | HTTPS to: OpenAI API, Telegram Bot API (`api.telegram.org`), Telegram Client API (`149.154.167.x` MTProto, used by the Telethon-based source collector), every configured RSS/news source (~230 after the v1.1 source pack integration), GitHub API (optional, for `github_api` sources) | No new outbound destinations vs. Phase 18.8 — the newly-validated video discovery only fetches URLs already present in already-fetched RSS/HTML content, never a new external service |
| Network (inbound) | SSH (22) only, required | See §1 port table below for what must stay internal-only |

## 2. Installation commands

```bash
# 1. System prerequisites (Ubuntu/Debian example)
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin git
sudo systemctl enable --now docker

# 2. Clone the repository at the validated commit
git clone <repo-url> ai-newsroom
cd ai-newsroom
git checkout 3e6a7a6cf734410dbbab972b7e8f19f7e857d508   # last commit covered by the READY FOR VPS validation

# 3. Build images (no registry configured in this project — local build)
docker compose build
```

## 3. Environment setup

```bash
cp .env.example .env
```

**`.env.example` is significantly out of date** — it documents ~15 variables while `core/config.py`
now defines **120 settings fields** (all with Python-level defaults, so the app *will* boot without
most of them set, but several must be set for real functionality). Treat the table below, not
`.env.example`, as authoritative for this deployment.

**Credentials — must be set for real operation (all default to empty/`None`):**

| Variable | Purpose |
|---|---|
| `POSTGRES_PASSWORD` | Generate fresh — never reuse a local dev password |
| `TELEGRAM_BOT_TOKEN` | From @BotFather. `bot/loader.py::create_bot()` raises `RuntimeError` at startup (not import time) if unset |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | From https://my.telegram.org — Telethon-based source collector |
| `TELEGRAM_SESSION_STRING` | Generated once via interactive Telethon login (see README "Telegram Client credentials") — never a `.session` file |
| `OPENAI_API_KEY` | Required for every LLM-dependent stage (analysis, copywriting, quality) |
| `ENABLED_PROVIDERS` | Must include `["openai"]` — an API key alone does not put a provider live |
| `NEWSROOM_TELEGRAM_CHAT_ID`, `NEWS_TOPIC_ID` | The real NEWS destination — validated this session as `-1004297182444` / topic `2`; use the operator's real production chat/topic, not this validation-only value |
| `EDITORIAL_CHAT_ID` | Legacy single-destination chat (pre-router-mode) |
| `GITHUB_TOKEN` | Optional — required only for the source pack's `github_api` sources to import; works unauthenticated at a lower rate limit otherwise |
| `REDIS_UNAVAILABLE_POLICY` | Has **no default** in `core/config.py`'s own design — must be explicitly `fail_open` or `fail_closed`; Settings construction otherwise leaves this unset behavior undefined for RateLimiter/CostTracker on Redis unavailability |

**Mode flags — recommended first-deployment values.** Every one of these already defaults to
`off`/`legacy`/`shadow`/`v1` (conservative) in `core/config.py`; a deployment that just runs
`docker compose up` with a minimal `.env` inherits the safest possible starting state by
construction. Do not flip any of these to `enforce` in the initial `.env` — activate them
individually, post-deployment, per §5's staged rollout, exactly as the just-completed validation
did in-process only:

| Variable | Real default | Recommended for first deploy |
|---|---|---|
| `NEWS_COLLECTION_ENABLED` | `False` | `True` (core, zero-cost) |
| `NEWS_ANALYSIS_ENABLED` | `False` | `True` only after `NEWS_COLLECTION_ENABLED` confirmed stable — this is a **paid** stage |
| `CONTENT_GENERATION_ENABLED` | `False` | `True` only after analysis confirmed stable — **paid + Telegram-facing** |
| `CONTENT_GENERATION_DRY_RUN` | `True` | Keep `True` for the first real run on the new server, matching this project's own established "prove it dry-run first" discipline, before switching to `False` |
| `EDITORIAL_DELIVERY_MODE` | `legacy` | `router` (required for V8-family/rich-media/video delivery — validated this session) |
| `COPYWRITING_PROMPT_VERSION` | `4` | `8.6` (the version actually validated) |
| `ARTICLE_ACQUISITION_MODE` | `off` | `enforce` — validated clean this session (0 errors across the full acquisition chain, including the sibling-reuse fix) |
| `STORY_MEMORY_MODE` | `off` | `shadow` first, `enforce` once comfortable — **note**: per direct source audit, `enforce` currently has no distinct code-level behavior from `shadow` anywhere in this codebase (`services/triage_orchestrator.py`'s own docstring: "enforce's suppression path is not implemented"); both values produce identical persistence/observability behavior today |
| `TELEGRAM_STORY_REPLY_MODE` | `off` | Keep `off` initially — this specific setting was **not** exercised at `enforce` in the validation (kept `off` throughout as an explicit safety invariant); validate separately before enabling |
| `RICH_MEDIA_MODE` | `off` | `enforce` — validated clean this session (real single-photo sends confirmed; media-group/video-attachment path exists and is tested but was not exercised by real delivered traffic this run — see the validation report §5) |
| `VIDEO_DISCOVERY_MODE` | `off` | `enforce` — validated clean this session; note the video-without-eligible-images gap disclosed in the validation report before expecting every discovered video to reach delivery |
| `IMAGE_CANDIDATE_PERSISTENCE_MODE`, `IMAGE_EDITORIAL_PREVIEW_ENABLED` | `off` / `False` | `enabled`/`True` — required for any image delivery at all |

All other mode flags (`meme_*`, `editorial_brief_mode`, `channel_relevance_mode`,
`adaptive_length_mode`, `beginner_copywriting_mode`, `editorial_completeness_mode`,
`source_intelligence_mode`, `media_vision_review_mode`, `editorial_planning_mode`,
`quote_telegram_rendering_mode`, etc.) are **out of scope for this deployment** — leave every one
at its real default (`off`/`v1`). None of them were part of the validation that produced the
READY FOR VPS verdict; activating them is a separate, future, separately-authorized decision.

**Ports (from `docker-compose.yml`):**

| Port | Service | Production exposure |
|---|---|---|
| 5432 | Postgres | Internal only — the compose file exposes it on the host by default; remove the `ports:` mapping or firewall it before going live |
| 6379 | Redis | Internal only, same reasoning — no `requirepass` is configured anywhere in this repo |
| 8000 | Backend (FastAPI) | Expose only if external API access is genuinely needed; otherwise keep internal, access via SSH tunnel |
| 22 | SSH | Key-based auth only |

## 4. Migration steps

The migration chain is a single linear history, 21 revisions, head `3f37cf34109d` — confirmed via
`alembic heads` (exactly one head, no branching to reconcile).

```bash
docker compose up -d postgres redis
# wait for both healthchecks to report healthy:
docker compose ps postgres redis

docker compose run --rm backend alembic upgrade head
# or, without the backend image: from a host with the venv/deps installed and
# POSTGRES_HOST pointed at the running container:
#   alembic upgrade head
```

On a **fresh** database this applies all 21 migrations cleanly in order — there is no reconciliation
needed (unlike the current local dev DB, which is 3 revisions behind `head` from earlier phases;
irrelevant to a fresh VPS install, which starts at base).

Verify: `alembic current` must print `3f37cf34109d (head)`.

## 5. Startup sequence

Staged, mirroring the pattern already established and proven in
`docs/phase17_m6_1_production_cutover_runbook.md` and `docs/phase18_8_vps_deployment_checklist.md`
— zero/low-cost services first, paid/Telegram-facing services only after the first stage is
confirmed stable:

```bash
# Stage 0: data layer
docker compose up -d postgres redis
docker compose ps postgres redis          # both healthy before continuing

# Stage 1: migrations
docker compose run --rm backend alembic upgrade head

# Stage 2: zero/low-cost services
docker compose up -d backend automation_worker telegram_bot
# verify (§6) before continuing

# Stage 3: paid services — separate, explicit authorization required
# (this project's own standing rule: no paid-API activation without explicit, separate approval)
docker compose up -d news_analysis_worker content_worker
```

`automation_worker`/`news_analysis_worker`/`content_worker` each have their own
enabled/disabled idle model (`worker/main.py`, `worker/analysis_main.py`,
`worker/content_main.py`): with `*_ENABLED=False` they block on an unset `asyncio.Event`
indefinitely rather than exiting — this is deliberate so `restart: unless-stopped` never produces
a restart loop for a container that is intentionally idle. A container in this state is normal,
not a failure.

## 6. Verification checklist

- [ ] `docker compose ps` — all 7 containers `Up`/`healthy` (postgres, redis have real
      `healthcheck:` blocks; the other 5 do not — see §8 gap note)
- [ ] `curl http://localhost:8000/` → `{"status": "Application running"}`
- [ ] `alembic current` → `3f37cf34109d (head)`
- [ ] `docker compose logs automation_worker` shows a real `Collection cycle finished:
      processed=... failed=... created=... duplicates=...` line
- [ ] Telegram bot responds to a manual `/start` or equivalent in a private chat (confirms
      `TELEGRAM_BOT_TOKEN` is valid and polling is active)
- [ ] With `CONTENT_GENERATION_DRY_RUN=True`: `docker compose logs content_worker` shows
      `dry_run_rendered` incrementing, **zero** real `send_message`/`send_photo`/`send_media_group`
      calls (no message actually appears in the real Telegram destination)
- [ ] Postgres reachable: `docker compose exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c
      "select count(*) from news_events;"`
- [ ] Redis reachable: `docker compose exec redis redis-cli ping` → `PONG`
- [ ] `docker compose logs` across all 5 app services shows **zero** unhandled tracebacks outside
      the known, benign per-source RSS-collector pattern (`services.collector | Source X failed,
      skipping` — expected resilience behavior, not an error)
- [ ] Only once `CONTENT_GENERATION_DRY_RUN` is flipped to `False`: confirm the first few real
      sends land in the correct chat/topic and render correctly (mirrors the real-time destination
      + formatting checks the pre-VPS validation harness performed)

## 7. Rollback procedure

**Behavior-only rollback (no migration, no data change)** — the common case, e.g. reverting a
mode flag:
```bash
# revert the relevant env var(s) in .env to their previous value
docker compose restart backend automation_worker news_analysis_worker content_worker
```
No `telegram_bot` restart needed unless the change was Telegram-facing.

**Code rollback:**
```bash
git log -1                          # record current commit before any change, always
git checkout <previous-known-good-commit>
docker compose build
docker compose up -d
```

**Migration rollback** (only if a new migration was applied and needs reverting):
```bash
alembic downgrade -1
```
Not expected to be needed for the commits covered by this validation — none of `1817a7a`/`915b553`/
`3e6a7a6` includes an unapplied migration; the last real schema change (`3f37cf34109d`) predates
all three.

**Full rollback (data-preserving stop):**
```bash
docker compose stop        # preserves postgres_data/redis_data/image_storage_data volumes
# or, to fully tear down (destructive — confirm backups first):
docker compose down        # add -v only if volumes should also be deleted; do not do this casually
```

**Rollback triggers** (mirroring the established convention in
`docs/phase17_m6_1_production_cutover_runbook.md`): unexpected error-rate increase in worker logs,
any `*_failed` log line volume spike, cost exceeding expectation (compare `AIExecution` row
sums), a destination violation (any send outside the configured chat/topic), or a duplicate
delivery for the same story.

## 8. First 24h monitoring checklist

- [ ] **Cost**: sum `AIExecution.cost` at regular intervals (the validation harness's own query —
      `SELECT sum(cost) FROM ai_executions`) against the expected daily budget; no automated
      dashboard exists yet, this is a manual check
- [ ] **Delivery volume**: count of real Telegram sends vs. expectation for the source volume
      enabled
- [ ] **Error log volume**: `docker compose logs --since 1h | grep -c ERROR` trend — a sudden
      increase is the primary rollback trigger
- [ ] **Per-source collector health**: watch for `Source X failed, skipping` — expected for a few
      stale/redirected RSS URLs (already known: ComfyUI, VentureBeat, Tom's Hardware, AnandTech,
      MacRumors, Windows Central per this session's validation run), but a sudden spike across many
      sources indicates a network/DNS issue on the new server, not the sources themselves
- [ ] **Story Memory decision mix**: spot-check `news_event_story_links.match_type` distribution —
      the validation observed a real, sensible mix (78 new_story / 40 related_story / 47
      uncertain_match / 7 semantic_duplicate / 2 story_update / 1 supporting_source over 60
      minutes); a distribution wildly different from this shape on the new server is worth a look
- [ ] **Duplicate-delivery check**: no story should receive two `ROOT`-type deliveries — spot-check
      `story_telegram_deliveries` for any `story_id` appearing more than once with
      `delivery_type='root'`
- [ ] **Disk growth**: `docker system df` and Postgres/`image_storage_data` volume size — establish
      a baseline in the first 24h to project growth
- [ ] **Container restart count**: `docker compose ps` — repeated restarts on any service indicate
      a crash loop, not visible from logs alone if the container exits before flushing
- [ ] **Telegram API error rate**: watch for `TelegramNetworkError`/`TelegramAPIError` — the
      validation observed one transient `ClientConnectorError` that self-resolved; a sustained rate
      indicates a real connectivity or rate-limit problem, not routine transience

### Known gaps (disclosed, not fixed by this guide — out of scope per "do not modify application logic / do not add features")

- No Docker-level `healthcheck:` exists for `backend`, `automation_worker`, `news_analysis_worker`,
  `content_worker`, or `telegram_bot` — only `postgres`/`redis` have one. A hung (not crashed)
  worker process would not be caught by `docker compose ps`.
- No log rotation is configured anywhere in this repo — `docker logs` has no size cap by default;
  set `max-size`/`max-file` in the Docker daemon config or compose `logging:` block before a real
  always-on deployment runs for weeks.
- No backup automation exists yet — `docs/phase18_8_vps_deployment_checklist.md §7`'s manual
  `pg_dump` strategy is still the only documented approach; no restore drill has ever been
  performed.
- No monitoring/alerting stack — every check in §8 above is manual.
- `.env.example` should be regenerated from the real `core/config.py` schema in a future,
  separately-authorized documentation pass — it currently covers roughly 15 of 120 real settings.
