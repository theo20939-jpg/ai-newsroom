# FOUNDER-VISUAL-FINAL-BOARD-MATCH-7 - report

## A. Base SHA

`94a2a78` (`feature/launch-readiness-visual-recap-parallel-1`). Working tree clean at start;
selective staging; no reset/clean/rebase/amend.

## B. Final SHA

The commit carrying this report on `feature/launch-readiness-visual-recap-parallel-1`
(parent `94a2a78`) - see `git log`.

## C. Founder V6 verdict

BREAKING = NEEDS_FINAL_ALIGNMENT (watermark still too dominant; pulse feels slightly too
independent from the lower media boundary; calm-baseline proportions not yet close enough).
DATA_GENERATED = NEEDS_FINAL_ALIGNMENT (label too heavy; hierarchy compressed; secondary too
weak; vertical rhythm off; grid too uniformly present; graph still a generic smooth arc; fill
still too much red mass; bright red mark too prominent).
DATA_SOURCE (light / dark / brand-suppression) = **APPROVED / FREEZE**. NEWS / QUOTE /
QUOTE_NO_ROLE = FREEZE.

This was a bounded precision-alignment pass: no redesign, no asset/font search, no new waveform
system, no production change.

## D. BREAKING board measurements

Same-scale re-measurement in `07_BOARD_MEASUREMENTS.md` (in the review package). Key: the line is
0.4245 of the media width; the calm baseline BEFORE the P-QRS-T complex is 0.23 of the line, the
complex itself 0.28, and the calm TAIL after is 0.49; the baseline sits ~1px above the media
bottom; R apex +20px (0.148 of the line width); S/R = 0.75; stroke ~2px. Watermark: 0.535 media
width, effective opacity ~0.23.

## E. BREAKING V6 -> V7 changes

* `_PULSE_WAVEFORM_UNIT` rebuilt so the drawn line is calm-flat 0..0.23, P-QRS-T 0.23..0.51, then
  a long calm tail 0.51..1.0 - it now reads as *a restrained lower-media branded line with a
  compact pulse event*, not a standalone ECG.
