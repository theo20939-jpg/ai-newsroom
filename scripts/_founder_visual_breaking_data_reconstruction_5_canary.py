"""FOUNDER-VISUAL-BREAKING-DATA-RECONSTRUCTION-5 - local canary + Founder review package.

Renders BREAKING / DATA (generated + source) through the reconstructed renderer on realistic
local assets (§27) and assembles the review package (§28) at
C:/Users/Theodor/Desktop/NINJA_PULSE_BREAKING_DATA_FIX_V5/.

No production. No image-generation model. Pillow only, deterministic. Run from the repo root:

    python scripts/_founder_visual_breaking_data_reconstruction_5_canary.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from services.brand_renderer import (  # noqa: E402
    _font,
    render_breaking_frame,
    render_data_card,
    render_data_hero_card,
)
from services.data_source_classification import DataPresentationMode  # noqa: E402
from services.presentation_director import DataCandidate  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
ART = REPO / "artifacts" / "founder_visual_breaking_data_reconstruction_5"
DESKTOP = Path("C:/Users/Theodor/Desktop/NINJA_PULSE_BREAKING_DATA_FIX_V5")
BOARD = REPO / "docs" / "founder_telegram_board.png"
SRC = REPO / "assets" / "brand" / "newsroom_visuals" / "v2_1_bakeoff_sources"


def _im(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def _scale_to(img: Image.Image, *, h: int, w: int | None = None) -> Image.Image:
    s = h / img.height
    if w is not None and img.width * s > w:
        s = w / img.width
    return img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))))


def _external_infographic(dark: bool) -> bytes:
    """Deterministic 'external publisher' infographic fixture (no NNJ). Pillow only."""
    w, h = 1600, 900
    bg = (16, 18, 22) if dark else (247, 248, 250)
    ink = (236, 238, 242) if dark else (20, 32, 60)
    sub = (150, 154, 162) if dark else (90, 96, 108)
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, w, 96), fill=(30, 34, 42) if dark else (20, 32, 60))
    d.text((40, 30), "AI COMPUTE SPEND BY QUARTER", font=_font(38, bold=True),
           fill=(236, 238, 242))
    vals = [12, 19, 27, 34, 46]
    yrs = ["Q1", "Q2", "Q3", "Q4", "Q1'"]
    bx, bw, gap, base_y, scale = 150, 150, 66, 760, 10.0
    for i, (v, yr) in enumerate(zip(vals, yrs)):
        bxi = bx + i * (bw + gap)
        bh = int(v * scale)
        col = (0, 168, 214) if i < len(vals) - 1 else (232, 92, 60)
        d.rectangle((bxi, base_y - bh, bxi + bw, base_y), fill=col)
        d.text((bxi, base_y - bh - 40), f"${v}B", font=_font(30, bold=True), fill=ink)
        d.text((bxi + 40, base_y + 12), yr, font=_font(26), fill=sub)
    d.line((120, base_y, w - 120, base_y), fill=(70, 74, 82) if dark else (170, 176, 186), width=3)
    d.text((40, h - 54), "Source: Sample Analytics Desk, Q1 2026", font=_font(24), fill=sub)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _external_infographic_br_occupied() -> bytes:
    """Light infographic whose BOTTOM-RIGHT carries a publisher watermark - proves safe
    placement / suppression, and that a third-party logo is never touched."""
    data = _external_infographic(dark=False)
    im = Image.open(io.BytesIO(data)).convert("RGB")
    d = ImageDraw.Draw(im)
    d.text((im.width - 260, im.height - 44), "chartsource.io", font=_font(26, bold=True),
           fill=(120, 126, 138))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _typography_sheet() -> Image.Image:
    cands = [
        ("Arial Bold (RECOVERY-4)", "C:/Windows/Fonts/arialbd.ttf"),
        ("Arial Black  <- SELECTED (heavy)", "C:/Windows/Fonts/ariblk.ttf"),
        ("Segoe UI Black", "C:/Windows/Fonts/segoeuiz.ttf"),
        ("Bahnschrift", "C:/Windows/Fonts/bahnschrift.ttf"),
        ("Tahoma Bold", "C:/Windows/Fonts/tahomabd.ttf"),
    ]
    rows = [c for c in cands if Path(c[1]).exists()]
    W, H = 1500, 210 * len(rows) + 30
    im = Image.new("RGB", (W, H), (6, 7, 9))
    d = ImageDraw.Draw(im)
    y = 16
    for name, path in rows:
        big = ImageFont.truetype(path, 128)
        red = ImageFont.truetype(path, 92)
        lab = ImageFont.truetype(path, 38)
        d.text((20, y), name, font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 22),
               fill=(150, 154, 162))
        d.text((20, y + 30), "500", font=big, fill=(255, 255, 255))
        w5 = d.textlength("500", font=big)
        d.text((30 + w5, y + 64), "МЛН", font=red, fill=(237, 28, 36))
        d.text((20, y + 168), "ПОЛЬЗОВАТЕЛЕЙ  +38%", font=lab, fill=(255, 255, 255))
        y += 210
    return im


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    DESKTOP.mkdir(parents=True, exist_ok=True)

    dark = (SRC / "case1_hero_product_iphone.jpg").read_bytes()
    light = (SRC / "case3_bright_promotional_scene.jpg").read_bytes()

    hero_a = DataCandidate(
        value="500", unit="млн", label="пользователей",
        evidence_fact="Достиг ChatGPT в июле 2025 года",
        series=(120.0, 150.0, 190.0, 250.0, 330.0, 420.0, 500.0), delta="+38%",
    )
    hero_b = DataCandidate(
        value="68", unit="%", label="электромобилей в новых продажах",
        evidence_fact="Доля новых машин в регионе за 2025 год",
        series=(18.0, 29.0, 41.0, 55.0, 68.0), delta="+13 п.п.",
    )
    hero_c = DataCandidate(
        value="1,4 млрд", unit="сообщений", label="в день",
        evidence_fact="WhatsApp, декабрь 2025",
        series=(0.9, 1.0, 1.15, 1.4), delta="+22%",
    )

    outputs = {
        "01_BREAKING_DARK.png": _im(render_breaking_frame(dark, category="AI", editorial_code="NP-B1")),
        "02_BREAKING_LIGHT.png": _im(render_breaking_frame(light, category="AI", editorial_code="NP-B2")),
        "03_DATA_GENERATED_A.png": _im(render_data_hero_card(hero_a)),
        "04_DATA_GENERATED_B.png": _im(render_data_hero_card(hero_b)),
        "04c_DATA_GENERATED_C_short_label.png": _im(render_data_hero_card(hero_c)),
        "05_DATA_SOURCE_LIGHT.png": _im(render_data_card(
            hero_b, category="DATA", editorial_code="NP-1",
            source_image_bytes=_external_infographic(dark=False),
            presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING)),
        "06_DATA_SOURCE_DARK.png": _im(render_data_card(
            hero_a, category="DATA", editorial_code="NP-2",
            source_image_bytes=_external_infographic(dark=True),
            presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING)),
        "06c_DATA_SOURCE_BR_OCCUPIED.png": _im(render_data_card(
            hero_a, category="DATA", editorial_code="NP-3",
            source_image_bytes=_external_infographic_br_occupied(),
            presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING)),
    }
    for name, img in outputs.items():
        img.save(ART / name)
        img.save(DESKTOP / name)

    typo = _typography_sheet()
    typo.save(ART / "07_TYPOGRAPHY_COMPARISON.png")
    typo.save(DESKTOP / "07_TYPOGRAPHY_COMPARISON.png")

    # 00_REFERENCE_VS_FIXED.png
    board = Image.open(BOARD).convert("RGB")
    brk_ref = _scale_to(board.crop((26, 758, 350, 918)), h=360)
    data_ref = _scale_to(board.crop((415, 128, 726, 360)), h=560)
    sheet_w = 1600
    rows = [
        ("BOARD - BREAKING crop", brk_ref),
        ("FIXED - 01 BREAKING (dark source)", _scale_to(outputs["01_BREAKING_DARK.png"], h=900, w=sheet_w - 40)),
        ("FIXED - 02 BREAKING (bright source)", _scale_to(outputs["02_BREAKING_LIGHT.png"], h=900, w=sheet_w - 40)),
        ("BOARD - DATA crop", data_ref),
        ("FIXED - 03 DATA GENERATED A (500 / МЛН)", _scale_to(outputs["03_DATA_GENERATED_A.png"], h=760, w=sheet_w - 40)),
        ("FIXED - 04 DATA GENERATED B (68 / %)", _scale_to(outputs["04_DATA_GENERATED_B.png"], h=760, w=sheet_w - 40)),
        ("FIXED - 04c DATA GENERATED C (long value, short label)", _scale_to(outputs["04c_DATA_GENERATED_C_short_label.png"], h=760, w=sheet_w - 40)),
        ("FIXED - 05 DATA SOURCE (light external infographic - preserved)", _scale_to(outputs["05_DATA_SOURCE_LIGHT.png"], h=760, w=sheet_w - 40)),
        ("FIXED - 06 DATA SOURCE (dark external infographic - preserved)", _scale_to(outputs["06_DATA_SOURCE_DARK.png"], h=760, w=sheet_w - 40)),
        ("FIXED - 06c DATA SOURCE (bottom-right publisher watermark - untouched)", _scale_to(outputs["06c_DATA_SOURCE_BR_OCCUPIED.png"], h=760, w=sheet_w - 40)),
    ]
    total_h = 30 + sum(40 + im.height + 26 for _, im in rows)
    sheet = Image.new("RGB", (sheet_w, total_h), (10, 10, 12))
    sd = ImageDraw.Draw(sheet)
    y = 16
    for title, im in rows:
        sd.text((20, y), title, font=_font(24, bold=True), fill=(255, 255, 255))
        y += 40
        sheet.paste(im, (20, y))
        y += im.height + 26
    sheet.save(ART / "00_REFERENCE_VS_FIXED.png")
    sheet.save(DESKTOP / "00_REFERENCE_VS_FIXED.png")

    print("wrote", len(outputs) + 2, "images to", ART, "and", DESKTOP)


if __name__ == "__main__":
    main()
