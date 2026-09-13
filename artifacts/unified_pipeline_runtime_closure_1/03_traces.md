# Candidate-selection / same-asset / no-visual-resolution / recovery-lifecycle traces (§44)

## A. Foldable-iPhone candidate-selection trace

Test: `tests/test_unified_pipeline_media_truthfulness_replay.py::
test_foldable_iphone_replay_exact_candidate_present_wins_over_wrong_and_generic` - PASSED.

Inputs: candidate A (ordinary iPhone, OFFICIAL_PRESS_ASSET, 6000x4000, wrong subject), candidate B
(contextual Apple logo, safe fallback), candidate C (exact foldable, 800x600, low resolution).

Trace:
1. `classify_subject_match(A, intent)` -> `MISMATCH` (caption text matches `must_not_imply`).
2. `classify_subject_match(C, intent)` -> `EXACT_SUBJECT` (caption confirms `must_show=["foldable design"]`).
3. `is_selectable(A)` -> `False` (MISMATCH). `is_selectable(C)` -> `True`.
4. `score_candidate(C)` = 60 (EXACT) + 14 (Tier3) + 10 (freshness) + 2 (quality, low-res) = 86.
5. `MediaSelectionResult.selected` = C (`candidate-c-exact-foldable`).
6. Assertion: `WRONG_IPHONE_IMAGE_SELECTED = False`. **PASS.**

## B. Same-asset invariant trace

Test: `tests/test_unified_pipeline_same_asset_invariant.py::
test_same_asset_invariant_renders_the_winner_never_the_pre_ranked_candidate` - PASSED.

Trace:
1. `PRE_MEDIA_CANDIDATE = A` (legacy rank 1, `telegram_file_id="FILE_ID_A_WRONG"`).
2. `MEDIA_RESEARCH_WINNER = B` (`telegram_file_id="FILE_ID_B_CORRECT"`), named ONLY via
   `image_candidate_record_id` in `MediaSelectionResult.selected`.
3. `_make_render_callback()`'s `_render(...)` receives `media_selection` (winner=B) directly -
   never A's pre-captured identity.
4. `resolve_selected_media_asset(media_selection, legacy_candidates_by_id={A, B})` looks up B's
   record ONLY (`image_candidate_record_id` match), never A's.
5. Returned `photo_input == "FILE_ID_B_CORRECT"`. **A never leaks in.**

## C. No-visual-resolution-failure trace (Case A / R5)

Test: `tests/test_unified_pipeline_same_asset_invariant.py::
test_r5_missing_local_storage_no_file_id_holds_never_text_only` - PASSED.

Trace:
1. Selected candidate has a legacy record with `telegram_file_id=None` and unreadable local bytes
   (`read_candidate_bytes` monkeypatched to `None`, simulating a real expired/missing storage row).
2. `resolve_selected_media_asset()` returns `failed=True`.
3. `_render(...)` returns `MediaResolutionFailure(candidate_id=..., detail=...)` - NOT `(None, html)`.
4. `run_editorial_production_pipeline()` maps this to `RecoveryReasonCode.MEDIA_RESOLUTION_FAILED`
   via `_recover()` - a real, durable, bounded-retryable recovery, never an ordinary text send.

## D. Recovery lifecycle trace (platform-scoped + concurrency-safe)

Test: `tests/test_unified_pipeline_recovery_concurrency_and_platform_scoping.py` (both tests) - PASSED.

Trace (platform scoping):
1. `create_or_retry(draft_id, TELEGRAM, ...)` -> row T (attempt_count=1).
2. `create_or_retry(draft_id, INSTAGRAM, ...)` -> row I (attempt_count=1, a DIFFERENT row - before
   this phase, the unscoped `find_open_recovery(draft_id)` lookup could have found and incremented
   row T here by mistake).
3. A second Telegram failure increments row T only (`attempt_count=2`); row I is untouched.

Trace (concurrency):
1. Row `winner` is inserted directly (simulating a concurrent transaction that committed first).
2. `create_or_retry()` is called with `find_open_recovery()` patched to report "nothing open" on
   its first call only (simulating the real race window).
3. The real INSERT this triggers collides with the real DB-level partial unique index
   `ix_recovery_jobs_open_lifecycle_identity` -> Postgres raises `IntegrityError`.
4. The real `except IntegrityError` branch in `create_or_retry()` re-reads and increments `winner`
   instead of crashing or leaving a duplicate open row.
5. Final state: exactly one open row for `(content_draft_id, platform)`, `attempt_count=2`.
