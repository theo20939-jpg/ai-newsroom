# INSTAGRAM-CONTENT-STRATEGY-V2-IMPLEMENTATION-1

## RECOVERY

```
INTERRUPTION_REASON=HOST_POWER_OFF

RECOVERED_BRANCH=feature/instagram-content-strategy-v2-implementation-1
RECOVERED_WORKTREE=C:/Users/Theodor/ai-newsroom-content-strategy-v2-1
RECOVERED_HEAD_AT_START=fb344d7 (feat(instagram): Phase 4 - NEWS_DIGEST replaces the old per-story NEWS trigger)
WORKTREE_WAS_DIRTY=true (Phase 5 - Trend Radar core - fully staged, 0 unstaged deltas on top, 0 untracked files)

COMMITS_FOUND_FROM_INTERRUPTED_RUN=4
  347fdb1 feat(director): Phase 1 - conversational Director + Product Truth
  0238ac9 feat(instagram): Phase 2 - generalized trigger + campaign-free PRODUCT lane
  87ca8b9 feat(instagram): Phase 3 - REEL production scripts
  fb344d7 feat(instagram): Phase 4 - NEWS_DIGEST replaces the old per-story NEWS trigger

PHASE_STATE_AT_RECOVERY:
PHASE_1_DIRECTOR=COMPLETE_COMMITTED
PHASE_2_PRODUCT_TRIGGER=COMPLETE_COMMITTED
PHASE_3_REEL_SCRIPTS=COMPLETE_COMMITTED
PHASE_4_NEWS_DIGEST=COMPLETE_COMMITTED
PHASE_5_TREND_CORE=COMPLETE_UNCOMMITTED (fully staged, syntactically clean, untested at recovery time)
PHASE_6_YOUTUBE_BLUESKY=NOT_STARTED
FINAL_REGRESSION_DOCS=NOT_STARTED

UNCOMMITTED_WORK_RECOVERED=Phase 5 (Trend Radar core): migration 9b2e4f7c1a83, database/models/trend_cluster.py,
  trend_observation.py, prompts/trend_fingerprint/v1.yaml, services/trend_evidence_ranking.py,
  trend_fingerprint.py, trend_normalization.py, trend_signal_matching.py, trend_source_scope.py,
  5 focused test files + the Phase 5 fixture-gate test, and matching core/config.py /
  database/models/__init__.py edits. Verified (not assumed) via: ast.parse on all 14 files
  (0 syntax errors - no mid-write truncation), a single alembic head (migration chain intact),
  and a full test run once a reachable local Postgres was available (see below) - 66/66 pass.
  Then committed as its own phase-specific commit (f5a90c4), per the recovery logic - nothing
  from the interrupted run was rewritten or regenerated, only verified and committed.
FILES_REQUIRING_REPAIR=none (no truncated/corrupt file found)
WORK_DISCARDED=false
```

Docker Desktop was not running at recovery start (`docker ps` failed to reach the daemon) - it was
started locally (`Start-Process 'Docker Desktop.exe'`) so the project's own existing local dev
`postgres`/`redis` containers (`docker-compose.yml`, already present as stopped containers from a
prior local session, not created new) could come up and Phase 5/6's DB-backed tests could actually
run rather than being assumed to pass. This is local dev-only infrastructure; the Founder's real
production stack (remote, deployed separately) was never touched, inspected, or connected to.

## Base lineage

Base: `feature/instagram-automatic-editorial-trigger-data-v2-integration-1` @ `d284d03` (already
merged into this branch's history via the normal multi-lineage integration chain this repo uses -
see `git log --graph` for the full merge history). `BASE_HEAD=d284d03`, `FINAL_HEAD=0db9a72`.

## Commit map (this implementation)

| Commit | Phase | Summary |
|---|---|---|
| `347fdb1` | 1 | Conversational Director + Product Truth (Migration 1) |
| `0238ac9` | 2 | Generalized trigger + campaign-free PRODUCT lane |
| `87ca8b9` | 3 | REEL production scripts (`reel_script_readiness`) |
| `fb344d7` | 4 | NEWS_DIGEST replaces the old per-story NEWS trigger (Migration 2) |
| `f5a90c4` | 5 | Trend Radar core - clustering, velocity, normalization, evidence gate (Migration 3) |
| `0db9a72` | 6 | YouTube + Bluesky Trend Radar source adapters |

## Migrations

1. `a3f7c1d9e042` - Director conversational extension (`BusinessContextProposal.origin`/
   `origin_context`, `Product.undecided_facts`)
