# NEWSROOM STABILITY HARNESS CHECKPOINT

Scope: a deterministic/offline regression harness for the NEWS pipeline, built against committed HEAD `c308d45f6d55dc895eabe24b1901e1f99f855bbe` plus the working tree's accumulated post-acceptance fixes (multi-crop dedup, UPDATE early short-circuit, acquisition evidence fix, Research stale-reuse fix, generic-prefix entity normalization — all confirmed present, see §0). Not committed, not deployed. Architecture freeze respected throughout: no video work, no source-pack integration, no Story Memory architecture change, no second workflow engine.

## 0. Baseline check

- Branch: `feature/phase19-editorial-depth-upgrade`, HEAD: `c308d45f6d55dc895eabe24b1901e1f99f855bbe` (unchanged this phase).
- Working tree still carries exactly the 13 previously-modified files from the prior phase (`capabilities/executor.py`, `services/analysis_reuse.py`, `services/content_draft_service.py`, `services/evidence_package.py`, `services/story_duplicate_guard.py`, `services/story_memory.py`, `worker/content_cycle.py`, and their 6 corresponding test files) — the 5 post-acceptance fixes are confirmed present and untouched by this phase.
- This phase's changes are additive only: `scripts/run_news_golden_suite.py`, `tests/fixtures/news_golden_cases.json`, `tests/golden/` (new package), `tests/test_news_golden_suite.py`, and one appended section (§15) to `docs/13_Testing_Strategy.md`. No production file under `capabilities/`, `services/`, `worker/`, `bot/`, or `workflows/` was modified.

## A. Existing infrastructure reused

Two research passes over `scripts/`, `tests/`, and `docs/` (not re-summarized here) found a mature but scattered set of replay/test infrastructure. Reused directly, with **zero new parallel framework**:

- `tests/fakes/fake_gateway.py::FakeLLMGateway` and the sibling `tests/fakes/*` doubles — available for any future orchestration-level (fake-gateway) golden case; not needed for this phase's chosen cases (see §C/§E).
- `tests/test_content_generation_integration.py::_real_capability_registry()` — the established "real registry + fake gateway + real DB" pattern; documented as the reuse point for a future orchestration-level copywriting case (see §J).
- `tests/fixtures/phase20_human_reviewed_cases.json` + `tests/test_story_memory_human_reviewed_calibration.py` — the direct precedent this harness's fixture/runner split is modeled on (`_load()`, `_seed_story()`, parametrized per-case tests). Extended in spirit across all 7 categories, not copied verbatim.
- `tests/test_evidence_package_degradation.py::_seed_acquisition`/`_seed_event` and `tests/test_analysis_reuse.py`'s `_make_acquisition` pattern — the seeding convention `tests/golden/runners.py::_run_stale_reuse_case`/`run_update_case_db` follow exactly (build via SQLAlchemy constructor, `add()` + `flush()`, rely on `conftest.py`'s `db_session` savepoint-rollback fixture, never `commit()`).
- `tests/test_router_media_integration.py::_fake_candidate()` — imported directly (not re-implemented) by `tests/golden/runners.py` for every media case.
- `worker/content_cycle.py::_compute_within_event_duplicate_flags`, `_normalize_image_origin`, `_select_top_ranked_image_candidates`, `_MAX_ROUTER_IMAGES` — private but already-established cross-file-reused helpers; imported directly.
- `scripts/validate_architecture.py` — confirmed it excludes `tests/` and `docs/` entirely (`EXCLUDED_DIR_NAMES`), so the new harness code is exempt from its forbidden-import rules as long as no new non-test production module is added (none was).
- `scripts/phase20_story_memory_replay.py` — reviewed as the most mature prior "replay against a disposable/real DB" script; **not reused directly** (it spins up a disposable Postgres container and replays multi-thousand-event windows — heavier than this harness needs). Its `_load()`/fixture-JSON convention was reused; its container-lifecycle machinery was not.
- The Phase 23.1J–1N `_phase23_*_golden_replay.py` scratch scripts — reviewed as prior art for the "replay real serialized candidates through a production ranking function" pattern (e.g. `_phase23_1n1_corpus_replay.py` for image-relevance re-ranking); confirmed this project has repeatedly reinvented ad hoc versions of exactly this harness across phases 17/18/19/20/23, which is the direct motivation for making this one permanent rather than another scratch script.
- **No CI configuration exists anywhere in the repository** (confirmed: no `.github/workflows/`, no other CI config). Per the phase brief's own instruction, no CI system was created from scratch — see §I.

