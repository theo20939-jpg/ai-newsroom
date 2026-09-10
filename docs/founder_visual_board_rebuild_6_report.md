# FOUNDER-VISUAL-BOARD-REBUILD-6 — report

## A. Base SHA

`014e353` (`feature/launch-readiness-visual-recap-parallel-1`). Working tree clean at start; no
unrelated dirty/untracked work; selective staging only; no reset/clean/rebase/amend.

## B. Final SHA

The commit carrying this report on `feature/launch-readiness-visual-recap-parallel-1`
(parent `014e353`) — see `git log`.

## C. Founder V5 rejection

BREAKING = NEEDS_FIX (pulse reads as a small independent ECG; scale/proportion under-reproduces
the board; the tiny solid-red NNJ corner mark ≠ the board's subtle large watermark).
DATA_GENERATED = REJECTED (typography, background, grid, graph character, area fill all wrong;
"too programmatic"). DATA_SOURCE_INFOGRAPHIC = REJECTED.

## D. Exact Founder board crops used

Committed for local comparison/testing only (`docs/founder_telegram_board.png` unmodified):

    tests/fixtures/founder_breaking_media_crop.png   board (28,764)-(346,907)   318 x 143  (~2.22:1)
    tests/fixtures/founder_data_media_crop.png       board (413,126)-(728,362)  315 x 236  (~1.33:1)

## E. BREAKING measured geometry (`services/nnj_board_metrics.py :: BREAKING`)

| Property | Measured | Constant |
|---|---|---|
| pulse left inset | 0.038 of media width | `pulse_start_frac` |
| pulse drawn width | 0.425 of media width | `pulse_width_frac` |
| baseline Y | 0.993 of media height (board sits on the edge; runtime uses **0.95** so the deep S stays on-canvas) | `pulse_baseline_frac` |
| R apex height | 0.148 of the **drawn width** (aspect-safe) | `pulse_r_amp_frac_of_width` |
| S trough depth | S/R ≈ **0.70** | `pulse_s_over_r` |
| R apex x | **0.341** of the drawn width | `pulse_apex_at_frac` |
| stroke | ~1 px on the 318-wide crop → 0.0032 of media width | `pulse_stroke_frac` |

`_PULSE_WAVEFORM_UNIT` (23-pt P-QRS-T) is retuned so the R apex lands at 0.341 and the S trough
reaches −0.70. Rendered by `_draw_recovered_pulse` (4× supersample → LANCZOS). Amplitude is not
exaggerated (§5) and scales with the drawn span, not raw canvas height.

## F. BREAKING watermark measurements

Board glyph (lower-right of the media): bounds **0.44 w × 0.69 h** of the media; right edge
**1.6 %** from the media right edge; glyph mean RGB **≈ (56,56,56)** over a ~15 ground →
effective opacity **≈ 0.20**, light-grey. `_draw_breaking_watermark()` composites the canonical
`rasterize_nnj_mark()` geometry recoloured to grey (`watermark_grey_on_dark (150,150,150)` /
`watermark_grey_on_light (70,70,70)`, chosen by the local region luminance) at opacity 0.20 —
never red, no badge, no background. It replaces the V5 solid-red corner mark entirely.

## G. DATA measured geometry (`services/nnj_board_metrics.py :: DATA`)

| Property | Measured | Constant |
|---|---|---|
| left text zone | 0.385 of card width ("500" right edge) | `left_zone_frac` |
| value cap height | 0.203 of card height | `value_cap_frac` (→ `_HERO_VALUE_FONT_MAX 176`) |
| unit / value cap ratio | 0.76 | `unit_over_value` |
| label / value cap ratio | 0.28 | `label_over_value` |
| graph x | 0.49 → 0.87 of card width (ends **short** of the right edge) | `graph_x_start/end_frac` |
| graph y | origin 0.90 h → peak **0.47 h** | `graph_y_bottom/top_frac` |
| graph stroke | ~2 px on the crop → 0.006 of card width | `graph_stroke_frac` |
| endpoint dot | ~5 px on the crop → 0.006 of card width radius | `graph_endpoint_radius_frac` |
| under-curve tint | ≈ (50,12,11) 18 px below the line | `graph_fill_peak_alpha 70`, `falloff 3.0` |

## H. DATA background / grid measurements

`bg_rgb = (6,7,9)` (near-black, faint cool tint, measured). Board grid delta ≈ +14, but that
still read as "squares" at Telegram size in review, so the runtime grid is `(13,14,17)` and a
hard **contrast guard** (`_guarded_grid_color`) clamps `grid_luma − bg_luma` into
**[5, 11]** on this board and any future re-measurement. Grid step = 0.068 of card width
(~1/14.5). Single-pixel lines. No visible vignette/gradient in the board crop → none added.

## I. Typography candidates (`09_TYPOGRAPHY_FINAL.png`)

`500 / МЛН / ПОЛЬЗОВАТЕЛЕЙ / +38% / 1,4 млрд / СООБЩЕНИЙ` compared against the board DATA crop.
V5's **Arial Black is not approved** and is an OS-font dependency. Legally-bundlable open-source
condensed grotesques with a Black weight + full Cyrillic + clean numerals: **Fira Sans Condensed**
(Mozilla, SIL OFL), Roboto Condensed (Apache-2.0, no true Black), Oswald (OFL, very condensed —
too narrow), PT Sans Narrow (OFL, Bold only).

## J. Final bundled font decision

    DATA_FONT_SOURCE   = Fira Sans Condensed (Mozilla; google/fonts ofl/firasanscondensed)
    DATA_FONT_LICENSE  = SIL Open Font License 1.1  (assets/brand/fonts/OFL.txt)
    DATA_FONT_REGULAR  = assets/brand/fonts/FiraSansCondensed-Regular.ttf   (secondary / grey)
    DATA_FONT_BOLD     = assets/brand/fonts/FiraSansCondensed-Bold.ttf      (label)
    DATA_FONT_BLACK    = assets/brand/fonts/FiraSansCondensed-Black.ttf     (value + unit)
    (also bundled: SemiBold - delta pill; Medium - reserve)
    FONT_BOARD_MATCH_CONFIDENCE = HIGH
      condensed black grotesque, near-circular numerals, full Cyrillic, modern editorial/tech
      character - the design family is right; not pixel-identical to the (unidentified) exact
      board typeface.

## K. Font licensing / runtime strategy (§19)

The OFL permits bundling the font, unmodified, inside application software; the `.ttf` files are
**not** redistributed to the Founder as standalone artifacts (only the rendered
`09_TYPOGRAPHY_FINAL.png`). `services/brand_renderer.py::_data_font()` /
`data_font_path()` resolve the weight to a path **relative to the repo root** —
`WINDOWS_RENDER_FONT == LINUX_RENDER_FONT` is true by construction (one committed file; the
resolver never branches on `platform.system()`). `core/config.py` adds an optional
`brand_font_heavy_path` override but it is unused by the DATA path. The DATA renderer no longer
touches `C:/Windows/Fonts/*` or `/usr/share/fonts/*`. `assets/brand/fonts/README.md` documents
the mapping; the Dockerfile needs no change (the fonts ship in the repo tree the image copies).

## L. DATA graph reconstruction

`_reduced_tension_path(xs, ys)` = **55 % straight anchor-to-anchor polyline + 45 % monotone-cubic**
(`_monotone_cubic`, Fritsch-Carlson). Every real `(x, y)` anchor is hit exactly; each segment keeps
its own slope so local direction changes stay visible (a plateau, a small dip); the monotone term
only rounds the corners. Both blended terms stay within `[min, max]` of the series, so the path
**cannot overshoot** and invents no intermediate numeric value (§10/§16). Chart box from the board
fractions; the curve rises to the peak at ~0.47 h, not to the top edge.

## M. DATA fill / glow reconstruction

The fill polygon is closed a **bounded band** (≤ 42 % of the chart height) below the curve, not
down to the axis. A vertical gradient (`(1 − j/H) ** 3.0`, peak alpha 70) fades it fast; a
horizontal gradient stays capped well below opaque and eases back to ~0 over the last 12 % so the
vertical right edge never reads as a column. Result: the red **line** is the feature; the majority
of the chart area is near-black; no red wedge (§11). Endpoint: a small crisp white dot,
board-measured radius.

## N. Source infographic architecture (§16-§18, Founder-approved this phase)

`render_data_card(MINIMAL_SOURCE_PRESERVING)` now returns **before** any `_select_data_signature`
/ stat-block / fallback work. It composites the fitted source and then
`_place_source_watermark(canvas)`: try the four bounded corners (lower-right first); skip any
whose local `ImageStat` stddev > 18 (numbers / bars / text / a publisher logo); on the quietest
remaining corner composite ONE small (0.062 w) adaptive NNJ (dark-grey on light, light-grey on
dark, opacity ≤ 0.34); if every corner is occupied → **BRAND SUPPRESSION** (source ships
unbranded). No pulse, no bottom signature line, no frame, no grid, no DATA-card background, no
second metric. `FINAL_VISIBLE_NNJ_COUNT ≤ 1` (0 when suppressed).

## O. Measured constants

All in `services/nnj_board_metrics.py` (`BREAKING` / `DATA` frozen dataclasses) with a per-field
comment naming the board measurement. `brand_renderer.py` reads them (`br._BREAKING_PULSE_* ==
bm.BREAKING.*`, `_HERO_* == bm.DATA.*`), not scattered magic numbers.

## P. Canary results

| File | Input | Result |
|---|---|---|
| `01_BREAKING_DARK.png` | `case1_hero_product_iphone.jpg` | short left deep-S pulse + large faint grey watermark, no band |
| `02_BREAKING_LIGHT.png` | `case3_bright_promotional_scene.jpg` | same on a bright source, watermark adapts |
| `03_DATA_GENERATED_500.png` | 500 / МЛН + 7-pt rising series | Fira Cond Black hierarchy, near-black bg, invisible grid, restrained line + small dot |
| `04_DATA_GENERATED_PERCENT.png` | 68 / % + a series with a near-flat segment | the plateau is visible in the path (not ironed into an arc) |
| `05_DATA_GENERATED_LONG_VALUE.png` | 1,4 млрд / сообщений + a series with a local dip | the dip is visible |
| `06_DATA_SOURCE_LIGHT.png` | light infographic (no NNJ) | source preserved, one small grey corner watermark |
| `07_DATA_SOURCE_DARK.png` | dark infographic (no NNJ) | source preserved, adaptive light watermark |
| `08_DATA_SOURCE_NO_SAFE_ZONE.png` | infographic with `chartsource.io` in all four corners | BRAND SUPPRESSION - source unbranded, publisher marks untouched |
| `09_TYPOGRAPHY_FINAL.png` | board crop vs bundled Fira Cond Black samples | — |

## Q. Visual review matrices

**BREAKING** — `PULSE_GEOMETRY_MATCH = PASS` · `PULSE_SCALE_MATCH = PASS` ·
`PULSE_PLACEMENT_MATCH = PASS` · `WATERMARK_MATCH = PARTIAL` (large adaptive grey glyph present at
the measured scale/opacity; exact tone is an approximation of the board measurement) ·
`OVERALL_BRAND_CHARACTER = PASS`. **No FAIL.**

**DATA** — `TYPOGRAPHY_MATCH = PASS` · `BACKGROUND_MATCH = PASS` · `GRID_MATCH = PASS` ·
`GRAPH_SHAPE_MATCH = PARTIAL` (local direction changes retained; the board's fully organic wiggle
needs a denser real series) · `GRAPH_FILL_MATCH = PASS` · `METRIC_HIERARCHY_MATCH = PASS` ·
`LOGO_MATCH = PARTIAL` (small, lowered opacity; board's exact DATA-mark treatment approximated) ·
`OVERALL_BOARD_CHARACTER = PASS`. **No FAIL.**

**DATA SOURCE** — `SOURCE_PRESERVATION = PASS` · `BRANDING_RESTRAINT = PASS` ·
`NO_DATA_OBSTRUCTION = PASS` · `NO_UNNECESSARY_PULSE = PASS` · `SAFE_SUPPRESSION = PASS`. **All PASS.**

## R. Tests

New `tests/test_founder_visual_board_rebuild_6.py` (16, all passing): board-derived waveform
proportions (apex 0.341, deep S, renderer fed the `bm.BREAKING` fractions); lower-media
left-anchored, no band; watermark large/restrained/grey/not-a-CTA; no headline, ≤ 1 NNJ, evidence
v6; bundled font is a repo asset, platform-independent path; board-derived typography hierarchy;
contrast-guarded near-invisible grid; graph keeps real anchors + never overshoots + reduced-tension
path + data-driven; restrained fill + small endpoint; ≤ 1 restrained NNJ, evidence v3-board;
DATA source has no pulse/frame/grid by default; light + dark preserved; suppression when no safe
corner (`_place_source_watermark` returns False, canvas untouched); third-party watermark
untouched; NEWS / QUOTE / QUOTE_NO_ROLE frozen.

Updated: `test_founder_visual_breaking_data_reconstruction_5.py`,
`test_founder_visual_overlay_recovery_4.py`, `test_founder_visual_polish_2.py`,
`test_founder_visual_board_alignment_1.py`, `test_brand_renderer.py`,
`test_render_evidence_parity.py`, `test_design_spec_enforcement.py` (v6 version, watermark helper,
`data_weight="black"`, `_reduced_tension_path`).

Broad regression sweep: **394 passed, 6 skipped, NEW_FAILURES = 0**. Pre-existing on `014e353`
(verified via `git stash`, same assertion, only the number changed 188→176):
`test_visual_spec_v2_activation::test_final_matrix_all_pass_no_placement_zone_partial` (hero value
font vs the stale `telegram_data` v1 spec range [48,88]) and
`test_presentation_director_mode_contract::test_enforce_gate_actually_assigns_every_mutating_target_at_least_once`
(`assert not {'keyboard'}`); plus the pre-existing collection errors in
`test_v2_4d_overlay_contract.py` / `test_v2_4f_compact_overlay.py`.

## S. Static checks

`ruff check` on all changed `services/`, `core/`, `tests/`, `scripts/` files → clean.
`mypy services/brand_renderer.py services/render_evidence.py services/nnj_board_metrics.py
core/config.py` → clean. **NEW_STATIC_ERRORS = 0.**

## T. Changed files

```
services/nnj_board_metrics.py         NEW - measured board proportions (BREAKING / DATA dataclasses)
assets/brand/fonts/*.ttf + OFL.txt + README.md   NEW - bundled Fira Sans Condensed (SIL OFL)
services/brand_renderer.py            _data_font/data_font_path (bundled); BREAKING pulse retuned
                                      to the board metrics + _draw_breaking_watermark (large grey);
                                      DATA hero bg/grid(contrast guard)/typography(bundled, board
                                      ratios)/graph(_reduced_tension_path)/fill(bounded band)/
                                      endpoint/mark(opacity); DATA source -> _place_source_watermark
                                      (source fidelity first, else suppression)
services/render_evidence.py           BREAKING evidence v6-board + watermark note; DATA hero
                                      evidence v3-board + bundled-font replay + notes
tests/test_founder_visual_board_rebuild_6.py   NEW (16)
tests/test_founder_visual_breaking_data_reconstruction_5.py / _overlay_recovery_4.py / _polish_2.py /
tests/test_founder_visual_board_alignment_1.py / test_brand_renderer.py /
tests/test_render_evidence_parity.py / test_design_spec_enforcement.py   updated to v6
tests/fixtures/founder_breaking_media_crop.png / founder_data_media_crop.png   NEW (board crops)
scripts/_founder_visual_board_rebuild_6_canary.py   NEW
artifacts/founder_visual_board_rebuild_6/           NEW (00-09)
docs/founder_visual_board_rebuild_6_report.md       NEW (this file)
design/founder_visual_breaking_data_fix_5_asset_inventory.md   (carried; no new asset search this phase)
```

## U. Remaining visual mismatches

1. **DATA graph character** — `GRAPH_SHAPE_MATCH = PARTIAL`. The reduced-tension path keeps local
   direction changes, but the board's fully organic wiggle comes from a denser series than the
   4-7-point `DataCandidate.series` carries; fabricating volatility is forbidden.
2. **BREAKING watermark tone / DATA mark treatment** — `WATERMARK_MATCH` / `LOGO_MATCH = PARTIAL`.
   Scale, position and opacity are measured; the exact grey tone and the board's precise DATA-mark
   rendering are approximations of a low-opacity measurement.
3. **Exact DATA typeface** — `FONT_BOARD_MATCH_CONFIDENCE = HIGH` on the design family; the exact
   board typeface is unidentified. Fira Sans Condensed is the closest legally-bundlable match.
4. **VPS render parity** — bundled-font determinism is proven by path semantics; an actual
   side-by-side Windows/Linux render was not run from this environment (no VPS access this phase).

---

`FOUNDER_VISUAL_BOARD_REBUILD_6_READY_FOR_REVIEW`

No production touched. The Founder must visually inspect V6 (BREAKING + DATA) before any rollout.
Work stops here.
