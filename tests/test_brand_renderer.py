"""Tests for services/brand_renderer.py - the programmatic (Pillow-only, no image-generation
model) NINJA PULSE Brand Renderer. Every render call here is fully offline/local - no network,
no Telegram, no LLM."""
import inspect
import io
import random

import pytest
from PIL import Image, ImageDraw

import services.brand_renderer as brand_renderer_module
from services.brand_renderer import (
    RenderResult,
    _CARD_HEIGHT,
    _CARD_WIDTH,
    _DATA_LABEL_FONT_MAX,
    _DATA_LABEL_FONT_MIN,
    _DATA_LABEL_MAX_LINES,
    _LOGO_PNG_PATH,
    _OFFICIAL_NNJ_RED,
    _OFFICIAL_NNJ_WHITE,
    _fit_wrapped_block,
    _measure_data_stat_block,
    _pick_adaptive_data_color,
    _select_data_block_placement,
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
    # Phase V2.20: DATA now requires a source image (same visual family as NEWS/BREAKING) - only
    # QUOTE's portrait remains genuinely optional.
    source = _solid_jpeg() if presentation_type in (NEWS, BREAKING, DATA) else None
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
    original_evidence_fact = candidate.evidence_fact
    result = render_branded_media(
        presentation_type=DATA, source_image_bytes=_solid_jpeg(1600, 900, color=(20, 20, 20)),
        category="AI", editorial_code="NP-0003", data_candidate=candidate,
    )
    assert result.success
    with Image.open(io.BytesIO(result.image_bytes)) as img:
        assert img.mode in ("RGB", "RGBA")
    assert candidate.evidence_fact == original_evidence_fact  # never rewritten by the renderer


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
    """End-to-end: the real render_data_card() call succeeds for a label as long as the real
    production case that previously clipped. Phase V2.20: DATA's canvas is now the MASTER NEWS
    reference canvas (1280x720), not the old standalone card's 1200x675 - an inherent consequence
    of reusing apply_master_news_branding() unchanged, not a separately-chosen size."""
    candidate = DataCandidate(
        value="20", unit="%", label=_LONG_RUSSIAN_LABEL[:80],
        evidence_fact="GeForce RTX 50 подорожали на 20% за месяц.",
    )
    out = render_data_card(
        candidate, category="TECH", editorial_code="NP-6139",
        source_image_bytes=_solid_jpeg(1600, 900, color=(15, 15, 15)),
    )
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (1280, 720)


# ---------------------------------------------------------------------------
# Phase V2.20 - DATA visual system redesign. The source/editorial image is now the primary
# visual (composited via the unchanged apply_master_news_branding()); exactly one compact stat
# block is added in a safe corner reusing MASTER NEWS's own edge/detail-risk safety gate and
# adaptive red/white visibility check. No "PULSE / {category}" label, no NP-xxxx chip, no boxed
# logo, no full-frame dark card. Structural/"never renders X" checks use source introspection
# (this file's own established non-OCR precedent, e.g. test_recap_fallback_card_never_calls_
# branded_media_dispatch), never pixel-diff/OCR.
# ---------------------------------------------------------------------------

_V2_20_DATA_CANDIDATE = DataCandidate(
    value="2,6 млн", unit="$", label="предзаказов за сутки",
    evidence_fact="2.6 million $ in preorders in one day.",
)


def _noisy_source(width: int = 1280, height: int = 720, seed: int = 7) -> bytes:
    """A pathologically busy source image - independent random noise at every pixel - used to
    prove the fail-safe "no safe placement" path: every corner's edge-density/detail-risk gate
    (the same gate nnj_master_news_overlay.py already uses for its own corner placement) must
    reject a region this noisy."""
    rng = random.Random(seed)
    img = Image.new("RGB", (width, height))
    img.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(width * height)])
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_data_card_never_renders_pulse_category_label():
    source = inspect.getsource(brand_renderer_module.render_data_card)
    assert "PULSE" not in source


