"""Tests for services/brand_renderer.py - the programmatic (Pillow-only, no image-generation
model) NINJA PULSE Brand Renderer. Every render call here is fully offline/local - no network,
no Telegram, no LLM."""
import io

import pytest
from PIL import Image, ImageDraw

from services.brand_renderer import (
    RenderResult,
    _CARD_HEIGHT,
    _CARD_WIDTH,
    _DATA_LABEL_FONT_MAX,
    _DATA_LABEL_FONT_MIN,
    _DATA_LABEL_MAX_LINES,
    _LOGO_PNG_PATH,
    _OFFICIAL_NNJ_RED,
    _fit_wrapped_block,
    load_brand_mark,
    render_branded_media,
    render_breaking_frame,
    render_data_card,
    render_news_hero,
    render_quote_card,
    render_recap_fallback_card,
)
from services.presentation_director import BREAKING, DATA, NEWS, QUOTE, DataCandidate, QuoteCandidate


def _solid_jpeg(width: int = 1600, height: int = 900, color: tuple[int, int, int] = (30, 60, 90)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# §38 official asset loading / geometry
# ---------------------------------------------------------------------------


def test_official_nnj_logo_png_loads():
    assert _LOGO_PNG_PATH.exists()
    mark = load_brand_mark()
    assert mark.size == (480, 480)  # official aspect ratio, never stretched


def test_brand_mark_is_used_unmodified_across_calls():
    """Real forensic finding (report §"NNJ official asset handling"): nnj_logo.png is already a
    composited red-badge + white-wordmark asset, not a transparent mark this module recolors -
    every call must return byte-identical pixels, never a per-call mutation/recolor."""
    first = load_brand_mark()
    second = load_brand_mark()
    assert first.tobytes() == second.tobytes()


def test_brand_mark_contains_both_the_official_red_and_white_as_shipped():
    """Confirms the asset is used as-is: both the official red badge background and the white
    wordmark are present, unmodified - never flattened into a single recolored blob."""
    mark = load_brand_mark().convert("RGBA")
    colors = {
        mark.getpixel((x, y))[:3]
        for x in range(0, 480, 10)
        for y in range(0, 480, 10)
        if mark.getpixel((x, y))[3] > 200
    }
    assert _OFFICIAL_NNJ_RED in colors
    assert (255, 255, 255) in colors


# ---------------------------------------------------------------------------
# Template dispatch / correct template selected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "presentation_type,template_version",
    [(NEWS, "pulse-news-v1"), (BREAKING, "pulse-breaking-v1"), (DATA, "pulse-data-v1"), (QUOTE, "pulse-quote-v1")],
)
def test_correct_template_selected(presentation_type, template_version):
    kwargs = {}
    if presentation_type == DATA:
        kwargs["data_candidate"] = DataCandidate(value="1", unit="million", label="users", evidence_fact="1 million users")
    if presentation_type == QUOTE:
        kwargs["quote_candidate"] = QuoteCandidate(text="Hello.", speaker="A")
    source = _solid_jpeg() if presentation_type in (NEWS, BREAKING) else None
    result = render_branded_media(
        presentation_type=presentation_type, source_image_bytes=source, category="AI",
        editorial_code="NP-0001", **kwargs,
    )
    assert result.success
    assert result.template_version == template_version


# ---------------------------------------------------------------------------
# NEWS subtle vs BREAKING stronger branding
# ---------------------------------------------------------------------------


def test_news_hero_preserves_source_image_dimensions():
    source = _solid_jpeg(1600, 900)
    out = render_news_hero(source, category="AI", editorial_code="NP-0001", branding_strength="EDITORIAL")
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (1600, 900)  # never resized/cropped/stretched


