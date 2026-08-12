# Phase 23.1K — V8.2 Live Canary Preflight

Generated 2026-08-10, immediately before Part F's live bounded canary. All checks are read-only
except the two settings this script itself overrides in-process for the canary run (never written
to `.env`).

## 1. Branch / HEAD / DB revision

- Branch: `feature/phase19-editorial-depth-upgrade`
- HEAD: `d509566154368bf42d54e7dd66166712d77409cb` (unchanged all session — nothing committed)
- DB revision (`alembic current`): `8faedf40f596`
- Alembic head (`alembic heads`): `3f37cf34109d`
- Two migrations remain **created but not applied** (Phase 20's `story_memory_v2_shadow_columns`,
  `stories_updated_at_index`) — unrelated to this phase, untouched, disclosed for completeness.

## 2. Worker / container states

| Container | Status |
|---|---|
| `ai_newsroom_postgres` | Up (healthy) |
| `ai_newsroom_redis` | Up (healthy) |
| `ai_newsroom_backend` | Up |
| `ai_newsroom_automation_worker` | Up (collection + triage, bundled) |
| `ai_newsroom_telegram_bot` | Up |
| `content_worker` | **stopped** (established safety baseline, unchanged) |
| `news_analysis_worker` | **stopped** (established safety baseline, unchanged) |

The canary script calls `run_triage_cycle()`/`run_analysis_cycle()`/`run_content_cycle()` directly
in-process, exactly like Phase 23.1I's canary — it does not start `content_worker`/
`news_analysis_worker`.

## 3. Active settings (real `.env`, before any in-process override)

| Setting | Real value |
|---|---|
| `copywriting_prompt_version` | `4` |
| `editorial_delivery_mode` | `legacy` |
| `fact_safety_mode` | `shadow` |
| `story_memory_mode` | `off` |
| `story_context_mode` | `shadow` |
| `source_intelligence_mode` | `shadow` |
| `editorial_planning_mode` | `shadow` |
| `article_acquisition_mode` | `shadow` |
| `quote_telegram_rendering_mode` | `shadow` |
| `content_generation_dry_run` | `False` |
| `image_editorial_preview_enabled` | `True` |
| `image_candidate_persistence_mode` | `finalists` |
| `newsroom_telegram_chat_id` | `None` (router destination unconfigured by default) |
| `news_topic_id` | `None` |
| `content_generation_min_score` | `65` |
| `content_generation_freshness_cutoff_hours` | `24.0` |
| `content_generation_scan_limit` | `50` |
| `content_generation_batch_size` | `5` |

**Required for this canary, applied in-process only (never written to `.env`):**
`copywriting_prompt_version="8.2"`, `editorial_delivery_mode="router"`,
`newsroom_telegram_chat_id=-1004297182444`, `news_topic_id=2`. `fact_safety_mode` is already
`shadow` — no change needed. `content_generation_dry_run` is already `False`, so a live send is
possible once the router destination is set — this is exactly why the chat_id/topic_id override
above is hardcoded to the canary's own destination, never left to resolve from ambient config.

## 4. Story Memory — actual state (honest disclosure)

`story_memory_mode=off` in the real `.env`. This canary does **not** enable shadow or enforce mode
— per the phase brief's explicit "do not enable enforce" instruction and this session's repeated
prior finding (Phase 23.1I) that Story Memory has no bearing on this phase's own scope (copywriting
style + V8-family delivery wiring). The duplicate-delivery guard added in Phase 23.1I
(`services/story_duplicate_guard.py`) is independent of `story_memory_mode` and remains active
regardless (it reads existing `NewsEventStoryLink`/`StoryTelegramDelivery` rows, which can exist
from `story_memory_mode=shadow` runs in earlier phases).

## 5. Routing target

`EditorialDestination.NEWS` → hardcoded canary override `chat_id=-1004297182444`,
`message_thread_id=2` (topic). No other destination (MEME/TELEGRAPH/INSTAGRAM/REELS) is reachable
through this canary's code path.

## 6. Image state

- Editorial image pipeline last produced a candidate at `2026-08-09 21:11:42 UTC` (~7 hours before
  this preflight) — confirms the pipeline is live and was active recently, not stalled.
- `image_candidate_persistence_mode=finalists`, `image_editorial_preview_enabled=True` — image
  attachment remains possible during the canary exactly as in Phase 23.1H/23.1I, unchanged.

## 7. Eligible event count (read-only, current real backlog)

`_select_eligible_events()` (the exact function `run_content_cycle()` itself calls), evaluated
against the real DB with the real current settings (`freshness_cutoff_hours=24`, `min_score=65`,
`scan_limit=50`): **2 eligible events** right now. `automation_worker` is running continuously and
will keep adding fresh triaged events during the canary's own up-to-4-hour window — 2 is a
starting point, not a hard ceiling on what the canary can process.

## 8. Go/no-go

All required conditions are met: `fact_safety_mode=shadow` (already true), Story Memory honestly
disclosed as `off` (not enabled, not silently assumed), route hardcoded to the canary's own
chat/topic, `content_worker`/`news_analysis_worker` stay stopped, no `.env` changes. **Proceeding
to Part F (bounded live canary).**
