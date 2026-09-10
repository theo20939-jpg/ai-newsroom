# FOUNDER-VISUAL-V8-TEST-CONTRACT-CATCHUP-1 - report

Test-only catch-up for the already Founder-approved NINJA PULSE Visual V8 release.

    V8_RELEASE_SHA = d0a03773bebc98c6b71edb67fe368b85472e2d6b   (unchanged)
    approved visual dev state = 8e690c5
    RUNTIME_FILES_CHANGED = 0

No runtime, renderer, RenderEvidence, VisualSpec-runtime, Dockerfile, dependency or
asset change. No production mutation. Story Continuity untouched.

## A. Stale tests identified

Reproduced against the approved V8 implementation on
`feature/launch-readiness-visual-recap-parallel-1` (V8 runtime = `8e690c5`). Exactly
three visual tests failed by encoding retired pre-V8 behaviour - the same three the
FOUNDER-VISUAL-V8-FINAL-RELEASE-PREP-1 report section K classified as
"stale, superseded by approved V8":

1. `tests/test_visual_single_brand_mark_contract.py::test_news_light_photo_has_exactly_one_mark`
2. `tests/test_visual_single_brand_mark_contract.py::test_breaking_places_exactly_one_brand_mark`
3. `tests/test_visual_spec_v2_activation.py::test_final_matrix_all_pass_no_placement_zone_partial`

No other visual test was proven stale (the broad visual/spec/director/founder-visual
suite otherwise passes against V8 - section F).

## B. Old expectations / C. Approved V8 expectations

### 1. `test_news_light_photo_has_exactly_one_mark` -> `test_news_light_photo_mark_only_stays_at_or_below_one_mark`

* **OLD_EXPECTATION**: `apply_master_news_branding(flat 230-grey photo)` always yields
  `_brand_mark_count(decision) == 1`.
* **WHY_RETIRED**: pre-V8, `apply_master_news_branding` defaulted to the FUSED
  signature (edge line + pulse + mark) which the placement scorer always positioned
  on a flat frame. FOUNDER-VISUAL-POLISH-2 §2 changed the NEWS default to
  `SIGNATURE_STYLE_MARK_ONLY` - one small canonical NNJ in the least-busy safe
  corner, or NONE when the low-opacity red mark cannot be placed with enough
  contrast. On a flat near-white frame the red mark scores below
  `_VISIBILITY_MIN_DISTANCE` in every corner and the decision resolves to
  `degradation_mode == "no_overlay"`, 0 marks - the same safe-suppression the DATA
  source path already uses.
* **V8_EXPECTATION**: `FINAL_VISIBLE_NNJ_COUNT <= 1` on the final media - never a
  fixed count, never a fixed corner. A flat near-white frame -> 0, and that must be a
  coherent `no_overlay` suppression with the upper-mark slot OMITTED (mutual
  exclusion), never an accidental drop and never two. The "mark IS placed -> exactly
  one" side stays covered by the adjacent, untouched
  `test_news_dark_photo_has_exactly_one_mark`.
* **FOUNDER_APPROVAL_SOURCE**: FOUNDER-VISUAL-POLISH-2 (NEWS default
  `signature_style="mark_only"`; Founder verdict NEWS=FAIL on the old fused
  signature). The V8 evidence contract `logo_count in (0, 1)` is asserted by
  `tests/test_founder_visual_polish_2.py::test_news_evidence_placement_zone_not_applicable`.
  This phase spec §4: "Safe source-infographic suppression may result in zero added
  mark ... The invariant is about the FINAL rendered media: FINAL_VISIBLE_NNJ_COUNT
  <= 1 ... Do not reinterpret this into a requirement for a fixed logo location."

### 2. `test_breaking_places_exactly_one_brand_mark`

* **OLD_EXPECTATION**: BREAKING routes through `select_master_news_branding()` exactly
  once (spied via `monkeypatch.setattr(brand_renderer, "select_master_news_branding", ...)`),
  reusing the NEWS fused lower signature.
* **WHY_RETIRED**: FOUNDER-VISUAL-POLISH-2 §2 rewrote `render_breaking_frame()` to
  composite BREAKING's OWN board-derived lower-media NINJA PULSE plus one restrained
  grey NNJ watermark (`_draw_breaking_watermark()`, geometry from
  `services/nnj_board_metrics.py::BREAKING`). It no longer calls
  `select_master_news_branding()` and `services/brand_renderer` no longer exports that
  symbol -> the monkeypatch target does not exist -> `AttributeError`.
* **V8_EXPECTATION**: `render_branded_media(BREAKING, ...)` succeeds;
  `derive_breaking_render_evidence(...).logo_count == 1` (exactly one canonical NNJ on
  the final media); `render_breaking_frame`'s body composites `_draw_breaking_watermark(`
  and contains no `select_master_news_branding(`, no second `rasterize_nnj_mark(`, no
  `_paste_svg_mark(` / `_paste_logo(`; and `brand_renderer` has no
  `select_master_news_branding` attribute.