## B. Golden corpus

`tests/fixtures/news_golden_cases.json` — **27 cases** across 7 categories:

| Category | Count | Cases |
|---|---|---|
| evidence_acquisition | 4 | google_news_wrapper_unresolved, bad_garbage_linkedin_interstitial, good_full_article_control, snapdragon_stale_reuse_evidence_supersedes |
| story_memory | 4 | vk_earnings_duplicate_entity_normalization, cd_projekt_layoffs_known_limitation, zoom_vulnerability_cross_publisher_same_story, gta_vi_negative_control_distinct_events |
| update | 2 | honor_robot_phone_update_repetition, update_unresolved_root_fail_closed |
| quote | 3 | discord_fragment_quote_not_self_contained, meaningful_quote_positive_control, quote_body_overlap_dedup |
| copywriting | 3 | v85_uncertainty_filler_regression_v86_fix, us_ai_productivity_weak_evidence_gating, v86_material_uncertainty_survives_control |
| media | 8 | honor_wordpress_photon_dedup, guardian_crop_pair_dedup, sf_estate_album_dedup, cnet_apple_icloud_album_dedup, hero_plus_avatar_exclusion, hero_plus_tiny_icon_exclusion, album_cap_three_distinct_images, first_image_fails_second_succeeds |
| presentation | 3 | text_news_footer_no_preview, media_group_source_button_attached, update_media_reply_routing |

