# Test summary

## New test files this phase

| File | Count | What it proves |
|---|---|---|
| `tests/test_unified_pipeline_recovery_service.py` | 9 | Real, durable `RecoveryService` state machine against the real `recovery_jobs` table: PENDING→RETRYING→TERMINAL_HOLD, deterministic backoff, attempt increment, max-attempts exhaustion, successful-retry→RECOVERED, `due_for_retry()` query, persistence across a fresh service instance, and the `hold_for_visual` compatibility mapping (never writes anything). |
| `tests/test_unified_pipeline_orchestrator_cutover.py` | 9 | Orchestrator's new, additive cutover behavior: durable persistence via an injected session/RecoveryService, `require_media`/`NO_SUITABLE_MEDIA`, `MEDIA_RESEARCH_TIMEOUT` (bounded via `asyncio.wait_for`), `QUALITY_GATE_FAILED` terminal-on-first-failure→BLOCK, the four-way `OrchestratorVerdict`, and full backward compatibility with the pre-existing in-process (no-session) fallback path. |
| `tests/test_unified_pipeline_cutover_authority.py` | 7 | Flag-on AUTHORITY (legacy decision/media/HOLD functions never invoked) + 5 real replays (A/D/F/G/H) run through the real, unmodified `run_content_cycle()` entry point, plus persistence-across-restart. |

Rewritten (obsolete tests replaced, not merely deleted): `tests/test_unified_pipeline_shadow_wiring.py`
— the old file proved the NOW-REMOVED "shadow hook alongside legacy" wiring; the new version proves
the actual current behavior (flag off → legacy; flag on + non-V8 → still legacy, unaffected).

Modified (additive fixture fix, not a behavior change): `tests/test_content_worker_cycle.py`'s
`test_source` fixture teardown now also deletes `recovery_jobs` rows for the test's own content
drafts before deleting the drafts themselves — the same guarded-delete convention every other
FK-referencing child table in that fixture already uses, needed because real committed-row tests
(this phase's own `test_unified_pipeline_cutover_authority.py`, and any future real-DB test
exercising the unified path) now write real recovery rows during the test.

## Regression suites re-run unmodified

| Suite | Result |
|---|---|
| `tests/test_editorial_pipeline_orchestrator.py` (pre-existing orchestrator tests) | pass, unmodified |
| `tests/test_editorial_pipeline_recovery.py` (pre-existing in-process recovery tests) | pass, unmodified |
| `tests/test_editorial_pipeline_instagram_adapter.py` | pass, unmodified |
| `tests/test_telegram_editorial_routing.py` (incl. the new additive `ambiguous` field) | pass, unmodified |
| `tests/test_router_media_integration.py` | 2 pre-existing failures (proven via `git stash` against the unmodified base — unrelated to this phase, both about an inline-keyboard button count), 0 new |
| `tests/test_visual_fallback_hold_repair_1.py` | pass, unmodified |
| `tests/test_content_worker_cycle.py` | pass (plus the one additive fixture fix) |
| `tests/test_editorial_delivery_mode.py` | pass, unmodified |
| `tests/test_story_continuity.py`, `tests/test_story_memory.py`, `tests/test_arxiv_story_clustering_repair.py` | pass, unmodified — zero Story Memory code touched this phase |

Full-repo sweep (`pytest tests/`, excluding 4 pre-existing, this-phase-unrelated collection errors
already present on the reviewed base SHA — missing `scripts.*` modules and one missing asset
manifest file): `49 failed, 6571 passed, 28 skipped` on the first pass. Every failure triaged
against a real `git worktree add` at the unmodified base SHA `9335426`: 44 pre-existing
(environment/ordering-sensitive, confirmed identical on base), 4 pure test-order/shared-DB-state
artifacts (pass in isolation on both branches), and exactly 1 real, new finding — a static
call-site guard (`tests/test_visual_single_brand_mark_call_sites.py`) that correctly flagged this
phase's new, deliberate `apply_master_news_branding()` caller (`telegram_integration.py`) as
needing explicit allowlisting. Root-caused and fixed by adding it to the guard's own
`_ALLOWED_IMPORTERS` with a full justification (not `services/media_finalizer.py` — that module's
own docstring says it is "not a router replacement," and `telegram_integration.py` is one, for this
scope). **`PRE_EXISTING_FAILURES = 48`, `NEW_FAILURES = 0`** after the fix — see the main report's
own §S for the full triage detail.

## Static checks

`ruff check` and `mypy --ignore-missing-imports` both run clean (zero new findings) on every
file this phase created or modified: `database/models/recovery_job.py`,
`services/editorial_pipeline/recovery_service.py`, `services/editorial_pipeline/telegram_integration.py`,
`services/editorial_pipeline/orchestrator.py`, `services/editorial_pipeline/contracts.py`,
`services/telegram_routing.py`, `worker/content_cycle.py`, and every new/modified test file. The
only mypy errors observed anywhere in these runs are 2 pre-existing, unrelated errors in
`services/story_delta_engine.py` (confirmed untouched by this phase via `git status`).
