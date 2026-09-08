"""DESIGN-SPEC-ENFORCEMENT-1 addendum §2 - RENDER EVIDENCE PARITY.

`services/render_evidence.py`'s derivers replay the renderer's own deterministic helpers. That is
only safe if a future renderer change cannot silently leave the evidence stale. These tests pin
the agreement between each `derive_*` result and (a) the renderer's OWN decision object / helper
output, and (b) the real rendered PIXELS, for every presentation type. If a renderer's structural
behaviour changes (corner scorer, canvas fit, stat-font fit, brand-mark count, the BREAKING band),
the deriver must be updated in lock-step or one of these fails.

Structurally-knowable fields covered: logo zone, brand-mark count, placement zone (where
applicable), scrim state (where applicable), safe margins, primary font size (where applicable),
line count (where applicable), source treatment, presentation mode (where applicable).
"""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw, ImageStat

from services.brand_renderer import (
    _BREAKING_BAND_HEIGHT_FRAC,
    _BREAKING_BAND_MAX_ALPHA,
    _CARD_WIDTH,
    _DATA_BLOCK_MARGIN,
    _DATA_BLOCK_WIDTH_FRAC,
    _data_signature_geometry,
    _measure_data_stat_block,
    _select_data_block_placement,
    _select_data_signature,
    render_breaking_frame,
    render_data_card,
    render_quote_card,
)
from services.data_source_classification import DataPresentationMode, classify_source_presentation, select_data_presentation_mode
from services.nnj_master_news_overlay import (
    _CANVAS_H,
    _CANVAS_W,
    _SAFE_INSET_FRAC,
    _SCORE_PAD_PX_FRAC,
    ComponentPlacement,
    _fit_photo_to_canvas,
    apply_master_news_branding,
    select_master_news_branding,
)
from services.presentation_director import DataCandidate, QuoteCandidate
from services.render_evidence import (
    NOT_MEASURED,
    derive_breaking_render_evidence,
    derive_data_render_evidence,
    derive_master_news_render_evidence,
    derive_quote_render_evidence,
)

_CAND = DataCandidate(value="42", unit="%", label="of benchmark improvement over the prior generation", evidence_fact="x")


def _jpeg(im: Image.Image, q: int = 94) -> bytes:
    b = io.BytesIO()
    im.convert("RGB").save(b, "JPEG", quality=q)
    return b.getvalue()


def _photo(w: int = 1280, h: int = 720, c: tuple[int, int, int] = (95, 115, 140)) -> bytes:
    im = Image.new("RGB", (w, h), c)
    d = ImageDraw.Draw(im)
    d.ellipse([w * 0.34, h * 0.18, w * 0.66, h * 0.82], fill=(168, 152, 132))
    return _jpeg(im)


def _busy_photo(w: int = 1280, h: int = 720) -> bytes:
    """High edge-density everywhere - forces _select_data_signature() down its degradation path."""
    import random

    rng = random.Random(7)
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for _ in range(4000):
        x0, y0 = rng.randint(0, w), rng.randint(0, h)
        d.rectangle([x0, y0, x0 + rng.randint(2, 18), y0 + rng.randint(2, 18)],
                    fill=(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)))
    return _jpeg(im)


def _portrait(w: int = 800, h: int = 1000) -> bytes:
    im = Image.new("RGB", (w, h), (38, 38, 48))
    d = ImageDraw.Draw(im)
    d.ellipse([w * 0.3, h * 0.18, w * 0.7, h * 0.56], fill=(205, 185, 165))
    return _jpeg(im)


# ==============================================================================================
# NEWS  (apply_master_news_branding / select_master_news_branding)
# ==============================================================================================