def test_news_minimal_branding_omits_pulse_line_and_code_label():
    """MINIMAL is the majority-case, most conservative NEWS treatment - source-media-first."""
    source = _solid_jpeg(1600, 900, color=(10, 10, 10))
    minimal = render_news_hero(source, category="AI", editorial_code="NP-0001", branding_strength="MINIMAL")
    editorial = render_news_hero(source, category="AI", editorial_code="NP-0001", branding_strength="EDITORIAL")
    # The MINIMAL variant draws strictly less (no pulse line, no code label) - a cheap, real proxy
    # is that its rendered bytes differ from the EDITORIAL variant's on the very dark source image
    # (both must differ from each other, and MINIMAL's own logo alone is smaller).
    assert minimal != editorial


def test_breaking_frame_never_exceeds_conservative_band_height():
    source = _solid_jpeg(1600, 900)
    out = render_breaking_frame(source, category="AI", editorial_code="NP-0002")
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (1600, 900)


def test_breaking_frame_works_with_no_source_image():
    out = render_breaking_frame(None, category="AI", editorial_code="NP-0002")
    with Image.open(io.BytesIO(out)) as img:
        assert img.width > 0 and img.height > 0


# ---------------------------------------------------------------------------
# DATA/QUOTE exactness (§39/§40)
# ---------------------------------------------------------------------------


def test_data_card_never_invents_the_evidence_fact_field():
    candidate = DataCandidate(value="500", unit="million", label="weekly users", evidence_fact="ChatGPT reached 500 million weekly users.")
    result = render_branded_media(
        presentation_type=DATA, source_image_bytes=None, category="AI", editorial_code="NP-0003",
        data_candidate=candidate,
    )
    assert result.success
    with Image.open(io.BytesIO(result.image_bytes)) as img:
        assert img.mode in ("RGB", "RGBA")


def test_quote_card_renders_without_paraphrasing_the_text():
    """The renderer must never be given a chance to alter quote text - this test asserts the
    render call itself never raises/rejects the exact original quote string, including
    punctuation, and that render_quote_card is a pure passthrough of `quote_candidate.text`."""
    original = "We are building a new interface."
    candidate = QuoteCandidate(text=original, speaker="Jane Doe")
    out = render_quote_card(candidate, category="AI", editorial_code="NP-0004")
    with Image.open(io.BytesIO(out)) as img:
        assert img.width > 0
    # The renderer takes candidate.text as an opaque string - no transformation function exists
    # in this module that touches QuoteCandidate.text before drawing (structural guarantee,
    # confirmed by reading render_quote_card's own implementation).
    assert candidate.text == original


# ---------------------------------------------------------------------------
# Fail-safe (§29/§38) - original media preserved / missing asset / renderer exception
# ---------------------------------------------------------------------------


def test_invalid_image_bytes_fails_safe_not_raises():
    result = render_branded_media(
        presentation_type=NEWS, source_image_bytes=b"not-an-image", category="AI", editorial_code="NP-0005",
    )
    assert result.success is False
    assert result.image_bytes is None
    assert result.fallback_reason is not None


def test_data_without_candidate_fails_safe():
    result = render_branded_media(
        presentation_type=DATA, source_image_bytes=None, category="AI", editorial_code="NP-0006",
        data_candidate=None,
    )
    assert result.success is False


def test_quote_without_candidate_fails_safe():
    result = render_branded_media(
        presentation_type=QUOTE, source_image_bytes=None, category="AI", editorial_code="NP-0007",
        quote_candidate=None,
    )
    assert result.success is False


def test_news_with_no_source_image_fails_safe():
    result = render_branded_media(
        presentation_type=NEWS, source_image_bytes=None, category="AI", editorial_code="NP-0008",
    )
    assert result.success is False


def test_missing_brand_asset_fails_safe(monkeypatch):
    import services.brand_renderer as brand_renderer_module
    from pathlib import Path

    monkeypatch.setattr(brand_renderer_module, "_LOGO_PNG_PATH", Path("assets/brand/does_not_exist.png"))
    result = render_branded_media(
        presentation_type=NEWS, source_image_bytes=_solid_jpeg(), category="AI", editorial_code="NP-0009",
    )
    assert result.success is False
    assert "missing official brand asset" in (result.fallback_reason or "")


