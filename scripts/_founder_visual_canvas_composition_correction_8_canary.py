"""FOUNDER-VISUAL-CANVAS-COMPOSITION-CORRECTION-8 - local canary + focused review package.

Builds C:/Users/Theodor/Desktop/NINJA_PULSE_DATA_COMPOSITION_V8/ per phase section 28:

    00_DATA_REFERENCE_VS_V8.png     LEFT  = Founder DATA media crop, RIGHT = V8 DATA  (EXACT same px)
    01_BREAKING_REFERENCE_VS_V8.png TOP   = Founder BREAKING media,   BOTTOM = V8 BREAKING (EXACT same px)
    02_DATA_500_RU.png             real-Cyrillic canary 1 (500 / МЛН / ПОЛЬЗОВАТЕЛЕЙ ...)
    03_DATA_68_PERCENT_RU.png      real-Cyrillic canary 2 (68 / % / ЭЛЕКТРОМОБИЛЕЙ В НОВЫХ ПРОДАЖАХ ...)
    04_DATA_1_4_BILLION_RU.png     real-Cyrillic canary 3 (1,4 млрд / СООБЩЕНИЙ / В ДЕНЬ ...)
    05_BREAKING_DARK.png           BREAKING on a dark product photo
    06_BREAKING_LIGHT.png          BREAKING on a bright photo (watermark subordinate, no opacity bump)
    07_DATA_SOURCE_FROZEN.png      frozen MINIMAL_SOURCE_PRESERVING regression proof
    08_GEOMETRY_MEASUREMENTS.md    the measurement record (also written to docs/ + artifacts/)

NO production. NO image-generation model. NO font files copied into the package. Run from repo root:

    python scripts/_founder_visual_canvas_composition_correction_8_canary.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw  # noqa: E402

from services import nnj_board_metrics as _bm  # noqa: E402
from services.brand_renderer import (  # noqa: E402
    _font,
    render_breaking_frame,
    render_data_card,
    render_data_hero_card,
)
from services.data_source_classification import DataPresentationMode  # noqa: E402
from services.presentation_director import DataCandidate  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
ART = REPO / "artifacts" / "founder_visual_canvas_composition_correction_8"
DESKTOP = Path("C:/Users/Theodor/Desktop/NINJA_PULSE_DATA_COMPOSITION_V8")
BOARD = REPO / "docs" / "founder_telegram_board.png"
SRC = REPO / "assets" / "brand" / "newsroom_visuals" / "v2_1_bakeoff_sources"
FIXTURES = REPO / "tests" / "fixtures"

# Re-measured ACTUAL media rectangles (phase section 3 / section 19), Telegram chrome excluded.
DATA_CROP = (404, 105, 404 + 322, 105 + 295)      # 322 x 295  aspect ~1.09
BRK_CROP = (18, 747, 18 + 322, 747 + 165)          # 322 x 165  aspect ~1.95


def _im(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def _same_px_pair(board: Image.Image, v8: Image.Image, *, stack: str, tw: int) -> Image.Image:
    """Board crop and V8 render forced to the EXACT SAME pixel size, captioned, LEFT/RIGHT
    (stack='h') or TOP/BOTTOM (stack='v'). Aspect is preserved by matching the board crop's
    aspect - the V8 render already carries that aspect for DATA; for BREAKING the V8 media band
    is cropped to the board crop's aspect first."""
    ar = board.width / board.height
    th = max(1, round(tw / ar))
    bd = board.resize((tw, th), Image.LANCZOS)
    v8r = v8.resize((tw, th), Image.LANCZOS)
    cap, pad, gap = 40, 20, 16
    if stack == "h":
        out = Image.new("RGB", (tw * 2 + pad * 2 + gap, th + cap + pad), (8, 8, 10))
        d = ImageDraw.Draw(out)
        d.text((pad, 10), "FOUNDER BOARD - DATA media (exact same px)", font=_font(20, bold=True), fill=(150, 200, 150))
        d.text((pad + tw + gap, 10), "V8 GENERATED DATA (exact same px)", font=_font(20, bold=True), fill=(210, 160, 160))
        out.paste(bd, (pad, cap))
        out.paste(v8r, (pad + tw + gap, cap))
    else:
        out = Image.new("RGB", (tw + pad * 2, th * 2 + cap * 2 + pad + gap), (8, 8, 10))
        d = ImageDraw.Draw(out)
        d.text((pad, 10), "FOUNDER BOARD - BREAKING media (exact same px)", font=_font(20, bold=True), fill=(150, 200, 150))
        out.paste(bd, (pad, cap))
        d.text((pad, cap + th + gap), "V8 BREAKING - lower media band (exact same px)", font=_font(20, bold=True), fill=(210, 160, 160))
        out.paste(v8r, (pad, cap * 2 + th + gap))
    return out


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    DESKTOP.mkdir(parents=True, exist_ok=True)
    board = Image.open(BOARD).convert("RGB")

    # ---- re-extract the two reference crops (fixtures were both too tight) --------------------------
    board.crop(DATA_CROP).save(FIXTURES / "founder_data_media_crop.png")
    board.crop(BRK_CROP).save(FIXTURES / "founder_breaking_media_crop.png")
    board_data = board.crop(DATA_CROP)
    board_brk = board.crop(BRK_CROP)

    # ---- DATA: three REAL-CYRILLIC canaries, DENSE explicit fixtures (7-9 values) ------------------
    c500 = DataCandidate(
        value="500", unit="МЛН", label="ПОЛЬЗОВАТЕЛЕЙ",
        evidence_fact="Достиг ChatGPT в июле 2025 года",
        series=(118.0, 130.0, 127.0, 190.0, 242.0, 230.0, 331.0, 420.0, 500.0), delta="+38%")
    c68 = DataCandidate(
        value="68", unit="%", label="ЭЛЕКТРОМОБИЛЕЙ В НОВЫХ ПРОДАЖАХ",
        evidence_fact="Доля новых машин в регионе за 2025 год",
        series=(18.0, 22.0, 29.0, 27.0, 41.0, 44.0, 52.0, 55.0, 68.0), delta="+13 п.п.")
    c14 = DataCandidate(
        value="1,4 млрд", unit="СООБЩЕНИЙ", label="В ДЕНЬ",
        evidence_fact="WhatsApp, декабрь 2025",
        series=(0.82, 0.9, 1.05, 1.0, 1.12, 1.18, 1.28, 1.4), delta="+22%")
    hero500 = _im(render_data_hero_card(c500))
    hero68 = _im(render_data_hero_card(c68))
    hero14 = _im(render_data_hero_card(c14))

    # ---- BREAKING: dark + bright ------------------------------------------------------------------
    dark = (SRC / "case1_hero_product_iphone.jpg").read_bytes()
    light = (SRC / "case3_bright_promotional_scene.jpg").read_bytes()
    brk_dark = _im(render_breaking_frame(dark, category="AI", editorial_code="NP-B1"))
    brk_light = _im(render_breaking_frame(light, category="AI", editorial_code="NP-B2"))

    def _brk_band(v8: Image.Image) -> Image.Image:
        ar = board_brk.width / board_brk.height
        bh = round(v8.width / ar)
        return v8.crop((0, v8.height - bh, v8.width, v8.height))

    # ---- frozen DATA source regression proof ----------------------------------------------------
    lg = Image.new("RGB", (1600, 900), (247, 248, 250))
    dr = ImageDraw.Draw(lg)
    dr.rectangle((0, 0, 1600, 90), fill=(20, 32, 60))
    dr.text((40, 30), "GLOBAL EV ADOPTION 2025", font=_font(38, bold=True), fill=(255, 255, 255))
    for i, v in enumerate((18, 29, 41, 55, 68)):
        x = 150 + i * 220
        dr.rectangle((x, 760 - v * 9, x + 150, 760), fill=(20, 32, 60) if i < 4 else (232, 92, 60))
        dr.text((x, 760 - v * 9 - 40), f"{v}%", font=_font(30, bold=True), fill=(20, 32, 60))
    dr.text((40, 840), "Source: Regional Transport Agency, Jan 2026", font=_font(24), fill=(90, 96, 108))
    lb = io.BytesIO()
    lg.save(lb, "JPEG", quality=92)
    src_frozen = _im(render_data_card(
        c500, category="DATA", editorial_code="NP-1", source_image_bytes=lb.getvalue(),
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING))

    # ---- exact-same-pixel comparisons ----------------------------------------------------------
    cmp_data = _same_px_pair(board_data, hero500, stack="h", tw=560)
    cmp_brk = _same_px_pair(board_brk, _brk_band(brk_dark), stack="v", tw=980)

    outs = {
        "00_DATA_REFERENCE_VS_V8.png": cmp_data,
        "01_BREAKING_REFERENCE_VS_V8.png": cmp_brk,
        "02_DATA_500_RU.png": hero500,
        "03_DATA_68_PERCENT_RU.png": hero68,
        "04_DATA_1_4_BILLION_RU.png": hero14,
        "05_BREAKING_DARK.png": brk_dark,
        "06_BREAKING_LIGHT.png": brk_light,
        "07_DATA_SOURCE_FROZEN.png": src_frozen,
    }
    for name, img in outs.items():
        img.save(ART / name)
        img.save(DESKTOP / name)

    geom = _geometry_doc()
    for dst in (
        ART / "08_GEOMETRY_MEASUREMENTS.md",
        DESKTOP / "08_GEOMETRY_MEASUREMENTS.md",
        REPO / "docs" / "founder_visual_canvas_composition_correction_8_geometry.md",
    ):
        dst.write_bytes(geom.encode("utf-8"))  # LF-only (repo is LF; write_text would emit CRLF on Windows)

    print("wrote", len(outs) + 1, "files to", ART, "and", DESKTOP)


