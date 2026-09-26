"""Zero-cost acceptance for the SINGLE / REEL media-cleanliness contract (a source image that exists is not one that must be used).
Fixtures are the REAL launch artifacts: the Habr share card (live Single), the vc.ru share card (live Reel), the live packages built from
them, and a real recap photograph whose live vision verdict was 'photograph, suitable'. No provider, no network, no DB: the vision step
is the real `check_primary_suitability` decision code with its model call replaced by a fixture answer (recorded where one exists; the
vc.ru card never went through vision live, so its fixture answer is stated as such in the output).
Usage: python scripts/_instagram_daily_media_acceptance.py <out dir>
"""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw  # noqa: E402

import services.instagram_automatic_trigger as trigger  # noqa: E402
import services.instagram_source_suitability as suit  # noqa: E402
from integrations.prompts.file_repository import FilePromptRepository  # noqa: E402
from schemas.instagram_creative import InstagramReelCreative, InstagramSingleCreative  # noqa: E402
from services.instagram_art_validator import validate_instagram_art  # noqa: E402
from services.instagram_content_package import InstagramContentPackage  # noqa: E402
from services.instagram_format_director import ContentFormat  # noqa: E402
from services.instagram_platform_renderer import InstagramRenderResult, render_instagram_feed_image, render_instagram_reel_cover  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "artifacts/instagram_feed_product/last_three_blockers_20260926"
IMAGES = LIVE / "daily/_image_storage/images"
HABR = IMAGES / "a5/a5b7675f1861cf31741262705fffda1abc1d31efcf413115287118c75f8fe2b6.png"
VCRU = IMAGES / "e8/e893b6b5bfdf52b8d678f2c428ecdf45f0ac05c4a4952e50166d5297cb88f34c.jpg"
PHOTO = LIVE / "recap/weekly_recap/story_media/story_4.img"
SINGLE = LIVE / "daily/2026-08-05_2_meme_trend"
REEL = LIVE / "daily/2026-08-10_2_meme_trend"

# the vision model's structured answer per fixture image (what `_call_vision` would have returned)
_ANSWERS = {
    "vcru": ({"image_kind": "article_or_news_card", "baked_in_text_prominent": True, "reason": "FIXTURE: vc.ru share card, headline over photo"},
             "fixture - this card never went through vision live"),
    "photo": ({"image_kind": "photograph", "baked_in_text_prominent": False, "reason": "recorded live verdict (recap story_4)"},
              "recorded live verdict: recap vision_verdicts.json story_4"),
}


def _image(path: Path) -> Image.Image:
    with Image.open(path) as decoded:
        return decoded.convert("RGB")


def _package(run: Path) -> InstagramContentPackage:
    data = json.loads((run / "package.json").read_text(encoding="utf-8"))
    data = {k: v for k, v in data.items() if k in {f.name for f in dataclasses.fields(InstagramContentPackage)}}
    data["content_format"] = ContentFormat(data["content_format"])
    return InstagramContentPackage(**data)


def _creative(run: Path, model):
    return model.model_validate(json.loads((run / "calls/02_director.json").read_text(encoding="utf-8"))["response"]["structured_output"])


async def _select(images: list[tuple[str, Image.Image]]) -> dict:
    """The REAL selection code; only the model call answers from the fixture table."""
    order = iter(name for name, _ in images)
    calls: list[str] = []

    async def fixture_vision(_gateway, _request, _runtime):
        name = next(n for n in order if n in _ANSWERS)  # deterministic-flat images are never sent to vision
        calls.append(name)
        return SimpleNamespace(error=None, call=None, response=SimpleNamespace(structured_output=_ANSWERS[name][0]))

    real, suit._call_vision = suit._call_vision, fixture_vision
    try:
        candidates = [(img, SimpleNamespace(id=f"fixture-{name}"), 0) for name, img in images]
        image, _candidate, _len, record = await trigger._select_daily_source_media(
            gateway=object(), prompt_repository=FilePromptRepository(ROOT / "prompts"), candidates=candidates)
    finally:
        suit._call_vision = real
    record["vision_fixture_calls"] = [{"image": n, "answer_origin": _ANSWERS[n][1]} for n in calls]
    record["selected_image"] = next((n for n, img in images if img is image), None)
    return record


