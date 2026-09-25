"""Zero-cost re-render of a SAVED weekly-recap run: the saved package (the Creative Director's exact plan) + the saved per-story source
images -> the CURRENT renderer and art validator. No provider call, no network, no DB. Used to judge renderer changes on real output.
Usage: python scripts/_instagram_recap_rerender.py <run dir>/weekly_recap <out dir>
"""
from __future__ import annotations

import dataclasses
import json
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from services.instagram_art_validator import validate_instagram_art  # noqa: E402
from services.instagram_content_package import InstagramContentPackage  # noqa: E402
from services.instagram_creative_media import derive_image_identity  # noqa: E402
from services.instagram_format_director import ContentFormat  # noqa: E402
from services.instagram_platform_renderer import render_instagram_carousel  # noqa: E402


def main() -> None:
    run, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    data = json.loads((run / "package.json").read_text(encoding="utf-8"))
    fields = {f.name for f in dataclasses.fields(InstagramContentPackage)}
    data = {k: v for k, v in data.items() if k in fields}
    data["content_format"] = ContentFormat(data["content_format"])
    slides = data["media_plan"].get("slides") or []
    if data["media_plan"].get("content_archetype") == "news_recap" and slides and slides[-1].get("role") == "closing":
        # what the pipeline now does before packaging (services.instagram_recap_frames.with_recap_cta): the subscription end card
        from services.instagram_recap_frames import RECAP_CTA_BODY, RECAP_CTA_HEADLINE

        slides[-1] = {**slides[-1], "text": RECAP_CTA_HEADLINE, "body": RECAP_CTA_BODY}
    pkg = InstagramContentPackage(**data)
    vision = {v["subject_key"]: v for v in json.loads((run / "vision_verdicts.json").read_text(encoding="utf-8"))}
    subject_assets = {}
    for path in sorted((run / "story_media").glob("*.img")):
        image = Image.open(BytesIO(path.read_bytes()))
        image.load()
        subject_assets[path.stem] = (image, derive_image_identity(image))
    renders = render_instagram_carousel(pkg, subject_assets=subject_assets)
    for i, r in enumerate(renders, 1):
        (out / f"slide_{i:02d}.png").write_bytes(r.image_bytes)
    art = validate_instagram_art(pkg, renders)
    notes = [{k: r.evidence.notes.get(k) for k in ("arrangement", "media_scale_orientation", "media_scale_rescued_rejected_plan",
                                                   "recap_frame", "body_placement", "layout_variant")} | {"media": [m.get("subject") for m in r.evidence.notes.get("media_regions") or []]}
             for r in renders]
    summary = {"art_passed": art.passed, "blocking": list(art.blocking_issues), "warnings": list(art.warnings), "slides": notes,
               "unsuitable_for_vision": [k for k, v in vision.items() if not v["suitable"]]}
    (out / "rerender.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    ims = [Image.open(BytesIO(r.image_bytes)).convert("RGB") for r in renders]
    w, h = ims[0].size
    tw, th = int(w * 0.33), int(h * 0.33)
    rows = (len(ims) + 2) // 3
    sheet = Image.new("RGB", (tw * 3 + 40, th * rows + 10 * (rows + 1)), "white")
    for i, im in enumerate(ims):
        sheet.paste(im.resize((tw, th)), (10 + (i % 3) * (tw + 10), 10 + (i // 3) * (th + 10)))
    sheet.save(out / "contact_sheet.png")
    print(json.dumps({k: summary[k] for k in ("art_passed", "blocking")}, ensure_ascii=False))
    for i, n in enumerate(notes):
        print(i, n)


if __name__ == "__main__":
    main()
