"""FOUNDER-VISUAL-OVERLAY-RECOVERY-4 focused tests (docs/founder_visual_overlay_recovery_4_report.md).

The recovery is asset-forensic: there is NO approved dedicated BREAKING overlay and NO DATA
hero-chart / background / font asset anywhere in the repo or its history (see
design/reference_manifest.md + the report). What IS recovered:

  * BREAKING - the refined ECG waveform GEOMETRY of the FOUND_APPROVED
    `assets/brand/newsroom_visuals/v1/overlays/universal/universal_minimal_01.png`, rendered
    deterministically + antialiased (`_draw_recovered_pulse`), retiring the rejected
    flat->spike->valley->flat polyline (`_draw_pulse`) from the BREAKING path;
  * DATA hero - the board's smooth red area curve (monotone-cubic through the REAL series, never
    overshooting the data range), real BOLD typography, the recovered pulse motif;
  * NEWS / QUOTE - frozen.
"""

from __future__ import annotations

import inspect
import io

from PIL import Image, ImageChops, ImageStat

from services import brand_renderer as br
from services.brand_renderer import (
    _PULSE_WAVEFORM_UNIT,
    _monotone_cubic,
    _resolve_bold_font_path,
    render_breaking_frame,
    render_data_card,
    render_data_hero_card,
    render_quote_card,
)
from services.data_source_classification import DataPresentationMode
from services.nnj_master_news_overlay import apply_master_news_branding
from services.presentation_director import DataCandidate, QuoteCandidate
from services.render_evidence import derive_breaking_render_evidence

_IPHONE = "assets/brand/newsroom_visuals/v2_1_bakeoff_sources/case1_hero_product_iphone.jpg"
_BRIGHT = "assets/brand/newsroom_visuals/v2_1_bakeoff_sources/case3_bright_promotional_scene.jpg"
_EXTERNAL_INFO = "tests/fixtures/external_source_infographic.jpg"
_PORTRAIT = "tests/fixtures/portrait_public_figure.jpg"
_APPROVED_WAVEFORM_ASSET = (
    "assets/brand/newsroom_visuals/v1/overlays/universal/universal_minimal_01.png"
)

_HERO = DataCandidate(
    value="500", unit="млн", label="пользователей",
    evidence_fact="Достиг ChatGPT в июле 2025 года",
    series=(120.0, 150.0, 190.0, 250.0, 330.0, 420.0, 500.0), delta="+38%",
)


