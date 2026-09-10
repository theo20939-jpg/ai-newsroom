"""FOUNDER-VISUAL-OVERLAY-RECOVERY-4 - local canary + reference-vs-recovered review package.

Renders the recovered BREAKING / DATA outputs on REALISTIC content (§24) and assembles the
Founder review sheet (§25) at C:/Users/Theodor/Desktop/NINJA_PULSE_OVERLAY_RECOVERY_REVIEW/.

No production. No image-generation model. Pillow only, deterministic. Run from the repo root:

    python scripts/_founder_visual_overlay_recovery_4_canary.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw  # noqa: E402

from services.brand_renderer import (  # noqa: E402
    _font,
    render_breaking_frame,
    render_data_card,
    render_data_hero_card,
)
from services.data_source_classification import DataPresentationMode  # noqa: E402
from services.presentation_director import DataCandidate  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
ART = REPO / "artifacts" / "founder_visual_overlay_recovery_4"
DESKTOP = Path("C:/Users/Theodor/Desktop/NINJA_PULSE_OVERLAY_RECOVERY_REVIEW")
BOARD = REPO / "docs" / "founder_telegram_board.png"
SRC = REPO / "assets" / "brand" / "newsroom_visuals" / "v2_1_bakeoff_sources"


def _im(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def _dark_external_infographic() -> bytes:
    """A deterministic DARK 'external publisher' infographic fixture (no NNJ) - a donut-ish bar
    readout on a near-black ground. Pillow primitives only, never an image model."""
    w, h = 1600, 900
    im = Image.new("RGB", (w, h), (16, 18, 22))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, w, 96), fill=(30, 34, 42))
    d.text((40, 30), "AI COMPUTE SPEND BY QUARTER", font=_font(38, bold=True), fill=(236, 238, 242))
    d.text((40, h - 54), "Source: Sample Analytics Desk, Q1 2026", font=_font(24), fill=(150, 154, 162))
    vals = [12, 19, 27, 34, 46]
    yrs = ["Q1", "Q2", "Q3", "Q4", "Q1'"]
    bx, bw, gap, base_y, scale = 150, 150, 66, 760, 10.0
    for i, (v, yr) in enumerate(zip(vals, yrs)):
        x = bx + i * (bw + gap)
        bh = int(v * scale)
        col = (0, 168, 214) if i < len(vals) - 1 else (232, 92, 60)
        d.rectangle((x, base_y - bh, x + bw, base_y), fill=col)
        d.text((x, base_y - bh - 40), f"${v}B", font=_font(30, bold=True), fill=(236, 238, 242))
        d.text((x + 40, base_y + 12), yr, font=_font(26), fill=(170, 174, 182))
    d.line((120, base_y, w - 120, base_y), fill=(70, 74, 82), width=3)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _scale_to(img: Image.Image, *, h: int, w: int | None = None) -> Image.Image:
    """Scale `img` to height `h` (and, if it would then exceed `w`, to width `w`), keeping aspect."""
    scale = h / img.height
    if w is not None and img.width * scale > w:
        scale = w / img.width
    return img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))))


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
    src_light = (REPO / "tests" / "fixtures" / "external_source_infographic.jpg").read_bytes()
    src_dark = _dark_external_infographic()

    outputs = {
        "01_BREAKING_DARK.png": _im(render_breaking_frame(dark, category="AI", editorial_code="NP-B1")),
        "02_BREAKING_LIGHT.png": _im(render_breaking_frame(light, category="AI", editorial_code="NP-B2")),
        "03_DATA_GENERATED_A.png": _im(render_data_hero_card(hero_a)),
        "04_DATA_GENERATED_B.png": _im(render_data_hero_card(hero_b)),
        "05_DATA_SOURCE_LIGHT.png": _im(render_data_card(
            hero_b, category="DATA", editorial_code="NP-1", source_image_bytes=src_light,
            presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING)),
        "06_DATA_SOURCE_DARK.png": _im(render_data_card(
            hero_a, category="DATA", editorial_code="NP-2", source_image_bytes=src_dark,
            presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING)),
    }
    for name, img in outputs.items():
        img.save(ART / name)
        img.save(DESKTOP / name)

    # 00_REFERENCE_VS_RECOVERED.png - board BREAKING + DATA crops on top, recovered outputs below,
    # each large enough to judge line/font quality (§25).
    board = Image.open(BOARD).convert("RGB")
    brk_ref = _scale_to(board.crop((28, 648, 382, 1044)), h=780)
    data_ref = _scale_to(board.crop((388, 86, 744, 452)), h=780)

    sheet_w = 1600
    max_row_h = 900
    rows: list[tuple[str, Image.Image]] = [
        ("RECOVERED - 01 BREAKING (dark product source)", outputs["01_BREAKING_DARK.png"]),
        ("RECOVERED - 02 BREAKING (bright product source)", outputs["02_BREAKING_LIGHT.png"]),
        ("RECOVERED - 03 DATA GENERATED A (500 / МЛН, rising series)", outputs["03_DATA_GENERATED_A.png"]),
        ("RECOVERED - 04 DATA GENERATED B (68 / %, different series)", outputs["04_DATA_GENERATED_B.png"]),
        ("RECOVERED - 05 DATA SOURCE (light external infographic - preserved)", outputs["05_DATA_SOURCE_LIGHT.png"]),
        ("RECOVERED - 06 DATA SOURCE (dark external infographic - preserved)", outputs["06_DATA_SOURCE_DARK.png"]),
    ]
    scaled_rows = [(t, _scale_to(im, h=min(max_row_h, im.height), w=sheet_w - 40)) for t, im in rows]
    total_h = 64 + brk_ref.height + 40 + sum(40 + im.height + 28 for _, im in scaled_rows) + 40

    sheet = Image.new("RGB", (sheet_w, total_h), (10, 10, 12))
    sd = ImageDraw.Draw(sheet)
    y = 20
    sd.text((20, y), "FOUNDER BOARD - reference crops (docs/founder_telegram_board.png)",
            font=_font(28, bold=True), fill=(255, 255, 255))
    y += 44
    sheet.paste(brk_ref, (20, y))
    sheet.paste(data_ref, (40 + brk_ref.width, y))
    y += brk_ref.height + 40
    for title, im in scaled_rows:
        sd.text((20, y), title, font=_font(24, bold=True), fill=(255, 255, 255))
        y += 40
        sheet.paste(im, (20, y))
        y += im.height + 28

    sheet.save(ART / "00_REFERENCE_VS_RECOVERED.png")
    sheet.save(DESKTOP / "00_REFERENCE_VS_RECOVERED.png")

    print("wrote", len(outputs) + 1, "images to", ART, "and", DESKTOP)


if __name__ == "__main__":
    main()