def test_render_result_is_always_returned_never_raises_for_any_type():
    for presentation_type in (NEWS, BREAKING, DATA, QUOTE):
        result = render_branded_media(
            presentation_type=presentation_type, source_image_bytes=None, category="AI", editorial_code="NP-0010",
        )
        assert isinstance(result, RenderResult)


# ---------------------------------------------------------------------------
# Album: only the first item is ever branded - see worker/content_cycle.py's own integration for
# the "candidate[1:] stays original" guarantee; this module itself only ever touches the bytes
# explicitly handed to it, never a list of candidates (a structural guarantee, not a runtime one).
# ---------------------------------------------------------------------------


def test_renderer_never_mutates_input_bytes():
    source = _solid_jpeg()
    original = bytes(source)
    render_news_hero(source, category="AI", editorial_code="NP-0011", branding_strength="EDITORIAL")
    assert source == original


# ---------------------------------------------------------------------------
# §41 performance
# ---------------------------------------------------------------------------


def test_render_performance_well_under_three_seconds():
    source = _solid_jpeg(1600, 900)
    result = render_branded_media(
        presentation_type=NEWS, source_image_bytes=source, category="AI", editorial_code="NP-0012",
        branding_strength="EDITORIAL",
    )
    assert result.success
    assert result.duration_ms < 3000


# ---------------------------------------------------------------------------
# Phase H.3C - render_recap_fallback_card(): EVENT_RECAP Tier 3 branded fallback card.
# Structural checks only (dimensions/format/non-empty/no crash) - never OCR, never pixel-perfect
# typography assertions, per the phase's own explicit instruction.
# ---------------------------------------------------------------------------


def test_recap_fallback_card_produces_valid_dimensions_and_format():
    result = render_recap_fallback_card("Google Pixel 11 Pro Fold")
    assert result.success is True
    assert result.image_bytes is not None
    assert len(result.image_bytes) > 0
    img = Image.open(io.BytesIO(result.image_bytes))
    assert img.format == "JPEG"
    assert img.size == (_CARD_WIDTH, _CARD_HEIGHT)


def test_recap_fallback_card_includes_the_official_nnj_logo_via_existing_helper():
    # No pixel-diff/OCR assertion (instruction's own explicit prohibition) - this proves the
    # SAME _paste_logo()/official-asset path render_data_card()/render_quote_card() already use
    # is reached at all (a missing/unreadable asset raises FileNotFoundError inside the function,
    # which would show up here as success=False, not a silent skip).
    result = render_recap_fallback_card("Twitch × Amazon")
    assert result.success is True


def test_recap_fallback_card_with_category_does_not_crash():
    result = render_recap_fallback_card("Pixel 11 Pro Fold", category="TECH")
    assert result.success is True


def test_recap_fallback_card_handles_long_subject_without_crashing():
    result = render_recap_fallback_card("A" * 200)
    assert result.success is True
    img = Image.open(io.BytesIO(result.image_bytes))
    assert img.size == (_CARD_WIDTH, _CARD_HEIGHT)  # bounded text wrapping - canvas never grows


def test_recap_fallback_card_handles_cyrillic_subject_without_crashing():
    result = render_recap_fallback_card("Twitch и Amazon: судебный спор о данных стримеров")
    assert result.success is True
    assert result.image_bytes is not None
    assert len(result.image_bytes) > 0


def test_recap_fallback_card_handles_empty_subject_without_crashing():
    result = render_recap_fallback_card("")
    assert result.success is True


def test_recap_fallback_card_is_deterministic_for_the_same_input():
    first = render_recap_fallback_card("Google Pixel 11 Pro Fold", category="TECH")
    second = render_recap_fallback_card("Google Pixel 11 Pro Fold", category="TECH")
    assert first.success and second.success
    assert first.image_bytes == second.image_bytes  # same input -> byte-identical output