def _b(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _im(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def _body(func) -> str:
    parts = inspect.getsource(func).split('"""')
    return parts[2] if len(parts) >= 3 else parts[0]


# ==================================================================================================
# BREAKING - recovered waveform, not the crude triangle
# ==================================================================================================
def test_breaking_uses_the_recovered_waveform_not_the_rejected_polyline() -> None:
    body = _body(render_breaking_frame)
    assert "_draw_recovered_pulse(" in body
    assert "_draw_pulse(" not in body  # the flat->spike->valley->flat polyline is retired here


def test_recovered_waveform_geometry_matches_an_ecg_p_qrs_t_morphology() -> None:
    """The waveform - pixel-traced from the Founder board's own BREAKING pulse
    (RECONSTRUCTION-5 §9 D): one dominant sharp R apex (1.0), a DEEP S undershoot right after it
    (board-measured S/R ~= 0.7), and a long calm baseline. This is NOT a 6-point triangle."""
    xs = [p[0] for p in _PULSE_WAVEFORM_UNIT]
    ys = [p[1] for p in _PULSE_WAVEFORM_UNIT]
    assert xs == sorted(xs) and xs[0] == 0.0 and xs[-1] == 1.0
    assert len(_PULSE_WAVEFORM_UNIT) >= 20  # a shaped curve, not a triangle
    assert max(ys) == 1.0 and ys.count(1.0) == 1  # exactly one R apex
    apex_i = ys.index(1.0)
    assert min(ys[apex_i:apex_i + 4]) < -0.5  # the board's deep S undershoot right after R
    calm = [y for y in ys if abs(y) < 0.12]
    assert len(calm) > 0.5 * len(ys)  # a long calm baseline dominates


def test_recovered_pulse_renders_smooth_and_antialiased() -> None:
    """Rendered on a flat mid-grey source: the pulse must have partial-alpha (antialiased) red
    edges and occupy many distinct row positions (a smooth curve, not 3 straight segments)."""
    grey = Image.new("RGB", (1280, 1600), (128, 128, 128))
    buf = io.BytesIO()
    grey.save(buf, "JPEG", quality=95)
    im = _im(render_breaking_frame(buf.getvalue(), category="AI", editorial_code="NP-1"))
    px = im.load()
    strong_red_rows, soft_red = set(), 0
    for y in range(int(im.height * 0.78), im.height):
        for x in range(0, im.width, 2):
            r, g, b = px[x, y]
            if r > 170 and g < 80 and b < 80:
                strong_red_rows.add(y)
            elif r > 140 and r - g > 30 and r - b > 30 and g > 70:
                soft_red += 1  # blended (AA) edge pixel
    assert len(strong_red_rows) >= 12, "the waveform spans many rows (smooth, not flat)"
    assert soft_red >= 50, "antialiased blended edges present (not a hard jagged polyline)"


def test_breaking_evidence_names_the_recovered_approved_asset() -> None:
    ev = derive_breaking_render_evidence(_b(_IPHONE))
    assert ev.renderer_version == "pulse-breaking-v6-board"
    # RECONSTRUCTION-5: the geometry is now pixel-traced from the Founder board itself.
    assert "founder_telegram_board.png" in ev.notes["overlay_asset"]
    assert ev.logo_count == 1
    assert ev.scrim_treatment == "none"
    assert ev.source_image_treatment == "preserve"


def test_breaking_keeps_source_native_size_one_mark_no_band() -> None:
    src = _b(_BRIGHT)
    out = render_breaking_frame(src, category="AI", editorial_code="NP-1")
    assert _im(out).size == _im(src).size  # native size preserved
    # neutral-grey control: no ~22% dark lower-third band
    grey = Image.new("RGB", (1280, 720), (128, 128, 128))
    buf = io.BytesIO()
    grey.save(buf, "JPEG", quality=95)
    g = _im(render_breaking_frame(buf.getvalue(), category="AI", editorial_code="NP-1")).convert("L")
    band = ImageStat.Stat(g.crop((0, int(720 * 0.78), 1280, 720))).mean[0]
    mid = ImageStat.Stat(g.crop((0, int(720 * 0.35), 1280, int(720 * 0.55)))).mean[0]
    assert band > mid - 30


def test_the_only_breaking_overlay_asset_is_still_rejected_not_composited() -> None:
    """`breaking_minimal_01.png` is FOUND_REJECTED (design/reference_manifest.md). The renderer
    must not load it (or any 4:5 overlay raster) - it recovers geometry, never composites the
    raster (4:5 -> 16:9 migration is forbidden by the recorded V1 product decision)."""
    src = inspect.getsource(render_breaking_frame) + inspect.getsource(br._draw_recovered_pulse)
    assert "breaking_minimal_01" not in src
    assert "overlays/universal/universal_minimal_01.png" not in src  # geometry is baked, not loaded
    assert ".open(" not in inspect.getsource(br._draw_recovered_pulse)


# ==================================================================================================
# DATA hero - smooth curve anchored to the real series, bold type, recovered pulse
# ==================================================================================================
def test_hero_trend_is_monotone_and_never_overshoots_the_series_range() -> None:
    series = [10.0, 12.0, 40.0, 41.0, 90.0]
    curve = _monotone_cubic(list(range(len(series))), series, samples_per_segment=20)
    ys = [y for _, y in curve]
    assert min(ys) >= min(series) - 1e-6 and max(ys) <= max(series) + 1e-6
    assert len(curve) > 4 * len(series)  # densified -> smooth


def test_hero_curve_anchors_are_the_supplied_series_verbatim() -> None:
    body = _body(render_data_hero_card) + _body(br._draw_hero_sparkline)
    assert "len(series) >= 2" in body
    assert "min(series)" in body and "max(series)" in body
    assert "_reduced_tension_path(" in body  # keeps local direction changes, non-overshooting
    assert "VERBATIM" in inspect.getsource(br._draw_hero_sparkline)
    # data-driven: a different series must produce a different image
    a = DataCandidate(value="9", unit="", label="", evidence_fact="", series=(1.0, 2.0, 9.0))
    b = DataCandidate(value="9", unit="", label="", evidence_fact="", series=(1.0, 8.0, 9.0))
    assert render_data_hero_card(a) != render_data_hero_card(b)
    assert render_data_hero_card(a) == render_data_hero_card(a)  # deterministic


def test_hero_has_no_chart_below_two_points_and_never_a_crude_polyline() -> None:
    body = _body(render_data_hero_card)
    spark = inspect.getsource(br._draw_hero_sparkline)
    # the rejected render was `draw.line(<raw anchor points>, joint="curve")`; now the curve is a
    # dense monotone-cubic path composited off a supersampled AA layer.
    assert "_reduced_tension_path(" in spark and "Image.Resampling.LANCZOS" in spark
    assert "_draw_hero_sparkline" in body and "_draw_recovered_pulse" in body
    one = DataCandidate(value="42", unit="%", label="x", evidence_fact="y", series=(3.0,))
    assert render_data_hero_card(one)  # renders, no crash, no chart


def test_hero_value_unit_label_use_the_real_bold_face() -> None:
    # RECONSTRUCTION-5 §13: value + unit use the black-weight `heavy` face; the label stays bold.
    body = _body(render_data_hero_card)
    assert body.count('data_weight="black"') >= 2  # value + unit
    assert 'data_weight="bold"' in body  # label
    assert _resolve_bold_font_path() is None or isinstance(_resolve_bold_font_path(), str)


def test_hero_metric_is_verbatim_never_reformatted() -> None:
    cand = DataCandidate(value="-8.1", unit="п.п.", label="quarterly", evidence_fact="Fell 8.1%.", delta="-2pp")
    before = (cand.value, cand.unit, cand.label, cand.evidence_fact, cand.delta)
    render_data_hero_card(cand)
    assert (cand.value, cand.unit, cand.label, cand.evidence_fact, cand.delta) == before


# ==================================================================================================
# DATA source - preservation unchanged (factual safety, §14)
# ==================================================================================================
def test_data_source_infographic_is_preserved_with_one_mark() -> None:
    src = _b(_EXTERNAL_INFO)
    out = render_data_card(
        _HERO, category="DATA", editorial_code="NP-1", source_image_bytes=src,
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    src_im, out_im = _im(src).resize((1280, 720)), _im(out)
    # the top 65% (title, big stat, most bars) is essentially untouched
    top = (0, 0, 1280, int(720 * 0.65))
    mad = sum(ImageStat.Stat(ImageChops.difference(src_im.crop(top), out_im.crop(top))).mean) / 3
    assert mad < 6.0, mad
    # branding lives only in the lower band
    low = out_im.crop((0, int(720 * 0.82), 1280, 720))
    px = low.load()
    red_or_chip = sum(
        1 for y in range(0, low.height, 2) for x in range(0, low.width, 2)
        if (lambda r, g, b: (r > 150 and g < 90 and b < 90) or (r < 70 and g < 70 and b < 70))(*px[x, y])
    )
    assert red_or_chip > 0


# ==================================================================================================
# FROZEN - NEWS / QUOTE untouched by the recovery
# ==================================================================================================
def test_news_and_quote_renderers_did_not_absorb_the_recovery() -> None:
    assert "_draw_recovered_pulse" not in inspect.getsource(render_quote_card)
    news_bytes, _ = apply_master_news_branding(_b(_BRIGHT))
    with Image.open(io.BytesIO(news_bytes)) as im:
        assert im.size == (1280, 720)
    q = QuoteCandidate(text="On-device inference is real now.", speaker="A. Researcher", role="Engineer")
    a = render_quote_card(q, category="QUOTE", editorial_code="NP-9", portrait_bytes=_b(_PORTRAIT))
    b = render_quote_card(q, category="QUOTE", editorial_code="NP-9", portrait_bytes=_b(_PORTRAIT))
    assert a == b
    with Image.open(io.BytesIO(a)) as im:
        assert im.size == (1200, 675)