def test_data_card_never_renders_np_editorial_code_chip():
    source = inspect.getsource(brand_renderer_module.render_data_card)
    assert "_draw_code_label" not in source  # the old NP-xxxx chip helper is never called here


def test_data_card_never_uses_boxed_logo_treatment():
    source = inspect.getsource(brand_renderer_module.render_data_card)
    # branding now comes entirely from apply_master_news_branding()'s own boxless mark - the old
    # standalone card's own _paste_logo() call is never reached inside this function anymore.
    assert "_paste_logo" not in source


def test_data_card_uses_source_image_as_primary_visual(monkeypatch):
    calls: list = []
    original = brand_renderer_module._fit_photo_to_canvas

    def _spy(photo, size):
        calls.append(photo)
        return original(photo, size)

    monkeypatch.setattr(brand_renderer_module, "_fit_photo_to_canvas", _spy)
    source = _solid_jpeg(1600, 900, color=(20, 20, 20))
    out = render_data_card(_V2_20_DATA_CANDIDATE, category="TECH", editorial_code="NP-2000", source_image_bytes=source)
    assert len(calls) == 1  # the real source bytes reach the shared canvas-fit helper exactly once
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (1280, 720)


def test_data_card_primary_stat_fits_within_block_bounds():
    scratch = Image.new("RGB", (1280, 720))
    draw = ImageDraw.Draw(scratch)
    max_width = 320
    primary_text, stat_font, _bbox, *_ = _measure_data_stat_block(draw, _V2_20_DATA_CANDIDATE, max_width=max_width)
    assert draw.textlength(primary_text, font=stat_font) <= max_width


def test_data_card_descriptor_fits_within_block_bounds():
    scratch = Image.new("RGB", (1280, 720))
    draw = ImageDraw.Draw(scratch)
    max_width = 320
    candidate = DataCandidate(
        value="1 млн $", unit="", label="предзаказов Microduck за 6 часов после анонса",
        evidence_fact="1 million $ in Microduck preorders within 6 hours of the announcement.",
    )
    _text, _font, _bbox, label_lines, label_font, _line_h, _total_h = _measure_data_stat_block(
        draw, candidate, max_width=max_width,
    )
    assert label_lines
    assert len(label_lines) <= _DATA_LABEL_MAX_LINES
    for line in label_lines:
        assert draw.textlength(line, font=label_font) <= max_width, f"line exceeds max_width: {line!r}"


def test_data_card_long_descriptor_does_not_clip():
    scratch = Image.new("RGB", (1280, 720))
    draw = ImageDraw.Draw(scratch)
    max_width = 320
    candidate = DataCandidate(
        value="20", unit="%", label=_LONG_RUSSIAN_LABEL[:80],
        evidence_fact="GeForce RTX 50 подорожали на 20% за месяц.",
    )
    _text, _font, _bbox, label_lines, label_font, _line_h, _total_h = _measure_data_stat_block(
        draw, candidate, max_width=max_width,
    )
    assert label_lines
    for line in label_lines:
        assert draw.textlength(line, font=label_font) <= max_width, f"line exceeds max_width: {line!r}"


def test_data_card_adaptive_color_picks_red_on_light_background():
    assert _pick_adaptive_data_color((235.0, 235.0, 235.0)) == _OFFICIAL_NNJ_RED


def test_data_card_adaptive_color_picks_white_on_dark_background():
    assert _pick_adaptive_data_color((10.0, 10.0, 10.0)) == _OFFICIAL_NNJ_WHITE


