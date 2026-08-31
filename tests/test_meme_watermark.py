"""MEME PRODUCTION PIPELINE (overnight phase): services.meme_watermark - the mandatory NNJ
watermark compositor. Pure PIL tests, no database, no network - every input is a real, in-memory
PNG built with Pillow.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image

from schemas.meme_copy import MemeCopy
from services.meme_watermark import MemeWatermarkError, apply_nnj_watermark


def _solid_png(size: tuple[int, int] = (800, 800), color: tuple[int, int, int] = (100, 150, 200)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _copy(*, bottom_text: str | None = None) -> MemeCopy:
    return MemeCopy(
        top_text="TOP TEXT", bottom_text=bottom_text, punchline_short="p",
        telegram_caption="c", alt_text="a",
    )


def _region_has_any_changed_pixel(
    image: Image.Image, *, box: tuple[int, int, int, int], background: tuple[int, int, int],
) -> bool:
    """The official NNJ mark (assets/brand/nnj_logo.png) is a wordmark/badge shape with real
    transparent padding around it within its own square canvas - a single exact corner pixel can
    legitimately land on that transparent padding rather than the visible glyph. Scanning the
    whole expected footprint region for ANY changed pixel is the correct, non-flaky proof that
    compositing actually happened there."""
    x0, y0, x1, y1 = box
    region = image.crop((x0, y0, x1, y1))
    return any(pixel != background for pixel in list(region.getdata()))


def test_watermark_returns_valid_decodable_image() -> None:
    watermarked = apply_nnj_watermark(_solid_png())
    out = Image.open(io.BytesIO(watermarked))
    out.load()
    assert out.size == (800, 800)


def test_watermark_actually_changes_pixels_in_the_corner() -> None:
    """Proves the compositor is genuinely invoked - the bottom-right corner region must contain
    at least one pixel that differs from the original solid background color once the logo is
    pasted there."""
    background = (100, 150, 200)
    original_bytes = _solid_png(color=background)
    watermarked_bytes = apply_nnj_watermark(original_bytes)
    watermarked = Image.open(io.BytesIO(watermarked_bytes)).convert("RGB")

    footprint = (watermarked.width - 200, watermarked.height - 200, watermarked.width, watermarked.height)
    assert _region_has_any_changed_pixel(watermarked, box=footprint, background=background)


def test_watermark_center_untouched_for_a_large_image() -> None:
    """The watermark must not dominate/cover the center of the image - a corner-only placement."""
    original_bytes = _solid_png(size=(1200, 1200), color=(50, 60, 70))
    watermarked_bytes = apply_nnj_watermark(original_bytes)
    watermarked = Image.open(io.BytesIO(watermarked_bytes)).convert("RGB")
    center_pixel = watermarked.getpixel((600, 600))
    assert center_pixel == (50, 60, 70)  # exact original background color, untouched


def test_watermark_placed_top_right_when_bottom_band_in_use() -> None:
    """Adaptive placement: with MemeCopy.bottom_text present, the watermark moves to top-right so
    it never sits against the bottom caption band."""
    background = (10, 10, 10)
    original_bytes = _solid_png(size=(1000, 1000), color=background)
    watermarked_bytes = apply_nnj_watermark(original_bytes, copy=_copy(bottom_text="BOTTOM"))
    watermarked = Image.open(io.BytesIO(watermarked_bytes)).convert("RGB")

    top_right_box = (watermarked.width - 200, 0, watermarked.width, 200)
    bottom_right_box = (watermarked.width - 200, watermarked.height - 200, watermarked.width, watermarked.height)
    assert _region_has_any_changed_pixel(watermarked, box=top_right_box, background=background)
    assert not _region_has_any_changed_pixel(watermarked, box=bottom_right_box, background=background)


def test_watermark_placed_bottom_right_when_no_bottom_text() -> None:
    background = (10, 10, 10)
    original_bytes = _solid_png(size=(1000, 1000), color=background)
    watermarked_bytes = apply_nnj_watermark(original_bytes, copy=_copy(bottom_text=None))
    watermarked = Image.open(io.BytesIO(watermarked_bytes)).convert("RGB")

    bottom_right_box = (watermarked.width - 200, watermarked.height - 200, watermarked.width, watermarked.height)
    assert _region_has_any_changed_pixel(watermarked, box=bottom_right_box, background=background)


def test_watermark_placed_bottom_right_when_copy_not_supplied() -> None:
    background = (10, 10, 10)
    original_bytes = _solid_png(size=(1000, 1000), color=background)
    watermarked_bytes = apply_nnj_watermark(original_bytes)  # copy=None default
    watermarked = Image.open(io.BytesIO(watermarked_bytes)).convert("RGB")

    bottom_right_box = (watermarked.width - 200, watermarked.height - 200, watermarked.width, watermarked.height)
    assert _region_has_any_changed_pixel(watermarked, box=bottom_right_box, background=background)


def test_corrupt_image_bytes_raise_watermark_error_never_silent() -> None:
    with pytest.raises(MemeWatermarkError):
        apply_nnj_watermark(b"not a real image at all")


def test_empty_bytes_raise_watermark_error() -> None:
    with pytest.raises(MemeWatermarkError):
        apply_nnj_watermark(b"")


def test_watermark_deterministic_for_same_input() -> None:
    """Same input bytes must always produce the same output bytes - no randomization anywhere."""
    original_bytes = _solid_png()
    first = apply_nnj_watermark(original_bytes)
    second = apply_nnj_watermark(original_bytes)
    assert first == second


def test_watermark_works_on_small_image() -> None:
    """Small images must not crash the sizing math (max() floors already guard against a
    zero-width watermark)."""
    watermarked = apply_nnj_watermark(_solid_png(size=(64, 64)))
    out = Image.open(io.BytesIO(watermarked))
    out.load()
    assert out.size == (64, 64)


def test_uses_the_canonical_brand_asset_not_a_redrawn_logo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves this module reuses services.brand_renderer.load_brand_mark() - the official,
    already-shipped nnj_logo.png - never a separately drawn/approximated mark. Monkeypatches
    load_brand_mark() itself and asserts it was actually called."""
    import services.meme_watermark as watermark_module

    calls: list[bool] = []
    original = watermark_module.load_brand_mark

    def _spy():
        calls.append(True)
        return original()

    monkeypatch.setattr(watermark_module, "load_brand_mark", _spy)
    apply_nnj_watermark(_solid_png())
    assert calls == [True]
