"""FOUNDER-VISUAL-BOARD-REBUILD-6 / FINAL-BOARD-MATCH-7 focused tests.

BREAKING + GENERATED DATA are built from pixel measurements of docs/founder_telegram_board.png
(services/nnj_board_metrics.py) and use a PROJECT-BUNDLED font (assets/brand/fonts/, SIL OFL) so
Windows and production Linux render identically.

  * BREAKING  - board-measured pulse (long calm baseline + compact P-QRS-T + long calm tail,
    baseline hugging the lower media edge) + a RESTRAINED grey NNJ watermark (low opacity,
    background-level). No bright CTA mark, no dark band, no baked headline, <= 1 NNJ.
  * DATA generated - bundled Fira Sans Condensed with SEPARATED weights (Black value/unit,
    SemiBold label, Medium secondary); grid limited to the graph zone; the real series points are
    the ONLY anchors, connected DIRECTLY (clean segmented line, no synthetic points); very subtle
    fill; small endpoint; restrained mark.
  * DATA source - source fidelity first: no pulse / frame / grid / bg by default; at most one
    small adaptive watermark if a bounded safe corner exists, else BRAND SUPPRESSION.
  * NEWS / QUOTE / QUOTE_NO_ROLE - frozen.
"""

from __future__ import annotations

import inspect
import io
import platform

from PIL import Image, ImageChops, ImageDraw, ImageStat

from services import brand_renderer as br
from services import nnj_board_metrics as bm
from services.brand_renderer import (
    _PULSE_WAVEFORM_UNIT,
    _guarded_grid_color,
    _luma,
    _segmented_anchor_path,
    data_font_path,
    render_breaking_frame,
    render_data_card,
    render_data_hero_card,
    render_quote_card,
)
from services.data_source_classification import DataPresentationMode
from services.nnj_master_news_overlay import apply_master_news_branding
from services.presentation_director import DataCandidate, QuoteCandidate
from services.render_evidence import derive_breaking_render_evidence, derive_data_render_evidence

_IPHONE = "assets/brand/newsroom_visuals/v2_1_bakeoff_sources/case1_hero_product_iphone.jpg"
_BRIGHT = "assets/brand/newsroom_visuals/v2_1_bakeoff_sources/case3_bright_promotional_scene.jpg"
_PORTRAIT = "tests/fixtures/portrait_public_figure.jpg"
_HERO = DataCandidate(
    value="500", unit="mln", label="polzovateley", evidence_fact="Reached ChatGPT in July 2025",
    series=(120.0, 150.0, 190.0, 250.0, 330.0, 420.0, 500.0), delta="+38%",
)


def _b(p: str) -> bytes:
    with open(p, "rb") as fh:
        return fh.read()


def _im(d: bytes) -> Image.Image:
    return Image.open(io.BytesIO(d)).convert("RGB")


def _body(fn) -> str:
    parts = inspect.getsource(fn).split('"""')
    return parts[2] if len(parts) >= 3 else parts[0]


def _mad(a: Image.Image, b: Image.Image, box=None) -> float:
    if box is not None:
        a, b = a.crop(box), b.crop(box)
    return sum(ImageStat.Stat(ImageChops.difference(a.convert("RGB"), b.convert("RGB"))).mean) / 3.0


def _grey_src(w: int, h: int, c: int = 128) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (c, c, c)).save(buf, "JPEG", quality=95)
    return buf.getvalue()


# ==================================================================================================
# BREAKING
# ==================================================================================================
def test_breaking_waveform_proportions_come_from_the_board_metrics() -> None:
    xs = [p[0] for p in _PULSE_WAVEFORM_UNIT]
    ys = [p[1] for p in _PULSE_WAVEFORM_UNIT]
    assert xs == sorted(xs) and xs[0] == 0.0 and xs[-1] == 1.0
    apex_i = ys.index(1.0)
    # a deep S undershoot right after R (board S/R ~= 0.72)
    assert min(ys[apex_i:apex_i + 4]) <= -0.6
    # a long calm baseline before the complex and a long calm tail after
    assert all(abs(y) < 0.04 for x, y in _PULSE_WAVEFORM_UNIT if x <= 0.20)
    assert all(abs(y) < 0.04 for x, y in _PULSE_WAVEFORM_UNIT if x >= 0.62)
    # the renderer feeds the board-measured fractions, not magic numbers
    assert br._BREAKING_PULSE_WIDTH_FRAC == bm.BREAKING.pulse_width_frac
    assert br._BREAKING_PULSE_AMP_FRAC == bm.BREAKING.pulse_r_amp_frac_of_width
    assert br._BREAKING_PULSE_Y_FRAC == bm.BREAKING.pulse_baseline_frac


