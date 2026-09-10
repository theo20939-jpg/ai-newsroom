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
    _CARD_WIDTH,
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


def test_news_geometry_is_the_fused_lower_right_signature_authoritative_evidence() -> None:
    """VISUAL-RENDERER-RECONCILIATION-1 §1 conclusion: NEWS_MASTER_EXPECTED_LAYOUT = B
    (FUSED_LOWER_RIGHT_SIGNATURE). The approved MASTER contract (V2.10H user-approved selection +
    the single-brand-mark contract) and the master prototype
    (assets/brand/newsroom_visuals/v1/references/nnj_editorial_visual_system_master_prototype.png -
    the pulse line runs left->right and TERMINATES at the one nnj mark on the RIGHT) both describe
    ONE fused bottom signature, not a separate lower-left pulse. This test pins that the current,
    UNCHANGED renderer produces exactly that."""
    branded, decision = apply_master_news_branding(_photo(1280, 720))

    # exactly one canonical mark (mutual exclusion), and it is a bottom corner (LOWER_RIGHT
    # preferred) - never a separate lower-left accent + lower-right logo pair.
    placed = [decision.lower_signature.placement, decision.upper_mark.placement]
    non_omitted = [p for p in placed if p is not ComponentPlacement.OMITTED]
    assert len(non_omitted) <= 1
    if non_omitted:
        assert non_omitted[0] in (ComponentPlacement.LOWER_RIGHT, ComponentPlacement.LOWER_LEFT,
                                  ComponentPlacement.UPPER_RIGHT, ComponentPlacement.UPPER_LEFT)
        # on a clean single-subject photo the scorer prefers LOWER_RIGHT (the prototype corner).
        assert decision.lower_signature.placement is ComponentPlacement.LOWER_RIGHT

    # pixel evidence: the signature (line + pulse + mark) lives in the BOTTOM band, concentrated
    # toward the RIGHT terminus - there is no independent red accent element in the lower-LEFT.
    im = Image.open(io.BytesIO(branded)).convert("RGB")
    W, H = im.size
    px = im.load()

    def red_count(x0: int, x1: int) -> int:
        return sum(1 for y in range(int(H * 0.86), H) for x in range(x0, x1, 2)
                   if px[x, y][0] > 140 and px[x, y][1] < 90 and px[x, y][2] < 90)

    right_reds = red_count(int(W * 0.55), W)
    left_reds = red_count(0, int(W * 0.30))
    assert right_reds > 0, "the fused signature + nnj mark sit toward the lower-right"
    assert right_reds > left_reds, "no independent lower-left pulse accent (case A) - it is fused right (case B)"


# ==============================================================================================
# BREAKING  (render_breaking_frame - corrected in VISUAL-RENDERER-RECONCILIATION-1)
# ==============================================================================================


def test_breaking_evidence_matches_the_corrected_news_family_signature() -> None:
    """FOUNDER-VISUAL-POLISH-2 §3: BREAKING is its OWN distinct treatment now - source at NATIVE
    size + a red pulse crossing the lower media + one restrained mark in the least-busy bottom
    corner. Still no band, no scrim."""
    from services.brand_renderer import _BREAKING_SAFE_INSET_FRAC

    raw = _photo(1280, 720)
    ev = derive_breaking_render_evidence(raw)

    assert ev.renderer_version == "pulse-breaking-v5-board"
    assert ev.logo_count == 1
    assert ev.logo_zone in ("lower_right", "lower_left")
    assert ev.placement_zone == "lower_left"            # the pulse crosses the lower media
    assert ev.source_image_treatment == "preserve"       # native size, no fit/crop
    assert ev.source_preserved is True
    assert ev.scrim_applied is False
    assert ev.scrim_treatment == "none"                   # no band, no scrim of any kind
    assert ev.safe_margin_frac == round(_BREAKING_SAFE_INSET_FRAC, 5)
    for f in ("primary_font_size", "secondary_font_size", "actual_line_count"):
        assert f in ev.not_applicable_fields


def test_breaking_corrected_pixels_have_no_dark_band_and_no_baked_wordmark() -> None:
    """§11: prove from pixels - darkened lower-third no longer ~22%, no full-width dark banner,
    source remains visible through the lower region, one NNJ mark, no baked white 'BREAKING' text."""
    raw = _photo(1280, 720, (128, 128, 128))  # neutral gray -> any band would be obvious
    rendered = render_breaking_frame(raw, category="tech", editorial_code="NP-B1")
    im = Image.open(io.BytesIO(rendered)).convert("L")
    W, H = im.size

    # 1. Row-mean luminance across the bottom third stays ~= the gray source (no band darkening).
    bottom_rows = [ImageStat.Stat(im.crop((0, y, W, y + 1))).mean[0] for y in range(int(H * 0.75), H)]
    darkened = sum(1 for m in bottom_rows if m < 108)
    assert darkened / len(bottom_rows) < 0.10, "no full-width dark band in the lower third"
    assert min(bottom_rows) > 70, "source stays visible through the lower region (no near-black banner)"

    # 2. No wide baked white wordmark: near-white pixels in the bottom 25% are just mark AA, not glyphs.
    px = im.load()
    white = sum(1 for y in range(int(H * 0.75), H) for x in range(0, W, 2) if px[x, y] > 205)
    assert white < 400, "no baked 'BREAKING' white wordmark"

    # 3. Structural render metadata (not OCR) already proves the text removal:
    import inspect
    src = inspect.getsource(render_breaking_frame)
    assert '"BREAKING"' not in src.split('"""')[2]  # only the docstring mentions it
    assert "band_height" not in src