* **FOUNDER_APPROVAL_SOURCE**: FOUNDER-VISUAL-POLISH-2 §2 (BREAKING rewritten with its
  own lower-media pulse + corner mark), FOUNDER-VISUAL-BOARD-REBUILD-6
  (`_draw_breaking_watermark`), FOUNDER-VISUAL-FINAL-BOARD-MATCH-7 /
  -CANVAS-COMPOSITION-CORRECTION-8 (`pulse-breaking-v7-board`). Covered by
  `tests/test_founder_visual_polish_2.py::test_breaking_is_distinct_from_news_lower_media_pulse`
  and `tests/test_founder_visual_board_rebuild_6.py::test_breaking_bakes_no_headline_and_at_most_one_nnj`.

### 3. `test_final_matrix_all_pass_no_placement_zone_partial` (DATA-photo sub-case)

* **OLD_EXPECTATION**: with `telegram_data` v1 ACTIVE (`font_size_max: 88,
  font_size_min: 48`), a DATA render from a non-infographic source (FULL_DATA_CARD) is
  SPEC_MATCH=PASS because the compact corner stat font fits `[48, 88]`.
* **WHY_RETIRED**: FOUNDER-VISUAL-BOARD-ALIGNMENT-1 replaced the compact corner stat
  with the generated DATA hero-metric card; FOUNDER-VISUAL-CANVAS-COMPOSITION-CORRECTION-8
  put the hero on the near-square 1280x1172 board-media canvas, so its
  board-proportional primary value font (`0.163 h` cap) fits at ~270 - far outside
  `[48, 88]`. `telegram_data` v1's range describes the retired treatment.
* **V8_EXPECTATION**: the DATA *source-preserving* MINIMAL render is still evaluated
  against `telegram_data` v1 (unchanged - MINIMAL skips the font check). The DATA
  *generated hero* (FULL_DATA_CARD) render is evaluated against the truthful V8
  `telegram_data` candidate `_V8_DATA_HERO = {font_size_max: 300, font_size_min: 100,
  max_line_count: 2, safe_margin_frac: 0.019}` (no `placement_zone` / `logo_zone` /
  `scrim_treatment` - source-dependent). The hero `primary_font_size` is asserted to
  measure a real value in `[100, 300]` and the SPEC_MATCH dimension is PASS. The
  "FULL_DATA_CARD forced over a classified infographic still hard-BLOCKs" safety
  assertion is preserved (now scored against `_V8_DATA_HERO` - the BLOCK is
  `INFOGRAPHIC_DESTROYED`, independent of the font range).
* **FOUNDER_APPROVAL_SOURCE**: FOUNDER-VISUAL-BOARD-ALIGNMENT-1 (hero card),
  FOUNDER-VISUAL-CANVAS-COMPOSITION-CORRECTION-8 (1280x1172, board-proportional font).
  `_V8_DATA_HERO` is the FOUNDER-VISUAL-V8-FINAL-RELEASE-PREP-1 §17-19
  `FINAL_V8_SPEC_SET` `telegram_data` parameter set, already encoded as
  `_DATA_HERO_PARAMS` in `tests/test_design_spec_enforcement.py`.

## D. Exact test changes

`git diff --name-only` = **2 files, both under `tests/`**:

### `tests/test_visual_single_brand_mark_contract.py`
* `test_news_light_photo_has_exactly_one_mark` renamed to
  `test_news_light_photo_mark_only_stays_at_or_below_one_mark`; assertion
  `== 1` -> `<= 1` PLUS, when 0, `degradation_mode == "no_overlay"` and
  `upper_mark.placement is OMITTED` (a coherent safe suppression, never an accidental
  drop). Docstring records the MARK_ONLY contract and FINAL_VISIBLE_NNJ_COUNT <= 1.
* `test_breaking_places_exactly_one_brand_mark`: dropped the `monkeypatch` of the
  removed `brand_renderer.select_master_news_branding`; now asserts `result.success`,
  `derive_breaking_render_evidence(...).logo_count == 1`,
  `not hasattr(brand_renderer, "select_master_news_branding")`, and the
  `render_breaking_frame` body contains `_draw_breaking_watermark(` and none of
  `select_master_news_branding(` / `rasterize_nnj_mark(` / `_paste_svg_mark(` /
  `_paste_logo(`.

### `tests/test_visual_spec_v2_activation.py`
* Added `_V8_DATA_HERO` parameter dict + a module comment citing
  FOUNDER-VISUAL-V8-FINAL-RELEASE-PREP-1 §17-19.
