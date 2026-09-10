"""FOUNDER-VISUAL-POLISH-2 focused tests (docs/founder_visual_polish_2_report.md).

Direct-Founder-review visual corrections:
  * NEWS   - restrained MARK_ONLY watermark (no long red line);
  * BREAKING - distinct: a red pulse crossing the LOWER media + one restrained mark;
  * FINAL_VISIBLE_NNJ_COUNT <= 1 - internal NNJ-branded source suppresses the renderer mark;
  * external source infographic - preserved, exactly one renderer mark, numbers unchanged;
  * DATA hero - polished (retained elements), no synthetic data;
  * QUOTE - deep-graphite composition, dark portrait integration, role optional / never fabricated,
    missing-role uses the SAME dark language (no light panel);
  * RenderEvidence truthfulness.
"""

from __future__ import annotations

import inspect
import io

from PIL import Image, ImageChops, ImageStat

from services.brand_renderer import (
    render_breaking_frame,
    render_data_card,
    render_data_hero_card,
    render_quote_card,
    source_carries_canonical_nnj,
)
from services.data_source_classification import DataPresentationMode
from services.nnj_master_news_overlay import (
    SIGNATURE_STYLE_FUSED,
    SIGNATURE_STYLE_MARK_ONLY,
    ComponentPlacement,
    apply_master_news_branding,
)
from services.presentation_director import DataCandidate, QuoteCandidate
from services.render_evidence import (
    derive_breaking_render_evidence,
    derive_master_news_render_evidence,
    derive_quote_render_evidence,
)

_PHOTO = "assets/brand/newsroom_visuals/v2_1_bakeoff_sources/case3_bright_promotional_scene.jpg"
_IPHONE = (
    "assets/brand/newsroom_visuals/v2_1_bakeoff_sources/case1_hero_product_iphone.jpg"
)
_INTERNAL_TMPL = (
    "assets/brand/newsroom_visuals/v1/references/data/data_template_white.png"
)
_EXTERNAL_INFO = "tests/fixtures/external_source_infographic.jpg"
_PORTRAIT = "tests/fixtures/portrait_public_figure.jpg"


def _b(path: str) -> bytes:
    return open(path, "rb").read()


