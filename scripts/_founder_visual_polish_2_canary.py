"""FOUNDER-VISUAL-POLISH-2 - LOCAL Founder review canaries (no Telegram send, no DB writes).

Renders the seven review classes through the CURRENT (polished) renderer, using representative
real assets, and builds the V2 contact sheet with the real Founder board on top.

    python scripts/_founder_visual_polish_2_canary.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

OUT = Path("artifacts/founder_visual_polish_2")
OUT.mkdir(parents=True, exist_ok=True)
BOARD = Path("docs/founder_telegram_board.png")
_BAKE = Path("assets/brand/newsroom_visuals/v2_1_bakeoff_sources")
_INTERNAL_TMPL = Path(
    "assets/brand/newsroom_visuals/v1/references/data/data_template_white.png"
)
_EXTERNAL_INFO = Path("tests/fixtures/external_source_infographic.jpg")
_PORTRAIT = Path("tests/fixtures/portrait_public_figure.jpg")


def _png(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as im:
        b = io.BytesIO()
        im.convert("RGB").save(b, format="PNG")
        return b.getvalue()


def main() -> int:
    from services.brand_renderer import (
        render_breaking_frame,
        render_data_card,
        render_quote_card,
    )
    from services.data_source_classification import DataPresentationMode
    from services.nnj_master_news_overlay import apply_master_news_branding
    from services.presentation_director import DataCandidate, QuoteCandidate

    # 01 NEWS - visually complex photo (photobooth scene, people, neon)
    news_src = _BAKE.joinpath("case3_bright_promotional_scene.jpg").read_bytes()
    news_bytes, _dec = apply_master_news_branding(news_src)
    (OUT / "01_NEWS.png").write_bytes(_png(news_bytes))

    # 02 BREAKING - product/news photo (iPhone)
    brk = render_breaking_frame(
        _BAKE.joinpath("case1_hero_product_iphone.jpg").read_bytes(),
        category="AI",
        editorial_code="NP-0185",
    )
    (OUT / "02_BREAKING.png").write_bytes(_png(brk))

    # 03 DATA external/source infographic (non-NNJ) - preserved, one renderer NNJ
    dc_ext = DataCandidate(
        value="68",
        unit="%",
        label="EV share",
        evidence_fact="68% of new car sales were electric",
    )
    d_ext = render_data_card(
        dc_ext,
        category="DATA",
        editorial_code="NP-0190",
        source_image_bytes=_EXTERNAL_INFO.read_bytes(),
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    (OUT / "03_DATA_SOURCE_INFOGRAPHIC.png").write_bytes(_png(d_ext))

    # 04 DATA hero metric (polished)
    dc_hero = DataCandidate(
        value="500",
        unit="млн",
        label="пользователей",
        evidence_fact="Достиг ChatGPT в июле 2025 года",
        series=(120.0, 175.0, 240.0, 320.0, 410.0, 500.0),
        delta="+38%",
    )
    d_hero = render_data_card(
        dc_hero,
        category="DATA",
        editorial_code="NP-0183",
        source_image_bytes=news_src,
        presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    (OUT / "04_DATA_HERO_METRIC.png").write_bytes(_png(d_hero))

    # 05 QUOTE - real portrait + role
    qc = QuoteCandidate(
        text="Технологии сами по себе ничего не значат. Важно то, во что мы верим и что создаём вместе.",
        speaker="Тим Кук",
        role="CEO, Apple",
    )
    q = render_quote_card(
        qc,
        category="QUOTE",
        editorial_code="NP-0182",
        portrait_bytes=_PORTRAIT.read_bytes(),
    )
    (OUT / "05_QUOTE.png").write_bytes(_png(q))

    # 06 QUOTE - real portrait, NO role (same dark language)
    qc2 = QuoteCandidate(
        text="On-device inference is real now, and it quietly changes what a product can promise.",
        speaker="A. Researcher",
    )
    q2 = render_quote_card(
        qc2,
        category="QUOTE",
        editorial_code="NP-0182",
        portrait_bytes=_PORTRAIT.read_bytes(),
    )
    (OUT / "06_QUOTE_NO_ROLE.png").write_bytes(_png(q2))

    # 07 INTERNAL NNJ-BRANDED SOURCE - regression: source already branded -> NO renderer NNJ added
    dc_int = DataCandidate(value="X,XXX", unit="", label="", evidence_fact="")
    d_int = render_data_card(
        dc_int,
        category="DATA",
        editorial_code="NP-0191",
        source_image_bytes=_INTERNAL_TMPL.read_bytes(),
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    (OUT / "07_INTERNAL_BRANDED_SOURCE.png").write_bytes(_png(d_int))

    _contact_sheet()
    print(f"wrote 7 renders + 00_CONTACT_SHEET_V2.png to {OUT}")
    return 0


def _contact_sheet() -> None:
    order = [
        (
            "01_NEWS.png",
            "01 NEWS - restrained corner mark, no red line, source dominant",
        ),
        ("02_BREAKING.png", "02 BREAKING - red PULSE across lower media + one mark"),
        (
            "03_DATA_SOURCE_INFOGRAPHIC.png",
            "03 DATA external infographic - preserved, ONE renderer NNJ",
        ),
        (
            "04_DATA_HERO_METRIC.png",
            "04 DATA hero metric - polished hierarchy / balance",
        ),
        ("05_QUOTE.png", "05 QUOTE - real portrait + role, dark composition"),
        (
            "06_QUOTE_NO_ROLE.png",
            "06 QUOTE no role - SAME dark language, role line omitted",
        ),
        (
            "07_INTERNAL_BRANDED_SOURCE.png",
            "07 internal NNJ-branded source - NO second NNJ added",
        ),
    ]
    cols, cw, ch, pad, cap = 3, 560, 315, 22, 34
    board_img = None
    W = cols * (cw + pad) + pad
    if BOARD.exists():
        with Image.open(BOARD) as bi:
            b = bi.convert("RGB")
            sc = W / b.width
            board_img = b.resize((int(b.width * sc), int(b.height * sc)))
    rows = (len(order) + cols - 1) // cols
    board_h = (board_img.height + cap + pad) if board_img else 0
    H = board_h + rows * (ch + cap + pad) + pad
    sheet = Image.new("RGB", (W, H), (16, 16, 18))
    d = ImageDraw.Draw(sheet)
    y0 = pad
    if board_img is not None:
        d.text(
            (pad, 6),
            "FOUNDER BOARD REFERENCE (docs/founder_telegram_board.png) - VISUAL AUTHORITY #1",
            fill=(237, 28, 36),
        )
        sheet.paste(board_img, (pad, cap))
        y0 = board_img.height + cap + pad
    for i, (name, title) in enumerate(order):
        cx = pad + (i % cols) * (cw + pad)
        cy = y0 + (i // cols) * (ch + cap + pad)
        p = OUT / name
        if p.exists():
            with Image.open(p) as im:
                t = im.convert("RGB")
                t.thumbnail((cw, ch))
                sheet.paste(t, (cx, cy + cap))
        d.text((cx, cy + 8), title, fill=(230, 230, 230))
    sheet.save(OUT / "00_CONTACT_SHEET_V2.png")


if __name__ == "__main__":
    raise SystemExit(main())