* Imported `DesignSpecVersion`.
* In `test_final_matrix_all_pass_no_placement_zone_partial`: build an in-memory
  `data_hero_spec` (`scope="telegram_data"`, `_V8_DATA_HERO`); the "DATA photo"
  sub-case now asserts `mode2 is FULL_DATA_CARD`, `primary_font_size` is an int in
  `[100, 300]`, and evaluates SPEC_MATCH against `data_hero_spec` -> PASS; the Kirin
  FULL_DATA_CARD-over-infographic sub-case is scored against `data_hero_spec` and
  still asserts `ArtDirectorDecision.BLOCK`. Docstring updated.
* The MINIMAL infographic sub-case is unchanged (still `data_spec` = `telegram_data`
  v1). NEWS/BREAKING/QUOTE sub-cases unchanged.

No safety assertion was replaced with a "does not crash" check. Duplicate-NNJ,
`NUMBER_MISMATCH`, `INFOGRAPHIC_DESTROYED`, source-preservation, quote-attribution,
no-fabricated-DATA-points, no-fabricated-quote-role and BREAKING retired-band-absence
assertions elsewhere in the suite are untouched and still pass.

## E. Runtime diff proof

    $ git diff --name-only
    tests/test_visual_single_brand_mark_contract.py
    tests/test_visual_spec_v2_activation.py

No file under `services/`, `core/`, `models/`, `worker*/`, `assets/`, no `Dockerfile`,
no dependency file. **`RUNTIME_FILES_CHANGED = 0`.**

`ruff check` + `mypy` on both changed test files: clean. Line endings unchanged (LF,
matching `HEAD`).

## F. Test results

* The 3 targeted tests: **PASS**.
* Directly changed files
  (`test_visual_single_brand_mark_contract.py`, `test_visual_single_brand_mark_call_sites.py`,
  `test_visual_spec_v2_activation.py`): **18 passed**.
* Broad visual surface (22 files: `brand_renderer`, `render_evidence_parity`,
  `v2_10h_master_news_production`, `design_spec_enforcement` / `_registry`,
  `kirin_data_regression`, `presentation_director` / `_mode_contract`,
  `visual_single_brand_mark_*`, `visual_renderer_constraints`, `visual_spec_v2_activation`,
  `art_director_number_mismatch_blocks`, `director_control_plane_1a/1b_*`,
  `visual_brand_core`, the 5 `founder_visual_*` suites):
  **352 passed, 1 failed, 1 skipped** (was 349/4/1 before this phase - the 3 stale
  tests flipped to PASS).
* Broad keyword sweep (`-k "visual or brand or nnj or master_news or render_evidence
  or design_spec or art_director or presentation_director or data_card or data_source
  or quote_card or founder_visual or single_brand_mark or spec_v2 or spec_vnext or
  v2_10h or kirin"`, the four pre-existing collection-error files ignored):
  **526 passed, 2 failed, 4 skipped**.

**`NEW_FAILURES = 0`** - every remaining failure reproduces with this phase's test
edits stashed (`git stash` -> same 2 failures).

## G. Remaining pre-existing failures

| test | classification | note |
|---|---|---|
| `tests/test_presentation_director_mode_contract.py::test_enforce_gate_actually_assigns_every_mutating_target_at_least_once` | `PRE_EXISTING_NON_VISUAL` | static-analysis contract test on the presentation-director enforce gate (`assert not {'keyboard'}`); fails identically on clean `d2dea2c` (FOUNDER-VISUAL-V8-FINAL-RELEASE-PREP-1 section J baseline) and with this phase's edits stashed. Not a renderer test. |
| `tests/test_v2_9_production_wiring.py::test_cached_file_id_with_source_risk_still_brands_with_lower_signature_disabled` | `PRE_EXISTING_NON_VISUAL` | cached-`file_id` + source-risk production-wiring test; in the FOUNDER-VISUAL-V8-FINAL-RELEASE-PREP-1 full-sweep failure set that reproduces on clean `d2dea2c`; fails identically with this phase's edits stashed. |

No `EXPECTED_ENVIRONMENT` failures observed. No `NEW_FAILURE`.

## H. TEST_CATCHUP_SHA

The commit carrying this report + the two test files on
`feature/launch-readiness-visual-recap-parallel-1` (parent `cb95ec0`) - see `git log`.

## I. Approved release SHA is unchanged

`V8_RELEASE_SHA` remains **`d0a03773bebc98c6b71edb67fe368b85472e2d6b`** on
`release/founder-visual-v8-content-worker-1` (origin). This phase did not touch,
amend, rebase or re-point that branch or that commit. `git ls-remote origin
release/founder-visual-v8-content-worker-1` still resolves to `d0a03773`.

---

`FOUNDER_VISUAL_V8_TEST_CONTRACT_CATCHUP_PASS`

Stale pre-V8 assertions corrected to the Founder-approved V8 contracts;
`RUNTIME_FILES_CHANGED = 0`; `NEW_FAILURES = 0`; approved `V8_RELEASE_SHA`
unchanged; no production mutation.
