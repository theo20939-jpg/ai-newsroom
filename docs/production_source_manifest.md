# Production Source Manifest

Release truth as of UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 (2026-09-13). Values below are read
directly from the live host (SSH) and this repository's own git history - nothing guessed.

| Service | Production image/tag | Source commit | Notes |
|---|---|---|---|
| `content_worker` | `ai-newsroom-content_worker:b5d5276-pinned` | `b5d5276` | TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1 (PASS), deployed 2026-09-12/13 |
| `telegram_bot` | `ai-newsroom-telegram_bot:d2dea2c` | `d2dea2c` | production baseline |
| `backend` | `ai-newsroom-backend:d2dea2c` | `d2dea2c` | production baseline |
| `automation_worker` | `ai-newsroom-automation_worker:6f56aec` | `6f56aec` | Story Continuity P0 + arXiv clustering |
| `news_analysis_worker` | `ai-newsroom-news_analysis_worker:d2dea2c` | `d2dea2c` | production baseline |
| `postgres` | `postgres:16-alpine` | n/a | |
| `redis` | `redis:7-alpine` | n/a | |

**DB migration head (production)**: `4a1b7c9d2e3f` (unchanged by this phase - confirmed no new
migration files added; this phase's own new contracts are in-process only, per its own S6/S23
instruction not to migrate for them).

**Instagram**: not deployed anywhere. Real source exists at `0379ff2`
(`feature/instagram-autonomous-trend-to-carousel-canary-1`, local-only, never pushed to origin) -
`instagram_publication_enabled = false` throughout its entire history; no credentials configured on
the production host.

**Cross-platform media research**: real source exists at `9fc7b1e`
(`feature/cross-platform-media-research-selection-1`, local-only, never pushed) - not deployed
anywhere; `media_web_discovery_mode` defaults to `off` (`NullWebDiscoveryClient`, zero network
calls) in every real environment.

**This phase's own integration branch**: `feature/unified-editorial-production-pipeline-1`
(worktree `C:/Users/Theodor/ai-newsroom-unified-pipeline-1`), based on `b5d5276` + three merges
(`6f56aec`, `0379ff2`, `9fc7b1e` - see `docs/unified_editorial_source_reconciliation_1.md` for the
full reconciliation). Introduces `services/editorial_pipeline/` (new, additive) and one feature flag,
`unified_editorial_pipeline_enabled` (default `false`), plus `unified_editorial_pipeline_shadow_mode`
(default `false`). **Not deployed anywhere; no production config changed by this phase.**

**GitHub default branch** (`feature/phase19-editorial-depth-upgrade`, public): predates and is
unrelated to every production fix since 2026-09-08 (see the reconciliation report). **Not changed by
this phase.**

**Enabled flags relevant to this phase's own scope** (production, unchanged):
`instagram_publication_enabled=false`, `presentation_director_mode` (per-environment, unchanged),
`unified_editorial_pipeline_enabled=false` (new, this phase, not deployed).
