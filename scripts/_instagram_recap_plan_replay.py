"""Zero-cost replay of a SAVED live weekly-recap Director plan that never reached render (e.g. rejected before the renderer):
the plan (calls/NN_director.json) goes through the CURRENT pre-render validation (including the unsuitable-hero demotion and the
coverage contract), the recap end card, the package's media plan and the CURRENT renderer + art gate - no provider, no network, no DB.
The package's non-media fields come from a template package of an earlier run of the same week (they do not affect the render).
Usage: python scripts/_instagram_recap_plan_replay.py <run>/weekly_recap <NN_director.json> <template package.json> <out dir>
"""
from __future__ import annotations

import dataclasses
import json
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

import services.instagram_creative_director as cd  # noqa: E402
from services.instagram_art_validator import validate_instagram_art  # noqa: E402
from services.instagram_automatic_trigger import _WEEKLY_RECAP  # noqa: E402
from services.instagram_content_package import InstagramContentPackage, _carousel_media_plan  # noqa: E402
from services.instagram_creative_media import derive_image_identity  # noqa: E402
from services.instagram_format_director import ContentFormat  # noqa: E402
from services.instagram_platform_renderer import render_instagram_carousel  # noqa: E402
from services.instagram_recap_frames import with_recap_cta  # noqa: E402


def main() -> None:
    run, call, template, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
    out.mkdir(parents=True, exist_ok=True)
    raw = json.loads((run / "calls" / call).read_text(encoding="utf-8"))["response"]["structured_output"]
    bundle = json.loads((run / "bundle.json").read_text(encoding="utf-8"))
    verdicts = json.loads((run / "vision_verdicts.json").read_text(encoding="utf-8"))
    assets = {}
    for path in sorted((run / "story_media").glob("*.img")):
        image = Image.open(BytesIO(path.read_bytes()))
        image.load()
        assets[path.stem] = (image, derive_image_identity(image))
    unsuitable = sorted(v["subject_key"] for v in verdicts if not v["suitable"])
    director_input = cd.CreativeDirectorInput(
        objective="saves", format="carousel", opportunity_summary="", allowed_evidence=list(bundle["evidence"]), locale="ru",
        external_news_entities_allowed=True, is_recap_bundle=True, recap_subjects=list(bundle["subjects"]), media_first=True,
        planned_format="WEEKLY_RECAP", planned_archetype=_WEEKLY_RECAP[1], recap_required_subjects=list(bundle["subjects"]),
        generated_media_available=False, available_media_subjects=tuple(sorted(assets)), unsuitable_media_subjects=tuple(unsuitable))
    diagnostics: list = []
    cd.set_raw_output_sink(lambda event, payload: diagnostics.append({"event": event, **payload}))
    try:
        outcome = cd._validate_carousel_output(raw, None, director_input=director_input, archetype=_WEEKLY_RECAP[1])
        result = {"pre_render": "PASS"}
    except Exception as exc:  # noqa: BLE001
        result = {"pre_render": f"{type(exc).__name__}: {str(exc)[:400]}"}
        outcome = None
    finally:
        cd.set_raw_output_sink(None)
    result["unsuitable"] = unsuitable
    result["demotions"] = [d for d in diagnostics if d["event"] == "unsuitable_hero_demoted"]
    if outcome is not None:
        creative = with_recap_cta(outcome.carousel)
        _caption, _cta, _hook, media_plan = _carousel_media_plan(creative)
        data = json.loads(template.read_text(encoding="utf-8"))
        data = {k: v for k, v in data.items() if k in {f.name for f in dataclasses.fields(InstagramContentPackage)}}
        data["content_format"] = ContentFormat(data["content_format"])
        data["media_plan"] = {**data["media_plan"], **media_plan, "content_archetype": _WEEKLY_RECAP[1], "media_first": True}
        data["caption"] = creative.final_caption or data["caption"]
        pkg = InstagramContentPackage(**data)
        renders = render_instagram_carousel(pkg, subject_assets=assets)
        for i, r in enumerate(renders, 1):
            (out / f"slide_{i:02d}.png").write_bytes(r.image_bytes)
        art = validate_instagram_art(pkg, renders)
        result.update({"slides": len(renders), "art_passed": art.passed, "art_blocking": list(art.blocking_issues),
                       "per_slide": [{"role": s.role, "media_subject": s.media_subject,
                                      "media": [m.get("subject") for m in r.evidence.notes.get("media_regions") or []],
                                      "editorial_variant": r.evidence.notes.get("editorial_variant"),
                                      "hero_zone_used": bool(r.evidence.notes.get("recap_frame")) and not r.evidence.notes.get("editorial_variant")}
                                     for s, r in zip(creative.slides, renders)]})
        ims = [Image.open(BytesIO(r.image_bytes)).convert("RGB") for r in renders]
        w, h = ims[0].size
        tw, th = int(w * 0.33), int(h * 0.33)
        sheet = Image.new("RGB", (tw * 3 + 40, th * ((len(ims) + 2) // 3) + 10 * ((len(ims) + 2) // 3 + 1)), "white")
        for i, im in enumerate(ims):
            sheet.paste(im.resize((tw, th)), (10 + (i % 3) * (tw + 10), 10 + (i // 3) * (th + 10)))
        sheet.save(out / "contact_sheet.png")
    (out / "replay.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: result.get(k) for k in ("pre_render", "unsuitable", "demotions", "slides", "art_passed", "art_blocking")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
