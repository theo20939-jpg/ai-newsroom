"""FOUNDER-VISUAL-FINAL-BOARD-MATCH-7 - local canary + same-scale Founder review sheet.

Renders the V7 BREAKING / GENERATED DATA on realistic local assets (DATA uses DENSE 7-9 point
fixtures, section 14) and assembles the review package at
C:/Users/Theodor/Desktop/NINJA_PULSE_FINAL_BOARD_MATCH_V7/ with SAME-SCALE comparison rows.

No production. No image-generation model. No font files copied into the package. Run from the
repo root:

    python scripts/_founder_visual_final_board_match_7_canary.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw  # noqa: E402

from services.brand_renderer import (  # noqa: E402
    _data_font,
    _font,
    render_breaking_frame,
    render_data_card,
    render_data_hero_card,
)
from services.data_source_classification import DataPresentationMode  # noqa: E402
from services.presentation_director import DataCandidate  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
ART = REPO / "artifacts" / "founder_visual_final_board_match_7"
DESKTOP = Path("C:/Users/Theodor/Desktop/NINJA_PULSE_FINAL_BOARD_MATCH_V7")
BOARD = REPO / "docs" / "founder_telegram_board.png"
SRC = REPO / "assets" / "brand" / "newsroom_visuals" / "v2_1_bakeoff_sources"
BRK_CROP = (28, 764, 346, 907)   # board BREAKING media
DATA_CROP = (413, 126, 728, 362)  # board DATA media


def _im(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def _row_pair(label: str, board_img: Image.Image, v7_img: Image.Image, panel_w: int) -> Image.Image:
    """One same-scale comparison row: board crop and V7 output scaled to the SAME width, stacked
    with clear captions."""
    def _fit(im: Image.Image) -> Image.Image:
        return im.resize((panel_w, max(1, round(im.height * panel_w / im.width))))

    bd, v7 = _fit(board_img), _fit(v7_img)
    pad, cap = 16, 34
    h = cap + cap + bd.height + 10 + cap + v7.height + pad
    out = Image.new("RGB", (panel_w + pad * 2, h), (10, 10, 12))
    d = ImageDraw.Draw(out)
    y = 10
    d.text((pad, y), label, font=_font(24, bold=True), fill=(255, 255, 255))
    y += cap
    d.text((pad, y), "FOUNDER BOARD (same width)", font=_font(20, bold=True), fill=(150, 200, 150))
    y += cap
    out.paste(bd, (pad, y))
    y += bd.height + 10
    d.text((pad, y), "V7", font=_font(20, bold=True), fill=(200, 160, 160))
    y += cap
    out.paste(v7, (pad, y))
    return out


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    DESKTOP.mkdir(parents=True, exist_ok=True)
    board = Image.open(BOARD).convert("RGB")

    dark = (SRC / "case1_hero_product_iphone.jpg").read_bytes()
    light = (SRC / "case3_bright_promotional_scene.jpg").read_bytes()
    brk_dark = _im(render_breaking_frame(dark, category="AI", editorial_code="NP-B1"))
    brk_light = _im(render_breaking_frame(light, category="AI", editorial_code="NP-B2"))

    # DENSE fixtures (section 14): 7-9 EXPLICIT values - fixture data, not renderer-fabricated
    d500 = DataCandidate(
        value="500", unit="mln", label="polzovateley", evidence_fact="Reached ChatGPT in July 2025",
        series=(118.0, 130.0, 127.0, 190.0, 242.0, 230.0, 331.0, 420.0, 500.0), delta="+38%")
    dpct = DataCandidate(
        value="68", unit="%", label="EV share of new registrations", evidence_fact="Regional new-car sales, 2025",
        series=(18.0, 22.0, 29.0, 27.0, 41.0, 44.0, 52.0, 55.0, 68.0), delta="+13 pp")
    dlong = DataCandidate(
        value="1,4 bln", unit="messages", label="per day", evidence_fact="WhatsApp, December 2025",
        series=(0.82, 0.9, 1.05, 1.0, 1.12, 1.18, 1.4), delta="+22%")
    hero500 = _im(render_data_hero_card(d500))
    heropct = _im(render_data_hero_card(dpct))
    herolong = _im(render_data_hero_card(dlong))

    # frozen DATA source regression proof
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
        d500, category="DATA", editorial_code="NP-1", source_image_bytes=lb.getvalue(),
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING))

    outs = {
        "01_BREAKING_DARK.png": brk_dark,
        "02_BREAKING_LIGHT.png": brk_light,
        "03_DATA_500.png": hero500,
        "04_DATA_PERCENT.png": heropct,
        "05_DATA_LONG_VALUE.png": herolong,
        "06_DATA_SOURCE_FROZEN.png": src_frozen,
    }
    for name, img in outs.items():
        img.save(ART / name)
        img.save(DESKTOP / name)

    # -- same-scale review sheet --------------------------------------------------------------------
    board_brk = board.crop(BRK_CROP)
    board_data = board.crop(DATA_CROP)
    PW = 1180
    # BREAKING: compare the lower branding band of the V7 render, cropped to the board crop's aspect
    def _brk_band(v7: Image.Image) -> Image.Image:
        ar = board_brk.width / board_brk.height
        bh = round(v7.width / ar)
        return v7.crop((0, v7.height - bh, v7.width, v7.height))

    rows = [
        _row_pair("BREAKING - dark product photo (lower branding band)", board_brk, _brk_band(brk_dark), PW),
        _row_pair("BREAKING - bright photo (lower branding band)", board_brk, _brk_band(brk_light), PW),
        _row_pair("DATA GENERATED - 500 / MLN, 9-point fixture", board_data, hero500, PW),
        _row_pair("DATA GENERATED - 68 / %, 9-point fixture", board_data, heropct, PW),
        _row_pair("DATA GENERATED - 1,4 bln / messages, 7-point fixture", board_data, herolong, PW),
    ]
    gap = 20
    # two columns of rows to avoid a giant vertical strip
    col_h = [0, 0]
    placed = []
    for i, r in enumerate(rows):
        c = 0 if col_h[0] <= col_h[1] else 1
        placed.append((c, col_h[c], r))
        col_h[c] += r.height + gap
    sheet_w = (PW + 40) * 2 + gap
    sheet_h = max(col_h) + 20
    sheet = Image.new("RGB", (sheet_w, sheet_h), (6, 6, 8))
    for c, y, r in placed:
        sheet.paste(r, (c * ((PW + 40) + gap) + 10, y + 10))
    sheet.save(ART / "00_REFERENCE_VS_V7.png")
    sheet.save(DESKTOP / "00_REFERENCE_VS_V7.png")

    print("wrote", len(outs) + 1, "images to", ART, "and", DESKTOP)
    _ = _data_font


if __name__ == "__main__":
    main()