By `failure_class`: **17 real_regression** (a confirmed real defect, now fixed, pinned), **8 good_control**, **1 negative_control** (GTA VI/6), **1 known_limitation** (CD Projekt). A second case (Zoom cross-publisher) was *originally written* as `real_regression` and was reclassified to `known_limitation` mid-build — see §J for why; this is itself evidence the harness works as intended (it caught its own author's optimistic assumption).

Every `real_regression`/`known_limitation` case carries a `provenance` field naming the exact doc/report/test and, where available, real event/draft/story IDs, real URLs, real perceptual hashes, or real prompt-file excerpts — no fabricated IDs. Two cases (`good_full_article_control`, `meaningful_quote_positive_control`) are explicitly labeled representative-synthetic controls (no single real production ID attached), consistent with the brief's own allowance for controls.

## C. Harness architecture

- **Entry point**: `python scripts/run_news_golden_suite.py` (`--case ID`, `--category NAME`, `--list`, `--verbose`). A thin wrapper around `pytest tests/test_news_golden_suite.py` — a small `_ResultCountingPlugin` counts pass/fail and the script prints `GOLDEN SUITE: N/N PASS` with a non-zero exit on any failure or on zero matched cases.
- **Fixture format**: `tests/fixtures/news_golden_cases.json` — one `cases` list, each entry validated by `tests/golden/loader.py` (required keys, valid `failure_class`/`kind` enums, no duplicate `case_id`).
- **Production functions reused** (no case reimplements business logic):
  - `services/article_acquisition.py::is_google_news_redirect_host`, `resolve_canonical_url`, `resolve_meta_refresh_url`, `estimate_substantive_char_count`, `classify_acquisition_status`.
  - `services/analysis_reuse.py::_acquisition_postdates` (DB-backed).
  - `services/story_memory.py::extract_story_signature`, `score_candidate`, `_LOW_THRESHOLD`/`_HIGH_THRESHOLD` (imported constants, not reimplemented).
  - `services/content_quality_gates.py::check_update_not_repeating_root`, `check_quote_is_self_contained`, `check_quote_has_attribution`.
  - `services/story_duplicate_guard.py::check_update_would_fail_closed` (DB-backed).
  - `services/quote_verification.py::verify_quote`; `services/text_normalization.py::fuzzy_phrase_contains`, `token_overlap_ratio`.
  - `services/editorial_treatment.py::_is_weak_evidence`.
  - `services/news_telegram_presentation.py::build_v81_news_body`, `render_v81_news_card_html`.
  - `worker/content_cycle.py::_compute_within_event_duplicate_flags`, `_select_top_ranked_image_candidates`; `services/image_quality.py::resolution_band`; `services/image_preview_notifier.py::build_rich_media_plan`.
  - `services/story_telegram_delivery.py::determine_reply_target`; `bot/keyboards/image_preview.py::build_source_only_keyboard`.
- **Fake gateway strategy**: no case in this corpus calls the LLM gateway at all. The `copywriting` category deliberately stays in the "deterministically testable" tier (prompt-file structural assertions + evidence-gating function calls) rather than invoking `FakeLLMGateway` through the real capability chain — see §D and §J for why, and what an orchestration-level case would need.
- **Two identified testability seams**, both narrow and disclosed rather than silently worked around:
  1. `quote_body_overlap_dedup`'s "already rendered elsewhere → suppressed" decision has no single named production function; the case approximates it via the same `fuzzy_phrase_contains()` primitive `verify_quote()` itself is built from, rather than inventing new logic. Documented as an approximation, not a verified call-site match, in §J.
  2. `story_memory` cases classify into a 3-bucket `outcome_bucket` (`new_story_or_related` / `uncertain_match` / `confident_same_story`) via the real imported `_LOW_THRESHOLD`/`_HIGH_THRESHOLD` constants rather than running the full async, DB-backed `match_story()` — this keeps 4 cases fast and DB-free but does not exercise the finer confident-type disambiguation (`story_update` vs. `supporting_source` vs. `semantic_duplicate`) that only `match_story()` itself computes. Acceptable because every case here only needs the coarser 3-way bucket to state its invariant; documented as a scope choice in §J.

## D. Invariants

No case asserts exact LLM prose. Every `expected` block in the fixture is evaluated by the generic comparator `tests/golden/invariants.py::evaluate_expectations()`, which supports exact-equality, `__in` (membership), `__contains`/`__not_contains` (substring), and `__gte`/`__lte` (numeric bound) — deliberately a thin comparison DSL, not a registry of bespoke semantic checks; the actual semantics live entirely in the production functions listed in §C. Representative invariants actually encoded, one per category:

- **Evidence**: `substantive_status_downgraded_from_full_text` (a reported-FULL_TEXT interstitial must reclassify once boilerplate is excluded); `stale_result_reused: false` under `article_acquisition_mode=enforce` with a postdating acquisition.
- **Story**: `entity_overlap`/`combined`/`outcome_bucket` bounds (confident-match floor for VK, ceiling for CD Projekt/GTA).
- **Update**: `root_repetition_check_passes: false` for a near-duplicate UPDATE; `would_fail_closed: true` for an unresolved root under `enforce`.
- **Quote**: `is_self_contained: false` for the Discord fragment; `verify_quote_passes`/`has_attribution` independently checked so a fragment's *other* passing gates stay visible, not masked by one failing gate.
- **Copy**: `v86_contains_never_write_enumerates_missing_details: true` / `v86_contains_never_repeat_phrases_framing: false` (structural prompt presence/absence, not prose quality).
- **Media**: `duplicate_flags` list per candidate (positional, matches input order); `eligible_candidate_ids`; `media_group_size` bounds.
- **Presentation**: `footer_present_exactly_once`; `button_label`/`button_url` exact match; `reply_to_message_id`/`decision` exact match.

## E. Example regression traces

**Snapdragon** (`snapdragon_stale_reuse_evidence_supersedes`): seeds a real-shaped `NewsEventArticleAcquisition` (FULL_TEXT, created "now") against a `news_analysis_result_timestamp` of `2026-08-13T09:22:28Z` (the real logged Research-call time) under `article_acquisition_mode=enforce`, calls the real `_acquisition_postdates()` directly. Asserts `stale_result_reused: false` — pins the exact fix from the prior phase (`services/analysis_reuse.py`'s staleness check).

**VK** (`vk_earnings_duplicate_entity_normalization`): the exact real titles from `tests/test_story_memory.py::_VK_TITLE_1`/`_VK_TITLE_2`, run through the real, unmodified `score_candidate()`. First run against the fixture's initial (paraphrased, not exact) titles produced `entity_overlap=0.0` instead of the expected `1.0` — a harness bug, not a product bug, caught immediately by the suite itself; fixed by substituting the byte-exact real titles. After the fix: `entity_overlap=1.0`, `combined≈0.97`, `outcome_bucket="confident_same_story"` — matches the checkpoint's own measured result exactly.

**Media duplicate** (`sf_estate_album_dedup`): 3 real phashes/URLs from the real $70M SF-estate Guardian album, run through the real `_compute_within_event_duplicate_flags()`. Asserts `duplicate_flags == [false, true, true]` — rank 1 survives, ranks 2–3 (Hamming distance 14–28, well above the old ≤10 threshold this session's predecessor phase removed) are correctly flagged via the same-origin signal alone.

**Quote failure** (`discord_fragment_quote_not_self_contained`): the real quote text (`"thoughtfully reviewing"`), real speaker (`"Discord"`), and real source sentence from the forensic report, run through the real `verify_quote()`, `check_quote_has_attribution()`, and `check_quote_is_self_contained()`. Asserts `verify_quote_passes: true`, `has_attribution: true`, `is_self_contained: false` — reproduces the exact real gap (a verbatim, attributed, but grammatically incomplete fragment) with all three gates visible independently, not collapsed into one boolean.

## F. Determinism

Full suite run twice, back to back, no code changes between runs:

- Run 1: `37 passed in 12.56s` → `GOLDEN SUITE: 37/37 PASS`
- Run 2: `37 passed in 12.65s` → `GOLDEN SUITE: 37/37 PASS`

Identical pass/fail classification for every case both times (timing variance only, as expected for a purely CPU/local-DB-bound suite with zero external calls).

## G. Validation

- **Harness self-tests** (`tests/test_news_golden_suite.py`, 10 tests): case-ID uniqueness, category filtering, `KeyError` on an unknown case, malformed-fixture handling (missing required key, duplicate `case_id`, invalid `failure_class` — all raise `MalformedFixtureError`), the known-limitation-must-stay-honest convention check, and 3 direct tests of `evaluate_expectations()`'s comparison DSL. All passing.
- **Golden suite itself**: 27/27 golden cases passing (37/37 including self-tests), confirmed deterministic across 2 runs (§F). No real Telegram send anywhere (no case constructs a `Bot`/`AsyncMock` at all — every case calls a pure or DB-only production function directly). No paid LLM call anywhere (no case imports or calls `LLMGateway`/`FakeLLMGateway`).
- **Ruff** (`tests/golden/`, `tests/test_news_golden_suite.py`, `scripts/run_news_golden_suite.py`): one real finding (2 unused imports in `runners.py` from an earlier draft), fixed; now clean.
- **mypy**: run against `scripts/run_news_golden_suite.py` (clean) — the one new non-test file. `tests/golden/*.py` were not mypy-checked, consistent with this repository's own established convention throughout every prior phase this session (mypy has only ever been run against production `services/`/`capabilities/`/`worker/` files, never `tests/*.py`; running it against `tests/golden/` additionally hits a real, pre-existing mypy module-resolution ambiguity between `golden.*` and `tests.golden.*` since `tests/` itself has no `__init__.py` — a structural, harness-adjacent finding, not a defect this phase introduced or is authorized to fix, since it would mean adding `tests/__init__.py` across the whole existing test tree).
- **`scripts/validate_architecture.py`**: clean, 0 forbidden-dependency violations (expected — `tests/` is excluded from every rule, and no new production module was added).
- **Broader existing regression suites** (`test_story_memory.py`, `test_story_duplicate_guard.py`, `test_analysis_reuse.py`, `test_evidence_package_degradation.py`, `test_router_media_integration.py`, `test_content_cycle_story_delivery.py`, `test_content_quality_gates.py`, `test_copywriting_v86_uncertainty_fix.py`, `test_news_telegram_presentation_v81.py`, `test_telegram_editorial_routing.py` — this run deliberately did NOT include the new `tests/test_news_golden_suite.py`, to give a clean before/after-free baseline) run to confirm zero interaction between the new harness's imports (several of which import private helpers directly, e.g. `_fake_candidate`, `_compute_within_event_duplicate_flags`) and the existing suites. Result: `234 passed, 1 failed, 51 errors`. Both anomalies confirmed pre-existing and unrelated to this phase: (1) `test_evidence_package_degradation.py::test_build_evidence_package_raises_when_table_missing` fails identically in complete isolation (`pytest tests/test_evidence_package_degradation.py::test_build_evidence_package_raises_when_table_missing` alone) — an environment/migration-state mismatch (the test expects an unmigrated table; this dev DB already has the migration applied), unrelated to any file this phase touched; (2) the 51 `ERROR`s (never `FAILED`) are exclusively in the same `factory`-based (non-transactional) tests in `test_story_duplicate_guard.py`/`test_router_media_integration.py`/`test_content_cycle_story_delivery.py` whose "teardown-only FK cleanup" pattern was independently discovered, root-caused, and confirmed pre-existing via `git stash` comparison in the immediately prior phase's own checkpoint (`docs/entity_normalization_fix_checkpoint.md`) — and since this particular run excluded the new golden-suite file entirely, these 51 errors cannot have been caused by anything built this phase. No production file was touched this phase, so no regression was structurally possible; this run is a confirmation, not a risk mitigation.

## H. Definition of Stable

**Offline**:
- 100% of required (`real_regression`/`good_control`/`negative_control`) golden cases passing; `known_limitation` cases document current behavior, never silently marked fixed.
- 0 `scripts/validate_architecture.py` violations.
- Ruff clean; mypy clean on changed production scope.
- No known severe regression hidden as PASS (enforced structurally: a `known_limitation` case whose `expected` block doesn't document the limitation fails the harness's own `test_known_limitation_cases_are_not_silently_marked_fixed` self-test).

**Live rolling quality** (unchanged from the prior acceptance-canary criteria, restated here for a single reference point): over a meaningful recent real sample — ≥95% GOOD, 0 severe evidence failures, 0 confirmed duplicate independent-root deliveries, 0 meaningless/contextless rendered quotes, 0 obvious same-asset duplicate images in albums, 0 destination violations, 0 malformed Telegram cards, 0 broken source-button behavior. For UPDATE/quote (rare categories), distinguish PASS / FAIL / **NOT LIVE-VALIDATED** rather than manufacturing traffic — a small sample is never sufficient for permanent certification on its own.

## I. Developer workflow

```
unit/integration tests
    ↓
golden NEWS regression suite   (python scripts/run_news_golden_suite.py)
    ↓
shadow/targeted validation     (only where §J says the golden suite cannot prove it)
    ↓
live acceptance
    ↓
deploy
```

Documented as the permanent project rule in `docs/13_Testing_Strategy.md` §15 (reused the existing testing-strategy doc rather than creating a new policy doc, per instruction). No CI config exists in this repository today; none was created this phase (the brief's own instruction: "do not create a complex CI system if none exists"). The golden suite is runnable locally in ~13 seconds with zero setup beyond the existing `db_session` test-DB fixture already required by the rest of the suite — that alone makes it practical as a pre-commit/pre-deploy local gate without any CI investment.

## J. Remaining limitations

What this offline harness **cannot** prove, honestly:

- **Nuanced LLM prose quality** — whether a real model call actually produces natural, non-filler, well-hedged text. The `copywriting` category proves data/prompt-structure/evidence-gating invariants only (prompt file contains/lacks specific framing; a weak-evidence signal is correctly detected; a deterministic collapse layer correctly preserves a material ending) — never that a live GPT/Claude/Gemini call will honor those rules. This requires live/shadow validation, unchanged from every prior phase's own disclosed limitation.
- **Naturally occurring quote selection** — whether a real model chooses a *good* quote from a real article in the first place; this harness only proves that a *given* quote passes/fails the deterministic gates correctly.
- **The reuse-vs-enforce fix's full orchestration path** — `snapdragon_stale_reuse_evidence_supersedes` proves `_acquisition_postdates()`'s own staleness logic directly; it does not run `capabilities/executor.py::_try_reuse()` end-to-end with a real `CapabilityExecutor`, so a future regression in the *wiring* between `_try_reuse()` and this staleness check (as opposed to the staleness check's own logic) would not be caught by this specific case. `tests/test_analysis_reuse.py`'s own existing 6-scenario suite (from the prior phase) already covers this more completely and continues to run as part of "existing regression suites," not superseded by this harness.
- **The `quote_body_overlap_dedup` case's approximation** (§C) — no single named production function for "quote already rendered elsewhere → suppress" was located; the case reuses `fuzzy_phrase_contains()` (the real primitive `verify_quote()` is built from) as a structural stand-in. If the real suppression decision ever diverges from plain fuzzy-phrase-containment, this case would not catch that divergence.
- **The Story Memory `outcome_bucket` simplification** (§C) — 4 cases classify via imported thresholds rather than the full `match_story()`, so they do not exercise the fine 3-way confident-type disambiguation, RELATED_STORY-vs-NEW_STORY distinction, or any DB-candidate-pool-size effects (`STORY_MATCH_CANDIDATE_LIMIT`, preselection). `tests/test_story_memory_human_reviewed_calibration.py`'s existing DB-integration suite already covers the full `match_story()` path realistically and continues to run unmodified.
- **A pre-existing mypy tests-package ambiguity** (§G) — not introduced by this phase, but confirmed for the first time by attempting to mypy-check `tests/golden/`; documented, not fixed (fixing it would mean adding `tests/__init__.py` across the entire existing test tree, out of this phase's narrow scope).
- **No CI wiring** — the suite is local-only today; see §I.
- **A newly-surfaced second finding, not a harness gap**: building `zoom_vulnerability_cross_publisher_same_story` found that the real scorer, run against the real headline pair, would *not* have confidently matched them from title/entity text alone (`combined=0.05`) — independent of the already-known `story_memory_mode=off` config-gate root cause. This is a genuine, previously-undocumented Story Memory precision gap for this specific pair, reclassified honestly as `known_limitation` rather than forced to pass; **out of scope to fix this phase** (architecture freeze), but now permanently pinned for whenever it is picked up.

## K. Recommendation

`STABILITY HARNESS READY`

The golden suite is real, deterministic, reuses production code exclusively, runs in ~13 seconds with zero external dependencies, and is already wired to the documented developer workflow. It caught one real harness-authoring bug (the VK title mismatch) and one real, previously-undisclosed product limitation (the Zoom pair's title-level score) during its own construction — direct evidence it does what it was built to do. The disclosed limitations in §J are genuine and should inform, not block, adoption: they are exactly the boundary between "offline golden suite" and "shadow/live validation" the phase brief itself asked to make explicit, not gaps in what was promised.

Not committed. Not deployed. Video and source-pack work not resumed. No live canary started.
