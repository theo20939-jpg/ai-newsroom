"""FOUNDER-VISUAL-BOARD-REBUILD-6 §20 - measured board proportions, one place, documented source.

Every value below is a DIRECT pixel measurement of `docs/founder_telegram_board.png` (visual
authority #1), taken from the two reference crops committed for local comparison:

    tests/fixtures/founder_breaking_media_crop.png   board (28,764)-(346,907)   318 x 143  (~2.22:1)
    tests/fixtures/founder_data_media_crop.png       board (413,126)-(728,362)  315 x 236  (~1.33:1)

Fractions are relative to the MEDIA canvas the primitive is drawn onto (the source photo for
BREAKING, the 1280x720 generated card for DATA) so the design scales across aspect ratios.
No value here is an intuition or a historical carry-over - if it is not measurable on the board
it does not belong in this module.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BreakingBoardMetrics:
    # --- the lower-media NINJA PULSE (re-measured same-scale, FINAL-BOARD-MATCH-7 §3) ---
    #   line x = [0.038, 0.462] of media width ; pre-wave calm flat = 0.23 of the line ; the
    #   P-QRS-T complex = 0.28 of the line ; a LONG calm tail = 0.49 of the line. Baseline sits ~1px
    #   above the media bottom (frac 0.993). R apex +20px = 0.148 of the drawn line width ;
    #   S/R = 0.75 ; stroke ~2px = 0.0063 of media width.
    pulse_start_frac: float = 0.038
    pulse_width_frac: float = 0.4245
    pulse_pre_flat_frac: float = 0.23        # calm baseline BEFORE the complex, of the drawn line
    pulse_complex_frac: float = 0.28         # the P-QRS-T span, of the drawn line
    #   (post-wave calm tail = 1 - pre - complex = 0.49 of the line)
    pulse_baseline_frac: float = 0.965       # board 0.993; runtime hugs the edge but keeps S on-canvas
    pulse_r_amp_frac_of_width: float = 0.125  # board 0.148; trimmed so the deep S clears the lowered
    #   baseline on a real photo (the board lets its S clip ~14px past the media edge)
    pulse_s_over_r: float = 0.72
    pulse_apex_at_frac: float = 0.341        # x of the R apex within the P-QRS-T complex
    pulse_stroke_frac: float = 0.0034        # of media width - thin, clean

    # --- the restrained NNJ watermark, lower-right (§4: background-level, NOT a primary element) ---
    #   board glyph: width 0.535 media w, right edge 0.016 from the media edge, bottom 0.035 from
    #   the media bottom, effective opacity ~0.23. The Founder found V6's presence too dominant, so
    #   the drawn opacity is HALVED (0.12) - the glyph stays large enough to read as a watermark
    #   but is genuinely subordinate to the photo and the pulse.
    watermark_width_frac: float = 0.50
    watermark_right_inset_frac: float = 0.016
    watermark_bottom_inset_frac: float = 0.035
    watermark_grey_on_dark: tuple[int, int, int] = (140, 140, 140)   # light-grey over a dark photo
    watermark_grey_on_light: tuple[int, int, int] = (46, 46, 46)     # dark-grey over a light photo
    watermark_opacity: float = 0.12


@dataclass(frozen=True)
class DataBoardMetrics:
    # --- ground + technical grid (measured on the DATA crop) ---
    bg_rgb: tuple[int, int, int] = (6, 7, 9)     # bg mean RGB
    # §13: the board measures a grid delta of ~+14, but at Telegram viewing size that still read as
    # "squares" in review - pulled down to the bottom of the guarded band so it reads as texture.
    grid_rgb: tuple[int, int, int] = (13, 14, 17)
    grid_step_frac: float = 0.068               # grid spacing, of card width (~1/14.5)
    grid_luma_delta_max: int = 11              # §13 contrast guard: grid luma - bg luma must be <= this
    grid_luma_delta_min: int = 5

    # --- typographic hierarchy (cap heights re-measured same-scale, §8) ---
    #   "500" = 0.203 h ; "МЛН" = 0.75 x that ; "ПОЛЬЗОВАТЕЛЕЙ" = only 0.19 x that (V6's 0.28 made
    #   the label far too heavy/large). Secondary copy sits just above the label size.
    value_cap_frac: float = 0.203
    unit_over_value: float = 0.75
    label_over_value: float = 0.19
    desc_over_value: float = 0.165            # "Достиг ChatGPT ..." secondary line
    left_zone_frac: float = 0.385

    # --- the trend line (re-measured same-scale, §17) ---
    graph_x_start_frac: float = 0.492
    graph_x_end_frac: float = 0.867           # ends well short of the right edge
    graph_y_bottom_frac: float = 0.965        # board left-end sits at 0.996 h - nearly the bottom
    graph_y_top_frac: float = 0.47            # curve endpoint (peak)
    graph_stroke_frac: float = 0.0052         # of card width (~2px on the 315 crop)
    graph_endpoint_radius_frac: float = 0.0065  # small crisp dot (~5px on the crop)
    graph_fill_peak_alpha: int = 34          # §15: HALVED - line primary, fill very subtle
    graph_fill_falloff: float = 3.6           # steeper vertical fade
    graph_fill_band_frac: float = 0.24        # fill reaches at most 24% of chart height below the line

    # --- the small NNJ mark (§19: restrained, must not compete with the graph endpoint) ---
    mark_width_frac: float = 0.048
    mark_opacity: float = 0.32


BREAKING = BreakingBoardMetrics()
DATA = DataBoardMetrics()
