# Changed-file list and test summary (§44)

## Changed files (base `839edb2`)

**New implementation files:**
- `services/editorial_pipeline/media_asset_resolver.py` - SelectedMediaAsset resolution (§7)
- `services/editorial_pipeline/subject_extraction.py` - generic MediaIntent subject extractor (§9)
- `services/editorial_pipeline/recovery_execution_policy.py` - explicit Option-B disclosure (§24)
- `database/migrations/versions/c48f6a1e9d02_recovery_jobs_concurrency_and_media_.py` - additive migration (§22/§23)

**Modified implementation files:**
- `services/editorial_pipeline/contracts.py` - `SelectedMediaAsset`, `MediaResolutionFailure`,
  `MEDIA_RESOLUTION_FAILED`, `STRUCTURED_CONTENT_PRESENT` rename
- `services/editorial_pipeline/orchestrator.py` - `RenderCallable` now passes `media_selection`;
  handles `MediaResolutionFailure`; final pre-transport assertion (defense in depth)
- `services/editorial_pipeline/telegram_integration.py` - the core fix: bounded candidate pool,
  no pre-selection byte capture, real asset resolution at render time, final pre-transport
  visual assertion
- `services/editorial_pipeline/media.py` - `build_visual_intent_from_evidence` uses the new extractor
- `services/editorial_pipeline/quality.py` - `FACT_SUPPORT` -> `STRUCTURED_CONTENT_PRESENT` rename
- `services/editorial_pipeline/recovery_service.py` - platform-scoped `find_open_recovery`,
  concurrency-safe `create_or_retry` (SAVEPOINT + IntegrityError recovery)
- `services/editorial_pipeline/platforms/instagram.py` - `FACT_SUPPORT` reference updated
- `services/editorial_pipeline/shadow.py` - render-callback signature updated (3rd param)
- `services/media_candidate_scoring.py` - `is_selectable()` excludes `EDITORIAL_REVIEW_REQUIRED`
- `services/media_research_selection.py` - real rejection-reason logging for rights exclusions
- `services/media_web_discovery.py` - `hits[:max_results_per_query]` bound enforced at the call site
- `database/models/recovery_job.py` - `MEDIA_RESOLUTION_FAILED` enum value, partial unique index

**New test files:**
- `tests/test_unified_pipeline_media_asset_resolver.py`
- `tests/test_unified_pipeline_same_asset_invariant.py`
- `tests/test_unified_pipeline_recovery_concurrency_and_platform_scoping.py`
- `tests/test_unified_pipeline_recovery_execution_policy.py`
- `tests/test_unified_pipeline_subject_extraction.py`
- `tests/test_unified_pipeline_bounded_web_discovery.py`

**Modified test files:** `test_editorial_pipeline_orchestrator.py`, `test_editorial_pipeline_shadow.py`,
`test_media_candidate_scoring.py`, `test_media_research_selection.py`,
`test_unified_pipeline_cutover_authority.py`, `test_unified_pipeline_media_truthfulness_replay.py`,
`test_unified_pipeline_orchestrator_cutover.py` (all: `RenderCallable` 3rd-param signature fix
and/or `EDITORIAL_REVIEW_REQUIRED` fixture-default fix - see report §W for full rationale per file).

**Total diff**: 19 tracked files changed (1097 insertions, 522 deletions) + 10 new files.

## Test summary

| Batch | Files | Result |
|---|---|---|
| Media/scoring/selection/rights (first pass) | 5 files | 44 passed |
| Orchestrator (both) | 2 files | 16 passed |
| Instagram/shadow/recovery adapters | 4 files | 19 passed |
| Authority/replay (7 real end-to-end replays through `run_content_cycle`) | 1 file | 7 passed |
| Shadow/brand-mark/truthfulness | 3 files | 10 passed |
| Recovery concurrency + platform scoping (NEW) | 1 file | 2 passed |
| Media asset resolver (NEW) | 1 file | 5 passed |
| Same-asset invariant + R4/R5 (NEW) | 1 file | 4 passed |
| Subject extraction (NEW, §9/§32) | 1 file | 16 passed |
| Bounded web discovery (NEW, §35) | 1 file | 3 passed (+10 pre-existing in same file's sibling) |
| Recovery execution policy (NEW, §24) | 1 file | 3 passed |
| **Full combined regression (32 files)** | | **197 passed, 0 failed** |
| Legacy router-media path (flag-off proof) | `test_router_media_integration.py` | 68 passed, 2 pre-existing failures (unrelated - keyboard-count assertion, present before this phase) |

**NEW_FAILURES = 0** across every batch. The 2 `test_router_media_integration.py` failures were
already present on the base branch (confirmed: neither touches any file this phase modified) and
are unrelated to this phase's changes (a keyboard-button-count assertion in the legacy NINJA PULSE
CTA path).

## Lint / type check

- `ruff check` on every new/modified non-test source file: clean (one pre-existing unused-import
  finding in `telegram_integration.py` and 6 in new test files, all fixed).
- `mypy --ignore-missing-imports` on every significantly modified module: clean except pre-existing,
  unrelated errors in `services/story_delta_engine.py` (not touched by this phase). One real new
  type error in `telegram_integration.py` (a `str | None` passed where `str` was expected) was
  found and fixed during this check.
