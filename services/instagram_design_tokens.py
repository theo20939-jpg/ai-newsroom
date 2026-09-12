"""INSTAGRAM-VISUAL-SYSTEM-V1-1 section 16: centralized Instagram design tokens. Every spacing,
color, font-size, logo-sizing, and overlay constant the Instagram visual layout modules use lives
HERE - no scattered magic numbers in the layout modules themselves.

Independent of Telegram V8 (`services/brand_renderer.py` and friends remain untouched and
unimported) - this is a fresh, Instagram-native token set, not a resize/reuse of Telegram's
constants. Reuses only the brand-neutral shared assets already established in
`services/instagram_visual_profiles.py` (bundled Fira Sans Condensed, the canonical NNJ mark)."""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------------------------
# Palette - one small, deliberate set. Red is an ACCENT (kicker chips, rules, the brand mark),
# never a full-canvas wash (section 1's own "not by adding more red" instruction).
# ---------------------------------------------------------------------------------------------
INK = (10, 11, 13)              # near-black canvas/panel ground
INK_RAISED = (20, 22, 26)       # a slightly lighter structural panel, for layered depth
PAPER = (245, 246, 248)         # near-white, used sparingly (framed-variant margins)
WHITE = (247, 248, 250)
GREY_STRONG = (198, 202, 209)   # secondary copy on dark
GREY_SOFT = (140, 145, 154)     # tertiary/metadata copy on dark
RED = (218, 30, 38)             # NNJ red - accents only
RED_DEEP = (140, 18, 24)        # a darker red for gradients/panels behind red kickers

# ---------------------------------------------------------------------------------------------
# Spacing / margins - fractions of canvas WIDTH unless noted, so they scale across profiles.
# ---------------------------------------------------------------------------------------------
MARGIN_FRAC = 0.08               # the standard content margin from any canvas edge
TIGHT_MARGIN_FRAC = 0.06
PANEL_PADDING_FRAC = 0.07        # padding inside a solid text panel (split/quote layouts)

# ---------------------------------------------------------------------------------------------
# Safe zones (fractions of canvas HEIGHT) - kept here as the Instagram-wide defaults;
# services/instagram_visual_profiles.py's own per-profile safe zones remain the authority for
# REEL_COVER's larger app-chrome allowance - layouts read from there for exact bounds.
# ---------------------------------------------------------------------------------------------
FEED_SAFE_TOP_FRAC = 0.03
FEED_SAFE_BOTTOM_FRAC = 0.03

# ---------------------------------------------------------------------------------------------
# Typography hierarchy - named ROLES, not raw sizes; every layout asks for a role and gets a
# fraction of canvas WIDTH (condensed faces read consistently sized relative to width, not height,
# across the 4:5 / 1:1 / 9:16 profiles this system spans).
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TypeRole:
    size_frac: float           # of canvas width
    weight: str                # bundled Fira Sans Condensed weight name
    max_lines: int
    color: tuple[int, int, int]


TYPE_KICKER = TypeRole(size_frac=0.032, weight="semibold", max_lines=1, color=GREY_STRONG)
TYPE_KICKER_ACCENT = TypeRole(size_frac=0.032, weight="semibold", max_lines=1, color=WHITE)  # on a red chip
TYPE_HEADLINE_L = TypeRole(size_frac=0.088, weight="black", max_lines=4, color=WHITE)
TYPE_HEADLINE_M = TypeRole(size_frac=0.072, weight="black", max_lines=4, color=WHITE)
TYPE_HEADLINE_S = TypeRole(size_frac=0.058, weight="black", max_lines=5, color=WHITE)
TYPE_DEK = TypeRole(size_frac=0.034, weight="medium", max_lines=3, color=GREY_STRONG)
TYPE_METRIC = TypeRole(size_frac=0.24, weight="black", max_lines=1, color=WHITE)
TYPE_METRIC_UNIT = TypeRole(size_frac=0.10, weight="black", max_lines=1, color=RED)
TYPE_METRIC_LABEL = TypeRole(size_frac=0.040, weight="semibold", max_lines=2, color=WHITE)
TYPE_METRIC_CONTEXT = TypeRole(size_frac=0.030, weight="medium", max_lines=3, color=GREY_STRONG)
TYPE_QUOTE_MARK = TypeRole(size_frac=0.14, weight="black", max_lines=1, color=RED)
TYPE_QUOTE_BODY = TypeRole(size_frac=0.052, weight="semibold", max_lines=8, color=WHITE)
TYPE_QUOTE_NAME = TypeRole(size_frac=0.036, weight="black", max_lines=1, color=WHITE)
TYPE_QUOTE_ROLE = TypeRole(size_frac=0.028, weight="medium", max_lines=2, color=GREY_SOFT)
TYPE_SLIDE_INDEX = TypeRole(size_frac=0.026, weight="semibold", max_lines=1, color=GREY_SOFT)
TYPE_CTA = TypeRole(size_frac=0.036, weight="semibold", max_lines=1, color=WHITE)

# ---------------------------------------------------------------------------------------------
# Logo sizing - the ONE canonical mark, sized by role. Restrained everywhere (section 15) - no
# giant watermark unless the format explicitly needs one (none in this system do).
# ---------------------------------------------------------------------------------------------
LOGO_WIDTH_FRAC_STANDARD = 0.065
LOGO_WIDTH_FRAC_COMPACT = 0.05     # carousel slides / reel cover - even more restrained
LOGO_MARGIN_FRAC = MARGIN_FRAC

# ---------------------------------------------------------------------------------------------
# Accent rules / geometry
# ---------------------------------------------------------------------------------------------
ACCENT_RULE_WIDTH_FRAC = 0.14      # a short red rule under a kicker/eyebrow
ACCENT_RULE_THICKNESS_PX = 6
CORNER_RADIUS_FRAC = 0.02          # rounded corners on chips/panels/frames

# ---------------------------------------------------------------------------------------------
# Image-overlay presets (services/instagram_image_handling.py consumes these) - readability
# gradients, never a flat "darken everything" scrim (section 13's own "controlled darkening").
# ---------------------------------------------------------------------------------------------
GRADIENT_BOTTOM_HEIGHT_FRAC = 0.55   # how tall the bottom readability gradient reaches up the frame
GRADIENT_BOTTOM_MAX_ALPHA = 235
GRADIENT_TOP_HEIGHT_FRAC = 0.30
GRADIENT_TOP_MAX_ALPHA = 200

# BREAKING-specific: a stronger, redder top treatment (section 8 - "NINJA red as an ACCENT, not a
# full cheap-looking overlay" - so this still eases to transparent, it is simply tinted).
BREAKING_ACCENT_GRADIENT_HEIGHT_FRAC = 0.22
BREAKING_ACCENT_GRADIENT_MAX_ALPHA = 190

# ---------------------------------------------------------------------------------------------
# Fallback background (no source image supplied - section 14) - a structured, deliberate
# composition, never a blank rectangle.
# ---------------------------------------------------------------------------------------------
FALLBACK_BLOCK_COUNT = 3
FALLBACK_BLOCK_ALPHA = 90          # a clearly visible but still restrained raised panel
FALLBACK_GRID_STEP_FRAC = 0.09
FALLBACK_GRID_ALPHA = 46           # a genuinely (not just nominally) faint technical grid line -
# these two values are real alpha-compositing inputs (services/instagram_image_handling.py::
# draw_with_alpha actually blends them against the canvas), not decorative constants that get
# silently discarded by a later `.convert("RGB")`.
