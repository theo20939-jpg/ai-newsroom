"""MemeCopy (Phase 18 M4): the final text of a meme, produced by
`capabilities/meme_copywriting_capability.py::MemeCopywritingCapability` from an already-approved
`MemeConcept` (docs/phase18_m4_meme_copywriting_report.md).

Every field name and constraint is taken directly from the Phase 18 brief's own M4 list: top/
bottom overlay text, a short punchline, a Telegram preview caption, an optional editor
explanation, and alt/descriptive text - short, mobile-readable, no small text, no URL inside the
image itself, no duplication of the ordinary news wording, tone matched to the channel.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

MEME_COPY_SCHEMA_VERSION = "v1"

# Brief's own "без URL в самом изображении" requirement, enforced structurally: any field whose
# text ends up rendered ONTO the image (top/bottom overlay, the short punchline - never the
# Telegram caption or editor explanation, which live outside the image) must not contain a URL.
_URL_RE = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)

# Mobile-readability ceilings (brief's own "коротко / читаемо на телефоне / без мелкого текста"
# requirement) - enforced at the schema level, not left to prompt-only discipline, so a
# too-long overlay can never silently reach rendering (M6) or preview (M8).
_OVERLAY_TEXT_MAX_LENGTH = 80
_PUNCHLINE_MAX_LENGTH = 120
_CAPTION_MAX_LENGTH = 300
_ALT_TEXT_MAX_LENGTH = 200


class MemeCopy(BaseModel):
    """Frozen - a completed copywriting decision, never mutated in place (mirrors
    `schemas.meme_concept.MemeConcept`'s identical discipline). A regeneration produces a new
    `MemeCopy`, never edits an existing one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = MEME_COPY_SCHEMA_VERSION
    top_text: str = Field(min_length=1, max_length=_OVERLAY_TEXT_MAX_LENGTH)
    # Not every meme_format needs bottom text (e.g. MemeFormat.SINGLE_CAPTION) - None, never an
    # empty string, when the format doesn't call for it (keeps "field genuinely absent" distinct
    # from "field present but blank", mirroring schemas.capability.CapabilityUsage's own
    # "optional, not zero-defaulted" discipline).
    bottom_text: str | None = Field(default=None, max_length=_OVERLAY_TEXT_MAX_LENGTH)
    punchline_short: str = Field(min_length=1, max_length=_PUNCHLINE_MAX_LENGTH)
    telegram_caption: str = Field(min_length=1, max_length=_CAPTION_MAX_LENGTH)
    editor_explanation: str | None = Field(default=None, max_length=_CAPTION_MAX_LENGTH)
    alt_text: str = Field(min_length=1, max_length=_ALT_TEXT_MAX_LENGTH)
    # MEME-PROD-4: per-panel on-image captions for MemeConcept.panel_count == 4 (services/
    # meme_render.py's new quadrant-caption path) - None for panel_count 1/2, which continue to
    # use top_text/bottom_text exactly as before (zero behavior change for the common case).
    # Never both populated and unused - the orchestrator/renderer branch on whichever is present.
    panel_texts: list[str] | None = Field(default=None, min_length=4, max_length=4)

    @field_validator("top_text", "bottom_text", "punchline_short")
    @classmethod
    def _no_url_in_on_image_text(cls, value: str | None) -> str | None:
        if value is not None and _URL_RE.search(value):
            raise ValueError("on-image text (top_text/bottom_text/punchline_short) must not contain a URL")
        return value

    @field_validator("panel_texts")
    @classmethod
    def _panel_texts_valid(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        for panel_text in value:
            if not panel_text or len(panel_text) > _OVERLAY_TEXT_MAX_LENGTH:
                raise ValueError(
                    f"each panel_texts entry must be 1-{_OVERLAY_TEXT_MAX_LENGTH} characters, got {panel_text!r}"
                )
            if _URL_RE.search(panel_text):
                raise ValueError("panel_texts must not contain a URL")
        return value
