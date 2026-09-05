"""MemeRenderResult (Phase 18 M6): the outcome of deterministically overlaying `MemeCopy`'s
top/bottom text onto a generated meme image (docs/phase18_m6_meme_rendering_report.md).

Never carries raw image bytes - only a storage reference, mirroring `schemas.meme_image.
MemeImageGenerationResult`'s identical discipline.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

MEME_RENDER_SCHEMA_VERSION = "v1"


class MemeRenderStatus(str, Enum):
    RENDERED = "rendered"
    FAILED = "failed"


class MemeRenderResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = MEME_RENDER_SCHEMA_VERSION
    status: MemeRenderStatus
    storage_key: str | None = None
    width: int | None = None
    height: int | None = None
    byte_size: int | None = None
    sha256: str | None = None
    # WCAG-style contrast ratio (1.0-21.0) between the chosen text color and the measured average
    # background luminance behind it - None when that band's text was absent (e.g. no
    # bottom_text) or rendering failed before reaching that band.
    top_text_contrast_ratio: float | None = None
    bottom_text_contrast_ratio: float | None = None
    # MEME-PROD-4: one entry per panel (in panel order), only for the 4-quadrant panel_texts
    # render path - None for the classic top/bottom path (mirrors top_text_contrast_ratio/
    # bottom_text_contrast_ratio's own "None means this path wasn't used" convention).
    panel_text_contrast_ratios: list[float] | None = None
    # False if EITHER present band's measured ratio fell below the minimum-readability threshold
    # (services/meme_render.py::_MIN_CONTRAST_RATIO) - a real, computed check, never assumed.
    contrast_passed: bool = True
    # Non-empty when a line had to be truncated to fit its safe zone even at the smallest
    # supported font size - never silently overflowed into the center "key object" zone instead.
    safe_zone_violations: list[str] = Field(default_factory=list)
    error_code: str | None = None