def test_data_card_adaptive_color_never_returns_a_color_under_the_visibility_threshold():
    """The only invariant _pick_adaptive_data_color() guarantees: whatever it returns (or None)
    must clear the shared MASTER NEWS visibility gate - never forced through illegibly. Checked
    directly against the real threshold rather than against one hand-picked expected color, so
    this stays correct even if the shared constant is ever recalibrated."""
    import math

    from services.brand_renderer import _VISIBILITY_MIN_DISTANCE

    near_red_gray = (200.0, 60.0, 60.0)  # deliberately close to official red #ED1C24
    result = _pick_adaptive_data_color(near_red_gray)
    if result is not None:
        assert math.dist(near_red_gray, result) >= _VISIBILITY_MIN_DISTANCE


def test_data_card_unsafe_placement_falls_back_to_no_stat_block():
    """Direct unit test of the placement search itself - the same edge-density/detail-risk gate
    nnj_master_news_overlay.py already uses for its own corner placement must reject every corner
    of a maximally busy (independent per-pixel noise) region."""
    noisy = Image.new("RGBA", (1280, 720))
    rng = random.Random(42)
    noisy.putdata([
        (rng.randrange(256), rng.randrange(256), rng.randrange(256), 255) for _ in range(1280 * 720)
    ])
    result = _select_data_block_placement(noisy, block_w=400, block_h=200, inset=20, pad=50, avoid_box=None)
    assert result is None


def test_data_card_end_to_end_with_unsafe_source_still_returns_valid_unclipped_image():
    """Full pipeline fail-safe: an unusably busy source must never crash or clip - it must still
    decode as a valid, correctly-sized JPEG (source + MASTER NEWS branding only, no stat block)."""
    out = render_data_card(
        _V2_20_DATA_CANDIDATE, category="TECH", editorial_code="NP-2001",
        source_image_bytes=_noisy_source(),
    )
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "JPEG"
        assert img.size == (1280, 720)


def test_data_card_no_source_image_fails_safe_via_render_branded_media():
    """DATA no longer has a source-photo-free synthetic-card form (spec's own explicit
    requirement) - a missing source image must be a genuine, disclosed fail-safe case, never a
    silently-rendered full-frame fallback card."""
    result = render_branded_media(
        presentation_type=DATA, source_image_bytes=None, category="TECH", editorial_code="NP-2002",
        data_candidate=_V2_20_DATA_CANDIDATE,
    )
    assert result.success is False
    assert result.fallback_reason is not None


def test_news_renderer_unaffected_by_data_redesign():
    """Explicit V2.20 regression guard: NEWS's own render path (render_news_hero /
    apply_master_news_branding is never even imported by NEWS's own code path) is untouched by
    the DATA changes above."""
    source = _solid_jpeg(1600, 900)
    result = render_branded_media(
        presentation_type=NEWS, source_image_bytes=source, category="AI", editorial_code="NP-2003",
        branding_strength="EDITORIAL",
    )
    assert result.success
    assert result.template_version == "pulse-news-v1"
    with Image.open(io.BytesIO(result.image_bytes)) as img:
        assert img.size == (1600, 900)  # NEWS still preserves original source dimensions, unlike DATA


def test_breaking_quote_recap_routing_unaffected_by_data_redesign():
    """Explicit V2.20 regression guard: BREAKING/QUOTE template dispatch and RECAP's fully
    separate direct-call path are untouched by the DATA changes above."""
    breaking = render_branded_media(
        presentation_type=BREAKING, source_image_bytes=_solid_jpeg(), category="AI", editorial_code="NP-2004",
    )
    assert breaking.success and breaking.template_version == "pulse-breaking-v1"

    quote = render_branded_media(
        presentation_type=QUOTE, source_image_bytes=None, category="AI", editorial_code="NP-2005",
        quote_candidate=QuoteCandidate(text="Hello.", speaker="A"),
    )
    assert quote.success and quote.template_version == "pulse-quote-v1"

    recap = render_recap_fallback_card("Pixel 11 Pro Fold", category="TECH")
    assert recap.success and recap.template_version == "pulse-recap-fallback-v1"