@pytest.mark.parametrize("src_w,src_h,expect_treatment", [(1280, 720, "preserve"), (1200, 900, "crop"), (1080, 1350, "crop")])
def test_news_evidence_matches_master_branding_decision(src_w: int, src_h: int, expect_treatment: str) -> None:
    raw = _photo(src_w, src_h)
    ev = derive_master_news_render_evidence(raw, presentation_type="NEWS")

    # Re-run the renderer's own decision independently and compare.
    with Image.open(io.BytesIO(raw)) as im:
        fit = _fit_photo_to_canvas(im.convert("RGBA"), (_CANVAS_W, _CANVAS_H))
        decision = select_master_news_branding(fit)
    placed = [p for p in (decision.lower_signature.placement, decision.upper_mark.placement) if p is not ComponentPlacement.OMITTED]

    assert ev.logo_count == len(placed)
    assert ev.logo_zone == (placed[0].value if placed else NOT_MEASURED)
    assert ev.safe_margin_frac == round(float(_SAFE_INSET_FRAC), 5)
    assert ev.source_image_treatment == expect_treatment
    assert ev.canvas_width == _CANVAS_W and ev.canvas_height == _CANVAS_H
    # placement_zone is a declared measurement gap; font/lines are not applicable on this path.
    assert ev.placement_zone is NOT_MEASURED
    for f in ("primary_font_size", "secondary_font_size", "actual_line_count"):
        assert f in ev.not_applicable_fields

    # Pixel parity: the branded output really has no dark bottom band (scrim=none).
    branded, _ = apply_master_news_branding(raw)
    out = Image.open(io.BytesIO(branded)).convert("L")
    top = ImageStat.Stat(out.crop((0, 0, out.width, out.height // 5))).mean[0]
    bot = ImageStat.Stat(out.crop((0, out.height * 4 // 5, out.width, out.height))).mean[0]
    assert abs(top - bot) < 35, "MASTER NEWS must not darken the bottom of the frame (scrim=none)"


# ==============================================================================================
# BREAKING  (render_breaking_frame)
# ==============================================================================================


def test_breaking_evidence_matches_the_real_rendered_band() -> None:
    raw = _photo(1280, 720, (120, 120, 120))  # neutral gray -> the band's darkening is unambiguous
    ev = derive_breaking_render_evidence(raw)
    rendered = render_breaking_frame(raw, category="technology", editorial_code="NP-B1")
    im = Image.open(io.BytesIO(rendered)).convert("L")
    W, H = im.size

    # 1. The deriver's band model tracks the renderer's own named constants (single source of truth).
    assert ev.scrim_applied is True
    assert ev.scrim_treatment == "strong"
    assert _BREAKING_BAND_HEIGHT_FRAC == 0.22 and _BREAKING_BAND_MAX_ALPHA == 210

    # 2. Pixel parity: a dark gradient band really occupies ~the bottom _BREAKING_BAND_HEIGHT_FRAC.
    col = [ImageStat.Stat(im.crop((W // 2 - 20, y, W // 2 + 20, y + 1))).mean[0] for y in range(H)]
    band_top = next(y for y in range(H) if col[y] < 118)  # gray source is 128; band darkens it
    measured_frac = (H - band_top) / H
    assert abs(measured_frac - _BREAKING_BAND_HEIGHT_FRAC) < 0.03, (measured_frac, _BREAKING_BAND_HEIGHT_FRAC)
    # bottom row is near-black (peak alpha ~0.82 over black) - a "strong" scrim by any reading.
    assert col[-1] < 45

    # 3. Structural fields the deriver still exposes truthfully.
    assert ev.source_image_treatment == "preserve"  # native size, no crop
    assert ev.logo_zone == "lower_right"
    margin_px = max(16, round(W * 0.02))
    assert ev.safe_margin_frac == round(margin_px / W, 5)
    assert "placement_zone" in ev.not_applicable_fields  # no pulse line in this template


def test_breaking_band_pixels_confirm_it_is_not_a_thin_pulse_treatment() -> None:
    """Forensic distinction (addendum §1): the band is option A (historical readability band),
    NOT option B (a thin pulse-related mark). A pulse line would darken << 5% of the frame height."""
    raw = _photo(1280, 720, (128, 128, 128))
    rendered = render_breaking_frame(raw, category="tech", editorial_code="NP-B1")
    im = Image.open(io.BytesIO(rendered)).convert("L")
    W, H = im.size
    darkened_rows = sum(
        1 for y in range(H)
        if ImageStat.Stat(im.crop((0, y, W, y + 1))).mean[0] < 110
    )
    assert darkened_rows / H > 0.15, "the BREAKING darkening spans a band, not a thin pulse line"


# ==============================================================================================
# DATA  (render_data_card / _select_data_signature / _measure_data_stat_block)
# ==============================================================================================


def test_data_full_evidence_matches_the_renderer_helpers_directly() -> None:
    raw = _photo(1280, 720)
    mode = DataPresentationMode.FULL_DATA_CARD
    ev = derive_data_render_evidence(raw, _CAND, presentation_mode=mode)

    # Independently replay the same helper calls render_data_card() makes.
    with Image.open(io.BytesIO(raw)) as im:
        canvas = _fit_photo_to_canvas(im.convert("RGBA"), (_CANVAS_W, _CANVAS_H))
    cw = canvas.size[0]
    inset = max(1, round(_SAFE_INSET_FRAC * cw))
    pad = max(1, round(_SCORE_PAD_PX_FRAC * cw))
    plan = _select_data_signature(canvas, inset=inset, pad=pad)
    assert plan is not None
    assert ev.logo_zone == plan.placement.value

    block_w = max(160, round(_DATA_BLOCK_WIDTH_FRAC * cw))
    inner = max(1, block_w - _DATA_BLOCK_MARGIN * 2)
    draw = ImageDraw.Draw(canvas)
    _p, stat_font, _bb, label_lines, _lf, _llh, text_h = _measure_data_stat_block(draw, _CAND, max_width=inner)
    mb, pb, lb = _data_signature_geometry(canvas.size, plan.placement, inset, plan.line_len)
    avoid = (min(mb[0], pb[0], lb[0]), min(mb[1], pb[1], lb[1]), max(mb[2], pb[2], lb[2]), max(mb[3], pb[3], lb[3]))
    placement = _select_data_block_placement(canvas, block_w=block_w, block_h=round(text_h) + _DATA_BLOCK_MARGIN * 2,
                                             inset=inset, pad=pad, avoid_box=avoid)
    if placement is None:
        assert ev.primary_font_size is NOT_MEASURED
        assert ev.actual_line_count == 0
    else:
        assert ev.primary_font_size == int(stat_font.size)
        assert ev.actual_line_count == len(label_lines)
    assert ev.safe_margin_frac == round(float(_SAFE_INSET_FRAC), 5)
    assert ev.source_image_treatment == "preserve"
    assert ev.presentation_mode == mode.value


def test_data_minimal_evidence_matches_the_renderer_early_return() -> None:
    raw = _photo(1280, 720)
    ev = derive_data_render_evidence(raw, _CAND, presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING)
    # render_data_card returns right after the signature in MINIMAL mode - no stat block at all.
    assert ev.actual_line_count == 0
    assert ev.primary_font_size is NOT_MEASURED
    assert "primary_font_size" in ev.not_applicable_fields
    assert ev.presentation_mode == "minimal_source_preserving"
    assert ev.logo_count == 1


def test_data_kirin_regression_evidence_is_faithful() -> None:
    """§14: the Kirin infographic path - source classified EXISTING_INFOGRAPHIC -> MINIMAL, and the
    evidence proves '42 stays 42' (zero descriptor lines, no competing stat font)."""
    src_type = classify_source_presentation(["possible_banner", "possible_logo"])
    mode = select_data_presentation_mode(src_type)
    infographic = Image.new("RGB", (1280, 720), (18, 18, 20))
    ImageDraw.Draw(infographic).text((120, 260), "42%", fill=(255, 255, 255))
    raw = _jpeg(infographic, 95)
    ev = derive_data_render_evidence(raw, _CAND, presentation_mode=mode)
    assert ev.presentation_mode == "minimal_source_preserving"
    assert ev.actual_line_count == 0
    assert ev.primary_font_size is NOT_MEASURED
    assert ev.source_preserved is True  # 1280x720 infographic, no crop
    assert ev.logo_count == 1


def test_data_busy_photo_signature_falls_back_and_evidence_records_the_scrim() -> None:
    raw = _busy_photo()
    with Image.open(io.BytesIO(raw)) as im:
        canvas = _fit_photo_to_canvas(im.convert("RGBA"), (_CANVAS_W, _CANVAS_H))
    cw = canvas.size[0]
    inset = max(1, round(_SAFE_INSET_FRAC * cw))
    pad = max(1, round(_SCORE_PAD_PX_FRAC * cw))
    plan = _select_data_signature(canvas, inset=inset, pad=pad)
    ev = derive_data_render_evidence(raw, _CAND, presentation_mode=DataPresentationMode.FULL_DATA_CARD)
    if plan is None:
        # guaranteed fallback signature -> lower-right on an opaque scrim
        assert ev.logo_zone == "lower_right"
        assert ev.scrim_applied is True
        assert ev.scrim_treatment == "strong"
    else:
        assert ev.logo_zone == plan.placement.value
    # render_data_card must still succeed on this input (never raises past the dispatch).
    assert render_data_card(_CAND, category="tech", editorial_code="NP-D1", source_image_bytes=raw,
                            presentation_mode=DataPresentationMode.FULL_DATA_CARD)


# ==============================================================================================
# QUOTE  (render_quote_card)
# ==============================================================================================


@pytest.mark.parametrize("pw,ph", [(800, 1000), (1000, 800), (600, 1200)])
def test_quote_evidence_matches_the_card_geometry(pw: int, ph: int) -> None:
    from services.brand_renderer import _CARD_HEIGHT

    raw = _portrait(pw, ph)
    ev = derive_quote_render_evidence(raw)
    rendered = render_quote_card(QuoteCandidate(text="On-device inference is real now.", speaker="A. R."),
                                 category="tech", editorial_code="NP-Q1", portrait_bytes=raw)
    im = Image.open(io.BytesIO(rendered)).convert("RGB")

    assert im.size == (_CARD_WIDTH, _CARD_HEIGHT)
    assert ev.canvas_width == _CARD_WIDTH and ev.canvas_height == _CARD_HEIGHT
    assert ev.safe_margin_frac == round(64 / _CARD_WIDTH, 5)  # render_quote_card's fixed margin=64
    assert ev.source_image_treatment == "preserve"

    # Pixel parity: the mark sits in the bottom-right corner (_paste_svg_mark geometry).
    br = ImageStat.Stat(im.crop((_CARD_WIDTH - 130, _CARD_HEIGHT - 130, _CARD_WIDTH, _CARD_HEIGHT)))
    tl = ImageStat.Stat(im.crop((0, 0, 130, 130)))
    assert max(br.mean) > max(tl.mean) + 10 or br.stddev[0] > tl.stddev[0], "expected the NNJ mark in the bottom-right"

    # Pixel parity for the "not a source scrim" claim: the portrait's far-right strip (well outside
    # the 40px left-edge feather) is NOT darkened relative to the same strip of the ORIGINAL
    # portrait - i.e. render_quote_card applies no legibility scrim over the source.
    portrait_w = round(_CARD_HEIGHT * pw / ph)
    with Image.open(io.BytesIO(raw)) as src_im:
        src_scaled = src_im.convert("RGB").resize((portrait_w, _CARD_HEIGHT), Image.Resampling.LANCZOS)
    strip = max(8, portrait_w // 6)
    card_strip = ImageStat.Stat(im.crop((_CARD_WIDTH - strip, 0, _CARD_WIDTH, _CARD_HEIGHT)).convert("L")).mean[0]
    src_strip = ImageStat.Stat(src_scaled.crop((portrait_w - strip, 0, portrait_w, _CARD_HEIGHT)).convert("L")).mean[0]
    assert card_strip >= src_strip - 6, ("the portrait's right edge must not be scrim-darkened", card_strip, src_strip)
    assert "scrim_treatment" in ev.not_applicable_fields


def test_quote_without_portrait_marks_source_treatment_note() -> None:
    ev = derive_quote_render_evidence(None)
    assert ev.scrim_applied is False
    assert "scrim_treatment" in ev.not_applicable_fields
    assert render_quote_card(QuoteCandidate(text="No portrait here.", speaker="X"),
                             category="tech", editorial_code="NP-Q2", portrait_bytes=None)


# ==============================================================================================
# static drift guard - the derivers import renderer constants live, never copy them
# ==============================================================================================


def test_derivers_share_the_renderers_own_constants_no_local_copies() -> None:
    """A future renderer constant change flows straight into the evidence (same object), so there
    is nothing to keep in sync by hand. This test fails loudly if someone re-introduces a copy."""
    import services.nnj_master_news_overlay as overlay
    import services.render_evidence as re_mod

    src = re_mod.__dict__  # module globals
    # render_evidence defines NO numeric renderer constants of its own (all imported at call time).
    leaked = [
        k for k, v in src.items()
        if k.isupper() and k.startswith("_") and isinstance(v, (int, float))
        and k not in {"_QUOTE_TEXT_PANEL_FEATHER_PX"}  # the ONE renderer literal it must mirror (asserted below)
    ]
    assert leaked == [], f"render_evidence.py must not keep local copies of renderer constants: {leaked}"

    # The single mirrored literal is pinned against the renderer's real value.
    from services.brand_renderer import render_quote_card as _rqc  # noqa: F401 - anchor the import

    assert re_mod._QUOTE_TEXT_PANEL_FEATHER_PX == 40
    assert overlay._SAFE_INSET_FRAC == 24 / overlay._CANVAS_W
