"""FOUNDER-VISUAL-BOARD-REBUILD-6 focused tests (docs/founder_visual_board_rebuild_6_report.md).

The Founder rejected V5. This phase rebuilds BREAKING + DATA directly from pixel measurements of
`docs/founder_telegram_board.png` (services/nnj_board_metrics.py) and introduces a PROJECT-BUNDLED
font (assets/brand/fonts/, SIL OFL) so Windows and production Linux render identically.

  * BREAKING - board-measured pulse + a restrained LARGE grey NNJ watermark (adaptive, low
    opacity); no bright CTA mark, no dark band, no baked headline, <= 1 NNJ.
  * DATA generated - bundled Fira Sans Condensed; board typographic hierarchy; contrast-guarded
    near-invisible grid; the real series points are the only anchors; non-overshooting path;
    restrained under-curve tint; small endpoint dot; <= 1 NNJ.
  * DATA source - source fidelity first: NO pulse / frame / grid / bg by default; AT MOST one
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
    _reduced_tension_path,
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
    value="500", unit="млн", label="пользователей", evidence_fact="Достиг ChatGPT в июле 2025 года",
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
    # board: R apex at x ~= 0.341 of the drawn span (measured)
    assert abs(xs[apex_i] - bm.BREAKING.pulse_apex_at_frac) < 0.03
    # board: deep S undershoot right after R (S/R ~= 0.70)
    assert min(ys[apex_i:apex_i + 4]) <= -0.6
    # a long calm tail
    assert all(abs(y) < 0.05 for x, y in _PULSE_WAVEFORM_UNIT if x >= 0.8)
    # the renderer feeds the board-measured fractions, not magic numbers
    assert br._BREAKING_PULSE_WIDTH_FRAC == bm.BREAKING.pulse_width_frac
    assert br._BREAKING_PULSE_AMP_FRAC == bm.BREAKING.pulse_r_amp_frac_of_width


def test_breaking_pulse_is_lower_media_left_anchored_no_band() -> None:
    out = _im(render_breaking_frame(_grey_src(1280, 900), category="AI", editorial_code="B1"))
    px = out.load()
    w, h = out.size

    def red(x0, x1, y0, y1):
        return sum(1 for y in range(y0, y1, 2) for x in range(x0, x1, 2)
                   if (lambda r, g, b: r > 150 and g < 90 and b < 90)(*px[x, y]))

    assert red(0, w // 2, int(h * 0.82), h) > 0                                  # present, lower-left
    assert red(0, w // 2, int(h * 0.82), h) > red(w // 2, w, int(h * 0.82), h)   # LEFT-anchored
    assert red(0, w, 0, int(h * 0.35)) == 0                                       # nothing up top
    g = out.convert("L")
    band = ImageStat.Stat(g.crop((0, int(h * 0.78), w, h))).mean[0]
    mid = ImageStat.Stat(g.crop((0, int(h * 0.35), w, int(h * 0.55)))).mean[0]
    assert band > mid - 30                                                        # no dark band


def test_breaking_watermark_is_large_restrained_grey_not_a_cta() -> None:
    src = inspect.getsource(br._draw_breaking_watermark)
    assert "red=False" in src                      # the canonical geometry, tinted grey - never red
    assert "watermark_opacity" in src and "watermark_grey_on" in src
    assert bm.BREAKING.watermark_width_frac >= 0.35     # LARGE, not a corner mark
    assert bm.BREAKING.watermark_opacity <= 0.30        # low opacity
    # pixel: on a mid-grey photo the lower-right stays close to the source (a quiet watermark,
    # never a bright/opaque logo)
    out = _im(render_breaking_frame(_grey_src(1200, 900), category="AI", editorial_code="B1"))
    br_region = ImageStat.Stat(out.crop((820, 640, 1180, 880))).mean
    assert all(abs(c - 128) < 60 for c in br_region), br_region


def test_breaking_bakes_no_headline_and_at_most_one_nnj() -> None:
    body = _body(render_breaking_frame)
    assert '"BREAKING"' not in body and "_draw_code_label(" not in body
    assert "_draw_breaking_watermark(" in body
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
    for weight in ("black", "bold", "semibold", "regular"):
        p = data_font_path(weight)
        assert p.exists() and p.suffix == ".ttf"
        assert "assets" in p.parts and "brand" in p.parts and "fonts" in p.parts  # in the repo
        assert "Windows" not in str(p) and "/usr/share" not in str(p).replace("\\", "/")
    # WINDOWS_RENDER_FONT == LINUX_RENDER_FONT: the path is the same relative asset on both
    rel = data_font_path("black")
    assert rel.name == "FiraSansCondensed-Black.ttf"
    _ = platform.system()  # (documented: resolution does not branch on the OS)


def test_data_hero_typography_hierarchy_is_board_derived() -> None:
    body = _body(render_data_hero_card)
    assert body.count('data_weight="black"') >= 2          # value + unit
    assert 'data_weight="bold"' in body                    # label
    assert 'data_weight="regular"' in body                 # secondary
    assert "unit_over_value" in body and "label_over_value" in body  # sized by board ratios
    assert render_data_hero_card(_HERO) == render_data_hero_card(_HERO)  # deterministic


def test_data_hero_grid_is_contrast_guarded_near_invisible() -> None:
    delta = _luma(_guarded_grid_color()) - _luma(br._HERO_BG)
    assert bm.DATA.grid_luma_delta_min <= delta <= bm.DATA.grid_luma_delta_max
    assert delta <= 12  # §13: reads as texture, not squares
    out = _im(render_data_hero_card(_HERO))
    # a quiet cell away from text/chart is essentially the background
    patch = ImageStat.Stat(out.crop((470, 40, 560, 300))).mean
    assert max(patch) < 20, patch


def test_data_hero_graph_keeps_real_anchors_and_never_overshoots() -> None:
    series = [8.0, 41.0, 40.0, 44.0, 96.0]  # a local dip the path must not iron flat into an arc
    path = _reduced_tension_path(list(range(len(series))), series)
    ys = [y for _, y in path]
    assert min(ys) >= min(series) - 1e-6 and max(ys) <= max(series) + 1e-6   # no overshoot
    # the real anchors are hit
    for i, v in enumerate(series):
        assert any(abs(px - i) < 1e-6 and abs(py - v) < 1e-6 for px, py in path)
    spark = inspect.getsource(br._draw_hero_sparkline)
    assert "_reduced_tension_path(" in spark and "VERBATIM" in spark
    assert "len(series) >= 2" in _body(render_data_hero_card)
    # data-driven
    a = DataCandidate(value="9", unit="", label="", evidence_fact="", series=(1.0, 2.0, 9.0))
    c = DataCandidate(value="9", unit="", label="", evidence_fact="", series=(1.0, 8.0, 9.0))
    assert render_data_hero_card(a) != render_data_hero_card(c)


def test_data_hero_fill_is_restrained_and_endpoint_is_small() -> None:
    assert bm.DATA.graph_fill_peak_alpha <= 90
    assert bm.DATA.graph_endpoint_radius_frac <= 0.008     # small crisp dot
    out = _im(render_data_hero_card(_HERO))
    # majority of the chart area is near-black: deep below the curve there is no red wedge
    deep = ImageStat.Stat(out.crop((640, 590, 900, 700))).mean
    assert deep[0] < 40, deep


def test_data_hero_has_at_most_one_nnj_restrained() -> None:
    body = _body(render_data_hero_card)
    assert body.count("rasterize_nnj_mark(") == 1
    assert "_HERO_MARK_OPACITY" in body                    # lowered opacity, not a CTA badge
    ev = derive_data_render_evidence(b"", _HERO, presentation_mode=DataPresentationMode.FULL_DATA_CARD)
    assert ev.logo_count == 1
    assert ev.renderer_version == "pulse-data-hero-v3-board"
    assert "Fira Sans Condensed" in ev.notes["typography"]


# ==================================================================================================
# DATA source  (§16-§18 architecture: source fidelity first)
# ==================================================================================================
def _infographic(dark: bool, watermark: bool = False) -> bytes:
    bg = (16, 18, 22) if dark else (247, 248, 250)
    ink = (236, 238, 242) if dark else (20, 32, 60)
    im = Image.new("RGB", (1600, 900), bg)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 1600, 90), fill=(30, 34, 42) if dark else (20, 32, 60))
    for i, v in enumerate((18, 29, 41, 55, 68)):
        x = 150 + i * 220
        d.rectangle((x, 760 - v * 9, x + 150, 760), fill=ink if i < 4 else (232, 92, 60))
        d.text((x, 760 - v * 9 - 34), f"{v}%", fill=ink)
    d.text((40, 840), "Source: Regional Transport Agency, Jan 2026", fill=(150, 154, 162) if dark else (90, 96, 108))
    if watermark:
        d.text((1400, 840), "chartsource.io", fill=(120, 126, 138))
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
    # the MINIMAL branch returns before any signature / stat-block work
    assert "_place_source_watermark(canvas)" in body
    assert body.index("_place_source_watermark(canvas)") < body.index("_select_data_signature(")
    src = inspect.getsource(br._place_source_watermark)
    assert "_draw_recovered_pulse" not in src and "_build_data_lower_signature_image" not in src
    assert "rounded_rectangle" not in src   # no frame / plate / badge


def test_data_source_light_preserved_with_one_small_watermark() -> None:
    src = _infographic(dark=False)
    got = _render_src(src)
    from services.nnj_master_news_overlay import _CANVAS_H, _CANVAS_W, _fit_photo_to_canvas
    fitted = _fit_photo_to_canvas(Image.open(io.BytesIO(src)).convert("RGBA"), (_CANVAS_W, _CANVAS_H)).convert("RGB")
    # all bars / numbers / attribution (everything except a small lower-right corner) untouched
    assert _mad(fitted, got, box=(0, 0, 1120, 720)) < 1.5
    assert _mad(fitted, got, box=(0, 620, 900, 720)) < 1.5      # source attribution intact


def test_data_source_dark_preserved_and_adaptive() -> None:
    src = _infographic(dark=True)
    got = _render_src(src)
    from services.nnj_master_news_overlay import _CANVAS_H, _CANVAS_W, _fit_photo_to_canvas
    fitted = _fit_photo_to_canvas(Image.open(io.BytesIO(src)).convert("RGBA"), (_CANVAS_W, _CANVAS_H)).convert("RGB")
    assert _mad(fitted, got, box=(0, 0, 1120, 720)) < 1.5
    assert got.size == (1280, 720)


def test_data_source_suppresses_when_no_safe_corner() -> None:
    import random
    random.seed(3)
    im = Image.new("RGB", (1600, 900), (240, 240, 240))
    d = ImageDraw.Draw(im)
    for _ in range(6000):
        x, y = random.randint(0, 1599), random.randint(0, 899)
        d.rectangle((x, y, x + 9, y + 9), fill=(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    from services.nnj_master_news_overlay import _CANVAS_H, _CANVAS_W, _fit_photo_to_canvas

    canvas = _fit_photo_to_canvas(
        Image.open(io.BytesIO(buf.getvalue())).convert("RGBA"), (_CANVAS_W, _CANVAS_H)
    )
    before = canvas.copy()
    placed = br._place_source_watermark(canvas)
    assert placed is False, "every corner is maximally busy -> BRAND SUPPRESSION"
    assert _mad(before, canvas) == 0.0, "the source canvas is not touched at all"
    # end to end: the render still succeeds and stays a 1280x720 image
    assert _render_src(buf.getvalue()).size == (1280, 720)


def test_data_source_third_party_watermark_is_untouched() -> None:
    src = _infographic(dark=False, watermark=True)
    got = _render_src(src)
    from services.nnj_master_news_overlay import _CANVAS_H, _CANVAS_W, _fit_photo_to_canvas
    fitted = _fit_photo_to_canvas(Image.open(io.BytesIO(src)).convert("RGBA"), (_CANVAS_W, _CANVAS_H)).convert("RGB")
    # the "chartsource.io" strip is byte-for-byte the source (the watermark went to another corner
    # or was suppressed - it never lands on a third-party mark)
    assert _mad(fitted, got, box=(1090, 655, 1240, 700)) < 0.8


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
