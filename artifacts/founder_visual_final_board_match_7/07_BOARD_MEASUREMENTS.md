# 07 - BOARD MEASUREMENTS (FOUNDER-VISUAL-FINAL-BOARD-MATCH-7)

Same-scale re-measurement of `docs/founder_telegram_board.png` used to correct V6 -> V7.
Crops: `tests/fixtures/founder_breaking_media_crop.png` (board (28,764)-(346,907), 318x143) and
`tests/fixtures/founder_data_media_crop.png` (board (413,126)-(728,362), 315x236).

## BREAKING pulse (measured on the crop)

| Property | Board (measured) | V6 | V7 (`nnj_board_metrics.BREAKING`) |
|---|---|---|---|
| line start X | 0.038 of media w | 0.038 | 0.038 (`pulse_start_frac`) |
| line width | 0.4245 of media w | 0.425 | 0.4245 (`pulse_width_frac`) |
| calm baseline BEFORE the complex | 0.23 of the line | (implicit) | 0.23 (`pulse_pre_flat_frac`) |
| the P-QRS-T complex | 0.28 of the line | ~0.45 | 0.28 (`pulse_complex_frac`) |
| calm tail AFTER | 0.49 of the line | ~0.32 | 0.49 (implicit) |
| baseline Y | 0.993 of media h (1px above bottom) | 0.95 | **0.965** (`pulse_baseline_frac`) - hugs the edge, keeps S on-canvas |
| R apex | +20px = 0.148 of the line width | 0.148 | **0.125** (`pulse_r_amp_frac_of_width`) - trimmed so the deep S clears the lowered baseline |
| S trough | S/R = 0.75 | 0.70 | 0.72 (`pulse_s_over_r`) |
| R apex X (within the complex) | 0.341 | 0.341 | 0.341 (`pulse_apex_at_frac`) |
| stroke | ~2px = 0.0063 of media w | 0.0032 | 0.0034 (`pulse_stroke_frac`) |

## BREAKING watermark (measured on the crop)

| Property | Board (measured) | V6 | V7 |
|---|---|---|---|
| width | 0.535 of media w | 0.44 | 0.50 (`watermark_width_frac`) |
| right inset | 0.016 | 0.016 | 0.016 |
| bottom inset | 0.035 | 0.02 | 0.035 |
| effective opacity | ~0.23 (glyph luma ~45 over a ~15 ground) | 0.20 | **0.12** (`watermark_opacity`) - HALVED: the Founder found V6 too dominant, so the drawn opacity is well below the measured value; the glyph stays large enough to read as a watermark but is genuinely background-level |
| tint | neutral grey | (150) / (70) | (140) on dark / (46) on light |

## DATA typography (cap heights, fraction of card height)

| Element | Board (measured) | V6 | V7 |
|---|---|---|---|
| value "500" | 0.203 h | 0.203 | 0.203 (`value_cap_frac`) |
| unit "МЛН" | 0.75 x value | 0.76 | 0.75 (`unit_over_value`) |
| label "ПОЛЬЗОВАТЕЛЕЙ" | **0.19 x value** | 0.28 (too heavy/large) | 0.19 (`label_over_value`) |
| secondary line | ~0.165 x value | (Regular, too weak) | 0.165 (`desc_over_value`) |
| weights | Black / Black-red / lighter / lighter | Black / Black / Bold / Regular | **Black / Black / SemiBold / Medium** |
| gap value->unit | 9px | 16px | 14px |
| gap unit->label | 14px | 12px | 10px |

## DATA grid

Board reads as full-canvas graph paper: **NO**. The technical grid belongs to the RIGHT GRAPH
ZONE (measured grid delta there ~+14.6); the LEFT text zone is essentially pure near-black.
V7: `_draw_hero_grid` only draws lines where `x >= (graph_x_start_frac - 0.03) * w`; the
contrast guard clamps grid_luma - bg_luma into [5, 11].

## DATA graph

| Property | Board (measured) | V6 | V7 (`nnj_board_metrics.DATA`) |
|---|---|---|---|
| x start | 0.492 of card w | 0.49 | 0.492 (`graph_x_start_frac`) |
| x end | 0.867 of card w (short of the edge) | 0.87 | 0.867 (`graph_x_end_frac`) |
| left-end Y (origin) | 0.996 h (near the bottom) | 0.90 | 0.965 (`graph_y_bottom_frac`) |
| right-end Y (peak) | 0.47 h | 0.47 | 0.47 (`graph_y_top_frac`) |
| stroke | ~2px = 0.006 of card w | 0.006 | 0.0052 (`graph_stroke_frac`) |
| endpoint dot | ~5-6px -> radius 0.0079 of card w | 0.006 | 0.0065 (`graph_endpoint_radius_frac`) - small, not enlarged |
| under-curve tint | ~(50,12,11) 18px below the line - very restrained | peak alpha 70 | **peak alpha 34** (`graph_fill_peak_alpha`), band <= 24% chart h (`graph_fill_band_frac`) |
| path | segmented, visible direction changes | reduced-tension spline | **direct segments through real anchors** (`_segmented_anchor_path`) - the renderer synthesises no points |

## DATA mark

| Property | V6 | V7 |
|---|---|---|
| width | 0.055 of card w | 0.048 (`mark_width_frac`) |
| opacity | 0.55 | **0.32** (`mark_opacity`) - must not compete with the graph endpoint |