def test_breaking_pulse_is_lower_media_left_anchored_hugging_the_edge_no_band() -> None:
    out = _im(render_breaking_frame(_grey_src(1280, 900), category="AI", editorial_code="B1"))
    px = out.load()
    w, h = out.size

    def red(x0, x1, y0, y1):
        return sum(1 for y in range(y0, y1, 2) for x in range(x0, x1, 2)
                   if (lambda r, g, b: r > 150 and g < 90 and b < 90)(*px[x, y]))

    assert red(0, w // 2, int(h * 0.85), h) > 0                                   # present, lower-left
    assert red(0, w // 2, int(h * 0.85), h) > red(w // 2, w, int(h * 0.85), h)    # LEFT-anchored
    assert red(0, w, 0, int(h * 0.35)) == 0                                        # nothing up top
    # the pulse sits near the media bottom edge (baseline ~0.965 h), not floating mid-lower
    assert red(0, w // 2, int(h * 0.92), h) > red(0, w // 2, int(h * 0.80), int(h * 0.88))
    g = out.convert("L")
    band = ImageStat.Stat(g.crop((0, int(h * 0.78), w, h))).mean[0]
    mid = ImageStat.Stat(g.crop((0, int(h * 0.35), w, int(h * 0.55)))).mean[0]
    assert band > mid - 30                                                         # no dark band


def test_breaking_watermark_is_restrained_grey_not_a_cta() -> None:
    src = inspect.getsource(br._draw_breaking_watermark)
    assert "red=False" in src                       # canonical geometry tinted grey - never red
    assert "watermark_opacity" in src and "watermark_grey_on" in src
    assert bm.BREAKING.watermark_opacity <= 0.16    # FINAL-BOARD-MATCH-7: halved vs V6, background-level
    # pixel: on a mid-grey photo the lower-right barely changes - a quiet watermark, never opaque
    out = _im(render_breaking_frame(_grey_src(1200, 900), category="AI", editorial_code="B1"))
    got_region = ImageStat.Stat(out.crop((820, 640, 1180, 880))).mean
    assert all(abs(c - 128) < 26 for c in got_region), got_region


def test_breaking_bakes_no_headline_and_at_most_one_nnj() -> None:
    body = _body(render_breaking_frame)
    assert '"BREAKING"' not in body and "_draw_code_label(" not in body
    assert body.count("_draw_breaking_watermark(") >= 1
    assert "rasterize_nnj_mark(" not in body        # only the watermark helper composites a mark
    ev = derive_breaking_render_evidence(_b(_BRIGHT))
    assert ev.renderer_version == "pulse-breaking-v6-board"
    assert ev.logo_count == 1
    assert ev.scrim_treatment == "none" and ev.source_image_treatment == "preserve"
    assert "watermark" in ev.notes


# ==================================================================================================
# DATA generated
# ==================================================================================================
def test_data_font_is_project_bundled_and_platform_independent() -> None:
    for weight in ("black", "semibold", "medium", "bold", "regular"):
        p = data_font_path(weight)
        assert p.exists() and p.suffix == ".ttf"
        assert "assets" in p.parts and "brand" in p.parts and "fonts" in p.parts
        assert "Windows" not in str(p) and "/usr/share" not in str(p).replace("\\", "/")
    assert data_font_path("black").name == "FiraSansCondensed-Black.ttf"
    _ = platform.system()  # documented: resolution does not branch on the OS


def test_data_hero_typography_weights_are_separated() -> None:
    body = _body(render_data_hero_card)
    assert body.count('data_weight="black"') >= 2          # value + unit
    assert 'data_weight="semibold"' in body                # label (not Bold)
    assert 'data_weight="medium"' in body                  # secondary (not Regular)
    assert "unit_over_value" in body and "label_over_value" in body and "desc_over_value" in body
    assert render_data_hero_card(_HERO) == render_data_hero_card(_HERO)  # deterministic
    # the board hierarchy: label is much smaller than the value (V6's 0.28 was too heavy)
    assert bm.DATA.label_over_value <= 0.22
    assert bm.DATA.unit_over_value < 1.0


def test_data_hero_grid_is_limited_to_the_graph_zone_and_near_invisible() -> None:
    delta = _luma(_guarded_grid_color()) - _luma(br._HERO_BG)
    assert bm.DATA.grid_luma_delta_min <= delta <= bm.DATA.grid_luma_delta_max
    src = inspect.getsource(br._draw_hero_grid)
    assert "graph_x_start_frac" in src and "zone_x" in src   # grid is zoned, not full-canvas
    out = _im(render_data_hero_card(_HERO))
    # the LEFT text zone (well left of the graph) is essentially the pure background
    left = ImageStat.Stat(out.crop((90, 40, 380, 110))).mean
    assert max(left) < 16, left


def test_data_hero_graph_is_a_clean_segmented_line_no_synthetic_points() -> None:
    series = [8.0, 41.0, 40.0, 44.0, 96.0]  # a local dip must stay visible, not be splined away
    xs = list(map(float, range(len(series))))
    path = _segmented_anchor_path(xs, list(series))
    assert path == list(zip(xs, series))  # EXACTLY the anchors, nothing else
    spark = inspect.getsource(br._draw_hero_sparkline)
    assert "_segmented_anchor_path(" in spark and "VERBATIM" in spark
    assert "_monotone_cubic(" not in spark and "_reduced_tension_path(" not in spark  # no spline
    assert "len(series) >= 2" in _body(render_data_hero_card)
    a = DataCandidate(value="9", unit="", label="", evidence_fact="", series=(1.0, 2.0, 9.0))
    c = DataCandidate(value="9", unit="", label="", evidence_fact="", series=(1.0, 8.0, 9.0))
    assert render_data_hero_card(a) != render_data_hero_card(c)                     # data-driven


def test_data_hero_fill_is_very_subtle_and_endpoint_is_small() -> None:
    assert bm.DATA.graph_fill_peak_alpha <= 40      # FINAL-BOARD-MATCH-7: halved
    assert bm.DATA.graph_fill_band_frac <= 0.30
    assert bm.DATA.graph_endpoint_radius_frac <= 0.008
    out = _im(render_data_hero_card(_HERO))
    # most of the graph area stays dark - no red mass well below the line
    deep = ImageStat.Stat(out.crop((700, 560, 980, 660))).mean
    assert deep[0] < 34, deep


def test_data_hero_mark_is_restrained_and_at_most_one() -> None:
    body = _body(render_data_hero_card)
    assert body.count("rasterize_nnj_mark(") == 1
    assert "_HERO_MARK_OPACITY" in body
    assert bm.DATA.mark_opacity <= 0.40            # must not compete with the graph endpoint
    ev = derive_data_render_evidence(b"", _HERO, presentation_mode=DataPresentationMode.FULL_DATA_CARD)
    assert ev.logo_count == 1
    assert ev.renderer_version == "pulse-data-hero-v3-board"
    assert "Fira Sans Condensed" in ev.notes["typography"]


# ==================================================================================================
# DATA source  (frozen architecture: source fidelity first)
# ==================================================================================================
def _infographic(dark: bool, occupied: bool = False) -> bytes:
    bg = (16, 18, 22) if dark else (247, 248, 250)
    ink = (236, 238, 242) if dark else (20, 32, 60)
    im = Image.new("RGB", (1600, 900), bg)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 1600, 90), fill=(30, 34, 42) if dark else (20, 32, 60))
    for i, v in enumerate((18, 29, 41, 55, 68)):
        x = 150 + i * 220
        d.rectangle((x, 760 - v * 9, x + 150, 760), fill=ink if i < 4 else (232, 92, 60))
        d.text((x, 760 - v * 9 - 34), f"{v}%", fill=ink)
    d.text((40, 840), "Source: Regional Transport Agency, Jan 2026",
           fill=(150, 154, 162) if dark else (90, 96, 108))
    if occupied:
        for cx, cy in ((60, 120), (1490, 120), (60, 830), (1470, 830)):
            d.text((cx, cy), "chartsource.io", fill=(120, 126, 138))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _render_src(data: bytes) -> Image.Image:
    return _im(render_data_card(
        _HERO, category="D", editorial_code="1", source_image_bytes=data,
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    ))


def test_data_source_has_no_pulse_no_frame_no_grid_by_default() -> None:
    body = _body(render_data_card)
    assert "_place_source_watermark(canvas)" in body
    assert body.index("_place_source_watermark(canvas)") < body.index("_select_data_signature(")
    src = inspect.getsource(br._place_source_watermark)
    assert "_draw_recovered_pulse" not in src and "_build_data_lower_signature_image" not in src
    assert "rounded_rectangle" not in src   # no frame / plate / badge


def test_data_source_light_and_dark_preserved() -> None:
    from services.nnj_master_news_overlay import _CANVAS_H, _CANVAS_W, _fit_photo_to_canvas
    for dark in (False, True):
        src = _infographic(dark=dark)
        got = _render_src(src)
        fitted = _fit_photo_to_canvas(
            Image.open(io.BytesIO(src)).convert("RGBA"), (_CANVAS_W, _CANVAS_H)
        ).convert("RGB")
        assert _mad(fitted, got, box=(0, 0, 1120, 720)) < 1.6
        assert got.size == (1280, 720)


def test_data_source_suppresses_when_no_safe_corner() -> None:
    import random
    random.seed(3)
    im = Image.new("RGB", (1600, 900), (240, 240, 240))
    d = ImageDraw.Draw(im)
    for _ in range(6000):
        x, y = random.randint(0, 1599), random.randint(0, 899)
        d.rectangle((x, y, x + 9, y + 9),
                    fill=(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    from services.nnj_master_news_overlay import _CANVAS_H, _CANVAS_W, _fit_photo_to_canvas

    canvas = _fit_photo_to_canvas(
        Image.open(io.BytesIO(buf.getvalue())).convert("RGBA"), (_CANVAS_W, _CANVAS_H)
    )
    before = canvas.copy()
    assert br._place_source_watermark(canvas) is False
    assert _mad(before, canvas) == 0.0
    assert _render_src(buf.getvalue()).size == (1280, 720)


def test_data_source_third_party_mark_is_untouched() -> None:
    from services.nnj_master_news_overlay import _CANVAS_H, _CANVAS_W, _fit_photo_to_canvas

    src = _infographic(dark=False, occupied=True)
    got = _render_src(src)
    fitted = _fit_photo_to_canvas(
        Image.open(io.BytesIO(src)).convert("RGBA"), (_CANVAS_W, _CANVAS_H)
    ).convert("RGB")
    assert _mad(fitted, got) < 1.6   # every corner occupied -> suppression, publisher marks intact


# ==================================================================================================
# FROZEN
# ==================================================================================================
def test_news_quote_quote_no_role_unchanged() -> None:
    assert "_draw_breaking_watermark" not in inspect.getsource(render_quote_card)
    assert "_data_font" not in inspect.getsource(render_quote_card)
    news, _ = apply_master_news_branding(_b(_BRIGHT))
    with Image.open(io.BytesIO(news)) as im:
        assert im.size == (1280, 720)
    for q in (
        QuoteCandidate(text="On-device inference is real.", speaker="A. Researcher", role="Engineer"),
        QuoteCandidate(text="On-device inference is real.", speaker="A. Researcher"),
    ):
        a = render_quote_card(q, category="QUOTE", editorial_code="NP-9", portrait_bytes=_b(_PORTRAIT))
        b = render_quote_card(q, category="QUOTE", editorial_code="NP-9", portrait_bytes=_b(_PORTRAIT))
        assert a == b
        with Image.open(io.BytesIO(a)) as im:
            assert im.size == (1200, 675)
