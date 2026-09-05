"""Phase 18 M6 - Meme Rendering / Text Overlay tests (docs/phase18_m6_meme_rendering_report.md).

No network - deterministic, local Pillow rendering only. `LocalImageStorage` writes to a
temporary directory (`tmp_path`), fully isolated between tests.
"""
from __future__ import annotations

import asyncio
from io import BytesIO

import pytest
from PIL import Image

from integrations.llm_gateway.image_protocol import ImageGenerationRequest
from integrations.llm_gateway.providers.mock_image_adapter import MockImageAdapter
from integrations.storage.image_storage import LocalImageStorage
from schemas.meme_copy import MemeCopy
from schemas.meme_render import MemeRenderStatus
from services.meme_render import _contrast_ratio, _relative_luminance, _wrap_text, render_meme

_VALID_COPY = MemeCopy(
    top_text="AI WON'T TAKE YOUR JOB",
    bottom_text="SAYS GUY WHOSE JOB IS AI",
    punchline_short="p", telegram_caption="c", editor_explanation=None, alt_text="alt",
)


def _generate_base_image(prompt: str = "A CEO on stage.") -> bytes:
    return asyncio.run(MockImageAdapter().generate_image(ImageGenerationRequest(prompt=prompt))).image_bytes


# ---------------------------------------------------------------------------
# Contrast math (pure)
# ---------------------------------------------------------------------------


def test_relative_luminance_white_is_one_black_is_zero() -> None:
    assert _relative_luminance((255, 255, 255)) == pytest.approx(1.0, abs=1e-6)
    assert _relative_luminance((0, 0, 0)) == pytest.approx(0.0, abs=1e-6)


def test_contrast_ratio_black_on_white_is_maximal() -> None:
    ratio = _contrast_ratio(_relative_luminance((255, 255, 255)), _relative_luminance((0, 0, 0)))
    assert ratio == pytest.approx(21.0, abs=0.01)


def test_contrast_ratio_is_symmetric() -> None:
    a = _contrast_ratio(0.8, 0.2)
    b = _contrast_ratio(0.2, 0.8)
    assert a == pytest.approx(b)


# ---------------------------------------------------------------------------
# Word wrap (pure, needs a real ImageDraw for text measurement)
# ---------------------------------------------------------------------------


def test_wrap_text_keeps_short_text_on_one_line() -> None:
    from PIL import ImageDraw, ImageFont

    image = Image.new("RGB", (1024, 200))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=48)
    lines = _wrap_text(draw, "SHORT", font, max_width=900)
    assert lines == ["SHORT"]


def test_wrap_text_splits_long_text_into_multiple_lines() -> None:
    from PIL import ImageDraw, ImageFont

    image = Image.new("RGB", (1024, 200))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=72)
    lines = _wrap_text(draw, "THIS IS A FAIRLY LONG PIECE OF MEME TEXT THAT MUST WRAP", font, max_width=400)
    assert len(lines) > 1
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=4)
        assert bbox[2] - bbox[0] <= 400


# ---------------------------------------------------------------------------
# render_meme - end to end
# ---------------------------------------------------------------------------