def _geometry_doc() -> str:
    b, dd = _bm.BREAKING, _bm.DATA
    return f"""# FOUNDER-VISUAL-CANVAS-COMPOSITION-CORRECTION-8 - geometry measurements

All numbers are DIRECT pixel measurements of `docs/founder_telegram_board.png` (1024 x 1280),
Telegram chrome / caption / reactions / buttons excluded. Nothing here assumes 16:9 or 4:3.

## 1. DATA media rectangle (section 2 / section 3)

| quantity | value |
|---|---|
| media x, y | 404, 105 |
| media w, h | {dd.media_w} x {dd.media_h} |
| **DATA_BOARD_MEDIA_ASPECT_RATIO** | {dd.media_w}/{dd.media_h} = **{dd.aspect:.4f}** (near-square) |

The prior fixture crop `(413,126)-(728,362)` (315 x 236, ~1.33:1) CUT OFF the media bottom - the
"~4:3" was a cropping artefact. Re-extracted `tests/fixtures/founder_data_media_crop.png` at
322 x 295.

## 2. DATA_16_9_REQUIRED (section 4)

**DATA_16_9_REQUIRED = false.** Telegram accepts non-16:9 photo/document media; nothing in the
send path (`bot/`, `worker/content_cycle.py`) forces a 16:9 canvas. 16:9 (1280x720) entered the
DATA hero renderer only because `_CANVAS_W/_CANVAS_H` were imported from
`nnj_master_news_overlay` (the NEWS hero), a shared default - not a platform rule. DATA therefore
gets its OWN canvas geometry.

## 3. DATA dedicated output canvas (section 5 / section 6)

Width is kept at the existing production-safe **1280**; height derives from the measured board
media aspect:

    canvas_h = round(1280 * {dd.media_h} / {dd.media_w}) = round({1280 * dd.media_h / dd.media_w:.1f}) = {dd.canvas_h}

**V8 DATA canvas = {dd.canvas_w} x {dd.canvas_h}  (aspect {dd.canvas_w / dd.canvas_h:.4f})**, a
{abs(dd.canvas_w / dd.canvas_h - dd.aspect) / dd.aspect * 100:.2f}% match to the board media aspect.
Deterministic; no runtime dimension branching.

## 4. DATA hierarchy re-measure (section 11 - section 13, fractions of media HEIGHT)

| element | board cap-height frac | V8 derivation |
|---|---|---|
| value ("500") | {dd.value_cap_frac:.3f} (top at {dd.value_top_frac:.3f}) | `_fit_single_line`, cap 0.163 h -> ~270 px Fira Cond Black; primary_font_size lands 270 (bounded, proportion-matched, not "maximise") |
| unit ("МЛН")  | {dd.unit_over_value:.2f} x value | Black, red |
| label         | {dd.label_over_value:.3f} x value | SemiBold |
| secondary     | {dd.desc_over_value:.2f} x value | Medium |
| left text zone | right edge at x-frac {dd.left_zone_frac:.2f} | `_HERO_LEFT_ZONE_FRAC` = {dd.left_zone_frac} |

Metric block is TOP-anchored at `value_top_frac` x canvas_h (was vertically centred on the 16:9
canvas). Graph x-start pulled to {dd.graph_x_start_frac:.2f} so the trend integrates with the
metric block (no oversized empty gap); graph x-end {dd.graph_x_end_frac:.2f}, y {dd.graph_y_top_frac:.2f}..{dd.graph_y_bottom_frac:.2f}.

## 5. DATA graph / grid / fill (section 14 - section 17)

* `_segmented_anchor_path(xs, ys) == list(zip(xs, ys))` - the real series points are the ONLY
  anchors, connected DIRECTLY. No spline, no `_monotone_cubic` on the render path, no synthetic
  points. A 9-value fixture draws 9 anchors.
* Grid drawn only where `gx >= zone_x` (the graph zone); the left text region is clean near-black.
  `_guarded_grid_color` clamps grid_luma - bg_luma into [{dd.grid_luma_delta_min}, {dd.grid_luma_delta_max}] -
  cells are near-imperceptible at Telegram scale.
* Fill: `graph_fill_peak_alpha={dd.graph_fill_peak_alpha}`, band <= {dd.graph_fill_band_frac:.2f} of
  chart height below the curve, falloff {dd.graph_fill_falloff}. The red LINE is primary; the glow
  is a whisper; most of the chart stays dark; no triangular red wedge.

## 6. FOUNDER_DATA_MEDIA_MARK (section 18)

**FOUNDER_DATA_MEDIA_MARK = ABSENT.** 0 canonical-red pixels in the DATA media's lower-right
corner on the board; the only red glyph is the "PULSE / DATA" header dot (not the NNJ mark).
This CONFLICTS with the prior explicit one-mark decision (VISUAL-SINGLE-BRAND-MARK-1). Per
section 18 the safe reading is taken: V8 keeps ONE very restrained mark
(`mark_width_frac={dd.mark_width_frac:.3f}`, `mark_opacity={dd.mark_opacity:.2f}` - lower than V7)
and the conflict is flagged for Founder review. If the Founder confirms the media should carry no
mark, `_HERO_MARK_OPACITY` -> 0 is a one-line change.

## 7. BREAKING media rectangle (section 19)

| quantity | value |
|---|---|
| media x, y | 18, 747 |
| media w, h | 322 x 165 (aspect ~1.95) |

The prior fixture crop `(28,764)-(346,907)` cut off the RIGHT of the media - the full-width pulse
line looked half-width. Re-extracted `tests/fixtures/founder_breaking_media_crop.png` at 322 x 165.

## 8. BREAKING pulse line (section 20)

| quantity | board | V8 |
|---|---|---|
| first -> last visible red px | x 39 -> 295 (media x-frac 0.065 -> 0.860) | start {b.pulse_start_frac:.3f}, width {b.pulse_width_frac:.3f} -> end {b.pulse_start_frac + b.pulse_width_frac:.3f} |
| **BREAKING_LINE_TOTAL_WIDTH_FRAC** | **0.795** | **{b.pulse_width_frac:.3f}** (V7 was 0.4245 - "baseline ends too early") |
| P-QRS-T event, of the COMPLETE line | starts ~0.19, spans ~0.27, calm tail ~0.54 | `_PULSE_WAVEFORM_UNIT` places it 0.20..0.51 (UNCHANGED - "do not change the waveform family again") |
| R apex | +20 px = 0.078 of the full-width line on the 322 media | `pulse_r_amp_frac_of_width={b.pulse_r_amp_frac_of_width:.3f}` |
| baseline y | 905 -> media y-frac 0.958; S clips past the edge | `pulse_baseline_frac={b.pulse_baseline_frac:.3f}` + the layer clamps the deep S to the canvas edge so the pulse reads as attached to the lower edge |

## 9. BREAKING watermark - EFFECTIVE VISIBLE box, NOT the SVG width (section 21 / section 22)

| quantity | board (measured from grey strokes) | V8 |
|---|---|---|
| width frac of media | ~0.47 | `watermark_width_frac={b.watermark_width_frac:.2f}` |
| height frac of media | ~0.34 | proportional to the NNJ glyph |
| left x-frac in media | ~0.524 (entirely RIGHT of the centre line) | 1 - {b.watermark_right_inset_frac} - {b.watermark_width_frac} = {1 - b.watermark_right_inset_frac - b.watermark_width_frac:.3f} |
| right inset frac | ~0.006 (flush) | {b.watermark_right_inset_frac:.3f} |
| bottom inset frac | ~0.012 (near flush) | {b.watermark_bottom_inset_frac:.3f} |
| effective opacity | ~0.12-0.20 over noise | drawn at **{b.watermark_opacity:.2f}** - a genuine background watermark |

V7 drew 0.50 wide with a 0.016 right inset -> x-frac 0.484..0.984, crossing the centre line. V8's
0.47 / 0.006 -> x-frac {1 - b.watermark_right_inset_frac - b.watermark_width_frac:.3f}..{1 - b.watermark_right_inset_frac:.3f},
matching the board and living entirely in the right portion. Opacity is NOT increased for a bright
source (section 23) - the same {b.watermark_opacity:.2f} on dark and bright.
"""


if __name__ == "__main__":
    main()
