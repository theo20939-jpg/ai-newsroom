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
    # --- the lower-media NINJA PULSE (measured on the BREAKING crop) ---
    pulse_start_frac: float = 0.038          # left inset of the waveform, of media width
    pulse_width_frac: float = 0.425          # total drawn width of the waveform, of media width
    pulse_baseline_frac: float = 0.95        # calm-baseline Y, of media height
    #   board is 0.993 (baseline sits ON the photo's bottom edge and the S-wave dips just past it);
    #   the runtime uses 0.95 so the deep S undershoot always stays on-canvas.
    pulse_r_amp_frac_of_width: float = 0.148  # R apex height above baseline, as a fraction of the
    #   drawn width (NOT of canvas height - keeps the waveform's own proportions on any aspect)
    pulse_s_over_r: float = 0.70             # S trough depth / R apex height  (deep, measured)
    pulse_apex_at_frac: float = 0.341        # x of the R apex, as a fraction of the drawn width
    pulse_stroke_frac: float = 0.0032        # stroke width, of media width (thin, ~1px on the crop)

    # --- the restrained LARGE NNJ watermark (lower-right of the media) ---
    watermark_width_frac: float = 0.44       # of media width (a big, quiet glyph - not a corner mark)
    watermark_right_inset_frac: float = 0.016  # right edge -> media right edge
    watermark_bottom_inset_frac: float = 0.02  # glyph bottom -> media bottom
    watermark_grey_on_dark: tuple[int, int, int] = (150, 150, 150)  # light-grey over a dark photo
    watermark_grey_on_light: tuple[int, int, int] = (70, 70, 70)     # dark-grey over a light photo
    watermark_opacity: float = 0.20         # measured: glyph mean RGB ~=(56,56,56) over a ~15 ground
    watermark_gap_from_pulse_frac: float = 0.085  # pulse end -> watermark left


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

    # --- typographic hierarchy (cap heights measured on the crop, as fractions of card height) ---
    value_cap_frac: float = 0.203             # "500"
    unit_over_value: float = 0.76             # "МЛН" cap height / "500" cap height (measured 36/48)
    label_over_value: float = 0.28            # "ПОЛЬЗОВАТЕЛЕЙ" / "500"
    left_zone_frac: float = 0.385             # "500" right edge -> left text column width

    # --- the trend line (measured on the crop) ---
    graph_x_start_frac: float = 0.49          # of card width
    graph_x_end_frac: float = 0.87            # of card width (ends short of the right edge)
    graph_y_bottom_frac: float = 0.90         # curve origin (left end), of card height
    graph_y_top_frac: float = 0.47            # curve endpoint (right end / peak), of card height
    graph_stroke_frac: float = 0.006          # of card width (~2px on the 315 crop)
    graph_endpoint_radius_frac: float = 0.006  # white dot radius, of card width (~5px on the crop)
    graph_fill_peak_alpha: int = 70          # under-curve tint: ~=(50,12,11) 18px below the line
    graph_fill_falloff: float = 3.0           # steep vertical fade - no red wedge

    # --- the small NNJ mark ---
    mark_width_frac: float = 0.055           # of card width (restrained; not a CTA badge)
    mark_opacity: float = 0.55


BREAKING = BreakingBoardMetrics()
DATA = DataBoardMetrics()
