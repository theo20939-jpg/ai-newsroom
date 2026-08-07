"""Phase 19 M9: services.image_quality's three new deterministic pre-filter signals
(watermark-token evidence, TV/lower-third heuristic, branded-screenshot heuristic). Same
in-memory-Pillow-fixture convention as tests/test_image_quality.py - no network.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from uuid import uuid4

from PIL import Image

from database.models.news_source import SourceType
from schemas.image_candidate import ImageCandidate, ImageCandidateStatus, ImageDiscoveryMethod, TechnicalValidation
from services.image_quality import analyze_candidate


def _candidate(
    url: str | None, width: int, height: int, *, alt: str | None = None,
) -> ImageCandidate:
    return ImageCandidate(
        candidate_id=f"c-{uuid4()}", event_id=uuid4(), source_type=SourceType.RSS,
        discovery_method=ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, status=ImageCandidateStatus.VALIDATED,
        remote_url=url, alt_text=alt, discovery_order=0, discovered_at=datetime.now(timezone.utc),
        technical_validation=TechnicalValidation(
            width=width, height=height, format="PNG", error_code=None,
            pixel_count=width * height, byte_size=1000,
        ),
    )


def _textured_image(width: int, height: int) -> Image.Image:
    """A deterministic, non-flat pattern (diagonal gradient) - representative of real editorial
    photography's pixel variance, unlike a single flat color."""
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = ((x * 3 + y * 7) % 256, (x * 5) % 256, (y * 11) % 256)
    return image


def _image_with_flat_bottom_band(width: int, height: int, band_fraction: float) -> Image.Image:
    """A textured upper region with a solid-color band across the bottom `band_fraction` of the
    frame - the shape of a TV lower-third graphic overlaid on broadcast footage."""
    image = _textured_image(width, height)
    band_start = int(height * (1 - band_fraction))
    solid = Image.new("RGB", (width, height - band_start), color=(20, 20, 20))
    image.paste(solid, (0, band_start))
    return image


def _flat_striped_image(width: int, height: int) -> Image.Image:
    """Many perfectly flat horizontal rows, alternating between two colors - the shape of UI
    chrome (toolbars, flat-color panels), unlike the smooth continuous gradient of a photo."""
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        color = (200, 200, 200) if (y // 4) % 2 == 0 else (210, 210, 210)
        for x in range(width):
            pixels[x, y] = color
    return image


def _bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _analyze(image: Image.Image, url: str | None = None, alt: str | None = None) -> object:
    width, height = image.size
    candidate = _candidate(url, width, height, alt=alt)
    return analyze_candidate(_bytes(image), candidate=candidate)


# --- watermark: token-evidence only ---------------------------------------------------------


def test_watermark_token_in_url_flags_possible_watermark() -> None:
    result = _analyze(_textured_image(800, 600), url="https://example.com/photo-watermark.jpg")
    assert result.signals.possible_watermark is True
    assert "possible_watermark" in result.quality_warnings


def test_watermark_token_in_alt_text_flags_possible_watermark() -> None:
    result = _analyze(_textured_image(800, 600), alt="Watermarked stock photo")
    assert result.signals.possible_watermark is True


def test_no_watermark_token_does_not_flag() -> None:
    result = _analyze(_textured_image(800, 600), url="https://example.com/photo.jpg")
    assert result.signals.possible_watermark is False


def test_watermark_signal_never_hard_rejects() -> None:
    result = _analyze(_textured_image(800, 600), url="https://example.com/photo-watermark.jpg")
    assert result.hard_rejection_reasons == []


# --- TV / lower-third heuristic ---------------------------------------------------------------


def test_16_9_image_with_flat_bottom_band_flags_possible_tv_lower_third() -> None:
    image = _image_with_flat_bottom_band(1280, 720, band_fraction=0.22)
    result = _analyze(image)
    assert result.signals.possible_tv_lower_third is True
    assert "possible_tv_lower_third" in result.quality_warnings
    assert result.hard_rejection_reasons == []


def test_textured_16_9_image_without_flat_band_is_not_flagged() -> None:
    image = _textured_image(1280, 720)
    result = _analyze(image)
    assert result.signals.possible_tv_lower_third is False


def test_non_16_9_image_with_flat_bottom_band_is_not_flagged() -> None:
    """The aspect-ratio gate is required - a square or portrait image with a flat bottom strip
    (e.g. a simple graphic/infographic) must not be flagged as broadcast footage."""
    image = _image_with_flat_bottom_band(800, 800, band_fraction=0.22)
    result = _analyze(image)
    assert result.signals.possible_tv_lower_third is False


# --- branded-screenshot heuristic ---------------------------------------------------------------


def test_flat_striped_image_with_screenshot_token_flags_possible_branded_screenshot() -> None:
    image = _flat_striped_image(800, 600)
    result = _analyze(image, url="https://example.com/app-screenshot.png")
    assert result.signals.possible_branded_screenshot is True
    assert "possible_branded_screenshot" in result.quality_warnings
    assert result.hard_rejection_reasons == []


def test_flat_striped_image_without_token_can_still_flag_at_higher_bar() -> None:
    """Without corroborating URL/alt-text evidence, the pixel signal alone still fires once flat-
    row density is high enough - conservative escalation, still never a hard rejection."""
    image = _flat_striped_image(800, 600)
    result = _analyze(image, url="https://example.com/photo.jpg")
    assert result.signals.possible_branded_screenshot is True
    assert result.hard_rejection_reasons == []


def test_textured_photo_is_not_flagged_as_branded_screenshot() -> None:
    image = _textured_image(800, 600)
    result = _analyze(image, url="https://example.com/photo.jpg")
    assert result.signals.possible_branded_screenshot is False


def test_ambiguous_editorial_photography_is_never_hard_rejected_by_new_signals() -> None:
    """A large, plausible editorial photo that happens to trip every new soft signal
    (watermark token + 16:9 flat-band shape + flat rows) must still never be hard-rejected -
    M9's own explicit requirement: ambiguous signals go to REVIEW, never a hard rejection."""
    image = _image_with_flat_bottom_band(1280, 720, band_fraction=0.22)
    result = _analyze(image, url="https://example.com/editorial-watermark-screenshot.jpg")
    assert result.hard_rejection_reasons == []