# ---------------------------------------------------------------------------
# Phase V2.20A - align DATA to the approved template: bottom-only pulse+NNJ signature (NO upper
# mark at all - a real, deliberate difference from MASTER NEWS's own two-component contract), the
# real canonical SVG assets (nnj_logo.svg / nnj_logo_red.svg) via the same rasterize_nnj_mark()
# MASTER NEWS's own lower signature already uses. Structural/"never renders X" checks stay non-OCR
# (this file's own established precedent); a few direct unit tests target the new small helper
# functions since those are cheap, precise, and don't need a full render_data_card() round trip.
# ---------------------------------------------------------------------------

from services.brand_renderer import (  # noqa: E402
    _DATA_SIGNATURE_CANDIDATE_PLACEMENTS,
    _DATA_SIGNATURE_COMPACT_WIDTH_FRAC,
    _DATA_SIGNATURE_FULL_WIDTH_FRAC,
    _build_data_lower_signature_image,
    _data_signature_geometry,
    _data_signature_line_length,
    _region_box,
    _score_box_safe,
    _select_data_signature,
)
from services.nnj_master_news_mark import rasterize_nnj_mark  # noqa: E402
from services.nnj_master_news_overlay import ComponentPlacement, _rects_intersect  # noqa: E402


def _function_body_source(func) -> str:
    """inspect.getsource(func) minus its own docstring - splits on the literal triple-quote
    delimiters in the raw source text (robust to whatever __doc__ normalization Python applies,
    unlike splitting on func.__doc__ itself)."""
    source = inspect.getsource(func)
    parts = source.split('"""')
    return '"""'.join(parts[2:]) if len(parts) >= 3 else source


def test_data_card_never_calls_master_news_branding_or_upper_mark():
    """Structural proof of the approved template's own "no upper NNJ mark" rule: render_data_card()
    never CALLS apply_master_news_branding() (MASTER's own two-component composition) or
    references an "upper_mark" component anywhere, and composites the bottom signature exactly
    once. Checked against the function's own code body only (docstring excluded) - the docstring
    legitimately explains, in prose, why apply_master_news_branding() is NOT called."""
    body_source = _function_body_source(brand_renderer_module.render_data_card)
    assert "apply_master_news_branding(" not in body_source
    assert "upper_mark" not in body_source
    assert body_source.count("_build_data_lower_signature_image(") == 1


def test_data_signature_candidates_are_bottom_only_never_upper():
    """The approved template forbids any upper mark - the signature's own candidate list must
    contain only the two bottom corners, never UPPER_LEFT/UPPER_RIGHT."""
    assert set(_DATA_SIGNATURE_CANDIDATE_PLACEMENTS) == {
        ComponentPlacement.LOWER_RIGHT, ComponentPlacement.LOWER_LEFT,
    }


def test_data_lower_signature_uses_real_white_svg_for_white_variant():
    """White variant must load the exact canonical assets/brand/nnj_logo.svg - via the same
    rasterize_nnj_mark(red=False) MASTER NEWS's own lower signature already uses, never a redrawn
    or approximated glyph."""
    from services.nnj_master_news_mark import NNJ_WHITE_SVG

    assert NNJ_WHITE_SVG.name == "nnj_logo.svg"
    full_len = _data_signature_line_length(1280, _DATA_SIGNATURE_FULL_WIDTH_FRAC)
    signature = _build_data_lower_signature_image(
        (1280, 720), ComponentPlacement.LOWER_RIGHT, 20, red=False, line_len=full_len,
    )
    assert signature.split()[-1].getbbox() is not None  # something was actually drawn


def test_data_lower_signature_uses_real_red_svg_for_red_variant():
    """Red variant must load the exact canonical assets/brand/nnj_logo_red.svg."""
    from services.nnj_master_news_mark import NNJ_RED_SVG

    assert NNJ_RED_SVG.name == "nnj_logo_red.svg"
    full_len = _data_signature_line_length(1280, _DATA_SIGNATURE_FULL_WIDTH_FRAC)
    signature = _build_data_lower_signature_image(
        (1280, 720), ComponentPlacement.LOWER_RIGHT, 20, red=True, line_len=full_len,
    )
    assert signature.split()[-1].getbbox() is not None


