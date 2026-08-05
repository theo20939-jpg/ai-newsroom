"""Phase 18 M4: MemeCopy schema tests (docs/phase18_m4_meme_copywriting_report.md)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from capabilities.capability_mapping import resolve_ai_capability
from database.models.ai_execution import AICapability
from schemas.meme_copy import MemeCopy

_VALID_KWARGS = dict(
    top_text="AI WON'T TAKE YOUR JOB",
    bottom_text="SAYS GUY WHOSE JOB IS AI",
    punchline_short="The one job AI can't replace.",
    telegram_caption="From today's keynote.",
    editor_explanation="Plays on the irony.",
    alt_text="A CEO on stage pointing at a slide.",
)


def test_meme_copy_is_frozen() -> None:
    copy = MemeCopy(**_VALID_KWARGS)
    with pytest.raises(ValidationError):
        copy.top_text = "changed"  # type: ignore[misc]


def test_meme_copy_allows_bottom_text_and_editor_explanation_to_be_none() -> None:
    kwargs = {**_VALID_KWARGS, "bottom_text": None, "editor_explanation": None}
    copy = MemeCopy(**kwargs)
    assert copy.bottom_text is None
    assert copy.editor_explanation is None


@pytest.mark.parametrize("field", ["top_text", "bottom_text", "punchline_short"])
def test_url_in_on_image_text_is_rejected(field: str) -> None:
    kwargs = {**_VALID_KWARGS, field: "Check https://example.com/story for details"}
    with pytest.raises(ValidationError):
        MemeCopy(**kwargs)


def test_url_in_telegram_caption_is_allowed() -> None:
    """The caption lives outside the rendered image - a source link there is fine."""
    kwargs = {**_VALID_KWARGS, "telegram_caption": "Source: https://example.com/story"}
    copy = MemeCopy(**kwargs)
    assert "https://example.com/story" in copy.telegram_caption


def test_overlong_top_text_is_rejected() -> None:
    kwargs = {**_VALID_KWARGS, "top_text": "x" * 200}
    with pytest.raises(ValidationError):
        MemeCopy(**kwargs)


def test_meme_copy_rejects_unknown_field() -> None:
    kwargs = {**_VALID_KWARGS, "unexpected_field": "x"}
    with pytest.raises(ValidationError):
        MemeCopy(**kwargs)


def test_meme_copywriting_capability_maps_to_copywriting_ai_capability() -> None:
    assert resolve_ai_capability("meme_copywriting") == AICapability.COPYWRITING
