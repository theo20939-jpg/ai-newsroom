"""Offline re-render of a SAVED carousel (saved package + saved generated pictures) through the current composition behaviour.
0 provider calls, 0 image calls: only the deterministic renderer runs. Writes final slides, a contact sheet and a before/after sheet."""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.instagram_content_package import InstagramContentPackage  # noqa: E402
from services.instagram_format_director import ContentFormat  # noqa: E402
from services.instagram_platform_renderer import GENERATED_HERO_KEY, render_instagram_carousel  # noqa: E402


def _sheet(images: list[Image.Image], path: Path, *, w: int = 400) -> None:
    thumbs = [im.convert("RGB").resize((w, round(w * im.height / im.width))) for im in images]
    sheet = Image.new("RGB", (len(thumbs) * (w + 8) + 8, thumbs[0].height + 16), (24, 24, 24))
    for i, t in enumerate(thumbs):
        sheet.paste(t, (8 + i * (w + 8), 8))
    sheet.save(path)


def main(src: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    data = json.loads((src / "post" / "package.json").read_text(encoding="utf-8"))
    names = {f.name for f in dataclasses.fields(InstagramContentPackage)}
    data["content_format"] = ContentFormat(data["content_format"])
    package = InstagramContentPackage(**{k: v for k, v in data.items() if k in names})
    slide_assets = {}
    for i, _ in enumerate(package.media_plan["slides"]):
        image = Image.open(src / "post" / "generated" / f"asset_{i}.png").convert("RGB")
        slide_assets[i] = {GENERATED_HERO_KEY: (image, f"saved-generated-{i}")}
    results = render_instagram_carousel(package, slide_subject_assets=slide_assets)
    from services.instagram_art_validator import validate_instagram_art

    art = validate_instagram_art(package, results)
    after = []
    report = []
    for r in results:
        im = Image.open(__import__("io").BytesIO(r.image_bytes)).convert("RGB")
        i = r.evidence.slide_index
        im.save(out / f"slide_{i + 1:02d}.png")
        after.append(im)
        n = r.evidence.notes
        report.append({"slide": i, "size": im.size, "layout_variant": n.get("layout_variant"), "layout_signature": n.get("layout_signature"),
                       "text_clipped": r.evidence.text_clipped, "brand_marks": r.evidence.visible_brand_mark_count,
                       "adaptations": n.get("layout_adaptations")})
    before = [Image.open(p).convert("RGB") for p in sorted((src / "post" / "slides").glob("slide_*.png"))]
    _sheet(after, out / "contact_sheet_after.png")
    _sheet(before, out / "contact_sheet_before.png")
    both = [Image.open(out / "contact_sheet_before.png"), Image.open(out / "contact_sheet_after.png")]
    ba = Image.new("RGB", (both[0].width, both[0].height + both[1].height + 12), (255, 255, 255))
    ba.paste(both[0], (0, 0)); ba.paste(both[1], (0, both[0].height + 12))
    ba.save(out / "before_after.png")
    report.append({"art_validation": {"passed": art.passed, "blocking": art.blocking_issues, "warnings": art.warnings}})
    (out / "render_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
