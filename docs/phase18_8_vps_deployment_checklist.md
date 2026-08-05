# Phase 18.8 M4 — VPS Deployment Checklist (Future-Phase Plan Only)

Status: **documentation only. No VPS was provisioned or deployed to in this phase** (out of
scope - see Phase 18.8's own context: "This phase is NOT VPS deployment"). Every number below is
derived from this project's real, currently-running local Docker Compose stack (Phase 18.8
M0-M3), not estimated from scratch.

## 1. Real observed resource baseline (this local deployment, light load)

| Service | Observed memory (idle/light load) | Observed CPU |
|---|---|---|
| `telegram_bot` | 170 MiB | ~0% |
| `automation_worker` | 142 MiB | ~0% (bursts during a collection cycle) |
| `postgres` | 118 MiB | ~0% |
| `backend` | 48 MiB | ~0.2% |
| `redis` | 10 MiB | ~0.7% |
| `news_analysis_worker` (not running this session) | ~140-170 MiB estimated, same base image | bursts during LLM calls (I/O-bound, not CPU-bound) |
| `content_worker` (not running this session) | ~140-170 MiB estimated, same base image | bursts during LLM calls + image handling |

**Observed total, 5 of 7 services running: ~490 MiB.** All 7 services together, conservatively:
**~800 MiB-1 GiB** at idle, with short bursts during LLM calls (I/O-bound waiting on OpenAI, not
CPU-heavy) and during a collection cycle (72-89 concurrent-ish HTTP fetches, still I/O-bound).

## 2. Recommended VPS specs

| Resource | Recommendation | Basis |
|---|---|---|
| RAM | **4 GB minimum, 8 GB comfortable** | ~1 GiB real usage at idle + headroom for burst concurrency, OS overhead, and Docker's own overhead; matches the `docker-compose.yml`-implied `7.458 GiB` container memory limit already configured in this local environment |
| vCPU | **2 vCPU minimum** | All observed load so far is I/O-bound (HTTP fetches, LLM API waits), not CPU-bound; 2 vCPUs covers concurrent worker activity without contention |
| Disk | **40 GB minimum, 80 GB comfortable** | Postgres data is 111.5 MB for 13,520 `NewsEvent` rows (~8.2 KB/row including indexes/related tables) - at sustained real-world ingestion (~1,000-1,500 new events/collection cycle observed in M2, cycles roughly every few minutes when `NEWS_COLLECTION_ENABLED`), data grows meaningfully over months; `image_storage_data` (28.8 MB observed) grows with `content_worker`'s own image-candidate persistence; plus Docker images/build cache (~1.1 GB images, 6+ GB build cache observed locally - a VPS build should use `--no-cache`-free CI builds or a registry pull instead of repeated local builds to avoid this) |
| OS | Linux (Ubuntu 22.04/24.04 LTS or Debian 12) | `worker/main.py`'s own signal-handling code explicitly notes Windows' event loop doesn't support `add_signal_handler` - graceful shutdown only works correctly on the Linux/Docker target this project's own code already assumes |
| Network | Outbound HTTPS to: OpenAI API, Telegram Bot API, every configured RSS/news source (~89 sources currently) | No inbound requirement beyond SSH + optionally port 8000 if the backend API needs external access |

## 3. Required services (unchanged from `docker-compose.yml` - reuse exactly, no architecture change)

`backend`, `automation_worker`, `news_analysis_worker`, `content_worker`, `telegram_bot`,
`postgres` (16-alpine), `redis` (7-alpine) - 7 containers, exactly as already defined in this
repository's own `docker-compose.yml`. No new service is proposed.

## 4. Ports

| Port | Service | Exposure |
|---|---|---|
| 5432 | Postgres | Internal only in production (do not expose publicly on a real VPS - this local dev setup exposes it directly, which is acceptable locally but should be firewalled or removed from the public interface on a real server) |
| 6379 | Redis | Internal only in production, same reasoning |
| 8000 | Backend | Expose only if external API access is actually needed; otherwise keep internal and access via SSH tunnel/VPN for admin use |
| 22 | SSH | Standard admin access - key-based auth only, no password auth |

## 5. Required environment variables (names only - reuse this repo's own `.env`, never commit it)