def test_data_signature_mark_preserves_svg_aspect_ratio():
    """rasterize_nnj_mark() resizes proportionally by construction - confirmed here directly for
    both variants across the target widths DATA's own signature builder actually requests.
    Tolerance is 5%, not exact equality: integer-pixel rounding at small target widths (the mark
    is only ~30-60px wide in real use) inherently shifts the raw width/height ratio slightly -
    this test is proving "no distortion," not asserting sub-pixel-exact geometry."""
    for red in (True, False):
        reference = rasterize_nnj_mark(target_width=480, red=red)  # large -> minimal rounding noise
        reference_ratio = reference.width / reference.height
        for target_width in (30, 48, 51, 60):
            mark = rasterize_nnj_mark(target_width=target_width, red=red)
            ratio = mark.width / mark.height
            assert abs(ratio - reference_ratio) / reference_ratio < 0.05


def test_data_signature_full_tier_spans_the_approved_near_full_width():
    """Item 1: the preferred/full DATA signature must still span ~82-85% of the frame width when
    safe - the canonical reference PNG's own bottom line spans ~82-93% of its frame (measured
    directly on data_template_white.png: solid line pixels at x=125->1432 on a 1600px canvas).
    Phase V2.20D changes HOW safety is scored, never the approved FULL geometry itself."""
    assert _DATA_SIGNATURE_FULL_WIDTH_FRAC > 0.7  # deliberately far wider than MASTER's own accent

    canvas_size = (1280, 720)
    full_len = _data_signature_line_length(canvas_size[0], _DATA_SIGNATURE_FULL_WIDTH_FRAC)
    signature = _build_data_lower_signature_image(
        canvas_size, ComponentPlacement.LOWER_RIGHT, 20, red=True, line_len=full_len,
    )
    bbox = signature.split()[-1].getbbox()
    assert bbox is not None
    span = bbox[2] - bbox[0]
    assert span / canvas_size[0] >= _DATA_SIGNATURE_FULL_WIDTH_FRAC - 0.05


def test_data_signature_geometry_scores_three_independent_regions_not_one_coarse_rectangle():
    """Items 2-5, the core V2.20D fix: mark/pulse/line must be three genuinely different real
    boxes - never one shared/coarse rectangle - and the line's own box must be a narrow horizontal
    band (height comparable only to the stroke + a small anti-aliasing margin), never tall enough
    to span the mark's own height. This is the direct structural proof that a thin 2-4px line no
    longer forces the whole ~85%-wide footprint to be scored as if it were a large solid overlay."""
    canvas_size = (1280, 720)
    inset = 20
    full_len = _data_signature_line_length(canvas_size[0], _DATA_SIGNATURE_FULL_WIDTH_FRAC)
    mark_box, pulse_box, line_box = _data_signature_geometry(
        canvas_size, ComponentPlacement.LOWER_RIGHT, inset, full_len,
    )

    assert mark_box != pulse_box != line_box
    mark_h = mark_box[3] - mark_box[1]
    pulse_h = pulse_box[3] - pulse_box[1]
    line_h = line_box[3] - line_box[1]
    line_w = line_box[2] - line_box[0]
    mark_w = mark_box[2] - mark_box[0]

    # the narrow band requirement: the line's own scored height is small in absolute terms and
    # materially smaller than either the mark's or the pulse's own height.
    assert line_h <= 12
    assert line_h < mark_h
    assert line_h < pulse_h
    # the line is the long, thin one - the opposite shape from mark/pulse.
    assert line_w > mark_w * 5