def _demoted_package(pkg: InstagramContentPackage, creative, selection: dict) -> tuple[InstagramContentPackage, bool]:
    """What the trigger now builds for a rejected source: the demoted plan, no source ref, the decision on the package."""
    demoted, changed = trigger._demote_source_plan(creative)
    plan = demoted.creative_execution_plan.model_dump()
    media_plan = copy.deepcopy(pkg.media_plan)
    media_plan["creative_execution_plan"] = {**media_plan.get("creative_execution_plan", {}), **plan}
    media_plan["media_execution"] = {**media_plan.get("media_execution", {}), "strategy": "typographic", "status": "typographic",
                                     "assets": [{"asset_key": "primary", "media_mode": "TYPOGRAPHIC", "status": "typographic"}]}
    media_plan["source_media_suitability"] = {**selection, **({"plan_demoted_to_typographic": True} if changed else {})}
    return dataclasses.replace(pkg, source_image_ref=None, media_candidate_id=None, media_plan=media_plan), changed


def _gate(pkg, renders) -> dict:
    art = validate_instagram_art(pkg, renders)
    return {"passed": art.passed, "blocking": list(art.blocking_issues)}


def _save(out: Path, name: str, render: InstagramRenderResult) -> str:
    (out / f"{name}.png").write_bytes(render.image_bytes)
    return f"{name}.png"


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    habr, vcru, photo = _image(HABR), _image(VCRU), _image(PHOTO)
    report: dict = {"provider_calls": 0}

    # 1 + 2 + 3 + 4: the Habr Single
    live_single = _package(SINGLE)
    live_render = render_instagram_feed_image(live_single, source_image=habr)
    report["1_single_live_failure_reproduced"] = _gate(live_single, [live_render])
    habr_selection = asyncio.run(_select([("habr", habr)]))
    report["2_habr_classified"] = habr_selection
    report["2_director_media_note"] = trigger._daily_media_note(habr_selection)
    single_pkg, demoted = _demoted_package(live_single, _creative(SINGLE, InstagramSingleCreative), habr_selection)
    single_render = render_instagram_feed_image(single_pkg, source_image=habr)  # handed the card anyway: the renderer must refuse it
    report["3_single_designed_without_card"] = {"plan_demoted": demoted, "file": _save(out, "single_habr_fixed", single_render),
                                               "treatment": single_render.evidence.source_image_treatment,
                                               "focal": single_render.evidence.notes.get("typographic_focal"),
                                               "designed_typographic": single_render.evidence.notes.get("designed_typographic")}
    report["4_single_gate"] = _gate(single_pkg, [single_render])

    # 5 + 6 + 7: the vc.ru Reel
    live_reel = _package(REEL)
    live_reel_render = render_instagram_reel_cover(live_reel, source_image=vcru)
    report["5_reel_live_cover_reproduced"] = {"file": _save(out, "reel_vcru_before", live_reel_render),
                                              "treatment": live_reel_render.evidence.source_image_treatment,
                                              "gate_without_suitability_record": _gate(live_reel, [live_reel_render])}
    vcru_selection = asyncio.run(_select([("vcru", vcru)]))
    report["6_vcru_classified"] = vcru_selection
    reel_pkg, reel_demoted = _demoted_package(live_reel, _creative(REEL, InstagramReelCreative), vcru_selection)
    reel_render = render_instagram_reel_cover(reel_pkg, source_image=vcru)
    report["6_share_card_cannot_be_the_hero"] = {"treatment": reel_render.evidence.source_image_treatment,
                                                 "layout_variant": reel_render.evidence.notes.get("layout_variant")}
    raw_clipped = dataclasses.replace(live_reel, media_plan={**live_reel.media_plan, "source_media_suitability": vcru_selection})
    report["10_clipped_embedded_text_still_fails"] = _gate(raw_clipped, [live_reel_render])
    report["7_reel_fallback_cover"] = {"plan_demoted": reel_demoted, "file": _save(out, "reel_vcru_fixed", reel_render),
                                       "designed_typographic": reel_render.evidence.notes.get("designed_typographic"),
                                       "gate": _gate(reel_pkg, [reel_render])}

    # 8: a suitable photograph stays eligible - and wins over an unsuitable first candidate
    photo_selection = asyncio.run(_select([("photo", photo)]))
    mixed_selection = asyncio.run(_select([("habr", habr), ("photo", photo)]))
    report["8_suitable_photo_eligible"] = {"alone": photo_selection, "after_an_unsuitable_card": mixed_selection}
    approved = dataclasses.replace(live_single, media_plan={**live_single.media_plan, "source_media_suitability": photo_selection,
                                                            "creative_execution_plan": {**live_single.media_plan["creative_execution_plan"],
                                                                                        "focal_point": "фото", "visual_treatment": "hero",
                                                                                        "composition_direction": "full hero"}})
    photo_render = render_instagram_feed_image(approved, source_image=photo)
    report["8_suitable_photo_single"] = {"file": _save(out, "single_suitable_photo", photo_render),
                                         "treatment": photo_render.evidence.source_image_treatment, "gate": _gate(approved, [photo_render])}

    # 9: a suitable, SELECTED image that does not reach the pixels still fails (Single and Reel)
    missing_single = render_instagram_feed_image(approved, source_image=None)
    approved_reel = dataclasses.replace(live_reel, media_plan={**live_reel.media_plan, "source_media_suitability": photo_selection})
    missing_reel = render_instagram_reel_cover(approved_reel, source_image=None)
    report["9_selected_media_missing"] = {"single": _gate(approved, [missing_single]), "reel": _gate(approved_reel, [missing_reel])}

    # plain text dump: omission is allowed only for a designed composition
    legacy_plan = {k: v for k, v in single_pkg.media_plan.items() if k != "creative_execution_plan"}
    dump_pkg = dataclasses.replace(single_pkg, media_plan=legacy_plan)
    dump = render_instagram_feed_image(dump_pkg, source_image=None)
    report["plain_text_dump_still_fails"] = {"layout_variant": dump.evidence.notes.get("layout_variant"), "file": _save(out, "single_plain_dump", dump),
                                             "gate": _gate(dump_pkg, [dump])}

    # 11: the split panel is the canonical KAGE violet
    from services.instagram_kage_brand import ACCENT
    from services.instagram_platform_renderer import render_instagram_carousel

    carousel = _package(ROOT / "artifacts/instagram_feed_product/launch_remediation_20260926/daily/2026-08-05_2_meme_trend")
    slides = render_instagram_carousel(carousel, subject_assets={})
    split = next(r for r in slides if r.evidence.notes.get("editorial_variant") == "split")
    split_img = Image.open(BytesIO(split.image_bytes)).convert("RGB")
    pixel = split_img.getpixel((split_img.width // 2, split_img.height - 60))
    _save(out, "split_panel", split)
    report["11_split_panel"] = {"pixel_rgb": list(pixel), "kage_accent": list(ACCENT), "violet": tuple(pixel) == tuple(ACCENT)}

    names = ["single_habr_fixed", "single_suitable_photo", "reel_vcru_before", "reel_vcru_fixed", "single_plain_dump", "split_panel"]
    ims = [Image.open(out / f"{n}.png").convert("RGB") for n in names]
    th = 540
    sheet = Image.new("RGB", (sum(round(im.width * th / im.height) + 12 for im in ims) + 12, th + 44), "white")
    x, draw = 12, ImageDraw.Draw(sheet)
    for n, im in zip(names, ims):
        w = round(im.width * th / im.height)
        sheet.paste(im.resize((w, th)), (x, 36))
        draw.text((x, 12), n, fill="black")
        x += w + 12
    sheet.save(out / "contact_sheet.png")
    (out / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    summary = {k: (v.get("passed") if isinstance(v, dict) and "passed" in v else v.get("gate", {}).get("passed") if isinstance(v, dict) and "gate" in v else None)
               for k, v in report.items()}
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