Same 26 variables already audited in `docs/phase18_8_environment_audit.md` §5:
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT`, `REDIS_HOST`, `REDIS_PORT`,
`REDIS_DB`, `REDIS_UNAVAILABLE_POLICY`, `OPENAI_API_KEY`, `ENABLED_PROVIDERS`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_STRING`,
`EDITORIAL_CHAT_ID`, `GITHUB_TOKEN`, `NEWS_COLLECTION_ENABLED`, `NEWS_ANALYSIS_ENABLED`,
`NEWS_ANALYSIS_FRESHNESS_CUTOFF_HOURS`, `CONTENT_GENERATION_ENABLED`,
`CONTENT_GENERATION_DRY_RUN`, `CONTENT_GENERATION_MIN_SCORE`,
`CONTENT_GENERATION_BATCH_SIZE`, `CONTENT_GENERATION_POLL_INTERVAL_SECONDS`,
`IMAGE_INTELLIGENCE_MODE`, `IMAGE_CANDIDATE_PERSISTENCE_MODE`, `IMAGE_EDITORIAL_PREVIEW_ENABLED`.

A real VPS deployment must generate a **fresh** `POSTGRES_PASSWORD` and rotate `OPENAI_API_KEY`/
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_SESSION_STRING`/`GITHUB_TOKEN` for the new environment rather than
copying this local `.env` verbatim - not done in this phase (secret rotation/generation is a
future-phase action, out of scope for a documentation-only checklist).

**Recommend deciding explicitly, before any real VPS deployment**, whether `meme_opportunity_mode`/
`meme_safety_gate_mode`/`meme_opportunity_calibration_version`/`meme_safety_calibration_version`
should be set in the new environment's `.env` at all - every one of them still defaults to `"off"`/
`"v1"` in `core/config.py`, and no phase through 18.8 has authorized changing that default anywhere
outside a local, read-only validation run.

## 6. Deployment steps (future phase - not executed here)

1. Provision the VPS per §2, install Docker + Docker Compose (matching or exceeding the locally
   proven `29.6.1`/`v5.3.0`).
2. Clone the repository at the desired release tag/checkpoint (e.g.
   `checkpoint/phase18-7-calibration-ready` or later, once authorized).
3. Create a fresh `.env` on the server (never copy the local one) - new Postgres password, rotated
   API keys/tokens, `CONTENT_GENERATION_DRY_RUN=true` recommended for the *first* deployment run
   until the operator has confirmed real behavior on the new server, matching this project's own
   established "prove it dry-run first" discipline.
4. `docker compose build` (or pull from a registry if CI is set up separately - not yet built in
   this project).
5. `docker compose up -d postgres redis` first; wait for both healthchecks to pass.
6. `python -m alembic upgrade head` — **and reconcile the already-known migration gap** (real local
   `alembic current` is one revision behind `heads` per every phase since 18.5's own audit) before
   or during this step, as its own explicitly-authorized action.
7. `docker compose up -d backend automation_worker telegram_bot` (zero/low-cost services first).
8. Verify: `curl http://localhost:8000/` → `{"status":"Application running"}`; check
   `automation_worker` logs for a real `Collection cycle finished` line; verify the bot responds in
   Telegram.
9. Only after step 8 is confirmed stable, and only with explicit, separate authorization (per this
   project's own standing rule on paid API activation), `docker compose up -d news_analysis_worker
   content_worker`.
10. Set up log rotation/monitoring (not currently configured anywhere in this repo - a real gap for
    a real always-on VPS, `docker logs` has no size cap by default).

## 7. Backup strategy

- **Postgres**: `pg_dump` on a schedule (e.g. daily via `docker exec ai_newsroom_postgres pg_dump
  -U $POSTGRES_USER $POSTGRES_DB` piped to a timestamped file), retained off-host (the VPS itself
  is a single point of failure for local-only backups). Current real data volume (111.5 MB for
  13,520 events) makes a full daily dump cheap; revisit frequency/incremental strategy once volume
  grows by 10-100x.
- **`image_storage_data` volume**: back up alongside Postgres (image bytes referenced by
  `MemeCandidate`/`ContentDraft` rows would orphan without their DB rows, and vice versa - back up
  both together, not independently, to keep them consistent).
- **`.env` / secrets**: back up via a secrets manager or encrypted vault, never as a plaintext file
  copy sitting next to the Postgres dump.
- **Restore drill**: not performed in this phase (requires an actual second environment to restore
  into) - recommend as an explicit first action once a real VPS exists, before declaring the backup
  strategy trustworthy.

## 8. Explicitly NOT covered by this checklist

Per this phase's own scope: no VPS was provisioned, no DNS/TLS/reverse-proxy setup, no CI/CD
pipeline, no actual secret rotation, no load testing at real production scale, no monitoring/
alerting stack. All of the above are real future-phase work, listed here so they are not silently
forgotten, not because any of them was attempted.
