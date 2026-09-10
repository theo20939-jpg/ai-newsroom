# FOUNDER-VISUAL-CANVAS-COMPOSITION-CORRECTION-8 - report

## A. Base SHA

`86920fd` (`feature/launch-readiness-visual-recap-parallel-1`, "FOUNDER-VISUAL-FINAL-BOARD-MATCH-7").
Working tree was clean at start; selective staging only; no reset / clean / rebase / amend.

## B. Final SHA

The commit carrying this report on `feature/launch-readiness-visual-recap-parallel-1` (parent
`86920fd`) - see `git log`.

## C. Founder V7 verdict acted on

BREAKING = NEEDS_FIX. DATA_GENERATED = REJECTED. DATA_SOURCE = APPROVED / FREEZE.
NEWS / QUOTE / QUOTE_NO_ROLE = APPROVED / FREEZE.

Core finding: the generated DATA renderer was still forced into a **widescreen (16:9) composition
whose geometry does not match the Founder board**. This phase is a bounded STRUCTURAL correction of
that mistake plus the outstanding BREAKING geometry. NO production deployment, NO VisualSpec
activation, NO image-generation model, NO Story Continuity changes.

## D. DATA media ratio - measured (section 2 / section 3)

The prior reference crop `tests/fixtures/founder_data_media_crop.png` (`board (413,126)-(728,362)`,
315 x 236, ~1.33:1) **cut off the media bottom** - the "~4:3" was a cropping artefact. Re-measured
against the ACTUAL DATA media rectangle in `docs/founder_telegram_board.png` (Telegram chrome /
caption `NP-0182` / `Источник:` / reactions / buttons excluded):

    DATA media  =  x 404, y 105, w 322, h 295
    DATA_BOARD_MEDIA_ASPECT_RATIO  =  322 / 295  =  1.0915   (near-square)

Not 16:9, not 4:3. `tests/fixtures/founder_data_media_crop.png` re-extracted to 322 x 295;
`services/nnj_board_metrics.py` docstring + `DataBoardMetrics` re-measured against that rectangle.
A measurement record is committed at `docs/founder_visual_canvas_composition_correction_8_geometry.md`
(and shipped as `08_GEOMETRY_MEASUREMENTS.md`).

## E. DATA_16_9_REQUIRED (section 4)

**DATA_16_9_REQUIRED = false.** Telegram accepts non-16:9 photo / document media; the send path
(`bot/`, `worker/content_cycle.py`, `services/telegram_routing.py`) never imposes 16:9. The DATA
hero renderer inherited 16:9 purely because `_CANVAS_W` / `_CANVAS_H` (1280 x 720) were imported
from `services/nnj_master_news_overlay` (the NEWS hero) as a shared default. DATA now gets its own
canvas geometry.

## F. DATA dedicated canvas (section 5 / section 6)

Width kept at the production-safe **1280**; height derived deterministically from the measured
board media aspect:

    canvas_h = round(1280 * 295 / 322) = round(1172.67) = 1172