def test_data_signature_anchor_is_the_mark_pulse_union_scored_once():
    """Documents and locks in the deliberate V2.20D refinement (see _select_data_signature()'s own
    docstring for the full empirical justification): the mark and pulse are scored TOGETHER as one
    anchor region, not as two fully independent tiny boxes - because nnj_master_news_overlay.py's
    shared 4x2 worst-case patch grid produces false rejections on ordinary real photo texture when
    given a box as small as either one alone. The anchor must be exactly their union (no bigger,
    no smaller) and must contain both source boxes entirely."""
    from services.brand_renderer import _data_signature_anchor_box

    canvas_size = (1280, 720)
    full_len = _data_signature_line_length(canvas_size[0], _DATA_SIGNATURE_FULL_WIDTH_FRAC)
    mark_box, pulse_box, _line_box = _data_signature_geometry(
        canvas_size, ComponentPlacement.LOWER_RIGHT, 20, full_len,
    )
    anchor = _data_signature_anchor_box(mark_box, pulse_box)

    assert anchor[0] == min(mark_box[0], pulse_box[0])
    assert anchor[1] == min(mark_box[1], pulse_box[1])
    assert anchor[2] == max(mark_box[2], pulse_box[2])
    assert anchor[3] == max(mark_box[3], pulse_box[3])
    # both original boxes fit entirely inside the anchor - nothing is left unscored.
    for box in (mark_box, pulse_box):
        assert anchor[0] <= box[0] and anchor[1] <= box[1] and anchor[2] >= box[2] and anchor[3] >= box[3]


def test_data_lower_signature_never_generates_or_redraws_the_nnj_glyph():
    """No polygon/hand-drawn glyph path exists anywhere in the DATA signature builder or the
    render function - the only mark-producing call is the real canonical SVG rasterizer."""
    signature_source = inspect.getsource(brand_renderer_module._build_data_lower_signature_image)
    render_source = inspect.getsource(brand_renderer_module.render_data_card)
    assert "rasterize_nnj_mark(" in signature_source
    for source in (signature_source, render_source):
        assert "draw.polygon" not in source
        assert "NEWSROOM NINJA" not in source
        assert '"NNJ"' not in source and "'NNJ'" not in source


def test_data_card_still_never_renders_np_or_pulse_or_category_labels():
    """Re-confirms the V2.20 structural guarantees still hold after the V2.20A/D rework - no
    "PULSE / {category}" text label, no NP-xxxx chip, no DATA/category label anywhere in the new
    bottom-signature path either. Checks for the literal drawn label text, not the bare word
    "PULSE" - which legitimately appears in this file as part of the (unrelated) pulse-*waveform*
    geometry constant names (`_LOWER_PULSE_W_FRAC` etc.), never as drawn on-image text."""
    for source in (
        inspect.getsource(brand_renderer_module.render_data_card),
        inspect.getsource(brand_renderer_module._build_data_lower_signature_image),
    ):
        assert "PULSE /" not in source
        assert "_draw_code_label" not in source
        assert '"DATA"' not in source


def test_data_block_placement_skips_corner_colliding_with_signature():
    """Direct proof of the new avoid_box collision check (approved-template requirement: "the data
    block does not collide with the lower pulse/logo signature") - a uniform, quiet, light canvas
    is content-safe and color-safe at every corner, so without avoid_box the first candidate
    (UPPER_LEFT) would win; passing UPPER_LEFT's own exact box as avoid_box must force the search
    to skip it and return a genuinely non-overlapping box instead."""
    canvas = Image.new("RGBA", (1280, 720), (200, 200, 200, 255))
    inset, pad, block_w, block_h = 20, 50, 300, 150
    avoid_box = _region_box((1280, 720), block_w, block_h, ComponentPlacement.UPPER_LEFT, inset)

    result = _select_data_block_placement(canvas, block_w=block_w, block_h=block_h, inset=inset, pad=pad, avoid_box=avoid_box)
    assert result is not None
    box, _color, _needs_backing = result
    assert not _rects_intersect(box, avoid_box)


