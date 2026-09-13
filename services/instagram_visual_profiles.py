"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 6/8: the ONE centralized definition of every Instagram
render profile (canvas geometry, safe zones) and the ONE repo-relative, container-safe font/brand
asset resolution point for the Instagram renderer.

Deliberately independent of `services/brand_renderer.py` (the Founder-approved, FROZEN Telegram V8
renderer) - this module imports nothing from it and it imports nothing from here
(TELEGRAM_V8_RUNTIME_CHANGED=false). It reuses the SAME bundled Fira Sans Condensed files
(assets/brand/fonts/, SIL OFL 1.1) and the SAME canonical NNJ mark rasterizer
(services/nnj_master_news_mark.py::rasterize_nnj_mark) - both are brand-neutral, already-approved
assets shared across every NINJA surface, not Telegram-renderer internals. No new font/asset
dependency is introduced (section 8's own "no new external font dependency without explicit
justification").

Instagram's own platform geometry (not Telegram's, not invented from a Telegram card resized):
  PORTRAIT_FEED   1080x1350 (4:5)   - Instagram's maximum-height feed post, the platform's own
                                      recommended default (more canvas than 1:1 for the same width).
  SQUARE_FEED     1080x1080 (1:1)   - the classic square feed post.
  CAROUSEL_SLIDE  1080x1350 (4:5)   - same aspect as PORTRAIT_FEED so every slide in one carousel
                                      shares one consistent visual system (section 10's own
                                      requirement) - carousel slides are cropped identically by
                                      Instagram's own feed renderer regardless of slide index.
  REEL_COVER      1080x1920 (9:16)  - the Reel/Story frame a cover image sits inside.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageFont

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FONT_DIR = _REPO_ROOT / "assets" / "brand" / "fonts"

_FONT_FILES: dict[str, str] = {
    "black": "FiraSansCondensed-Black.ttf",
    "semibold": "FiraSansCondensed-SemiBold.ttf",
    "medium": "FiraSansCondensed-Medium.ttf",
    "regular": "FiraSansCondensed-Regular.ttf",
    "bold": "FiraSansCondensed-Bold.ttf",
}


class InstagramRenderProfile(str, enum.Enum):
    PORTRAIT_FEED = "portrait_feed"
    SQUARE_FEED = "square_feed"
    CAROUSEL_SLIDE = "carousel_slide"
    REEL_COVER = "reel_cover"


@dataclass(frozen=True)
class ProfileSpec:
    """One render profile's full geometry. `safe_top_frac`/`safe_bottom_frac` mark the fraction of
    canvas height at the top/bottom a renderer must keep clear of load-bearing content - Instagram's
    OWN UI chrome (profile header above a feed post; the caption/like/share bar below it; the
    Reels/Stories full-screen overlay - progress bar, account name, caption, action icons - drawn
    OVER a Reel/Story frame by the Instagram app itself, never by this renderer). No UI chrome is
    ever drawn INTO the image (section 6's own explicit instruction) - the safe zone exists purely
    so this renderer's own content does not collide with chrome Instagram draws later."""

    width: int
    height: int
    safe_top_frac: float
    safe_bottom_frac: float
    safe_side_frac: float

    @property
    def aspect(self) -> float:
        return self.width / self.height


# Centralized - the ONE place any renderer/test reads a profile's geometry from.
INSTAGRAM_RENDER_PROFILES: dict[InstagramRenderProfile, ProfileSpec] = {
    InstagramRenderProfile.PORTRAIT_FEED: ProfileSpec(
        width=1080, height=1350, safe_top_frac=0.03, safe_bottom_frac=0.03, safe_side_frac=0.05,
    ),
    InstagramRenderProfile.SQUARE_FEED: ProfileSpec(
        width=1080, height=1080, safe_top_frac=0.03, safe_bottom_frac=0.03, safe_side_frac=0.05,
    ),
    InstagramRenderProfile.CAROUSEL_SLIDE: ProfileSpec(
        width=1080, height=1350, safe_top_frac=0.03, safe_bottom_frac=0.03, safe_side_frac=0.05,
    ),
    # Reels/Stories: the app draws a progress bar + account chip near the top and a caption/action
    # column near the bottom/right OVER the frame - a materially larger safe margin than a static
    # feed post needs.
    InstagramRenderProfile.REEL_COVER: ProfileSpec(
        width=1080, height=1920, safe_top_frac=0.14, safe_bottom_frac=0.22, safe_side_frac=0.06,
    ),
}


def profile_spec(profile: InstagramRenderProfile) -> ProfileSpec:
    return INSTAGRAM_RENDER_PROFILES[profile]


def ig_font_path(weight: str = "regular") -> Path:
    """The absolute, repo-relative path of the bundled font for `weight`. Container-safe: resolved
    from `__file__`, never a Windows/host/Desktop path."""
    return (_FONT_DIR / _FONT_FILES.get(weight, _FONT_FILES["regular"])).resolve()


_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def ig_font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    """Loads the bundled Fira Sans Condensed face at `size`. Deterministic and cached. Raises
    (never silently substitutes a host font) if the bundled file is somehow missing - an Instagram
    render must never silently drift onto a different, unapproved typeface."""
    key = (weight, int(size))
    hit = _font_cache.get(key)
    if hit is not None:
        return hit
    font = ImageFont.truetype(str(ig_font_path(weight)), size)
    _font_cache[key] = font
    return font


@lru_cache(maxsize=4)
def ig_brand_mark(*, target_width: int, red: bool = True) -> Image.Image:
    """The ONE canonical NNJ mark, reused read-only from the shared, brand-neutral rasterizer -
    never generatively redrawn (section 7). Cached (the underlying SVG parse + rasterize is pure
    and deterministic)."""
    from services.nnj_master_news_mark import rasterize_nnj_mark

    return rasterize_nnj_mark(target_width=target_width, red=red)
