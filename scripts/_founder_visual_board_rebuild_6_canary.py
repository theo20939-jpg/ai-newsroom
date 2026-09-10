"""FOUNDER-VISUAL-BOARD-REBUILD-6 - local canary + Founder review package (§22).

Renders BREAKING / DATA (generated + source) through the rebuilt renderer on realistic local
assets and assembles the review package at C:/Users/Theodor/Desktop/NINJA_PULSE_BOARD_REBUILD_V6/.

No production. No image-generation model. No font files are copied into the review package (the
bundled OFL font is a repo runtime asset only, §7/§19). Run from the repo root:

    python scripts/_founder_visual_board_rebuild_6_canary.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from services.brand_renderer import (  # noqa: E402
    _data_font,
    _font,
    data_font_path,
    render_breaking_frame,
    render_data_card,
    render_data_hero_card,
)
from services.data_source_classification import DataPresentationMode  # noqa: E402
from services.presentation_director import DataCandidate  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
ART = REPO / "artifacts" / "founder_visual_board_rebuild_6"
DESKTOP = Path("C:/Users/Theodor/Desktop/NINJA_PULSE_BOARD_REBUILD_V6")
BOARD = REPO / "docs" / "founder_telegram_board.png"
SRC = REPO / "assets" / "brand" / "newsroom_visuals" / "v2_1_bakeoff_sources"


def _im(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def _scale(img: Image.Image, *, h: int, w: int | None = None) -> Image.Image:
    s = h / img.height
    if w is not None and img.width * s > w:
        s = w / img.width
    return img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))))


def _infographic(dark: bool, occupied: bool = False) -> bytes:
    bg = (16, 18, 22) if dark else (247, 248, 250)
    ink = (236, 238, 242) if dark else (20, 32, 60)
    sub = (150, 154, 162) if dark else (90, 96, 108)
    im = Image.new("RGB", (1600, 900), bg)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 1600, 92), fill=(30, 34, 42) if dark else (20, 32, 60))
    d.text((40, 30), "GLOBAL EV ADOPTION 2025", font=_font(38, bold=True), fill=(236, 238, 242))
    for i, v in enumerate((18, 29, 41, 55, 68)):
        x = 150 + i * 220
        d.rectangle((x, 760 - v * 9, x + 150, 760), fill=ink if i < 4 else (232, 92, 60))
        d.text((x, 760 - v * 9 - 40), f"{v}%", font=_font(30, bold=True), fill=ink)
        d.text((x + 40, 772), str(2021 + i), font=_font(24), fill=sub)
    d.line((120, 760, 1480, 760), fill=(70, 74, 82) if dark else (170, 176, 186), width=3)
    d.text((40, 840), "Source: Regional Transport Agency, Jan 2026", font=_font(24), fill=sub)
    if occupied:
        for cx, cy in ((60, 120), (1500, 120), (60, 820), (1470, 820)):
            d.text((cx, cy), "chartsource.io", font=_font(24, bold=True), fill=(120, 126, 138))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _typography_sheet() -> Image.Image:
    board = Image.open(BOARD).convert("RGB").crop((413, 126, 728, 300))
    board = _scale(board, h=300)
    samples = ["500", "МЛН", "ПОЛЬЗОВАТЕЛЕЙ", "+38%", "1,4 млрд", "СООБЩЕНИЙ"]
    W, H = 1600, 300 + 60 + len(samples) * 96 + 40
    im = Image.new("RGB", (W, H), (6, 7, 9))
    d = ImageDraw.Draw(im)
    d.text((20, 12), f"FOUNDER BOARD DATA crop  vs  BUNDLED {data_font_path('black').name}  (SIL OFL)",
           font=_font(24, bold=True), fill=(255, 255, 255))
    im.paste(board, (20, 46))
    y = 46 + board.height + 24
    for s in samples:
        f = _data_font(72, "black")
        d.text((24, y), s, font=f, fill=(237, 28, 36) if s in ("МЛН", "СООБЩЕНИЙ", "+38%") else (255, 255, 255))
        y += 96
    return im


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    DESKTOP.mkdir(parents=True, exist_ok=True)

    dark = (SRC / "case1_hero_product_iphone.jpg").read_bytes()
    light = (SRC / "case3_bright_promotional_scene.jpg").read_bytes()

    hero_500 = DataCandidate(
        value="500", unit="млн", label="пользователей",
        evidence_fact="Достиг ChatGPT в июле 2025 года",
        series=(120.0, 150.0, 190.0, 250.0, 330.0, 420.0, 500.0), delta="+38%")
    hero_pct = DataCandidate(
        value="68", unit="%", label="электромобилей в новых продажах",
        evidence_fact="Доля новых машин в регионе за 2025 год",
        series=(18.0, 29.0, 41.0, 44.0, 68.0), delta="+13 п.п.")
    hero_long = DataCandidate(
        value="1,4 млрд", unit="сообщений", label="в день",
        evidence_fact="WhatsApp, декабрь 2025",
        series=(0.9, 1.05, 1.0, 1.4), delta="+22%")

    outputs = {
        "01_BREAKING_DARK.png": _im(render_breaking_frame(dark, category="AI", editorial_code="NP-B1")),
        "02_BREAKING_LIGHT.png": _im(render_breaking_frame(light, category="AI", editorial_code="NP-B2")),
        "03_DATA_GENERATED_500.png": _im(render_data_hero_card(hero_500)),
        "04_DATA_GENERATED_PERCENT.png": _im(render_data_hero_card(hero_pct)),
        "05_DATA_GENERATED_LONG_VALUE.png": _im(render_data_hero_card(hero_long)),
        "06_DATA_SOURCE_LIGHT.png": _im(render_data_card(
            hero_pct, category="DATA", editorial_code="NP-1", source_image_bytes=_infographic(False),
            presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING)),
        "07_DATA_SOURCE_DARK.png": _im(render_data_card(
            hero_500, category="DATA", editorial_code="NP-2", source_image_bytes=_infographic(True),
            presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING)),
        "08_DATA_SOURCE_NO_SAFE_ZONE.png": _im(render_data_card(
            hero_500, category="DATA", editorial_code="NP-3",
            source_image_bytes=_infographic(False, occupied=True),
            presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING)),
    }
    for name, img in outputs.items():
        img.save(ART / name)
        img.save(DESKTOP / name)

    typo = _typography_sheet()
    typo.save(ART / "09_TYPOGRAPHY_FINAL.png")
    typo.save(DESKTOP / "09_TYPOGRAPHY_FINAL.png")

    # 00_REFERENCE_VS_V6.png - board crops beside the V6 outputs, LARGE
    board = Image.open(BOARD).convert("RGB")
    brk_ref = _scale(board.crop((28, 764, 346, 907)), h=360)
    data_ref = _scale(board.crop((413, 126, 728, 362)), h=620)
    sheet_w = 1720
    rows: list[tuple[str, Image.Image]] = [
        ("FOUNDER BOARD - BREAKING crop", brk_ref),
        ("V6 - 01 BREAKING (dark source)", _scale(outputs["01_BREAKING_DARK.png"], h=940, w=sheet_w - 40)),
        ("V6 - 02 BREAKING (bright source)", _scale(outputs["02_BREAKING_LIGHT.png"], h=940, w=sheet_w - 40)),
        ("FOUNDER BOARD - DATA crop", data_ref),
        ("V6 - 03 DATA GENERATED (500 / МЛН)", _scale(outputs["03_DATA_GENERATED_500.png"], h=800, w=sheet_w - 40)),
        ("V6 - 04 DATA GENERATED (68 / %)", _scale(outputs["04_DATA_GENERATED_PERCENT.png"], h=800, w=sheet_w - 40)),
        ("V6 - 05 DATA GENERATED (1,4 млрд / сообщений)", _scale(outputs["05_DATA_GENERATED_LONG_VALUE.png"], h=800, w=sheet_w - 40)),
        ("V6 - 06 DATA SOURCE (light infographic - preserved + small watermark)", _scale(outputs["06_DATA_SOURCE_LIGHT.png"], h=800, w=sheet_w - 40)),
        ("V6 - 07 DATA SOURCE (dark infographic - preserved)", _scale(outputs["07_DATA_SOURCE_DARK.png"], h=800, w=sheet_w - 40)),
        ("V6 - 08 DATA SOURCE (every corner occupied - BRAND SUPPRESSION)", _scale(outputs["08_DATA_SOURCE_NO_SAFE_ZONE.png"], h=800, w=sheet_w - 40)),
    ]
    total_h = 24 + sum(42 + im.height + 26 for _, im in rows)
    sheet = Image.new("RGB", (sheet_w, total_h), (10, 10, 12))
    d = ImageDraw.Draw(sheet)
    y = 14
    for title, im in rows:
        d.text((20, y), title, font=_font(24, bold=True), fill=(255, 255, 255))
        y += 42
        sheet.paste(im, (20, y))
        y += im.height + 26
    sheet.save(ART / "00_REFERENCE_VS_V6.png")
    sheet.save(DESKTOP / "00_REFERENCE_VS_V6.png")

    print("wrote", len(outputs) + 2, "images to", ART, "and", DESKTOP)
    _ = ImageFont


if __name__ == "__main__":
    main()