2. `d84b1e6f3a52` - `digest_schedule_state` (NEWS_DIGEST's `last_run_at` cold-start state)
3. `9b2e4f7c1a83` - `trend_observations` + `trend_clusters` (Trend Radar core)

All three chain cleanly to a single alembic head (`9b2e4f7c1a83`); verified with
`python -m alembic heads` against the local dev Postgres.

## Architecture invariants (verified, not assumed)

- `NEW_PIPELINES=0`, `NEW_SCHEDULERS=0`, `NEW_CREATIVE_DIRECTORS=0`, `NEW_RENDERERS=0`,
  `NEW_AGENTS=0`. TREND/PRODUCT/NEWS_DIGEST all resolve to the same existing
  `ContentOpportunity` -> `generate_growth_strategy()` -> existing Format/Creative Director ->
  existing `InstagramContentPackage` -> existing renderer/QA/Telegram delivery path.
- `services/story_memory.py`, `services/editorial_treatment.py`, `services/telegram_routing.py`,
  the Unified Editorial Pipeline, the Vision Gate, and arXiv guards were never modified this
  implementation (confirmed via `git diff --name-only d284d03..HEAD` - none of those paths appear).
- Structural fixture-gate tests (not just flags) prove shadow-only status for both Phase 5 and
  Phase 6: `worker/content_cycle.py`'s own AST is inspected to prove it never calls
  `build_trend_opportunity()`/`is_trend_evidence_sufficient()` and never imports either Trend
  Radar source adapter.
- `TREND_AUTONOMOUS_CONTENT_GENERATION` stays `False`; `trend_collection_enabled` /
  `trend_clustering_enabled` stay `False`; `trend_ranking_shadow` stays `True`.

## Phase 6 (new this session): YouTube + Bluesky adapters

`integrations/sources/youtube_source.py` (`YouTubeTrendSourceAdapter`) and
`integrations/sources/bluesky_source.py` (`BlueskyTrendSourceAdapter`) - real, official-API-only
adapters (YouTube Data API v3 `search.list`+`videos.list`; Bluesky AT Protocol
`app.bsky.feed.searchPosts` with app-password session auth via `com.atproto.server.createSession`).
Neither scrapes nor estimates a metric its own API doesn't return. Both raise
`TrendSourceNotConfigured` (new, in `services/trend_fingerprint.py`) when their credentials
(`settings.youtube_api_key` / `settings.bluesky_handle`+`bluesky_app_password`, all optional
`SecretStr`-backed config, unset in this environment) are absent, rather than fabricating
candidates - code/tests/config readiness only, exactly as scoped; **no credentials were requested
from the Founder**. `fetch_candidates()` returns the new shared `TrendSignalCandidate` DTO (also
added to `trend_fingerprint.py`, the pre-existing pre-storage boundary module) - callable and
fully unit-tested, but not wired into any live collection cycle (`worker/content_cycle.py` imports
neither adapter, proven structurally by `tests/test_instagram_content_strategy_v2_phase6_fixture_gate.py`).

## Tests by phase

| Phase | Test files | Result |
|---|---|---|
| 1 | `test_instagram_content_strategy_v2_phase1_fixtures.py`, `test_business_context_command_parser_v2.py`, `test_business_context_director_questions.py`, `test_product_context_service_fact_merge.py`, `test_product_fact_state.py` | 40/40 pass |
| 2+3+4 | `test_instagram_content_strategy_v2_phase2_product_lane.py`, `..._phase2_worker_wiring.py`, `..._phase3_reel_scripts.py`, `test_instagram_creative_director.py`, `..._phase4_news_digest_wiring.py`, `test_instagram_news_digest.py` | 61/61 pass |
| 5 | `test_trend_evidence_ranking.py`, `test_trend_fingerprint.py`, `test_trend_normalization.py`, `test_trend_signal_matching.py`, `test_trend_source_scope.py`, `..._phase5_fixture_gate.py` | 56/56 pass (34 need no DB, 22 need Postgres - all pass once the local dev DB was reachable) |
| 6 | `test_youtube_source.py`, `test_bluesky_source.py`, `..._phase6_fixture_gate.py` | 13/13 pass |

## Final regression (chunked, per policy - no monolithic full-suite run)

| Chunk | Scope | Result |
|---|---|---|
| A | Business Context / Proposal / Product / ProductContextVersion | 68/68 pass |
| B | Story Memory (v1+v2) + arXiv guards | 226/227 pass, 1 skipped - **1 pre-existing failure, not caused by this implementation** (see below) |
| C | Vision Gate (`media_subject_match_capability`, unified pipeline subject-match/vision-gate + replays) | 38/38 pass |
| D | Unified Editorial Pipeline core (orchestrator, adapters, recovery, language QA, shadow) | 45/45 pass |
| E | Unified Editorial Pipeline hardening/runtime (media truthfulness, same-asset invariant, cutover authority, recovery concurrency) | 84/84 pass |
| F | Telegram routing + editorial treatment | 136/136 pass |
| G | Instagram creative/package/opportunity/digest/art-validator | 74/74 pass |
| H | worker/content_cycle + all Phase 1-4 fixture gates + Instagram-Telegram editorial delivery | 81/81 pass |
| Phase 5+6 (rerun after Phase 6 edits touched shared `trend_fingerprint.py`/`core/config.py`) | Trend Radar + source adapters | 69/69 pass |

**Total new/rerun this session: 782 passed, 1 skipped, 1 pre-existing failure.**

### Disclosed pre-existing failure (not a regression from this implementation)

`tests/test_story_memory_v2_shadow_isolation.py::test_only_expected_files_import_the_v2_modules`
fails: `scripts/_phase23_1p_post_run_analysis.py` imports `story_delta_engine`/`story_suppression`/
`story_confidence` and isn't on that test's allowlist. Verified via `git log d284d03 --
scripts/_phase23_1p_post_run_analysis.py` that this script - and the test itself - already existed,
unmodified, at this implementation's own base commit, well before Phase 1 started. `services/
story_memory.py` and its V2 modules are a frozen area for this implementation and were never
touched; this finding is disclosed for a separate, dedicated fix, not addressed here.

### mypy

Files actually authored this session (`integrations/sources/youtube_source.py`, `bluesky_source.py`,
the `TrendSignalCandidate`/`TrendSourceNotConfigured` addition to `services/trend_fingerprint.py`,
the `core/config.py` credential fields, and all three new Phase 6 test files) are mypy-clean.
Running mypy across the full set of files changed since the base commit (`d284d03..HEAD`) surfaces
60 findings, but every one traces to either (a) pre-existing test-fixture looseness already present
in Phase 1/3/4/5 files this implementation inherited rather than authored (e.g. `SimpleNamespace`
stubs typed against `Product`), or (b) mypy's transitive analysis of unrelated, pre-existing services
imported by those files (`story_delta_engine.py`, `instagram_editorial_regeneration.py`,
`instagram_telegram_delivery.py`, `design_reference_registry.py`'s missing PyYAML stubs, etc.) -
none of which this implementation modified. `database/models/__init__.py` has 6 pre-existing ruff
F401 findings (unused re-exports, by the module's own registration-only design); 2 are this
implementation's own `TrendCluster`/`TrendObservation` additions following the exact same
already-established pattern as the other 4 pre-existing ones in that same file.

## External blockers (unchanged from the approved scope)

- `settings.youtube_api_key` / `settings.bluesky_handle` / `settings.bluesky_app_password` are
  unset in this environment - Phase 6 is `BLOCKED_EXTERNAL_SETUP` for any *live* collection; no
  credentials were requested from the Founder, per instruction.
- Real threshold tuning for `services/trend_evidence_ranking.py`'s evidence-sufficiency gate is
  explicit future work, gated on observing real Phase 6 data once credentials exist.

## Remaining work / rollout notes

- Trend Radar ingestion orchestration (actually calling the two new adapters on a schedule and
  feeding results through `trend_fingerprint`/`trend_signal_matching`/`trend_evidence_ranking`
  into a real `ContentOpportunity(TREND)`) is intentionally **not built** this implementation -
  `build_trend_opportunity()` exists and is fully tested but is never called live, per the
  approved shadow-mode scope. That wiring, plus real threshold calibration against live data, is
  the natural next phase once YouTube/Bluesky credentials exist.
- This branch was never deployed, and no production system, database, or `.env` was touched at any
  point in this recovery.

## Rollback notes

Every phase is its own isolated commit (`347fdb1`, `0238ac9`, `87ca8b9`, `fb344d7`, `f5a90c4`,
`0db9a72`) on `feature/instagram-content-strategy-v2-implementation-1`; reverting any one phase
independently is a normal `git revert` of that single commit (Phase 5/6 depend on Phases 1-4's
migrations/config but not vice versa; Phase 6 depends on Phase 5's `TrendSignalCandidate`/
`TrendSourceNotConfigured` additions to `trend_fingerprint.py`).
