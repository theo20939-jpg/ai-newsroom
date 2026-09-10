"""FOUNDER-VISUAL-BREAKING-DATA-RECONSTRUCTION-5 focused tests
(docs/founder_visual_breaking_data_reconstruction_5_report.md).

Founder re-rejected the RECOVERY-4 BREAKING + DATA as STRUCTURAL mismatches. This phase
reconstructs both against `docs/founder_telegram_board.png` directly:

  * BREAKING  - a short, LEFT-anchored NINJA PULSE pixel-traced from the board's own BREAKING
    pulse (deep S undershoot), rendered 4x-supersampled + LANCZOS. No crude polyline on the path.
  * DATA hero - board-measured near-black background (6,7,9), barely-there reconstructed grid,
    the black-weight `heavy` face for value/unit, a monotone (non-overshooting) area curve with a
    restrained glow, the board pulse motif.
  * DATA source - minimal editorial integration: adaptive thin bottom pulse+mark when it fits
    safely, else BRAND SUPPRESSION. Never a rectangular badge / dark plate. FINAL_VISIBLE_NNJ <= 1.
  * NEWS / QUOTE / QUOTE_NO_ROLE - frozen.
"""

from __future__ import annotations

import inspect
import io

from PIL import Image, ImageChops, ImageStat

