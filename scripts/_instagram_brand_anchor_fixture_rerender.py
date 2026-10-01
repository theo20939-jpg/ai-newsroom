"""Offline rerender of a saved Instagram carousel package and its existing generated pixels.

Usage: python scripts/_instagram_brand_anchor_fixture_rerender.py PACKAGE_JSON GENERATED_DIR OUTPUT_DIR
No provider, image-generation, database, or Telegram code is imported or called.
"""
from __future__ import annotations

import io
import json
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

from services.instagram_content_package import InstagramContentPackage
from services.instagram_art_validator import validate_instagram_art
from services.instagram_format_director import ContentFormat
from services.instagram_platform_renderer import GENERATED_HERO_KEY, derive_asset_identity, render_instagram_carousel
from services.instagram_telegram_package_presenter import present_carousel


def _load_package(path: Path) -> InstagramContentPackage:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["content_format"] = ContentFormat(data["content_format"])
    if isinstance(data.get("created_at"), str):
        data["created_at"] = datetime.fromisoformat(data["created_at"])
    return InstagramContentPackage(**data)


def _contact_sheet(slides: list[Image.Image]) -> Image.Image:
    panel_w, panel_h, gap, margin, label_h = 324, 405, 18, 24, 42
    sheet = Image.new("RGB", (margin * 2 + panel_w * len(slides) + gap * (len(slides) - 1), margin * 2 + label_h + panel_h), (18, 18, 20))
    draw = ImageDraw.Draw(sheet)
    for i, slide in enumerate(slides):
        x = margin + i * (panel_w + gap)
        draw.text((x, margin + 8), f"SLIDE {i + 1}", fill=(255, 255, 255))
        sheet.paste(slide.resize((panel_w, panel_h), Image.Resampling.LANCZOS), (x, margin + label_h))
    return sheet


def main() -> None:
    package_path, generated_dir, output_dir = map(Path, sys.argv[1:4])
    package = _load_package(package_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    slide_assets = {}
    for i in range(package.slide_count or 0):
        path = generated_dir / f"asset_{i}.png"
        raw = path.read_bytes()
        slide_assets[i] = {GENERATED_HERO_KEY: (Image.open(io.BytesIO(raw)).convert("RGB"), derive_asset_identity(raw))}
    renders = render_instagram_carousel(package, slide_subject_assets=slide_assets)
    images = []
    for i, render in enumerate(renders, 1):
        path = output_dir / f"slide_{i:02d}.jpg"
        path.write_bytes(render.image_bytes)
        images.append(Image.open(io.BytesIO(render.image_bytes)).convert("RGB"))
    presentation = present_carousel(package, renders, version=1)
    art = validate_instagram_art(package, renders)
    (output_dir / "control_text.html").write_text(presentation.control_text, encoding="utf-8")
    (output_dir / "render_evidence.json").write_text(
        json.dumps([render.evidence.to_dict() for render in renders], ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (output_dir / "contact_sheet.jpg").write_bytes(_jpeg(_contact_sheet(images)))
    summary = {
        "slide_count": len(renders),
        "text_clipped": any(render.evidence.text_clipped for render in renders),
        "kage_marks": [render.evidence.visible_brand_mark_count for render in renders],
        "brand_anchor": renders[0].evidence.notes.get("product_brand_anchor"),
        "art_validation": {"passed": art.passed, "blocking_issues": art.blocking_issues},
        "control_text": presentation.control_text,
        "provider_calls": 0,
        "image_calls": 0,
        "telegram_sends": 0,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _jpeg(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=94)
    return out.getvalue()


if __name__ == "__main__":
    main()