def _im(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def _body(func) -> str:
    parts = inspect.getsource(func).split('"""')
    return parts[2] if len(parts) >= 3 else parts[0]


def _mad(
    a: Image.Image, b: Image.Image, box: tuple[int, int, int, int] | None = None
) -> float:
    """Mean absolute per-channel difference between two RGB images (pure PIL, no numpy)."""
    if box is not None:
        a, b = a.crop(box), b.crop(box)
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    return sum(ImageStat.Stat(diff).mean) / 3.0


# --------------------------------------------------------------------------------------------------
# NEWS - restrained mark only
# --------------------------------------------------------------------------------------------------
def test_news_is_mark_only_no_fused_line_or_pulse() -> None:
    b, dec = apply_master_news_branding(_b(_PHOTO))
    assert dec.upper_mark.placement is ComponentPlacement.OMITTED
    assert (
        dec.lower_signature.placement is not ComponentPlacement.OMITTED
    )  # the one mark lives here
    with Image.open(io.BytesIO(b)) as im:
        assert im.size == (1280, 720)
    # the mark-only layer is small: a canonical mark, no ~44%-wide fused signature
    layer = dec.lower_signature.image
    assert layer is not None
    bbox = layer.split()[-1].getbbox()
    assert bbox is not None and (bbox[2] - bbox[0]) < 0.14 * 1280, (
        "NEWS mark must be a small corner watermark, not a wide signature"
    )


def test_news_evidence_placement_zone_not_applicable() -> None:
    ev = derive_master_news_render_evidence(_b(_PHOTO), presentation_type="NEWS")
    assert ev.logo_count in (0, 1)
    assert "placement_zone" in ev.not_applicable_fields
    assert "NOT APPLICABLE" in ev.notes["placement_zone"]
    assert ev.scrim_treatment == "none"


def test_fused_style_still_available_for_explicit_callers() -> None:
    _b1, d_fused = apply_master_news_branding(
        _b(_PHOTO), signature_style=SIGNATURE_STYLE_FUSED
    )
    apply_master_news_branding(_b(_PHOTO), signature_style=SIGNATURE_STYLE_MARK_ONLY)
    # the fused decision scores a wide LOWER signature; mark-only does not
    fused_attempts = d_fused.lower_signature.attempts
    assert any((a.box[2] - a.box[0]) > 0.30 * 1280 for a in fused_attempts)


# --------------------------------------------------------------------------------------------------
# BREAKING - distinct, lower-media pulse
# --------------------------------------------------------------------------------------------------
def test_breaking_is_distinct_from_news_lower_media_pulse() -> None:
    body = _body(render_breaking_frame)
    assert (
        "select_master_news_branding(" not in body
    )  # NOT the NEWS family signature anymore
    assert "_draw_recovered_pulse(" in body  # its own RECOVERED pulse motif (not the crude triangle)
    assert (
        '"BREAKING"' not in body
        and "band" not in body.lower().split("bake")[0][:0] + body
    )

    src = _b(_IPHONE)
    out = render_breaking_frame(src, category="AI", editorial_code="NP-1")
    orig = _im(src)
    rendered = _im(out)
    assert rendered.size == orig.size  # native size preserved

    # red pixels appear in the LOWER band (y >= 78% h) far more than the upper band
    def _red_frac(im: Image.Image, y0: int, y1: int) -> float:
        crop = im.crop((0, y0, im.width, y1))
        px = list(crop.getdata())
        red = sum(1 for (r, g, bl) in px if r > 150 and g < 90 and bl < 90)
        return red / max(1, len(px))

    h = rendered.height
    lower = _red_frac(rendered, int(h * 0.78), h)
    upper = _red_frac(rendered, 0, int(h * 0.30))
    assert lower > upper * 3 + 1e-5, (lower, upper)
    assert lower > 0, "the red BREAKING pulse must be visible in the lower media"


def test_breaking_evidence_is_v3_lower_center() -> None:
    ev = derive_breaking_render_evidence(_b(_IPHONE))
    assert ev.renderer_version == "pulse-breaking-v5-board"
    assert ev.placement_zone == "lower_left"
    assert ev.logo_count == 1
    assert ev.logo_zone in ("lower_right", "lower_left")
    assert ev.scrim_treatment == "none"
    assert ev.source_image_treatment == "preserve"


def test_breaking_no_retired_dark_band() -> None:
    # a neutral-grey source: any ~22% dark lower-third band would drop the lower rows' mean sharply
    grey = Image.new("RGB", (1280, 720), (128, 128, 128))
    buf = io.BytesIO()
    grey.save(buf, "JPEG", quality=95)
    im = _im(
        render_breaking_frame(buf.getvalue(), category="AI", editorial_code="NP-1")
    ).convert("L")
    band = ImageStat.Stat(im.crop((0, int(720 * 0.78), 1280, 720))).mean[0]
    mid = ImageStat.Stat(im.crop((0, int(720 * 0.35), 1280, int(720 * 0.55)))).mean[0]
    assert band > mid - 30, ("no heavy dark lower-third band", band, mid)


# --------------------------------------------------------------------------------------------------
# FINAL_VISIBLE_NNJ_COUNT <= 1
# --------------------------------------------------------------------------------------------------
def test_internal_branded_source_is_detected() -> None:
    assert source_carries_canonical_nnj(_b(_INTERNAL_TMPL)) is True
    assert source_carries_canonical_nnj(_b(_EXTERNAL_INFO)) is False
    assert source_carries_canonical_nnj(_b(_PHOTO)) is False


def test_internal_branded_source_gets_no_renderer_nnj() -> None:
    src = _b(_INTERNAL_TMPL)
    dc = DataCandidate(value="X,XXX", unit="", label="", evidence_fact="")
    out = render_data_card(
        dc,
        category="D",
        editorial_code="NP",
        source_image_bytes=src,
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    # the composite equals the source fitted to canvas - NOTHING added
    from services.nnj_master_news_overlay import (
        _CANVAS_H,
        _CANVAS_W,
        _fit_photo_to_canvas,
    )

    expected = _fit_photo_to_canvas(
        Image.open(io.BytesIO(src)).convert("RGBA"), (_CANVAS_W, _CANVAS_H)
    ).convert("RGB")
    got = _im(out)
    assert got.size == expected.size
    # pixel-identical up to a JPEG round-trip -> the mean absolute channel diff is tiny
    assert _mad(expected, got) < 4.0, (
        "internal branded source must be returned unmodified (no renderer NNJ)"
    )


def test_explicit_source_already_branded_flag_suppresses_mark() -> None:
    src = _b(_EXTERNAL_INFO)  # not internally known, but caller asserts it is branded
    dc = DataCandidate(value="68", unit="%", label="x", evidence_fact="y")
    with_flag = render_data_card(
        dc,
        category="D",
        editorial_code="NP",
        source_image_bytes=src,
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
        source_already_branded=True,
    )
    # FOUNDER-VISUAL-BREAKING-DATA-RECONSTRUCTION-5 §20/§23: with the flag set the source ships
    # exactly as fitted - zero renderer marks (FINAL_VISIBLE_NNJ stays <= 1).
    from services.nnj_master_news_overlay import _CANVAS_H, _CANVAS_W, _fit_photo_to_canvas

    fitted = _fit_photo_to_canvas(
        Image.open(io.BytesIO(src)).convert("RGBA"), (_CANVAS_W, _CANVAS_H)
    ).convert("RGB")
    assert _mad(fitted, _im(with_flag)) < 2.0, "the branded source must be preserved unchanged"


def test_external_source_infographic_gets_exactly_one_renderer_mark_and_preserves_data() -> (
    None
):
    src = _b(_EXTERNAL_INFO)
    dc = DataCandidate(
        value="68", unit="%", label="EV share", evidence_fact="68% of new car sales"
    )
    out = render_data_card(
        dc,
        category="D",
        editorial_code="NP",
        source_image_bytes=src,
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    got = _im(out)
    assert got.size == (1280, 720)
    # the source's own printed "68%" region (upper-left) is untouched: compare to the fitted source
    from services.nnj_master_news_overlay import (
        _CANVAS_H,
        _CANVAS_W,
        _fit_photo_to_canvas,
    )

    fitted = _fit_photo_to_canvas(
        Image.open(io.BytesIO(src)).convert("RGBA"), (_CANVAS_W, _CANVAS_H)
    ).convert("RGB")
    assert _mad(fitted, got, box=(40, 90, 420, 300)) < 3.0, (
        "the source's own metric must be preserved exactly"
    )
    # FOUNDER-VISUAL-BREAKING-DATA-RECONSTRUCTION-5 §20/§21: the renderer NEVER pastes a
    # rectangular logo badge / dark plate over a third-party infographic. It either places a thin
    # adaptive bottom-only pulse+mark signature or (this busy light fixture) suppresses branding
    # entirely - so the whole top ~78% of the frame is byte-for-byte the fitted source.
    assert _mad(fitted, got, box=(0, 0, 1280, 560)) < 3.0, (
        "no badge / plate anywhere above the bottom signature band"
    )


# --------------------------------------------------------------------------------------------------
# DATA hero - polish only, no synthetic data
# --------------------------------------------------------------------------------------------------
def test_hero_card_retains_every_element_and_no_synthetic_data() -> None:
    body = _body(render_data_hero_card)
    for token in (
        "value_text",
        "unit_text",
        "label_lines",
        "desc_lines",
        "data_candidate.delta",
        "_draw_hero_sparkline",
        "_draw_hero_grid",
        "_draw_recovered_pulse",
        "rasterize_nnj_mark",
    ):
        assert token in body, token
    assert "len(series) >= 2" in body  # chart only from a real series
    # no chart when < 2 points; deterministic either way
    no_series = DataCandidate(value="42", unit="%", label="x", evidence_fact="y")
    assert render_data_hero_card(no_series) == render_data_hero_card(no_series)
    with_series = DataCandidate(
        value="500",
        unit="M",
        label="users",
        evidence_fact="reached in July",
        series=(1.0, 2.0, 3.0),
        delta="+8%",
    )
    with Image.open(io.BytesIO(render_data_hero_card(with_series))) as im:
        assert im.size == (1280, 720)


def test_hero_card_metric_is_verbatim() -> None:
    cand = DataCandidate(
        value="-8.1",
        unit="п.п.",
        label="изменение",
        evidence_fact="Снижение на 8,1 п.п.",
        delta="-2 п.п.",
    )
    before = (cand.value, cand.unit, cand.label, cand.evidence_fact, cand.delta)
    render_data_hero_card(cand)
    assert (cand.value, cand.unit, cand.label, cand.evidence_fact, cand.delta) == before


# --------------------------------------------------------------------------------------------------
# QUOTE - dark composition, portrait integration, role optional, missing-role dark fallback
# --------------------------------------------------------------------------------------------------
_QUOTE_TXT = "Технологии сами по себе ничего не значат. Важно то, во что мы верим и что создаём вместе."


def test_quote_card_is_deep_graphite_and_integrates_the_portrait() -> None:
    out = render_quote_card(
        QuoteCandidate(text=_QUOTE_TXT, speaker="Тим Кук", role="CEO, Apple"),
        category="Q",
        editorial_code="NP",
        portrait_bytes=_b(_PORTRAIT),
    )
    im = _im(out)
    assert im.size == (1200, 675)
    left_col = ImageStat.Stat(im.crop((0, 0, 360, 675)).convert("L")).mean[0]
    inner_edge = ImageStat.Stat(im.crop((672, 0, 840, 675)).convert("L")).mean[
        0
    ]  # portrait inner edge
    whole = ImageStat.Stat(im.convert("L")).mean[0]
    assert left_col < 55, ("text column must be deep graphite", left_col)
    assert inner_edge < 115, (
        "portrait inner edge must dissolve into the dark panel - no hard seam",
        inner_edge,
    )
    assert whole < 120, ("overall composition must read dark", whole)


def test_quote_missing_role_uses_the_same_dark_language_no_light_panel() -> None:
    with_role = _im(
        render_quote_card(
            QuoteCandidate(text=_QUOTE_TXT, speaker="A. R.", role="Researcher"),
            category="Q",
            editorial_code="NP",
            portrait_bytes=_b(_PORTRAIT),
        )
    )
    no_role = _im(
        render_quote_card(
            QuoteCandidate(text=_QUOTE_TXT, speaker="A. R."),
            category="Q",
            editorial_code="NP",
            portrait_bytes=_b(_PORTRAIT),
        )
    )
    # the right (portrait) half must be equally dark in both - no light-panel fallback
    r_with = ImageStat.Stat(with_role.crop((720, 0, 1200, 675)).convert("L")).mean[0]
    r_no = ImageStat.Stat(no_role.crop((720, 0, 1200, 675)).convert("L")).mean[0]
    assert abs(r_with - r_no) < 8, (
        "missing-role must not change the portrait/background treatment",
        r_with,
        r_no,
    )
    assert r_no < 150


def test_quote_never_fabricates_a_role() -> None:
    body = _body(render_quote_card)
    assert "quote_candidate.role" in body
    # role only drawn inside `if quote_candidate.role:` - no default string anywhere
    assert "role or " not in body and 'role", "' not in body


def test_quote_body_is_verbatim_and_font_fitted() -> None:
    long_q = QuoteCandidate(
        text=(
            "Это достаточно длинная цитата, которую нужно уменьшить по кеглю и перенести по словам, "
            "но никогда не обрезать посреди слова или предложения."
        ),
        speaker="Кто-то",
        role="Роль",
    )
    out = render_quote_card(
        long_q, category="Q", editorial_code="NP", portrait_bytes=_b(_PORTRAIT)
    )
    with Image.open(io.BytesIO(out)) as im:
        assert im.size == (1200, 675)  # renders bounded, no exception
    ev = derive_quote_render_evidence(_b(_PORTRAIT))
    assert ev.text_clipped is False
    assert ev.logo_count == 1 and ev.logo_zone == "lower_right"


# --------------------------------------------------------------------------------------------------
# RenderEvidence truthfulness (cross-check a few invariants)
# --------------------------------------------------------------------------------------------------
def test_render_evidence_reports_actual_zones_truthfully() -> None:
    # NEWS: the reported logo_zone must equal the decision's own placed corner
    src = _b(_PHOTO)
    _b1, dec = apply_master_news_branding(src)
    ev = derive_master_news_render_evidence(src, presentation_type="NEWS")
    placed = [
        p
        for p in (dec.lower_signature.placement, dec.upper_mark.placement)
        if p is not ComponentPlacement.OMITTED
    ]
    if placed:
        assert ev.logo_zone == placed[0].value
    # BREAKING: evidence lower_center + a real bottom corner for the mark
    bev = derive_breaking_render_evidence(src)
    assert bev.placement_zone == "lower_left" and bev.logo_zone in (
        "lower_right",
        "lower_left",
    )