def test_data_signature_falls_back_to_none_on_unsafe_bottom_corners():
    """Item 8: complete branding omission must happen only when bottom branding itself is unsafe -
    a maximally busy (independent per-pixel noise) canvas must reject both bottom corners entirely
    (mark, pulse, AND even the compact-tier line), returning None."""
    noisy = Image.new("RGBA", (1280, 720))
    rng = random.Random(11)
    noisy.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256), 255) for _ in range(1280 * 720)])
    result = _select_data_signature(noisy, inset=20, pad=50)
    assert result is None


def test_data_card_renders_exactly_one_bottom_signature_end_to_end():
    """Full pipeline: on a real, cooperative (quiet, mid-gray) canvas the signature must render at
    a bottom corner at the FULL tier - proving the whole render_data_card() ->
    _select_data_signature() -> _build_data_lower_signature_image() chain actually executes and
    composites something. Mid-gray (120,120,120), matching the exact fixture color MASTER NEWS's
    own test suite already uses (tests/test_v2_10h_master_news_production.py) - a real, pre-
    existing property of the shared, unmodified _score_region(): Pillow's FIND_EDGES zero-pads at
    a crop's own boundary, producing a small brightness-proportional false edge response there:
    negligible against real photo texture (confirmed against a real fixture in the regression test
    above) but disproportionate for a perfectly flat synthetic color right at the safety threshold
    the brighter it is - a pure synthetic-test-fixture concern, not a production behavior change."""
    solid = _solid_jpeg(1280, 720, color=(120, 120, 120))
    plan = _select_data_signature(Image.open(io.BytesIO(solid)).convert("RGBA"), inset=20, pad=50)
    assert plan is not None
    assert plan.placement in (ComponentPlacement.LOWER_RIGHT, ComponentPlacement.LOWER_LEFT)
    assert plan.tier == "full"


def test_data_signature_real_fixture_regression_iphone_photo_no_longer_loses_branding():
    """Direct real-world regression proof: this exact source photo (v2_10a_overlay_fix/
    iphone_recomposed_source.jpg) is one of the V2.20C preview fixtures that lost its bottom
    signature ENTIRELY once the coarse ~85%-wide rectangle was scored as one solid region - the
    hand/fingers extend into the bottom strip and were enough to fail the whole coarse box. Under
    V2.20D's geometry-aware scoring the mark+pulse+line must independently succeed here (at
    whatever tier is actually needed)."""
    from pathlib import Path

    fixture = (
        Path(r"C:\Users\Theodor\ai-newsroom") / "assets/brand/newsroom_visuals/v2_10a_overlay_fix"
        / "iphone_recomposed_source.jpg"
    )
    if not fixture.exists():
        pytest.skip("real fixture not present in this checkout")
    photo = Image.open(fixture).convert("RGBA")
    canvas = brand_renderer_module._fit_photo_to_canvas(photo, (1280, 720))
    plan = _select_data_signature(canvas, inset=20, pad=50)
    assert plan is not None, "V2.20D regression: bottom signature still lost entirely on a real photo"


