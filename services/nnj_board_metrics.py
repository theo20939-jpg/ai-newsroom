"""FOUNDER-VISUAL-BOARD-REBUILD-6 §20 - measured board proportions, one place, documented source.

Every value below is a DIRECT pixel measurement of `docs/founder_telegram_board.png` (visual
authority #1). CANVAS-COMPOSITION-CORRECTION-8 §2/§3/§19: the earlier reference crops were both
too tight - the DATA crop cut off the media BOTTOM (making a near-square media look ~4:3) and the
BREAKING crop cut off the RIGHT (making the full-width pulse line look half-width). Re-measured
against the ACTUAL media rectangles (Telegram chrome / caption / reactions / buttons excluded):

    BREAKING media   board (18,747)-(340,912)    322 x 165   (~1.95:1)
    DATA media       board (404,105)-(726,400)   322 x 295   (~1.09:1, NOT 16:9 and NOT 4:3)

    tests/fixtures/founder_breaking_media_crop.png  - re-extracted to the 322 x 165 rect
    tests/fixtures/founder_data_media_crop.png      - re-extracted to the 322 x 295 rect

Fractions are relative to the MEDIA rectangle the primitive is drawn onto: for BREAKING the source
photo (any aspect); for DATA the dedicated generated card, whose canvas is now the measured board
media aspect (1280 x 1172), NOT the old shared 16:9 default. No value here is an intuition or a
historical carry-over - if it is not measurable on the board it does not belong in this module.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BreakingBoardMetrics:
    # ==============================================================================================
    # FOUNDER-VISUAL-CANVAS-COMPOSITION-CORRECTION-8 §19-§23: re-measured against the ACTUAL BREAKING
    # MEDIA rectangle in docs/founder_telegram_board.png (the iPhone photo, excluding the headline /
    # Telegram chrome):   x = 18, y = 747, w = 322, h = 165   (aspect ~1.95).
    #
    #   * The red pulse LINE runs first->last visible red pixel x = 39 -> 295, i.e. media x-frac
    #     0.065 -> 0.860.  BREAKING_LINE_TOTAL_WIDTH_FRAC = 0.795  (V7 drew only 0.4245 -> the
    #     baseline stopped less than half way across; the Founder's "baseline ends too early").
    #   * The P-QRS-T event sits at media x-frac ~0.22..0.44 -> within the COMPLETE line it starts
    #     ~0.19 in, spans ~0.27, then a LONG calm tail ~0.54. The retained _PULSE_WAVEFORM_UNIT
    #     already places the complex at 0.20..0.51 of the drawn line (calm <=0.20 and >=0.62), which
    #     - now that the line is drawn full width - lands the event in the right place. Per the
    #     "do NOT change the waveform family again" constraint the unit path is UNCHANGED.
    #   * R apex +20px measured on the 322-wide media = 0.078 of the (now full-width) drawn line;
    #     S/R ~= 0.8 on the board, kept at 0.72 so the deep S clears a lowered baseline on a real
    #     photo. Baseline y = 905 -> media y-frac 0.958; the board lets its S clip past the media
    #     bottom, the runtime nudges the baseline to 0.972 and clamps the S to the canvas edge so
    #     the pulse reads as attached to the lower edge (Founder: "too independent from the edge").
    #   * stroke ~2px = 0.006 of the 322 media width; 0.0034 keeps it thin on a large source photo.
    # ==============================================================================================
    pulse_start_frac: float = 0.065
    pulse_width_frac: float = 0.795
    pulse_pre_flat_frac: float = 0.20        # calm baseline BEFORE the complex, of the drawn line
    pulse_complex_frac: float = 0.27         # the P-QRS-T span, of the drawn line
    #   (post-wave calm tail = 1 - pre - complex = 0.53 of the line)
    pulse_baseline_frac: float = 0.972       # board 0.958 + S clips the edge; runtime hugs + clamps S
    pulse_r_amp_frac_of_width: float = 0.078  # board R +20px / 0.795 full-width line on the 322 media
    pulse_s_over_r: float = 0.72
    pulse_apex_at_frac: float = 0.341        # x of the R apex within the P-QRS-T complex
    pulse_stroke_frac: float = 0.0034        # of media width - thin, clean

    # --- the restrained NNJ watermark, lower-right (§4/§22: background-level, NOT a primary element) --
    #   Re-measured from the EFFECTIVE VISIBLE grey strokes on the board (NOT the NNJ SVG box):
    #   the glyph occupies media x-frac ~0.524 -> ~0.994 (WIDTH 0.47), y-frac ~0.66 -> ~1.0
    #   (HEIGHT ~0.34), flush to the right edge (inset ~0.006) and near-flush to the bottom
    #   (inset ~0.012). It lives ENTIRELY in the right ~47% of the media - right of the centre line
    #   (Founder V7: "still too wide, should live primarily in the RIGHT portion"). Effective opacity
    #   measures ~0.12-0.20 over noise; drawn at 0.10 - a genuine background watermark.
    watermark_width_frac: float = 0.47
    watermark_right_inset_frac: float = 0.006
    watermark_bottom_inset_frac: float = 0.012
    watermark_grey_on_dark: tuple[int, int, int] = (140, 140, 140)   # light-grey over a dark photo
    watermark_grey_on_light: tuple[int, int, int] = (46, 46, 46)     # dark-grey over a light photo
    watermark_opacity: float = 0.10


@dataclass(frozen=True)
class DataBoardMetrics:
    # ==============================================================================================
    # FOUNDER-VISUAL-CANVAS-COMPOSITION-CORRECTION-8 §2/§3: the earlier DATA measurements were taken
    # against a crop that CUT OFF the bottom of the media, making it look ~4:3. The DATA MEDIA
    # rectangle in docs/founder_telegram_board.png (excluding Telegram chrome / caption / reactions
    # / buttons) is:
    #     x = 404, y = 105, w = 322, h = 295   ->   ASPECT = 322 / 295 = 1.0915  (near-square)
    # NOT 16:9 and not 4:3. Every fraction below is re-measured against THAT 322x295 media.
    # ==============================================================================================
    media_x: int = 404
    media_y: int = 105
    media_w: int = 322
    media_h: int = 295

    @property
    def aspect(self) -> float:
        return self.media_w / self.media_h

    # --- ground + technical grid ---
    bg_rgb: tuple[int, int, int] = (6, 7, 9)
    grid_rgb: tuple[int, int, int] = (13, 14, 17)
    grid_step_frac: float = 0.075               # grid spacing, of card width
    grid_luma_delta_max: int = 11              # contrast guard: grid luma - bg luma must be <= this
    grid_luma_delta_min: int = 5

    # --- typographic hierarchy (cap heights, fraction of MEDIA HEIGHT) ---
    #   "500"  y 46..94  -> top 0.156 h, cap height 0.163 h        (V7's 0.203 was of the WRONG crop)
    #   "МЛН"  = 0.75 x "500"                                       (measured 36/48)
    #   "ПОЛЬЗОВАТЕЛЕЙ" = 0.188 x "500"                             (measured  9/48)
    #   secondary line   ~= 0.21 x "500"
    value_top_frac: float = 0.156
    value_cap_frac: float = 0.163
    unit_over_value: float = 0.75
    label_over_value: float = 0.188
    desc_over_value: float = 0.21
    left_zone_frac: float = 0.41              # "500" right edge measured at x-frac 0.404

    # --- the trend line (re-measured on the 322x295 media) ---
    graph_x_start_frac: float = 0.34          # the chart begins right after the metric block
    graph_x_end_frac: float = 0.88            # ends short of the right edge
    graph_y_top_frac: float = 0.43            # curve endpoint (peak)
    graph_y_bottom_frac: float = 0.93         # curve origin (left end), near the media bottom
    graph_stroke_frac: float = 0.006          # of card width
    graph_endpoint_radius_frac: float = 0.0078  # small crisp dot (~5px on the 322 media)
    graph_fill_peak_alpha: int = 32          # line primary, fill very subtle
    graph_fill_falloff: float = 3.6
    graph_fill_band_frac: float = 0.24

    # --- NNJ mark: the board DATA MEDIA has NO visible canonical mark (0 red px in the corner) ->
    #   FOUNDER_DATA_MEDIA_MARK = ABSENT. This conflicts with the prior explicit one-mark decision
    #   (VISUAL-SINGLE-BRAND-MARK-1), so per §18 ONE very restrained mark is kept and the conflict
    #   is flagged for Founder review (see the report §M).
    mark_width_frac: float = 0.040
    mark_opacity: float = 0.26            # even lower than V7 - the board shows none

    # --- the dedicated generated-DATA output canvas (§4/§6) -----------------------------------------
    #   DATA_16_9_REQUIRED = false (Telegram accepts non-16:9 photo media; 16:9 was a shared
    #   renderer default, not a platform rule). Width is kept at the existing production-safe
    #   1280; height is derived from the measured board aspect:  1280 * 295 / 322 = 1172.6 -> 1172.
    canvas_w: int = 1280
    canvas_h: int = 1172


BREAKING = BreakingBoardMetrics()
DATA = DataBoardMetrics()