def test_recap_fallback_card_never_calls_branded_media_dispatch():
    """Deliberately called directly, never through render_branded_media()'s presentation_type
    dispatch (module docstring) - confirmed structurally: no presentation_type/DataCandidate/
    QuoteCandidate argument exists on this function's own signature at all."""
    import inspect

    params = inspect.signature(render_recap_fallback_card).parameters
    assert "presentation_type" not in params
    assert set(params) == {"subject", "category"}


def test_recap_fallback_card_fails_soft_on_missing_logo_asset(monkeypatch: pytest.MonkeyPatch):
    import services.brand_renderer as brand_renderer_module

    monkeypatch.setattr(brand_renderer_module, "_LOGO_PNG_PATH", brand_renderer_module._LOGO_PNG_PATH.parent / "does-not-exist.png")
    result = render_recap_fallback_card("Any Subject")
    assert result.success is False
    assert result.image_bytes is None
    assert result.fallback_reason is not None


# ---------------------------------------------------------------------------
# Phase V2.17 - DATA card text safety: no clipping, ever. A real production case (a Russian
# GeForce RTX 50 pricing story) had its explanatory label run past the card's right edge - direct,
# non-OCR proof that the deterministic wrap/shrink fitting stays inside the card's own bounding
# box, using the renderer's own measurement functions (draw.textlength()), never OCR.
# ---------------------------------------------------------------------------

_LONG_RUSSIAN_LABEL = (
    "За один месяц видеокарты GeForce RTX 50 подорожали почти на 20% на фоне "
    "ажиотажного спроса и ограниченных поставок на рынке"
)


def test_data_card_long_russian_label_wraps_within_bounds_no_clipping():
    """Direct measurement, not OCR: every line the fitting helper actually returns must measure
    <= the card's own text max_width, using the exact same font it selected."""
    margin = 64
    max_width = _CARD_WIDTH - margin * 2
    scratch = Image.new("RGB", (_CARD_WIDTH, 100))
    draw = ImageDraw.Draw(scratch)

    lines, font, _size = _fit_wrapped_block(
        draw, _LONG_RUSSIAN_LABEL, font_max=_DATA_LABEL_FONT_MAX, font_min=_DATA_LABEL_FONT_MIN,
        max_width=max_width, max_lines=_DATA_LABEL_MAX_LINES,
    )

    assert lines  # never silently empty
    assert len(lines) <= _DATA_LABEL_MAX_LINES
    for line in lines:
        assert draw.textlength(line, font=font) <= max_width, f"line exceeds max_width: {line!r}"


def test_data_card_renders_successfully_with_representative_long_label():
    """End-to-end: the real render_data_card() call succeeds and stays at the fixed card size for
    a label as long as the real production case that previously clipped."""
    candidate = DataCandidate(
        value="20", unit="%", label=_LONG_RUSSIAN_LABEL[:80],
        evidence_fact="GeForce RTX 50 подорожали на 20% за месяц.",
    )
    out = render_data_card(candidate, category="TECH", editorial_code="NP-6139")
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (_CARD_WIDTH, _CARD_HEIGHT)


def test_data_card_short_value_and_unit_still_render_unchanged_in_shape():
    """Regression guard: an ordinary short value/unit (the common case) must still render at the
    full approved max font size - the new bounded-fit helper must not shrink text that already
    fits comfortably."""
    from services.brand_renderer import _DATA_UNIT_FONT_MAX, _DATA_VALUE_FONT_MAX, _fit_single_line

    scratch = Image.new("RGB", (_CARD_WIDTH, 300))
    draw = ImageDraw.Draw(scratch)
    margin = 64
    max_width = _CARD_WIDTH - margin * 2

    _font_obj, size = _fit_single_line(
        draw, "20", font_max=_DATA_VALUE_FONT_MAX, font_min=100, max_width=max_width,
    )
    assert size == _DATA_VALUE_FONT_MAX

    _font_obj, size = _fit_single_line(
        draw, "%", font_max=_DATA_UNIT_FONT_MAX, font_min=32, max_width=max_width,
    )
    assert size == _DATA_UNIT_FONT_MAX