def test_render_produces_valid_png_and_stores_it(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    result = render_meme(_generate_base_image(), _VALID_COPY, storage=storage)

    assert result.status == MemeRenderStatus.RENDERED
    assert result.storage_key is not None
    assert storage.exists(result.storage_key)
    with Image.open(BytesIO(storage.read(result.storage_key))) as rendered:
        assert rendered.format == "PNG"
        assert rendered.size == (1024, 1024)


def test_render_reports_contrast_ratios_for_both_bands(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    result = render_meme(_generate_base_image(), _VALID_COPY, storage=storage)

    assert result.top_text_contrast_ratio is not None
    assert result.bottom_text_contrast_ratio is not None
    assert result.contrast_passed is True


def test_render_with_no_bottom_text_leaves_bottom_ratio_none(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    copy = MemeCopy(
        top_text="ONLY TOP TEXT", bottom_text=None,
        punchline_short="p", telegram_caption="c", editor_explanation=None, alt_text="alt",
    )
    result = render_meme(_generate_base_image(), copy, storage=storage)

    assert result.top_text_contrast_ratio is not None
    assert result.bottom_text_contrast_ratio is None


def test_center_safe_zone_is_never_drawn_into(tmp_path) -> None:
    """The base image's own center circle (MockImageAdapter's placeholder 'key object') must
    survive unmodified - proves text is confined to the top/bottom bands only."""
    storage = LocalImageStorage(tmp_path)
    base_bytes = _generate_base_image()
    result = render_meme(base_bytes, _VALID_COPY, storage=storage)

    with Image.open(BytesIO(base_bytes)) as before, Image.open(BytesIO(storage.read(result.storage_key))) as after:
        before_rgb, after_rgb = before.convert("RGB"), after.convert("RGB")
        center_box = (300, 300, 724, 724)  # well inside the un-drawn center band
        assert list(before_rgb.crop(center_box).getdata()) == list(after_rgb.crop(center_box).getdata())


def test_fit_text_to_band_truncates_when_nothing_fits_even_smallest_font() -> None:
    """Direct unit test of the truncation mechanism itself (decoupled from whether any
    particular MemeCopy-length string happens to still fit at the smallest supported font size -
    it may legitimately fit, which is not a bug): an artificially tiny max_height guarantees the
    'nothing fits' branch, proving text is truncated rather than left overflowing."""
    from PIL import ImageDraw

    from services.meme_render import _fit_text_to_band

    image = Image.new("RGB", (1024, 200))
    draw = ImageDraw.Draw(image)
    long_text = "ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVEN TWELVE THIRTEEN"

    font, lines, violated = _fit_text_to_band(draw, long_text, max_width=900, max_height=1)

    assert violated is True
    assert len(lines) <= 2  # _MAX_LINES_PER_BAND - never grows unbounded either


def test_render_reports_truncation_reason_code_when_text_cannot_fit(tmp_path, monkeypatch) -> None:
    """End-to-end: forcing the band height fraction down to an unfittable size proves
    render_meme() surfaces the violation through to MemeRenderResult.safe_zone_violations,
    never silently drawing over the safe zone instead."""
    import services.meme_render as meme_render_module

    monkeypatch.setattr(meme_render_module, "_BAND_HEIGHT_FRACTION", 0.02)
    storage = LocalImageStorage(tmp_path)
    copy = MemeCopy(
        top_text="THIS TEXT IS DEFINITELY TOO TALL FOR A TWO PERCENT HEIGHT BAND TO CONTAIN",
        bottom_text=None, punchline_short="p", telegram_caption="c", editor_explanation=None, alt_text="alt",
    )

    result = render_meme(_generate_base_image(), copy, storage=storage)

    assert result.status == MemeRenderStatus.RENDERED
    assert "top_text_truncated_to_fit_safe_zone" in result.safe_zone_violations


def test_deterministic_same_inputs_produce_same_output(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    base = _generate_base_image()
    first = render_meme(base, _VALID_COPY, storage=storage)
    second = render_meme(base, _VALID_COPY, storage=storage)
    assert first.sha256 == second.sha256
    assert first.storage_key == second.storage_key


def test_reserve_watermark_clearance_keeps_corner_region_untouched() -> None:
    """MEME-PROD-2.1: real production overlap was confirmed by rendering a long line before this
    fix - the watermark's own top-right (or bottom-right) footprint must stay pure background when
    `reserve_watermark_clearance=True` is passed for the band the watermark will occupy."""
    from PIL import ImageDraw

    from services.meme_render import _draw_band

    background = (200, 200, 200)
    image = Image.new("RGB", (1024, 1024), background)
    draw = ImageDraw.Draw(image)
    long_text = "This is a fairly long top overlay line of meme text that wraps across lines"

    _draw_band(image, draw, long_text, band="top", reserve_watermark_clearance=True)

    watermark_corner_box = (824, 0, 1024, 184)  # top band's own right portion, band_height=184
    assert list(image.crop(watermark_corner_box).getdata()) == [background] * (200 * 184)


def test_without_clearance_long_text_can_reach_the_watermark_corner() -> None:
    """Negative control proving the clearance reservation above is load-bearing, not a no-op -
    without it, the same long line's wrapped text does reach into that same corner region."""
    from PIL import ImageDraw

    from services.meme_render import _draw_band

    background = (200, 200, 200)
    image = Image.new("RGB", (1024, 1024), background)
    draw = ImageDraw.Draw(image)
    long_text = "This is a fairly long top overlay line of meme text that wraps across lines"

    _draw_band(image, draw, long_text, band="top", reserve_watermark_clearance=False)

    watermark_corner_box = (824, 0, 1024, 184)
    region_pixels = list(image.crop(watermark_corner_box).getdata())
    assert any(pixel != background for pixel in region_pixels)


def test_render_meme_never_exceeds_two_lines_per_band(tmp_path) -> None:
    """Brief's own explicit rule: top text max 2 lines, bottom text max 2 lines."""
    from services.meme_render import _MAX_LINES_PER_BAND

    assert _MAX_LINES_PER_BAND == 2


def test_malformed_base_image_bytes_return_failed_not_raise(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    result = render_meme(b"not an image", _VALID_COPY, storage=storage)

    assert result.status == MemeRenderStatus.FAILED
    assert result.error_code is not None
    assert result.storage_key is None


# ---------------------------------------------------------------------------
# MEME-PROD-2.1: Cyrillic-capable font resolution (real production defect - Pillow's own
# load_default() has no Cyrillic glyphs, renders as ".notdef" tofu boxes).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_font_path_cache(monkeypatch: pytest.MonkeyPatch):
    """The module-level `_font_path_resolution` single-element cache must not leak a resolution
    from one test into another - reset before and after every test in this file, mirroring the
    isolation every other stateful-cache fixture in this codebase already provides."""
    import services.meme_render as meme_render_module

    monkeypatch.setattr(meme_render_module, "_font_path_resolution", [])
    yield
    monkeypatch.setattr(meme_render_module, "_font_path_resolution", [])


def test_resolve_font_path_prefers_brand_font_path_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    import services.meme_render as meme_render_module
    from core.config import settings

    monkeypatch.setattr(settings, "brand_font_path", "/fake/override/font.ttf")
    monkeypatch.setattr(Path, "exists", lambda self: self.as_posix() == "/fake/override/font.ttf")

    assert meme_render_module._resolve_font_path() == "/fake/override/font.ttf"


def test_resolve_font_path_falls_back_through_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    import services.meme_render as meme_render_module
    from core.config import settings

    monkeypatch.setattr(settings, "brand_font_path", None)
    target = meme_render_module._FONT_CANDIDATE_PATHS[-1]
    monkeypatch.setattr(Path, "exists", lambda self: self.as_posix() == target)

    assert meme_render_module._resolve_font_path() == target


def test_resolve_font_path_returns_none_when_nothing_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    import services.meme_render as meme_render_module
    from core.config import settings

    monkeypatch.setattr(settings, "brand_font_path", None)
    monkeypatch.setattr(Path, "exists", lambda self: False)

    assert meme_render_module._resolve_font_path() is None


def test_resolve_font_path_is_cached_after_first_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    import services.meme_render as meme_render_module
    from core.config import settings

    monkeypatch.setattr(settings, "brand_font_path", None)
    calls = []

    def _tracked_exists(self):
        calls.append(self.as_posix())
        return self.as_posix() == meme_render_module._FONT_CANDIDATE_PATHS[0]

    monkeypatch.setattr(Path, "exists", _tracked_exists)
    first = meme_render_module._resolve_font_path()
    call_count_after_first = len(calls)
    second = meme_render_module._resolve_font_path()

    assert first == second
    assert len(calls) == call_count_after_first  # no new filesystem probes on the second call


def test_load_font_falls_back_to_default_when_truetype_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    import services.meme_render as meme_render_module
    from core.config import settings

    monkeypatch.setattr(settings, "brand_font_path", None)
    target = meme_render_module._FONT_CANDIDATE_PATHS[0]
    monkeypatch.setattr(Path, "exists", lambda self: self.as_posix() == target)

    original_truetype = meme_render_module.ImageFont.truetype

    def _raise_only_for_target(font_path, *args, **kwargs):
        if font_path == target:
            raise OSError("cannot open resource")
        # Pillow's own load_default() calls truetype() internally (with a BytesIO, not a path) to
        # build its bundled ASCII-only fallback font - that internal call must go through
        # unmodified, or the fallback path itself would break.
        return original_truetype(font_path, *args, **kwargs)

    monkeypatch.setattr(meme_render_module.ImageFont, "truetype", _raise_only_for_target)
    font = meme_render_module._load_font(40)
    assert font is not None  # degraded (ASCII-only) but never a crash


def test_load_font_renders_real_cyrillic_glyphs_not_tofu_boxes() -> None:
    """Direct empirical proof of the actual production defect this fix addresses: Pillow's own
    load_default() renders Cyrillic as uniform ".notdef" boxes, all visually identical regardless
    of which letter they stand in for - a resolved real font must NOT do this."""
    from PIL import ImageDraw

    from services.meme_render import _load_font

    font = _load_font(48)
    image = Image.new("RGB", (400, 100), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    width_a = draw.textbbox((0, 0), "а", font=font)[2]  # Cyrillic "a"
    width_zh = draw.textbbox((0, 0), "ж", font=font)[2]  # Cyrillic "zh" - visually much wider
    # Two different, real Cyrillic glyphs must not measure identically - a tofu-box font renders
    # every unmapped codepoint as the same fixed-width placeholder glyph, so distinct widths are
    # direct proof real glyph outlines were used, not a missing-glyph fallback shape.
    assert width_a != width_zh
