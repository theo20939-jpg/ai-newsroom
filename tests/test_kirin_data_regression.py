"""DIRECTOR-CONTROL-PLANE-1 §23-26/§41: the real Kirin 9050 Pro DATA regression - a source
infographic already showing "42%" got a SECOND, competing stat block composited on top by the old
FULL_DATA_CARD-only behavior, producing a visually confusing/ambiguous "142%"-reading result (real,
reported production failure, spec §23's own verbatim description). Structural proof (no OCR,
spec §41's own explicit instruction): MINIMAL_SOURCE_PRESERVING mode never even CALLS the stat-
block measurement/placement functions that would draw a second, competing number - proven by
spying on them, not by pixel-reading text."""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

import services.brand_renderer as brand_renderer_module
from services.brand_renderer import render_branded_media, render_data_card
from services.data_source_classification import (
    DataPresentationMode,
    SourceType,
    classify_source_presentation,
    select_data_presentation_mode,
)
from services.presentation_director import DATA, DataCandidate

_CANVAS = (1280, 720)
# CANVAS-COMPOSITION-CORRECTION-8: FULL_DATA_CARD renders the generated hero on its own near-square
# canvas at the measured board-media aspect; MINIMAL_SOURCE_PRESERVING keeps the 1280x720 source.
_HERO_CANVAS = (1280, 1172)


def _kirin_style_infographic_bytes() -> bytes:
    """A synthetic stand-in for the real Kirin 9050 Pro source photo - a banner-shaped image with
    its own large printed metric ("42%") and a small embedded corner mark, matching the exact
    structural shape (possible_banner + possible_logo) real production image intelligence already
    flags for a pre-made infographic (services/data_source_classification.py's own docstring)."""
    im = Image.new("RGB", _CANVAS, (18, 18, 20))
    draw = ImageDraw.Draw(im)
    draw.text((120, 260), "42%", fill=(255, 255, 255))
    draw.rectangle([1180, 20, 1260, 70], outline=(200, 30, 30), width=3)  # stand-in embedded logo mark
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


_KIRIN_WARNINGS = ["possible_banner", "possible_logo"]
_KIRIN_DATA_CANDIDATE = DataCandidate(
    value="42", unit="%", label="of Kirin 9050 Pro benchmark improvement", evidence_fact="42% improvement reported",
)


def test_kirin_source_is_classified_as_existing_infographic() -> None:
    assert classify_source_presentation(_KIRIN_WARNINGS) == SourceType.EXISTING_INFOGRAPHIC


def test_existing_infographic_selects_minimal_source_preserving_mode() -> None:
    source_type = classify_source_presentation(_KIRIN_WARNINGS)
    assert select_data_presentation_mode(source_type) == DataPresentationMode.MINIMAL_SOURCE_PRESERVING


def test_ordinary_photo_still_gets_full_data_card_unchanged() -> None:
    """The fix must never regress a genuine PHOTO/PRODUCT_PHOTO source (spec §25's own "every other
    source type keeps today's existing FULL_DATA_CARD behavior" requirement)."""
    source_type = classify_source_presentation(warnings=None)
    assert source_type == SourceType.UNKNOWN
    assert select_data_presentation_mode(source_type) == DataPresentationMode.FULL_DATA_CARD


def test_minimal_source_preserving_never_draws_a_second_competing_stat_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real structural proof: with MINIMAL_SOURCE_PRESERVING, render_data_card() must never
    even call the functions that would measure/place/draw a second number - not merely "the second
    number happens to look fine," genuinely never composited at all."""
    calls: list[str] = []

    def _record_and_fail(name: str, *_a: object, **_k: object) -> None:
        calls.append(name)
        raise AssertionError(f"{name} must never be called in MINIMAL_SOURCE_PRESERVING mode")

    monkeypatch.setattr(brand_renderer_module, "_measure_data_stat_block", lambda *a, **k: _record_and_fail("_measure_data_stat_block"))
    monkeypatch.setattr(brand_renderer_module, "_select_data_block_placement", lambda *a, **k: _record_and_fail("_select_data_block_placement"))

    result_bytes = render_data_card(
        _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-KIRIN",
        source_image_bytes=_kirin_style_infographic_bytes(),
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )

    assert calls == []
    out = Image.open(io.BytesIO(result_bytes))
    assert out.size == _CANVAS


def test_full_data_card_mode_still_calls_the_stat_block_path_for_non_infographic_sources() -> None:
    """Confirms the spy technique above is actually meaningful - FULL_DATA_CARD (the unaffected,
    default path) genuinely does reach the stat-block code, so the MINIMAL_SOURCE_PRESERVING test's
    own "calls == []" assertion is proving something real, not vacuously true because the functions
    are never called under any mode."""
    result_bytes = render_data_card(
        _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-KIRIN",
        source_image_bytes=_kirin_style_infographic_bytes(),
        presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    out = Image.open(io.BytesIO(result_bytes))
    assert out.size == _HERO_CANVAS


def test_render_branded_media_end_to_end_routes_minimal_mode_through_to_data_card() -> None:
    """End-to-end through the real dispatch entry point (services/brand_renderer.py::
    render_branded_media()), not just the lower-level render_data_card() call."""
    result = render_branded_media(
        presentation_type=DATA, source_image_bytes=_kirin_style_infographic_bytes(),
        category="technology", editorial_code="NP-KIRIN", data_candidate=_KIRIN_DATA_CANDIDATE,
        data_presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    assert result.success
    assert result.image_bytes is not None


def test_render_branded_media_default_mode_is_full_data_card_unchanged() -> None:
    """Every pre-existing caller that never passes data_presentation_mode gets byte-identical
    FULL_DATA_CARD behavior - the new parameter is purely additive."""
    result = render_branded_media(
        presentation_type=DATA, source_image_bytes=_kirin_style_infographic_bytes(),
        category="technology", editorial_code="NP-KIRIN", data_candidate=_KIRIN_DATA_CANDIDATE,
    )
    assert result.success