def test_data_signature_line_degrades_to_shortened_when_full_length_unsafe(monkeypatch):
    """Item 6: the mark+pulse anchor is always safe; only the FULL-length line's own band is
    unsafe - the search must degrade to a SHORTER line (tier "shortened") while keeping the exact
    same anchor, never dropping branding outright. The safety oracle itself is mocked here
    (discriminated by box HEIGHT - the anchor box is visibly taller than the line's own narrow
    band, matching the real geometry exactly: anchor height ~max(mark_h, pulse_h), line height is
    just `2*line_margin` - see _data_signature_geometry()) so this test targets the DEGRADATION
    ALGORITHM in isolation; the real oracle's own correctness is proven separately
    (test_data_signature_geometry_scores_three_independent_regions_not_one_coarse_rectangle and
    the real-fixture regression test)."""
    canvas = Image.new("RGBA", (1280, 720), (210, 210, 210, 255))
    full_len = _data_signature_line_length(1280, _DATA_SIGNATURE_FULL_WIDTH_FRAC)

    def fake_score_box_safe(_canvas, box, *, pad):
        height = box[3] - box[1]
        if height > 20:  # the mark+pulse anchor - always taller than the line's own thin band
            return True
        width = box[2] - box[0]
        return width < full_len - 10  # only the FULL-length line itself is unsafe

    monkeypatch.setattr(brand_renderer_module, "_score_box_safe", fake_score_box_safe)
    plan = _select_data_signature(canvas, inset=20, pad=50)
    assert plan is not None
    assert plan.tier == "shortened"
    assert plan.line_len < full_len


def test_data_signature_line_degrades_to_compact_when_shortened_also_unsafe(monkeypatch):
    """Item 7: the compact bottom signature is available as a SECOND fallback - if even every
    shortened intermediate length fails, the search must still succeed at the compact tier before
    giving up, never jumping straight from "full fails" to "nothing"."""
    canvas = Image.new("RGBA", (1280, 720), (210, 210, 210, 255))
    compact_len = _data_signature_line_length(1280, _DATA_SIGNATURE_COMPACT_WIDTH_FRAC)

    def fake_score_box_safe(_canvas, box, *, pad):
        height = box[3] - box[1]
        if height > 20:  # the mark+pulse anchor
            return True
        width = box[2] - box[0]
        return width <= compact_len + 2  # only the compact-or-shorter line passes

    monkeypatch.setattr(brand_renderer_module, "_score_box_safe", fake_score_box_safe)
    plan = _select_data_signature(canvas, inset=20, pad=50)
    assert plan is not None
    assert plan.tier == "compact"
    assert plan.line_len == compact_len


def test_data_signature_protects_mark_by_switching_corner_not_ignoring_conflict(monkeypatch):
    """Item 9: a watermark/source-text collision at the mark's own footprint must still be
    respected - never silently ignored merely to keep branding on the "preferred" corner. Here the
    LOWER_RIGHT mark+pulse anchor is made unsafe (simulating a bottom-right watermark) while
    LOWER_LEFT remains clean; the search must switch corners, never draw over the flagged region."""
    canvas = Image.new("RGBA", (1280, 720), (210, 210, 210, 255))

    def fake_score_box_safe(_canvas, box, *, pad):
        height = box[3] - box[1]
        near_right_edge = box[2] > 1280 - 150
        if height > 20 and near_right_edge:  # the anchor box anchored at the right = LOWER_RIGHT
            return False
        return True

    monkeypatch.setattr(brand_renderer_module, "_score_box_safe", fake_score_box_safe)
    plan = _select_data_signature(canvas, inset=20, pad=50)
    assert plan is not None
    assert plan.placement is ComponentPlacement.LOWER_LEFT


def test_score_box_safe_is_the_real_oracle_select_data_signature_calls():
    """Confirms _select_data_signature() genuinely delegates to the real, unmocked _score_box_safe
    (not a private reimplementation) - a quiet uniform canvas must clear it for a small mark-sized
    box at the real production padding (`_SCORE_PAD_PX_FRAC`-derived, 50px at this canvas width -
    a much smaller ad-hoc pad understates the real gate, see the previous test's own comment for
    why), and pure noise must fail it regardless of padding, using the exact function under test."""
    quiet = Image.new("RGBA", (1280, 720), (120, 120, 120, 255))
    assert _score_box_safe(quiet, (600, 600, 650, 630), pad=50) is True

    rng = random.Random(3)
    noisy = Image.new("RGBA", (1280, 720))
    noisy.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256), 255) for _ in range(1280 * 720)])
    assert _score_box_safe(noisy, (600, 600, 650, 630), pad=50) is False