* `pulse_baseline_frac` 0.95 -> **0.965** (hugs the media bottom edge, per Founder point #2);
  `_draw_recovered_pulse` now clamps its layer to the media bottom so the deep S kisses the edge
  like the board rather than being drawn off-canvas.
* `pulse_r_amp_frac_of_width` 0.148 -> **0.125** (trimmed so the deep S clears the lowered
  baseline; the amplitude is no longer exaggerated).
* Watermark: `watermark_opacity` 0.20 -> **0.12** (halved - the glyph stays large enough to read
  as a watermark but is genuinely background-level, per Founder point #1); tints darkened
  (140 on dark / 46 on light); `watermark_bottom_inset_frac` 0.02 -> 0.035; width 0.44 -> 0.50
  (the board-measured value).
* 4x supersampling, LANCZOS, deterministic rendering - unchanged.

## F. DATA board measurements

`07_BOARD_MEASUREMENTS.md`. Key: value cap-height 0.203 h; unit 0.75x value; **label only 0.19x
value** (V6's 0.28 was far too large); secondary ~0.165x value; left text zone 0.385 w; grid
delta ~+14.6 measured only in the RIGHT graph zone; graph x 0.492..0.867, origin Y 0.996 (near
the bottom), peak Y 0.47; endpoint radius 0.0079 w; under-curve tint ~(50,12,11) 18px below the
line.

## G. Typography weight hierarchy

The bundled Fira Sans Condensed family is unchanged (Founder-accepted). V7 SEPARATES the weights:

    value / unit  ->  Black          (data_weight="black")
    label         ->  SemiBold       (data_weight="semibold")   (V6 used Bold - too heavy)
    secondary     ->  Medium         (data_weight="medium")     (V6 used Regular - too weak)
    delta pill    ->  SemiBold

Sizes are derived from the fitted `value` size by the board's measured cap-height ratios
(`unit_over_value` 0.75, `label_over_value` 0.19, `desc_over_value` 0.165), and the vertical gaps
were tightened toward the board's rhythm (value->unit 14px, unit->label 10px).

## H. Grid zoning

`_draw_hero_grid` now draws lines **only where `x >= (graph_x_start_frac - 0.03) * w`** - the
RIGHT graph zone. The LEFT text zone renders as clean near-black; the horizontal rules also start
at the zone boundary. The contrast guard (`_guarded_grid_color`, delta clamped into [5, 11]) is
retained. At Telegram size the viewer perceives technical depth *behind the graph*, not square
cells across the whole card.

## I. Segmented graph rendering

`_reduced_tension_path` (55% linear + 45% monotone-cubic) is REMOVED. `_draw_hero_sparkline` now
calls `_segmented_anchor_path`, which returns **exactly the supplied `(x, y)` anchors, in order,
and nothing else** - the real points are connected DIRECTLY. Antialiasing, rounded joins and the
glow come from the 4x supersampled RGBA layer + LANCZOS downscale and `joint="curve"`; the
directional changes between anchors are preserved because no spline is applied. `_monotone_cubic`
is kept in the module (unit-tested) but is no longer on the render path.

## J. Factual-anchor proof

`_segmented_anchor_path(xs, ys) == list(zip(xs, ys))` - asserted in
`test_founder_visual_board_rebuild_6.py::test_data_hero_graph_is_a_clean_segmented_line_no_synthetic_points`.
The renderer synthesises NO points: a 7-point series draws 7 anchors, a 4-point series draws 4.
`series` values are plotted at exact linear x, min-max normalised y, verbatim. Two series that
differ produce different images (data-driven), and the same series is byte-deterministic. The
DATA review canaries use DENSE 7-9-point *fixture* series so the segment quality, joins, glow and
grid can be judged - those values are fixture data, not renderer output (section 14).

## K. Glow / fill changes

`graph_fill_peak_alpha` 70 -> **34** (halved); `graph_fill_band_frac` -> **0.24** (the fill
polygon is closed a bounded band <= 24% of the chart height below the line, not down to the
axis); `graph_fill_falloff` 3.0 -> 3.6 (steeper). The horizontal gradient is capped well below
opaque and eased to ~0 over the last 12% so the vertical right edge never reads as a column.
Result: the red LINE is the primary feature, the glow is a whisper, and most of the chart area
stays dark - no red triangular wedge.

## L. Logo treatment

`mark_width_frac` 0.055 -> **0.048**; `mark_opacity` 0.55 -> **0.32**. The NNJ mark is a small,
low-opacity red glyph in the lower-right that no longer competes with the graph endpoint dot. The
small pulse motif under the delta pill was also reduced (span 168 -> 132, amplitude 20 -> 13,
stroke 3 -> 2) so it stays visually secondary to `+38%` and the chart.

## M. Frozen DATA-source proof

`render_data_card(MINIMAL_SOURCE_PRESERVING)` and `_place_source_watermark` are **byte-unchanged**
this phase (`git diff` touches only the hero card and BREAKING). Regression covered by
`test_founder_visual_board_rebuild_6.py::test_data_source_*` (no pulse, no frame, no grid, source
preserved, adaptive light/dark watermark, brand suppression when no safe corner, third-party
marks untouched, `FINAL_VISIBLE_NNJ_COUNT <= 1`). `06_DATA_SOURCE_FROZEN.png` is the visual proof.

## N. Review artifacts

`C:/Users/Theodor/Desktop/NINJA_PULSE_FINAL_BOARD_MATCH_V7/` -
`00_REFERENCE_VS_V7.png` (SAME-SCALE rows: the board crop and the V7 output scaled to the same
width, stacked, two columns to stay readable), `01`-`06` full renders,
`07_BOARD_MEASUREMENTS.md`. Mirror in `artifacts/founder_visual_final_board_match_7/`.

## O. Tests

New/updated in `tests/test_founder_visual_board_rebuild_6.py` (15, all passing):
board-measured waveform proportions (long calm baseline + deep S + long tail; renderer fed
`bm.BREAKING.*`); pulse lower-media left-anchored AND hugging the bottom edge, no band; watermark
opacity <= 0.16 and near-imperceptible on a grey photo; no headline, one NNJ, evidence v6;
bundled Fira Cond present for every weight, repo-relative path; typography weights SEPARATED
(black / semibold / medium); grid source is zoned (`graph_x_start_frac` / `zone_x`) and the left
text zone renders as pure background; `_segmented_anchor_path` returns exactly the anchors, no
spline in the sparkline source, no synthetic points, data-driven; fill peak alpha <= 40 and band
<= 0.30 and deep-chart stays dark; mark opacity <= 0.40, one NNJ, evidence v3-board; DATA source
frozen (no pulse/frame/grid, light+dark preserved, suppression, third-party untouched);
NEWS / QUOTE / QUOTE_NO_ROLE frozen.

Updated for the renamed graph helper / weights: `test_founder_visual_overlay_recovery_4.py`,
`test_founder_visual_breaking_data_reconstruction_5.py`.

Broad regression sweep: **393 passed, 6 skipped, NEW_FAILURES = 0**. Pre-existing on `94a2a78`
(verified via `git stash`, only the number changed 176->176):
`test_visual_spec_v2_activation::test_final_matrix_all_pass_no_placement_zone_partial` (hero value
font vs the stale `telegram_data` v1 spec range [48,88]) and
`test_presentation_director_mode_contract::test_enforce_gate_actually_assigns_every_mutating_target_at_least_once`
(`assert not {'keyboard'}`); plus the pre-existing collection errors in
`test_v2_4d_overlay_contract.py` / `test_v2_4f_compact_overlay.py`.

## P. Static checks

`ruff check` on all changed `services/`, `tests/`, `scripts/` files -> clean.
`mypy services/brand_renderer.py services/render_evidence.py services/nnj_board_metrics.py
core/config.py` -> clean. **NEW_STATIC_ERRORS = 0.**

## Q. Remaining visual differences

1. **Chart width proportion** - the board's DATA card is a 4:3 media so its chart is more
   horizontally compressed; the runtime card is 16:9 so the chart occupies a wider band. The
   fractional x-start / x-end match the board; the absolute proportion differs with the aspect.
2. **Watermark tone** - scale, position and opacity are measured; the exact grey tone over an
   arbitrary photo is an approximation of a low-opacity measurement.
3. **Exact DATA typeface** - Fira Sans Condensed is the Founder-accepted family; it is not
   pixel-identical to the (still unidentified) board typeface.
4. **VPS render parity** - proven by bundled-font path semantics; no live Windows/Linux
   side-by-side render was run from this environment.

---

`FOUNDER_VISUAL_FINAL_BOARD_MATCH_7_READY_FOR_REVIEW`

No production touched. Not a claim of production readiness - the Founder must visually inspect V7.
Work stops here.