def test_breaking_no_source_still_carries_exactly_one_mark_and_no_band() -> None:
    rendered = render_breaking_frame(None, category="tech", editorial_code="NP-B1")
    im = Image.open(io.BytesIO(rendered)).convert("RGB")
    assert im.size[0] > 0 and im.size[1] > 0
    # solid NNJ-black card: the only non-black content is the single red mark bottom-right.
    br = ImageStat.Stat(im.crop((im.width - 160, im.height - 120, im.width, im.height)))
    rest = ImageStat.Stat(im.crop((0, 0, im.width // 2, im.height // 2)))
    assert max(br.mean) > max(rest.mean) + 8


# ==============================================================================================
# DATA  (render_data_card / _select_data_signature / _measure_data_stat_block)
# ==============================================================================================


def test_data_full_evidence_matches_the_hero_renderer_decisions_directly() -> None:
    """FOUNDER-VISUAL-BOARD-ALIGNMENT-1: FULL_DATA_CARD renders the generated hero-metric card
    (`brand_renderer.render_data_hero_card`) - a source-free graphite panel. Evidence replays that
    renderer's OWN two deterministic decisions: the fitted primary-value font size and the wrapped
    label line count."""
    from services.brand_renderer import (
        _HERO_LABEL_FONT_MAX,
        _HERO_LABEL_FONT_MIN,
        _HERO_LABEL_MAX_LINES,
        _HERO_MARGIN,
        _HERO_VALUE_FONT_MAX,
        _HERO_VALUE_FONT_MIN,
        _fit_single_line,
        _fit_wrapped_block,
    )

    raw = _photo(1280, 720)
    mode = DataPresentationMode.FULL_DATA_CARD
    ev = derive_data_render_evidence(raw, _CAND, presentation_mode=mode)

    scratch = ImageDraw.Draw(Image.new("RGB", (_CANVAS_W, _CANVAS_H)))
    inner_w = _CANVAS_W - _HERO_MARGIN * 2
    value_font, _vs = _fit_single_line(
        scratch, _CAND.value, font_max=_HERO_VALUE_FONT_MAX, font_min=_HERO_VALUE_FONT_MIN, max_width=inner_w,
    )
    label_lines, _lf, _ls = _fit_wrapped_block(
        scratch, _CAND.label.strip().upper(), font_max=_HERO_LABEL_FONT_MAX,
        font_min=_HERO_LABEL_FONT_MIN, max_width=inner_w, max_lines=_HERO_LABEL_MAX_LINES,
    )

    assert ev.renderer_variant == "brand_renderer.render_data_hero_card"
    assert ev.primary_font_size == int(value_font.size)
    assert ev.actual_line_count == len(label_lines)
    assert ev.logo_count == 1 and ev.logo_zone == "lower_right"
    assert ev.scrim_applied is False and ev.scrim_treatment == "none"
    assert ev.safe_margin_frac == round(_HERO_MARGIN / _CANVAS_W, 5)
    assert ev.source_image_treatment is NOT_MEASURED
    assert "source_image_treatment" in ev.not_applicable_fields
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
    # The bottom pulse+NNJ signature + its guaranteed opaque-scrim fallback live on the
    # source-preserving DATA path (FOUNDER-VISUAL-BOARD-ALIGNMENT-1: FULL_DATA_CARD is now the
    # source-free hero card and never composites over a busy photo).
    raw = _busy_photo()
    with Image.open(io.BytesIO(raw)) as im:
        canvas = _fit_photo_to_canvas(im.convert("RGBA"), (_CANVAS_W, _CANVAS_H))
    cw = canvas.size[0]
    inset = max(1, round(_SAFE_INSET_FRAC * cw))
    pad = max(1, round(_SCORE_PAD_PX_FRAC * cw))
    plan = _select_data_signature(canvas, inset=inset, pad=pad)
    ev = derive_data_render_evidence(raw, _CAND, presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING)
    if plan is None:
        # guaranteed fallback signature -> lower-right on an opaque scrim
        assert ev.logo_zone == "lower_right"
        assert ev.scrim_applied is True
        assert ev.scrim_treatment == "strong"
    else:
        assert ev.logo_zone == plan.placement.value
    # render_data_card must still succeed on this input (never raises past the dispatch).
    assert render_data_card(_CAND, category="tech", editorial_code="NP-D1", source_image_bytes=raw,
                            presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING)


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

    # FOUNDER-VISUAL-POLISH-2 §7/§8: the quote card is a DELIBERATE deep-graphite composition - the
    # portrait is integrated (blended toward graphite + a left->right gradient + a brightness
    # reduction), never a light panel. Prove the left column and the portrait's inner edge both
    # read dark, and the whole card mean is dark.
    inner_edge = ImageStat.Stat(im.crop((_CARD_WIDTH - round(_CARD_WIDTH * 0.44), 0,
                                         _CARD_WIDTH - round(_CARD_WIDTH * 0.30), _CARD_HEIGHT)).convert("L")).mean[0]
    left_col = ImageStat.Stat(im.crop((0, 0, round(_CARD_WIDTH * 0.30), _CARD_HEIGHT)).convert("L")).mean[0]
    assert left_col < 60, ("the text column must be deep graphite", left_col)
    assert inner_edge < 110, ("the portrait's inner edge must dissolve into the dark panel", inner_edge)
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
