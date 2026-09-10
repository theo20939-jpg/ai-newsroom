# FOUNDER-VISUAL-CANVAS-COMPOSITION-CORRECTION-8 - geometry measurements

All numbers are DIRECT pixel measurements of `docs/founder_telegram_board.png` (1024 x 1280),
Telegram chrome / caption / reactions / buttons excluded. Nothing here assumes 16:9 or 4:3.

## 1. DATA media rectangle (section 2 / section 3)

| quantity | value |
|---|---|
| media x, y | 404, 105 |
| media w, h | 322 x 295 |
| **DATA_BOARD_MEDIA_ASPECT_RATIO** | 322/295 = **1.0915** (near-square) |

The prior fixture crop `(413,126)-(728,362)` (315 x 236, ~1.33:1) CUT OFF the media bottom - the
"~4:3" was a cropping artefact. Re-extracted `tests/fixtures/founder_data_media_crop.png` at
322 x 295.

## 2. DATA_16_9_REQUIRED (section 4)

**DATA_16_9_REQUIRED = false.** Telegram accepts non-16:9 photo/document media; nothing in the
send path (`bot/`, `worker/content_cycle.py`) forces a 16:9 canvas. 16:9 (1280x720) entered the
DATA hero renderer only because `_CANVAS_W/_CANVAS_H` were imported from
`nnj_master_news_overlay` (the NEWS hero), a shared default - not a platform rule. DATA therefore
gets its OWN canvas geometry.

## 3. DATA dedicated output canvas (section 5 / section 6)

Width is kept at the existing production-safe **1280**; height derives from the measured board
media aspect:

    canvas_h = round(1280 * 295 / 322) = round(1172.7) = 1172

**V8 DATA canvas = 1280 x 1172  (aspect 1.0922)**, a
0.06% match to the board media aspect.
Deterministic; no runtime dimension branching.

## 4. DATA hierarchy re-measure (section 11 - section 13, fractions of media HEIGHT)

| element | board cap-height frac | V8 derivation |
|---|---|---|
| value ("500") | 0.163 (top at 0.156) | `_fit_single_line`, cap 0.163 h -> ~270 px Fira Cond Black; primary_font_size lands 270 (bounded, proportion-matched, not "maximise") |
| unit ("МЛН")  | 0.75 x value | Black, red |
| label         | 0.188 x value | SemiBold |
| secondary     | 0.21 x value | Medium |
| left text zone | right edge at x-frac 0.41 | `_HERO_LEFT_ZONE_FRAC` = 0.41 |

Metric block is TOP-anchored at `value_top_frac` x canvas_h (was vertically centred on the 16:9
canvas). Graph x-start pulled to 0.34 so the trend integrates with the
metric block (no oversized empty gap); graph x-end 0.88, y 0.43..0.93.

## 5. DATA graph / grid / fill (section 14 - section 17)

* `_segmented_anchor_path(xs, ys) == list(zip(xs, ys))` - the real series points are the ONLY
  anchors, connected DIRECTLY. No spline, no `_monotone_cubic` on the render path, no synthetic
  points. A 9-value fixture draws 9 anchors.
* Grid drawn only where `gx >= zone_x` (the graph zone); the left text region is clean near-black.
  `_guarded_grid_color` clamps grid_luma - bg_luma into [5, 11] -
  cells are near-imperceptible at Telegram scale.
* Fill: `graph_fill_peak_alpha=32`, band <= 0.24 of
  chart height below the curve, falloff 3.6. The red LINE is primary; the glow
  is a whisper; most of the chart stays dark; no triangular red wedge.

## 6. FOUNDER_DATA_MEDIA_MARK (section 18)

**FOUNDER_DATA_MEDIA_MARK = ABSENT.** 0 canonical-red pixels in the DATA media's lower-right
corner on the board; the only red glyph is the "PULSE / DATA" header dot (not the NNJ mark).
This CONFLICTS with the prior explicit one-mark decision (VISUAL-SINGLE-BRAND-MARK-1). Per
section 18 the safe reading is taken: V8 keeps ONE very restrained mark
(`mark_width_frac=0.040`, `mark_opacity=0.26` - lower than V7)
and the conflict is flagged for Founder review. If the Founder confirms the media should carry no
mark, `_HERO_MARK_OPACITY` -> 0 is a one-line change.

## 7. BREAKING media rectangle (section 19)

| quantity | value |
|---|---|
| media x, y | 18, 747 |
| media w, h | 322 x 165 (aspect ~1.95) |

The prior fixture crop `(28,764)-(346,907)` cut off the RIGHT of the media - the full-width pulse
line looked half-width. Re-extracted `tests/fixtures/founder_breaking_media_crop.png` at 322 x 165.

## 8. BREAKING pulse line (section 20)

| quantity | board | V8 |
|---|---|---|
| first -> last visible red px | x 39 -> 295 (media x-frac 0.065 -> 0.860) | start 0.065, width 0.795 -> end 0.860 |
| **BREAKING_LINE_TOTAL_WIDTH_FRAC** | **0.795** | **0.795** (V7 was 0.4245 - "baseline ends too early") |
| P-QRS-T event, of the COMPLETE line | starts ~0.19, spans ~0.27, calm tail ~0.54 | `_PULSE_WAVEFORM_UNIT` places it 0.20..0.51 (UNCHANGED - "do not change the waveform family again") |
| R apex | +20 px = 0.078 of the full-width line on the 322 media | `pulse_r_amp_frac_of_width=0.078` |
| baseline y | 905 -> media y-frac 0.958; S clips past the edge | `pulse_baseline_frac=0.972` + the layer clamps the deep S to the canvas edge so the pulse reads as attached to the lower edge |

## 9. BREAKING watermark - EFFECTIVE VISIBLE box, NOT the SVG width (section 21 / section 22)

| quantity | board (measured from grey strokes) | V8 |
|---|---|---|
| width frac of media | ~0.47 | `watermark_width_frac=0.47` |
| height frac of media | ~0.34 | proportional to the NNJ glyph |
| left x-frac in media | ~0.524 (entirely RIGHT of the centre line) | 1 - 0.006 - 0.47 = 0.524 |
| right inset frac | ~0.006 (flush) | 0.006 |
| bottom inset frac | ~0.012 (near flush) | 0.012 |
| effective opacity | ~0.12-0.20 over noise | drawn at **0.10** - a genuine background watermark |

V7 drew 0.50 wide with a 0.016 right inset -> x-frac 0.484..0.984, crossing the centre line. V8's
0.47 / 0.006 -> x-frac 0.524..0.994,
matching the board and living entirely in the right portion. Opacity is NOT increased for a bright
source (section 23) - the same 0.10 on dark and bright.