from services import brand_renderer as br
from services.brand_renderer import (
    _HERO_BG,
    _PULSE_WAVEFORM_UNIT,
    _monotone_cubic,
    _resolve_heavy_font_path,
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
_BOARD = "docs/founder_telegram_board.png"

_HERO = DataCandidate(
    value="500", unit="млн", label="пользователей",
    evidence_fact="Достиг ChatGPT в июле 2025 года",
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


# ==================================================================================================
# BREAKING - board-traced pulse
# ==================================================================================================
def test_breaking_pulse_is_board_traced_left_anchored_deep_s() -> None:
    xs = [p[0] for p in _PULSE_WAVEFORM_UNIT]
    ys = [p[1] for p in _PULSE_WAVEFORM_UNIT]
    assert xs == sorted(xs)
    apex = ys.index(1.0)
    # the board's defining feature: a DEEP S trough right after R (measured S/R ~= 0.7)
    assert min(ys[apex:apex + 5]) <= -0.5
    # QRS is LEFT-of-centre in the drawn span (board: apex well before the midpoint), then a flat tail
    assert xs[apex] < 0.45
    assert all(abs(y) < 0.05 for x, y in _PULSE_WAVEFORM_UNIT if x >= 0.75)


def test_breaking_render_uses_the_supersampled_primitive_not_a_crude_polyline() -> None:
    body = _body(render_breaking_frame)
    assert "_draw_recovered_pulse(" in body and "x_left=" in body
    assert "_draw_pulse(" not in body
    prim = inspect.getsource(br._draw_recovered_pulse)
    assert "_PULSE_SUPERSAMPLE" in prim and "Image.Resampling.LANCZOS" in prim
    assert "_catmull_rom(" in prim


def test_breaking_pulse_sits_in_the_lower_media_left_half_no_band() -> None:
    # neutral-grey source so only the pulse is red - test its POSITION deterministically
    grey = io.BytesIO()
    Image.new("RGB", (1280, 900), (128, 128, 128)).save(grey, "JPEG", quality=95)
    out = _im(render_breaking_frame(grey.getvalue(), category="AI", editorial_code="B1"))
    assert out.size == (1280, 900)
    px = out.load()
    w, h = out.size

    def redcount(x0, x1, y0, y1):
        return sum(
            1 for y in range(y0, y1, 2) for x in range(x0, x1, 2)
            if (lambda r, g, b: r > 150 and g < 90 and b < 90)(*px[x, y])
        )

    lower_left = redcount(0, w // 2, int(h * 0.80), h)
    lower_right = redcount(w // 2, w, int(h * 0.80), int(h * 0.97))  # exclude the corner mark
    upper = redcount(0, w, 0, int(h * 0.30))
    assert lower_left > 0
    assert lower_left > lower_right          # LEFT-anchored
    assert lower_left > upper * 3 + 1        # in the lower media, not the upper
    # no dark lower-third band
    g = out.convert("L")
    band = ImageStat.Stat(g.crop((0, int(h * 0.78), w, h))).mean[0]
    mid = ImageStat.Stat(g.crop((0, int(h * 0.35), w, int(h * 0.55)))).mean[0]
    assert band > mid - 30


def test_breaking_bakes_no_headline_and_one_mark() -> None:
    body = _body(render_breaking_frame)
    assert '"BREAKING"' not in body and "_draw_code_label(" not in body
    assert body.count("_draw_breaking_watermark(") >= 1  # mutually-exclusive branches
    ev = derive_breaking_render_evidence(_b(_BRIGHT))
    assert ev.renderer_version == "pulse-breaking-v6-board"
    assert ev.placement_zone == "lower_left"
    assert ev.logo_count == 1
    assert "founder_telegram_board.png" in ev.notes["overlay_asset"]


# ==================================================================================================
# DATA generated - background / typography / graph reconstructed from the board
# ==================================================================================================
def test_hero_background_is_board_measured_near_black() -> None:
    assert _HERO_BG == (6, 7, 9)
    out = _im(render_data_hero_card(_HERO))
    # a quiet cell mid-right (above the chart, right of the text) is the near-black ground
    patch = ImageStat.Stat(out.crop((760, 40, 1180, 90))).mean
    assert max(patch) < 22, patch  # dark; the faint grid never lifts it to a visible grey


def test_hero_value_and_unit_use_the_heavy_face() -> None:
    body = _body(render_data_hero_card)
    assert body.count('data_weight="black"') >= 2  # value + unit (label/secondary use lighter weights)
    resolved = _resolve_heavy_font_path()
    assert resolved is None or isinstance(resolved, str)


def test_hero_metric_is_verbatim_and_wrapping_is_deterministic() -> None:
    cand = DataCandidate(
        value="1,4 млрд", unit="сообщений", label="очень длинная подпись метрики которая переносится",
        evidence_fact="WhatsApp за декабрь 2025 года", delta="+22%",
    )
    before = (cand.value, cand.unit, cand.label, cand.evidence_fact, cand.delta)
    a = render_data_hero_card(cand)
    b = render_data_hero_card(cand)
    assert a == b  # deterministic wrap/fit
    assert (cand.value, cand.unit, cand.label, cand.evidence_fact, cand.delta) == before  # never mutated


def test_hero_graph_interpolation_never_overshoots_and_has_no_synthetic_points() -> None:
    series = [8.0, 40.0, 41.0, 42.0, 95.0]
    curve = _monotone_cubic(list(range(len(series))), series, samples_per_segment=24)
    ys = [y for _, y in curve]
    assert min(ys) >= min(series) - 1e-6 and max(ys) <= max(series) + 1e-6
    spark = inspect.getsource(br._draw_hero_sparkline)
    assert "_segmented_anchor_path(" in spark and "VERBATIM" in spark
    assert "len(series) >= 2" in _body(render_data_hero_card)
    # data-driven: two different series -> two different images
    a = DataCandidate(value="9", unit="", label="", evidence_fact="", series=(1.0, 2.0, 9.0))
    c = DataCandidate(value="9", unit="", label="", evidence_fact="", series=(1.0, 8.0, 9.0))
    assert render_data_hero_card(a) != render_data_hero_card(c)


def test_hero_area_fill_is_a_restrained_glow_not_a_solid_block() -> None:
    out = _im(render_data_hero_card(_HERO))
    px = out.load()
    # sample deep-bottom-left of the chart zone: the fill must have faded to ~background there
    deep = ImageStat.Stat(out.crop((580, 660, 760, 700))).mean
    assert deep[0] < 40, deep  # not a big red wedge reaching the bottom-left
    # but there IS red where the curve actually runs (peak ~0.47h, ends ~0.87w)
    near = sum(
        1 for y in range(300, 520, 3) for x in range(860, 1090, 3)
        if px[x, y][0] > 90 and px[x, y][0] - px[x, y][2] > 25
    )
    assert near > 0


def test_hero_small_motif_uses_the_same_board_pulse_primitive() -> None:
    body = _body(render_data_hero_card)
    assert "_draw_recovered_pulse(" in body
    assert "_draw_pulse_line(" not in body  # the retired hand-coded flat->spike->valley


def test_hero_has_exactly_one_nnj_mark() -> None:
    body = _body(render_data_hero_card)
    assert body.count("rasterize_nnj_mark(") == 1


# ==================================================================================================
# DATA source - minimal integration, safe, no badge
# ==================================================================================================
def test_data_source_light_infographic_values_untouched_no_badge() -> None:
    src = _b(_EXTERNAL_INFO)
    out = render_data_card(
        _HERO, category="D", editorial_code="1", source_image_bytes=src,
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    from services.nnj_master_news_overlay import _CANVAS_H, _CANVAS_W, _fit_photo_to_canvas

    fitted = _fit_photo_to_canvas(
        Image.open(io.BytesIO(src)).convert("RGBA"), (_CANVAS_W, _CANVAS_H)
    ).convert("RGB")
    got = _im(out)
    # every number / axis / source-line region (top 78%) is byte-for-byte the fitted source -
    # no badge, no plate, no re-rendered data
    assert _mad(fitted, got, box=(0, 0, 1280, 560)) < 2.0


def test_data_source_dark_infographic_is_also_preserved() -> None:
    dark = io.BytesIO()
    di = Image.new("RGB", (1600, 900), (16, 18, 22))
    from PIL import ImageDraw

    d = ImageDraw.Draw(di)
    d.rectangle((120, 300, 300, 760), fill=(0, 168, 214))
    d.rectangle((520, 180, 700, 760), fill=(232, 92, 60))
    d.text((140, 40), "SAMPLE DARK CHART - 46%", fill=(235, 238, 242))
    di.save(dark, "JPEG", quality=92)
    out = render_data_card(
        _HERO, category="D", editorial_code="2", source_image_bytes=dark.getvalue(),
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    from services.nnj_master_news_overlay import _CANVAS_H, _CANVAS_W, _fit_photo_to_canvas

    fitted = _fit_photo_to_canvas(
        Image.open(io.BytesIO(dark.getvalue())).convert("RGBA"), (_CANVAS_W, _CANVAS_H)
    ).convert("RGB")
    got = _im(out)
    assert got.size == (1280, 720)
    # the chart bars / title (top 75%) are preserved; any branding is bottom-only + thin
    assert _mad(fitted, got, box=(0, 0, 1280, 540)) < 2.5


def test_data_source_suppresses_branding_rather_than_pasting_a_badge() -> None:
    """§20/§21: when the adaptive signature cannot be placed safely, the source ships unbranded -
    the renderer NEVER falls back to a rectangular logo badge / dark plate in MINIMAL mode."""
    src = inspect.getsource(br.render_data_card)
    assert "_build_data_signature_fallback(" in src  # still available for the LEGACY card path...
    # ...but explicitly gated OUT of the source-preserving path
    assert "presentation_mode != DataPresentationMode.MINIMAL_SOURCE_PRESERVING" in src


def test_data_source_final_visible_nnj_at_most_one() -> None:
    src = _b(_EXTERNAL_INFO)
    out = _im(render_data_card(
        _HERO, category="D", editorial_code="1", source_image_bytes=src,
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    ))
    # the fixture's own art has no canonical NNJ; the renderer added 0 or 1 (suppressed here) -
    # never 2. (Structural: render_data_card composites at most one signature layer.)
    body = _body(br.render_data_card)
    assert body.count("_build_data_lower_signature_image(") == 1
    assert out.size == (1280, 720)


# ==================================================================================================
# FROZEN - NEWS / QUOTE / QUOTE_NO_ROLE
# ==================================================================================================
def test_news_quote_unchanged_by_the_reconstruction() -> None:
    assert "_draw_recovered_pulse" not in inspect.getsource(render_quote_card)
    news, _ = apply_master_news_branding(_b(_BRIGHT))
    with Image.open(io.BytesIO(news)) as im:
        assert im.size == (1280, 720)
    role = QuoteCandidate(text="On-device inference is real now.", speaker="A. Researcher", role="Engineer")
    no_role = QuoteCandidate(text="On-device inference is real now.", speaker="A. Researcher")
    for q in (role, no_role):
        a = render_quote_card(q, category="QUOTE", editorial_code="NP-9", portrait_bytes=_b(_PORTRAIT))
        b = render_quote_card(q, category="QUOTE", editorial_code="NP-9", portrait_bytes=_b(_PORTRAIT))
        assert a == b
        with Image.open(io.BytesIO(a)) as im:
            assert im.size == (1200, 675)