**V8 DATA canvas = 1280 x 1172** (aspect 1.0922; a 0.06 % match to the board's 1.0915). No runtime
dimension branching. `_HERO_CW` / `_HERO_CH` are wired from `_bm.DATA.canvas_w` / `canvas_h`.

## G. DATA typography hierarchy (section 11 - section 13)

* Metric block is **TOP-anchored** at `value_top_frac (0.156) x canvas_h` (V7 vertically centred it
  on the 16:9 canvas - which shrank it and floated it mid-card).
* `value` ("500") is fitted to the board cap-height `0.163 h` -> ~270 px Fira Sans Condensed Black;
  `primary_font_size` lands at **270** (bounded by `_HERO_VALUE_FONT_MAX = 270`, which is the
  board-proportional value - NOT "maximise"). V7's ceiling was 200 on the 720 canvas.
* Weights stay SEPARATED (Founder-accepted family, unchanged): value / unit = Black, unit red;
  label = SemiBold; secondary = Medium; delta pill = SemiBold. Sizes derive from the fitted value
  by the board ratios `unit_over_value 0.75`, `label_over_value 0.188`, `desc_over_value 0.21`.
* Left text zone = `left_zone_frac 0.41` of the width; the column is compact / dense.

## H. DATA graph + grid + fill (section 14 - section 17)

* `_draw_hero_sparkline` calls `_segmented_anchor_path`, which returns **exactly `list(zip(xs, ys))`**
  - the real series points are the ONLY anchors, connected DIRECTLY. No spline, no `_monotone_cubic`
  on the render path, no synthetic / fabricated values. A 9-value fixture draws 9 anchors.
  *(The renderer owns STYLE - 4x supersample, LANCZOS, rounded joins, the glow. The input owns
  SHAPE.)*
* `graph_x_start_frac` pulled 0.40 -> **0.34** so the trend integrates with the metric block and
  the mid-card no longer reads as an oversized empty gap; `graph_x_end_frac 0.88`,
  `graph_y_top 0.43`, `graph_y_bottom 0.93`.
* Grid drawn only where `gx >= zone_x` (the graph zone); the left text region renders as clean
  near-black. `_guarded_grid_color` clamps `grid_luma - bg_luma` into `[5, 11]` - cells are
  near-imperceptible at Telegram scale.
* Fill: `graph_fill_peak_alpha 32`, band `<= 0.24` of chart height below the curve, falloff 3.6,
  horizontal gradient eased to ~0 at the right edge. The red LINE is primary; the glow is a
  whisper; most of the chart stays dark; no triangular red wedge and no full-canvas red mass.

## I. DATA logo - FOUNDER_DATA_MEDIA_MARK (section 18)

**FOUNDER_DATA_MEDIA_MARK = ABSENT.** Zero canonical-red pixels in the DATA media's lower-right on
the board; the only red glyph is the `● PULSE / DATA` header dot, which is not the NNJ mark.

This **conflicts** with the prior explicit one-mark decision (VISUAL-SINGLE-BRAND-MARK-1, "exactly
one canonical NNJ per rendered frame"). Per section 18 the conflict is reported rather than
silently resolved, and the safe reading is taken: V8 keeps **one very restrained** mark
(`mark_width_frac 0.040`, `mark_opacity 0.26` - lower than V7's 0.32) in the lower-right. If the
Founder confirms the DATA media should carry no mark at all, `_HERO_MARK_OPACITY = 0.0` is a
one-line change - flagged for the review.

## J. BREAKING media rectangle (section 19)

The prior crop `board (28,764)-(346,907)` (318 x 143, ~2.22:1) **cut off the RIGHT** of the media,
which is why the full-width board pulse line looked half-width. Re-measured:

    BREAKING media  =  x 18, y 747, w 322, h 165   (aspect ~1.95)

`tests/fixtures/founder_breaking_media_crop.png` re-extracted to 322 x 165.

## K. BREAKING pulse line (section 20)

| quantity | board | V8 (was V7) |
|---|---|---|
| first -> last visible red px | x 39 -> 295 = media x-frac **0.065 -> 0.860** | start 0.065, width **0.795** -> end 0.860 |
| **BREAKING_LINE_TOTAL_WIDTH_FRAC** | **0.795** | **0.795**  (was 0.4245 - "baseline ends too early") |
| P-QRS-T event vs the COMPLETE line | starts ~0.19, spans ~0.27, then a calm tail ~0.54 | `_PULSE_WAVEFORM_UNIT` places the complex at 0.20..0.51 of the drawn line (calm `<=0.20` and `>=0.62`) - **UNCHANGED**, "do not change the waveform family again"; drawn full-width it now lands the event where the board has it |
| R apex | +20 px = **0.078** of the full-width line on the 322 media | `pulse_r_amp_frac_of_width` 0.125 -> **0.078** (keeps the absolute spike ~unchanged now that the line is ~1.9x longer) |
| baseline y | 905 = media y-frac 0.958; the S clips past the media bottom | `pulse_baseline_frac` 0.965 -> **0.972**; `_draw_recovered_pulse` still clamps the deep S to the canvas edge so the pulse reads as **attached to the lower edge** (Founder: "too independent from the edge") |
| stroke | ~2 px = 0.006 of the 322 media | `pulse_stroke_frac 0.0034` of the source width - unchanged, thin on a large photo |

## L. BREAKING watermark - EFFECTIVE VISIBLE box (section 21 / section 22)

Measured from the board's actual grey strokes, NOT the NNJ SVG width:

| quantity | board | V8 (was V7) |
|---|---|---|
| width frac of media | ~0.47 | `watermark_width_frac` 0.50 -> **0.47** |
| height frac of media | ~0.34 | proportional to the NNJ glyph |
| occupied x-frac in media | ~0.524 .. ~0.994 (entirely RIGHT of centre) | 1 - 0.006 - 0.47 = **0.524 .. 0.994** (V7 was 0.484..0.984, crossing the centre line) |
| right inset frac | ~0.006 (flush) | 0.016 -> **0.006** |
| bottom inset frac | ~0.012 (near flush) | 0.035 -> **0.012** |
| effective opacity | ~0.12-0.20 over image noise | drawn 0.12 -> **0.10** - a genuine background watermark |

Opacity is the **same 0.10 on dark and bright** sources - not increased for a bright source
(section 23). `05_BREAKING_DARK.png` / `06_BREAKING_LIGHT.png` show the watermark visible but
subordinate in both.

## M. Frozen formats - proof (section 24 / section 25)

`git diff 86920fd..HEAD` touches only: `services/brand_renderer.py` (the DATA **hero** card +
BREAKING frame), `services/nnj_board_metrics.py` (constants), `services/render_evidence.py`
(BREAKING / DATA-hero evidence notes + version strings), the canary script, tests, docs, artifacts.

* **DATA source** - `render_data_card(MINIMAL_SOURCE_PRESERVING)`, `_place_source_watermark`,
  `_SOURCE_WM_BUSY_STDDEV`, brand suppression, the `_fit_photo_to_canvas(photo, (1280, 720))`
  source canvas: **byte-unchanged**. No pulse / frame / grid / re-rendered numbers / badge added.
  Regression canary kept (`07_DATA_SOURCE_FROZEN.png`;
  `test_kirin_data_regression.py::test_minimal_source_preserving_never_draws_a_second_competing_stat_block`;
  `test_founder_visual_board_rebuild_6.py::test_data_source_*`).
* **NEWS / QUOTE / QUOTE_NO_ROLE** - renderers byte-unchanged; regressions green
  (`test_founder_visual_polish_2.py`, `test_brand_renderer.py` quote suite).

## N. RenderEvidence (section 27)

* **DATA hero** (`_derive_data_hero_evidence`): `renderer_version = "pulse-data-hero-v4-square"`,
  `canvas_width = 1280`, `canvas_height = 1172`, `safe_margin_frac`, `primary_font_size = 270`,
  typography note "value/unit=Black, label=SemiBold, secondary=Medium", `graph_interpolation` note
  "segmented_anchor_path - the real series points connected DIRECTLY ... no spline", a `canvas_aspect`
  note carrying `1280/1172` vs `_bm.DATA.aspect` and `DATA_16_9_REQUIRED=false`, `background_version`
  note "near-square 1280x1172 board-media aspect".
* **BREAKING** (`derive_breaking_render_evidence`): `renderer_version = "pulse-breaking-v7-board"`;
  `placement_zone` note now reports the drawn line x-frac span, `BREAKING_LINE_TOTAL_WIDTH_FRAC`,
  the P-QRS-T position within the complete line, the R apex fraction and the S edge clamp;
  `watermark` note reports the EFFECTIVE VISIBLE zone x-frac, width, insets and drawn opacity;
  `logo_count` note "exactly 1 visible NNJ - the lower-right watermark". `logo_count = 1`.

## O. Tests

Updated / added (all green):

* Canvas change size assertions: `test_brand_renderer.py` (hero branch -> 1280x1172, MINIMAL kept
  at `(_CANVAS_W, _CANVAS_H)`), `test_founder_visual_polish_2.py`,
  `test_founder_visual_board_alignment_1.py` (test renamed `..._is_near_square_jpeg_...`),
  `test_kirin_data_regression.py` (`_HERO_CANVAS = (1280, 1172)` for FULL_DATA_CARD),
  `test_design_spec_enforcement.py` (`_DATA_HERO_PARAMS` font range 100..300; the hero
  `primary_font_size` assertion is now `200 <= x <= 300`).
* Renderer version bump `pulse-breaking-v6-board` -> `pulse-breaking-v7-board` across
  `render_evidence.py` + 6 test files; `pulse-data-hero-v3-board` -> `pulse-data-hero-v4-square`
  (done in the smoke phase) confirmed in `test_founder_visual_board_rebuild_6.py`.
* Fill-region test `test_founder_visual_breaking_data_reconstruction_5.py::test_hero_area_fill_is_a_restrained_glow_not_a_solid_block`
  re-boxed to the 1172-tall chart region.

Broad regression sweep - see section S. **NEW_FAILURES = 0.**

The 40 sweep failures break down as: **37 fail identically on `86920fd`** (re-ran the exact 40
against `git stash`ed base -> 37 failed, 3 passed) and **3 pass in isolation** on the working tree
(`test_recap_r2_10_g3_llm_judge.py::test_llm_path_cannot_write_db`,
`test_story_memory_v2_phase1.py::test_delivery_recorded_when_reply_mode_off_but_story_link_exists`,
`test_story_memory_v2_phase1.py::test_send_success_plus_persistence_failure_fails_safe`) - all three
green when run alone, all three with zero import path to `brand_renderer` / `nnj_board_metrics` /
`render_evidence`; they flake under 35-min full-suite DB / resource contention, not from this change.

The 37 pre-existing failures are the known classes: the `test_*::test_no_production_files_changed_since_base_commit`
/ `test_no_production_readiness_mutation` / `test_dotenv_file_on_disk_was_not_modified` guards (fail
because this worktree is intentionally dirty), timing-sensitive worker-loop tests
(`test_content_worker_main.py`, `test_content_worker_cycle_image_preview.py`),
`test_visual_single_brand_mark_contract.py::{test_news_light_photo_has_exactly_one_mark,
test_breaking_places_exactly_one_brand_mark}` (`AttributeError: no attribute
'select_master_news_branding'` - a stale helper name),
`test_visual_spec_v2_activation.py::test_final_matrix_all_pass_no_placement_zone_partial`,
`test_presentation_director_mode_contract.py::test_enforce_gate_actually_assigns_every_mutating_target_at_least_once`,
`test_evidence_package_degradation.py::test_build_evidence_package_raises_when_table_missing`, and a
set of `test_recap_*` / `test_v2_7_e2e_forensic_recovery.py` / `test_v2_8_*` / `test_v2_9_*` /
`test_router_media_integration.py` / `test_story_memory_v2_shadow_isolation.py` /
`test_meme_diversity.py` / `test_phase15/17/18_*` cases that fail the same way on the clean base.

## P. Static checks

`ruff check` on every changed `services/` / `tests/` / `scripts/` file -> clean.
`mypy services/brand_renderer.py services/render_evidence.py services/nnj_board_metrics.py` -> clean.
**NEW_STATIC_ERRORS = 0.**

## Q. Local VisualSpec candidate note (section 26)

No production spec is touched. The DATA aspect correction does change the geometry a candidate
`telegram_data` vNEXT spec would describe: OLD = 16:9 1280x720, value font ceiling ~200, chart in a
right-side band; NEW = near-square 1280x1172 (board media 1.0915), value font ~270 from the
`0.163 h` cap, chart integrated from x-frac 0.34. This is recorded here and in the geometry doc; no
`schemas/` or DB spec row is modified, and no activation script is run.

## R. Review package (section 28)

`C:/Users/Theodor/Desktop/NINJA_PULSE_DATA_COMPOSITION_V8/` (mirror
`artifacts/founder_visual_canvas_composition_correction_8/`):

| file | content |
|---|---|
| `00_DATA_REFERENCE_VS_V8.png` | LEFT = Founder DATA media crop, RIGHT = V8 DATA - **exact same pixel size** |
| `01_BREAKING_REFERENCE_VS_V8.png` | TOP = Founder BREAKING media, BOTTOM = V8 BREAKING lower band - **exact same pixel size** |
| `02_DATA_500_RU.png` | `500` / `МЛН` / `ПОЛЬЗОВАТЕЛЕЙ` / `Достиг ChatGPT в июле 2025 года` / `+38%`, 9-point fixture |
| `03_DATA_68_PERCENT_RU.png` | `68` / `%` / `ЭЛЕКТРОМОБИЛЕЙ В НОВЫХ ПРОДАЖАХ` / `Доля новых машин в регионе за 2025 год` / `+13 п.п.`, 9-point fixture |
| `04_DATA_1_4_BILLION_RU.png` | `1,4 млрд` / `СООБЩЕНИЙ` / `В ДЕНЬ` / `WhatsApp, декабрь 2025` / `+22%`, 8-point fixture |
| `05_BREAKING_DARK.png` | BREAKING on a dark product photo |
| `06_BREAKING_LIGHT.png` | BREAKING on a bright photo - watermark subordinate, opacity NOT raised |
| `07_DATA_SOURCE_FROZEN.png` | frozen MINIMAL_SOURCE_PRESERVING regression proof |
| `08_GEOMETRY_MEASUREMENTS.md` | the measurement record |

All DATA canaries render **real Cyrillic** with the bundled Fira Sans Condensed (Black / SemiBold /
Medium) - no transliteration, no English. `CYRILLIC_CANARY_VALID = true`. The two REFERENCE_VS
images are the primary Founder-review artifacts; no giant vertical contact sheet was produced.
`DATA_ASPECT_COMPARISON_VALID = true` (board crop and V8 render forced to identical pixel
dimensions before stacking).

## S. Broad sweep count

`pytest -p no:randomly -q --tb=no -rf` with the four PRE-EXISTING collection-error files ignored
(`test_phase20_m1_harness_fixes.py`, `test_v2_3a_editorial_recomposition_canary.py`,
`test_v2_4d_overlay_contract.py`, `test_v2_4f_compact_overlay.py`):

    40 failed, 6292 passed, 28 skipped   in 2136s

Delta vs `86920fd` (same 40 re-run against the stashed base = 37 failed / 3 passed; the 3 pass in
isolation on the working tree): **NEW_FAILURES = 0**, **NEW_STATIC_ERRORS = 0**.

## T. Remaining visual differences (for the Founder's eye)

1. **Graph fill mass** - the board's under-curve red glow is noticeably more present than V8's.
   V8's is deliberately a whisper (Founder V6/V7: "reduce the red mass substantially", "most of the
   graph area dark"). If the Founder now wants more glow, `graph_fill_peak_alpha` /
   `graph_fill_band_frac` are the two dials.
2. **Upper-mid-card space on short-text canaries** - a metric with few short lines (canary 3) leaves
   the upper-centre sparse; the board example carried more description text. The block is
   top-anchored to the board measurement rather than stretched to fill.
3. **DATA mark** - kept as one restrained mark despite `FOUNDER_DATA_MEDIA_MARK = ABSENT`; see
   section I. Needs a Founder decision.
4. **Sub-pill caption** - the board shows a small `рост за 2 месяца` line *under* the `+38%` pill;
   V8 places the evidence fact as the description *above* the pill. Not changed this phase.
5. **Exact DATA typeface** - Fira Sans Condensed is the Founder-accepted family; not pixel-identical
   to the (still unidentified) board face.
6. **VPS render parity** - proven by bundled-font path semantics; no live Windows/Linux
   side-by-side render was run from this environment.

---

`FOUNDER_VISUAL_CANVAS_COMPOSITION_8_READY_FOR_REVIEW`

Aspect measured (1.0915, not 16:9 / not 4:3); the 16:9 assumption removed (DATA_16_9_REQUIRED =
false; dedicated 1280x1172 canvas); same-aspect exact-pixel comparison produced; three real-Cyrillic
DATA canaries produced; BREAKING total line span corrected (0.4245 -> 0.795) and watermark
corrected (0.47 wide, right of centre, opacity 0.10); frozen formats byte-unchanged;
NEW_FAILURES = 0; NEW_STATIC_ERRORS = 0; no production mutation. This is NOT a claim of production
readiness - the Founder must visually inspect V8. Work stops here; V9 is not started.
